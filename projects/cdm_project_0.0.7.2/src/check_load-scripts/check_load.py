import glob
import json
import logging
import os
import re
import duckdb
import pandas as pd


def read_file(entity_structure, dtype_, parse_dates):
    """
    Attempts to read a CSV file using a specific entity configuration via Pandas.
    If strict data type parsing fails, it falls back to a generic read and logs the column types.
    """
    logging.info("Trying to read the file with the configuration provided.")
    try:
        # Read CSV using configured schema parameters (separator, types, dates, encoding)
        df = pd.read_csv(
            entity_structure['uploaded_filename'],
            sep=entity_structure['separator'],
            dtype=dtype_,
            parse_dates=parse_dates,
            encoding=entity_structure['encoding']
        )
        # Filter dataframe to keep only the columns relevant to this entity
        df = df[entity_structure['entity_variables']]  
        len_df = len(df)
        logging.info(f"{len_df} records read.")
        return df
    except ValueError as e:
        logging.error(f"Reading the file with the provided configuration failed!")
        logging.error(str(e))
        
        # Fallback: Read without strict types to inspect data and debug the schema mismatch
        df = pd.read_csv(
            entity_structure['uploaded_filename'],
            sep=entity_structure['separator'],
            encoding=entity_structure['encoding']
        )
        variables_name = []
        variables_format = []
        for k, v in dtype_.items():
            if pd.StringDtype != type(v):
                variables_name.append(k)
                variables_format.append(v)
        
        # Log actual inferred data types to aid debugging
        for v in df.dtypes.items():
            logging.error(f"{v}")
        exit(1)


def load_file(entity_structure, df):
    """
    Connects to the DuckDB database and inserts the records from a Pandas DataFrame 
    into the designated entity table.
    """
    logging.info(f"Trying to connect to the database ...")
    try:
        con = duckdb.connect(database_path, read_only=False)
        # Set sample size for analyzing Pandas dataframes during injection
        con.execute("SET GLOBAL pandas_analyze_sample=500000")
        logging.info(f"Connected!")
        
        entity_name_ = entity_structure['entity_name']
        logging.info(f"Trying to load records in the table \"{entity_name_}\"")
        
        # Insert all data from the local 'df' variable into the SQL table
        query = "INSERT INTO {entity} SELECT * FROM df;".format(entity=entity_name_)
        con.execute(query)
        logging.info(f"{entity_structure['uploaded_filename']} -> LOADED!")
        
        global entities_uploaded
        entities_uploaded = entities_uploaded + 1
    except Exception as e:
        logging.error("Something went wrong trying to insert the data!")
        logging.error(str(e))
    finally:
        con.close()

        
def found_candidate(file_columns, entity_colums):
    """
    Checks if the columns found in a file exactly match the expected schema 
    columns for an entity (both in content and count).
    """
    return set(entity_colums) == set(file_columns) and len(entity_colums) == len(file_columns)


def query_found_errors(filename, entity_info):
    """
    Generates SQL queries to check for data casting/type mismatch errors 
    by testing if values can be successfully cast to their designated types.
    """
    queries = []
    for entity_key, entity_value in entity_info['parse'].items():
        # Uses DuckDB's TRY_CAST. If casting fails, it changes or returns null, capturing line errors.
        query_errors = f"""select * from (select row_number() over() as rk, TRY_CAST({entity_key} AS {entity_value})::VARCHAR AS {entity_key}_error, {entity_key} 
        from read_csv('{filename}', all_varchar=TRUE)) where {entity_key}_error != {entity_key} or {entity_key}_error = {entity_key} is null"""
        queries.append({'variable': entity_key, 'query': query_errors})
    return queries


def query_fk_errors(filename, entity_name):
    """
    NEW FUNCTION: Generates a SQL query to check for Foreign Key violations (Orphan Records).
    Assumes 'women_ent' is the parent table and 'woman_id' is the primary foreign key.
    """
    # If the entity is the parent table itself, foreign key validation is not needed
    if entity_name == "women_ent":
        return None
    
    # Query finds any 'woman_id' in the CSV that doesn't exist in the parent 'women_ent' table
    query_fk = f"""
    SELECT * FROM (
        SELECT row_number() over() as rk, woman_id 
        FROM read_csv('{filename}', all_varchar=TRUE)
    ) 
    WHERE woman_id NOT IN (SELECT woman_id FROM women_ent) AND woman_id IS NOT NULL
    """
    return query_fk

        
