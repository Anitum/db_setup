# Database Setup for Multi-Outlet Detection System

This repository contains scripts for setting up a PostgreSQL database with TimescaleDB and PostGIS extensions for processing detection data across multiple outlets with ROI (Region of Interest) polygons.

## Overview

The system processes detection data and checks if detections fall within defined ROI polygons for multiple outlets. It uses PostgreSQL with TimescaleDB for time-series data and PostGIS for spatial operations.

## Prerequisites

- Ubuntu/Debian Linux
- Python 3.x with pip
- PostgreSQL access
- Sufficient disk space for database operations

## Repository Structure

```
db_postgres/
├── run_DB_scripts_with_installs.sh          # Main orchestration script
├── create_detections_hypertable.py          # Creates detections hypertable
├── one_shot_to_create_all_geom_tables.py    # Creates ROI geometry tables
├── one_shot_all_output_tables.py            # Creates output tables
├── one_shot_triggers.py                     # Creates multi-outlet triggers
├── P_Table_ROI_<outlet>/                    # Table ROI polygon data
├── P_Section_ROI_<outlet>/                  # Section ROI polygon data
└── README.md                                # This file
```

## Initial Setup (One-Time Only)

### Step 1: Database and Extension Installation

**⚠️ Only run this once for initial setup**

1. Activate your Python virtual environment:
   ```bash
   source /path/to/your/venv/bin/activate
   ```

2. Edit `run_DB_scripts_with_installs.sh` and **uncomment** the installation section (lines 5-48):
   ```bash
   # Uncomment these sections:
   # - PostgreSQL installation
   # - TimescaleDB installation
   # - PostGIS installation
   # - Python package installation
   ```

3. Update database credentials in the script if needed:
   ```bash
   DB_HOST="localhost"
   DB_PORT="5432"
   DB_USER="postgres"
   DB_PASSWORD="your_password"
   DB_NAME="your_database_name"
   ```

4. Run the installation:
   ```bash
   bash run_DB_scripts_with_installs.sh
   ```

### Step 2: Create Detections Hypertable

**⚠️ Only run this once after installation**

1. In `run_DB_scripts_with_installs.sh`, **uncomment** lines 157-163:
   ```bash
   echo "Creating detections hypertable..." | tee -a "$LOG_FILE"
   "$PYTHON_PATH" /home/aabadmin/db_postgres/create_detections_hypertable.py >> "$LOG_FILE" 2>&1
   if [ $? -ne 0 ]; then
       echo "Error: Detections hypertable creation failed. Check $LOG_FILE for details."
       exit 1
   fi
   echo "Detections hypertable creation completed successfully." | tee -a "$LOG_FILE"
   ```

2. **Comment out** lines 168-185 (other Python scripts)

3. **Comment out** the installation section (lines 5-48)

4. Run the script:
   ```bash
   bash run_DB_scripts_with_installs.sh
   ```

## Adding New Outlets

### Step 1: Prepare ROI Data

Ensure you have the correct folder structure and data format for your outlet:

#### Required Folders:
```
P_Table_ROI_<outlet>/
P_Section_ROI_<outlet>/
```

#### Data Format Example:

**File:** `P_Section_ROI_blr_boommachandra_2/channel102/polygon_1_points.txt`

```
Polygon Points (normalized coordinates):
Point 1: (0.9875, 0.5703)
Point 2: (0.3703, 0.2109)
Point 3: (0.0234, 0.4401)
Point 4: (0.025, 0.9766)
Point 5: (0.9938, 0.987)
```

**Key Requirements:**
- Coordinates must be normalized (0.0 to 1.0 range)
- Each polygon in a separate file
- Files organized by channel folders
- Files named as `polygon_N_points.txt` where N is the polygon number

### Step 2: Configure Outlet in Script

1. Edit `run_DB_scripts_with_installs.sh`

2. Update the `OUTLET` variable (around line 57):
   ```bash
   OUTLET="your_outlet_name"
   ```

3. Verify the folder paths match your data structure:
   ```bash
   TABLE_ROI_FOLDER="/home/aabadmin/db_postgres/P_Table_ROI_${OUTLET}"
   SECTION_ROI_FOLDER="/home/aabadmin/db_postgres/P_Section_ROI_${OUTLET}"
   ```

### Step 3: Create Geometry and Output Tables

1. In `run_DB_scripts_with_installs.sh`:
   - **Comment out** lines 157-163 (detections hypertable creation)
   - **Comment out** lines 5-48 (installation section)
   - **Uncomment** lines 168-185 (geometry and output table creation scripts)
   - **Comment out** lines 189-196 (trigger creation script)

2. Ensure these scripts are uncommented:
   ```bash
   # Line 168-174: Table creation
   echo "Running table creation script..." | tee -a "$LOG_FILE"
   "$PYTHON_PATH" /home/aabadmin/db_postgres/one_shot_to_create_all_geom_tables.py >> "$LOG_FILE" 2>&1
   
   # Line 178-185: Output tables creation
   echo "Running output tables creation script..." | tee -a "$LOG_FILE"
   "$PYTHON_PATH" /home/aabadmin/db_postgres/one_shot_all_output_tables.py >> "$LOG_FILE" 2>&1
   ```

3. Run the script:
   ```bash
   bash run_DB_scripts_with_installs.sh
   ```

4. **Repeat Steps 2-3 for each outlet** you want to add

