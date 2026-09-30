# SCORE-CVD: Stroke algorithm
# User-defined parameters
# parameters.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
#
# Date Created: 2026-06-03
#
# This script defines all user-configurable parameters for the stroke algorithm.
# It is sourced at the top of pipeline_run.R and the parameters defined here
# are passed as arguments to each function in the pipeline.
#
# INSTRUCTIONS FOR USERS:
# - Edit the parameters in this file to configure the algorithm for your dataset.
# - Do NOT edit the function scripts themselves.
# - Parameters are grouped into sections below with descriptions.


# =============================================================================
# 1 ID name
# =============================================================================

# To be changed by algorithm user depending on ID name in the data set
person_id_var <- "person_id"

# =============================================================================
# 2 STUDY DATES
# =============================================================================

# Study start and end dates in the format "YYYY-MM-DD"
study_start_date <- "2022-01-01"
study_end_date   <- "2025-12-31"

# =============================================================================
#  3 STROKE ICD-10 CODES
# =============================================================================

# Define stroke ICD-10 codes grouped by subtype.
# - Keys are subtype labels (used in outputs)
# - Values are vectors of ICD-10 codes to detect in the data
#
# Notes:
# - Trailing X and dots are removed in NHS England health records:
#   "I60X" appears as "I60", "I60.1" appears as "I601"
# - Codes provided here must reflect this - however should different data source be used please senure the 
#   codes reflect those within the data source
# - The default version uses 3-character codes: I60, I61, I63, I64
# - You can extend to 4-character codes (e.g. "I630", "I631") - but must ensure that columns selected below for positions in HES APC refelct this decision 
# - where 3 level codes only needed that list can reflect this e.g. include code I60 only for catch all of I60 codes
# - # where 4 level codes needed (and diag_4 columns selected below) please lsit all codes relevant and where you would like all codes related to a code type
#   then please also include the three level catch all code e.g. I60, I601, I602, I603, I604, I605, I606, I608, I609. 
# - You can add related codes as you see fit such as TIA (G45) or subdural haemorrhage (I62) etc.

stroke_subtype_map <- list(
  "ischaemic"    = c("I63"),
  "haemorrhagic" = c("I60", "I61"),
  "unknown"      = c("I64")
)

# Derive flat vector of all stroke codes from the subtype map to be used by the algorithm (do not edit)
stroke_codes <- unique(unlist(stroke_subtype_map))

# =============================================================================
# 4 CODE POSITIONS IN HES-APC
# =============================================================================
# The diagnosis column names used in HES APC depend on the type of ICD code list being used:
#
# - If using ONLY 3-character ICD codes:
#       use columns such as diag_3_01, diag_3_02 ... diag_3_20
#
# - If using 4-character ICD codes:
#       use columns such as diag_4_01, diag_4_02 ... diag_4_20
#       (or diag_04_01 etc depending on your dataset naming convention)
#
# This example is currently set up for 3-character diagnosis columns
# (diag_3_01 to diag_3_20), where:
#       diag_3_01 = primary diagnosis position
#       diag_3_02 onwards = secondary diagnosis positions
#
# IMPORTANT:
# If using 4-character code lists, update BOTH the column prefix
# and the position ranges below accordingly.

# -------------------------------------------------------------------
# Specify diagnosis positions accepted for a FIRST stroke in HES APC
# -------------------------------------------------------------------
#
# Default setting:
#     accepts a stroke code in ANY diagnosis position
#     (diag_3_01 to diag_3_20)
#
# To change the range:
#     range(start_position, stop_position + 1)
#
# Examples:
#     range(1, 21) = positions 1 to 20
#     range(1, 2)  = position 1 only
#     range(1, 6)  = positions 1 to 5

