# Databricks notebook source
# MAGIC %md
# MAGIC ## 1. Setup

# COMMAND ----------

# MAGIC %run "./project_config"

# COMMAND ----------

from functions import load_table, save_table, read_csv_file, write_csv_file
import re
from pyspark.sql import functions as f
from pyspark.sql.window import Window
import os

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Cleaning

# COMMAND ----------

deaths_single = load_table('deaths_single')

# convert all column names to lower case
deaths_single = deaths_single.toDF(*[c.lower() for c in deaths_single.columns])

# rename the secondary_cause_cols from s_cod_underlying_1 to cod_mentioned_1, 2 etc
s_cod_cols = sorted(
    [c for c in deaths_single.columns if c.startswith("s_cod_code")],
    key=lambda x: int(re.search(r"\d+$", x).group())
) # list of columns related to secondary causes of death, in numerical order
# map on new names 
rename_map = {old: f"cod_mentioned_{i+1}" for i, old in enumerate(s_cod_cols)} 
for old, new in rename_map.items():
    deaths_single = deaths_single.withColumnRenamed(old, new)

# create list wirth newly names s_cod_mentioned_cols
cod_mentioned_cols =[c for c in deaths_single.columns if c.startswith("cod_mentioned_")]
print(cod_mentioned_cols)

# select required column, rename and ensure date_of_death is in date format
deaths_cleaned = (
    deaths_single
    .select(
        'person_id',
        'date_of_death',
        f.col('s_underlying_cod_icd10').alias('underlying_cod'),
        *cod_mentioned_cols
    )
    .withColumn('date_of_death', f.to_date(f.col('date_of_death')))
)

    # Null bad dates: 1800-01-01 and 1801-01-01
deaths_cleaned = (
    deaths_cleaned
    .withColumn(
        'date_of_death',
        f.when(
            (f.col('date_of_death') != f.to_date(f.lit('1800-01-01')))
            & (f.col('date_of_death') != f.to_date(f.lit('1801-01-01'))),
            f.col('date_of_death')
        )
    )
    )


save_table(deaths_cleaned, 'ons_deaths_cleaned')


# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Inclusion Criteria

# COMMAND ----------

# Inclusion cirteria: column names and SQL expression
inclusion_criteria = {
    'valid_person_id': "person_id IS NOT NULL",
    'valid_death_date': "date_of_death IS NOT NULL",
}

# Convert dictionary to list of tuples with index starting from 1
inclusion_criteria_list = [
    ("criteria_" + str(i+1), k, v)
    for i, (k, v) in enumerate(inclusion_criteria.items())
]

# Create PySpark DataFrame for inclusion criteria 
df_inclusion_criteria = spark.createDataFrame(
    inclusion_criteria_list,
    schema=['criteria', 'description', 'expression']
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Create inclusion flags

# COMMAND ----------

ons_deaths_cleaned = load_table('ons_deaths_cleaned')

# Create criteria condition flags
for column_name, sql_expression in inclusion_criteria.items():
    ons_deaths_cleaned = (
        ons_deaths_cleaned
        .withColumn(column_name, f.expr(sql_expression))
    )

ons_deaths_cleaned = (
    ons_deaths_cleaned
    .fillna(False, list(inclusion_criteria.keys()))
    .withColumn('criteria_0', f.lit(True))
)

# Create inclusion flags
for index, column_name in enumerate(inclusion_criteria.keys()):
    ons_deaths_cleaned = (
        ons_deaths_cleaned
        .withColumn(f'criteria_{index + 1}', f.col(f'criteria_{index}') & f.col(column_name))
    )

    if index + 1 == len(inclusion_criteria):
        ons_deaths_cleaned = ons_deaths_cleaned.withColumn('include', f.col(f'criteria_{index + 1}'))


save_table(df = ons_deaths_cleaned, table = 'ons_deaths_cleaned')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Flowchart

# COMMAND ----------

ons_deaths_cleaned = load_table('ons_deaths_cleaned')

criteria_columns = [column for column in ons_deaths_cleaned.columns if column.startswith('criteria_')]
_win = Window.orderBy('criteria_index')

id_cols = ['person_id']

flowchart = (
    ons_deaths_cleaned
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
    .orderBy('criteria_index')
    .select(
        'criteria_index', 'criteria', 'description', 'expression',
        'n_row', 'n_distinct_id', 'excluded_rows', 'excluded_ids'
    )
)

# Save as .csv
flowchart.toPandas().to_csv(
    f'{os.environ["PROJECT_RUNTIME_FOLDER"]}/outputs/flowchart_ons_deaths_cleaning.csv',
    index=False
)
# (flowchart.toPandas().to_csv('outputs/flowchart_ons_deaths_cleaning.csv', index = False))

# COMMAND ----------

# round to nearest 5 for 
flowchart_ons_deaths_cleaning_sdc = (
    flowchart
    .withColumn('n_row', f.round(f.col('n_row')/5) *5)
    .withColumn('n_distinct_id', f.round(f.col('n_distinct_id')/5) *5)
    .withColumn('excluded_rows', f.round(f.col('excluded_rows')/5) *5)
    .withColumn('excluded_ids', f.round(f.col('excluded_ids')/5) *5)
    )

write_csv_file(df = flowchart_ons_deaths_cleaning_sdc, path = "./outputs/flowchart_ons_deaths_cleaning_sdc.csv")



# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Filter rows

# COMMAND ----------


ons_deaths_cleaned = load_table('ons_deaths_cleaned')

ons_deaths_cleaned = (
    ons_deaths_cleaned
    .filter(f.col('include'))
    .drop(*criteria_columns)
)

save_table(df = ons_deaths_cleaned, table = 'ons_deaths_cleaned')