# SCORE-CVD: Stroke algorithm
# Save sample HES and death data for stroke algorithm
# save_sample_data_stroke_function.R
# BHF Data Science Centre, 2025
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
# 
# Date Created: 2025-05-27
#
# This script encapsulates the stroke algorithm data saving function.
# It loads the HES APC and ONS deaths simulation data from folder 'stroke_sample_data', separates 
# expected output columns, and saves the HES APC and ONS deaths data in folder 'data' 
# by financial year for HES data

options(scipen=999)

save_sample_data_stroke <- function(
    input_sample_hes_apc_path,
    expected_columns_hes_path,
    output_sample_data_hes_path,
    input_sample_ons_deaths_path,
    expected_columns_deaths_path,
    output_sample_data_deaths_path
) {
  library(readr)
  library(dplyr)
  library(stringr)
  library(lubridate)
  library(fs)
  
  
  # Load and process HES APC data 
  hes_apc_with_expected_cols <- read_csv(here::here(input_sample_hes_apc_path), 
                                         col_types = cols(
                                           EPIEND    = col_date(format = "%d/%m/%Y"),
                                           DISDATE   = col_date(format = "%d/%m/%Y"),
                                           EPISTART  = col_date(format = "%d/%m/%Y"),
                                           EXPECTED_STROKE_DATE = col_date(format = "%d/%m/%Y"),
                                           ADMIDATE  = col_date(format = "%d/%m/%Y")))
  
  # Extract expected outputs and filter out excluded cases
  expected_hes_apc_outputs <- hes_apc_with_expected_cols %>%
    select(PERSON_ID, EPIKEY, EXPECTED_CIPS_ID, INDIVIDUAL_WITH_STROKE_CODE,
 EXPECTED_QUALIFY, EXPECTED_STROKE_COUNT, EXPECTED_STROKE_DATE, EXPECTED_TERMINAL_NODE) %>%
    filter(!(str_detect(PERSON_ID, "^E") | PERSON_ID == "NA")) %>%
    filter(INDIVIDUAL_WITH_STROKE_CODE == 1)
  
  # Save expected outputs
  write_rds(
    x = expected_hes_apc_outputs,
    file = file.path(expected_columns_hes_path, "expected_hes_apc_stroke_outputs.rds")
  )
  
  # Remove expected columns to create HES APC input dataset
  hes_apc_clean <- hes_apc_with_expected_cols %>%
    select(-c(EXPECTED_CIPS_DESCRIPTION, EXPECTED_CIPS_ID, EXPECTED_QUALIFY, EXPECTED_STROKE_COUNT, 
              EXPECTED_STROKE_DATE, EXPECTED_TERMINAL_NODE, EXPECTED_TERMINAL_NODE_DESCRIPTION,
              EXPECTED_STROKE_SUBTYPE, EXPECTED_STROKE_TYPE_CIPS, COMMENTS, DEATH_RECORD_FOR_ID)) %>%
    mutate(across(c(EPIEND, DISDATE, EPISTART, ADMIDATE), as.Date))
  
  # Determine financial year date
  relevant_date <- function(EPIEND, DISDATE, EPISTART, ADMIDATE) {
    if (!is.na(EPIEND)) {
      return(EPIEND)
    } else if (!is.na(DISDATE)) {
      return(DISDATE)
    } else if (!is.na(EPISTART)) {
      return(EPISTART)
    } else {
      return(ADMIDATE)
    }
  }
  
  hes_apc_clean <- hes_apc_clean %>%
    rowwise() %>%
    mutate(FY_date = relevant_date(EPIEND, DISDATE, EPISTART, ADMIDATE)) %>%
    ungroup()
  
  # Compute financial year directly in mutate with vectorized operations
  hes_apc_clean <- hes_apc_clean %>%
    mutate(
      FY = case_when(
        is.na(FY_date) ~ NA_real_,
        month(FY_date) <= 3 ~ year(FY_date) - 1,
        TRUE ~ year(FY_date)
      )
    )
  
  unique_fys <- unique(hes_apc_clean$FY)
  
  # Split and save by financial year - using a direct loop instead of lapply
  split_data <- split(hes_apc_clean, hes_apc_clean$FY)
  
  for (year in names(split_data)) {
    write_csv(
      x = split_data[[year]],
      file = file.path(output_sample_data_hes_path, paste0("hes_apc_fy.", year, ".csv"))
    )
  }
  
  # Load and process ONS deaths data
  ons_deaths_with_expected <- read_csv(input_sample_ons_deaths_path)
  
  expected_ons_deaths_outputs <- ons_deaths_with_expected %>%
    select(PERSON_ID, INDIVIDUAL_WITH_STROKE_CODE, EXPECTED_QUALIFY, EXPECTED_STROKE_COUNT, EXPECTED_STROKE_DATE,
           EXPECTED_TERMINAL_NODE, EXPECTED_TERMINAL_NODE_DESCRIPTION) %>%
    filter(!is.na(PERSON_ID)) %>%
    filter(INDIVIDUAL_WITH_STROKE_CODE == 1)
  
  # Save expected outputs
  write_rds(
    x = expected_ons_deaths_outputs,
    file = file.path(expected_columns_deaths_path, "expected_ons_deaths_stroke_outputs.rds")
  )
  
  # Create input version by removing expected columns
  ons_deaths_clean <- ons_deaths_with_expected %>%
    select(-c(EXPECTED_QUALIFY, EXPECTED_STROKE_COUNT, EXPECTED_STROKE_DATE, EXPECTED_TERMINAL_NODE,
              EXPECTED_TERMINAL_NODE_DESCRIPTION, EXPECTED_STROKE_SUBTYPE, COMMENTS, LINKS_TO_HES_PERSON_ID))
  
  write_csv(
    x = ons_deaths_clean,
    file = file.path(output_sample_data_deaths_path, "ons_deaths_data.csv")
  )
}
