# SCORE-CVD: Stroke algorithm
# Validate that the expected output matches the actual processed output for HES APC
# test-validate_hes_apc_stroke_function.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
# 
# Date Created: 2026-07-10


# This script checks that the events which qualify as a stroke and their associated terminal nodes
# match between the expected outputs (i.e. the raw simulation data) and the processed outputs 
# i.e. the columns produced by running the processing functions/HES APC stroke algorithm 
# it is called in the 'run_tests_stroke.R' script as part of the validation of the simulation data
# It runs the hes_apc_stroke_function.R script as part of the process

# --- test HES APC outputs ---
test_that("Validate hes apc stroke outputs", {
  # --- Load parameters ---
  source(here::here("R", "parameters.R"))
  # Source the function
  source(here::here("R", "functions", "hes_apc_stroke_function.R"))
  
  options(scipen = 999)
  
  # input and output paths
  stroke_hes_apc_input_path <- here::here ("data", "interim_data", "hes_apc_prepared_cips.rds")
  output_stroke_hes_apc_path <-  here::here ("outputs")
  generated_hes_data_path <- here::here("outputs" , "hes_apc_classified.rds")
  expected_hes_data_path <- here::here ("data", "interim_data", "expected_hes_apc_stroke_outputs.rds")
  
  # call function
  run_hes_apc_stroke_algorithm(
    stroke_hes_apc_input_path                         = stroke_hes_apc_input_path,
    stroke_codes                             = stroke_codes,
    stroke_subtype_map                       = stroke_subtype_map,
    code_positions_first_stroke_hes_apc      = code_positions_first_stroke_hes_apc,
    code_positions_subsequent_stroke_hes_apc = code_positions_subsequent_stroke_hes_apc,
    washout_between_strokes                  = washout_between_strokes,
    output_hes_apc_stroke_path               = output_stroke_hes_apc_path
  )
  
  # Read in the generated data
  generated_data <- read_rds(generated_hes_data_path)
  
  # Select person_id and epikey
  generated_hes_stroke <- generated_data %>%
    select(person_id, epikey, cips_id, qualify, stroke_date, stroke_count, terminal_node) %>%
    mutate(stroke_count = ifelse(is.na(stroke_count), 0, stroke_count),
           epikey = as.character(epikey)) %>%
    arrange(person_id, epikey)
  
  # Read in the expected data 
  expected_data <- read_rds(expected_hes_data_path)
  
  expected_hes_stroke <- expected_data %>%
    select(person_id = PERSON_ID, epikey = EPIKEY, cips_id = EXPECTED_CIPS_ID, qualify = EXPECTED_QUALIFY, 
           stroke_date = EXPECTED_STROKE_DATE, stroke_count = EXPECTED_STROKE_COUNT, terminal_node = EXPECTED_TERMINAL_NODE) %>%
    mutate(stroke_date = as.Date(stroke_date, format = "%d/%m/%Y"),
           epikey = as.character(epikey)) %>%
    distinct() %>%
    arrange(person_id, epikey)
  
  # Compare expected and actual
  expect_equal(generated_hes_stroke, expected_hes_stroke)
})
  
