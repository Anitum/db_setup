#!/bin/bash

# A script to install and configure PostgreSQL, TimescaleDB, and related packages.

# # Install necessary packages for PostgreSQL and TimescaleDB repositories
# echo "Installing core dependencies..."
# sudo apt update -y
# sudo apt install -y gnupg postgresql-common apt-transport-https lsb-release wget

# # Add the PostgreSQL repository and its GPG qkey
# echo "Adding PostgreSQL repository..."
# sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
# sudo apt update -y

# # Install a specific PostgreSQL server development package
# echo "Installing postgresql-server-dev-17..."
# sudo apt install -y postgresql-server-dev-17

# # Add TimescaleDB repository and GPG key
# echo "Adding TimescaleDB repository..."
# echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -c -s) main" | sudo tee /etc/apt/sources.list.d/timescaledb.list
# wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg
# sudo apt update -y

# # Install TimescaleDB and the PostgreSQL client
# echo "Installing TimescaleDB..."
# sudo apt install -y timescaledb-2-postgresql-17 postgresql-client-17

# # Run timescaledb-tune to configure PostgreSQL settings for TimescaleDB
# echo "Running timescaledb-tune..."
# sudo timescaledb-tune --yes

# # Restart PostgreSQL service to apply changes
# echo "Restarting PostgreSQL service..."
# sudo systemctl restart postgresql

# # Install PostGIS extension
# echo "Installing PostGIS..."
# sudo apt install -y postgresql-17-postgis-3

# # Install Python packages using pip
# echo "Installing Python dependencies..."
# pip install SQLAlchemy==2.0.41
# pip install GeoAlchemy2==0.18.0

# echo "All installations and configurations are complete!"

# --- Centralized Database Configuration ---
DB_HOST="localhost"
DB_PORT="5432"
DB_USER="postgres"
DB_PASSWORD="anitum"
DB_NAME="aab_db_demo_diwali_v2"

# --- Global Outlet Configuration ---
OUTLET="th_road"

# --- ROI Configuration ---
# Table ROI Configuration
TABLE_ROI_FOLDER="/home/aabadmin/db_postgres/P_Table_ROI_${OUTLET}"
TABLE_ROI_GEOMETRY_TABLE="roi_table_polygons_geometries_${OUTLET}"
TABLE_ROI_MATRIX_TABLE="roi_table_polygons_matrix_${OUTLET}"
# TABLE_ROI_SCALED_TABLE="roi_table_polygons_matrix_scaled_${OUTLET}"
TABLE_ROI_OUTLET="${OUTLET}"
TABLE_ROI_DESCRIPTION="Table ROI polygons (temporary staging)"

# Section ROI Configuration
SECTION_ROI_FOLDER="/home/aabadmin/db_postgres/P_Section_ROI_${OUTLET}"
SECTION_ROI_GEOMETRY_TABLE="roi_section_polygons_geometries_${OUTLET}"
SECTION_ROI_OUTLET="${OUTLET}"
SECTION_ROI_DESCRIPTION="Section-wise ROI polygons (temporary staging)"

# --- Export Variables for Python Scripts ---
export DB_HOST
export DB_PORT
export DB_USER
export DB_PASSWORD
export DB_NAME
export OUTLET

# Export ROI Configuration
export TABLE_ROI_FOLDER
export TABLE_ROI_GEOMETRY_TABLE
export TABLE_ROI_MATRIX_TABLE
export TABLE_ROI_SCALED_TABLE
export TABLE_ROI_OUTLET
export TABLE_ROI_DESCRIPTION

export SECTION_ROI_FOLDER
export SECTION_ROI_GEOMETRY_TABLE
export SECTION_ROI_OUTLET
export SECTION_ROI_DESCRIPTION

# --- Output Tables Configuration ---
# Detection input table
DETECTIONS_TABLE_NAME="detections"

# Output table mappings (polygon_table:output_table)
TABLE_OUTPUT_MAPPING="${TABLE_ROI_MATRIX_TABLE}:detections_in_table_${OUTLET},
${TABLE_ROI_SCALED_TABLE}:detections_in_table_scaled_${OUTLET},
${SECTION_ROI_GEOMETRY_TABLE}:detections_in_section_${OUTLET}"

# Export output table configuration
export DETECTIONS_TABLE_NAME
export TABLE_OUTPUT_MAPPING

# Set PGPASSWORD to avoid password prompts
export PGPASSWORD="$DB_PASSWORD"

# --- Create and Configure the Database ---

# Check if the database already exists
echo "Checking for existing database: $DB_NAME"
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo "Database '$DB_NAME' already exists. Skipping creation."
else
    echo "Creating PostgreSQL database: $DB_NAME"
    createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" || { echo "Failed to create database."; exit 1; }
fi

echo "Enabling PostGIS and TimescaleDB extensions..."
psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS timescaledb;
" || { echo "Failed to enable extensions."; exit 1; }
echo "Database '$DB_NAME' is ready."

# --- Run Python Scripts Sequentially with logging ---
# Log file where all output and errors will be stored.
LOG_FILE="combined_logs.log"

echo "Starting Python scripts sequentially..." > "$LOG_FILE" 2>&1

# Get the path of the python interpreter
PYTHON_PATH=$(which python)

# Check if python was found
if [ -z "$PYTHON_PATH" ]; then
    echo "Error: Python not found in PATH." | tee -a "$LOG_FILE"
    exit 1
fi

echo "Using Python interpreter: $PYTHON_PATH" | tee -a "$LOG_FILE"

# echo "Creating detections hypertable..." | tee -a "$LOG_FILE"
# "$PYTHON_PATH" /home/aabadmin/db_postgres/create_detections_hypertable.py >> "$LOG_FILE" 2>&1
# if [ $? -ne 0 ]; then
#     echo "Error: Detections hypertable creation failed. Check $LOG_FILE for details."
#     exit 1
# fi
# echo "Detections hypertable creation completed successfully." | tee -a "$LOG_FILE"



echo "Running table creation script..." | tee -a "$LOG_FILE"
"$PYTHON_PATH" /home/aabadmin/db_postgres/one_shot_to_create_all_geom_tables.py >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    echo "Error: Table creation script failed. Check $LOG_FILE for details."
    exit 1
fi
echo "Table creation completed successfully." | tee -a "$LOG_FILE"



echo "Running output tables creation script..." | tee -a "$LOG_FILE"
"$PYTHON_PATH" /home/aabadmin/db_postgres/one_shot_all_output_tables.py >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    echo "Error: Output tables creation script failed. Check $LOG_FILE for details."
    exit 1
fi
echo "Output tables creation completed successfully." | tee -a "$LOG_FILE"



# echo "Running triggers creation script..." | tee -a "$LOG_FILE"
# "$PYTHON_PATH" /home/aabadmin/db_postgres/one_shot_triggers.py >> "$LOG_FILE" 2>&1
# if [ $? -ne 0 ]; then
#     echo "Error: Triggers creation script failed. Check $LOG_FILE for details."
#     exit 1
# fi
# echo "Triggers creation completed successfully." | tee -a "$LOG_FILE"

# echo "All Python scripts have finished successfully." | tee -a "$LOG_FILE"

# Unset password for security
unset PGPASSWORD

