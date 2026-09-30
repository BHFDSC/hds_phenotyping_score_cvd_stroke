# SCORE-CVD: Stroke algorithm 
# Run the Stroke Algorithm Pipeline
# pipeline_run_stroke.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
# 
# Date Created: 2026-06-04

#
# This script runs each of the function scripts needed to process the HES APC data and 
# ONS deaths data through the stroke algorithm. 
# This includes the following scripts which have been refactored to functions:
# - prepare_hes_apc_stroke_function.R - prepares the HES APC data
# - prepare_ons_deaths_stroke_function.R - prepares the ONS deaths data
# - hes_apc_generate_cips_function.R - generates the continuous inpatient spell (CIPS) ID
# - hes_apc_stroke_function.R - identifies stroke events in the HES APC data
# - ons_deaths_stroke_function.R - identifies stroke events in ONS deaths data
# - stroke_events_function.R - combines HES and ONS strokes with washout logic

# User required to add their data to the folders "data/hes_apc_data" and "data/ons_deaths_data" 
# User required to input their study parameters into script 'parameters.R'

# Load necessary libraries
library(tidyverse)
library(glue)
library(here)

# --- Load parameters ---
source(here::here("R", "parameters.R"))

# --- Define the paths to input and output files ---
input_hes_apc_path <- here::here("data", "hes_apc_data")
output_hes_apc_path <- here::here("data", "interim_data")

input_ons_deaths_path <- here::here("data", "ons_deaths_data", "ons_deaths_data.csv")
output_ons_deaths_path <- here::here("data", "interim_data")

cips_input_path <- here::here("data", "interim_data", "hes_apc_prepared.rds")
output_cips_path <- here::here("data", "interim_data")

stroke_hes_apc_input_path <- here::here("data", "interim_data", "hes_apc_prepared_cips.rds")
output_stroke_hes_apc_path <- here::here("outputs")

stroke_ons_deaths_input_path <- here::here("data", "interim_data", "ons_deaths_prepared.rds")
output_stroke_ons_deaths_path <- here::here("outputs")

output_hes_apc_stroke_path<- here::here( "outputs", "hes_apc_stroke_patients.rds")

output_ons_deaths_patients <- here::here( "outputs", "ons_deaths_stroke_patients.rds")

hes_apc_stroke_patients_path <- output_hes_apc_stroke_path
hes_apc_strokes_processed_path <- here::here("outputs", "hes_apc_strokes_processed.rds")
ons_deaths_strokes_processed_path <- here::here("outputs", "ons_deaths_stroke_processed.rds")
hes_apc_deaths_for_events_path <- here::here("data", "interim_data", "hes_apc_prepared.rds")
output_stroke_events_path <- here::here("outputs")

# --- Validate that the required columns are present in raw HES APC and raw ONS Deaths data ---
# columns in raw data set can be upper or lower case 
required_hes_cols <- c(person_id_var, "EPIKEY", "EPIORDER", "EPISTAT", "EPIEND", "ADMIDATE", 
                       "DISDATE", "PROCODE5", "ADMISORC", "ADMIMETH", "DISDEST", "DISMETH") 

# Add diagnosis columns based on the stroke algorithm positions
required_hes_cols <- c(required_hes_cols, 
                       code_positions_first_stroke_hes_apc, 
                       code_positions_subsequent_stroke_hes_apc) %>% unique()

required_ons_cols <- c(person_id_var, "DATE_OF_DEATH")

# Add death code columns based on the stroke algorithm positions
required_ons_cols <- c(required_ons_cols, code_positions_first_stroke_deaths, 
                       code_positions_subsequent_stroke_deaths) %>% unique()

validate_columns <- function(df, required_cols, dataset_name = "Dataset") {
  df_cols_lower <- tolower(names(df))
  required_cols_lower <- tolower(required_cols)
  
  missing_cols <- required_cols[!tolower(required_cols) %in% df_cols_lower]
  
  if (length(missing_cols) > 0) {
    stop(paste("Missing required columns in", dataset_name, ":", paste(missing_cols, collapse = ", ")))
  } else {
    message(paste(dataset_name, "passed column validation"))
  }
}

