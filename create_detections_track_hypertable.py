import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Retrieve the database configuration from environment variables
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME")
DB_URL = f'postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

def get_engine():
    return create_engine(DB_URL, echo=False)

def create_detections_track_hypertable(engine):
    """
    Creates the detections_track hypertable if it doesn't exist.
    Includes all indexes and TimescaleDB hypertable conversion.
    """
    
    create_table_sql = """
    -- Create detections_track table if it doesn't exist
    CREATE TABLE IF NOT EXISTS detections_track (
        id SERIAL,
        channel_id TEXT,
        frame_id INTEGER,
        xc DOUBLE PRECISION,
        yc DOUBLE PRECISION,
        w DOUBLE PRECISION,
        h DOUBLE PRECISION,
        class_id INTEGER,
        conf DOUBLE PRECISION,
        tracking_id INTEGER,
        timestamp TIMESTAMPTZ NOT NULL,
        outlet TEXT,
        PRIMARY KEY (id, timestamp, channel_id, outlet)
    );
    """
    
    create_hypertable_sql = """
    -- Convert to hypertable if not already converted
    SELECT create_hypertable('detections_track', 'timestamp', if_not_exists => TRUE);
    """
    
    create_indexes_sql = """
    -- Create indexes if they don't exist
    CREATE INDEX IF NOT EXISTS detections_track_timestamp_idx 
    ON detections_track (timestamp DESC);
    
    CREATE INDEX IF NOT EXISTS idx_channel_timestamp 
    ON detections_track (channel_id, timestamp);

    CREATE INDEX IF NOT EXISTS idx_outlet 
    ON detections_track (outlet);
    
    CREATE INDEX IF NOT EXISTS idx_outlet_timestamp 
    ON detections_track (outlet, timestamp DESC);
    
    CREATE INDEX IF NOT EXISTS idx_outlet_channel_timestamp 
    ON detections_track (outlet, channel_id, timestamp DESC);
    """
    
    try:
        with engine.connect() as conn:
            print("🚀 Creating detections_track hypertable...")
            
            # Check if table already exists
            table_exists = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'detections_track'
                );
            """)).scalar()
            
            if table_exists:
                print("📋 Table 'detections_track' already exists.")
                
                # Check if it's already a hypertable
                is_hypertable = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM timescaledb_information.hypertables 
                        WHERE hypertable_name = 'detections_track' 
                        AND hypertable_schema = 'public'
                    );
                """)).scalar()
                
                if is_hypertable:
                    print("✅ Table is already a hypertable.")
                else:
                    print("🔄 Converting existing table to hypertable...")
                    conn.execute(text(create_hypertable_sql))
                    conn.commit()
                    print("✅ Successfully converted to hypertable.")
                    
            else:
                print("📝 Creating new detections_track table...")
                conn.execute(text(create_table_sql))
                conn.commit()
                print("✅ Table created successfully.")
                
                print("🔄 Converting to hypertable...")
                conn.execute(text(create_hypertable_sql))
                conn.commit()
                print("✅ Successfully converted to hypertable.")
            
            # Create indexes
            print("📊 Creating indexes...")
            conn.execute(text(create_indexes_sql))
            conn.commit()
            print("✅ Indexes created successfully.")
            
            # Verify the setup
            print("\n📋 Verifying hypertable setup...")
            
            # Check hypertable info
            hypertable_info = conn.execute(text("""
                SELECT hypertable_name, hypertable_schema, num_dimensions
                FROM timescaledb_information.hypertables 
                WHERE hypertable_name = 'detections_track'
            """)).fetchone()
            
            if hypertable_info:
                print(f"✅ Hypertable: {hypertable_info[1]}.{hypertable_info[0]} with {hypertable_info[2]} dimension(s)")
            else:
                print("❌ Warning: Hypertable verification failed")
            
            # Check indexes
            indexes = conn.execute(text("""
                SELECT indexname, indexdef 
                FROM pg_indexes 
                WHERE tablename = 'detections_track'
                ORDER BY indexname
            """)).fetchall()
            
            print(f"📊 Found {len(indexes)} indexes:")
            for idx in indexes:
                print(f"   - {idx[0]}")
            
            # Check table structure
            columns = conn.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns 
                WHERE table_name = 'detections_track' 
                AND table_schema = 'public'
                ORDER BY ordinal_position
            """)).fetchall()
            
            print(f"📋 Table structure ({len(columns)} columns):")
            for col in columns:
                nullable = "NULL" if col[2] == "YES" else "NOT NULL"
                default = f" DEFAULT {col[3]}" if col[3] else ""
                print(f"   - {col[0]}: {col[1]} {nullable}{default}")
            
    except Exception as e:
        print(f"❌ Error creating detections_track hypertable: {e}")
        raise

def main():
    """Main function to create the detections_track hypertable"""
    print("🎯 detections_track Hypertable Creation Script")
    print("=" * 50)
    
    try:
        engine = get_engine()
        create_detections_track_hypertable(engine)
        print("\n🎉 detections_track hypertable setup complete!")
        
    except Exception as e:
        print(f"\n❌ Script failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()