### Step 4: Create Multi-Outlet Triggers (After All Outlets Are Added)

**⚠️ Only run this after all outlets have been processed**

1. In `run_DB_scripts_with_installs.sh`:
   - **Comment out** lines 157-163 (detections hypertable creation)
   - **Comment out** lines 168-185 (geometry and output table scripts)
   - **Uncomment** lines 189-196 (trigger creation script)

   ```bash
   echo "Running triggers creation script..." | tee -a "$LOG_FILE"
   "$PYTHON_PATH" /home/aabadmin/db_postgres/one_shot_triggers.py >> "$LOG_FILE" 2>&1
   ```

2. Update the enabled outlets list in `one_shot_triggers.py` if needed (line 19):
   ```python
   enabled_outlets_str = os.environ.get('ENABLED_OUTLETS', 
       "semmancheri, th_road, blr_boommachandra_2, blr_boommachandra, nungambakkam, ooty, ooty_2")
   ```

3. Run the script:
   ```bash
   bash run_DB_scripts_with_installs.sh
   ```

## Script Execution Summary

### Script Configuration Checklist

| Step | Script Section | Lines | Action |
|------|----------------|-------|--------|
| **Initial Setup** | Installation | 5-48 | Uncomment once |
| | Detections Hypertable | 157-163 | Uncomment once |
| | Geometry Tables | 168-185 | Comment |
| | Triggers | 189-196 | Comment |
| **Per Outlet** | Installation | 5-48 | Comment |
| | Detections Hypertable | 157-163 | Comment |
| | Geometry Tables | 168-185 | Uncomment |
| | Triggers | 189-196 | Comment |
| **Final Step** | Installation | 5-48 | Comment |
| | Detections Hypertable | 157-163 | Comment |
| | Geometry Tables | 168-185 | Comment |
| | Triggers | 189-196 | Uncomment |

## What Each Script Does

### 1. `create_detections_hypertable.py`
- Creates the main `detections` table as a TimescaleDB hypertable
- Partitioned by timestamp for efficient time-series queries
- Includes indexes for fast lookups by channel, outlet, and timestamp
- **Run once during initial setup**

### 2. `one_shot_to_create_all_geom_tables.py`
- Reads polygon data from ROI folders
- Creates geometry tables for:
  - Table ROI polygons (matrix format)
  - Section ROI polygons (single geometry format)
- Stores polygons as PostGIS geometry objects
- **Run once per outlet**

### 3. `one_shot_all_output_tables.py`
- Creates output tables for each outlet:
  - `detections_in_table_<outlet>`: Detections within table ROIs
  - `detections_in_section_<outlet>`: Detections within section ROIs
- Creates comprehensive indexes for query performance
- Converts tables to TimescaleDB hypertables
- **Run once per outlet**

### 4. `one_shot_triggers.py`
- Creates a single multi-outlet trigger system
- Automatically processes new detections for all configured outlets
- Uses dynamic SQL to handle different polygon configurations
- Processes data incrementally to avoid reprocessing
- **Run once after all outlets are configured**

## Database Tables Created

### Input Table
- `detections`: Main detection data (hypertable)

### Per-Outlet Tables
- `roi_table_polygons_matrix_<outlet>`: Table ROI polygons (multiple columns)
- `roi_section_polygons_geometries_<outlet>`: Section ROI polygons (single geometry)
- `detections_in_table_<outlet>`: Output for table ROIs
- `detections_in_section_<outlet>`: Output for section ROIs

### System Tables
- `trigger_processing_state_outlet_triggers`: Tracks trigger processing state

## Troubleshooting

### Common Issues

1. **"Table already exists" errors**
   - These are expected if re-running scripts
   - Scripts handle existing tables gracefully

2. **"ROI folder not found"**
   - Check that `P_Table_ROI_<outlet>` and `P_Section_ROI_<outlet>` folders exist
   - Verify the `OUTLET` variable matches your folder names

3. **"Polygon file format error"**
   - Ensure polygon files follow the exact format shown above
   - Check that coordinates are normalized (0.0-1.0)

4. **"Permission denied" errors**
   - Verify PostgreSQL user has necessary permissions
   - Check that the Python virtual environment is activated

5. **Script fails during execution**
   - Check `combined_logs.log` for detailed error messages
   - Verify database connection parameters are correct

### Viewing Logs

All script output is logged to `combined_logs.log`:
```bash
tail -f combined_logs.log  # Watch logs in real-time
cat combined_logs.log      # View complete log
```

## Environment Variables

The bash script exports these variables for Python scripts:

```bash
# Database connection
DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

# Outlet configuration
OUTLET

# ROI paths and table names
TABLE_ROI_FOLDER, TABLE_ROI_GEOMETRY_TABLE, TABLE_ROI_MATRIX_TABLE
SECTION_ROI_FOLDER, SECTION_ROI_GEOMETRY_TABLE

# Output configuration
DETECTIONS_TABLE_NAME, TABLE_OUTPUT_MAPPING
```

## Performance Notes

- The trigger system processes detections incrementally using ID tracking
- Spatial indexes ensure fast containment checks
- TimescaleDB partitioning optimizes time-series queries
- Each outlet is processed independently for better scalability

## Support

For issues or questions:
1. Check `combined_logs.log` for error details
2. Verify your ROI data format matches the examples
3. Ensure all prerequisites are installed correctly

## License

[Add your license information here]

## Contributors

[Add contributor information here]
