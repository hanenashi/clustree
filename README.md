# Clustree

<p align="center">
  <img src="clustree.png" width="400" alt="Clustree icon">
</p>

**Chaos photo-folder ingestion engine.**

Clustree is a desktop helper for chewing through messy media dumps: old phones, WhatsApp folders, `E:\temp`, half-forgotten backup drives, and other digital compost heaps.

The goal is simple: scan a chaotic folder, build a timeline, detect duplicate media, group files into time-based events, then let you quickly name and move those events into clean chronological folders.

It is not a polished consumer app yet. It is a working bulldozer. Keep hands away from moving teeth.

---

## Current state

The repo currently contains a working Python/PyQt triage app with a SQLite backend.

Implemented now:

- Recursive media scanning.
- SQLite database tracking of discovered files.
- Resume-friendly path tracking, so already-known files are skipped.
- Size-first duplicate detection.
- SHA-256 hashing only when another file with the same byte size exists.
- EXIF / filename / OS-date timeline extraction.
- Time-gap event clustering.
- Rebuildable cluster generation without stale duplicate cluster piles.
- PyQt thumbnail triage UI.
- Drag thumbnails between detected events.
- Rename / commit an event into a dated folder.
- Collision-safe move names using `_2`, `_3`, etc.
- Basic missing-file handling during commit.

Still rough / not done yet:

- No thumbnail cache yet; thumbnails are regenerated when opening clusters.
- Video thumbnails are placeholders only.
- No ffprobe video creation-time extraction yet.
- Duplicate files are marked in DB, but not yet moved into a separate trash folder.
- No dry-run / undo move plan yet.
- Cluster gap is still hardcoded to 12 hours in the GUI worker.
- UI is functional, not pretty. Which is fine. Pretty can wait in line.

---

## Architecture

Clustree is split into four practical parts:

### 1. Crawler

Located in `core/crawler.py`.

The crawler walks the selected folder and inserts supported media files into SQLite.

Supported extensions right now:

```text
.jpg .jpeg .png .mp4 .mov .avi
```

Current crawler behavior:

- Uses `os.scandir()` recursion for faster directory walking.
- Skips files already present in the database by `original_path`.
- Stores file size for every new file.
- Does **not** hash files with unique sizes.
- Hashes same-size candidates using SHA-256 in 4 MB chunks.
- Commits database work in batches instead of after every file.

This makes large scans much less stupid than the first naive version. Still Python, but less Python-with-ankle-weights.

### 2. Database

Located in `core/database.py`.

Clustree uses plain SQLite.

The database stores:

- original path
- SHA-256 hash, when needed
- file size
- EXIF date
- filename-regex date
- OS date
- computed final date
- duplicate flag
- cluster ID
- processing status

Current speed settings:

- WAL mode enabled.
- `synchronous=NORMAL`.
- in-memory temp storage.
- larger SQLite cache.
- indexes for hash, size, status, cluster ID, and computed date.

### 3. Metadata extractor

Located in `core/metadata.py`.

Date extraction uses a waterfall:

1. JPEG EXIF `DateTimeOriginal`.
2. Filename regex date/time.
3. OS creation/modification time.

Current filename patterns cover common Android / Pixel / WhatsApp-ish date formats, for example:

```text
PXL_20260517_154036124.jpg
IMG-20260517-WA0001.jpg
2026-05-17 15.40.36.jpg
```

Video metadata is not deeply parsed yet. For videos, filename or OS date is usually what you get for now.

### 4. Cluster engine

Located in `core/cluster.py`.

The cluster engine sorts dated, non-duplicate files by computed time and groups them into events.

Current logic:

```text
If the gap between two files is <= 12 hours, keep them in the same event.
If the gap is larger, start a new event.
```

Before rebuilding clusters, Clustree now deletes non-archived old clusters and resets previously clustered files back to `dated`. That prevents repeated scans from creating duplicate ghost events. Ghost events are rude.

### 5. GUI triage app

Located in `gui/main_window.py`.

The GUI lets you:

- pick a folder to scan
- see detected events on the left
- click an event to load thumbnails
- drag selected files into another event
- type an event name
- commit/move the event into a dated folder

Current commit output folder pattern:

```text
YYYY-MM-DD_Event_Name
```

Current output filename pattern:

```text
YYYYMMDD_HHMMSS_Event_Name_original_filename.ext
```

If a target filename already exists, Clustree appends `_2`, `_3`, etc.

---

## Running

Install dependencies first. Exact requirements may change, but the app currently expects Python with PyQt5, Pillow, and piexif available.

Typical setup:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install PyQt5 Pillow piexif
python main.py
```

On Linux/macOS, activation is instead usually:

```bash
source .venv/bin/activate
```

---

## Safe testing advice

Do **not** point this first at your only copy of the sacred photo archive.

Recommended test flow:

1. Make a small copied test folder.
2. Include a few JPEGs, PNGs, MP4s, and deliberate duplicates.
3. Run Clustree on that copy.
4. Check clustering and moved output.
5. Only then try bigger folders.

Clustree moves files when committing an event. It is not an image viewer toy; it has boots.

---

## Current pipeline

```text
Select folder
   ↓
Scan media files
   ↓
Store path + size in SQLite
   ↓
Hash only same-size candidates
   ↓
Mark exact duplicates
   ↓
Extract timeline date
   ↓
Build time-gap clusters
   ↓
Triage in GUI
   ↓
Name event
   ↓
Move files into dated folder
```

---

## Roadmap

High-value next steps:

- Thumbnail cache in `.clustree_cache/thumbs/`.
- Real video thumbnails via ffmpeg.
- Video creation-time extraction via ffprobe.
- Adjustable cluster gap presets: 3h, 12h, 36h, 72h.
- Fast vs Accurate metadata mode.
- Duplicate trash/export phase.
- Dry-run move plan before commit.
- Undo / recovery log.
- Safer multi-root output destination selector.
- Better progress reporting in the GUI instead of terminal goblin noises.

---

## Tech stack

- Python 3.8+
- SQLite3
- PyQt5
- Pillow
- piexif
- hashlib / SHA-256
- pathlib / os.scandir

---

## Status summary

Clustree is currently useful for testing and controlled real-world cleanup runs on copied folders.

It is not yet at the “trust it with the only copy of 15 years of family photos” stage.

That stage requires dry-run plans, undo logs, thumbnail caching, and more abuse testing. The goblin is awake, but not yet house-trained.
