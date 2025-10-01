# some table names are hard coded, please correct them - when you get time - sorry :(

import os
import re
from pathlib import Path
from typing import Optional
import logging

# Retrieve all database connection details from environment variables
DB_HOST = os.environ.get("DB_HOST")  # Use a default value if not set
DB_PORT = os.environ.get("DB_PORT")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME") # No default for the database name

from sqlalchemy import (
    create_engine, Column, Integer, Float, String, Index, text, 
    MetaData, ARRAY, UniqueConstraint, Table, select
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.dialects.postgresql import insert, JSONB

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

Base = declarative_base()

def get_roi_polygon_model(table_name: str):
    """Create a dynamic ROI polygon model with the specified table name."""
    class RoiPolygonDynamic(Base):
        __tablename__ = table_name 
        id = Column(Integer, primary_key=True, autoincrement=True)
        channel_id = Column(Integer, nullable=False)  # Explicitly keeping as Integer
        polygon_id = Column(Integer, nullable=False)
        polygon_points = Column(JSONB, nullable=False)
        x_coordinates = Column(ARRAY(Float), nullable=False)
        y_coordinates = Column(ARRAY(Float), nullable=False)
        point_count = Column(Integer, nullable=False)

        __table_args__ = (
            UniqueConstraint('channel_id', 'polygon_id', name=f'uq_{table_name}_channel_polygon'),
            Index(f'idx_{table_name}_channel_id', 'channel_id'),
            Index(f'idx_{table_name}_polygon_id', 'polygon_id'),
            Index(f'idx_{table_name}_channel_polygon', 'channel_id', 'polygon_id'),
            Index(f'idx_{table_name}_polygon_points_gin', 'polygon_points', postgresql_using='gin'),
        )

    return RoiPolygonDynamic

# Consolidated database operations helper
class DatabaseHelper:
    @staticmethod
    def execute_sql_with_commit(engine, sql_text, error_msg):
        """Execute SQL with proper error handling and commit."""
        try:
            with engine.begin() as conn:
                conn.execute(text(sql_text))
                logger.info(f"Successfully executed: {error_msg}")
        except Exception as e:
            logger.error(f"Error in {error_msg}: {e}")
            raise

    @staticmethod
    def get_table_stats(engine, table_name, stat_columns):
        """Get statistics for a table."""
        try:
            with engine.connect() as conn:
                stats_sql = f"SELECT {stat_columns} FROM {table_name}"
                result = conn.execute(text(stats_sql))
                return result.fetchone()
        except Exception as e:
            logger.warning(f"Could not retrieve statistics for {table_name}: {e}")
            return None

class RoiProcessor:
    def __init__(self, database_url: str, table_name: str):
        """
        Initialize the ROI processor with database connection and table name.
        
        Args:
            database_url: PostgreSQL connection string
            table_name: Name for the ROI polygons table (e.g., 'roi_polygons_table_intermediate', 'roi_polygons_section_intermediate')
        """
        self.engine = create_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.table_name = table_name
        self.RoiPolygon = get_roi_polygon_model(self.table_name)
        self.db_helper = DatabaseHelper()

    def create_roi_table(self):
        """Create the ROI polygons table."""
        try:
            Base.metadata.create_all(self.engine, tables=[self.RoiPolygon.__table__])
            logger.info(f"Created table {self.table_name}")
        except Exception as e:
            logger.error(f"Error creating table {self.table_name}: {e}")
            raise

    def parse_folder_name(self, folder_name: str) -> Optional[int]:
        """
        Parse ROI folder name to extract channel ID.
        Handles both formats:
        - "channel1002" (simple format)
        - "channel1002_20250319090000_20250319091001__polygon_points" (complex format)
        
        Args:
            folder_name: Folder name containing channel info
            
        Returns:
            Channel ID or None if parsing fails
        """
        # Try simple format first (channel123)
        simple_pattern = r'channel(\d+)$'
        simple_match = re.match(simple_pattern, folder_name)
        if simple_match:
            return int(simple_match.group(1))
        
        # Try complex format (channel123_timestamp_timestamp__polygon_points)
        complex_pattern = r'channel(\d+)_.*polygon_points'
        complex_match = re.match(complex_pattern, folder_name)
        if complex_match:
            return int(complex_match.group(1))
        
        logger.warning(f"Could not parse folder name: {folder_name}")
        return None

    def find_polygon_folders(self, base_folder: Path) -> list:
        """
        Find polygon folders based on naming patterns.
        
        Args:
            base_folder: Base directory to search
            
        Returns:
            List of polygon folders found
        """
        # Look for folders with 'polygon_points' in name OR folders matching 'channel123' pattern
        polygon_folders = []
        
        for d in base_folder.iterdir():
            if not d.is_dir():
                continue
                
            # Pattern 1: folders containing 'polygon_points'
            if 'polygon_points' in d.name:
                polygon_folders.append(d)
            # Pattern 2: simple channel folders (channel123)
            elif re.match(r'channel\d+$', d.name):
                polygon_folders.append(d)
        
        return polygon_folders

    def parse_polygon_file(self, filepath: Path, channel_id: int) -> Optional[dict]:
        """
        Parse a polygon points file.
        
        Args:
            filepath: Path to the polygon_X_points.txt file
            channel_id: Channel ID (kept as integer)
            
        Returns:
            Dictionary with polygon data or None if parsing fails
        """
        polygon_match = re.search(r'polygon_(\d+)_points\.txt', filepath.name)
        if not polygon_match:
            logger.warning(f"Could not extract polygon ID from {filepath.name}")
            return None
        polygon_id = int(polygon_match.group(1))

        try:
            with open(filepath, 'r') as f:
                content = f.read()

            point_pattern = r'Point\s+(\d+):\s*\(\s*([\d.]+),\s*([\d.]+)\s*\)'
            matches = re.findall(point_pattern, content)

            if not matches:
                logger.warning(f"No points found in {filepath}")
                return None

            matches.sort(key=lambda x: int(x[0]))

            polygon_points = []
            x_coordinates = []
            y_coordinates = []

            for match in matches:
                point_number = int(match[0])
                x_coord = float(match[1])
                y_coord = float(match[2])

                if not (0 <= x_coord <= 1 and 0 <= y_coord <= 1):
                    logger.warning(f"Invalid coordinates in {filepath}: Point {point_number} ({x_coord}, {y_coord})")
                    continue

                polygon_points.append({"point": point_number, "x": x_coord, "y": y_coord})
                x_coordinates.append(x_coord)
                y_coordinates.append(y_coord)

            if not polygon_points:
                logger.warning(f"No valid points found in {filepath}")
                return None

            return {
                'channel_id': channel_id,  # Ensure this remains an integer
                'polygon_id': polygon_id,
                'polygon_points': polygon_points,
                'x_coordinates': x_coordinates,
                'y_coordinates': y_coordinates,
                'point_count': len(polygon_points)
            }

        except Exception as e:
            logger.error(f"Error reading file {filepath}: {e}")
            return None

    def insert_polygon(self, polygon_data: dict):
        """Insert a single polygon into the database."""
        with self.engine.connect() as conn:
            try:
                stmt = insert(self.RoiPolygon).values(polygon_data)
                stmt = stmt.on_conflict_do_update(
                    constraint=f'uq_{self.table_name}_channel_polygon',
                    set_={
                        'polygon_points': stmt.excluded.polygon_points,
                        'x_coordinates': stmt.excluded.x_coordinates,
                        'y_coordinates': stmt.excluded.y_coordinates,
                        'point_count': stmt.excluded.point_count
                    }
                )
                conn.execute(stmt)
                conn.commit()
                logger.info(f"Inserted/Updated polygon for channel {polygon_data['channel_id']}, "
                            f"polygon {polygon_data['polygon_id']} with {polygon_data['point_count']} points")
            except Exception as e:
                logger.error(f"Error inserting polygon: {e}")
                conn.rollback()
                raise

    def process_roi_folder(self, base_folder_path: str):
        """
        Process all ROI polygon folders and insert them into the database.
        
        Args:
            base_folder_path: Path to the folder containing all channel polygon folders
        """
        base_folder = Path(base_folder_path)
        if not base_folder.exists():
            raise ValueError(f"Base folder does not exist: {base_folder_path}")

        polygon_folders = self.find_polygon_folders(base_folder)
        logger.info(f"Found {len(polygon_folders)} polygon folders in {base_folder_path}")

        if not polygon_folders:
            logger.warning("No polygon folders found")
            return

        processed_count = 0

        for folder in polygon_folders:
            logger.info(f"Processing folder: {folder.name}")
            channel_id = self.parse_folder_name(folder.name)
            if not channel_id:
                continue

            polygon_files = list(folder.glob("polygon_*_points.txt"))
            if not polygon_files:
                logger.warning(f"No polygon files found in {folder}")
                continue

            for polygon_file in polygon_files:
                logger.info(f"  Processing file: {polygon_file.name}")
                polygon_data = self.parse_polygon_file(polygon_file, channel_id)
                if polygon_data:
                    self.insert_polygon(polygon_data)
                    processed_count += 1

        logger.info(f"Processing complete. Processed {processed_count} polygons.")

    def get_roi_stats(self):
        """Get basic statistics about the ROI data."""
        stats = self.db_helper.get_table_stats(
            self.engine,
            self.table_name,
            """COUNT(*) as total_polygons,
               COUNT(DISTINCT channel_id) as unique_channels,
               AVG(point_count) as avg_points_per_polygon,
               MIN(point_count) as min_points,
               MAX(point_count) as max_points"""
        )
        
        if stats:
            logger.info(f"ROI Database Statistics for {self.table_name}:")
            logger.info(f"  Total polygons: {stats.total_polygons}")
            logger.info(f"  Unique channels: {stats.unique_channels}")
            logger.info(f"  Avg points per polygon: {stats.avg_points_per_polygon:.1f}")
            logger.info(f"  Point count range: {stats.min_points} - {stats.max_points}")

        with self.engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT channel_id, COUNT(*) as polygon_count, AVG(point_count) as avg_points
                FROM {self.table_name}
                GROUP BY channel_id
                ORDER BY channel_id
            """))
            logger.info("Channel distribution:")
            for row in result:
                logger.info(f"  Channel {row.channel_id}: {row.polygon_count} polygons, "
                            f"avg {row.avg_points:.1f} points")

    def query_examples(self):
        """Show some example queries for the ROI data."""
        with self.engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT channel_id, polygon_id, point_count, 
                       polygon_points->0->>'x' as first_point_x,
                       polygon_points->0->>'y' as first_point_y
                FROM {self.table_name}
                WHERE channel_id = (SELECT MIN(channel_id) FROM {self.table_name})
                LIMIT 1
            """))

            for row in result:
                logger.info(f"Example from {self.table_name} - Channel {row.channel_id}, Polygon {row.polygon_id}: "
                            f"{row.point_count} points, first point: ({row.first_point_x}, {row.first_point_y})")

