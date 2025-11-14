#!/bin/bash

# --- Centralized Database Configuration ---


set -e

CONFIG_FILE="config/pipeline.yaml"

# Extract DB vars from YAML using Python
eval $(python3 <<EOF
import yaml, sys
cfg = yaml.safe_load(open("$CONFIG_FILE"))
db = cfg["database"]
for k, v in db.items():
    key = f"DB_{k.upper()}"
    print(f'export {key}="{v}"')
print(f'export PGPASSWORD="{db["password"]}"')
EOF
)

echo "Database config loaded from $CONFIG_FILE"

echo "Database config loaded from $CONFIG_FILE"
echo "DB_HOST=$DB_HOST DB_PORT=$DB_PORT DB_NAME=$DB_NAME"



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
PYTHON_PATH=$(which python3)

# Check if python was found
if [ -z "$PYTHON_PATH" ]; then
    echo "Error: Python not found in PATH." | tee -a "$LOG_FILE"
    exit 1
fi

echo "Using Python interpreter: $PYTHON_PATH" | tee -a "$LOG_FILE"

echo "Creating detections hypertable..." | tee -a "$LOG_FILE"
"$PYTHON_PATH" create_detections_track_hypertable.py >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    echo "Error: Detections hypertable creation failed. Check $LOG_FILE for details."
    exit 1
fi
echo "Detections hypertable creation completed successfully." | tee -a "$LOG_FILE"



# echo "Running table creation script..." | tee -a "$LOG_FILE"
# "$PYTHON_PATH" one_shot_to_create_all_geom_tables.py >> "$LOG_FILE" 2>&1
# if [ $? -ne 0 ]; then
#     echo "Error: Table creation script failed. Check $LOG_FILE for details."
#     exit 1
# fi
# echo "Table creation completed successfully." | tee -a "$LOG_FILE"



# echo "Running output tables creation script..." | tee -a "$LOG_FILE"
# "$PYTHON_PATH" one_shot_all_output_tables.py >> "$LOG_FILE" 2>&1
# if [ $? -ne 0 ]; then
#     echo "Error: Output tables creation script failed. Check $LOG_FILE for details."
#     exit 1
# fi
# echo "Output tables creation completed successfully." | tee -a "$LOG_FILE"



# echo "Running triggers creation script..." | tee -a "$LOG_FILE"
# "$PYTHON_PATH" one_shot_triggers.py >> "$LOG_FILE" 2>&1
# if [ $? -ne 0 ]; then
#     echo "Error: Triggers creation script failed. Check $LOG_FILE for details."
#     exit 1
# fi
# echo "Triggers creation completed successfully." | tee -a "$LOG_FILE"

# echo "All Python scripts have finished successfully." | tee -a "$LOG_FILE"

# Unset password for security
unset PGPASSWORD