# Load one of HES APC csv files for validating columns
hes_raw_files <- list.files(input_hes_apc_path, full.names = TRUE)
if (length(hes_raw_files) == 0) {
  stop("No HES APC CSV files found in ", input_hes_apc_path)
}
hes_raw_file <- hes_raw_files[1]
if (is.na(hes_raw_file) || !file.exists(hes_raw_file)) {
  stop("Unable to locate a valid HES APC CSV file in ", input_hes_apc_path)
}
hes_raw <- read_csv(hes_raw_file)
validate_columns(hes_raw, required_hes_cols, "Raw HES-APC data")

# Load ONS deaths csv file for validating columns
if (!file.exists(input_ons_deaths_path)) {
  stop("ONS deaths file not found at ", input_ons_deaths_path)
}
ons_raw <- read_csv(input_ons_deaths_path)
validate_columns(ons_raw, required_ons_cols, "Raw ONS Deaths data")

# --- Source the functions ---
source(here::here("R", "functions", "prepare_hes_apc_stroke_function.R"))
source(here::here("R", "functions", "prepare_ons_deaths_stroke_function.R"))
source(here::here("R", "functions", "hes_apc_generate_cips_function.R"))
source(here::here("R", "functions", "hes_apc_stroke_function.R"))
source(here::here("R", "functions", "ons_deaths_stroke_function.R"))
source(here::here("R", "functions", "stroke_events_function.R"))

# --- Pipeline process ---
message("\n========================================")
message("Starting Stroke Algorithm Pipeline")
message("========================================\n")

# Step 1: Prepare HES-APC Data
message("Step 1: Preparing HES-APC data...")
prepare_hes_apc_stroke(
  input_hes_apc_path = input_hes_apc_path, 
  person_id_var = person_id_var,
  output_hes_apc_path = output_hes_apc_path
)

# Step 2: Prepare ONS Deaths Data
message("\nStep 2: Preparing ONS Deaths data...")
prepare_ons_deaths_stroke(
  input_ons_deaths_path = input_ons_deaths_path, 
  person_id_var = person_id_var,
  output_ons_deaths_path = output_ons_deaths_path
)

# Step 3: Generate CIPS for HES-APC Data
message("\nStep 3: Generating CIPS for HES-APC data...")
generate_cips(
  cips_input_path = cips_input_path, 
  output_cips_path = output_cips_path
)

# Step 4: Run Stroke Algorithm on HES-APC Data
message("\nStep 4: Running stroke algorithm on HES-APC data...")
run_hes_apc_stroke_algorithm(
  stroke_hes_apc_input_path                = stroke_hes_apc_input_path,
  stroke_codes                             = stroke_codes,
  stroke_subtype_map                       = stroke_subtype_map,
  code_positions_first_stroke_hes_apc      = code_positions_first_stroke_hes_apc,
  code_positions_subsequent_stroke_hes_apc = code_positions_subsequent_stroke_hes_apc,
  washout_between_strokes                  = washout_between_strokes,
  output_hes_apc_stroke_path               = output_stroke_hes_apc_path
)


# Step 5: Run Stroke Algorithm on ONS Deaths Data
message("\nStep 5: Running stroke algorithm on ONS Deaths data...")
run_ons_deaths_stroke_algorithm(
  ons_deaths_input_path = stroke_ons_deaths_input_path,
  hes_apc_prepared_path = cips_input_path,
 # hes_apc_strokes_processed = hes_apc_strokes_processed_path,
  hes_apc_stroke_patients_path = hes_apc_stroke_patients_path,
  icd10_code_length_deaths = icd10_code_length_deaths,
  code_positions_first_stroke_deaths = code_positions_first_stroke_deaths,
  code_positions_subsequent_stroke_deaths = code_positions_subsequent_stroke_deaths,
  stroke_codes = stroke_codes,
  stroke_subtype_map = stroke_subtype_map,
  washout_between_death_and_hes_stroke = washout_between_death_and_hes_stroke,
  output_ons_deaths_stroke_path = output_stroke_ons_deaths_path
)

# Step 6: Process Stroke Events (combine HES and ONS strokes)
message("\nStep 6: Processing combined stroke events...")
process_stroke_events(
  hes_apc_strokes_input_path = hes_apc_stroke_patients_path,
  ons_deaths_strokes_input_path = output_ons_deaths_patients,
  hes_apc_deaths_input_path = hes_apc_deaths_for_events_path,
  washout_between_strokes = washout_between_strokes,
  fatal_stroke_definition = fatal_stroke_definition,
  output_stroke_events_path = output_stroke_events_path
)


message("\n========================================")
message("Stroke Algorithm Pipeline Complete!")
message("========================================\n")
message("Output files saved to: ", output_stroke_events_path)