code_positions_first_stroke_hes_apc <- paste0("diag_3_", sprintf("%02d", 1:20))
#   -------------------------------------------------------------------
# Specify diagnosis positions accepted for a SUBSEQUENT stroke in HES APC
# -------------------------------------------------------------------
#
# Default setting:
#     accepts a stroke code in PRIMARY diagnosis position only
#     (diag_3_01)
#
# Modify the range below if additional diagnosis positions
# should be included for subsequent stroke events

code_positions_subsequent_stroke_hes_apc <- paste0("diag_3_", sprintf("%02d", 1:1))

# =============================================================================
# 5 CODE POSITIONS IN ONS DEATHS
# =============================================================================
# 5.1 ONS deaths ICD-10 code length
#-------------------------------------------------------------------
#
# Specify whether the ICD-10 code list contains:
# - ONLY 3-character ICD-10 codes
#       e.g. I63
# - 4-character ICD-10 codes
#       e.g. I631

# Options:
#       3 = use first 3 characters only
#       4 = use first 4 characters only
#
# IMPORTANT:
# This setting must match the format of the ICD-10 codes
# included in the code list.
icd10_code_length_deaths <- 3

# -------------------------------------------------------------------
# 5.2  ONS Deaths diagnosis positions
#-------------------------------------------------------------------
#
# Column definitions:
#       underlying_cod     = underlying cause of death
#       cod_mentioned_1+   = additional causes mentioned on death certificate

# -------------------------------------------------------------------
# 5.2.1 Specify diagnosis positions accepted for a FIRST stroke in ONS deaths
# -------------------------------------------------------------------
#
# This applies when:
#       no previous stroke has been identified in HES APC,
#       and the FIRST evidence of stroke appears in death records.
#
# Default setting:
#       accepts stroke codes in ANY death certificate position:
#           - underlying_cod
#           - cod_mentioned_1 to cod_mentioned_15
#
# To change the number of secondary positions included:
#       range(start_position, stop_position + 1)
#
# Examples:
#       range(1, 16) = cod_mentioned_1 to cod_mentioned_15
#       range(1, 6)  = cod_mentioned_1 to cod_mentioned_5
#       range(0, 0)  = include NO secondary causes
code_positions_first_stroke_deaths <- c(
  "underlying_cod",
  paste0("cod_mentioned_", 1:15)
)

# -------------------------------------------------------------------
# 5.2.2 Specify diagnosis positions accepted for a SUBSEQUENT stroke in ONS deaths
# -------------------------------------------------------------------
#
# This applies when:
#       a stroke has already been identified in HES APC,
#       and a later stroke recorded in death records is counted
#       as a separate SUBSEQUENT stroke event.
#
# Default setting:
#       accepts ONLY the underlying cause of death
#       (underlying_cod)
#
# Secondary causes of death are currently excluded because:
#       range(0, 0) produces no cod_mentioned columns.
#
# To include secondary causes:
#       range(1, 16) = cod_mentioned_1 to cod_mentioned_15

code_positions_subsequent_stroke_deaths <- c(
  "underlying_cod"
)

# =============================================================================
# 6 WASHOUT PERIODS
# =============================================================================

# Washout period (in days) between stroke events in HES-APC.
# Any subsequent stroke recorded within this many days of a prior stroke
# will not be counted as a new event.
# Set to 0 to apply no washout.
washout_between_strokes <- 30

# Washout period (in days) between a stroke death and a prior HES-APC stroke.
# A stroke death occurring within this many days of a HES-APC stroke event
# will not be counted as a new event (assumed to relate to the same episode).
# Set to 0 to apply no washout.
washout_between_death_and_hes_stroke <- 30

# =============================================================================
# 7 FATAL STROKE DEFINITION
# =============================================================================

# Number of days after a HES-APC stroke event within which a death from any
# cause (e.g. pneumonia) classifies that stroke as "fatal".
# e.g. the default value of 30 means any stroke followed by death within
# 30 days is recorded as a fatal stroke.
# Set to 0 to not classify any HES-APC strokes as fatal.
fatal_stroke_definition <- 30
