# Databricks notebook source
# MAGIC %md
# MAGIC ## 1. Setup

# COMMAND ----------

# MAGIC %run "./project_config"

# COMMAND ----------

# %run "./hds_functions"

# COMMAND ----------

# MAGIC %run "./parameters"

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
# MAGIC ## 2. Curate deaths data

# COMMAND ----------

deaths_cleaned = load_table('ons_deaths_cleaned')
cohort = load_table('cohort')

# extracing the columns required based of specified code positions as outline in parameters notebook - and concatenating them
death_columns_all_positions= (code_positions_first_stroke_deaths + code_positions_subsequent_stroke_deaths) 
death_columns_all_positions=  list(dict.fromkeys(death_columns_all_positions))# deduplicating list

# Trim the ICD10 codes in the relevant columns to length set out in parameters notebook (i.e. 3 or 4 characters in length)
icd10_code_length_deaths = int(icd10_code_length_deaths) # ensure that the parameter icd10_code_length_deaths is interger

# loop through the columns in death_columns_all_positions and truncate the code length to value sepcified in icd10_code_length_deaths
for col in death_columns_all_positions: 
    deaths_cleaned= deaths_cleaned.withColumn(
        col,
        f.when(
            f.col(col).isNotNull(),
            f.col(col).substr(1, icd10_code_length_deaths)
        ).otherwise(None)
    )

# inner join cohort to deaths_cleaned 
deaths_stroke = (
    deaths_cleaned
    .select(
        'person_id','date_of_death',
        f.array(death_columns_all_positions).alias('death_array_any'),
        f.array(code_positions_first_stroke_deaths).alias('death_array_first_stroke_positions'),
        f.array(code_positions_subsequent_stroke_deaths).alias('death_array_subsequent_stroke_positions'),
    )
    .filter(f"(date_of_death >= '{study_start_date}') AND (date_of_death <= '{study_end_date}') AND (person_id IS NOT NULL)") # don't need start and end dates for now - filter at cohort level? 
    .join(
        cohort
        .select('person_id'),
        on = 'person_id', how = 'inner'
    )
    )


# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Create DF of non stroke deaths and DF of stroke deaths

# COMMAND ----------

# flag episodes with stroke codes of interest and create flag at person_id level of whether they have had a stroke death during the time period

win_id = Window.partitionBy('person_id')

deaths_stroke_prep = (
   deaths_stroke
    .withColumn(
        'death_stroke_any',
        f.when(
            f.size(f.array_intersect(f.col('death_array_any'),f.array(*[f.lit(c) for c in stroke_codes])))>0,
            f.lit(True)
        ).otherwise(f.lit(False))
    )    
    .withColumn(
        'death_first_stroke_positions',
        f.when(
            f.size(f.array_intersect(f.col('death_array_first_stroke_positions'),f.array(*[f.lit(c) for c in stroke_codes])))>0,
            f.lit(True)
        ).otherwise(f.lit(False))
    )   
    .withColumn(
        'death_subsequent_stroke_positions',
        f.when(
            f.size(f.array_intersect(f.col('death_array_subsequent_stroke_positions'),f.array(*[f.lit(c) for c in stroke_codes])))>0,
            f.lit(True)
        ).otherwise(f.lit(False))
    )   
    .withColumn(
        'individual_with_stroke_death',
        f.max('death_stroke_any').over(win_id)
    )
)

# df of people with no stroke codes during time period
deaths_algo_non_stroke_patients = (
    deaths_stroke_prep
    .filter("individual_with_stroke_death = False")
    .withColumn('qualify', f.lit(False))
    .withColumn('terminal_node', f.lit(0))
    .withColumn('terminal_node_description', f.lit('T0: individual with no stroke ICD-10 code ever in the death records in positions relevant to first OR subsequent stroke'))
)

save_table(df = deaths_algo_non_stroke_patients, table = 'deaths_algo_non_stroke_patients')

# df of people with at least one stroke code in ONS deaths in a position releveant to first OR subsequent stroke
deaths_algo_stroke_patients = (
    deaths_stroke_prep
    .filter("individual_with_stroke_death = True")
)

save_table(df = deaths_algo_stroke_patients, table = 'deaths_algo_stroke_patients')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Curate stroke subtypes

# COMMAND ----------

# Add subtypes of stroke to death df

deaths_algo_stroke_patients =  load_table('deaths_algo_stroke_patients')

# Extract FIRST stroke code
# filter to only stroke_codes in deaths_array_any to get the estroke codes per episode
def stroke_filter_expr(array_col, stroke_codes):
    like_expr = " OR ".join([f"x LIKE '{c}%'" for c in stroke_codes])
    return f.expr(f"filter({array_col}, x -> {like_expr})")


deaths_algo_stroke_patients = deaths_algo_stroke_patients.withColumn(
    "stroke_codes_in_death_episode",
    stroke_filter_expr("death_array_any", stroke_codes)
)

