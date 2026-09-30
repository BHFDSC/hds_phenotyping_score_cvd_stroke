# Databricks notebook source
# MAGIC %md
# MAGIC ## 1. Set up

# COMMAND ----------

# MAGIC %run "./project_config"

# COMMAND ----------

# MAGIC %run "./hds_functions"

# COMMAND ----------

from functions import load_table, save_table, read_csv_file, write_csv_file, map_column_values
import re
from pyspark.sql import functions as f
import pyspark.sql.types as t
from pyspark.sql.window import Window
import pandas as pd
from functools import reduce

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Study dates

# COMMAND ----------

# Study dates - input dates in the form yyyy-mm-dd
study_start_date = '2022-01-01'
study_end_date = '2025-12-31'

print(f"study_start_date: {study_start_date}")
print(f"study_end_date: {study_end_date}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Study age range

# COMMAND ----------

# user to specifiy the minimum nad maximum age ranges acceptable in the cohort
min_age = '18'
max_age = '120'

print(f"min_age: {min_age}")
print(f"max_age: {max_age}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Stroke ICD-10 codes - based on subtype map

# COMMAND ----------

# Define the ICD-10 stroke codes based on sybtypes of stroke required - can be edited to include related codes such as subdural haemorrhage (I62) or TIA (G45)
# can enter 3 or 4 chaqracter code list but must ensure that columns selected below for positions in HES APC refelct this decision 
# where 3 level codes only needed that list can reflect this e.g. include code I60 only for catch all of I60 codes
# where 4 level codes needed (and diag_4 columns selected below) please lsit all codes relevant and where you would like all codes related to a code type then please also include the three level catch all code e.g. I60, I601, I602, I603, I604, I605, I606, I608, I609. 
# Note trailing X have been removed from data as well as '.' i.e. code 'I60X' is 'I60' in NHS SDE HES APC health recods and 'I60.1' is 'I601' - codes provided here must reflect this
# Default verison of the algotihm uses 3 character ICD-10 codes I60, I61, I63, I64
stroke_subtype_map = {
    "ischaemic": ["I63"],
    "haemorrhagic": ["I60", "I61"], 
    "unknown": ["I64"]
}
print("stroke subtypes:")
for col in stroke_subtype_map:
    print(col)

# takes the subtypes above and generates the lsit of ICD-10 codes to be used by the algorithm
stroke_codes = tuple({code for codes in stroke_subtype_map.values() for code in codes})


print("stroke codes:")
for col in stroke_codes:
    print(col)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Position of clinical codes for record type (HES APC, ONS Deaths) and for first or subsequent stroke

# COMMAND ----------

# MAGIC %md
# MAGIC ### 4.1 HES APC positions

# COMMAND ----------

# HES APC - selecting position columns from HES 
# Depending on the codelist (i.e. whether the codelist contains only 3 charcter codes, or also 4 charcater codes) the positions input below can be diag_4_01, diag_4_02 etc up to diag_04_20 OR diag_3_01, diag_3_02 etc up to diag_3_20
# The below code set up assuming columns names diag_3_01, diag_3_02 etc where diag_3_01 is the first position. This can be edited as necessary. 
# NOTE if using 4 character code lists select columns diag_04_01 etc etc.

# specify position columns accepted for a FIRST stroke in HES
code_positions_first_stroke_hes_apc = [f"diag_3_{i:02d}" for i in range(1, 21)] # manually edit to represent the range of positions preferred for FIRST stroke, default version specifies ANY position in HES APC for first stroke i.e. diag_3_01 to diag_3_20. 
# Note - input: range(first digit required, stops before this digit (i.e. if max required is 20 then set to 21))
print("HES- positions FIRST stroke:")
for col in code_positions_first_stroke_hes_apc:
    print(col)

# specify position columns accepted for a SUBSEQUENT stroke in HES 
code_positions_subsequent_stroke_hes_apc = [f"diag_3_{i:02d}" for i in range(1, 2)] # manually edit to represent the range of positions for SUBSEQUENT stroke preferred, default version specifies FIRST position only in HES APC for subsequent stroke i.e. diag_3_01 to diag_3_01. 
# Note - inpu:  range(first digit required, stops before this digit (i.e. if max required is 1 position then set to 2))

print("HES- positions SUBSEQUENT stroke:")
for col in code_positions_subsequent_stroke_hes_apc:
    print(col)



# COMMAND ----------

# MAGIC %md
# MAGIC ### 4.2 ONS Deaths positions

# COMMAND ----------

# ONS deaths ICD10 charcter length
#user must specifiy whteher they are using 3 or 4 charcter ICD10 codes in their code list
# "3" = use only first 3 characters
# "4" = use only first 4 characters
icd10_code_length_deaths = 3   # or 4

# COMMAND ----------

# ONS deaths

# specify position columns accepted for a FIRST stroke in ONS deaths
# this is the case where no stroke has been previously recorded in HES APC and the first record of a stroke appears in the death records
code_positions_first_stroke_deaths = (
    ["underlying_cod"]
    + [f"cod_mentioned_{i}" for i in range(1, 16)]
)
# manually edit to represent the range of positions preferred, default version specifies ANY position in deaths for first stroke i.e.underlying_cod (underlying cause of death) to cod_mentioned_15 (secondary cause of death 15). 
# Note - input: range(first digit required, stops before this digit (i.e. if max required is 20 then set to 21))
print("Deaths- positions FIRST stroke:")
for col in code_positions_first_stroke_deaths:
    print(col)

# specify position columns accepted for a SUBSEQUENT stroke in ONS deaths
# this is the case where there has been a stroke has been previously recorded in HES APC and the stroke reorded in the deaths records would be counted as a seperate subsequent stroke
code_positions_subsequent_stroke_deaths = (
    ["underlying_cod"]
    + [f"cod_mentioned_{i}" for i in range(0, 0)]
)
# manually edit to represent the range of positions preferred, default version specifies FIRST position in deaths for first stroke i.e.underlying_cod (underlying cause of death) only, therefore for secondary causes of death 'cod_mentioned_' the values are set to 0.
#  Note - input: range(first digit required, stops before this digit (i.e. if max required is 20 then et to 21)

print("Deaths- positions SUBSEQUENT stroke:")
for col in code_positions_subsequent_stroke_deaths:
    print(col)



# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Washout periods

# COMMAND ----------

# MAGIC %md
# MAGIC ###  5.1 Washout period for any stroke in HES-APC
# MAGIC Applied in cases where researcher would like to exclude ANY susbequent stroke recorded in HES APC, which has occured within a specified time frame (often 30 days post prior stroke). <br> This is based on stroke epidates (subsequent stroke epidate - first stroke epidate > washout) 

# COMMAND ----------

washout_between_strokes = '30' # default algorithm applies a 30 day washout period between stroke events
# set to '0' if you do not want to apply a washout

print(f"Washout period in days between strokes in HES: {washout_between_strokes}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### 5.2 Washout period between stroke deaths and piror HES stroke
# MAGIC Applied in cases where the researcher would like to exclude/not count stroke deaths events in the case where a HES APC stroke record exists within the specified time period e.g. 30 days (date_of_death - epistart/stroke_date > 30)
# MAGIC

# COMMAND ----------

washout_between_death_and_hes_stroke = '30' # default algorithm assumes a wahsout of 30 days, not counting as a new stroke event any records of stroke death which have occured within 30 days of a HES APC stroke event. It assumes that this death stroke event is the same as the HES event and has been captured by the HES APC portion of the algorithm
# set to '0' if you do not want to apply a washout

print(f"Washout period in days between stroke death and a prior stroke in HES: {washout_between_death_and_hes_stroke }")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Fatal stroke definition
# MAGIC Set the timeframe for a stroke in HES APC being defined as a fatal stroke by the algorithms outputs e.g. stroke events which are followed by a death from any cause within 30 days are often referred to as fatal stroke 

# COMMAND ----------

fatal_stroke_definition = '30' # default algorithm specifies that any stroke event in HES APC in which a death is recorded in the death records (for any cuase) within 30 days, is recorded as a fatal stroke
# set to '0' if you do not want classify as fatal any HES APC strokes


print(f"Fatal stroke classified in days between stroke in HES and death from any cause: {fatal_stroke_definition}")