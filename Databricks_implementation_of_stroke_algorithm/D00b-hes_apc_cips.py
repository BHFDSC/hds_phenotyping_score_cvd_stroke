# Databricks notebook source
# MAGIC %md
# MAGIC ## 1. Setup

# COMMAND ----------

# MAGIC %run "./project_config"

# COMMAND ----------

# %run "./hds_functions"

# COMMAND ----------

from functions import load_table, save_table
import re
from pyspark.sql import functions as f
from pyspark.sql.window import Window

# COMMAND ----------

# MAGIC %md
# MAGIC # 2. Provider spell

# COMMAND ----------

hes_apc_cips_episodes = load_table('hes_apc_cleaned')

hes_apc_cips_episodes = (hes_apc_cips_episodes
.withColumn('epikey', f.col('epikey').cast('string'))
)


# Define transit flag
hes_apc_cips_episodes = (
    hes_apc_cips_episodes
    .withColumn(
        'transit',
        f.when(
            (~f.col('admisorc').isin(['51', '52', '53']))
            & (~f.col('admimeth').isin(['2B', '81']))
            & (f.col('disdest').isin(['51', '52', '53'])),
            f.lit(1)
        )
        .when(
            (
                (f.col('admisorc').isin(['51', '52', '53']))
                | (f.col('admimeth').isin(['2B', '81']))
            )
            & (f.col('disdest').isin(['51', '52', '53'])),
            f.lit(2)
        )
        .when(
            (
                (f.col('admisorc').isin(['51', '52', '53']))
                | (f.col('admimeth').isin(['2B', '81']))
            )
            & (~f.col('disdest').isin(['51', '52', '53'])),
            f.lit(3)
        )
        .otherwise(0)
    )
)

# Provider spell grouping and ordering
window_p_spell_grouping = (
    Window.partitionBy('person_id', 'procode5')
    .orderBy('epistart', 'epiend', 'epiorder', 'transit', 'epikey')
)

# Create lag columns
hes_apc_cips_episodes = (
    hes_apc_cips_episodes
    .withColumn('previous_admidate', f.lag('admidate').over(window_p_spell_grouping))
    .withColumn('previous_epistart', f.lag('epistart').over(window_p_spell_grouping))
    .withColumn('previous_dismeth', f.lag('dismeth').over(window_p_spell_grouping))
    .withColumn('previous_epiend', f.lag('epiend').over(window_p_spell_grouping))
)

# An episode is considered to be part of the same provider spell as the previous 
# episode if one of the following is true:
# 1. `admidate` of the current episode is the same as for the previous episode
# 2. `epistart` of the current episode is the same as for the previous episode
# 3. The method of discharge of the previuos episode is an intra-provider transfer (DISMETH is 8 or 9)
#    and the episode start date (epistart) of the current episode matches the episode end date 
#    of the previous episode (epiend)

hes_apc_cips_episodes = (
    hes_apc_cips_episodes
    .withColumn(
        'new_p_spell',
        f.when(
            (f.col('admidate') == f.col('previous_admidate')),
            f.lit(0)
        )
        .when(
            (f.col('epistart') == f.col('previous_epistart')),
            f.lit(0)
        )
        .when(
            (f.col('previous_dismeth').isin(['8', '9'])) & (f.col('epistart') == f.col('previous_epiend')),
            f.lit(0)
        )
        .otherwise(1),
    )
    .withColumn('p_spell_order', f.sum(f.col('new_p_spell')).over(window_p_spell_grouping))
    .withColumn(
        'p_spell_id',
        f.concat(
            f.col('person_id'), f.lit('-'), f.col('procode5'), f.lit('-'),
            f.col('p_spell_order')
        )
    )
)

# Calculate episode order, episode count, first and last episode flags within each provider spell
window_p_spell_id_ordered = (
    Window.partitionBy('p_spell_id')
    .orderBy('epistart', 'epiend', 'epiorder', 'transit', 'epikey')
)

