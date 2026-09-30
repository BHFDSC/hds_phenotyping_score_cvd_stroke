# Databricks notebook source
# MAGIC %md
# MAGIC ## 1. Study setup

# COMMAND ----------

# MAGIC %run "./project_config"

# COMMAND ----------

# MAGIC %run "./parameters"

# COMMAND ----------

# %run "./hds_functions"

# COMMAND ----------

from functions import load_table, save_table, read_csv_file, write_csv_file, map_column_values
import re
from pyspark.sql import functions as f
import pyspark.sql.types as t
from pyspark.sql.window import Window
import pandas as pd
from functools import reduce
from datetime import timedelta

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Curate HES APC

# COMMAND ----------

hes_apc_cips_episodes = load_table('hes_apc_cips_episodes')

cohort = load_table('cohort')

diagnosis_columns_all_positions = (code_positions_first_stroke_hes_apc + code_positions_subsequent_stroke_hes_apc) # concatenating the code position required as outlined in parameters
diagnosis_columns_all_positions=  list(dict.fromkeys(diagnosis_columns_all_positions))# deduplicating list
print(diagnosis_columns_all_positions)

hes_apc_algo_prep = (
    load_table('hes_apc_cips_episodes')
    .select(
        'epikey', 'person_id', 'epistart', 'epiend', 'epiorder',
        'admidate', 'disdate', 'admisorc', 'disdest', 'admimeth', 'dismeth','tretspef',
        f.array(diagnosis_columns_all_positions).alias('diag_array_any'),
        f.array(code_positions_first_stroke_hes_apc).alias('diag_array_first_stroke_positions'),
        f.array(code_positions_subsequent_stroke_hes_apc).alias('diag_array_subsequent_stroke_positions'),
        'cips_id', 'cips_admidate', 'cips_disdate', 'procode5'
    )
   .filter(f"(epistart >= '{study_start_date}') AND (epistart <= '{study_end_date}') AND (person_id IS NOT NULL)") 
    .join(
        cohort
        .select('person_id'),
        on = 'person_id', how = 'inner'
    )
)

save_table(df = hes_apc_algo_prep, table = 'hes_apc_algo_prep')


# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Create DF of people with no stroke codes, and those with at leats one stroke code

# COMMAND ----------

 hes_apc_algo_prep = load_table('hes_apc_algo_prep')

# flag episodes with stroke codes of interest and create flag at person_id level of whether they have had a stroke during the time period

win_id = Window.partitionBy('person_id')

hes_apc_prep = (
    hes_apc_algo_prep
    .withColumn(
        'diag_stroke_any',
        f.when(
            f.size(f.array_intersect(f.col('diag_array_any'),f.array(*[f.lit(c) for c in stroke_codes])))>0,
            f.lit(True)
        ).otherwise(f.lit(False))
    )    
    .withColumn(
        'diag_first_stroke_positions',
        f.when(
            f.size(f.array_intersect(f.col('diag_array_first_stroke_positions'),f.array(*[f.lit(c) for c in stroke_codes])))>0,
            f.lit(True)
        ).otherwise(f.lit(False))
    )   
    .withColumn(
        'diag_subsequent_stroke_positions',
        f.when(
            f.size(f.array_intersect(f.col('diag_array_subsequent_stroke_positions'),f.array(*[f.lit(c) for c in stroke_codes])))>0,
            f.lit(True)
        ).otherwise(f.lit(False))
    )   
    .withColumn(
        'individual_with_stroke',
        f.max('diag_stroke_any').over(win_id)
    )
)

# df of people with no stroke codes during time period
hes_apc_algo_non_stroke_patients = (
    hes_apc_prep
    .filter("individual_with_stroke = False")
    .withColumn('qualify', f.lit(False))
    .withColumn('terminal_node', f.lit(0))
    .withColumn('terminal_node_description', f.lit('T0: individual with no stroke ICD-10 code ever in positions relevant to first OR subsequent stroke'))
)

save_table(df = hes_apc_algo_non_stroke_patients, table = 'hes_apc_algo_non_stroke_patients')

# df of people with at leats one stroke code in HES in a position releveant to first OR subsequent stroke
hes_apc_algo_stroke_patients = (
    hes_apc_prep
    .filter("individual_with_stroke = True")
)

save_table(df = hes_apc_algo_stroke_patients, table = 'hes_apc_algo_stroke_patients')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Curate stroke subtypes

# COMMAND ----------

# Adding stroke subtype - taking the first stroke code per episode. if more than one stroke type per cips then labelling as stroke unknown

hes_apc_algo_stroke_patients =  load_table('hes_apc_algo_stroke_patients')