def drop_roi_table(database_url: str, table_name: str):
    """Drop existing ROI table if it exists."""
    try:
        engine = create_engine(database_url)
        DatabaseHelper.execute_sql_with_commit(
            engine, 
            f"DROP TABLE IF EXISTS {table_name} CASCADE",
            f"dropping table {table_name}"
        )
    except Exception as e:
        logger.warning(f"Could not drop table {table_name}: {e}")

def process_roi_directory(database_url: str, roi_folder: str, table_name: str, drop_existing: bool = False):
    """
    Process a single ROI directory and create intermediate table.
    
    Args:
        database_url: PostgreSQL connection string
        roi_folder: Path to ROI folder to process
        table_name: Name for the intermediate table
        drop_existing: Whether to drop existing table before creating
    """
    try:
        if drop_existing:
            drop_roi_table(database_url, table_name)
        
        processor = RoiProcessor(database_url, table_name)
        processor.create_roi_table()

        if not os.path.exists(roi_folder):
            logger.error(f"ROI folder does not exist: {roi_folder}")
            return

        logger.info(f"Processing ROI files from: {roi_folder} -> {table_name}")
        processor.process_roi_folder(roi_folder)
        
        logger.info(f"Processing complete for {table_name}! Final statistics:")
        processor.get_roi_stats()
        processor.query_examples()

    except Exception as e:
        logger.error(f"Error processing {roi_folder}: {e}")
        raise