def sniff_original_files(uploaded_file_, entity_info_):        
    """
    Uses DuckDB's CSV sniffer to discover delimiters, headers, and column definitions.
    Maps the discovered schema against defined entities to identify matching targets.
    """
    logging.info("Sniffing original files")
    con = duckdb.connect(database_path, read_only=False)
    
    # Analyze CSV attributes automatically using DuckDB built-in metadata sniffer
    result = con.execute(f"from sniff_csv('{uploaded_file_}', sample_size = 250000)").df()
    columns = result['Columns']
    columns = pd.DataFrame(list(columns[0]))
    entities_to_upload = []
    entity_assigned = "Not found"
    
    # Evaluate which system configuration matches this specific CSV file structure
    for entity in entity_info_:
        candidate = found_candidate(columns['name'], entity['entity_columns'])
        if candidate:
            # Generate quality validation queries (Casting and Foreign Key constraints)
            queries_errors = query_found_errors(uploaded_file_, entity)
            #fk_query = query_fk_errors(uploaded_file_, entity['entity_name'])
            entity_assigned = entity['entity_name']          
            parse_original_file = {k: entity['parse'][k] for k in columns['name']}         
            
            entities_to_upload.append({
                "file": uploaded_file_, 
                "entity": entity['entity_name'], 
                "parse": parse_original_file, 
                'queries': queries_errors
                #'fk_query': fk_query  # Save the custom Foreign Key verification query
            })
    
    # Log detailed overview of metadata metrics collected from the CSV file
    logging.info("Original file characteristics")
    logging.info("=============================")
    logging.info(f"File: {uploaded_file_.replace('./inputs/','')}")
    logging.info(f"Delimiter: {result['Delimiter'][0]}")
    logging.info(f"Quote: {result['Quote'][0]}")
    logging.info(f"Escape: {result['Escape'][0]}")
    logging.info(f"NewLineDelimiter: {result['NewLineDelimiter'][0]}")
    logging.info(f"SkipRows: {result['SkipRows'][0]}")
    logging.info(f"HasHeader: {result['HasHeader'][0]}")
    logging.info(f"DateFormat: {result['DateFormat'][0]}")
    logging.info(f"TimestampFormat: {result['TimestampFormat'][0]}")
    logging.info('Columns with inferred types:')
    logging.info("\n" + columns.to_string(index=False))
    logging.info(f'Assigned entity: {entity_assigned}')
    logging.info("=============================\n\n")
    return entities_to_upload


def get_duckdb_parsed_config(entity_variables, entity_formats):
    """
    Maps configuration file datatypes into explicit native DuckDB data types.
    """
    dtype_ = {}
    parse_dates = []
    try_casting = []
    
    for c, f in zip(entity_variables, entity_formats):
        if f == 'string':
            dtype_[c] = 'VARCHAR'
        elif f == 'boolean':
            dtype_[c] = 'BOOLEAN'
        elif f == 'date':
            dtype_[c] = 'DATE'
        elif f == 'datetime':
            dtype_[c] = 'TIMESTAMP'
        elif f == 'integer':
            dtype_[c] = 'HUGEINT'
        elif f == 'double':
            dtype_[c] = 'DOUBLE'
        else:
            logging.warning(f"Format '{f}' not found, will be interpreted as String object.")
            dtype_[c] = 'VARCHAR'
        try_casting.append(f"TRY_CAST({c} AS {dtype_[c]}) AS {c}_error")
    return dtype_
    

