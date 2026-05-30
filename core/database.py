import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ClustreeDB:
    def __init__(self, db_path="clustree.db"):
        self.db_path = Path(db_path)
        # check_same_thread=False allows our PyQt5 background workers to safely read/write
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Initializes the database schema if it doesn't exist."""
        cursor = self.conn.cursor()
        
        # Files Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_path TEXT UNIQUE NOT NULL,
                file_hash TEXT,
                file_size INTEGER,
                exif_date TEXT,
                regex_date TEXT,
                os_date TEXT,
                computed_date TEXT,
                is_duplicate BOOLEAN DEFAULT 0,
                cluster_id INTEGER,
                status TEXT DEFAULT 'pending' 
            )
        ''')

        # Clusters Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_date TEXT,
                end_date TEXT,
                file_count INTEGER,
                assigned_name TEXT,
                status TEXT DEFAULT 'pending'
            )
        ''')
        
        self.conn.commit()
        logger.info("Database schema initialized.")

    def close(self):
        self.conn.close()