def create_roi_geometry_tables(database_url: str, source_table: str, geometry_table: str, outlet_name: str = None):
    """
    Create ROI geometry table from polygon points table.
    **FIXED: Ensures channel_id stays as INTEGER throughout**
    
    Args:
        database_url: PostgreSQL connection string
        source_table: Name of the source polygon_points table
        geometry_table: Name of the target geometry table to create
        outlet_name: Name of the outlet to add as a column
    """
    try:
        engine = create_engine(database_url)
        
        # **FIX: Explicitly cast channel_id to INTEGER to prevent text conversion**
        outlet_column = f"'{outlet_name}'::TEXT AS outlet," if outlet_name else ""
        sql = f"""
            CREATE EXTENSION IF NOT EXISTS postgis;
            
            DROP TABLE IF EXISTS {geometry_table};

            CREATE TABLE {geometry_table} AS
            SELECT
                channel_id::INTEGER,  -- EXPLICIT INTEGER CAST TO PREVENT CONVERSION
                polygon_id::INTEGER,  -- EXPLICIT INTEGER CAST TO PREVENT CONVERSION
                {outlet_column}
                ST_MakePolygon(
                    ST_MakeLine(
                        ARRAY_APPEND(
                            ARRAY_AGG(ST_MakePoint(x, y) ORDER BY point_index),
                            (ARRAY_AGG(ST_MakePoint(x, y) ORDER BY point_index))[1]
                        )
                    )
                )::geometry(Polygon, 4326) AS geom
            FROM {source_table}
            GROUP BY channel_id, polygon_id;
            
            -- Add indexes for better performance
            CREATE INDEX idx_{geometry_table}_channel_id ON {geometry_table}(channel_id);
            CREATE INDEX idx_{geometry_table}_polygon_id ON {geometry_table}(polygon_id);
            CREATE INDEX idx_{geometry_table}_geom ON {geometry_table} USING GIST(geom);
        """
        
        DatabaseHelper.execute_sql_with_commit(engine, sql, f"creating geometry table {geometry_table}")
        
        # Get statistics
        stats = DatabaseHelper.get_table_stats(
            engine,
            geometry_table,
            "COUNT(*) as total_polygons, COUNT(DISTINCT channel_id) as unique_channels"
        )
        
        if stats:
            logger.info(f"✅ Table '{geometry_table}' created successfully!")
            logger.info(f"   - Total polygon geometries: {stats.total_polygons}")
            logger.info(f"   - Unique channels: {stats.unique_channels}")
                
    except Exception as e:
        logger.error(f"Error creating geometry table {geometry_table}: {e}")
        raise

