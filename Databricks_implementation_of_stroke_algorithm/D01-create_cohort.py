# Databricks notebook source
# MAGIC %md
# MAGIC ## 1. Setup

# COMMAND ----------

# MAGIC %run "./project_config"

# COMMAND ----------

from functions import load_table, save_table, first_row, write_csv_file, read_csv_file
from pyspark.sql import functions as f
from pyspark.sql import Window

# COMMAND ----------

# %run "./hds_functions"

# COMMAND ----------

# MAGIC %run "./parameters"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Load demographics

# COMMAND ----------

# Select key demographic columns, define row ID & study dates
cohort = (
    load_table('demographics')
    .select(
        f.monotonically_increasing_id().alias('row_id'),
        'person_id', 'date_of_birth', 'sex', 'ethnicity_5_group',
        'in_gdppr', 'death_flag', 'date_of_death', 'lsoa'
    )
    .withColumn('study_start_date', f.to_date(f.lit(study_start_date)))
    .withColumn('study_end_date', f.to_date(f.lit(study_end_date)))
    .withColumn('min_age', (f.lit(min_age)))
    .withColumn("min_age", f.col("min_age").cast("int"))
    .withColumn('max_age', (f.lit(max_age)))
    .withColumn("max_age", f.col("max_age").cast("int"))
)

save_table(df = cohort, table ='cohort')


# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Join GDPPR and extract dates

# COMMAND ----------

cohort = load_table('cohort')

cohort = (
    cohort
    .join(
        load_table('gdppr', method = 'gdppr')
        .filter('person_id IS NOT NULL')
        .groupBy('person_id')
        .agg(
            f.min('record_date').alias('min_gdppr_record_date'),
            f.min('date').alias('min_gdppr_date')
        ),
        on = 'person_id', how = 'left'
    )
)

save_table(df = cohort, table = 'cohort')


# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Join HES APC and flag prior stroke

# COMMAND ----------


cohort = load_table('cohort')

# filter to include only participnats who do not have a stroke code BEFORE the study start date
cohort = (
    cohort
    .join(
        load_table('hes_apc_diagnosis')
        .withColumn('stroke_present', f.when(f.col('code').isin(*stroke_codes), 1).otherwise(0))
        .withColumn('stroke_present_date', f.when(f.col('stroke_present') == 1, f.col('epistart')).otherwise(None))
        .filter(f.col("epistart") < study_start_date)
        .groupBy('person_id')
        .agg(
            f.max('stroke_present').alias('prior_stroke'),
            f.min('stroke_present_date').alias('prior_stroke_date')
        ),
        on='person_id', how='left'
    )
)


save_table(df=cohort, table='cohort')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Flag valid_nhs_number and calculate age_at_study_start

# COMMAND ----------

token_pseudo_id_lookup = load_table('token_pseudo_id_lookup')
cohort =load_table('cohort')

token_pseudo_id_lookup = (
    token_pseudo_id_lookup
    .select(
        f.col('pseudo_id').alias('person_id'),
        'valid_nhs_number'
    )
)

cohort = (
    cohort
    .withColumn('age_study_start', f.round(f.datediff('study_start_date', 'date_of_birth')/365.25, 2))
    .join(token_pseudo_id_lookup, on = 'person_id', how = 'left')
)


save_table(df=cohort, table='cohort')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Flowchart of inclusion criteria

# COMMAND ----------

cohort = load_table('cohort')


inclusion_criteria = {
    'valid_nhs_number' : "valid_nhs_number = true",
    'valid_age_on_study_start_date': "(age_study_start >= min_age) AND (age_study_start <= max_age)",
    'sex_male_or_female': "(sex = 'F') OR (sex = 'M')",
    'alive_on_study_start': "(date_of_death IS NULL) OR (date_of_death > study_start_date)",
    'valid_or_no_death_record': "(date_of_death IS NULL) OR ((date_of_death IS NOT NULL) AND (death_flag = 1))",
    'record_in_gdppr': "in_gdppr = 1",
    'record_in_gdppr_prior_to_start_date': "(min_gdppr_record_date < study_start_date) OR (min_gdppr_date < study_start_date)",
    'lsoa_in_england': "lsoa LIKE 'E%'",
    'no_history_of_stroke': "prior_stroke IS NULL OR prior_stroke = 0"
}

