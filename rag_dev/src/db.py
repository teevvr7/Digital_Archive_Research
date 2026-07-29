"""Database connection helper using psycopg 3 (modern psycopg) to align with backend virtualenv packages."""

import psycopg
from psycopg.rows import dict_row
from src.config import DATABASE_URL

def get_db_connection():
    """Return a new raw database connection returning dictionaries from rows."""
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    return conn

def init_db():
    """Verify database connection can be established."""
    try:
        conn = get_db_connection()
        conn.close()
        print("Database connection verified successfully.")
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        raise e
