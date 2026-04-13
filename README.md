# Clustree 🌳 (The Chaos Folder Ingestion Engine)

## Overview
If `Imagee` is a surgeon's scalpel for structured archives, `Clustree` is the bulldozer. 

Designed to process years of unsorted, chaotic photo dumps (multiple phones, WhatsApp downloads, random `E:\temp` folders), Clustree acts as a massive data-ingestion pipeline. It chews through tens of thousands of files, eliminates exact duplicates, calculates true timelines, and uses time-based clustering to automatically group unorganized media into sortable "Events."

The final output is a perfectly structured, chronologically named directory ready for flat-cloud ingestion (like Google Photos) without manual drag-and-drop hell.

## 🏗️ System Architecture
To handle 50,000+ files without crashing or losing progress, the app is split into a heavy-lifting backend and a lightweight frontend:
* **The Crawler (Headless):** Scans the file system, computes hashes, and extracts metadata.
* **The Brain (SQLite3):** A local `.db` file stores all file paths, hashes, and calculated dates so processing can be paused/resumed instantly.
* **The Triage UI (PyQt6):** Reads from the pre-computed database to instantly render visual thumbnail grids of detected events for rapid naming and sorting.

## 🗺️ The 4-Phase Pipeline

### Phase 1: The Great Deduplication (SHA-256)
Bypasses filenames entirely. Calculates a digital fingerprint (SHA-256 hash) of the actual file data. If two files have the exact same hash, they are identical.
* **Action:** Isolates all true duplicates into a `_TRASH_DUPLICATES` directory.

### Phase 2: Timeline Extraction (The Waterfall Method)
Since folder names don't exist, the file must reveal its own birth date using a strict fallback hierarchy:
1. `EXIF:DateTimeOriginal` (The Gold Standard)
2. Filename Regex (e.g., extracting `2021:10:12` from `WhatsApp Image 2021-10-12...`)
3. OS File Creation/Modification Date (The Last Resort)

### Phase 3: "Magic Clusters" (Automated Event Detection)
Instead of presenting 50,000 individual photos, the engine uses time-based algorithms to detect "bursts" of photos. 
* **Logic:** "If photos are taken within 12 hours of each other, followed by a 2-day gap, group them into a single 'Cluster'."
* **Result:** Reduces 50,000 files into ~800 highly manageable events.

### Phase 4: The Triage GUI & Smart Rename
A high-speed PyQt6 interface designed for rapid workflow.
* **Layout:** Auto-generated clusters on the left, massive thumbnail grid in the center, naming input on the bottom.
* **Action:** Click a cluster (e.g., *142 photos from 2021-08-15*), type "Beach Trip", and hit Enter. 
* **Automation:** The script creates the folder, moves the media, and chronologically renames every file (`20210815_Beach_Trip_IMG_0001.jpg`).

## 👾 Gremlin Handling: File Name Collisions
When merging files from two different devices (e.g., two phones generating `IMG_1042.JPG` on the same trip), Clustree prevents accidental overwriting during the Smart Rename phase by automatically appending the EXIF camera model or a short hash (e.g., `IMG_1042_Pixel5.jpg`).

## 🛠️ Tech Stack
* **Language:** Python 3.8+
* **Database:** `sqlite3` (Native)
* **GUI Framework:** PyQt6
* **File Hashing:** `hashlib` (SHA-256)
* **Metadata Processing:** `piexif`, `Pillow`, `re`
* 