# 1 Extract FIRST stroke code in the array of stroke codes per episode
def stroke_filter_expr(array_col, stroke_codes):
    like_expr = " OR ".join([f"x LIKE '{c}%'" for c in stroke_codes])
    return f.expr(f"filter({array_col}, x -> {like_expr})")


hes_apc_algo_stroke_patients = hes_apc_algo_stroke_patients.withColumn(
    "stroke_codes_in_episode",
    stroke_filter_expr("diag_array_any", stroke_codes)
)

hes_apc_algo_stroke_patients = hes_apc_algo_stroke_patients.withColumn(
    "first_stroke_code",
    f.when(
        f.size("stroke_codes_in_episode") > 0,
        f.col("stroke_codes_in_episode")[0]
    )
)


# 2 Episode-level subtype - taking only first mentioned stroke per episode

def prefix_match(col, prefixes):
    conditions = [f.col(col).startswith(p) for p in prefixes]
    return reduce(lambda a, b: a | b, conditions)

hes_apc_algo_stroke_patients = hes_apc_algo_stroke_patients.withColumn("stroke_type_episode", f.lit(None))

for subtype, prefixes in stroke_subtype_map.items():
    hes_apc_algo_stroke_patients = hes_apc_algo_stroke_patients.withColumn(
        "stroke_type_episode",
        f.when(prefix_match("first_stroke_code", prefixes), f.lit(subtype))
         .otherwise(f.col("stroke_type_episode"))
    )


# 3 CIPS-level harmonisation


w_cips = Window.partitionBy("person_id", "cips_id")

hes_apc_algo_stroke_patients = hes_apc_algo_stroke_patients.withColumn(
    "stroke_types_in_cips",
    f.collect_set("stroke_type_episode").over(w_cips)
).withColumn(
    "n_subtypes_cips",
    f.size("stroke_types_in_cips")
)


hes_apc_algo_stroke_patients = hes_apc_algo_stroke_patients.withColumn(
    "stroke_type_cips",
    f.when(f.col("n_subtypes_cips") > 1, f.lit("unknown"))
     .otherwise(f.col("stroke_type_episode"))
)

save_table(df = hes_apc_algo_stroke_patients, table = 'hes_apc_algo_stroke_patients')


# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Define function to classify strokes 

# COMMAND ----------

#  outling function hes_apc_stroke_pandas which classify's whether an episode qualify's as a stroke or not - using pandas

# defining function
def hes_apc_stroke_pandas(pdf):

# Sort dataframe by admidate, epistart, epiend, epiorder and epikey
    pdf["admidate"] = pd.to_datetime(pdf["admidate"])
    pdf["epistart"] = pd.to_datetime(pdf["epistart"])
    pdf["epiend"] = pd.to_datetime(pdf["epiend"])

    pdf = pdf.sort_values(by=["admidate", "epistart", "epiend", "epiorder", "epikey"])

    # Row index reset 
    pdf = pdf.reset_index(drop=True)
    pdf["index_num"] = pdf.index

   
    # Initiate new columns
    pdf['qualify'] = False
    pdf['stroke_date'] = pd.NaT
    pdf['stroke_count'] = 0
    pdf['terminal_node'] = pd.NA
    pdf['terminal_node_description'] = pd.NA
    pdf['same_cips_as_last_stroke'] = False
    pdf['first_stroke_diagnosis'] = False
    pdf['recurrent_stroke'] = pd.NA

    # ensure washout parameter is integer
    washout_days = int(washout_between_strokes)

   # last stroke date intitaly set to none to avoid loop breaking in instances wehere we do not have a qualifying prior stroke
    last_valid_stroke_date = None
    last_valid_cips = None

    # stroke count set to 0 intially
    stroke_counter = 0

  
    # Loop over rows
    for index, row in pdf.iterrows():
       
        # D1: Does this episode contain any stroke ICD10 code?
        if not row['diag_stroke_any']:
            pdf.at[index, 'terminal_node'] = 1
            pdf.at[index, 'terminal_node_description'] = 'T1: Not a stroke event'
            continue


        # FIRST QUALIFYING STROKE 
        first_stroke = (last_valid_stroke_date is None)

        # D2: Is this the first record with a pre-specified stroke ICD10-code
        if first_stroke: 

            # D3: Stroke in valid first-stroke ICD position?
            # T2 - Not valid first stroke position
            if not row['diag_first_stroke_positions']:
                pdf.at[index, 'terminal_node'] = 2
                pdf.at[index, 'terminal_node_description'] = 'T2: Not a stroke event - not in valid position for first stroke'
                continue

            # T3 — Valid first stroke
            stroke_counter = 1
            last_valid_stroke_date = row['admidate']
            last_valid_cips = row['cips_id']

            pdf.at[index, 'qualify'] = True
            pdf.at[index, 'stroke_date'] = row['epistart']
            pdf.at[index, 'stroke_count'] = stroke_counter
            pdf.at[index, 'first_stroke_diagnosis'] = True
            pdf.at[index, 'terminal_node'] = 3
            pdf.at[index, 'terminal_node_description'] = 'T3: First stroke event'
            continue


        # SUBSEQUENT STROKE LOGIC

        # D4: Same CIPS as last stroke?
        same_cips = (row['cips_id'] == last_valid_cips)
        pdf.at[index, 'same_cips_as_last_stroke'] = same_cips

        # T4 - Same CIPS as last stroke
        if same_cips:
            pdf.at[index, 'terminal_node'] = 4
            pdf.at[index, 'terminal_node_description'] = 'T4: Not a stroke event - same CIPS as last stroke'
            continue

        # D5: Stroke in valid subsequent-stroke ICD position?
        # T5 - Not in valid position
        if not row['diag_subsequent_stroke_positions']:
            pdf.at[index, 'terminal_node'] = 5
            pdf.at[index, 'terminal_node_description'] = 'T5: Not stroke event - stroke code not in valid subsequent position'
            continue

        # D6: Washout check
        days_since_last = (row['epistart'] - last_valid_stroke_date).days

        # T6: within washout period
        if washout_days > 0 and days_since_last < washout_days:
            pdf.at[index, 'terminal_node'] = 6
            pdf.at[index, 'terminal_node_description'] = f'T6: Not a stroke event - within washout days'
            continue

        # T7: valid recurrent stroke
        stroke_counter += 1
        last_valid_stroke_date = row['epistart']
        last_valid_cips = row['cips_id']

        pdf.at[index, 'qualify'] = True
        pdf.at[index, 'stroke_date'] = row['epistart']
        pdf.at[index, 'stroke_count'] = stroke_counter
        pdf.at[index, 'terminal_node'] = 7
        pdf.at[index, 'terminal_node_description'] = 'T7: Recurrent stroke event'

    return pdf


# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Apply function

# COMMAND ----------

hes_apc_algo_stroke_patients = load_table('hes_apc_algo_stroke_patients')

# Extract the schema of the input DataFrame
input_schema = hes_apc_algo_stroke_patients.schema

# Create a new schema by adding new columns dynamically
new_columns = [
    t.StructField('qualify', t.BooleanType(), True),
    t.StructField('stroke_date', t.DateType(), True),
    t.StructField('stroke_count', t.IntegerType(), True),
    t.StructField('terminal_node', t.IntegerType(), True),
    t.StructField('terminal_node_description', t.StringType(), True),
    t.StructField('first_stroke_diagnosis', t.BooleanType(), True),
    t.StructField('index_num', t.IntegerType(), True),
    t.StructField('same_cips_as_last_stroke', t.BooleanType(), True),
    t.StructField('recurrent_stroke', t.BooleanType(), True)
]

output_schema = t.StructType(input_schema.fields + new_columns)

# apply the stroke alg function to data frame - grouped by person_id
hes_apc_algo_stroke_patients = (
    hes_apc_algo_stroke_patients
    .groupBy('person_id')
    .applyInPandas(
        hes_apc_stroke_pandas,
        schema = output_schema
    )
)

hes_apc_algo_stroke_patients = hes_apc_algo_stroke_patients.withColumn(
    "recurrent_stroke",
    f.col("stroke_count") > 1
)

save_table(df = hes_apc_algo_stroke_patients, table = 'hes_apc_algo_stroke_patients')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Sumarrise terminal nodes

# COMMAND ----------

hes_apc_algo_stroke_patients = load_table('hes_apc_algo_stroke_patients')

