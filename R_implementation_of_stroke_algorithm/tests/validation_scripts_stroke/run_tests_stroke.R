# SCORE-CVD: Stroke algorithm 
# Saves simulation data, runs preparation scripts and stroke algorithm, checks
# that the outputs of the algorithm match what we expect from the simulation data
# run_tests_stroke.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
# 
# Date Created: 2026-07-13

# This script runs each of the function scripts needed to validate that the outputs
# produced by the stroke algorithm are what we expect given the simulation data. 
# It runs the following scripts:
# "prepare_hes_apc_stroke_function.R" - prepares HES APC data
# "prepare_ons_deaths_stroke_function.R" - prepares ONS deaths data
# "hes_apc_generate_cips_function.R" - generates the continuous inpatient stay (CIPS) ID
# It uses testthat to check for matches between the expected and actual outputs. 
# testthat is run on all scripts in the file "tests", "validation_scripts_stroke", "testthat" 
# i.e. test-validate_hes_apc_stroke_function (which runs the hes_apc_stroke_function.R script 
# and compares the output with the expected simulation data)
# and test-validate_ons_deaths_stroke_function (which runs the ons_deaths_stroke_function.R script 
# and compares the output with the expected simulation data)

# The script returns whether the test-validate_ons_deaths_stroke_function.R and 
# test-validate_hes_apc_stroke_function.R pass checks of whether the simulation outputs 
# and generated outputs match

options(scipen=999)

# Load libraries
library(testthat)
library(tidyverse)
library(lubridate)
library(here)  

# --- Define ID name ---
# NB to be changed by algorithm user depending on ID name in the data set
person_id_var <- "person_id"

# turns off scientific notation
options(scipen = 999)

# --- Load stroke parameters ---
message("Loading stroke algorithm parameters...")
source(here::here("R", "parameters.R"))

# --- Save the raw simulation data in correct format in file 'data' ----

message("Saving raw simulation data...")

# save the simulation data in correct format
# source the script to save the simulation data in the correct format
source(here::here("tests", "validation_scripts_stroke", "function", "save_sample_data_stroke_function.R"))  

# set the input and output paths for save_sample_data_stroke function
input_sample_hes_apc_path <- here::here ("tests", "stroke_sample_data", "hes_apc_data.csv")
expected_columns_hes_path <- here::here ("data", "interim_data")
output_sample_data_hes_path <- here::here ("data", "hes_apc_data")

input_sample_ons_deaths_path  <- here::here ("tests", "stroke_sample_data", "ons_deaths_data.csv")
expected_columns_deaths_path <- here::here ("data", "interim_data")
output_sample_data_deaths_path <- here::here ("data", "ons_deaths_data")

# run the function
save_sample_data_stroke(
  input_sample_hes_apc_path = input_sample_hes_apc_path,
  expected_columns_hes_path = expected_columns_hes_path,
  output_sample_data_hes_path = output_sample_data_hes_path,
  input_sample_ons_deaths_path = input_sample_ons_deaths_path,
  expected_columns_deaths_path = expected_columns_deaths_path,
  output_sample_data_deaths_path = output_sample_data_deaths_path
)


# --- Run the data preparation and cips generation functions ----
message("Running data preparation functions...")

# Source preparation and cips generation scripts 
source(here::here("R", "functions", "prepare_hes_apc_stroke_function.R"))
source(here::here("R", "functions", "prepare_ons_deaths_stroke_function.R"))
source(here::here("R", "functions", "hes_apc_generate_cips_function.R")) 

# set the input and output paths for preparation scripts
input_hes_apc_path <- here::here ("data", "hes_apc_data")
output_hes_apc_path <- here::here ("data", "interim_data")

input_ons_deaths_path <- here::here ("data", "ons_deaths_data", "ons_deaths_data.csv")
output_ons_deaths_path <- here::here ("data", "interim_data")

cips_input_path <- here::here ("data", "interim_data", "hes_apc_prepared.rds")
output_cips_path <-  here::here ("data", "interim_data")


# Run the preparation functions for HES APC and ONS deaths and cips generation
prepare_hes_apc_stroke(input_hes_apc_path = input_hes_apc_path, 
                       person_id_var = person_id_var,
                       output_hes_apc_path = output_hes_apc_path)


prepare_ons_deaths_stroke(input_ons_deaths_path = input_ons_deaths_path, 
                          person_id_var = person_id_var,
                          output_ons_deaths_path = output_ons_deaths_path)

# Generate CIPS ID
generate_cips(cips_input_path = cips_input_path,
                 output_cips_path = output_cips_path)

# --- Run testthat validation tests ---
message("Running validation tests...")

# Run the tests
test_file(here::here("tests", "validation_scripts_stroke", "testthat", "test-validate_hes_apc_stroke_function.R"))
test_file(here::here("tests", "validation_scripts_stroke", "testthat", "test-validate_ons_deaths_stroke_function.R"))

message("Stroke algorithm validation complete!")
