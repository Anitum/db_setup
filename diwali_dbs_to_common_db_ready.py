#!/usr/bin/env python3

"""
This script modifies a PostgreSQL table in-place to:
1. Add an 'outlet' (TEXT) column, if it doesn't exist.
2. Populate the 'outlet' column with a static name (idempotently).
3. Change the 'channel_id' (INTEGER) column to TEXT and
   reformat its data (e.g., 1002 -> 'channel1002').
"""

import sys
import logging
import psycopg2
from psycopg2 import sql

# --- 1. SCRIPT CONFIGURATION: DATABASE ---
# Fill in your PostgreSQL database details here
DB_CONFIG = {
    "dbname": "a2b_th_road",
    "user": "postgres",
    "password": "anitum",
    "host": "localhost",  # Or your DB host IP/domain
    "port": "5432"        # Default PostgreSQL port
}
# --- END DATABASE CONFIGURATION ---


# --- 2. SCRIPT CONFIGURATION: INPUTS ---
# Set your target table and the new outlet name here
TABLE_TO_MODIFY = "detections"
OUTLET_TO_ADD = "th_road"
# --- END INPUTS CONFIGURATION ---


# Setup clear logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_column_type(cursor, table_name, column_name):
    """Helper function to check a column's data type."""
    check_sql = sql.SQL("""
        SELECT data_type 
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s;
    """)
    cursor.execute(check_sql, (table_name, column_name))
    result = cursor.fetchone()
    if result:
        return result[0]
    return None

def modify_table_in_place(table_name, outlet_name):
    """
    Connects to the DB and runs the 3-step modification
    within a single transaction.
    """
    conn = None
    try:
        # --- Connect to the database ---
        logging.info(f"Connecting to database '{DB_CONFIG['dbname']}'...")
        conn = psycopg2.connect(**DB_CONFIG)
        # We MUST disable autocommit to use a transaction
        conn.autocommit = False
        
        # Use a single cursor for the entire transaction
        with conn.cursor() as cursor:

            # --- Step 1: Add the 'outlet' column (Idempotent) ---
            logging.info(f"Step 1/3: Ensuring 'outlet' column exists on '{table_name}'...")
            
            # Use psycopg2.sql to safely format identifiers (table/column names)
            add_col_sql = sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS outlet TEXT;") \
                             .format(sql.Identifier(table_name))
            
            cursor.execute(add_col_sql)
            logging.info(" -> 'outlet' column ensured.")

            # --- Step 2: Populate the 'outlet' column (Idempotent) ---
            logging.info(f"Step 2/3: Populating 'outlet' column with '{outlet_name}'...")
            
            pop_col_sql = sql.SQL("UPDATE {} SET outlet = %s WHERE outlet IS NULL;") \
                               .format(sql.Identifier(table_name))
            
            # Pass data (%s) as a separate argument to prevent SQL injection
            cursor.execute(pop_col_sql, (outlet_name,))
            logging.info(f" -> {cursor.rowcount} rows updated.")
            
            # --- Step 3: Check and Transform 'channel_id' (Idempotent) ---
            logging.info(f"Step 3/3: Checking and transforming 'channel_id' column...")
            
            current_type = get_column_type(cursor, table_name, 'channel_id')
            
            if not current_type:
                logging.error(f" -> ERROR: Column 'channel_id' not found in table '{table_name}'.")
                raise Exception(f"Column 'channel_id' not found.")

            logging.info(f" -> Current 'channel_id' data type is: {current_type}")

            if current_type == 'integer':
                logging.info(" -> Type is 'integer'. Transforming to TEXT and reformatting...")
                
                # This SQL alters the type AND reformats the data in one go
                transform_sql = sql.SQL("""
                    ALTER TABLE {} 
                    ALTER COLUMN channel_id TYPE TEXT 
                    USING CONCAT('channel', channel_id);
                """).format(sql.Identifier(table_name))
                
                cursor.execute(transform_sql)
                logging.info(" -> 'channel_id' column successfully transformed.")
            
            elif current_type == 'text':
                logging.info(" -> 'channel_id' is already 'text'. Skipping transformation.")
            
            else:
                logging.warning(f" -> 'channel_id' type is '{current_type}', not 'integer'. Skipping.")

        # --- All steps successful, commit the transaction ---
        logging.info("All steps complete. Committing transaction...")
        conn.commit()
        logging.info("✅ Transaction committed successfully.")

    except (Exception, psycopg2.DatabaseError) as error:
        logging.error(f"❌ AN ERROR OCCURRED: {error}")
        if conn:
            logging.warning("Rolling back transaction...")
            conn.rollback()
            logging.warning("Transaction rolled back.")
        sys.exit(1) # Exit with a non-zero status code to indicate failure

    finally:
        if conn:
            conn.close()
            logging.info("Database connection closed.")


if __name__ == "__main__":
    logging.info(f"--- Starting Table Modification Script ---")
    logging.info(f"Target Table: {TABLE_TO_MODIFY}")
    logging.info(f"Outlet Name:  {OUTLET_TO_ADD}")
    
    # Run the main function
    modify_table_in_place(TABLE_TO_MODIFY, OUTLET_TO_ADD)