def create_roi_geometry_matrix_table(database_url: str, geometry_table: str, matrix_table: str, outlet_name: str = None):
    """
    Create ROI geometry matrix table from geometry table (only for table ROI polygons).
    **FIXED: Ensures channel_id stays as INTEGER throughout**
    
    Args:
        database_url: PostgreSQL connection string
        geometry_table: Name of the source geometry table (roi_table_polygons_geometries)
        matrix_table: Name of the target matrix table to create
        outlet_name: Name of the outlet to add as a column
    """
    try:
        engine = create_engine(database_url)
        
        with engine.begin() as conn:
            logger.info(f"Creating matrix table {matrix_table} from {geometry_table}...")
            
            # Step 1: Get only the existing (channel_id, polygon_id) pairs - ENSURE INTEGERS
            existing_pairs = conn.execute(text(f"""
                SELECT DISTINCT channel_id::INTEGER, polygon_id::INTEGER
                FROM {geometry_table}
                ORDER BY channel_id, polygon_id
            """)).fetchall()
            
            if not existing_pairs:
                logger.warning(f"No data found in {geometry_table}")
                return
            
            logger.info(f"Found {len(existing_pairs)} unique channel-polygon pairs")

            # Step 2: Build CASE columns only for existing pairs
            column_expressions = []
            for c_id, p_id in existing_pairs:
                # **FIX: Use explicit INTEGER comparison to prevent type conversion**
                expr = f"""
                    MAX(CASE WHEN r.channel_id::INTEGER = {int(c_id)} AND r.polygon_id::INTEGER = {int(p_id)}
                        THEN r.geom END)::geometry(Polygon, 4326) AS "{c_id}_p{p_id}"
                """
                column_expressions.append(expr.strip())

            columns_sql = ',\n        '.join(column_expressions)

            # Step 3: Final SQL to create the matrix table
            outlet_column = f"'{outlet_name}'::TEXT AS outlet," if outlet_name else ""
            final_sql = f"""
                DROP TABLE IF EXISTS {matrix_table};

                CREATE TABLE {matrix_table} AS
                SELECT
                    r.channel_id::INTEGER AS channel_id,
                    {outlet_column}
                    {columns_sql}
                FROM {geometry_table} r
                GROUP BY r.channel_id::INTEGER
                ORDER BY r.channel_id::INTEGER;

                -- Add index on channel_id for better performance
                CREATE INDEX idx_{matrix_table}_channel_id ON {matrix_table}(channel_id);
            """

            conn.execute(text(final_sql))
            
        # Get statistics
        stats = DatabaseHelper.get_table_stats(engine, matrix_table, "COUNT(*) as total_rows")
        
        if stats:
            logger.info(f"✅ Matrix table '{matrix_table}' created successfully!")
            logger.info(f"   - Total rows (channels): {stats.total_rows}")
            logger.info(f"   - Total columns (polygons): {len(existing_pairs)}")
            logger.info(f"   - Matrix dimensions: {stats.total_rows} x {len(existing_pairs)}")
                
    except Exception as e:
        logger.error(f"Error creating matrix table {matrix_table}: {e}")
        raise

def create_polygon_points_table(database_url: str):
    """Create the polygon_points table if it doesn't exist."""
    sql = """
        CREATE TABLE IF NOT EXISTS polygon_points (
            id SERIAL PRIMARY KEY,
            polygon_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,  -- EXPLICIT INTEGER TYPE
            point_index INTEGER NOT NULL,
            x FLOAT NOT NULL,
            y FLOAT NOT NULL,
            CONSTRAINT uq_polygon_points_unique UNIQUE(polygon_id, channel_id, point_index)
        );
        
        CREATE INDEX IF NOT EXISTS idx_polygon_points_channel_id ON polygon_points(channel_id);
        CREATE INDEX IF NOT EXISTS idx_polygon_points_polygon_id ON polygon_points(polygon_id);
        CREATE INDEX IF NOT EXISTS idx_polygon_points_channel_polygon ON polygon_points(channel_id, polygon_id);
    """
    
    try:
        engine = create_engine(database_url)
        DatabaseHelper.execute_sql_with_commit(engine, sql, "creating polygon_points table")
        logger.info("Created/verified polygon_points table with indexes")
    except Exception as e:
        logger.error(f"Error creating polygon_points table: {e}")
        raise

def convert_roi_to_polygon_points(database_url: str, roi_table_name: str):
    """
    Convert data from roi_polygons intermediate table to polygon_points table.
    **FIXED: Ensures channel_id stays as INTEGER throughout**
    
    Args:
        database_url: PostgreSQL connection string
        roi_table_name: Name of the source ROI table (intermediate)
    """
    try:
        engine = create_engine(database_url)
        metadata = MetaData()
        metadata.reflect(bind=engine)
        
        # Get the roi table
        roi_table = Table(roi_table_name, metadata, autoload_with=engine)
        polygon_points_table = Table('polygon_points', metadata, autoload_with=engine)

        with engine.connect() as conn:
            session = Session(bind=conn)

            logger.info(f"Converting data from {roi_table_name} to polygon_points table...")

            # Fetch all rows from roi_polygons intermediate table
            results = session.execute(select(roi_table)).mappings().all()

            # Prepare the insert data
            insert_data = []
            for row in results:
                polygon_id = int(row['polygon_id'])  # **FIX: Explicit integer conversion**
                channel_id = int(row['channel_id'])  # **FIX: Explicit integer conversion**
                x_coords = row['x_coordinates']
                y_coords = row['y_coordinates']
                point_count = row['point_count']

                for idx in range(point_count):
                    insert_data.append({
                        'polygon_id': polygon_id,
                        'channel_id': channel_id,  # **FIX: Ensure integer**
                        'point_index': idx + 1,
                        'x': x_coords[idx],
                        'y': y_coords[idx]
                    })

            # Insert into polygon_points table using upsert with the correct constraint name
            if insert_data:
                for data_chunk in [insert_data[i:i+1000] for i in range(0, len(insert_data), 1000)]:
                    stmt = insert(polygon_points_table).values(data_chunk)
                    stmt = stmt.on_conflict_do_update(
                        constraint='uq_polygon_points_unique',
                        set_={
                            'x': stmt.excluded.x,
                            'y': stmt.excluded.y
                        }
                    )
                    session.execute(stmt)
                
                session.commit()
                logger.info(f"Inserted/Updated {len(insert_data)} rows from {roi_table_name} into 'polygon_points' table.")
            else:
                logger.warning(f"No data found in {roi_table_name} to convert.")

    except Exception as e:
        logger.error(f"Error converting {roi_table_name} to polygon_points: {e}")
        raise