# take the first stroke code per episode only
deaths_algo_stroke_patients = deaths_algo_stroke_patients.withColumn(
    "first_stroke_code_death",
    f.when(
        f.size("stroke_codes_in_death_episode") > 0,
        f.col("stroke_codes_in_death_episode")[0]
    )
)


# Episode-level subtype - taking only first mentioned stroke per episode add label of subtype based on this irst stoke ICD10 code
def prefix_match(col, prefixes):
    conditions = [f.col(col).startswith(p) for p in prefixes]
    return reduce(lambda a, b: a | b, conditions)

deaths_algo_stroke_patients = deaths_algo_stroke_patients.withColumn("stroke_type_death_episode", f.lit(None))

for subtype, prefixes in stroke_subtype_map.items():
    deaths_algo_stroke_patients = deaths_algo_stroke_patients.withColumn(
        "stroke_type_death_episode",
        f.when(prefix_match("first_stroke_code_death", prefixes), f.lit(subtype))
         .otherwise(f.col("stroke_type_death_episode"))
    )


# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Flag in hospital death

# COMMAND ----------

hes_apc_cleaned = load_table('hes_apc_cleaned')

# inner join hes_apc_cleaned and flag detah within 1 day of disharge, discharge to death, in hosp death, death_before_hosp_death, 

in_hospital_death = (
    deaths_algo_stroke_patients
    .select('person_id', 'date_of_death')
    .join(
        hes_apc_cleaned
        .select('epikey', 'person_id', 'disdate', 'dismeth', 'disdest', 'epiend'),
        how = 'inner',
        on = ['person_id']
    )
    .withColumn(
        'death_within_1_day_of_discharge',
        f.when(
            f.abs(f.datediff('date_of_death', 'disdate')) <= f.lit(1),
            f.lit(True)
        )
        .otherwise(False)
    )
    .withColumn(
        'discharge_to_death',
        f.when(
            f.expr("(dismeth = '4') OR (disdest = '79')"),
            f.lit(True)
        )
        .otherwise(False)
    )
    .withColumn(
        'death_before_hosp_death', # column to flag cases where the date_of_detah is before hosp epiend or disdate, allows these to be flagged as in hosp death and not counted by the death algorithm 
        f.when(
           (f.col('discharge_to_death') == True) & 
           (f.col('date_of_death') < f.greatest('epiend', 'disdate')),
           f.lit(True)
        ).otherwise(f.lit(False))
        )
   .withColumn(
        'in_hospital_death',
        f.expr(
            "(death_within_1_day_of_discharge AND discharge_to_death) OR (death_before_hosp_death AND discharge_to_death)"
        )
    )
    .groupBy('person_id')
    .agg(
        f.max('in_hospital_death').alias('in_hospital_death')
    )
)


# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Curate washout period and prior hes stroke flag

# COMMAND ----------

hes_apc_algo_stroke_patients = load_table('hes_apc_algo_stroke_patients')

# ensure parameter is integer
washout_between_death_and_hes_stroke = int(washout_between_death_and_hes_stroke)

prior_hes_stroke = (
    deaths_algo_stroke_patients
    .select('person_id', 'date_of_death')
    .join(
        hes_apc_algo_stroke_patients
        .filter("qualify")
        .select('person_id', 'stroke_date'),
        on='person_id',
        how='left'
    )
    .withColumn(
        "days_between",
        f.datediff("date_of_death", "stroke_date")
    )
    .withColumn(
        "stroke_within_washout",
        f.when(
            (washout_between_death_and_hes_stroke > 0) &
            (f.col("days_between") >= 0) &
            (f.col("days_between") < washout_between_death_and_hes_stroke),
            True
        ).otherwise(False)
    )
    .groupBy('person_id')
    .agg(
        f.max("stroke_within_washout").alias("stroke_within_washout"),
        f.max(f.when(f.col("stroke_date").isNotNull(), True).otherwise(False)).alias("prior_qualifying_hes_stroke")
    )
)


# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Join hospital death, prior hes stroke, and washout to deaths cohort

# COMMAND ----------

# join in_hospital_detah and prior_hes_stroke to deaths_stroke
deaths_algo_stroke_patients= (
    deaths_algo_stroke_patients
    .join(in_hospital_death, on='person_id', how='left')
    .join(prior_hes_stroke, on='person_id', how='left')
    .fillna(False, subset=['in_hospital_death','stroke_within_washout','prior_qualifying_hes_stroke'])
)


# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Flag qualifying stroke death

# COMMAND ----------

deaths_algo_stroke_patients = (deaths_algo_stroke_patients
.withColumn(
    "qualify",
    f.when(
        (f.col("in_hospital_death") == False) &
        (f.col("stroke_within_washout") == False) &
        (
            ((f.col("prior_qualifying_hes_stroke") == False) & (f.col("death_first_stroke_positions") == True)) |
            ((f.col("prior_qualifying_hes_stroke") == True) & (f.col("death_subsequent_stroke_positions") == True))
        ),
        True
    ).otherwise(False)
)
)


