# Databricks notebook source
# MAGIC %run "./project_config"

# COMMAND ----------

import os
print("PROJECT_FOLDER:", os.environ.get('PROJECT_FOLDER'))
print("PROJECT_RUNTIME_FOLDER:", os.environ.get('PROJECT_RUNTIME_FOLDER'))

# COMMAND ----------

import os
runtime = os.environ.get('PROJECT_RUNTIME_FOLDER')
print("config dir exists:", os.path.exists(f'{runtime}/config'))
print("table_directory exists:", os.path.exists(f'{runtime}/config/table_directory.json'))

# COMMAND ----------

# MAGIC %run "./hds_functions"

# COMMAND ----------

from functions import load_table, save_table, read_csv_file, write_csv_file
import re
import os
from pyspark.sql import functions as f
from pyspark.sql.window import Window

# COMMAND ----------

_runtime_folder = os.environ['PROJECT_RUNTIME_FOLDER']

# COMMAND ----------

# MAGIC
# MAGIC %md
# MAGIC # 1 Select columns 

# COMMAND ----------

hes_apc = load_table('hes_apc', method = 'hes_apc')

hes_apc = hes_apc.toDF(*[c.lower() for c in hes_apc.columns])

general_columns = [
    'person_id', 'epikey', 'epiorder', 'epistat',
    'epistart', 'epiend', 'admidate', 'disdate',
    'admisorc', 'admimeth', 'disdest', 'dismeth',
    'procode3', 'procode5', 'tretspef', 'classpat'
]

diagnosis_3_columns = [col for col in list(hes_apc.columns) if re.match(r'^diag_3_\d\d$', col)]
diagnosis_4_columns = [col for col in list(hes_apc.columns) if re.match(r'^diag_4_\d\d$', col)]
operation_3_columns = [col for col in list(hes_apc.columns) if re.match(r'^opertn_3_\d\d$', col)]
operation_4_columns = [col for col in list(hes_apc.columns) if re.match(r'^opertn_4_\d\d$', col)]


hes_apc_cleaned = (
    hes_apc
    .select(general_columns + diagnosis_3_columns + diagnosis_4_columns + operation_3_columns + operation_4_columns)
)


# COMMAND ----------

# MAGIC
# MAGIC %md
# MAGIC # 2 Cleaning
# MAGIC

# COMMAND ----------

# MAGIC
# MAGIC %md
# MAGIC ## 2.1 Null dates

# COMMAND ----------

# Null bad dates: 1800-01-01 and 1801-01-01
hes_apc_cleaned = (
    hes_apc_cleaned
    .withColumn(
        'epistart',
        f.when(
            (f.col('epistart') != f.to_date(f.lit('1800-01-01')))
            & (f.col('epistart') != f.to_date(f.lit('1801-01-01'))),
            f.col('epistart')
        )
    )
    .withColumn(
        'epiend',
        f.when(
            (f.col('epiend') != f.to_date(f.lit('1800-01-01')))
            & (f.col('epiend') != f.to_date(f.lit('1801-01-01'))),
            f.col('epiend')
        )
    )
    .withColumn(
        'admidate',
        f.when(
            (f.col('admidate') != f.to_date(f.lit('1800-01-01')))
            & (f.col('admidate') != f.to_date(f.lit('1801-01-01'))),
            f.col('admidate')
        )
    )
    .withColumn(
        'disdate',
        f.when(
            (f.col('disdate') != f.to_date(f.lit('1800-01-01')))
            & (f.col('disdate') != f.to_date(f.lit('1801-01-01'))),
            f.col('disdate')
        )
    )
)

# COMMAND ----------

# MAGIC
# MAGIC %md
# MAGIC ## 2.2 Episode start/end dates

# COMMAND ----------

hes_apc_cleaned = (
    hes_apc_cleaned
    .withColumn(
        'epistart_gt_epiend',
        f.when(
            f.col('epistart') > f.col('epiend'),
            f.lit(1)
        )
    )
    .withColumn('epistart_temp', f.col('epistart'))
    .withColumn('epiend_temp', f.col('epiend'))
    .withColumn(
        'epistart',
        f.when(
            f.col('epistart_gt_epiend') == f.lit(1),
            f.col('epiend_temp')
        )
        .otherwise(f.col('epistart_temp'))
    )
    .withColumn(
        'epiend',
        f.when(
            f.col('epistart_gt_epiend') == f.lit(1),
            f.col('epistart_temp')
        )
        .otherwise(f.col('epiend_temp'))
    )
)

