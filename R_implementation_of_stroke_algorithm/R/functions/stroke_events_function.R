# SCORE-CVD: Stroke algorithm
# Stroke Events Combination and Processing
# stroke_events_function.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
#
# Date Created: 2026-07-03
#
# This script combines HES-APC and ONS deaths stroke events and applies
# washout periods to generate the final stroke events table.

library(tidyverse)
library(lubridate)

# Function to process stroke events from both HES APC and ONS deaths
process_stroke_events <- function(hes_apc_strokes_input_path,
                                  ons_deaths_strokes_input_path,
                                  hes_apc_deaths_input_path,
                                  washout_between_strokes,
                                  fatal_stroke_definition,
                                  output_stroke_events_path) {

  hes_apc_strokes <- read_rds(hes_apc_strokes_input_path) %>%
    filter(qualify == TRUE) %>%
    select(person_id, stroke_date, stroke_subtype = stroke_type_cips) %>%
    mutate(data_source = "HES-APC")
  
  
  ons_deaths_strokes <- read_rds(ons_deaths_strokes_input_path) %>%
    filter(qualify == TRUE) %>%
    select(person_id, stroke_date, stroke_subtype = stroke_type_death_episode) %>%
    mutate(data_source = "ONS Mortality")

  
  
  # Read in all HES APC cleaned data to get death dates
  hes_apc_cleaned <- read_rds(hes_apc_deaths_input_path)
  
  # Get unique death dates per person
  deaths_info <- hes_apc_cleaned %>%
    group_by(person_id) %>%
    summarise(
      .groups = "drop"
    )
  
  # If available, read full ons_deaths_processed for death dates
  ons_deaths_path <- dirname(ons_deaths_strokes_input_path)
  ons_deaths_file <- file.path(
    dirname(dirname(ons_deaths_strokes_input_path)),
    "data",
    "interim_data",
    "ons_deaths_prepared.rds"
  )
  
  # Try to load ONS deaths to get death dates
  date_of_death <- NULL
  tryCatch({
    ons_deaths_prepared <- read_rds(ons_deaths_file)
    date_of_death <- ons_deaths_prepared %>%
      select(person_id, date_of_death) %>%
      distinct()
  }, error = function(e) {
    message("Warning: Could not load ONS deaths file for death dates")
  })
  
  # Combine HES and ONS death strokes
  stroke_events <- bind_rows(hes_apc_strokes, ons_deaths_strokes) %>%
    distinct()
  
  # Join with death dates if available
  if (!is.null(date_of_death)) {
    stroke_events <- stroke_events %>%
      left_join(date_of_death, by = "person_id")
  } else {
    stroke_events <- stroke_events %>%
      mutate(date_of_death = NA_Date_)
  }
  
  # Order by person and stroke date, then calculate stroke indices
  stroke_events <- stroke_events %>%
    group_by(person_id) %>%
    arrange(stroke_date, data_source, .by_group = TRUE) %>%
    mutate(
      stroke_index = row_number(),
      stroke_total_count = n()
    ) %>%
    ungroup()
  
  # Calculate fatal stroke indicator
  fatal_stroke_definition <- as.integer(fatal_stroke_definition)
  
  stroke_events <- stroke_events %>%
    mutate(
      death_within_fatal_window = if_else(
        !is.na(date_of_death) &
          !is.na(stroke_date) &
          (fatal_stroke_definition > 0) &
          (as.integer(date_of_death - stroke_date) >= 0) &
          (as.integer(date_of_death - stroke_date) < fatal_stroke_definition),
        TRUE,
        FALSE
      ),
      stroke_fatal_type = case_when(
        (stroke_index == stroke_total_count) & (death_within_fatal_window) ~ "Fatal",
        .default = "Non-fatal"
      ),
      stroke_first_or_subsequent = if_else(stroke_index == 1, "First", "Subsequent")
    )
  

  
  # Select final output columns
  stroke_events_final <- stroke_events %>%
    select(
      person_id,
      stroke_date,
      data_source,
      stroke_index,
      stroke_total_count,
      stroke_first_or_subsequent,
      stroke_subtype,
      stroke_fatal_type
    ) %>%
    arrange(person_id, stroke_index)
  
  # Save stroke events
  write_rds(
    stroke_events_final,
    file = here::here(output_stroke_events_path, "stroke_events.rds")
  )
  
  # Save to CSV for viewing
  write_csv(
    stroke_events_final,
    file = here::here(output_stroke_events_path, "stroke_events.csv")
  )
  
  # Generate summary by stroke index and data source
  summary_by_index_source <- stroke_events_final %>%
    group_by(stroke_index, data_source) %>%
    summarise(
      n = n(),
      .groups = "drop"
    ) %>%
    arrange(stroke_index, data_source)
  
  write_csv(
    summary_by_index_source,
    file = here::here(output_stroke_events_path, "stroke_events_summary_by_index_source.csv")
  )
  
  # Generate summary by first/subsequent and data source
  summary_by_first_sub <- stroke_events_final %>%
    group_by(stroke_first_or_subsequent, data_source) %>%
    summarise(
      n = n(),
      .groups = "drop"
    ) %>%
    arrange(stroke_first_or_subsequent, data_source)
  
  write_csv(
    summary_by_first_sub,
    file = here::here(output_stroke_events_path, "stroke_events_summary_by_first_sub.csv")
  )
  
  # Generate summary by fatal and data source
  summary_by_fatal <- stroke_events_final %>%
    group_by(stroke_first_or_subsequent, data_source, stroke_fatal_type) %>%
    summarise(
      n = n(),
      .groups = "drop"
    ) %>%
    arrange(stroke_first_or_subsequent, data_source, stroke_fatal_type)
  
  write_csv(
    summary_by_fatal,
    file = here::here(output_stroke_events_path, "stroke_events_summary_by_fatal.csv")
  )
  
  # Generate summary by data source, first/subsequent, fatal, subtype
  summary_by_fatal_subtype <- stroke_events_final %>%
    group_by(stroke_first_or_subsequent, data_source, stroke_fatal_type, stroke_subtype ) %>%
    summarise(
      n = n(),
      .groups = "drop"
    ) %>%
    arrange(stroke_first_or_subsequent, data_source, stroke_fatal_type, stroke_subtype)
  
  write_csv(
    summary_by_fatal_subtype,
    file = here::here(output_stroke_events_path, "stroke_events_summary_by_fatal_subtype.csv")
  )
  
  message("Stroke events processing complete. Total stroke events: ", nrow(stroke_events_final))
  
  return(stroke_events_final)
}
