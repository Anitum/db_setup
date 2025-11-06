from sqlalchemy import create_engine, MetaData, Table, Column, Integer, Float, String, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import TIMESTAMP
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
TABLE_NAME = "initial_frames"

# -------------------------------
# Create Table
# -------------------------------

# Create SQLAlchemy engine and metadata
engine = create_engine(DB_URL)
metadata = MetaData()

# Define the table schema
video_data = Table(
    TABLE_NAME,
    metadata,
    Column('timestamp', TIMESTAMP(timezone=False), nullable=False),
    Column('channel_id', Integer, nullable=False),
    Column('frame_id', Integer, nullable=False),
    Column('outlet', String, nullable=False),
    PrimaryKeyConstraint('timestamp', 'channel_id', 'frame_id', 'outlet', name=f'{TABLE_NAME}_pk')
)

# Create the table in the database
metadata.create_all(engine)

print(f"Table '{TABLE_NAME}' created successfully with a composite primary key (timestamp, channel_id, frame_id, outlet).")