# Convert dictionary to list of tuples with index starting from 1
inclusion_criteria_list = [("criteria_" + str(i+1), k, v) for i, (k, v) in enumerate(inclusion_criteria.items())]

# Create PySpark DataFrame for inclusion criteria 
df_inclusion_criteria = spark.createDataFrame(
    inclusion_criteria_list,
    schema=['criteria', 'description', 'expression']
)
id_cols = ['row_id', 'person_id']

df_inclusion_columns = (
    cohort
    .select(
        id_cols + 
        [
            *[f.expr(sql_expression).alias(column_name) 
            for column_name, sql_expression in inclusion_criteria.items()]
        ]
    )
    .fillna(False, list(inclusion_criteria.keys()))
    .withColumn('criteria_0', f.lit(True))
)

for index, column_name in enumerate(inclusion_criteria.keys()):
    df_inclusion_columns = (
        df_inclusion_columns
        .withColumn(f'criteria_{index + 1}', f.col(f'criteria_{index}') & f.col(column_name))
    )

    if index + 1 == len(inclusion_criteria):
        df_inclusion_columns = df_inclusion_columns.withColumn('include', f.col(f'criteria_{index + 1}'))

# Create flowchart
criteria_columns = [column for column in df_inclusion_columns.columns if column.startswith('criteria_')]
_win = Window.partitionBy(f.lit(1)).orderBy('criteria_index')

flowchart = (
    df_inclusion_columns
    .select(id_cols + criteria_columns)
    .unpivot(
        ids = id_cols, values = criteria_columns,
        variableColumnName = 'criteria', valueColumnName = 'value'
    )
    .groupBy('criteria')
    .agg(
        f.count(f.when(f.col('value') == True, 1)).alias('n_row'),
        f.countDistinct(f.when(f.col('value') == True, f.col('person_id'))).alias('n_distinct_id')
    )
    .join(
        df_inclusion_criteria,
        on = 'criteria', how = 'left'
    )
    .withColumn('criteria_index', (f.regexp_extract('criteria', r'\d+', 0)).cast('int'))
    .withColumn('excluded_rows', (f.col('n_row') - f.lag('n_row', 1).over(_win)).cast('int'))
    .withColumn('excluded_ids', (f.col('n_distinct_id') - f.lag('n_distinct_id', 1).over(_win)).cast('int'))
    .orderBy(['criteria_index'])
    .select(
        [
            'criteria_index', 'criteria', 'description', 'expression',
            'n_row', 'n_distinct_id', 'excluded_rows', 'excluded_ids'
        ]
    )
)

display(flowchart)

# Save as .csv
write_csv_file(df = flowchart, path = "./outputs/flowchart_cohort_stroke.csv")


# Join inclusion flag back to cohort table
cohort = (
    cohort
    .join(
        df_inclusion_columns.select('row_id', 'include'),
        on = 'row_id', how = 'left'
    )
    .filter(f.col('include'))
)

save_table(df = cohort, table = 'cohort')

# COMMAND ----------

# round to nearest 5 for export
flowchart_cohort_sdc = (
    flowchart
    .withColumn('n_row', f.round(f.col('n_row')/5) *5)
    .withColumn('n_distinct_id', f.round(f.col('n_distinct_id')/5) *5)
    .withColumn('excluded_rows', f.round(f.col('excluded_rows')/5) *5)
    .withColumn('excluded_ids', f.round(f.col('excluded_ids')/5) *5)
    )

write_csv_file(df = flowchart_cohort_sdc, path = "./outputs/flowchart_cohort_stroke_sdc.csv")

