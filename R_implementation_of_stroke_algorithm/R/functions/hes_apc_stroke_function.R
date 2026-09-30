# SCORE-CVD: Stroke algorithm
# HES-APC Stroke Algorithm
# hes_apc_stroke_function.R
# BHF Data Science Centre, 2026
#
# Authors:
# - Laura Sherlock, BHF Data Science Centre
#
# Date Created: 2026-06-09
#
# This script encapsulates the HES-APC stroke classification step in a function.
# It translates the row-by-row pandas algorithm from the Databricks notebook
# into R.
#
# See algorithm flowchart and the README for more details

library(tidyverse)
library(lubridate)

# Internal helper: classify episodes for a single individual
# Applied via group_modify() - receives a data frame of one person's episodes
classify_strokes_individual <- function(df, stroke_codes,
                                        code_positions_first_stroke_hes_apc,
                                        code_positions_subsequent_stroke_hes_apc,
                                        washout_between_strokes,
                                        stroke_subtype_map) {
  
  # Sort episodes chronologically (mirrors pandas sort_values in Databricks)
  df <- df %>%
    arrange(admidate, epistart, epiend, epiorder, epikey) %>%
    mutate(index_num = row_number())
  
  # Identify which diagnosis columns exist in this dataset
  all_diag_cols <- colnames(df)[grepl("^diag_[34]_\\d{2}$", colnames(df))]
  
  first_positions  <- intersect(code_positions_first_stroke_hes_apc,      all_diag_cols)
  subseq_positions <- intersect(code_positions_subsequent_stroke_hes_apc,  all_diag_cols)
  any_positions    <- union(first_positions, subseq_positions)
  
  # Flag each episode: stroke code presence in relevant positions
  has_stroke_any <- function(row_vals) {
    any(row_vals %in% stroke_codes, na.rm = TRUE)
  }
  
  df <- df %>%
    mutate(
      diag_stroke_any = apply(
        select(., all_of(any_positions)), 1, has_stroke_any
      ),
      diag_first_stroke_positions = apply(
        select(., all_of(first_positions)), 1, has_stroke_any
      ),
      diag_subsequent_stroke_positions = apply(
        select(., all_of(subseq_positions)), 1, has_stroke_any
      )
    )
  
  # Person-level flag: has at least one stroke code anywhere
  individual_with_stroke <- any(df$diag_stroke_any, na.rm = TRUE)

  # Subtyping 
  
  # 1. Extract all stroke codes present in each episode (from any position)
  df <- df %>%
    rowwise() %>%
    mutate(
      stroke_codes_in_episode = list({
        vals   <- unlist(across(all_of(any_positions)))
        vals[vals %in% stroke_codes & !is.na(vals)]
      })
    ) %>%
    ungroup()
  
  # 2. First stroke code per episode
  df <- df %>%
    mutate(
      first_stroke_code = sapply(stroke_codes_in_episode, function(codes) {
        if (length(codes) > 0) codes[[1]] else NA_character_
      })
    )
  
  # 3. Episode-level subtype from first stroke code
  assign_subtype <- function(code) {
    if (is.na(code)) return(NA_character_)
    for (subtype in names(stroke_subtype_map)) {
      prefixes <- stroke_subtype_map[[subtype]]
      if (any(startsWith(code, prefixes))) return(subtype)
    }
    return(NA_character_)
  }
  
  df <- df %>%
    mutate(
      stroke_type_episode = sapply(first_stroke_code, assign_subtype)
    )
  
  # 4. CIPS-level harmonisation: if >1 subtype in a CIPS → "unknown"
  cips_subtypes <- df %>%
    group_by(cips_id) %>%
    summarise(
      stroke_types_in_cips = list(unique(na.omit(stroke_type_episode))),
      n_subtypes_cips      = length(unique(na.omit(stroke_type_episode))),
      .groups = "drop"
    )
  
  df <- df %>%
    left_join(cips_subtypes, by = "cips_id") %>%
    mutate(
      stroke_type_cips = case_when(
        n_subtypes_cips > 1  ~ "unknown",
        n_subtypes_cips == 1 ~ stroke_type_episode,
        TRUE                 ~ NA_character_
      )
    )
  

  # Initialise output columns 
  df <- df %>%
    mutate(
      qualify                   = FALSE,
      stroke_date               = as.Date(NA),
      stroke_count              = 0L,
      terminal_node             = NA_integer_,
      terminal_node_description = NA_character_,
      same_cips_as_last_stroke  = FALSE,
      first_stroke_diagnosis    = FALSE,
      recurrent_stroke          = NA
    )

  # Row-by-row classification loop 
  washout_days       <- as.integer(washout_between_strokes)
  last_valid_stroke_date <- NULL   # NULL until a qualifying stroke is found
  last_valid_cips        <- NULL
  stroke_counter         <- 0L
  
  for (i in seq_len(nrow(df))) {
    
    row <- df[i, ]
    
    # D1: Does this episode contain a stroke code in any relevant position?
    if (!row$diag_stroke_any) {
      df$qualify[i]                   <- FALSE
      df$terminal_node[i]             <- 1L
      df$terminal_node_description[i] <- "T1: Not a stroke event"
      next
    }
    
    # D2: Is this the FIRST record with a stroke code (no prior qualifying stroke)?
    first_stroke <- is.null(last_valid_stroke_date)
    
    if (first_stroke) {
      
      # D3: Is the code in a valid position for a FIRST stroke?
      if (!row$diag_first_stroke_positions) {
        # T2: Not in valid position for first stroke
        df$qualify[i]                   <- FALSE
        df$terminal_node[i]             <- 2L
        df$terminal_node_description[i] <- "T2: Not a stroke event - not in valid position for first stroke"
        next
      }
      
      # T3: Valid first stroke
      stroke_counter         <- 1L
      last_valid_stroke_date <- row$admidate    # washout tracking uses admidate (matches Databricks)
      last_valid_cips        <- row$cips_id
      
      df$qualify[i]                   <- TRUE
      df$stroke_date[i]               <- row$epistart  # stroke_date = epistart (matches Databricks)
      df$stroke_count[i]              <- stroke_counter
      df$first_stroke_diagnosis[i]    <- TRUE
      df$terminal_node[i]             <- 3L
      df$terminal_node_description[i] <- "T3: First stroke event"
      next
    }
    

    # Subsequent stroke logic

    # D4: Is this episode part of the same CIPS as the last qualifying stroke?
    same_cips <- !is.null(last_valid_cips) &&
      !is.na(row$cips_id) &&
      row$cips_id == last_valid_cips
    
    df$same_cips_as_last_stroke[i] <- same_cips
    
    if (same_cips) {
      # T4: Same CIPS as last stroke
      df$qualify[i]                   <- FALSE
      df$terminal_node[i]             <- 4L
      df$terminal_node_description[i] <- "T4: Not a stroke event - same CIPS as last stroke"
      next
    }
    
    # D5: Is the code in a valid position for a SUBSEQUENT stroke?
    if (!row$diag_subsequent_stroke_positions) {
      # T5: Not in valid position for subsequent stroke
      df$qualify[i]                   <- FALSE
      df$terminal_node[i]             <- 5L
      df$terminal_node_description[i] <- "T5: Not stroke event - stroke code not in valid subsequent position"
      next
    }
    
    # D6: Washout check - is this episode within the washout period?
    days_since_last <- as.numeric(row$epistart - last_valid_stroke_date)
    
    if (washout_days > 0 && !is.na(days_since_last) && days_since_last < washout_days) {
      # T6: Within washout period
      df$qualify[i]                   <- FALSE
      df$terminal_node[i]             <- 6L
      df$terminal_node_description[i] <- "T6: Not a stroke event - within washout days"
      next
    }
    
    # T7: Valid recurrent (subsequent) stroke
    stroke_counter         <- stroke_counter + 1L
    last_valid_stroke_date <- row$epistart    # subsequent stroke date = epistart (matches Databricks)
    last_valid_cips        <- row$cips_id
    
    df$qualify[i]                   <- TRUE
    df$stroke_date[i]               <- row$epistart
    df$stroke_count[i]              <- stroke_counter
    df$terminal_node[i]             <- 7L
    df$terminal_node_description[i] <- "T7: Recurrent stroke event"
    
  }
  
  # Post-loop: derive recurrent_stroke flag (mirrors Databricks post-apply step)
  df <- df %>%
    mutate(
      recurrent_stroke = case_when(
        qualify ~ stroke_count > 1,
        TRUE    ~ NA
      )
    )
  
  return(df)
}



