# SCORE-CVD: Stroke algorithm
# Validate that the expected output matches the actual processed output for ONS deaths
# test-validate_ons_deaths_stroke_function.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
# 
# Date Created: 2026-07-12
#
# This script checks that the events which qualify as a stroke and their associated terminal nodes
# match between the expected outputs (i.e. the raw simulation data) and the processed outputs 
# i.e. the columns produced by running the processing functions/ONS deaths stroke algorithm 
# it is called in the 'run_tests_stroke.R' script as part of the validation of the simulation data
# It runs the ons_deaths_stroke_function.R script as part of the process

# --- test ONS deaths outputs ---
test_that("Validate ONS deaths stroke outputs", {
  # --- Load parameters ---
  source(here::here("R", "parameters.R"))
  # Source the function
  source(here::here("R", "functions", "ons_deaths_stroke_function.R")) 
  
  # input and output paths
  stroke_ons_deaths_input_path <-  here::here ("data", "interim_data", "ons_deaths_prepared.rds")
  output_stroke_ons_deaths_path <-  here::here ("outputs")
  stroke_hes_apc_input_path <- here::here ("data", "interim_data", "hes_apc_prepared_cips.rds")
  stroke_hes_apc_processed_path <- here::here ("outputs", "hes_apc_stroke_processed.rds")
  generated_ons_data_path <- here::here("outputs" , "ons_deaths_stroke_patients.rds")
  expected_ons_data_path <- here::here ( "data", "interim_data", "expected_ons_deaths_stroke_outputs.rds")
  hes_apc_stroke_patients_path<- here::here( "outputs", "hes_apc_stroke_patients.rds")
  cips_input_path <- here::here("data", "interim_data", "hes_apc_prepared.rds")
  
  # call function
  run_ons_deaths_stroke_algorithm(
    ons_deaths_input_path = stroke_ons_deaths_input_path,
    hes_apc_prepared_path = cips_input_path,
    # hes_apc_strokes_processed = hes_apc_strokes_processed_path,
    hes_apc_stroke_patients_path = hes_apc_stroke_patients_path,
    code_positions_first_stroke_deaths = code_positions_first_stroke_deaths,
    code_positions_subsequent_stroke_deaths = code_positions_subsequent_stroke_deaths,
    stroke_codes = stroke_codes,
    icd10_code_length_deaths = icd10_code_length_deaths,
    stroke_subtype_map = stroke_subtype_map,
    washout_between_death_and_hes_stroke = washout_between_death_and_hes_stroke,
    output_ons_deaths_stroke_path = output_stroke_ons_deaths_path
  )
  
  # Read in the generated data
  generated_data <- read_rds(generated_ons_data_path)
  
  # Select columns
  generated_death_stroke <- generated_data %>%
    select(person_id, qualify, stroke_date, terminal_node) %>%
    arrange(person_id)
  
  # Read in the expected data 
  expected_data <- read_rds(expected_ons_data_path)
  names(expected_data) <- tolower(names(expected_data))
  
  expected_death_stroke <- expected_data %>%
    select(person_id = person_id, qualify = expected_qualify, stroke_date = expected_stroke_date, terminal_node = expected_terminal_node) %>%
    distinct() %>%
    arrange(person_id) %>%
    mutate(stroke_date = as.Date(stroke_date, format = "%d/%m/%Y"))
  
  # Compare expected and actual
  expect_equal(generated_death_stroke, expected_death_stroke)
})