window_p_spell_id_grouped = (
    Window.partitionBy('p_spell_id')
)

hes_apc_cips_episodes = (
    hes_apc_cips_episodes
    .withColumn(
        'p_spell_epiorder',
        f.row_number().over(window_p_spell_id_ordered)
    )
    .withColumn(
        'p_spell_epi_count',
        f.max(f.col('p_spell_epiorder')).over(window_p_spell_id_grouped)
    )
    .withColumn(
        'p_spell_first_episode',
        f.when(
            f.col('p_spell_epiorder') == f.lit(1),
            f.lit(1)
        )
    )
    .withColumn(
        'p_spell_last_episode',
        f.when(
            f.col('p_spell_epiorder') == f.col('p_spell_epi_count'),
            f.lit(1)
        )
    )
)

save_table(df = hes_apc_cips_episodes, table = 'hes_apc_cips_episodes')

# COMMAND ----------

hes_apc_cips_episodes = load_table('hes_apc_cips_episodes')

p_spell_first_episode = (
    hes_apc_cips_episodes
    .filter(f.col('p_spell_first_episode') == f.lit(1))
    .select(
        'person_id', 'procode5', 'p_spell_id', 'p_spell_order',
        f.col('epistart').alias('p_spell_epistart'),
        f.col('admidate').alias('p_spell_admidate'),
        f.col('admisorc').alias('p_spell_admisorc'),
        f.col('admimeth').alias('p_spell_admimeth')
    )
)

p_spell_last_episode = (
    hes_apc_cips_episodes
    .filter(f.col('p_spell_last_episode') == f.lit(1))
    .select(
        'person_id', 'procode5', 'p_spell_id', 'p_spell_order',
        f.col('epiend').alias('p_spell_epiend'),
        f.col('disdate').alias('p_spell_disdate'),
        f.col('disdest').alias('p_spell_disdest'),
        f.col('dismeth').alias('p_spell_dismeth')
    )
)

hes_apc_cips_provider_spells = (
    p_spell_first_episode
    .join(
        p_spell_last_episode,
        on = ['person_id', 'procode5', 'p_spell_order', 'p_spell_id'],
        how = 'full'
    )
)

save_table(df = hes_apc_cips_provider_spells, table = 'hes_apc_cips_provider_spells')

# COMMAND ----------

hes_apc_cips_provider_spells = load_table('hes_apc_cips_provider_spells')

# Obtain previous epiend and disdest 
window_cips_ordered = (
    Window.partitionBy('person_id')
    .orderBy('p_spell_admidate', 'p_spell_epistart', 'p_spell_disdate', 'procode5', 'p_spell_order')
)

hes_apc_cips_provider_spells = (
    hes_apc_cips_provider_spells
    .withColumn('prev_p_spell_epiend', f.lag('p_spell_epiend').over(window_cips_ordered))
    .withColumn('prev_p_spell_disdest', f.lag('p_spell_disdest').over(window_cips_ordered))
)

# A provider spell is considered to be part of the same CIPS as the previous provider spell 
# if `epistart` is not more than 3 days later than `epiend` of the previous spell and one of 
# the following is true:
# 1. The discharge destination of the previous spell is another hospital (`disdest` is 51, 52 or 53)
# 2. The source of admission of the current spell another hospital (`admisorc` is 51, 52 or 53)
# 3. The method of admission of the current spell is a transfer ('admimeth` is 2B or 81)

hes_apc_cips_provider_spells = (
    hes_apc_cips_provider_spells
    .withColumn(
        'new_cips',
        f.when(
            (f.datediff(f.col('p_spell_epistart'), f.col('prev_p_spell_epiend')) <= f.lit(3))
            & (
                f.col('prev_p_spell_disdest').isin(['51', '52', '53'])
                | f.col('p_spell_admisorc').isin(['51', '52', '53'])
                | f.col('p_spell_admimeth').isin(['2B', '81'])
            ),
            f.lit(0)
        )
        .otherwise(1),
    )
    .withColumn('cips_order', f.sum(f.col('new_cips')).over(window_cips_ordered))
    .withColumn(
        'cips_id',
        f.concat(f.col('person_id'), f.lit('-'), f.col('cips_order'))
    )
)

