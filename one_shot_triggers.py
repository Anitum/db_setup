import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# This code correctly reads the environment variables exported by your bash script
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME")

DB_URL = f'postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

def get_engine():
    return create_engine(DB_URL, echo=False)

# ========================================
# CONFIGURATION - UPDATE ALL TABLES HERE
# ========================================

def get_outlet_trigger_config():
    """
    Outlet-based trigger configuration.
    Update enabled outlets and table patterns here.
    
    Returns:
        dict: Configuration for outlet-based triggers
    """
    # Convert comma-separated string from env var to a list
    enabled_outlets_str = os.environ.get('ENABLED_OUTLETS', "semmancheri, th_road, blr_boommachandra_2, blr_boommachandra, nungambakkam, ooty, ooty_2")
    enabled_outlets_list = [outlet.strip() for outlet in enabled_outlets_str.split(',')]
    
    return {
        'enabled_outlets': enabled_outlets_list,
        'detection_table': 'detections',
        'table_patterns': {
            'matrix': {
                'roi_pattern': 'roi_table_polygons_matrix_{outlet}',
                'output_pattern': 'detections_in_table_{outlet}'
            },
            'single': {
                'roi_pattern': 'roi_section_polygons_geometries_{outlet}', 
                'output_pattern': 'detections_in_section_{outlet}'
            }
        }
    }

# ========================================
# CORE TRIGGER CREATION FUNCTIONS
# ========================================