deaths_algo_stroke_patients = (deaths_algo_stroke_patients
.withColumn(
    "stroke_date",
    f.col("date_of_death")
)
)


save_table(df = deaths_algo_stroke_patients, table = 'deaths_algo_stroke_patients')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Flowchart

# COMMAND ----------

# Create flowchart of algorithm 

flowchart_schema = {
    'node_d01': {
        'parent_node': None,
        'expression': 'TRUE',
        'description': "D1: Is there a corresponding record in HES-APC  documenting an in-hospital death  (defined as discharge date within 1 day of the date of death; and  discharge method of '4' , or discharge destination of '79' )"
    },
    'node_t01': {
        'parent_node': 'node_d01',
        'expression': '(in_hospital_death = TRUE)',
        'description': 'T1: Excluded as event will have been captured in HES-APC as in hospital death'
    },
    'node_d02': {
        'parent_node': 'node_d01',
        'expression': '(in_hospital_death = FALSE)',
        'description': 'D2: Is there a recorded qualifying stroke event in HES-APC within the specified washout period? (as specified by user in the parameters notebook as object washout_between_death _and_hes_stroke)'
    },
    'node_t02': {
        'parent_node': 'node_d02',
        'expression': '(stroke_within_washout = TRUE)',
        'description': 'T2: Excluded as death within washout period and assumed to relate to previously recorded stroke.'
    },
    'node_d03': {
        'parent_node': 'node_d02',
        'expression': '(stroke_within_washout = FALSE)',
        'description': 'D3: Is there ANY qualifying stroke event recorded in HES-APC prior to death?'
    },
    'node_d04': {
        'parent_node': 'node_d03',
        'expression': '(prior_qualifying_hes_stroke = FALSE)',
        'description': 'D4: Is the stroke code in a valid position for FIRST stroke death? (as specified by user in parameters notebook as object code_positions_first stroke_death)'
    },
    'node_t03': {
        'parent_node': 'node_d04',
        'expression': '(death_first_stroke_positions = FALSE)',
        'description': 'T3: Not a stroke  event - not in valid position for first stroke'
    },
    'node_t04': {
        'parent_node': 'node_d04',
        'expression': '(death_first_stroke_positions = TRUE)',
        'description': 'T4: First stroke event'
    },
    'node_d05': {
        'parent_node': 'node_d03',
        'expression': '(prior_qualifying_hes_stroke = TRUE)',
        'description': 'D5: Is the stroke code in a valid position for SUBSEQUENT stroke death? (as specified by user in parameters notebook as object code_positions_subsequent stroke_death)'
    },
    'node_t05': {
        'parent_node': 'node_d05',
        'expression': '(death_subsequent_stroke_positions = FALSE)',
        'description': 'T5: Not a stroke   - not in valid position for subsequent stroke'
    },
    'node_t06': {
        'parent_node': 'node_d05',
        'expression': '(death_subsequent_stroke_positions = TRUE)',
        'description': 'T6: Subsequent stroke event'
    }
}

node_names = keys_list = list(flowchart_schema.keys())


deaths_stroke = load_table('deaths_algo_stroke_patients')

for node_name, node_features in flowchart_schema.items():

    if node_features['parent_node'] is None:
        deaths_stroke = (
            deaths_stroke
            .withColumn(node_name, f.expr(node_features['expression']))
        )
    
    else:
        deaths_stroke = (
            deaths_stroke
            .withColumn(node_name, f.col(node_features['parent_node']) & f.expr(node_features['expression']))
        )

flowchart_long = (
    deaths_stroke
    .withColumn('row_id', f.row_number().over(Window.orderBy(f.lit(1))))
    .select(['row_id', 'person_id', *node_names])
    .unpivot(
        ids = ['row_id', 'person_id'],
        values = node_names,
        variableColumnName = 'node_id',
        valueColumnName = 'membership'
    )
)

# Create two separate dictionaries
dict_parent_node = {key: value['parent_node'] for key, value in flowchart_schema.items()}
dict_description = {key: value['description'] for key, value in flowchart_schema.items()}

flowchart_summary = (
    flowchart_long
    .groupBy('node_id') \
    .agg(
        f.count(f.when(f.expr("membership = TRUE"), f.lit(1))).alias('n'),
        f.countDistinct(f.when(f.expr("membership = TRUE"), f.col('person_id'))).alias('n_id')
    )
    .transform(
        map_column_values,
        map_dict = dict_parent_node,
        column = 'node_id',
        new_column = 'parent_node'
    )
    .transform(
        map_column_values,
        map_dict = dict_description,
        column = 'node_id',
        new_column = 'description'
    )
)

write_csv_file(df = flowchart_summary, path = './outputs/flowchart_stroke_deaths_default.csv')


flowchart_summary_sdc = (
    flowchart_summary
    .withColumn('n', f.round(f.col('n')/10, 0)*10)
    .withColumn('n_id', f.round(f.col('n_id')/10, 0)*10)
)

write_csv_file(df = flowchart_summary_sdc, path = './outputs/flowchart_stroke_deaths_default_sdc.csv')