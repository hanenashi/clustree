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
        self._tune_connection()
        self._init_schema()

    def _tune_connection(self):
        """Applies SQLite settings that make large ingestion runs less painfully slow."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA cache_size=-65536")  # 64 MB cache
        self.conn.commit()

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

        # Query accelerators for large libraries. original_path already has an implicit UNIQUE index.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_hash ON files(file_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_size ON files(file_size)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_cluster ON files(cluster_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_computed_date ON files(computed_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_status_duplicate_date ON files(status, is_duplicate, computed_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_clusters_status_date ON clusters(status, start_date)")
        
        self.conn.commit()
        logger.info("Database schema initialized.")

    def close(self):
        self.conn.close()
