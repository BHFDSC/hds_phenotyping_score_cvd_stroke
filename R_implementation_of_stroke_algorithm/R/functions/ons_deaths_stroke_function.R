# SCORE-CVD: Stroke algorithm
# ONS Deaths Stroke Algorithm
# ons_deaths_stroke_function.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
#
# Date Created: 2026-06-10

#
# This script encapsulates the ONS deaths stroke classification step.
# For each individual, it determines whether their death record constitutes
# a qualifying stroke event

# See algorithm flowchart and the README for more details

library(tidyverse)
library(lubridate)

run_ons_deaths_stroke_algorithm <- function(
    ons_deaths_input_path,
    hes_apc_prepared_path,
    hes_apc_stroke_patients_path,
    stroke_codes,
    stroke_subtype_map,
    icd10_code_length_deaths,
    code_positions_first_stroke_deaths,
    code_positions_subsequent_stroke_deaths,
    washout_between_death_and_hes_stroke,
    output_ons_deaths_stroke_path
) {
  

  # 1. Load data
  #    Cohort filtering and study period restriction are applied upstream
  #    before this function is called 
  ons_deaths       <- read_rds(ons_deaths_input_path)
  hes_apc_prepared <- read_rds(hes_apc_prepared_path)
  
  # Load HES-APC qualifying stroke events (may be empty if run before HES alg)
  hes_apc_stroke_patients <- read_rds(hes_apc_stroke_patients_path)
  
  # Keep only columns we need from HES-APC prepared for in-hospital death check
  hes_apc_discharge <- hes_apc_prepared %>%
    select(person_id, epikey, disdate, dismeth, disdest, epiend)
  

  # 2. Truncate ICD-10 codes in death certificate columns to specified length in parameters
  #  - Without this,4-character codes such as I639 fail to match the 3-character stroke_codes
  #    list and are silently missed.

  icd10_code_length_deaths <- as.integer(icd10_code_length_deaths)
  
  death_columns_all_positions <- unique(c(
    code_positions_first_stroke_deaths,
    code_positions_subsequent_stroke_deaths
  ))
  
  icd10_cols_present <- intersect(death_columns_all_positions, colnames(ons_deaths))
  
  if (length(icd10_cols_present) > 0) {
    ons_deaths <- ons_deaths %>%
      mutate(
        across(
          all_of(icd10_cols_present),
          ~ if_else(!is.na(.), substr(., 1, icd10_code_length_deaths), NA_character_)
        )
      )
  }
  

  # 3. Flag stroke codes in death records
  #    (mirrors Databricks sections 2-3)
  first_cod_cols  <- intersect(code_positions_first_stroke_deaths,      colnames(ons_deaths))
  subseq_cod_cols <- intersect(code_positions_subsequent_stroke_deaths,  colnames(ons_deaths))
  any_cod_cols    <- union(first_cod_cols, subseq_cod_cols)
  
  has_code <- function(row_vals) {
    any(row_vals %in% stroke_codes, na.rm = TRUE)
  }
  
  ons_deaths <- ons_deaths %>%
    mutate(
      death_stroke_any = apply(
        select(., all_of(any_cod_cols)), 1, has_code
      ),
      death_first_stroke_positions = apply(
        select(., all_of(first_cod_cols)), 1, has_code
      ),
      death_subsequent_stroke_positions = apply(
        select(., all_of(subseq_cod_cols)), 1, has_code
      )
    )

  # 4. Extract stroke codes and assign subtype
 
  # All stroke codes present in each death record
  ons_deaths <- ons_deaths %>%
    mutate(
      stroke_codes_in_death_episode = apply(
        select(., all_of(any_cod_cols)), 1,
        function(x) {
          matched <- x[x %in% stroke_codes & !is.na(x)]
          if (length(matched) > 0) matched else character(0)
        }
      )
    )
  
  # First stroke code per death record 
  ons_deaths <- ons_deaths %>%
    mutate(
      first_stroke_code_death = sapply(stroke_codes_in_death_episode, function(codes) {
        if (length(codes) > 0) codes[[1]] else NA_character_
      })
    )
  
  # Episode-level subtype from first stroke code 
  assign_subtype <- function(code) {
    if (is.na(code)) return(NA_character_)
    for (subtype in names(stroke_subtype_map)) {
      if (any(startsWith(code, stroke_subtype_map[[subtype]]))) return(subtype)
    }
    return(NA_character_)
  }
  
  ons_deaths <- ons_deaths %>%
    mutate(
      stroke_type_death_episode = sapply(first_stroke_code_death, assign_subtype)
    )
  

  # 5. Split into stroke and non-stroke deaths
  
  deaths_with_stroke <- ons_deaths %>%
    filter(death_stroke_any)
  
  deaths_without_stroke <- ons_deaths %>%
    filter(!death_stroke_any) %>%
    mutate(
      qualify                   = FALSE,
      terminal_node             = 0L,
      terminal_node_description = "T0: individual with no stroke ICD-10 code ever in the death records in positions relevant to first OR subsequent stroke"
    )
  
 
  # 6. D1: Flag in-hospital deaths
  #    In-hospital death = discharge within 1 day of death
  #    AND (dismeth == "4" OR disdest == "79")
  in_hospital_death <- deaths_with_stroke %>%
    select(person_id, date_of_death) %>%
    inner_join(hes_apc_discharge, by = "person_id") %>%
    mutate(
      death_within_1_day_of_discharge = !is.na(date_of_death) &
        !is.na(disdate) &
        abs(as.numeric(date_of_death - disdate)) <= 1,
      discharge_to_death = dismeth == "4" | disdest == "79",
      death_before_hosp_death = discharge_to_death &
        !is.na(date_of_death) &
        date_of_death < pmax(epiend, disdate, na.rm = TRUE),
      in_hospital_death = (death_within_1_day_of_discharge & discharge_to_death) |
        (death_before_hosp_death & discharge_to_death)
    ) %>%
    group_by(person_id) %>%
    summarise(in_hospital_death = any(in_hospital_death, na.rm = TRUE),
              .groups = "drop")
  
  deaths_with_stroke <- deaths_with_stroke %>%
    left_join(in_hospital_death, by = "person_id") %>%
    mutate(in_hospital_death = replace_na(in_hospital_death, FALSE))

  # D2 & D3: Flag washout period and prior qualifying HES stroke
  if (nrow(hes_apc_stroke_patients) > 0) {
    
    qualifying_hes_strokes <- hes_apc_stroke_patients %>%
      filter(qualify == TRUE) %>%
      select(person_id, stroke_date)
    
    prior_hes_stroke <- deaths_with_stroke %>%
      select(person_id, date_of_death) %>%
      left_join(qualifying_hes_strokes, by = "person_id") %>%
      mutate(
        days_between = as.numeric(date_of_death - stroke_date),
        stroke_within_washout = if_else(
          washout_between_death_and_hes_stroke > 0 &
            !is.na(days_between) &
            days_between >= 0 &
            days_between < washout_between_death_and_hes_stroke,
          TRUE, FALSE
        )
      ) %>%
      group_by(person_id) %>%
      summarise(
        stroke_within_washout        = any(stroke_within_washout, na.rm = TRUE),
        prior_qualifying_hes_stroke  = any(!is.na(stroke_date)),
        .groups = "drop"
      )
    
  } else {
    
    # No HES strokes available — treat all as having no prior HES stroke
    prior_hes_stroke <- deaths_with_stroke %>%
      select(person_id) %>%
      distinct() %>%
      mutate(
        stroke_within_washout       = FALSE,
        prior_qualifying_hes_stroke = FALSE
      )
    
  }
  
  deaths_with_stroke <- deaths_with_stroke %>%
    left_join(prior_hes_stroke, by = "person_id") %>%
    mutate(
      stroke_within_washout       = replace_na(stroke_within_washout, FALSE),
      prior_qualifying_hes_stroke = replace_na(prior_qualifying_hes_stroke, FALSE)
    )

  
  # 7. Apply decision tree to classify each death
  deaths_with_stroke <- deaths_with_stroke %>%
    mutate(
      qualify = case_when(
        # T1: In-hospital death - captured by HES-APC
        in_hospital_death                                                        ~ FALSE,
        # T2: Within washout period of a prior HES stroke
        stroke_within_washout                                                    ~ FALSE,
        # D3/D4: No prior HES stroke - check first stroke position
        !prior_qualifying_hes_stroke & death_first_stroke_positions              ~ TRUE,
        !prior_qualifying_hes_stroke & !death_first_stroke_positions             ~ FALSE,
        # D3/D5: Prior HES stroke - check subsequent stroke position
        prior_qualifying_hes_stroke  & death_subsequent_stroke_positions         ~ TRUE,
        prior_qualifying_hes_stroke  & !death_subsequent_stroke_positions        ~ FALSE,
        .default = FALSE
      ),
      terminal_node = case_when(
        in_hospital_death                                                        ~ 1L,
        stroke_within_washout                                                    ~ 2L,
        !prior_qualifying_hes_stroke & !death_first_stroke_positions             ~ 3L,
        !prior_qualifying_hes_stroke & death_first_stroke_positions              ~ 4L,
        prior_qualifying_hes_stroke  & !death_subsequent_stroke_positions        ~ 5L,
        prior_qualifying_hes_stroke  & death_subsequent_stroke_positions         ~ 6L,
        .default = NA_integer_
      ),
      terminal_node_description = case_when(
        terminal_node == 1L ~ "T1: Excluded - in-hospital death captured by HES-APC",
        terminal_node == 2L ~ paste0("T2: Excluded - death within washout period of ",
                                     washout_between_death_and_hes_stroke,
                                     " days from prior HES stroke"),
        terminal_node == 3L ~ "T3: Not a stroke event - not in valid position for first stroke",
        terminal_node == 4L ~ "T4: First stroke event",
        terminal_node == 5L ~ "T5: Not a stroke event - not in valid position for subsequent stroke",
        terminal_node == 6L ~ "T6: Subsequent stroke event",
        .default = NA_character_
      ),
      stroke_date = if_else(qualify, date_of_death, NA_Date_)
    )
  
  
  # 8. Combine stroke and non-stroke deaths
  ons_deaths_classified <- bind_rows(deaths_with_stroke, deaths_without_stroke)
  
 
  # 9. Generate flowchart
  flowchart_ons_deaths_stroke <- ons_deaths_classified %>%
    group_by(terminal_node, terminal_node_description) %>%
    summarise(
      n_deaths = n(),
      n_ids    = n_distinct(person_id),
      .groups  = "drop"
    ) %>%
    arrange(terminal_node)
  
  write_csv(
    x    = flowchart_ons_deaths_stroke,
    file = file.path(output_ons_deaths_stroke_path,
                     "flowchart_ons_deaths_stroke.csv")
  )
  

  # 10. Save outputs
    # Primary output: stroke-code individuals only (T1-T6)
  # deaths_algo_stroke_patients. Includes qualify=TRUE AND qualify=FALSE rows.
  write_rds(
    x    = deaths_with_stroke,
    file = file.path(output_ons_deaths_stroke_path,
                     "ons_deaths_stroke_patients.rds")
  )
  
  # T0 non-stroke individuals saved separately
  # deaths_algo_non_stroke_patients
  write_rds(
    x    = deaths_without_stroke,
    file = file.path(output_ons_deaths_stroke_path,
                     "ons_deaths_non_stroke_patients.rds")
  )
  
  # Combined classified dataset (T0-T6) retained for audit purposes
  write_rds(
    x    = ons_deaths_classified,
    file = file.path(output_ons_deaths_stroke_path, "ons_deaths_classified.rds")
  )
  
  # Qualifying stroke deaths only (T4, T6) for downstream stroke events step
  ons_deaths_qualifying <- deaths_with_stroke %>%
    filter(qualify == TRUE)
  
  write_rds(
    x    = ons_deaths_qualifying,
    file = file.path(output_ons_deaths_stroke_path,
                     "ons_deaths_stroke_patients_qualifying.rds")
  )
  
  write_csv(
    x    = ons_deaths_qualifying %>%
      select(
        person_id, date_of_death, stroke_date,
        stroke_codes_in_death_episode,
        first_stroke_code_death,
        stroke_type_death_episode,
        terminal_node, terminal_node_description
      ),
    file = file.path(output_ons_deaths_stroke_path,
                     "ons_deaths_stroke_patients.csv")
  )
  
  message(glue::glue(
    "ONS deaths stroke classification complete. ",
    "{n_distinct(deaths_with_stroke$person_id)} individuals with stroke codes ",
    "({nrow(deaths_with_stroke)} records) processed. ",
    "{n_distinct(ons_deaths_qualifying$person_id)} qualifying stroke deaths identified."
  ))
}