# SCORE-CVD: Stroke algorithm
# Prepare HES-APC
# prepare_hes_apc_stroke_function.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
#
# Date Created: 2025-05-13
# Last updated: 2026-06-13
# Version:      v2
#
# This script encapsulates the data preparation for HES-APC in the stroke algorithm.
# It loads the HES-APC dataset and performs the following:
# - Combines financial years if necessary
# - Assigning date and integer columns
# - Removing null dates
# - Rename columns for consistency
# - Removing bad episodes (with flowchart)
# - Saves cleaned dataset

library(tidyverse)
library(lubridate)
library(janitor)

options(scipen=999)

# Function to prepare HES-APC dataset for stroke algorithm
prepare_hes_apc_stroke <- function(input_hes_apc_path, 
                                   person_id_var, 
                                   date_cols = c("admidate", "disdate", "epiend", "epistart"),
                                   integer_cols = c("epiorder", "epistat"),
                                   null_dates = c("1800-01-01", "1801-01-01"),
                                   output_hes_apc_path) {
  
  # Load dataset (combine financial years if applicable)
  hes_apc_files <- list.files(input_hes_apc_path, pattern = "*.csv", full.names = TRUE)
  hes_apc <- hes_apc_files %>%
    map_dfr(
      function(.hes_apc_file) {
        .hes_apc <- read_csv(
          .hes_apc_file,
          col_types = cols(.default = col_character())
        )
        return(.hes_apc)
      }
    )
  
  names(hes_apc) <- tolower(names(hes_apc))
  
  # Set column types
  set_column_types <- function(.hes_apc, .date_cols, .integer_cols) {
    .col_names <- colnames(.hes_apc)
    .date_cols <- intersect(.col_names, .date_cols)
    .integer_cols <- intersect(.col_names, .integer_cols)
    
    if (length(.date_cols) > 0) {
      .hes_apc <- .hes_apc %>% 
        mutate(across(all_of(.date_cols), as.Date))
    }
    
    if (length(.integer_cols) > 0) {
      .hes_apc <- .hes_apc %>% 
        mutate(across(all_of(.integer_cols), as.integer))
    }
    
    return(.hes_apc)
  }
  
  hes_apc <- hes_apc %>%
    set_column_types(
      .date_cols = date_cols,
      .integer_cols = integer_cols
    )
  
  # Remove null dates
  remove_null_dates <- function(.date, null_dates) {
    .date <- if_else(.date %in% ymd(null_dates), NA_Date_, .date)
    return(.date)
  }
  
  hes_apc <- hes_apc %>% 
    mutate(
      across(all_of(date_cols), function(.x) {
        remove_null_dates(.x, null_dates = null_dates)
      })
    )
  
  # Clean column names and assign person_id column
  hes_apc <- hes_apc %>% 
    rename(person_id = all_of(person_id_var)) %>% 
    janitor::clean_names()
  
  # Accept EPISTART as ADMIDATE if ADMIDATE is missing and EPIORDER is 1
  hes_apc <- hes_apc %>% 
    mutate(
      admidate = if_else(
        condition = is.na(admidate) & (!is.na(epistart)) & (epiorder == 1),
        true = epistart,
        false = admidate
      )
    )
  
  # Create quality indicators
  hes_apc <- hes_apc %>% 
    mutate(
      known_person_id = if_else(!is.na(person_id), TRUE, FALSE),
      known_epikey = if_else(!is.na(epikey), TRUE, FALSE),
      known_procode5 = if_else(!is.na(procode5), TRUE, FALSE),
      known_epistart = if_else(!is.na(epistart), TRUE, FALSE),
      known_epiend = if_else(!is.na(epiend), TRUE, FALSE),
      known_admidate = if_else(!is.na(admidate), TRUE, FALSE),
      complete_episode = if_else(epistat == 3, TRUE, FALSE, missing = FALSE)
    )
  
  # Create inclusion flags
  hes_apc <- hes_apc %>%
    mutate(
      c0 = TRUE,
      c1 = c0 & known_person_id,
      c2 = c1 & known_epikey,
      c3 = c2 & known_procode5,
      c4 = c3 & complete_episode,
      c5 = c4 & known_epistart,
      c6 = c5 & known_epiend,
      c7 = c6 & known_admidate,
      include = c7
    )
  
  # Compute flowchart
  flowchart_hes_apc <- hes_apc %>% 
    select(person_id, c0, c1, c2, c3, c4, c5, c6, c7) %>% 
    mutate(row_id = row_number()) %>% 
    pivot_longer(cols = starts_with("c"), names_to = "criteria", values_to = "inclusion") %>%
    filter(inclusion) %>% 
    group_by(criteria) %>%
    summarise(
      n_episodes = n(),
      n_ids = n_distinct(person_id),
      .groups = "drop"
    ) %>%
    mutate(
      description = case_when(
        criteria == "c0" ~ "Original HES-APC dataset",
        criteria == "c1" ~ "Non-null person_id",
        criteria == "c2" ~ "Non-null epikey",
        criteria == "c3" ~ "Non-null procode5",
        criteria == "c4" ~ "Complete episode",
        criteria == "c5" ~ "Non-null epistart",
        criteria == "c6" ~ "Non-null epiend",
        criteria == "c7" ~ "Non-null admidate",
        .default = NA_character_
      )
    )
  
  # Save flowchart
  write_csv(
    flowchart_hes_apc,
    file = here::here(output_hes_apc_path, "hes_apc_flowchart.csv")
  )
  
  # Filter to only include episodes
  hes_apc_cleaned <- hes_apc %>%
    filter(include == TRUE) %>%
    select(-starts_with("c"), -include, -known_person_id, -known_epikey, 
           -known_procode5, -known_epistart, -known_epiend, -known_admidate, -complete_episode)
  
  # Save cleaned HES-APC dataset
  write_rds(
    hes_apc_cleaned,
    file = here::here(output_hes_apc_path, "hes_apc_prepared.rds")
  )
  
  message("HES-APC data preparation complete. Total episodes: ", nrow(hes_apc_cleaned))
  
  return(hes_apc_cleaned)
}