def scale_polygon_table(database_url: str, source_table: str, scale_factor: float, target_table: str = None):
    """
    Scale all polygon geometries in a table by the specified factor.
    **STEP 6 FUNCTION: Scales polygon geometries around their centroids**
    
    Args:
        database_url: PostgreSQL connection string
        source_table: Source table name containing geometry columns
        scale_factor: Scale factor for polygon geometries (e.g., 1.5 for 150%)
        target_table: Target table name (default: source_table_scaled)
    """
    try:
        engine = create_engine(database_url)
        
        # Set target table name if not provided
        if target_table is None:
            target_table = f"{source_table}_scaled"
        
        logger.info(f"Starting polygon scaling operation...")
        logger.info(f"Source table: {source_table}")
        logger.info(f"Target table: {target_table}")
        logger.info(f"Scale factor: {scale_factor}")
        
        with engine.connect() as conn:
            # Get table columns to identify geometry columns
            columns_query = text("""
                SELECT column_name, udt_name, data_type
                FROM information_schema.columns 
                WHERE table_name = :table_name 
                  AND table_schema = 'public'
                ORDER BY ordinal_position
            """)
            
            result = conn.execute(columns_query, {"table_name": source_table})
            columns = result.fetchall()
            
            if not columns:
                raise Exception(f"Table {source_table} not found or has no columns")
            
            # Check for geometry columns
            geom_columns = [col for col in columns if col.udt_name == 'geometry']
            if not geom_columns:
                logger.warning(f"No geometry columns found in {source_table}")
                return False
            
            logger.info(f"Found {len(geom_columns)} geometry columns: {[col.column_name for col in geom_columns]}")
            
            # Build SELECT clause with scaling for geometry columns
            select_parts = []
            for col in columns:
                column_name = col.column_name
                data_type = col.udt_name
                
                if data_type == 'geometry':
                    # Scale geometry columns using translate-scale-translate approach
                    scaled_col = f"""ST_Translate(
                        ST_Scale(
                            ST_Translate(
                                "{column_name}", 
                                -ST_X(ST_Centroid("{column_name}")), 
                                -ST_Y(ST_Centroid("{column_name}"))
                            ),
                            {scale_factor}, 
                            {scale_factor}
                        ),
                        ST_X(ST_Centroid("{column_name}")), 
                        ST_Y(ST_Centroid("{column_name}"))
                    ) AS "{column_name}" """
                    select_parts.append(scaled_col)
                else:
                    # Keep other columns as-is
                    select_parts.append(f'"{column_name}"')
            
            select_clause = ',\n        '.join(select_parts)
            
            # Build the complete scaling query
            scaling_query = f"""
                DROP TABLE IF EXISTS "{target_table}";
                
                CREATE TABLE "{target_table}" AS 
                SELECT 
                    {select_clause}
                FROM "{source_table}";
                
                -- Add index on channel_id if it exists
                CREATE INDEX IF NOT EXISTS idx_{target_table}_channel_id ON "{target_table}"(channel_id);
                
                -- Add spatial indexes for geometry columns
            """
            
            # Add spatial indexes for each geometry column
            for col in geom_columns:
                scaling_query += f"""
                CREATE INDEX idx_{target_table}_{col.column_name}_geom ON "{target_table}" USING GIST("{col.column_name}");"""
            
            logger.info("Executing polygon scaling operation...")
            conn.execute(text(scaling_query))
            conn.commit()
            
            # Get statistics for the new table
            stats_query = f'SELECT COUNT(*) FROM "{target_table}"'
            result = conn.execute(text(stats_query))
            row_count = result.scalar()
            
            logger.info(f"✅ Successfully created {target_table} with {row_count} scaled rows")
            logger.info(f"   - Scale factor applied: {scale_factor}")
            logger.info(f"   - Geometry columns scaled: {[col.column_name for col in geom_columns]}")
            
            return True
                
    except Exception as e:
        logger.error(f"Error scaling polygon table {source_table}: {e}")
        raise