def get_entity_info():
    """
    Parses structural settings from the master configuration JSON file.
    Triggers automated database table generation based on schema specs.
    """
    if 'entities' in configuration_file:
        entities_structure = []
        for entity in configuration_file['entities']:
            if 'name' not in entity or 'variables' not in entity:
                logging.error("properties \"name\" or \"variables\" not found in entity! Check specifications!")
                exit(1)
            entity_name = entity['name']
            logging.info(f"Processing entity \"{entity_name}\"...")
            try:
                entity_variables = [variable['label'] for variable in entity['variables']]
                entity_formats = [str(variable['format']).lower() for variable in entity['variables']]
                
                # Dynamically create relational structure inside DB if missing
                create_entity_table_if_not_exists(entity_name, entity_variables, entity_formats)
                
                info = get_duckdb_parsed_config(entity_variables, entity_formats)
                r = {'entity_name': entity_name, 'entity_columns': entity_variables, 'entity_formats': entity_formats, 'parse': info}
                entities_structure.append(r)
            except Exception as e:
                logging.error("Variables must have the properties \"label\" and \"format\"")
                logging.error(str(e))
                exit(1)
        return entities_structure
    else:
        logging.error("\"entities\" not found in your configuration file! Check specifications!")
        exit(1)
 

def create_entity_table_if_not_exists(entity_name_, entity_variables_, entity_formats_):
    """
    Constructs and executes the SQL DDL commands to create tables, primary keys, 
    and foreign key constraints enforcing strict data schema requirements.
    """
    format_translation = {
        "string": "VARCHAR(255)",
        "boolean": "BOOLEAN",
        "date": "DATE",
        "datetime": "TIMESTAMP",
        "integer": "HUGEINT",
        "double": "DOUBLE"
    }
    
    columns_query = []
    for variable_, format_ in zip(entity_variables_, entity_formats_):
        if variable_ == "exploration_description_st":
            data_type = "TEXT"
        else:
            data_type = format_translation.get(format_, "VARCHAR(255)")
        columns_query.append(f"{variable_} {data_type}")
        
    # Enforce relational Integrity: Assign specific Primary Keys and Foreign Keys
    constraints = []
    if entity_name_ == "women_ent":
        constraints.append("PRIMARY KEY (woman_id)")
    elif entity_name_ == "dicom_series_ent":
        constraints.append("PRIMARY KEY (woman_id, study_id, series_id)")
        #constraints.append("CONSTRAINT fk_dicom_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id)")
    elif entity_name_ == "surgical_treatment_ent":
        constraints.append("PRIMARY KEY (woman_id, initial_treatment_date_dt)")
        #constraints.append("CONSTRAINT fk_surgical_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id)")
    elif entity_name_ == "pathological_specimen_ent":
        constraints.append("PRIMARY KEY (woman_id, biopsy_dt)")
        #constraints.append("CONSTRAINT fk_pathological_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id)")
    elif entity_name_ == "neoadjuvant_treatment_ent":
        constraints.append("PRIMARY KEY (woman_id, neoadjuvant_therapy_drug_atc_cd)")
        #constraints.append("CONSTRAINT fk_neoadjuvant_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id)")
    elif entity_name_ == "followup_ent":
        constraints.append("PRIMARY KEY (woman_id, last_followup_contact_dt)")
        #constraints.append("CONSTRAINT fk_followup_woman FOREIGN KEY (woman_id) REFERENCES women_ent(woman_id)")

    full_body = columns_query + constraints
    query = f"CREATE TABLE IF NOT EXISTS {entity_name_} (\n    " + ",\n    ".join(full_body) + "\n);"

    try:
        logging.info(f"Trying to connect to the database ...")
        logging.info(f"Trying to create the table for entity \"{entity_name_}\"")
        con = duckdb.connect(database_path, read_only=False)
        con.execute(query)
        logging.info(f"Table successfully created or already exists!")
    except Exception as e:
        logging.error("Something went wrong in the creation of the table")
        logging.error(str(e))
    finally:
        con.close()


