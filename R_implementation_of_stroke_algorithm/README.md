---
title: "README"
author: "Laura Sherlock"
date: "2026-06-12"
output: html_document
---
# Stroke Event Identification Pipeline — Project Documentation

## 1. Project Overview

This R project falls under the BHF Data Science Centre's [SCORE-CVD](https://zenodo.org/records/8171481) (Standardising Clinical Outcome measures in Routinely collected Electronic healthcare systems data) project. It provides a pipeline for identifying stroke events, including recurrent strokes, in HES APC and ONS deaths datasets. Priority is given to stroke events identified in HES APC records: if a stroke event is counted in HES records, the event is not counted again in the deaths records. A flowchart detailing the logic of the algorithm can be found in the docs folder `docs > flowchart`.

Following discussions around the different needs of projects, the algorithm has been developed to allow flexibility in certain parameters, for example the ICD10 codes used, the subtypes defined, the washout periods between first and subsequent stroke etc. These require user input in the 'parameters.R' script, otherwise default values will be run. 

The ICD-10 codes used to identify stroke eventsa are configurable by the user in `parameters.R`. The default codes are:

| Subtype | ICD-10 codes |
|---------|-------------|
| Ischaemic | I63 |
| Haemorrhagic | I60, I61 |
| Unknown | I64 |

Stroke subtype is derived at episode level from the first stroke code identified in the diagnosis array, and then harmonised to CIPS level: if more than one subtype is present within a single CIPS, the CIPS is labelled `"unknown"`.