def convert_channel_ids_to_text(database_url: str, table_names: list):
    """
    Convert channel_id columns from INTEGER to TEXT with 'channel' prefix across multiple tables.
    **ISOLATED FUNCTION: Converts channel_id to format like 'channel502', 'channel602', etc.**
    
    Args:
        database_url: PostgreSQL connection string
        table_names: List of table names to process
    """
    try:
        engine = create_engine(database_url)
        
        logger.info(f"Starting channel_id conversion to text format...")
        
        for table_name in table_names:
            logger.info(f"Converting channel_id in table: {table_name}")
            
            try:
                with engine.connect() as conn:
                    # Check if table exists and has channel_id column
                    check_query = text("""
                        SELECT COUNT(*) 
                        FROM information_schema.columns 
                        WHERE table_name = :table_name 
                          AND column_name = 'channel_id'
                          AND table_schema = 'public'
                    """)
                    
                    result = conn.execute(check_query, {"table_name": table_name})
                    if result.scalar() == 0:
                        logger.warning(f"  Table {table_name} does not exist or has no channel_id column - skipping")
                        continue
                    
                    # Convert channel_id from INTEGER to TEXT with 'channel' prefix
                    conversion_query = f"""
                        ALTER TABLE "{table_name}" 
                        ALTER COLUMN channel_id TYPE TEXT 
                        USING 'channel' || channel_id::TEXT;
                    """
                    
                    conn.execute(text(conversion_query))
                    conn.commit()
                    
                    # Get sample of converted values for verification
                    sample_query = f"""
                        SELECT DISTINCT channel_id 
                        FROM "{table_name}" 
                        ORDER BY channel_id 
                        LIMIT 5
                    """
                    
                    sample_result = conn.execute(text(sample_query))
                    sample_values = [row[0] for row in sample_result.fetchall()]
                    
                    logger.info(f"  ✅ Successfully converted {table_name} - Sample values: {sample_values}")
                    
            except Exception as e:
                logger.error(f"  ❌ Error converting {table_name}: {e}")
                continue
        
        logger.info("Channel ID conversion to text format completed!")
                
    except Exception as e:
        logger.error(f"Error in channel_id conversion process: {e}")
        raise

