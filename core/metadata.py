import os
import re
import platform
import logging
from datetime import datetime
from pathlib import Path
from PIL import Image, ExifTags

# Using piexif for deep EXIF extraction
import piexif

from core.database import ClustreeDB

logger = logging.getLogger(__name__)

class MetadataExtractor:
    def __init__(self, db: ClustreeDB):
        self.db = db
        
        # Regex for Android/Pixel/Standard formats with Time (e.g., PXL_20260517_154036124, 2026-05-17 15.40.36)
        self.regex_with_time = re.compile(r'(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)[-_T\s]?([0-2]\d)[-_. ]?([0-5]\d)[-_. ]?([0-5]\d)')
        
        # Regex fallback for Date only (e.g., IMG-20260517-WA0001)
        self.regex_date_only = re.compile(r'(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)')

    def _get_exif_date(self, file_path: Path) -> str:
        """Extracts DateTimeOriginal using piexif for deep EXIF parsing."""
        if file_path.suffix.lower() not in {'.jpg', '.jpeg'}:
            return None
            
        try:
            # piexif is much more aggressive at finding hidden EXIF data
            exif_dict = piexif.load(str(file_path))
            
            # DateTimeOriginal is hidden in the 'Exif' sub-dictionary
            date_bytes = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
            
            if date_bytes:
                # piexif returns raw bytes, so we decode it
                date_str = date_bytes.decode('utf-8')
                # Format: '2026:05:17 15:40:36' -> '2026-05-17 15:40:36'
                return date_str.replace(":", "-", 2)
        except Exception as e:
            logger.debug(f"EXIF read failed for {file_path.name}: {e}")
            
        return None

    def _get_regex_date(self, file_name: str) -> str:
        """Extracts date (and time if available) from filename using regex."""
        # 1. Try to extract Date AND Time
        match_time = self.regex_with_time.search(file_name)
        if match_time:
            year, month, day, hour, minute, second = match_time.groups()
            if 1 <= int(month) <= 12 and 1 <= int(day) <= 31 and int(hour) < 24:
                return f"{year}-{month}-{day} {hour}:{minute}:{second}"
                
        # 2. Fallback to Date only
        match_date = self.regex_date_only.search(file_name)
        if match_date:
            year, month, day = match_date.groups()
            if 1 <= int(month) <= 12 and 1 <= int(day) <= 31:
                return f"{year}-{month}-{day} 00:00:00"
                
        return None

    def _get_os_date(self, file_path: Path) -> str:
        """Gets the OS file creation or modification date."""
        stat = file_path.stat()
        try:
            # Try to get birthtime (creation date) if OS supports it (Windows/macOS)
            timestamp = stat.st_birthtime
        except AttributeError:
            # Fallback to modification time (Linux)
            timestamp = stat.st_mtime
            
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    def process_pending_files(self):
        """Iterates through database and calculates the True Date for each file."""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, original_path FROM files WHERE status = 'pending'")
        rows = cursor.fetchall()

        updates = []
        for row in rows:
            file_id = row['id']
            file_path = Path(row['original_path'])
            
            if not file_path.exists():
                updates.append(('missing', None, None, None, None, file_id))
                continue

            exif_date = self._get_exif_date(file_path)
            regex_date = self._get_regex_date(file_path.name)
            os_date = self._get_os_date(file_path)

            # The Waterfall logic
            computed_date = exif_date or regex_date or os_date

            updates.append(('dated', exif_date, regex_date, os_date, computed_date, file_id))
            print(f"Dated: {file_path.name} | Computed: {computed_date} | Source: {'EXIF' if exif_date else 'REGEX' if regex_date else 'OS'}")

        # Batch update the database
        cursor.executemany('''
            UPDATE files 
            SET status = ?, exif_date = ?, regex_date = ?, os_date = ?, computed_date = ?
            WHERE id = ?
        ''', updates)
        
        self.db.conn.commit()
        print(f"Successfully extracted timeline data for {len(updates)} files.")
