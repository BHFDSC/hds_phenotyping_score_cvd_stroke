# Databricks notebook source
# MAGIC %md
# MAGIC ## 1. Setup

# COMMAND ----------

# MAGIC %run "./project_config"

# COMMAND ----------

from functions import load_table, save_table, write_csv_file
from pyspark.sql import functions as f
from pyspark.sql.window import Window

# COMMAND ----------

# %run "./hds_functions"

# COMMAND ----------

# MAGIC %run "./parameters"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Load stroke deaths data

# COMMAND ----------

deaths_stroke = load_table('deaths_algo_stroke_patients')
deaths_stroke = (
    deaths_stroke
    .filter("qualify")
    .select(
        'person_id',
        f.col('date_of_death').alias('stroke_date'),
        f.col('stroke_type_death_episode').alias('stroke_subtype'),
        f.lit('ONS Mortality').alias('data_source')
    )
)


# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Load HES APC strokes data

# COMMAND ----------

hes_apc_stroke = (
    load_table('hes_apc_algo_stroke_patients')
    .filter("qualify")
    .select(
        'person_id',
        'stroke_date',
        f.col('stroke_type_cips').alias('stroke_subtype'),
        f.lit('HES-APC').alias('data_source')
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Curate stroke events table

# COMMAND ----------

deaths_single = load_table('deaths_single')

_win_id = Window.partitionBy('person_id')
_win_id_ordered = Window.partitionBy('person_id').orderBy('stroke_date', 'data_source')

fatal_stroke_definition = int(fatal_stroke_definition)

stroke_events = (
    hes_apc_stroke
    .unionByName(deaths_stroke)
    .join(
        deaths_single
        .select('person_id', 'date_of_death'),
        on = 'person_id', how = 'left'
    )
    .withColumn(
        'stroke_index',
        f.row_number().over(_win_id_ordered)
    )
    .withColumn(
        'stroke_total_count',
        f.max('stroke_index').over(_win_id)
    )
    .withColumn(
        'death_within_fatal_window', # fatal_window set in parameters as 'fatal_stroke_definition'
        f.when(
            (f.col("date_of_death").isNotNull()) &
            (f.col("stroke_date").isNotNull()) &
            (fatal_stroke_definition > 0) &
            (f.datediff(f.col("date_of_death"), f.col("stroke_date")) < fatal_stroke_definition),
            f.lit(True)
        ).otherwise(False)
    )
    .withColumn(
        'stroke_fatal_type',
        f.when(
            f.expr("(stroke_index = stroke_total_count) AND (death_within_fatal_window)"),
            f.lit('Fatal')
        )
        .otherwise('Non-fatal')
    )
    .withColumn('stroke_first_or_subsequent', f.when(f.col('stroke_index')== 1, f.lit('First')).otherwise(f.lit('Subsequent')))
    .select('person_id', 'stroke_date', 'data_source', 'stroke_index', 'stroke_total_count', 'stroke_first_or_subsequent','stroke_subtype', 'stroke_fatal_type')
)

save_table(df = stroke_events, table = 'stroke_events')

# COMMAND ----------

stroke_events = load_table('stroke_events')

display(
    stroke_events
    .groupBy('stroke_index', 'data_source')
    .agg(
        f.count('*').alias('n')
    )
    .orderBy('stroke_index', 'data_source')
)

stroke_events_summary_index= (
    stroke_events
    .groupBy('stroke_index', 'data_source')
    .agg(f.count('*').alias('n'))
    .orderBy('stroke_index', 'data_source')
    .withColumn('n', f.round(f.col('n')/5, 0)*5)
    .filter(f.col('n')>=10)
)

write_csv_file(df = stroke_events_summary_index, path = './outputs/stroke_events_summary_index_sdc.csv')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Summarise by data sorce (HES vs deaths) and index (first or subsequent)

# COMMAND ----------

stroke_events = load_table('stroke_events')

display(
    stroke_events
    .groupBy('stroke_first_or_subsequent', 'data_source')
    .agg(
        f.count('*').alias('n')
    )
    .orderBy('stroke_first_or_subsequent', 'data_source')
)

stroke_events_summary_first_sub= (
    stroke_events
    .groupBy('stroke_first_or_subsequent', 'data_source')
    .agg(f.count('*').alias('n'))
    .orderBy('stroke_first_or_subsequent', 'data_source')
    .withColumn('n', f.round(f.col('n')/5, 0)*5)
    .filter(f.col('n')>=10)
)

write_csv_file(df = stroke_events_summary_first_sub, path = './outputs/stroke_events_summary_first_sub_sdc.csv')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Summarise by data source (HES or deaths) and index (first or subsequent) and fatal (fatal or non-fatal)

# COMMAND ----------

stroke_events_fatal = load_table('stroke_events')

display(
    stroke_events_fatal
    .groupBy('stroke_first_or_subsequent', 'data_source', 'stroke_fatal_type')
    .agg(
        f.count('*').alias('n')
    )
    .orderBy('stroke_first_or_subsequent', 'data_source', 'stroke_fatal_type')
)

stroke_events_summary_fatal= (
    stroke_events_fatal
    .groupBy('stroke_first_or_subsequent', 'data_source' , 'stroke_fatal_type')
    .agg(f.count('*').alias('n'))
    .orderBy('stroke_first_or_subsequent', 'data_source', 'stroke_fatal_type')
    .withColumn('n', f.round(f.col('n')/5, 0)*5)
    .filter(f.col('n')>=10)
)

write_csv_file(df = stroke_events_summary_fatal, path = './outputs/stroke_events_summary_fatal_sdc.csv')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Summarise by data source (HES vs deaths) and index (first or subsequent) and subtype

# COMMAND ----------

stroke_events_subtype = load_table('stroke_events')

display(
    stroke_events_subtype
    .groupBy('stroke_first_or_subsequent', 'data_source', 'stroke_subtype')
    .agg(
        f.count('*').alias('n')
    )
    .orderBy('stroke_first_or_subsequent', 'data_source', 'stroke_subtype')
)

stroke_events_summary_subtype= (
    stroke_events_subtype
    .groupBy('stroke_first_or_subsequent', 'data_source' , 'stroke_subtype')
    .agg(f.count('*').alias('n'))
    .orderBy('stroke_first_or_subsequent', 'data_source', 'stroke_subtype')
    .withColumn('n', f.round(f.col('n')/5, 0)*5)
    .filter(f.col('n')>=10)
)

write_csv_file(df = stroke_events_summary_subtype, path = './outputs/stroke_events_summary_subtype_sdc.csv')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Summarise by data source (HES vs deaths) and index (first or subsequent) and subtype and fatal (fatal or non-fatal)

# COMMAND ----------

stroke_events_subtype_fatal = load_table('stroke_events')

display(
    stroke_events_subtype_fatal
    .groupBy('stroke_first_or_subsequent', 'data_source', 'stroke_subtype', 'stroke_fatal_type')
    .agg(
        f.count('*').alias('n')
    )
    .orderBy('stroke_first_or_subsequent', 'data_source', 'stroke_subtype', 'stroke_fatal_type')
)

stroke_events_summary_subtype_fatal= (
    stroke_events_subtype_fatal
    .groupBy('stroke_first_or_subsequent', 'data_source' , 'stroke_subtype', 'stroke_fatal_type')
    .agg(f.count('*').alias('n'))
    .orderBy('stroke_first_or_subsequent', 'data_source', 'stroke_subtype', 'stroke_fatal_type')
    .withColumn('n', f.round(f.col('n')/5, 0)*5)
    .filter(f.col('n')>=10)
)

write_csv_file(df = stroke_events_summary_subtype_fatal, path = './outputs/stroke_events_summary_subtype_fatal_sdc.csv')