# Databricks notebook source
# MAGIC %md
# MAGIC ## 1. Setup

# COMMAND ----------

# MAGIC %run "./project_config"

# COMMAND ----------

# MAGIC %run "./hds_functions"

# COMMAND ----------

from hds_functions import load_table, save_table, create_dict_from_csv, map_column_values, read_csv_file, clean_column_names
from pyspark.sql import functions as f
from pyspark.sql.window import Window

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Flag covariates in cohort

# COMMAND ----------


cohort = load_table('cohort')
gdppr = load_table('gdppr', method = 'gdppr')
hes_apc_diagnosis = load_table('hes_apc_diagnosis')

combined_codelist = read_csv_file(
    path = "./codelists/combined_codelist.csv"
)

# HES-APC

codelist_covariate_comorbidities_hes_apc = (
    combined_codelist
    .filter("(data_source = 'HES-APC') AND (variable_type = 'covariate_comorbidities')")
    .select('phenotype', 'code')
)

hes_apc_matched = (
    hes_apc_diagnosis
    .select('person_id', f.col('epistart').alias('date'), 'code')
    .join(
        f.broadcast(codelist_covariate_comorbidities_hes_apc),
        on = 'code', how = 'inner'
    )
    .join(
        cohort
        .select('person_id', 'date_of_birth', 'study_end_date'),
        on = 'person_id', how = 'inner'
    )
    .filter("(date >= date_of_birth) AND (date <= study_end_date)")
)

# GDPPR

codelist_covariate_comorbidities_gdppr = (
    combined_codelist
    .filter("(data_source = 'GDPPR') AND (variable_type = 'covariate_comorbidities')")
    .select('phenotype', 'code')
)

gdppr_matched = (
    gdppr
    .select('person_id', 'date', 'code')
    .join(
        f.broadcast(codelist_covariate_comorbidities_gdppr),
        on = 'code', how = 'inner'
    )
    .join(
        cohort
        .select('person_id', 'date_of_birth', 'study_end_date'),
        on = 'person_id', how = 'inner'
    )
    .filter("(date >= date_of_birth) AND (date <= study_end_date)")
)

matched_combined = (
    hes_apc_matched
    .unionByName(gdppr_matched)
)

matched_agg = (
    matched_combined
    .groupBy('person_id')
    .pivot('phenotype')
    .agg(
        f.min('date').alias('date')
    )
)

cohort = (
    cohort
    .join(
        matched_agg,
        on = 'person_id', how = 'left'
    )
)

save_table(df = cohort, table = 'cohort')


# COMMAND ----------

display(cohort.limit(50))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Flag smoking status in cohort

# COMMAND ----------


cohort = load_table('cohort')
gdppr = load_table('gdppr', method = 'gdppr')

combined_codelist = read_csv_file(
    path = "./codelists/combined_codelist.csv"
)

codelist_covariate_smoking_status_gdppr = (
    combined_codelist
    .filter("(data_source = 'GDPPR') AND (variable_type = 'covariate_smoking')")
    .select('phenotype', 'code')
)

gdppr_matched = (
    gdppr
    .select('person_id', 'date', 'code')
    .join(
        f.broadcast(codelist_covariate_smoking_status_gdppr),
        on = 'code', how = 'inner'
    )
    .join(
        cohort
        .select('person_id', 'date_of_birth', 'study_start_date'),
        on = 'person_id', how = 'inner'
    )
    .filter("(date >= date_of_birth) AND (date <= study_start_date)")
)

matched_agg = (
    gdppr_matched
    .groupBy('person_id')
    .pivot('phenotype')
    .agg(
        f.min('date').alias('date')
    )
)

cohort = (
    cohort
    .join(
        matched_agg,
        on = 'person_id', how ='left'
    )
)

save_table(df = cohort, table = 'cohort')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Join LSOA

# COMMAND ----------

# Index of multiple deprivation
cohort = load_table('cohort')
lsoa_2011 = load_table('lsoa_2011')

lsoa_imd19_mapping = (
    lsoa_2011
    .select(
        f.col('LSOA_2011').alias('lsoa'),
        f.col('IMD_2019_QUINTILES').alias('imd_19_quin'),
    )
    .withColumn(
        'imd_19_quin',
        f.when(f.col('imd_19_quin') == 1, '1 (most deprived)')
        .when(f.col('imd_19_quin') == 5, '5 (least deprived)')
        .otherwise(f.col('imd_19_quin').cast('string'))
    )
)

cohort = (
cohort
.join(lsoa_imd19_mapping, on = 'lsoa', how = 'left')
)

save_table(df = cohort, table = 'cohort')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Join stroke events

# COMMAND ----------

cohort= load_table('cohort')


stroke_events = load_table('stroke_events')

stroke_patients_cohort= (
    stroke_events
    .join(cohort, on = 'person_id', how= 'left')
)


stroke_patients_cohort.count()

display(stroke_patients_cohort)
 
save_table(df = stroke_patients_cohort, table = 'stroke_patients_cohort')