# Databricks notebook source
# Databricks notebook source
import importlib, sys
import sys
import os


# Grab username
username = spark.sql('select current_user() as user').collect()[0]['user']

# Project conficuration (project_config.json) path
project_config_path = f'/Workspace/Repos/{username}/hds_ls_score_cvd_stroke/databricks/pipeline/config/project_config.json'

# Append repos to 
sys.path.append(f"/Workspace/Repos/{username}/")

# Read project config, parse project folder
from functions.json_utils import read_json_file
project_config = read_json_file(path=project_config_path)
project_name = project_config['project_name']
# Append username to project_name to ensure unique table names per user in shared database
username_short = username.split('@')[0].replace('.', '_')  # e.g. joe.bloggs@university.ac.uk -> joe_bloggs
project_name = f'{project_name}_{username_short}'
project_folder = project_config['project_folder'].format(username = username, project_name = project_name)
del read_json_file

# Assign to environment 
os.environ['USERNAME'] = username
os.environ['PROJECT_FOLDER'] = project_folder
os.environ['PROJECT_NAME'] = project_name

project_runtime_folder = project_config['project_runtime_folder'].format(
    username=username, project_name=project_name
)

# Create runtime folders if they don't exist
import os
os.makedirs(f'{project_runtime_folder}/config', exist_ok=True)
os.makedirs(f'{project_runtime_folder}/outputs', exist_ok=True)

os.environ['PROJECT_RUNTIME_FOLDER'] = project_runtime_folder
os.environ['TABLE_DIRECTORY_PATH'] = f'{project_runtime_folder}/config/table_directory.json'
os.environ['TABLE_MAPPING_PATH']   = f'{project_runtime_folder}/config/table_mapping.json'


# COMMAND ----------


#print(project_folder)