# Calculate spell order, spell count, first and last spell flags within each CIPS
window_cips_id_ordered = (
    Window.partitionBy('cips_id')
    .orderBy('p_spell_admidate', 'p_spell_epistart', 'p_spell_disdate', 'procode5', 'p_spell_order')
)

window_cips_id_grouped = (
    Window.partitionBy('cips_id')
)

hes_apc_cips_provider_spells = (
    hes_apc_cips_provider_spells
    .withColumn(
        'cips_spell_order',
        f.row_number().over(window_cips_id_ordered)
    )
    .withColumn(
        'cips_spell_count',
        f.max(f.col('cips_spell_order')).over(window_cips_id_grouped)
    )
    .withColumn(
        'cips_first_spell',
        f.when(
            f.col('cips_spell_order') == f.lit(1),
            f.lit(1)
        )
    )
    .withColumn(
        'cips_last_spell',
        f.when(
            f.col('cips_spell_order') == f.col('cips_spell_count'),
            f.lit(1)
        )
    )
)

save_table(df = hes_apc_cips_provider_spells, table = 'hes_apc_cips_provider_spells')

# COMMAND ----------

hes_apc_cips_provider_spells = load_table('hes_apc_cips_provider_spells')

cips_first_spell = (
    hes_apc_cips_provider_spells
    .filter(f.col('cips_first_spell') == f.lit(1))
    .select(
        'person_id', 'cips_id', 'cips_order',
        f.col('p_spell_epistart').alias('cips_epistart'),
        f.col('p_spell_admidate').alias('cips_admidate'),
        f.col('p_spell_admisorc').alias('cips_admisorc'),
        f.col('p_spell_admimeth').alias('cips_admimeth')
    )
)

cips_last_spell = (
    hes_apc_cips_provider_spells
    .filter(f.col('cips_last_spell') == f.lit(1))
    .select(
        'person_id', 'cips_id', 'cips_order',
        f.col('p_spell_epiend').alias('cips_epiend'),
        f.col('p_spell_disdate').alias('cips_disdate'),
        f.col('p_spell_disdest').alias('cips_disdest'),
        f.col('p_spell_dismeth').alias('cips_dismeth')
    )
)

hes_apc_cips_cips = (
    cips_first_spell
    .join(
        cips_last_spell,
        on = ['person_id', 'cips_order', 'cips_id'],
        how = 'full'
    )
)

save_table(df = hes_apc_cips_cips, table = 'hes_apc_cips_cips')

# COMMAND ----------

hes_apc_cips_provider_spells = load_table('hes_apc_cips_provider_spells')
hes_apc_cips_cips = load_table('hes_apc_cips_cips')

hes_apc_cips_provider_spells = (
    hes_apc_cips_provider_spells
    .join(
        hes_apc_cips_cips,
        on = ['person_id', 'cips_order', 'cips_id'],
        how = 'left'
    )
)

save_table(df = hes_apc_cips_provider_spells, table = 'hes_apc_cips_provider_spells')

# COMMAND ----------

hes_apc_cips_episodes = load_table('hes_apc_cips_episodes')
hes_apc_cips_provider_spells = load_table('hes_apc_cips_provider_spells')

hes_apc_cips_episodes = (
    hes_apc_cips_episodes
    .join(
        hes_apc_cips_provider_spells
        .drop(*['procode5', 'p_spell_order']),
        on = ['person_id', 'p_spell_id'],
        how = 'left'
    )
)

save_table(df = hes_apc_cips_episodes, table = 'hes_apc_cips_episodes')