# COMMAND ----------

# MAGIC
# MAGIC %md
# MAGIC ## 2.3 Impute ADMIDATE

# COMMAND ----------

# Accept epistart as admidate if admidate is missing, epistart is known,
# epiorder is 1 and no evidence of inter-provider transfer
hes_apc_cleaned = (
    hes_apc_cleaned
    .withColumn(
        'admidate',
        f.when(
            f.col('admidate').isNull() 
            & f.col('epistart').isNotNull() 
            & (f.col('epiorder') == f.lit(1))
            & (~f.col('admimeth').isin(['2B', '81']))
            & (~f.col('admisorc').isin(['51', '52', '53'])),
            f.col('epistart')
        )
        .otherwise(f.col('admidate'))
    )
)

save_table(df = hes_apc_cleaned, table = 'hes_apc_cleaned')

# COMMAND ----------

# MAGIC %md
# MAGIC # 3 Filter out bad episodes

# COMMAND ----------

# MAGIC
# MAGIC %md
# MAGIC ## 3.1 Inclusion criteria

# COMMAND ----------

# Inclusion cirteria: column names and SQL expression
inclusion_criteria = {
    'valid_epikey': "epikey IS NOT NULL",
    'valid_person_id': "person_id IS NOT NULL",
    'valid_procode': "procode5 IS NOT NULL",
    'valid_epistart': "epistart IS NOT NULL",
    'valid_epiend': "epiend IS NOT NULL",
    'valid_admidate': "admidate IS NOT NULL",
    'finished_episode': "epistat = 3",
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

# MAGIC
# MAGIC %md
# MAGIC ## 3.2 Create inclusion flags

# COMMAND ----------


hes_apc_cleaned = load_table('hes_apc_cleaned')

# Create criteria condition flags
for column_name, sql_expression in inclusion_criteria.items():
    hes_apc_cleaned = (
        hes_apc_cleaned
        .withColumn(column_name, f.expr(sql_expression))
    )

hes_apc_cleaned = (
    hes_apc_cleaned
    .fillna(False, list(inclusion_criteria.keys()))
    .withColumn('criteria_0', f.lit(True))
)

# Create inclusion flags
for index, column_name in enumerate(inclusion_criteria.keys()):
    hes_apc_cleaned = (
        hes_apc_cleaned
        .withColumn(f'criteria_{index + 1}', f.col(f'criteria_{index}') & f.col(column_name))
    )

    if index + 1 == len(inclusion_criteria):
        hes_apc_cleaned = hes_apc_cleaned.withColumn('include', f.col(f'criteria_{index + 1}'))


save_table(df = hes_apc_cleaned, table = 'hes_apc_cleaned')


# COMMAND ----------

# MAGIC
# MAGIC %md
# MAGIC ## 3.3 Flowchart

# COMMAND ----------

hes_apc_cleaned = load_table('hes_apc_cleaned')

criteria_columns = [column for column in hes_apc_cleaned.columns if column.startswith('criteria_')]
_win = Window.orderBy('criteria_index')

id_cols = ['epikey', 'person_id']

flowchart = (
    hes_apc_cleaned
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
#(flowchart.toPandas().to_csv('outputs/flowchart_hes_cleaning.csv', index = False))
flowchart.toPandas().to_csv(
    f'{_runtime_folder}/outputs/flowchart_hes_cleaning.csv', 
    index=False
)

# COMMAND ----------

# round to nearest 5 for export
flowchart_hes_cleaning_sdc = (
    flowchart
    .withColumn('n_row', f.round(f.col('n_row')/5) *5)
    .withColumn('n_distinct_id', f.round(f.col('n_distinct_id')/5) *5)
    .withColumn('excluded_rows', f.round(f.col('excluded_rows')/5) *5)
    .withColumn('excluded_ids', f.round(f.col('excluded_ids')/5) *5)
    )

write_csv_file(df = flowchart_hes_cleaning_sdc, path = "./outputs/flowchart_hes_cleaning_sdc.csv")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3.4 Filter rows

# COMMAND ----------


hes_apc_cleaned = load_table('hes_apc_cleaned')

hes_apc_cleaned = (
    hes_apc_cleaned
    .filter(f.col('include'))
    .drop(*criteria_columns)
)

save_table(df = hes_apc_cleaned, table = 'hes_apc_cleaned')