### Main exported function

run_hes_apc_stroke_algorithm <- function(
    stroke_hes_apc_input_path,
    stroke_codes,
    stroke_subtype_map,
    code_positions_first_stroke_hes_apc,
    code_positions_subsequent_stroke_hes_apc,
    washout_between_strokes,
    output_hes_apc_stroke_path
) {
  
  # 1. Load CIPS data
  hes_apc_cips <- read_rds(stroke_hes_apc_input_path)
  
  # 2. Study period filter
  hes_apc_cips <- hes_apc_cips %>%
    filter(
      !is.na(epistart),
      epistart >= as.Date(study_start_date),
      epistart <= as.Date(study_end_date),
      !is.na(person_id)
    )
  
  
  # 3. Pre-flag stroke codes and split into stroke / non-stroke populations
  all_diag_cols_global <- colnames(hes_apc_cips)[grepl("^diag_[34]_\\d{2}$", colnames(hes_apc_cips))]
  any_positions_global <- union(
    intersect(code_positions_first_stroke_hes_apc,      all_diag_cols_global),
    intersect(code_positions_subsequent_stroke_hes_apc, all_diag_cols_global)
  )
  
  has_stroke_any_global <- function(row_vals) {
    any(row_vals %in% stroke_codes, na.rm = TRUE)
  }
  
  hes_apc_cips <- hes_apc_cips %>%
    mutate(
      diag_stroke_any_pre = apply(
        select(., all_of(any_positions_global)), 1, has_stroke_any_global
      )
    ) %>%
    group_by(person_id) %>%
    mutate(individual_with_stroke = any(diag_stroke_any_pre, na.rm = TRUE)) %>%
    ungroup()
  
  # T0: individuals with no stroke code in any relevant position across all episodes
  hes_apc_non_stroke_patients_t0 <- hes_apc_cips %>%
    filter(!individual_with_stroke) %>%
    mutate(
      qualify                   = FALSE,
      terminal_node             = 0L,
      terminal_node_description = "T0: individual with no stroke ICD-10 code ever in positions relevant to first OR subsequent stroke"
    ) %>%
    select(-diag_stroke_any_pre, -individual_with_stroke)
  
  # Individuals with >=1 stroke code: these go into the row-by-row algorithm
  hes_apc_for_algorithm <- hes_apc_cips %>%
    filter(individual_with_stroke) %>%
    select(-diag_stroke_any_pre, -individual_with_stroke)
  

  # 4. Apply stroke classification row-by-row per individual
  #    Only applied to individuals with >=1 stroke code 
  message("Applying HES-APC stroke classification algorithm...")
  
  hes_apc_classified_stroke <- hes_apc_for_algorithm %>%
    group_by(person_id) %>%
    group_modify(
      ~ classify_strokes_individual(
        df                                       = .x,
        stroke_codes                             = stroke_codes,
        code_positions_first_stroke_hes_apc      = code_positions_first_stroke_hes_apc,
        code_positions_subsequent_stroke_hes_apc = code_positions_subsequent_stroke_hes_apc,
        washout_between_strokes                  = washout_between_strokes,
        stroke_subtype_map                       = stroke_subtype_map
      )
    ) %>%
    ungroup()
  
  # Combine classified stroke individuals with T0 non-stroke individuals
  # (mirrors Databricks saving both tables separately then unioning for flowchart)
  hes_apc_classified <- bind_rows(hes_apc_classified_stroke, hes_apc_non_stroke_patients_t0)
  

  # 5. Separate qualifying stroke episodes from non-stroke episodes
  #    Both filtered from hes_apc_classified_stroke (stroke individuals only)

  hes_apc_stroke_patients <- hes_apc_classified_stroke %>%
    filter(qualify == TRUE)
  
  hes_apc_non_stroke_episodes <- hes_apc_classified_stroke %>%
    filter(qualify == FALSE | is.na(qualify))
  
  # 7. Generate flowchart of terminal node counts
  #    (mirrors Databricks section 7-8 summary)
  #     R flowchart is generated from hes_apc_classified_stroke only. T0 counts are reported separately.

  
  # T0 summary (separate, matching Databricks hes_apc_algo_non_stroke_patients)
  flowchart_t0 <- hes_apc_non_stroke_patients_t0 %>%
    summarise(
      terminal_node             = 0L,
      terminal_node_description = "T0: individual with no stroke ICD-10 code ever in positions relevant to first OR subsequent stroke",
      n_episodes                = n(),
      n_ids                     = n_distinct(person_id)
    )
  
  write_csv(
    x    = flowchart_t0,
    file = file.path(output_hes_apc_stroke_path, "flowchart_hes_apc_t0_non_stroke.csv")
  )
  
  # Main flowchart: T1-T7 only, from stroke individuals 
  flowchart_hes_apc_stroke <- hes_apc_classified_stroke %>%
    group_by(terminal_node, terminal_node_description) %>%
    summarise(
      n_episodes = n(),
      n_ids      = n_distinct(person_id),
      .groups    = "drop"
    ) %>%
    arrange(terminal_node)
  
  write_csv(
    x    = flowchart_hes_apc_stroke,
    file = file.path(output_hes_apc_stroke_path, "flowchart_hes_apc_stroke.csv")
  )

  # 8. Save outputs

  # hes_apc_classified: stroke individuals only (T1-T7)
  # hes_apc_algo_stroke_patients. Does NOT include T0 individuals.
  write_rds(
    x    = hes_apc_classified_stroke,
    file = file.path(output_hes_apc_stroke_path, "hes_apc_classified.rds")
  )
  
  # T0 non-stroke individuals saved separately
  # hes_apc_algo_non_stroke_patients
  write_rds(
    x    = hes_apc_non_stroke_patients_t0,
    file = file.path(output_hes_apc_stroke_path, "hes_apc_non_stroke_patients.rds")
  )
  
  # Qualifying stroke episodes only (qualify == TRUE)
  write_rds(
    x    = hes_apc_stroke_patients,
    file = file.path(output_hes_apc_stroke_path, "hes_apc_stroke_patients.rds")
  )
  
  write_csv(
    x    = hes_apc_stroke_patients %>%
      select(
        person_id, stroke_date, stroke_count,
        stroke_type_cips,
        first_stroke_diagnosis,
        recurrent_stroke,
        terminal_node, terminal_node_description
      ),
    file = file.path(output_hes_apc_stroke_path, "hes_apc_stroke_patients.csv")
  )
  
  message(glue::glue(
    "HES-APC stroke classification complete. ",
    "{n_distinct(hes_apc_stroke_patients$person_id)} individuals with ",
    "{nrow(hes_apc_stroke_patients)} qualifying stroke episodes identified."
  ))
}
