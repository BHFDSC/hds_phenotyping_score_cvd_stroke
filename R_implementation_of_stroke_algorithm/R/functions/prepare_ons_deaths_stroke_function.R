# SCORE-CVD: Stroke algorithm
# Prepare ONS deaths
# prepare_ons_deaths_stroke_function.R
# BHF Data Science Centre, 2025
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
# 
# Date Created: 2025-05-13
#
# This script encapsulates the ONS deaths data preparation for the stroke algorithm.
# It loads the ONS deaths dataset and performs the following:
# - Removing duplicates
# - Assigning date columns
# - Removing null dates
# - Rename columns for consistency
# - Removing bad records (with flowchart)
# - Saves cleaned dataset

library(tidyverse)
library(lubridate)
library(janitor)

options(scipen=999)

# Function to prepare ONS deaths data for stroke algorithm
prepare_ons_deaths_stroke <- function(input_ons_deaths_path, 
                                      person_id_var, 
                                      output_ons_deaths_path) {
  
  # Columns with date data types
  date_cols <- c("date_of_death")
  
  # Read in ONS deaths data
  ons_deaths <- read_csv(input_ons_deaths_path, col_types = cols(.default = col_character()))
  
  # Convert column names to lower case
  names(ons_deaths) <- tolower(names(ons_deaths))
  
  # Set column types
  set_column_types <- function(.ons_deaths, .date_cols) {
    .col_names <- colnames(.ons_deaths)
    .date_cols <- intersect(.col_names, .date_cols)
    
    if (length(.date_cols) > 0) {
      .ons_deaths <- .ons_deaths %>% 
        #mutate(across(all_of(.date_cols), ~ dmy(.)))
      mutate(across(all_of(.date_cols), ~ parse_date_time(
        .,
        orders = c("ymd", "dmy", "mdy")
      ) %>% as.Date()))
    }
    
    return(.ons_deaths)
  }
  
  ons_deaths <- ons_deaths %>% 
    set_column_types(.date_cols = date_cols)
  
  # Remove null dates
  remove_null_dates <- function(.date, null_dates) {
    .date <- if_else(.date %in% ymd(null_dates), NA_Date_, .date)
    return(.date)
  }
  
  ons_deaths <- ons_deaths %>% 
    mutate(
      across(all_of(date_cols), function(.x) {
        remove_null_dates(.x, null_dates = c("1800-01-01", "1801-01-01"))
      })
    )
  
  # Clean column names and rename key columns
  # Standard ONS columns: underlying_cod, cod_mentioned_1 through cod_mentioned_15
  ons_deaths <- ons_deaths %>% 
    janitor::clean_names() %>%
    rename(person_id = all_of(person_id_var))
  
  # Flag duplicates - keep earliest record
  ons_deaths <- ons_deaths %>%
    arrange(person_id, date_of_death) %>%
    group_by(person_id) %>%
    mutate(
      non_duplicated_record = if_else(
        row_number() == 1,
        TRUE,
        FALSE
      )
    ) %>%
    ungroup()
  
  # Create quality indicators
  ons_deaths <- ons_deaths %>%  
    mutate(
      known_person_id = if_else(!is.na(person_id), TRUE, FALSE),
      known_death_date = if_else(!is.na(date_of_death), TRUE, FALSE),
      non_duplicated_record = as.logical(non_duplicated_record)
    )
  
  # Create inclusion flags
  ons_deaths <- ons_deaths %>%  
    mutate(
      c0 = TRUE,
      c1 = c0 & known_person_id,
      c2 = c1 & known_death_date,
      c3 = c2 & non_duplicated_record,
      include = c3
    )
  
  # Compute flowchart
  flowchart_ons_deaths <- ons_deaths %>%   
    select(person_id, c0, c1, c2, c3) %>% 
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
        criteria == "c0" ~ "Original ONS deaths dataset",
        criteria == "c1" ~ "Non-null person_id",
        criteria == "c2" ~ "Non-null date_of_death",
        criteria == "c3" ~ "Non-duplicated record",
        .default = NA_character_
      ),
      episodes_removed = n_episodes - lag(n_episodes),
      ids_removed = n_ids - lag(n_ids),
      pct_episodes_removed = round(episodes_removed / lag(n_episodes) * 100, 2),
      pct_ids_removed = round(ids_removed / lag(n_ids) * 100, 2)
    ) %>% 
    select(criteria, description, n_episodes, episodes_removed, pct_episodes_removed,
           n_ids, ids_removed, pct_ids_removed)
  
  # Save flowchart
  write_csv(
    flowchart_ons_deaths,
    file = here::here(output_ons_deaths_path, "flowchart_ons_deaths.csv")
  )
  
  # Save excluded rows for reference
  ons_deaths_excluded_rows <- ons_deaths %>% 
    filter(!include)
  
  write_csv(
    ons_deaths_excluded_rows,
    file = here::here(output_ons_deaths_path, "ons_deaths_excluded_rows.csv")
  )
  
  # Filter to only include good records
  ons_deaths_prepared <- ons_deaths %>% 
    filter(include) %>%
    select(-include, -known_person_id, -known_death_date, -non_duplicated_record)
  
  # Save ons_deaths_prepared to .csv for portability
  write_csv(
    ons_deaths_prepared,
    file = here::here(output_ons_deaths_path, "ons_deaths_prepared.csv")
  )
  
  # Save ons_deaths_prepared to .rds for use in stroke algorithm function
  write_rds(
    ons_deaths_prepared,
    file = here::here(output_ons_deaths_path, "ons_deaths_prepared.rds")
  )
  
  message("ONS deaths data preparation complete. Total records: ", nrow(ons_deaths_prepared))
  
  return(ons_deaths_prepared)
}