def create_outlet_aware_trigger(engine):
    """
    Creates single uber-trigger that handles all outlets dynamically
    """
    config = get_outlet_trigger_config()
    detection_table = config['detection_table']
    # Format list for SQL array literal
    enabled_outlets = ", ".join([f"'{o}'" for o in config['enabled_outlets']])

    setup_sql = f"""
    CREATE TABLE IF NOT EXISTS trigger_processing_state_outlet_triggers (
        table_name text PRIMARY KEY,
        last_processed_id integer DEFAULT 0,
        last_processed_timestamp timestamp DEFAULT NOW()
    );
    INSERT INTO trigger_processing_state_outlet_triggers (table_name) 
    VALUES ('{detection_table}') 
    ON CONFLICT (table_name) DO NOTHING;
    """

    trigger_sql = f"""
    -- Main outlet-aware trigger function
    CREATE OR REPLACE FUNCTION execute_outlet_polygon_trigger()
    RETURNS TRIGGER AS $$
    DECLARE
        current_max_id integer;
        previous_max_id integer;
        outlet_name text;
        enabled_outlets_array text[] := ARRAY[{enabled_outlets}];
        total_rows_processed integer := 0;
        outlet_rows integer;
    BEGIN
            -- Get ID range for processing
        SELECT COALESCE(MAX(id), 0) INTO current_max_id FROM {detection_table};
        SELECT last_processed_id INTO previous_max_id 
        FROM trigger_processing_state_outlet_triggers 
        WHERE table_name = '{detection_table}';
        
        -- Only process if there are new rows
        IF current_max_id > previous_max_id THEN
            
            -- Get distinct outlets from new detections
            FOR outlet_name IN 
                SELECT DISTINCT outlet 
                FROM {detection_table} 
                WHERE id > previous_max_id AND id <= current_max_id
                AND outlet IS NOT NULL
                AND outlet = ANY(enabled_outlets_array)
            LOOP
                -- Process matrix polygons for this outlet
                SELECT process_outlet_matrix_polygons(outlet_name, previous_max_id, current_max_id) INTO outlet_rows;
                total_rows_processed := total_rows_processed + outlet_rows;
                
                -- Process single geometry polygons for this outlet
                SELECT process_outlet_single_geom(outlet_name, previous_max_id, current_max_id) INTO outlet_rows;
                total_rows_processed := total_rows_processed + outlet_rows;
            END LOOP;
            
            -- Update tracking state
            UPDATE trigger_processing_state_outlet_triggers 
            SET last_processed_id = current_max_id,
                last_processed_timestamp = NOW()
            WHERE table_name = '{detection_table}';
            
            RAISE NOTICE 'Outlet trigger: % total rows processed for IDs % to %', 
                         total_rows_processed, previous_max_id + 1, current_max_id;
        END IF;
        
        RETURN NULL;
        
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'Outlet trigger execution failed: %', SQLERRM;
            RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;

    -- Get polygon columns for outlet table
    CREATE OR REPLACE FUNCTION get_polygon_columns_for_outlet(table_name_param text)
    RETURNS text[] AS $$
    DECLARE
        polygon_cols text[];
    BEGIN
        SELECT array_agg(column_name ORDER BY column_name) INTO polygon_cols
        FROM information_schema.columns 
        WHERE table_name = table_name_param 
          AND column_name NOT IN ('channel_id', 'outlet') 
          AND (data_type = 'USER-DEFINED' OR udt_name = 'geometry');
        
        RETURN polygon_cols;
    END;
    $$ LANGUAGE plpgsql;

    -- Process outlet-specific matrix polygons
    CREATE OR REPLACE FUNCTION process_outlet_matrix_polygons(outlet_name text, p_previous_max_id integer, p_current_max_id integer)
    RETURNS integer AS $$
    DECLARE
        roi_table text;
        output_table text;
        polygon_cols text[];
        col_name text;
        select_cols text := '';
        insert_cols text := '';
        rows_processed integer := 0;
        table_exists boolean := false;
    BEGIN
        -- Build table names
        roi_table := format('roi_table_polygons_matrix_%s', outlet_name);
        output_table := format('detections_in_table_%s', outlet_name);
        
        -- Check if tables exist
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = roi_table
        ) INTO table_exists;
        IF NOT table_exists THEN
            RAISE NOTICE 'ROI table % does not exist, skipping processing', roi_table;
            RETURN 0;
        END IF;
        
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = output_table
        ) INTO table_exists;
        IF NOT table_exists THEN
            RAISE NOTICE 'Output table % does not exist, skipping processing', output_table;
            RETURN 0;
        END IF;

        -- Get polygon columns dynamically
        SELECT get_polygon_columns_for_outlet(roi_table) INTO polygon_cols;
        
        IF polygon_cols IS NULL OR array_length(polygon_cols, 1) = 0 THEN
            RAISE NOTICE 'No polygon columns found in %, skipping processing', roi_table;
            RETURN 0;
        END IF;
        
        -- Build dynamic SELECT and INSERT columns for all polygons
        insert_cols := '"in_' || array_to_string(polygon_cols, '", "in_') || '"';
        FOREACH col_name IN ARRAY polygon_cols
        LOOP
            IF select_cols != '' THEN
                select_cols := select_cols || ', ';
            END IF;
            select_cols := select_cols || 
                format('ST_Contains(roi."%s", ST_SetSRID(ST_MakePoint(d.xc, d.yc), 4326)) AS "in_%s"', col_name, col_name);
        END LOOP;
        
        -- Execute polygon containment check
        EXECUTE format($fmt$
            INSERT INTO public.%I (
                id, class_id, channel_id, frame_id, timestamp, outlet, %s
            )
            SELECT 
                d.id,
                d.class_id,
                d.channel_id,
                d.frame_id,
                d.timestamp,
                d.outlet,
                %s
            FROM public.detections d
            JOIN public.%I roi ON d.channel_id = roi.channel_id AND d.outlet = roi.outlet
            WHERE d.id > %s AND d.id <= %s AND d.outlet = %L
            ON CONFLICT (id, timestamp) DO NOTHING
        $fmt$,
            output_table,
            insert_cols,
            select_cols,
            roi_table,
            p_previous_max_id,
            p_current_max_id,
            outlet_name
        );
        
        GET DIAGNOSTICS rows_processed = ROW_COUNT;
        RAISE NOTICE 'Matrix outlet %: % rows processed for detection IDs % to %', 
                     outlet_name, rows_processed, p_previous_max_id + 1, p_current_max_id;
        
        RETURN rows_processed;
        
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'Matrix outlet % processing failed: %', outlet_name, SQLERRM;
            RETURN 0;
    END;
    $$ LANGUAGE plpgsql;

    -- Process outlet-specific single geometry polygons
    CREATE OR REPLACE FUNCTION process_outlet_single_geom(outlet_name text, p_previous_max_id integer, p_current_max_id integer)
    RETURNS integer AS $$
    DECLARE
        roi_table text;
        output_table text;
        rows_processed integer := 0;
        table_exists boolean := false;
    BEGIN
        -- Build table names
        roi_table := format('roi_section_polygons_geometries_%s', outlet_name);
        output_table := format('detections_in_section_%s', outlet_name);
        
        -- Check if tables exist
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = roi_table
        ) INTO table_exists;
        IF NOT table_exists THEN
            RAISE NOTICE 'ROI table % does not exist, skipping processing', roi_table;
            RETURN 0;
        END IF;
        
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = output_table
        ) INTO table_exists;
        IF NOT table_exists THEN
            RAISE NOTICE 'Output table % does not exist, skipping processing', output_table;
            RETURN 0;
        END IF;
        
        -- Execute single geometry containment check
        EXECUTE format($fmt$
            INSERT INTO public.%I (
                id, class_id, channel_id, frame_id, timestamp, outlet, "in_geom"
            )
            SELECT 
                d.id,
                d.class_id,
                d.channel_id,
                d.frame_id,
                d.timestamp,
                d.outlet,
                ST_Contains(roi.geom, ST_SetSRID(ST_MakePoint(d.xc, d.yc), 4326)) AS "in_geom"
            FROM public.detections d
            JOIN public.%I roi ON d.channel_id = roi.channel_id AND d.outlet = roi.outlet
            WHERE d.id > %s AND d.id <= %s AND d.outlet = %L
            ON CONFLICT (id, timestamp) DO NOTHING
        $fmt$,
            output_table,
            roi_table,
            p_previous_max_id,
            p_current_max_id,
            outlet_name
        );
        
        GET DIAGNOSTICS rows_processed = ROW_COUNT;
        RAISE NOTICE 'Single geom outlet %: % rows processed for detection IDs % to %', 
                     outlet_name, rows_processed, p_previous_max_id + 1, p_current_max_id;
        
        RETURN rows_processed;
        
    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'Single geom outlet % processing failed: %', outlet_name, SQLERRM;
            RETURN 0;
    END;
    $$ LANGUAGE plpgsql;

    -- Drop and create trigger
    DROP TRIGGER IF EXISTS outlet_polygon_trigger ON {detection_table};
    CREATE TRIGGER outlet_polygon_trigger
        AFTER INSERT ON {detection_table}
        FOR EACH STATEMENT
        EXECUTE FUNCTION execute_outlet_polygon_trigger();
    """
    
    with engine.connect() as conn:
        conn.execute(text(setup_sql))      # Run the setup script first
        conn.execute(text(trigger_sql))     # Then run the trigger creation
        conn.commit()


