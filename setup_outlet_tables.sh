#!/bin/bash

# This script is a 'worker' called by main_setup.sh.
# It accepts: 1. outlet_name, 2. path_to_table_roi, 3. path_to_section_roi

# --- Validate Input ---
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
    echo "❌ Error: Missing arguments."
    echo "Usage: $0 <outlet_name> <path_to_table_roi_folder> <path_to_section_roi_folder>"
    exit 1
fi

# --- Capture Arguments ---
OUTLET="$1"
TABLE_ROI_FOLDER="$2"
SECTION_ROI_FOLDER="$3"

echo "--- [Worker] Starting setup for outlet: ${OUTLET} ---"
echo "--- [Worker] Using Table ROI data from: ${TABLE_ROI_FOLDER} ---"
echo "--- [Worker] Using Section ROI data from: ${SECTION_ROI_FOLDER} ---"

# # --- Centralized Database Configuration ---
# DB_HOST="localhost"
# DB_PORT="5432"
# DB_USER="postgres"
# DB_PASSWORD="anitum"
# DB_NAME="aab_db_11"

# --- ROI Configuration (Logic from your original script) ---
TABLE_ROI_GEOMETRY_TABLE="roi_table_polygons_geometries_${OUTLET}"
TABLE_ROI_MATRIX_TABLE="roi_table_polygons_matrix_${OUTLET}"
TABLE_ROI_SCALED_TABLE="roi_table_polygons_matrix_scaled_${OUTLET}"
TABLE_ROI_OUTLET="${OUTLET}"
TABLE_ROI_DESCRIPTION="Table ROI polygons (temporary staging)"
SECTION_ROI_GEOMETRY_TABLE="roi_section_polygons_geometries_${OUTLET}"
SECTION_ROI_OUTLET="${OUTLET}"
SECTION_ROI_DESCRIPTION="Section-wise ROI polygons (temporary staging)"

# --- Output Tables Configuration (Logic from your original script) ---
DETECTIONS_TABLE_NAME="detections"
TABLE_OUTPUT_MAPPING="${TABLE_ROI_MATRIX_TABLE}:detections_in_table_${OUTLET},${TABLE_ROI_SCALED_TABLE}:detections_in_table_scaled_${OUTLET},${SECTION_ROI_GEOMETRY_TABLE}:detections_in_section_${OUTLET}"

# --- Export ALL Variables for Python Scripts ---
export DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME OUTLET
export TABLE_ROI_FOLDER TABLE_ROI_GEOMETRY_TABLE TABLE_ROI_MATRIX_TABLE TABLE_ROI_SCALED_TABLE TABLE_ROI_OUTLET TABLE_ROI_DESCRIPTION
export SECTION_ROI_FOLDER SECTION_ROI_GEOMETRY_TABLE SECTION_ROI_OUTLET SECTION_ROI_DESCRIPTION
export DETECTIONS_TABLE_NAME TABLE_OUTPUT_MAPPING

# Set PGPASSWORD to avoid password prompts
export PGPASSWORD="$DB_PASSWORD"

# --- Run Python Scripts to create and populate tables ---
LOG_FILE="setup_${OUTLET}.log"
echo "Starting Python scripts for outlet '${OUTLET}'... Logging to ${LOG_FILE}" > "$LOG_FILE" 2>&1

PYTHON_PATH=$(which python)
if [ -z "$PYTHON_PATH" ]; then
    echo "Error: Python not found in PATH." | tee -a "$LOG_FILE"
    exit 1
fi

# --- Run scripts with proper error checking ---

echo "Running one_shot_to_create_all_geom_tables.py..." | tee -a "$LOG_FILE"
"$PYTHON_PATH" one_shot_to_create_all_geom_tables.py >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    echo "❌ Error during geom table creation for outlet '${OUTLET}'. Check ${LOG_FILE}."
    exit 1 # Exit with an error code
fi

echo "Running one_shot_all_output_tables.py..." | tee -a "$LOG_FILE"
"$PYTHON_PATH" one_shot_all_output_tables.py >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    echo "❌ Error during output table creation for outlet '${OUTLET}'. Check ${LOG_FILE}."
    exit 1 # Exit with an error code
fi

echo "--- [Worker] Finished setup for outlet: ${OUTLET} ---"
unset PGPASSWORD