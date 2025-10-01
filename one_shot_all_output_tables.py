from sqlalchemy import create_engine, MetaData, Table, Column, Integer, DateTime, Boolean, insert, func, text, select, Text
from sqlalchemy.schema import PrimaryKeyConstraint
from sqlalchemy.orm import Session
from geoalchemy2 import Geometry, functions as geo_func
import os
# -------------------------------
# Config
# -------------------------------

# Retrieve all database connection details from environment variables
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME")

DB_URL = f'postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
DETECTIONS_TABLE_NAME = os.environ.get("DETECTIONS_TABLE_NAME", "detections")  # Input detection table
SRID = 4326

# Parse table configuration from environment variable
# Format: "table1:output1,table2:output2,table3:output3"
mapping_str = os.environ.get("TABLE_OUTPUT_MAPPING", "")
TABLE_CONFIG = {}
if mapping_str:
    for pair in mapping_str.split(","):
        if ":" in pair:
            polygon_table, output_table = pair.strip().split(":")
            TABLE_CONFIG[polygon_table.strip()] = output_table.strip()

# -------------------------------
# Setup
# -------------------------------
engine = create_engine(DB_URL)
metadata = MetaData()
metadata.reflect(engine)

# Reflect detections table
#detections = metadata.tables[DETECTIONS_TABLE_NAME]


def create_output_table(polygon_table_name, output_table_name):
    """Create output table based on polygon table structure"""
    
    print(f"Creating output table: {output_table_name} (based on {polygon_table_name})")
    
    # Check if output table already exists
    if output_table_name in metadata.tables:
        print(f"Output table '{output_table_name}' already exists. Skipping...")
        return
    
    # Reflect polygon table
    polygon_table = metadata.tables[polygon_table_name]
    
    # -------------------------------
    # Discover polygon columns
    # -------------------------------
    polygon_columns = [
        col.name for col in polygon_table.columns
        if col.name != 'channel_id' and 'geometry' in str(col.type)
    ]
    
    print(f"Found polygon columns: {polygon_columns}")
    
    # -------------------------------
    # Create output table structure
    # -------------------------------
    # Define base columns first
    output_columns = [
        Column("id", Integer),
        Column("class_id", Integer),
        Column("channel_id", Text),
        Column("frame_id", Integer),
        Column("timestamp", DateTime(timezone=True)),
        Column("outlet", Text),  # Add outlet column
    ]
    
    # Add polygon boolean columns
    for poly_col in polygon_columns:
        output_columns.append(Column(f"in_{poly_col}", Boolean, nullable=True))
    
    # Add primary key constraint
    pk_name = f"{output_table_name}_pk"
    output_columns.append(PrimaryKeyConstraint("id", "timestamp", name=pk_name))
    
    # Create table
    output_table = Table(output_table_name, metadata, *output_columns)
    output_table.create(engine)
    
    print(f"✓ Created table: {output_table_name}")
    
    # -------------------------------
    # Convert to Hypertable
    # -------------------------------
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                SELECT create_hypertable('{output_table_name}', 'timestamp', if_not_exists => TRUE);
            """))
            conn.commit()
        print(f"✓ Converted to hypertable: {output_table_name}")
    except Exception as e:
        print(f"⚠ Warning: Could not convert to hypertable: {e}")
    
    # -------------------------------
    # Create comprehensive indexes for faster querying
    # -------------------------------
    try:
        with engine.connect() as conn:
            # Basic indexes
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_{output_table_name}_timestamp 
                ON {output_table_name} (timestamp DESC);
                
                CREATE INDEX IF NOT EXISTS idx_{output_table_name}_channel_timestamp 
                ON {output_table_name} (channel_id, timestamp DESC);
                
                CREATE INDEX IF NOT EXISTS idx_{output_table_name}_outlet 
                ON {output_table_name} (outlet);
                
                CREATE INDEX IF NOT EXISTS idx_{output_table_name}_outlet_timestamp 
                ON {output_table_name} (outlet, timestamp DESC);
                
                CREATE INDEX IF NOT EXISTS idx_{output_table_name}_outlet_channel_timestamp 
                ON {output_table_name} (outlet, channel_id, timestamp DESC);
                
                CREATE INDEX IF NOT EXISTS idx_{output_table_name}_class_id 
                ON {output_table_name} (class_id);
                
                CREATE INDEX IF NOT EXISTS idx_{output_table_name}_frame_id 
                ON {output_table_name} (frame_id);
            """))
            conn.commit()
        print(f"✓ Created indexes for: {output_table_name}")
    except Exception as e:
        print(f"⚠ Warning: Could not create some indexes: {e}")
    
    # Reflect metadata again to get the newly created table
    metadata.reflect(bind=engine)

# -------------------------------
# Main execution loop
# -------------------------------
def main():
    print(f"Creating output tables for detection table: {DETECTIONS_TABLE_NAME}")
    print(f"Configured table pairs: {TABLE_CONFIG}")
    
    if not TABLE_CONFIG:
        print("❌ No table configuration found. Check TABLE_OUTPUT_MAPPING environment variable.")
        return
    
    print("=" * 60)
    
    for polygon_table_name, output_table_name in TABLE_CONFIG.items():
        try:
            create_output_table(polygon_table_name, output_table_name)
            print(f"✓ Completed table creation: {output_table_name}")
        except Exception as e:
            print(f"✗ Failed to create table: {output_table_name}")
            print(f"  Error: {e}")
        print("-" * 50)
    
    print("Table creation process completed!")

if __name__ == "__main__":
    main()