# ========================================
# MAIN SETUP FUNCTION
# ========================================

def setup_outlet_polygon_trigger(engine):
    """
    Setup outlet-aware polygon trigger.
    This is the main function to call.
    """
    config = get_outlet_trigger_config()
    
    print("🚀 Setting up outlet-aware polygon trigger...")
    print("=" * 50)
    
    print(f"📋 Enabled outlets: {config['enabled_outlets']}")
    print(f"   Detection table: {config['detection_table']}")
    print(f"   Matrix pattern: {config['table_patterns']['matrix']['output_pattern']}")
    print(f"   Single pattern: {config['table_patterns']['single']['output_pattern']}")
    
    try:
        create_outlet_aware_trigger(engine)
        print("   ✅ Outlet trigger created successfully!")
    except Exception as e:
        print(f"   ❌ Failed to create outlet trigger: {e}")
    
    print("\n🎉 Outlet polygon trigger setup complete!")

# ========================================
# UTILITY FUNCTIONS
# ========================================

def test_outlet_trigger(engine):
    """Test the outlet trigger"""
    with engine.connect() as conn:
        # Check if trigger exists
        result = conn.execute(text("""
            SELECT trigger_name, event_object_table, action_timing, event_manipulation
            FROM information_schema.triggers 
            WHERE trigger_name = 'outlet_polygon_trigger'
        """)).fetchone()
        
        if result:
            print(f"✅ Trigger: {result[0]} on {result[1]} ({result[2]} {result[3]})")
        else:
            print("❌ Trigger 'outlet_polygon_trigger' not found!")
            
        # Check tracking state
        try:
            result = conn.execute(text("""
                SELECT table_name, last_processed_id, last_processed_timestamp 
                FROM trigger_processing_state_outlet_triggers
            """)).fetchone()
            
            if result:
                print(f"📊 Processing state: Table={result[0]}, Last ID={result[1]}, Time={result[2]}")
            else:
                print("❌ No tracking state found for outlet triggers")
                
        except Exception as e:
            print(f"❌ Error checking tracking state: {e}")

def list_outlet_triggers(engine):
    """List outlet polygon triggers"""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT trigger_name, event_object_table, action_timing, event_manipulation
            FROM information_schema.triggers 
            WHERE trigger_name LIKE '%%outlet%%polygon%%'
            ORDER BY trigger_name
        """)).fetchall()
        
        print("📋 Active Outlet Triggers:")
        print("-" * 40)
        for trigger in result:
            print(f"   {trigger[0]} on {trigger[1]}")

def disable_outlet_trigger(engine):
    """Disable outlet trigger"""
    config = get_outlet_trigger_config()
    detection_table = config['detection_table']
    
    with engine.connect() as conn:
        conn.execute(text(f"DROP TRIGGER IF EXISTS outlet_polygon_trigger ON {detection_table}"))
        conn.commit()
        print("🔇 Outlet trigger disabled")

def get_outlet_trigger_status(engine):
    """Get status of outlet trigger"""
    config = get_outlet_trigger_config()
    
    print("📊 Outlet Trigger Status Report:")
    print("=" * 50)
    print(f"\n🔍 Configuration:")
    print(f"   Enabled outlets: {config['enabled_outlets']}")
    print(f"   Detection table: {config['detection_table']}")
    test_outlet_trigger(engine)

# ========================================
# MAIN EXECUTION
# ========================================

if __name__ == "__main__":
    engine = get_engine()
    
    print("🎯 Outlet-Aware Polygon Trigger System")
    print("=" * 50)
    
    # Show current configuration
    config = get_outlet_trigger_config()
    print(f"\n📋 Configuration:")
    print(f"   Enabled outlets: {config['enabled_outlets']}")
    print(f"   Detection table: {config['detection_table']}")
    
    # Setup trigger
    print("\n" + "=" * 50)
    setup_outlet_polygon_trigger(engine)
    
    # Show status
    print("\n" + "=" * 50)
    get_outlet_trigger_status(engine)
    
    # List active triggers
    print("\n" + "=" * 50)
    list_outlet_triggers(engine)
    
    print("\n💡 Usage:")
    print("   - Update outlets in get_outlet_trigger_config()")
    print("   - Run setup_outlet_polygon_trigger(engine)")
    print("   - Trigger works automatically on INSERT operations!")