def main():
    """Main function to process both ROI directories and convert to polygons table."""
    
    # Configuration
    DATABASE_URL = f'postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

    # Directory configurations with temporary staging tables
    roi_configs = [
        {
            'folder': os.environ.get("TABLE_ROI_FOLDER"),
            'table_name': "roi_table_polygons_temp",
            'final_geometry_table': os.environ.get("TABLE_ROI_GEOMETRY_TABLE"),
            'final_matrix_table': os.environ.get("TABLE_ROI_MATRIX_TABLE"),
            'final_scaled_table': os.environ.get("TABLE_ROI_SCALED_TABLE"),
            'description': os.environ.get("TABLE_ROI_DESCRIPTION"),
            'create_matrix': True,
            'outlet': os.environ.get("TABLE_ROI_OUTLET")
        },
        {
            'folder': os.environ.get("SECTION_ROI_FOLDER"), 
            'table_name': "roi_section_polygons_temp",
            'final_geometry_table': os.environ.get("SECTION_ROI_GEOMETRY_TABLE"),
            'final_matrix_table': None,
            'final_scaled_table': None,
            'description': os.environ.get("SECTION_ROI_DESCRIPTION"),
            'create_matrix': False,
            'outlet': os.environ.get("SECTION_ROI_OUTLET")
        }
    ]
    
    logger.info("Starting ROI processing pipeline...")
    
    # Step 1: Process both directories and create intermediate tables
    logger.info(f"\n{'='*60}")
    logger.info("STEP 1: Processing ROI directories and creating intermediate tables")
    logger.info(f"{'='*60}")
    
    for config in roi_configs:
        logger.info(f"\nProcessing {config['description']}")
        logger.info(f"{'-'*40}")
        
        process_roi_directory(
            database_url=DATABASE_URL,
            roi_folder=config['folder'],
            table_name=config['table_name'],
            drop_existing=True  # Set to True if you want to recreate tables
        )
    
    # Step 2: Create polygon_points table
    logger.info(f"\n{'='*60}")
    logger.info("STEP 2: Creating polygon_points table")
    logger.info(f"{'='*60}")
    
    create_polygon_points_table(DATABASE_URL)
    
    # Step 3: Convert both intermediate tables to polygon_points table
    logger.info(f"\n{'='*60}")
    logger.info("STEP 3: Converting intermediate tables to polygon_points table")
    logger.info(f"{'='*60}")
    
    for config in roi_configs:
        logger.info(f"\nConverting {config['description']} to polygon_points table")
        logger.info(f"{'-'*50}")
        
        convert_roi_to_polygon_points(
            database_url=DATABASE_URL,
            roi_table_name=config['table_name']
        )
    
    # Step 4: Create geometry tables from temporary staging tables
    logger.info(f"\n{'='*60}")
    logger.info("STEP 4: Creating ROI geometry tables from staging data")
    logger.info(f"{'='*60}")
    
    # Create separate geometry tables for each ROI type
    for config in roi_configs:
        geometry_table = config['final_geometry_table']
        
        logger.info(f"\nCreating geometry table for {config['description']}")
        logger.info(f"Source: {config['table_name']} -> Target: {geometry_table}")
        logger.info(f"{'-'*50}")
        
        # First convert staging table to points format temporarily
        temp_points_table = config['table_name'].replace('_temp', '_points_temp')
        
        try:
            engine = create_engine(DATABASE_URL)
            
            # **FIX: Ensure channel_id stays INTEGER in temporary table creation**
            temp_table_sql = f"""
                DROP TABLE IF EXISTS {temp_points_table};
                
                CREATE TABLE {temp_points_table} AS
                SELECT 
                    channel_id::INTEGER,  -- EXPLICIT INTEGER CAST
                    polygon_id::INTEGER,  -- EXPLICIT INTEGER CAST
                    generate_subscripts(x_coordinates, 1) as point_index,
                    unnest(x_coordinates) as x,
                    unnest(y_coordinates) as y
                FROM {config['table_name']};
            """
            
            DatabaseHelper.execute_sql_with_commit(
                engine, 
                temp_table_sql, 
                f"creating temporary points table: {temp_points_table}"
            )
                
        except Exception as e:
            logger.error(f"Error creating temporary points table: {e}")
            continue
        
        # Now create geometry table from the temporary points table
        create_roi_geometry_tables(
            database_url=DATABASE_URL,
            source_table=temp_points_table,
            geometry_table=geometry_table,
            outlet_name=config['outlet']
        )
        
        # Clean up temporary points table
        try:
            DatabaseHelper.execute_sql_with_commit(
                engine,
                f"DROP TABLE IF EXISTS {temp_points_table}",
                f"cleaning up temporary table: {temp_points_table}"
            )
        except Exception as e:
            logger.warning(f"Could not clean up temporary table {temp_points_table}: {e}")
    
    # Step 5: Create matrix table ONLY for table ROI polygons (not section)
    logger.info(f"\n{'='*60}")
    logger.info("STEP 5: Creating ROI geometry matrix table (Table ROI only)")
    logger.info(f"{'='*60}")
    
    # Only create matrix table for the table ROI polygons (first config with create_matrix=True)
    table_roi_config = next(config for config in roi_configs if config['create_matrix'])
    table_roi_geometry = table_roi_config['final_geometry_table']
    matrix_table_name = table_roi_config['final_matrix_table']
    
    logger.info(f"\nCreating matrix table for Table ROI polygons")
    logger.info(f"Source: {table_roi_geometry} -> Target: {matrix_table_name}")
    logger.info(f"{'-'*50}")
    
    create_roi_geometry_matrix_table(
        database_url=DATABASE_URL,
        geometry_table=table_roi_geometry,
        matrix_table=matrix_table_name,
        outlet_name=table_roi_config['outlet']
    )
    
    # Step 6: Scale polygon geometries (ONLY for table ROI matrix - output of Step 5)
    logger.info(f"\n{'='*60}")
    logger.info("STEP 6: Scaling polygon geometries (Table ROI Matrix only)")
    logger.info(f"{'='*60}")
    
    # Scale ONLY the table ROI matrix (not the section ROI)
    scale_factor = 1.5  # Default scaling factor - can be made configurable
    scaled_table_name = table_roi_config['final_scaled_table']
    
    logger.info(f"\nScaling Table ROI matrix polygons")
    logger.info(f"Source: {matrix_table_name} -> Target: {scaled_table_name}")
    logger.info(f"Scale factor: {scale_factor}")
    logger.info(f"{'-'*50}")
    
    try:
        scale_polygon_table(
            database_url=DATABASE_URL,
            source_table=matrix_table_name,
            scale_factor=scale_factor,
            target_table=scaled_table_name
        )
    except Exception as e:
        logger.error(f"Error scaling polygon table: {e}")
    
    # Step 7: Convert all channel_id columns to text format (ISOLATED STEP)
    logger.info(f"\n{'='*60}")
    logger.info("STEP 7: Converting channel_id columns to text format")
    logger.info(f"{'='*60}")
    
    # List all tables that need channel_id conversion
    tables_to_convert = ["polygon_points"]
    
    # Add all final geometry tables
    for config in roi_configs:
        tables_to_convert.append(config['final_geometry_table'])
    
    # Add matrix and scaled tables (only for table ROI)
    tables_to_convert.extend([matrix_table_name, scaled_table_name])
    
    logger.info(f"Converting channel_id columns to text format with 'channel' prefix")
    logger.info(f"Tables to process: {tables_to_convert}")
    logger.info(f"{'-'*50}")
    
    try:
        convert_channel_ids_to_text(
            database_url=DATABASE_URL,
            table_names=tables_to_convert
        )
    except Exception as e:
        logger.error(f"Error in channel_id conversion: {e}")
    
    # Step 8: Final summary (rename the existing final summary)
    logger.info(f"\n{'='*60}")
    logger.info("PROCESSING COMPLETE!")
    logger.info(f"{'='*60}")
    logger.info("Created temporary staging tables:")
    for config in roi_configs:
        logger.info(f"  - {config['table_name']} ({config['description']})")
    logger.info("Converted all data to final 'polygon_points' table")
    logger.info("Created ROI geometry tables:")
    for config in roi_configs:
        geometry_table = config['final_geometry_table']
        logger.info(f"  - {geometry_table} (from {config['table_name']})")
    logger.info(f"Created matrix table: {matrix_table_name} (from {table_roi_geometry})")
    logger.info(f"Created scaled table: {scaled_table_name} (scaled by factor {scale_factor})")
    
    # Show final statistics using consolidated helper
    try:
        engine = create_engine(DATABASE_URL)
        db_helper = DatabaseHelper()
        
        # Stats for polygon_points
        stats = db_helper.get_table_stats(
            engine,
            "polygon_points",
            """COUNT(*) as total_points,
               COUNT(DISTINCT channel_id) as unique_channels,
               COUNT(DISTINCT polygon_id) as unique_polygons"""
        )
        
        if stats:
            logger.info(f"\nFinal polygon_points Table Statistics:")
            logger.info(f"  Total points: {stats.total_points}")
            logger.info(f"  Unique channels: {stats.unique_channels}")
            logger.info(f"  Unique polygons: {stats.unique_polygons}")
            
        # Stats for geometry tables using helper
        for config in roi_configs:
            geometry_table = config['final_geometry_table']
            geom_stats = db_helper.get_table_stats(
                engine,
                geometry_table,
                "COUNT(*) as total_geometries, COUNT(DISTINCT channel_id) as unique_channels"
            )
            if geom_stats:
                logger.info(f"\n{geometry_table} Statistics:")
                logger.info(f"  Total geometries: {geom_stats.total_geometries}")
                logger.info(f"  Unique channels: {geom_stats.unique_channels}")
        
        # Stats for matrix table
        matrix_stats = db_helper.get_table_stats(engine, matrix_table_name, "COUNT(*) as total_rows")
        if matrix_stats:
            logger.info(f"\n{matrix_table_name} Statistics:")
            logger.info(f"  Total rows (channels): {matrix_stats.total_rows}")
            
            with engine.connect() as conn:
                column_result = conn.execute(text(f"""
                    SELECT COUNT(*) as column_count
                    FROM information_schema.columns 
                    WHERE table_name = '{matrix_table_name}' 
                    AND column_name != 'channel_id'
                """))
                
                col_stats = column_result.fetchone()
                if col_stats:
                    logger.info(f"  Total columns (polygons): {col_stats.column_count}")
                    logger.info(f"  Matrix dimensions: {matrix_stats.total_rows} x {col_stats.column_count}")
        
        # Stats for scaled table
        scaled_stats = db_helper.get_table_stats(engine, scaled_table_name, "COUNT(*) as total_rows")
        if scaled_stats:
            logger.info(f"\n{scaled_table_name} Statistics:")
            logger.info(f"  Total rows (channels): {scaled_stats.total_rows}")
            logger.info(f"  Scale factor applied: {scale_factor}")
            
            with engine.connect() as conn:
                scaled_column_result = conn.execute(text(f"""
                    SELECT COUNT(*) as column_count
                    FROM information_schema.columns 
                    WHERE table_name = '{scaled_table_name}' 
                    AND column_name != 'channel_id'
                """))
                
                scaled_col_stats = scaled_column_result.fetchone()
                if scaled_col_stats:
                    logger.info(f"  Total columns (polygons): {scaled_col_stats.column_count}")
                    logger.info(f"  Scaled matrix dimensions: {scaled_stats.total_rows} x {scaled_col_stats.column_count}")
                    
    except Exception as e:
        logger.warning(f"Could not retrieve final statistics: {e}")
    
    # Step 9: Cleanup temporary tables (keep only final tables)
    logger.info(f"\n{'='*60}")
    logger.info("STEP 9: Cleaning up temporary tables")
    logger.info(f"{'='*60}")
    
    # List of tables to keep (final tables only)
    tables_to_keep = [
        matrix_table_name,  # roi_table_polygons_matrix
        scaled_table_name,  # roi_table_polygons_matrix_scaled
        "roi_section_polygons_geometries",  # section geometry table
    ]
    
    # List of temporary tables to drop
    tables_to_drop = [
        "polygon_points",  # temporary consolidated table
        "roi_table_polygons_temp",  # temporary staging table
        "roi_section_polygons_temp",  # temporary staging table
        "roi_table_polygons_geometries",  # table geometry (keep only matrix & scaled)
    ]
    
    logger.info(f"Keeping final tables: {tables_to_keep}")
    logger.info(f"Dropping temporary tables: {tables_to_drop}")
    logger.info(f"{'-'*50}")
    
    try:
        engine = create_engine(DATABASE_URL)
        for table_name in tables_to_drop:
            try:
                DatabaseHelper.execute_sql_with_commit(
                    engine,
                    f"DROP TABLE IF EXISTS {table_name} CASCADE",
                    f"dropping temporary table: {table_name}"
                )
                logger.info(f"  ✅ Dropped temporary table: {table_name}")
            except Exception as e:
                logger.warning(f"  ⚠️  Could not drop table {table_name}: {e}")
        
        logger.info("✅ Cleanup completed! Only final tables remain.")
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
    
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    main()