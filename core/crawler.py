import hashlib
from pathlib import Path
from core.database import ClustreeDB

class Crawler:
    def __init__(self, db: ClustreeDB, chunk_size=8192):
        self.db = db
        self.chunk_size = chunk_size
        self.supported_extensions = {'.jpg', '.jpeg', '.png', '.mp4', '.mov', '.avi'}

    def get_file_hash(self, file_path: Path) -> str:
        """Calculates SHA-256 hash of a file safely in chunks."""
        sha256 = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                while chunk := f.read(self.chunk_size):
                    sha256.update(chunk)
            return sha256.hexdigest()
        except Exception as e:
            print(f"Error hashing {file_path}: {e}")
            return None

    def scan_directory(self, target_dir: str):
        """Recursively finds media files and inserts them into the DB."""
        target_path = Path(target_dir)
        
        for file_path in target_path.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in self.supported_extensions:
                
                # Check if already in DB to allow pausing/resuming
                cursor = self.db.conn.cursor()
                cursor.execute("SELECT id FROM files WHERE original_path = ?", (str(file_path),))
                if cursor.fetchone():
                    continue 

                file_size = file_path.stat().st_size
                file_hash = self.get_file_hash(file_path)

                # Check for duplicates across the entire database
                cursor.execute("SELECT id FROM files WHERE file_hash = ?", (file_hash,))
                is_duplicate = 1 if cursor.fetchone() else 0

                cursor.execute('''
                    INSERT INTO files (original_path, file_hash, file_size, is_duplicate)
                    VALUES (?, ?, ?, ?)
                ''', (str(file_path), file_hash, file_size, is_duplicate))
                
                self.db.conn.commit()
                print(f"Indexed: {file_path.name} | Dup: {bool(is_duplicate)}")