display(
    hes_apc_algo_stroke_patients
    .groupBy('terminal_node', 'terminal_node_description')
    .agg(
        f.count('*').alias('n'),
        f.countDistinct('person_id').alias('n_id')
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Flowchart

# COMMAND ----------

flowchart_schema = {

    # D1: Any stroke code?
    'node_d01': {
        'parent_node': None,
        'expression': 'TRUE',
        'description': 'D1: Does this episode have one of the specified stroke ICD-10 codes?'
    },
    'node_t01': {
        'parent_node': 'node_d01',
        'expression': '(diag_stroke_any = FALSE)',
        'description': 'T1: Not a stroke event'
    },

    # D2: Is this the first EVER stroke?
    'node_d02': {
        'parent_node': 'node_d01',
        'expression': '(diag_stroke_any = TRUE)',
        'description': 'D2: Is this the FIRST record with a pre-sepcified stroke ICD-10 code??'
    },

    # D3: For FIRST stroke only is the code in valid first stroke position?
    'node_d03': {
        'parent_node': 'node_d02',
        'expression': '(first_stroke_diagnosis = TRUE)',
        'description': 'D3: Is the stroke code in a valid position for FIRST stroke? (as specified by user in parameters notebook as object  code_positions_first_ stroke_hes_apc)'
    },
    'node_t02': {
        'parent_node': 'node_d03',
        'expression': '(diag_first_stroke_positions = FALSE)',
        'description': 'T2: Not a stroke event - first stroke code not in valid position'
    },

    'node_t03': {
        'parent_node': 'node_d03',
        'expression': '(diag_first_stroke_positions = TRUE)',
        'description': 'T3: First stroke event'
    },

    # SUBSEQUENT STRTOKES
    # D4: Same CIPS as prior stroke
    'node_d04': {
        'parent_node': 'node_d02',
        'expression': '(first_stroke_diagnosis = FALSE)',
        'description': 'D4: Is this episode part of the same continuous inpatient spell (CIPS) as the previous recorded stroke event?'
    },

    'node_t04': {
        'parent_node': 'node_d04',
        'expression': '(same_cips_as_last_stroke = TRUE)',
        'description': 'T4: Not a stroke event - same CIPS as prior stroke'
    },

    # D5: Valid subsequent stroke ICD position?
    'node_d05': {
        'parent_node': 'node_d04',
        'expression': '(same_cips_as_last_stroke = FALSE)',
        'description': 'D5: Is the stroke code in a valid position for SUBSEQUENT stroke? (as specified by user in parameters notebook as object  code_positions_subsequent _stroke_hes_apc)'
    },

    'node_t05': {
        'parent_node': 'node_d05',
        'expression': '(diag_subsequent_stroke_positions = FALSE)',
        'description': 'T5: Not a stroke event - stroke code not in valid subsequent position'
    },

    # D6: Outside washout period?
    'node_d06': {
        'parent_node': 'node_d05',
        'expression': '(diag_subsequent_stroke_positions = TRUE)',
        'description': 'D6: Is the stroke within the specified washout period? (as specified by user in the parameters notebook as object washout_between_strokes)' 
    },
    'node_t06': {
        'parent_node': 'node_d06',
        'expression': '(terminal_node = 6)',    # row was assigned terminal_node = 6 in pandas logic i.e. within washout
        'description': 'T6: Not a stroke event - within washout period'
    },
    'node_t07': {
        'parent_node': 'node_d06',
        'expression': '(terminal_node = 7)',   # row was assigned terminal_node = 7 i.e. not within washout
        'description': 'T7: Recurrent stroke event'
    }
}

node_names = keys_list = list(flowchart_schema.keys())


hes_apc_algo_stroke_patients = load_table('hes_apc_algo_stroke_patients')

for node_name, node_features in flowchart_schema.items():

    if node_features['parent_node'] is None:
        hes_apc_algo_stroke_patients = (
            hes_apc_algo_stroke_patients
            .withColumn(node_name, f.expr(node_features['expression']))
        )
    
    else:
        hes_apc_algo_stroke_patients = (
            hes_apc_algo_stroke_patients
            .withColumn(node_name, f.col(node_features['parent_node']) & f.expr(node_features['expression']))
        )

flowchart_long = (
    hes_apc_algo_stroke_patients 
    .withColumn('row_id', f.row_number().over(Window.orderBy(f.lit(1))))
    .select(['row_id', 'person_id', 'epikey', *node_names])
    .unpivot(
        ids = ['row_id', 'person_id', 'epikey'],
        values = node_names,
        variableColumnName = 'node_id',
        valueColumnName = 'membership'
    )
)

# Create two separate dictionaries
dict_parent_node = {key: value['parent_node'] for key, value in flowchart_schema.items()}
dict_description = {key: value['description'] for key, value in flowchart_schema.items()}

flowchart_summary = (
    flowchart_long
    .groupBy('node_id') \
    .agg(
        f.count(f.when(f.expr("membership = TRUE"), f.lit(1))).alias('n'),
        f.countDistinct(f.when(f.expr("membership = TRUE"), f.col('person_id'))).alias('n_id')
    )
    .transform(
        map_column_values,
        map_dict = dict_parent_node,
        column = 'node_id',
        new_column = 'parent_node'
    )
    .transform(
        map_column_values,
        map_dict = dict_description,
        column = 'node_id',
        new_column = 'description'
    )
)

write_csv_file(df = flowchart_summary, path = './outputs/flowchart_stroke_hes_apc.csv')

flowchart_summary_sdc = (
    flowchart_summary
    .withColumn('n', f.round(f.col('n')/10, 0)*10)
    .withColumn('n_id', f.round(f.col('n_id')/10, 0)*10)
)

write_csv_file(df = flowchart_summary_sdc, path = './outputs/flowchart_stroke_hes_apc_sdc.csv')