Continuous inpatient spells were generated based on documentation from the [Health & Social Care Information Centre (2014)](https://webarchive.nationalarchives.gov.uk/ukgwa/20180307232845tf_/http:/content.digital.nhs.uk/media/11859/Provider-Spells-Methodology/pdf/Spells_Methodology.pdf).

The primary processing script is `pipeline_run.R`, which coordinates the full data workflow including input preparation, CIPS generation, stroke detection, and output generation for both HES APC and ONS deaths data.

The pipeline assumes that study related restrictions have already been applied to the raw data on which the algorithm is run e.g. any age restrictions, geopgraphical restrictions, etc. 

### Simulation Data for Validation

The project includes simulation data and scripts to test outputs and support validation of the algorithm. Simulation HES and ONS datasets with columns indicating whether an episode qualifies as a stroke event are included and can be run through the pipeline using the `run_tests.R` script. These tests compare generated outputs with expected results to confirm correctness.The simulation data is designed to test each node of the algorithm.

## 2. Data Sources

The algorithm requires Hospitals Episode Statistics Admitted Patient Care (HES APC) and Office for National Statistics (ONS) deaths data. The data used for developing the initial Databricks version of this algorithm was accessed within the NHS England Secure Data Environment via the BHF Data Science Centre's [CVD-COVID-UK/COVID-IMPACT Consortium](https://bhfdatasciencecentre.org/areas/cvd-covid-uk-covid-impact/).

## 3. Folder Structure

Below is the folder structure with example input data, interim files, and outputs.

```
> data
  > hes_apc_data
    > hes_apc_fy_2022.csv
    > hes_apc_fy_2023.csv
    > ...
  > ons_deaths_data
    > ons_deaths.csv
  > interim_data
    > expected_hes_apc_stroke_outputs.rds
    > expected_ons_deaths_stroke_outputs.rds
    > flowchart_hes_apc.csv
    > flowchart_ons_deaths.csv
    > hes_apc_flowchart.csv
    > hes_apc_prepared.rds
    > hes_apc_excluded_rows.csv
    > hes_apc_prepared.rds
    > hes_apc_prepared_cips.rds
    > ons_deaths_excluded_rows.csv
    > ons_deaths_prepared.rds
    > ons_deaths_prepared.csv

> docs
  > derived_variables.md
  > files_generated.md
  > stroke_algorithm_flowchart.png
  > pipeline_run_flowchart.png
  > required_columns.csv

> outputs
    > hes_apc_classified.rds
    > hes_apc_stroke_patients.rds
    > hes_apc_stroke_patients.csv
    > flowchart_hes_apc_stroke.csv
    > ons_deaths_classified.rds
    > ons_deaths_stroke_patients.rds
    > ons_deaths_stroke_patients.csv
    > flowchart_ons_deaths_stroke.csv
    > stroke_events.csv
    > stroke_events.rds
    > stroke_events_summary_by_fatal.csv
    > stroke_events_summary_by_fatal_subtype.csv
    > stroke_events_summary_by_first_sub.csv
    > stroke_events_summary_by_index_ource.csv

> R
  > functions
    > prepare_hes_apc_stroke_function.R
    > hes_apc_generate_cips_function.R
    > hes_apc_stroke_function.R
    > prepare_ons_deaths_stroke_function.R
    > ons_deaths_stroke_function.R
    > stroke_events_function.R
  > parameters.R
  > pipeline_run_stroke.R

> tests
  > sample_data
    > hes_apc_data.csv
    > ons_deaths_data.csv
  > validation_scripts_R
    > function
      > save_sample_data.R
  > testthat
    > test-validate_hes_apc_stroke_function.R
    > test-validate_ons_deaths_stroke_function.R
  > run_tests.R

> README.md
```

## 4. Key Components

### 4.1 Parameters Script

**parameters.R**

All user-configurable settings for the pipeline are defined in `parameters.R`. Users should edit this file before running the pipeline otherwise below default values will run. More detailed instructions on allowed parameter values are described in the 'parameters.R' script. Do **not** edit the function scripts themselves. Parameters are grouped into the following sections:

**ID name **
```r
person_id_var <- "person_id"
```

**Study dates**
```r
study_start_date <- "2022-01-01"
study_end_date   <- "2025-12-31"
```

**Stroke ICD-10 codes**

Codes are defined as a named list grouped by subtype. The default uses 3-character codes:
```r
stroke_subtype_map <- list(
  "ischaemic"    = c("I63"),
  "haemorrhagic" = c("I60", "I61"),
  "unknown"      = c("I64")
)
```
The flat vector `stroke_codes` is derived automatically from this map and should not be edited.

Users can extend to 4-character codes (e.g. `"I630"`) if needed — the diagnosis column positions below must be updated accordingly.See 'parameters.R' script for more details.

**Code positions in HES APC**

Diagnosis column names used to identify a valid first or subsequent stroke. Defaults use 3-character diagnosis columns (`diag_3_01` to `diag_3_20`):
```r
# First stroke: any of the 20 diagnosis positions
code_positions_first_stroke_hes_apc <- paste0("diag_3_", sprintf("%02d", 1:20))

# Subsequent stroke: primary diagnosis position only
code_positions_subsequent_stroke_hes_apc <- paste0("diag_3_", sprintf("%02d", 1:1))
```

**Code positions in ONS deaths**

ICD-10 code length and death certificate column positions used for first and subsequent stroke detection:
```r
icd10_code_length_deaths <- 3  # use first 3 characters of ICD-10 code

# First stroke death: underlying cause + up to 15 mentioned causes
code_positions_first_stroke_deaths <- c("underlying_cod", paste0("cod_mentioned_", 1:15))

# Subsequent stroke death: underlying cause only
code_positions_subsequent_stroke_deaths <- c("underlying_cod")
```

**Washout periods**
```r
washout_between_strokes                <- 30  # days between HES stroke events
washout_between_death_and_hes_stroke   <- 30  # days between a stroke death and prior HES stroke
```

**Fatal stroke definition**
```r
fatal_stroke_definition <- 30  # days after HES stroke within which death classifies the stroke as fatal
```

### 4.2 Main Pipeline Script

**pipeline_run.R**

- **Role:** Orchestrates the entire processing workflow.
- **Key Features:**
  - Users must edit `parameters.R` to configure the algorithm before running.
 
  - Input paths point to folders containing one or more CSV files. If HES APC data spans multiple financial years, place all CSV files in the HES APC folder and they will be combined automatically.
  - Output directories are created automatically under `outputs/` if they do not already exist.

### 4.3 Functions

The functions in `R/functions/` are sourced and called in sequence by `pipeline_run.R`.

| File | Description |
|------|-------------|
| `parameters.R` | User-configurable settings: ID variable name, study dates, stroke ICD-10 codes, diagnosis code positions, washout periods, fatal stroke definition. |
| `prepare_hes_apc_stroke_function.` | Cleans and standardises raw HES APC data: parses dates, removes null dates, deduplicates, flags bad records, and saves a flowchart of excluded rows. |
| `hes_apc_generate_cips_function.R` | Assigns Continuous Inpatient Spell (CIPS) IDs, grouping episodes that form part of the same uninterrupted inpatient stay. |
| `hes_apc_stroke_function.R` | Detects and classifies stroke events in HES APC data. Applies a row-by-row decision tree per individual, assigns stroke subtype at episode and CIPS level, identifies first and recurrent stroke events, and outputs terminal node labels. |
| `prepare_ons_deaths_stroke_function..R` | Cleans and standardises ONS deaths data: parses dates (auto-detecting format), truncates ICD-10 codes to the specified length, removes duplicates and out-of-study-period records, and saves a flowchart of excluded rows. |
| `ons_deaths_stroke_function.R` | Detects stroke-related deaths in ONS data. Excludes in-hospital deaths already captured by HES APC, applies washout and prior-HES-stroke logic, classifies each death record.|
| `stroke_events_function.R` | Combines qualifying stroke events from HES APC and ONS deaths into a single stroke events table, applies the fatal stroke definition, and outputs a unified events dataset. |

### 4.4 Optional Tests & Validation

**run_tests.R**

- **Role:** Validates the pipeline using simulation data covering all decision tree nodes.
- **Simulation data:** CSV files in `tests/sample_data/`. These contain cases representing each terminal node of both the HES APC and ONS deaths decision trees, including cases with missing key fields to test the data preparation scripts.
- **Steps:**
  1. Edit `run_tests.R` to set the person ID column name:
     ```r
     person_id_var <- "person_id"
     ```
  2. **Runs `save_sample_data.R`** to prepare sample data and save expected outputs, stripping algorithm-derived columns so the pipeline can re-generate them.
  3. **Runs unit tests via testthat:**
     - `test-validate_hes_apc_stroke_function.R`: validates stroke detection in HES APC data against expected outputs.
     - `test-validate_ons_deaths_stroke_function.R`: validates stroke death classification against expected outputs.

## 5. How to Run the Pipeline

### 5.1 Production Run

1. Open `R/functions/parameters.R` and configure all settings for your study (dates, ICD-10 codes, code positions, washout periods).

2. Place your data files as follows:
   - **HES APC data:** one or more `.csv` files in `data/hes_apc_data/`
   - **ONS deaths data:** a `.csv` file in `data/ons_deaths_data/`

3. Run the pipeline:
   ```r
   source("R/pipeline_run.R")
   ```

Column names in your data do not need to match case — the pipeline standardises all names to lowercase automatically. File paths use the `here` package, so as long as the `.Rproj` file is open, relative paths will resolve correctly.

### 5.2 Validation / Testing Run

1. Open `tests/run_tests.R` and set the person ID column names.

2. Run:
   ```r
   source("tests/run_tests.R")
   ```

If successful, tests will confirm that the stroke classification logic is producing correct outputs for all decision tree nodes.

## 6. Outputs

### Main outputs

The final three steps of the pipeline 'hes_apc_stroke_function.R', 'ons_deaths_stroke_function.R' and 'stroke_events_function.R'writes its outputs to the folder `outputs/`.Other steps output to the folder 'interim data'.

| Function| File | Description |
|--------|------|-------------|
| `hes_apc_stroke_function` | `hes_apc_classified.rds` | All HES APC episodes with terminal node labels. |
|  `hes_apc_stroke_function`  | `hes_apc_stroke_patients.rds / .csv` | Qualifying stroke episodes only, with stroke date, count, subtype, and flags. |
|  `hes_apc_stroke_function`  | `flowchart_hes_apc_stroke.csv` | Episode and individual counts at each HES APC algorithm terminal node. |
| 'ons_deaths_stroke_function'  | `ons_deaths_classified.rds` | All ONS death records with terminal node labels. |
| 'ons_deaths_stroke_function'  | `ons_deaths_stroke_patients.rds / .csv` | Qualifying stroke deaths only, with stroke date, codes, and subtype. |
| 'ons_deaths_stroke_function'  | `flowchart_ons_deaths_stroke.csv` | Record and individual counts at each ONS deaths algorithm terminal node. |
| `stroke_events_function` | `stroke_events.csv` | Combined stroke events table from HES APC and ONS deaths. |

### Key columns in `hes_apc_stroke_patients.csv`

| Column | Description |
|--------|-------------|
| `person_id` | Individual identifier. |
| `stroke_date` | Date of the stroke event (`admidate` for first stroke; `epistart` for subsequent strokes). |
| `stroke_count` | Index of this stroke event for the individual (1 = first, 2 = second, etc.). |
| `stroke_type_cips` | Stroke subtype harmonised at CIPS level: `ischaemic`, `haemorrhagic`, or `unknown`. |
| `first_stroke_diagnosis` | `TRUE` if this row is the qualifying first stroke episode. |
| `recurrent_stroke` | `TRUE` if this is a recurrent (subsequent) stroke event. |
| `terminal_node` | Terminal node number from the HES APC decision tree (T1–T7). |
| `terminal_node_description` | Plain-text description of the terminal node. |

### Key columns in `ons_deaths_stroke_patients.csv`

| Column | Description |
|--------|-------------|
| `person_id` | Individual identifier. |
| `date_of_death` | Date of death from ONS records. |
| `stroke_date` | Date assigned to the stroke event (equals `date_of_death` for qualifying records). |
| `stroke_codes_in_death_episode` | All stroke ICD-10 codes found in the death record. |
| `first_stroke_code_death` | The first stroke code identified (used for subtype assignment). |
| `stroke_type_death_episode` | Stroke subtype derived from `first_stroke_code_death`. |

## 7. Logical Decision Trees (Stroke Classification)
A flowchart detailing the logic of the algorithm can be found in the docs folder `docs > flowchart`.

### Part A: HES APC algorithm

The HES APC algorithm processes each individual's episodes chronologically using the following logic:

| Node | Description |
|------|-------------|
| D1 | Does this episode contain a stroke code in any relevant diagnosis position? |
| T1 | No → Not a stroke event |
| D2 | Is this the first episode with a stroke code (no prior qualifying stroke)? |
| D3 | First record: is the code in a valid position for a **first** stroke? |
| T2 | No → Not a stroke event (code not in valid first-stroke position) |
| T3 | Yes → **First stroke event** |
| D4 | Subsequent record: is this episode part of the same CIPS as the last qualifying stroke? |
| T4 | Yes → Not a stroke event (same CIPS as prior stroke) |
| D5 | Is the code in a valid position for a **subsequent** stroke? |
| T5 | No → Not a stroke event (code not in valid subsequent position) |
| D6 | Is this episode within the washout period from the last qualifying stroke? |
| T6 | Yes → Not a stroke event (within washout period) |
| T7 | No → **Recurrent stroke event** |

### Part B: ONS deaths algorithm

The ONS deaths algorithm applies the following logic to each death record containing a stroke code:

| Node | Description |
|------|-------------|
| T0 | No stroke ICD-10 code in any relevant death certificate position → excluded |
| D1 | Is there a corresponding HES APC record documenting an in-hospital death? (discharge ≤1 day from death AND dismeth = `"4"` OR disdest = `"79"`) |
| T1 | Yes → Excluded (event captured by HES APC algorithm) |
| D2 | Is there a qualifying HES APC stroke within the washout period prior to death? |
| T2 | Yes → Excluded (assumed to relate to the prior HES stroke) |
| D3 | Is there ANY prior qualifying HES APC stroke? |
| D4 | No prior HES stroke: is the code in a valid position for a **first** stroke death? |
| T3 | No → Not a stroke event |
| T4 | Yes → **First stroke event** |
| D5 | Prior HES stroke exists: is the code in a valid position for a **subsequent** stroke death? |
| T5 | No → Not a stroke event |
| T6 | Yes → **Subsequent stroke event** |

## 8. Requirements

### Input columns required to run the algorithm 
See file required_columns.csv in the docs folder `docs > required_columns.csv` for list of columns required in the HES APC or ONS DEATHS data which you must add to the relevant folders.Case does not matter as the pipeline will convert to lowercase. 

### Software and R packages

The pipeline was built under R version 4.4.3 (2025-02-28 ucrt).

The following R packages, available on CRAN, are required:

- [tidyverse](https://cran.r-project.org/web/packages/tidyverse/index.html)
- [lubridate](https://cran.r-project.org/web/packages/lubridate/index.html)
- [janitor](https://cran.r-project.org/web/packages/janitor/index.html)
- [glue](https://cran.r-project.org/web/packages/glue/index.html)
- [here](https://cran.r-project.org/web/packages/here/index.html)
- [testthat](https://cran.r-project.org/web/packages/testthat/index.html)
- [fs](https://cran.r-project.org/web/packages/fs/index.html)

## 9. Limitations of the Algorithm

The algorithm has been developed using HES APC data - as with all electronic health records, there will be a delay between the patient event and the data being coded and available. This algorithm may not be suitable for all use cases.

NHS administrative data organises records by Hospital Spells and Episodes, each recorded as a single row per patient. A stroke occurring after admission will be coded to the start date of the episode, and as such the stroke date may not be accurate to the day of the event.

The washout period between stroke events (default: 30 days) is applied to avoid counting a continuation of the same clinical episode as a new event. This period is user-configurable in `parameters.R`.

Stroke subtype is assigned using the **first** stroke ICD-10 code identified per episode. Where a CIPS contains episodes with more than one distinct subtype, the CIPS-level subtype is set to `"unknown"`. Users extending the code list to 4-character codes should ensure that the diagnosis column positions in `parameters.R` are updated accordingly.


## 10. Contributors

- *Laura Sherlock, BHF Data Science Centre*

## 11. Contact Details

Should you have any suggestions for improvements to the algorithm and/or related documentation, or should you have any questions, please email the BHF Health Data Science team at bhfdsc_hds@hdruk.ac.uk.
<br>
<br>
<br>
