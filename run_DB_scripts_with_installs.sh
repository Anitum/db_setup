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
<<<<<<< HEAD
DB_NAME="a2b_ooty_2_15112025"

# --- Global Outlet Configuration ---
OUTLET="ooty_2"
=======
DB_NAME="constrained_db_testing"

# --- Outlets Configuration ---
# Define the list of outlets to process
OUTLETS=("nungambakkam")
echo "Processing outlets: ${OUTLETS[@]}"
>>>>>>> 450b50587d46c85f48a18fa1ea9c4df823f0b309

# Create comma-separated list for ENABLED_OUTLETS
ENABLED_OUTLETS=$(IFS=,; echo "${OUTLETS[*]}")
export ENABLED_OUTLETS

# Export global database configuration
export DB_HOST
export DB_PORT
export DB_USER
export DB_PASSWORD
export DB_NAME
export DETECTIONS_TABLE_NAME="detections"

# Function to set outlet-specific variables
set_outlet_variables() {
    local outlet=$1
    
    export OUTLET="$outlet"
    export TABLE_ROI_FOLDER="./P_Table_ROI_${outlet}"
    export TABLE_ROI_GEOMETRY_TABLE="roi_table_polygons_geometries_${outlet}"
    export TABLE_ROI_MATRIX_TABLE="roi_table_polygons_matrix_${outlet}"
    export TABLE_ROI_SCALED_TABLE="roi_table_polygons_matrix_scaled_${outlet}"
    export TABLE_ROI_OUTLET="${outlet}"
    export TABLE_ROI_DESCRIPTION="Table ROI polygons (temporary staging)"
    
    export SECTION_ROI_FOLDER="./P_Section_ROI_${outlet}"
    export SECTION_ROI_GEOMETRY_TABLE="roi_section_polygons_geometries_${outlet}"
    export SECTION_ROI_OUTLET="${outlet}"
    export SECTION_ROI_DESCRIPTION="Section-wise ROI polygons (temporary staging)"
    
    export TABLE_OUTPUT_MAPPING="${TABLE_ROI_MATRIX_TABLE}:detections_in_table_${outlet},${TABLE_ROI_SCALED_TABLE}:detections_in_table_scaled_${outlet},${SECTION_ROI_GEOMETRY_TABLE}:detections_in_section_${outlet}"
}

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

# --- One-time Setup ---
LOG_FILE="combined_logs.log"
echo "Database Setup - $(date)" > "$LOG_FILE"

PYTHON_PATH=$(which python3)
if [ -z "$PYTHON_PATH" ]; then
    echo "Error: Python not found in PATH." | tee -a "$LOG_FILE"
    exit 1
fi

echo "Creating detections hypertable (once)..." | tee -a "$LOG_FILE"
"$PYTHON_PATH" ./create_detections_hypertable.py >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    echo "Error: Detections hypertable creation failed. Check $LOG_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

# --- Process Each Outlet ---
for outlet in "${OUTLETS[@]}"; do
    echo "" | tee -a "$LOG_FILE"
    echo "Processing outlet: $outlet" | tee -a "$LOG_FILE"
    
    set_outlet_variables "$outlet"
    
    echo "[${outlet}] Running table creation..." | tee -a "$LOG_FILE"
    "$PYTHON_PATH" ./one_shot_to_create_all_geom_tables.py >> "$LOG_FILE" 2>&1
    if [ $? -ne 0 ]; then
        echo "[${outlet}] Error: Table creation failed. Check $LOG_FILE" | tee -a "$LOG_FILE"
        exit 1
    fi
    
    echo "[${outlet}] Running output tables creation..." | tee -a "$LOG_FILE"
    "$PYTHON_PATH" ./one_shot_all_output_tables.py >> "$LOG_FILE" 2>&1
    if [ $? -ne 0 ]; then
        echo "[${outlet}] Error: Output tables creation failed. Check $LOG_FILE" | tee -a "$LOG_FILE"
        exit 1
    fi
    
    echo "[${outlet}] Completed successfully" | tee -a "$LOG_FILE"
done

# --- Run Triggers Creation Once (After All Outlets) ---
echo "" | tee -a "$LOG_FILE"
echo "Running triggers creation..." | tee -a "$LOG_FILE"

"$PYTHON_PATH" ./one_shot_triggers.py >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    echo "Error: Triggers creation failed. Check $LOG_FILE" | tee -a "$LOG_FILE"
    exit 1
fi


# Unset password for security
unset PGPASSWORD