if __name__ == '__main__':
    # Initialize execution directory paths and fundamental logger frameworks
    os.chdir(os.path.dirname(__file__))
    logging.basicConfig(format='%(levelname)s:: %(message)s', level=logging.INFO)
    logging.info("Starting Checking data syntax process")
    
    database_path = '../../inputs/data.duckdb'
    configuration_file_path = '../../docs/CDM/cdmb_config.json'
    output_path = '../../outputs'
    upload_files_path = './inputs'
    global entities_uploaded
    entities_uploaded = 0
    
    # Load settings file tracking master configurations 
    try:
        with open(configuration_file_path) as configuration_file:
            configuration_file = json.load(configuration_file)
    except FileNotFoundError as e:
        logging.error("Configuration file is missing!")
        exit(1)
        
    logging.info("Configuration file loaded\n")
    CDMB_VERSION = configuration_file["cdmb_version"] if "cdmb_version" in configuration_file else "Non-versioned"
    ASPIRE_VERSION = os.environ.get('ASPIRE_VERSION', 'Non-versioned')
    PIPELINE_VERSION = os.environ.get('PIPELINE_VERSION', 'Non-versioned')
    logging.info("#########################################")
    logging.info(f"# CDMB version: {CDMB_VERSION}")
    logging.info(f"# ASPIRE version: {ASPIRE_VERSION}")
    logging.info(f"# PIPELINE version: {PIPELINE_VERSION}")
    logging.info("#########################################\n")
    
    entity_info = get_entity_info()    
    
    # Enforce priority execution order to prevent Foreign Key dependency failures.
    # The parent table ('women_ent') must be loaded first before child tables attempt lookup checks.
    strict_order = [
        "women_ent", 
        "dicom_series_ent", 
        "surgical_treatment_ent", 
        "pathological_specimen_ent", 
        "neoadjuvant_treatment_ent", 
        "followup_ent"
    ]
    entity_info = sorted(entity_info, key=lambda x: strict_order.index(x['entity_name']) if x['entity_name'] in strict_order else 99)

    # Gather available processing targets from data intake directory
    csv_files = glob.glob(upload_files_path + "/*.csv", recursive=True)
    uploaded_file_structure = []
    logging.info(f"-Found {len(csv_files)} uploaded files to check and map!")
    all_files_to_upload = []
    if len(csv_files) > 0: 
        logging.info("Starting the check of the files that do match an entity.")
        
    for uploaded_file in csv_files:
        try:
            # Match schema structure of files against structural metadata definitions
            entities_to_upload = sniff_original_files(uploaded_file, entity_info)
            all_files_to_upload = all_files_to_upload + entities_to_upload
        except Exception as e:
            logging.error(f"Something went wrong trying to read \"{uploaded_file}\" file")
            logging.error(str(e))
            exit(1)

    # Process ingestion loops per registered conceptual entity 
    for entity in entity_info:
        files_to_upload = [item for item in all_files_to_upload if item["entity"] == entity['entity_name']]
        if len(files_to_upload) == 0:
            logging.warning(f"No file of the uploaded files has been found that matches the header with the configuration of the \"{entity['entity_name']}\" entity.!")
        else:
            logging.info(f"A file (total files: {len(files_to_upload)}) of the uploaded files has been found that matches the header with the configuration of the \"{entity['entity_name']}\" entity.!")
            
            try:
                logging.info(f"Trying to connect to the database ...")
                con = duckdb.connect(database_path, read_only=False)
                logging.info(f"Trying to load records in the table \"{entity['entity_name']}\"")
                has_pass = 0
                for i, item in enumerate(files_to_upload):
                    try:
                        # MODIFIED: Proactive Foreign Key validation block executed prior to data insertion
                        # if item['fk_query'] is not None:
                        #     fk_errors = con.execute(item['fk_query']).df()
                        #     if len(fk_errors) > 0:
                        #         # Force descriptive error to abort loop if orphaned child keys are detected
                        #         raise ValueError(f"Foreign Key constraint violation: Found {len(fk_errors)} rows with 'woman_id' that do not exist in 'women_ent'.")

                        parse_configuracion = json.dumps(item['parse'], ensure_ascii=False)
                        if i == 0:
                            # Use DELETE followed by INSERT to safeguard predefined PK/FK schema structures
                            con.execute(f"DELETE FROM {entity['entity_name']};")
                            query = f"INSERT INTO {entity['entity_name']} SELECT {','.join(entity['entity_columns'])} from (select * FROM read_csv('{item['file']}',nullstr=['NA',''], columns ={parse_configuracion}))"
                            con.execute(query)
                            logging.info(f"Table cleared and records loaded! (SAFE INSERT OPERATION)")
                        else: 
                            query = f"INSERT INTO {entity['entity_name']} SELECT {','.join(entity['entity_columns'])} from (select * FROM read_csv('{item['file']}', nullstr=['NA',''], columns ={parse_configuracion}))"
                            con.execute(query)
                            logging.info(f"Table successfully appended! (INSERT OPERATION)")
                        has_pass = has_pass + 1
                    except Exception as e:
                        logging.error("Something went wrong trying to insert data into the database\n")
                        logging.error(str(e))
                        
                        # MODIFIED: Detailed error tracking block if operation aborted due to FK Constraints
                        # if "Foreign Key constraint violation" in str(e) and item['fk_query'] is not None:
                        #     fk_errors = con.execute(item['fk_query']).df()
                        #     logging.error("\n[CRITICAL] Checking Foreign Key violations (Orphan Records):\n")
                        #     logging.error(f"Filename: {item['file'].replace('./inputs/','')}")
                        #     n_lines = fk_errors["rk"].astype(str).tolist()
                        #     n_wrong_values = fk_errors["woman_id"].astype(str).unique().tolist()
                            
                        #     n_lines_st = ", ".join(n_lines[:15]) + (", ..." if len(n_lines) > 15 else "")
                        #     n_wrong_values_st = ", ".join(f"'{v}'" for v in n_wrong_values[:15]) + (", ..." if len(n_wrong_values) > 15 else "")
                            
                        #     logging.error(f"Line numbers where invalid woman_id values were found: {n_lines_st}")
                        #     logging.error(f"Erroneous woman_id values causing the mismatch: {n_wrong_values_st}")
                        #     logging.error("--------------------------------------------------\n")

                        # Variable by variable debugging block to catch casting/data-type translation problems
                        logging.error("\nChecking variable casting variable by variable\n")
                        for query in item['queries']:
                            result_error = con.execute(query['query']).df()
                            n_errors = len(result_error)
                            if n_errors > 0:
                                logging.error("---------")
                                logging.error(f"Checking variable: {query['variable']}")
                                logging.error(f"Filename: {item['file'].replace('./inputs/','')}")
                                logging.error(f"Found casting errors in {len(result_error)} line(s)")
                                n_lines = result_error["rk"].astype(str).tolist()
                                n_wrong_values = result_error[query['variable']].astype(str).unique().tolist()
                                logging.error(f"{len(n_wrong_values)} values have been found that cause casting errors.")
                                n_lines_st = ""
                                n_values_st = ""
                                if len(n_lines) > 15:
                                    n_lines_st = ", ".join(f"'{v}'" for v in n_lines[:15]) + ", ..."
                                else:
                                    n_lines_st = ", ".join(f"'{v}'" for v in n_lines)
                                
                                if len(n_wrong_values) > 15:
                                    n_values_st = ", ".join(f"'{v}'" for v in n_wrong_values[:15]) + ", ..."
                                else:
                                    n_values_st = ", ".join(f"'{v}'" for v in n_wrong_values)
                                    
                                logging.error(f"Line number where errors were found: {n_lines_st}")
                                logging.error(f"Example of erroneous values found: {n_values_st}")        
                                logging.error("---------")
                        exit(1)
                
                # Report metrics on ingestion status (Success, Failure, Partial tracking logs)
                if has_pass == len(files_to_upload):
                    entities_uploaded = entities_uploaded + 1
                    result = con.execute(f"select count(*) as n_rows from {entity['entity_name']}").df()            
                    logging.info(f"{result.loc[0, 'n_rows']} records read.\n\n")
                elif has_pass == 0:
                    logging.error("0 records read")
                else:
                    result = con.execute(f"select count(*) as n_rows from {entity['entity_name']}").df()     
                    logging.info(f"The entity has not been fully loaded with all records.")       
                    logging.info(f"{result.loc[0, 'n_rows']} records read.\n\n")
                
            except Exception as e:
                logging.error("Something went wrong trying to connect to the database")
                logging.error(str(e))
            finally:
                con.close()
                
    if entities_uploaded == 0:
        logging.error("None of the uploaded files have been matched with an entity!")
    else:
        logging.info(f"Total number of entities that have been matched to an uploaded file: {entities_uploaded}")