import re
import logging
from datetime import datetime, timedelta
from pathlib import Path

import piexif

from core.database import ClustreeDB

logger = logging.getLogger(__name__)


QUICKTIME_EPOCH = datetime(1904, 1, 1)
QUICKTIME_CONTAINER_ATOMS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"ilst"}
QUICKTIME_META_ATOM = b"meta"
MAX_QUICKTIME_SCAN_BYTES = 64 * 1024 * 1024
IMAGE_DATE_EXTENSIONS = (".jpg", ".jpeg")
VIDEO_DATE_EXTENSIONS = (".mov", ".mp4")


class MetadataExtractor:
    def __init__(self, db: ClustreeDB):
        self.db = db
        
        # Regex for Android/Pixel/Standard formats with Time (e.g., PXL_20260517_154036124, 2026-05-17 15.40.36)
        self.regex_with_time = re.compile(r'(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)[-_T\s]?([0-2]\d)[-_. ]?([0-5]\d)[-_. ]?([0-5]\d)')
        
        # Regex fallback for Date only (e.g., IMG-20260517-WA0001)
        self.regex_date_only = re.compile(r'(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)')

    def _normalize_exif_datetime(self, value) -> str:
        if not value:
            return None

        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")

        value = str(value).strip().split("\x00", 1)[0]
        if not value:
            return None

        normalized = value.replace(":", "-", 2)

        try:
            datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

        return normalized

    def _get_exif_date(self, file_path: Path) -> str:
        """Extracts the best embedded image/video capture date available."""
        if file_path.suffix.lower() in VIDEO_DATE_EXTENSIONS:
            sibling_date = self._get_same_stem_image_date(file_path)
            if sibling_date:
                return sibling_date

            return self._get_quicktime_date(file_path)

        return self._get_image_metadata_date(file_path)

    def _get_image_metadata_date(self, file_path: Path) -> str:
        if file_path.suffix.lower() not in IMAGE_DATE_EXTENSIONS:
            return None

        try:
            exif_dict = piexif.load(str(file_path))
            candidates = (
                exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal),
                exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeDigitized),
                exif_dict.get("0th", {}).get(piexif.ImageIFD.DateTime),
            )

            for candidate in candidates:
                normalized = self._normalize_exif_datetime(candidate)
                if normalized:
                    return normalized
        except Exception as e:
            logger.debug(f"EXIF read failed for {file_path.name}: {e}")
            
        return None

    def _get_same_stem_image_date(self, file_path: Path) -> str:
        """Uses a same-name image next to a video, common in iPhone/Live Photo dumps."""
        if file_path.suffix.lower() not in VIDEO_DATE_EXTENSIONS:
            return None

        suffixes = (".JPG", ".JPEG", ".jpg", ".jpeg")

        for suffix in suffixes:
            candidate = file_path.with_suffix(suffix)
            if candidate == file_path or not candidate.exists():
                continue

            date_value = self._get_image_metadata_date(candidate)
            if date_value:
                return date_value

        return None

    def _read_atom_header(self, handle):
        header = handle.read(8)
        if len(header) < 8:
            return None

        atom_size = int.from_bytes(header[:4], "big")
        atom_type = header[4:8]
        header_size = 8

        if atom_size == 1:
            extended_size = handle.read(8)
            if len(extended_size) < 8:
                return None
            atom_size = int.from_bytes(extended_size, "big")
            header_size = 16
        elif atom_size == 0:
            return atom_type, 0, header_size

        if atom_size < header_size:
            return None

        return atom_type, atom_size, header_size

    def _quicktime_datetime_from_seconds(self, seconds: int) -> str:
        if not seconds:
            return None

        try:
            value = QUICKTIME_EPOCH + timedelta(seconds=seconds)
        except OverflowError:
            return None

        if not 1990 <= value.year <= 2100:
            return None

        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _date_from_mvhd_payload(self, payload: bytes) -> str:
        if len(payload) < 8:
            return None

        version = payload[0]

        if version == 0 and len(payload) >= 8:
            seconds = int.from_bytes(payload[4:8], "big")
        elif version == 1 and len(payload) >= 12:
            seconds = int.from_bytes(payload[4:12], "big")
        else:
            return None

        return self._quicktime_datetime_from_seconds(seconds)

    def _date_from_quicktime_text(self, payload: bytes) -> str:
        match = re.search(
            rb"(20\d{2})[-:](\d{2})[-:](\d{2})[T ]([0-2]\d):(\d{2}):(\d{2})",
            payload,
        )
        if not match:
            return None

        year, month, day, hour, minute, second = [
            part.decode("ascii", errors="ignore") for part in match.groups()
        ]

        try:
            datetime(
                int(year),
                int(month),
                int(day),
                int(hour),
                int(minute),
                int(second),
            )
        except ValueError:
            return None

        return f"{year}-{month}-{day} {hour}:{minute}:{second}"

    def _scan_quicktime_atoms(self, handle, start: int, end: int, depth: int = 0) -> str:
        if depth > 8:
            return None

        handle.seek(start)

        while handle.tell() + 8 <= end:
            atom_start = handle.tell()
            header = self._read_atom_header(handle)
            if not header:
                return None

            atom_type, atom_size, header_size = header
            atom_end = end if atom_size == 0 else atom_start + atom_size

            if atom_end <= atom_start or atom_end > end:
                return None

            payload_start = atom_start + header_size
            payload_size = atom_end - payload_start

            if atom_type == b"mvhd":
                payload = handle.read(min(payload_size, 32))
                date_value = self._date_from_mvhd_payload(payload)
                if date_value:
                    return date_value
            elif atom_type == QUICKTIME_META_ATOM:
                if 0 < payload_size <= MAX_QUICKTIME_SCAN_BYTES:
                    payload = handle.read(payload_size)
                    date_value = self._date_from_quicktime_text(payload)
                    if date_value:
                        return date_value

                date_value = self._scan_quicktime_atoms(handle, payload_start + 4, atom_end, depth + 1)
                if date_value:
                    return date_value
            elif atom_type in QUICKTIME_CONTAINER_ATOMS:
                if 0 < payload_size <= MAX_QUICKTIME_SCAN_BYTES:
                    payload = handle.read(payload_size)
                    date_value = self._date_from_quicktime_text(payload)
                    if date_value:
                        return date_value

                date_value = self._scan_quicktime_atoms(handle, payload_start, atom_end, depth + 1)
                if date_value:
                    return date_value
            elif payload_size > 0 and payload_size <= MAX_QUICKTIME_SCAN_BYTES:
                payload = handle.read(payload_size)
                date_value = self._date_from_quicktime_text(payload)
                if date_value:
                    return date_value

            handle.seek(atom_end)

        return None

    def _get_quicktime_date(self, file_path: Path) -> str:
        """Extracts creation time from MOV/MP4 atoms without requiring ffprobe."""
        if file_path.suffix.lower() not in {".mov", ".mp4"}:
            return None

        try:
            file_size = file_path.stat().st_size
            with file_path.open("rb") as handle:
                return self._scan_quicktime_atoms(handle, 0, file_size)
        except Exception as e:
            logger.debug(f"QuickTime date read failed for {file_path.name}: {e}")

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

    def process_pending_files(self, progress_callback=None):
        """Iterates through database and calculates the True Date for each file."""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, original_path FROM files WHERE status = 'pending'")
        rows = cursor.fetchall()
        total = len(rows)

        updates = []
        for index, row in enumerate(rows, start=1):
            file_id = row['id']
            file_path = Path(row['original_path'])
            
            if not file_path.exists():
                updates.append(('missing', None, None, None, None, file_id))
                if progress_callback and (index % 50 == 0 or index == total):
                    progress_callback(index, total, file_path.name, "missing")
                continue

            exif_date = self._get_exif_date(file_path)
            regex_date = self._get_regex_date(file_path.name)
            os_date = self._get_os_date(file_path)

            # The Waterfall logic
            computed_date = exif_date or regex_date or os_date

            updates.append(('dated', exif_date, regex_date, os_date, computed_date, file_id))
            source_label = 'METADATA' if exif_date else 'REGEX' if regex_date else 'OS'
            print(f"Dated: {file_path.name} | Computed: {computed_date} | Source: {source_label}")

            if progress_callback and (index % 50 == 0 or index == total):
                progress_callback(index, total, file_path.name, source_label)

        # Batch update the database
        cursor.executemany('''
            UPDATE files 
            SET status = ?, exif_date = ?, regex_date = ?, os_date = ?, computed_date = ?
            WHERE id = ?
        ''', updates)
        
        self.db.conn.commit()
        print(f"Successfully extracted timeline data for {len(updates)} files.")

        return {
            "processed": len(updates),
            "pending": total,
        }
