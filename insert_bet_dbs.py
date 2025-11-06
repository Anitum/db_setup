import psycopg2
from psycopg2 import extras
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def copy_table_data():
    """
    Connects to a PostgreSQL database server, fetches all data from a source table,
    and inserts it into a destination table using optimized bulk insert operations.

    Assumes:
    - Both databases are on the same PostgreSQL server.
    - The destination table (which can be a Hypertable) already exists and
      has a structure compatible with the source table.
    - Uses chunked processing for memory efficiency with large datasets.
    """
    source_connection = None
    dest_connection = None
    
    # Configuration for bulk operations
    CHUNK_SIZE = 10000  # Process records in chunks for memory efficiency
    PAGE_SIZE = 1000    # Template size for execute_values

    try:
        # --- 1. CONFIGURE YOUR DATABASE, SCHEMA, AND TABLE NAMES ---
        source_db = 'aab_db'
        source_schema = 'public'
        source_table = 'detections'

        dest_db = 'aab_db_copy'
        dest_schema = 'public'
        dest_table = 'detections'
        
        # --- 2. CONNECT TO SOURCE DATABASE AND GET COLUMN INFO ---
        logger.info(f"Connecting to source database '{source_db}'...")
        source_connection = psycopg2.connect(
            host='localhost',
            port='5432',
            user='postgres',
            password='anitum',
            dbname=source_db
        )
        source_cursor = source_connection.cursor()
        
        # Get column information for the source table
        column_query = f"""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_schema = '{source_schema}' 
        AND table_name = '{source_table}' 
        ORDER BY ordinal_position
        """
        source_cursor.execute(column_query)
        columns = [row[0] for row in source_cursor.fetchall()]
        logger.info(f"Table columns: {columns}")
        
        # Get total record count
        count_query = f'SELECT COUNT(*) FROM "{source_schema}"."{source_table}"'
        source_cursor.execute(count_query)
        total_records = source_cursor.fetchone()[0]
        logger.info(f"Total records to copy: {total_records}")

        if total_records == 0:
            logger.info("Source table is empty. Nothing to copy.")
            return

        # --- 3. CONNECT TO DESTINATION DATABASE ---
        logger.info(f"Connecting to destination database '{dest_db}'...")
        dest_connection = psycopg2.connect(
            host='localhost',
            port='5432',
            user='postgres',
            password='anitum',
            dbname=dest_db
        )
        dest_connection.autocommit = False
        dest_cursor = dest_connection.cursor()

        # Optimize destination connection for bulk inserts
        dest_cursor.execute("SET synchronous_commit = OFF")
        dest_cursor.execute("SET work_mem = '256MB'")
        dest_cursor.execute("SET maintenance_work_mem = '512MB'")
        
        # Prepare column placeholders for INSERT
        column_list = ', '.join([f'"{col}"' for col in columns])
        placeholder = ', '.join(['%s'] * len(columns))
        insert_query = f'INSERT INTO "{dest_schema}"."{dest_table}" ({column_list}) VALUES ({placeholder})'
        
        # --- 4. PROCESS DATA IN CHUNKS FOR MEMORY EFFICIENCY ---
        offset = 0
        total_inserted = 0
        
        while offset < total_records:
            # Fetch chunk of data
            select_query = f'SELECT * FROM "{source_schema}"."{source_table}" LIMIT {CHUNK_SIZE} OFFSET {offset}'
            source_cursor.execute(select_query)
            chunk_records = source_cursor.fetchall()
            
            if not chunk_records:
                break
                
            logger.info(f"Processing chunk: {offset + 1} to {offset + len(chunk_records)} of {total_records}")
            
            # Bulk insert current chunk
            try:
                extras.execute_values(
                    dest_cursor, 
                    insert_query, 
                    chunk_records,
                    template=None,
                    page_size=PAGE_SIZE
                )
                dest_connection.commit()
                total_inserted += len(chunk_records)
                logger.info(f"Successfully inserted chunk of {len(chunk_records)} records. Total: {total_inserted}")
                
            except Exception as chunk_error:
                logger.error(f"Error inserting chunk at offset {offset}: {chunk_error}")
                dest_connection.rollback()
                raise chunk_error
            
            offset += CHUNK_SIZE
        
        # Close source connection after processing
        source_cursor.close()
        source_connection.close()
        logger.info(f"Source connection to '{source_db}' closed.")
        
        logger.info(f"Bulk insert completed! Total records inserted: {total_inserted}")

    except (Exception, psycopg2.Error) as error:
        logger.error(f"Error while working with PostgreSQL: {error}")
        if dest_connection:
            dest_connection.rollback()
            logger.info("Transaction rolled back.")
        raise error

    finally:
        # --- 5. CLOSE ANY OPEN CONNECTIONS ---
        if source_connection and not source_connection.closed:
            source_connection.close()
            logger.info("Source PostgreSQL connection is closed.")
        if dest_connection and not dest_connection.closed:
            dest_cursor.close()
            dest_connection.close()
            logger.info("Destination PostgreSQL connection is closed.")

if __name__ == '__main__':
    copy_table_data()

