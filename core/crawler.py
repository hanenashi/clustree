import hashlib
import os
from pathlib import Path
from core.database import ClustreeDB


class Crawler:
    def __init__(self, db: ClustreeDB, chunk_size=1024 * 1024 * 4, batch_size=500):
        self.db = db
        self.chunk_size = chunk_size
        self.batch_size = batch_size
        self.supported_extensions = {'.jpg', '.jpeg', '.png', '.mp4', '.mov', '.avi'}

    def iter_media_files(self, target_path: Path):
        """Fast recursive media scanner using os.scandir instead of Path.rglob."""
        stack = [target_path]

        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                file_path = Path(entry.path)
                                if file_path.suffix.lower() in self.supported_extensions:
                                    yield file_path, entry.stat(follow_symlinks=False).st_size
                        except OSError as e:
                            print(f"Skipping {entry.path}: {e}")
            except OSError as e:
                print(f"Skipping directory {current}: {e}")

    def get_file_hash(self, file_path: Path) -> str:
        """Calculates SHA-256 hash of a file safely in large chunks."""
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
        """Recursively finds media files, hashes only duplicate-size candidates, and inserts them into the DB."""
        target_path = Path(target_dir)
        cursor = self.db.conn.cursor()
        scanned = 0
        inserted = 0
        skipped = 0

        for file_path, file_size in self.iter_media_files(target_path):
            scanned += 1
            original_path = str(file_path)

            cursor.execute("SELECT id FROM files WHERE original_path = ?", (original_path,))
            if cursor.fetchone():
                skipped += 1
                continue

            # Size-first dedupe: unique sizes cannot be exact duplicates, so do not hash them yet.
            cursor.execute("SELECT id FROM files WHERE file_size = ? LIMIT 1", (file_size,))
            same_size_exists = cursor.fetchone() is not None

            file_hash = None
            is_duplicate = 0

            if same_size_exists:
                file_hash = self.get_file_hash(file_path)
                cursor.execute(
                    "SELECT id FROM files WHERE file_size = ? AND file_hash = ? LIMIT 1",
                    (file_size, file_hash),
                )
                is_duplicate = 1 if cursor.fetchone() else 0

                # Older files with this size may have been inserted before we knew their size had twins.
                cursor.execute(
                    "SELECT id, original_path FROM files WHERE file_size = ? AND file_hash IS NULL",
                    (file_size,),
                )
                unhashes = cursor.fetchall()
                for row in unhashes:
                    old_path = Path(row['original_path'])
                    if not old_path.exists():
                        continue
                    old_hash = self.get_file_hash(old_path)
                    old_is_duplicate = 1 if old_hash == file_hash else 0
                    cursor.execute(
                        "UPDATE files SET file_hash = ?, is_duplicate = ? WHERE id = ?",
                        (old_hash, old_is_duplicate, row['id']),
                    )

            cursor.execute('''
                INSERT INTO files (original_path, file_hash, file_size, is_duplicate)
                VALUES (?, ?, ?, ?)
            ''', (original_path, file_hash, file_size, is_duplicate))

            inserted += 1
            if inserted % self.batch_size == 0:
                self.db.conn.commit()
                print(f"Indexed batch: {inserted} new files ({scanned} scanned, {skipped} skipped)")

        self.db.conn.commit()
        print(f"Scan complete: {inserted} new files indexed, {skipped} already known, {scanned} media files seen.")
