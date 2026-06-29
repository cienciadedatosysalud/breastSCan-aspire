import os
import duckdb
import pandas as pd
import gzip
import shutil

DUCKDB_PATH = "../../inputs/data.duckdb"
# PG_CONN_STRING = os.environ.get("DATABASE_URL")
db_user = os.environ.get('POSTGRES_USER')
db_password = os.environ.get('POSTGRES_PASSWORD')
db_name = os.environ.get('POSTGRES_DB')
db_host = os.environ.get('POSTGRES_HOST')
db_port = os.environ.get('POSTGRES_PORT')
PG_CONN_STRING = f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

OUTPUT_DIR = "../../outputs"
EXTENSIONS_DIR = "../../../extensions"

def migrate_tables():


    print("--- Starting DuckDB to PostgreSQL Migration ---")
    
    if not PG_CONN_STRING:
        print("❌ Error: DATABASE_URL environment variable is not set!")
        return
        
    if not os.path.exists(DUCKDB_PATH):
        print(f"❌ Error: The file '{DUCKDB_PATH}' was not found inside the container.")
        return

    print(f"Opening DuckDB database at: {DUCKDB_PATH}")
    conn = duckdb.connect(DUCKDB_PATH)

    # Ensure output directory exists for error reporting
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        # --- OFFLINE GZ EXTRACTION & LOADING ---
        gz_path = os.path.join(EXTENSIONS_DIR, "postgres_scanner.duckdb_extension.gz")
        extracted_extension_path = os.path.join(EXTENSIONS_DIR, "postgres_scanner.duckdb_extension")

        # Check if the downloaded .gz archive exists
        if not os.path.exists(gz_path):
            raise FileNotFoundError(f"Missing extension GZ archive at: {gz_path}")

        # Decompress the .gz file on the fly if it hasn't been extracted yet
        if not os.path.exists(extracted_extension_path):
            print(f"📦 Decompressing {gz_path}...")
            with gzip.open(gz_path, 'rb') as f_in:
                with open(extracted_extension_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        
        print(f"Loading Postgres extension locally from: {extracted_extension_path}...")
        conn.execute(f"LOAD '{extracted_extension_path}';")
        # ------------------------------------------------

        print("Connecting to PostgreSQL container...")
        conn.execute(f"ATTACH '{PG_CONN_STRING}' AS my_postgres (TYPE POSTGRES);")

        # Strict relational order to respect Foreign Keys constraints during insertion
        strict_order = [
            "women_ent", 
            "dicom_series_ent", 
            "surgical_treatment_ent", 
            "pathological_specimen_ent", 
            "neoadjuvant_treatment_ent", 
            "followup_ent"
        ]

        # Verify that the tables actually exist in DuckDB before inserting
        db_tables = [t[0] for t in conn.execute("SHOW TABLES;").fetchall()]
        ordered_tables = [t for t in strict_order if t in db_tables]

        if not ordered_tables:
            print("⚠️ No matching target tables found inside the DuckDB file to migrate.")
            return

        print(f"Found {len(ordered_tables)} tables to migrate in order: {ordered_tables}")

        # Start an explicit, atomic database transaction block
        print("\n🚀 Beginning global transaction...")
        conn.execute("BEGIN TRANSACTION;")

        table_pks = {
            "women_ent": ["woman_id"],
            "dicom_series_ent": ["woman_id", "study_id", "series_id"],
            "surgical_treatment_ent": ["woman_id", "initial_treatment_date_dt"],
            "pathological_specimen_ent": ["woman_id", "biopsy_dt"],
            "neoadjuvant_treatment_ent": ["woman_id", "neoadjuvant_therapy_drug_atc_cd"],
            "followup_ent": ["woman_id", "last_followup_contact_dt"]
        }

        for table in ordered_tables:
            print(f"Processing table: {table}...")
            
            pks = table_pks[table]
            all_columns = [col[1] for col in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            updates = [col for col in all_columns if col not in pks]
            
            conflict_target = ", ".join(pks)
            set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in updates])

            source_view = table
            
            # Foreign Key Constraint Validation for child tables
            if table != "women_ent":
                # Detect orphaned records whose woman_id does not exist in the target PostgreSQL instance
                query_orphans = f"""
                    SELECT * FROM {table} 
                    WHERE woman_id NOT IN (SELECT woman_id FROM my_postgres.women_ent)
                """
                df_errors = conn.execute(query_orphans).df()
                
                if not df_errors.empty:
                    error_file = os.path.join(OUTPUT_DIR, f"errors_fk_{table}.csv")
                    df_errors.to_csv(error_file, index=False)
                    print(f"  ⚠️ Detected {len(df_errors)} rows with FK conflicts. Saved to {error_file}")
                    
                    # Redirect source to a temporary view containing only valid relational records
                    conn.execute(f"""
                        CREATE OR REPLACE TEMPORARY VIEW {table}_valid AS 
                        SELECT * FROM {table} 
                        WHERE woman_id IN (SELECT woman_id FROM my_postgres.women_ent)
                    """)
                    source_view = f"{table}_valid"
                else:
                    print("  ✅ No Foreign Key constraint conflicts detected.")

            # Build and format the UPSERT statement execution string
            query_upsert = f"""
                INSERT INTO my_postgres.{table} 
                SELECT * FROM {source_view}
                ON CONFLICT ({conflict_target}) 
                DO UPDATE SET {set_clause};
            """
            
            try:
                conn.execute(query_upsert)
                print(f"  ✅ Stage UPSERT operation successful for table '{table}'.")
            except Exception as e:
                print(f"  ❌ Unexpected database error processing table {table}: {e}")
                raise e # Reraise exception to abort the transaction block gracefully

        # Commit all inserts only if every single table succeeded without fatal execution errors
        conn.execute("COMMIT;")
        print("\n🎉 Migration finished perfectly! All data committed to PostgreSQL.")

    except Exception as e:
        print(f"\n❌ ERROR: An integrity constraint violation or database error occurred: {e}")
        print("⚠️ CRITICAL: Triggering ROLLBACK. No data has been saved to PostgreSQL.")
        
        try:
            conn.execute("ROLLBACK;")
        except Exception as rollback_err:
            print(f"Failed to execute rollback transaction: {rollback_err}")
            
        print("\n💡 Hint: Check database connection states or scheme structural updates.")
        
    finally:
        conn.close()
        print("--- Migration Pipeline Closed ---")

if __name__ == "__main__":

    os.chdir(os.path.dirname(__file__))
    migrate_tables()