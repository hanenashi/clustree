import os
import re
import platform
import logging
from datetime import datetime
from pathlib import Path
from PIL import Image, ExifTags

# Using piexif/Pillow for image EXIF
import piexif

from core.database import ClustreeDB

logger = logging.getLogger(__name__)

class MetadataExtractor:
    def __init__(self, db: ClustreeDB):
        self.db = db
        
        # Regex patterns to catch standard filename dates (e.g., IMG-20211012-WA001, 2021_10_12_screenshot)
        self.filename_date_patterns = [
            re.compile(r'(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)'),  # Matches YYYYMMDD or YYYY-MM-DD or YYYY_MM_DD
        ]

    def _get_exif_date(self, file_path: Path) -> str:
        """Extracts DateTimeOriginal from EXIF."""
        if file_path.suffix.lower() not in {'.jpg', '.jpeg'}:
            return None
            
        try:
            img = Image.open(file_path)
            exif_raw = img.getexif()
            if not exif_raw:
                return None
                
            # 36867 is the EXIF tag ID for DateTimeOriginal
            # Format usually looks like: '2021:10:12 14:30:00'
            date_str = exif_raw.get(36867) 
            if date_str:
                # Normalize EXIF date format to standard YYYY-MM-DD HH:MM:SS
                return date_str.replace(":", "-", 2)
        except Exception as e:
            logger.debug(f"EXIF read failed for {file_path.name}: {e}")
        return None

    def _get_regex_date(self, file_name: str) -> str:
        """Extracts date from filename using regex."""
        for pattern in self.filename_date_patterns:
            match = pattern.search(file_name)
            if match:
                year, month, day = match.groups()
                # Basic validation to avoid impossible dates
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
