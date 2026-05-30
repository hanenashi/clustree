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
- App version constant and visible version/status bar.
- Settings pane.
- Settings saved to `clustree_settings.json`.
- Configurable cluster gap presets.
- Configurable thumbnail size.
- Cluster names saved to the database without moving files immediately.
- Cluster list shows saved names.
- Dry-run move plan preview.
- Move plan JSON export as `clustree_move_plan_YYYYMMDD_HHMMSS.json`.
- `Run Plan` button that executes the latest previewed plan.
- Collision-safe move names using `_2`, `_3`, etc.
- Basic missing-file handling during plan execution.

Still rough / not done yet:

- No thumbnail cache yet; thumbnails are regenerated when opening clusters.
- Video thumbnails are placeholders only.
- No ffprobe video creation-time extraction yet.
- Duplicate files are marked in DB, but not yet moved into a separate trash folder.
- No undo / rollback from executed plan yet.
- Manual split/merge UI is not implemented yet.
- UI is functional, not pretty. Which is fine. Pretty can wait in line.

---

## Architecture

Clustree is split into five practical parts:

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

### 3. Settings and version config

Located in `core/app_config.py`.

Current settings:

- app version: `0.2.0`
- cluster gap preset
- cluster gap hours
- thumbnail size

Settings are stored locally in:

```text
clustree_settings.json
```

This file is ignored by Git because it is local runtime state, not project code.

Cluster gap presets:

```text
Tight - 3 hours
Normal - 12 hours
Travel - 36 hours
Vacation blob - 72 hours
Custom
```

### 4. Metadata extractor

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

### 5. Cluster engine

Located in `core/cluster.py`.

The cluster engine sorts dated, non-duplicate files by computed time and groups them into events.

Current logic:

```text
If the gap between two files is <= selected cluster gap, keep them in the same event.
If the gap is larger, start a new event.
```

Before rebuilding clusters, Clustree now deletes non-archived old clusters and resets previously clustered files back to `dated`. That prevents repeated scans from creating duplicate ghost events. Ghost events are rude.

### 6. GUI triage app

Located in `gui/main_window.py`.

The GUI lets you:

- pick a folder to scan
- open settings
- choose cluster gap preset
- choose thumbnail size
- see detected events on the left
- click an event to load thumbnails
- drag selected files into another event
- save an event name without moving files
- preview a batch move plan for all named clusters
- run the previewed plan after confirmation

Current output folder pattern:

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
pip install -r requirements.txt
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
4. Save names for a few clusters.
5. Click `Preview Plan` and inspect the planned moves.
6. Only if the preview looks sane, click `Run Plan`.
7. Check moved output.
8. Only then try bigger folders.

Clustree moves files only when `Run Plan` is confirmed. Still: copied test folder first. Memories are not scratch files.

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
Build time-gap clusters using selected gap setting
   ↓
Triage in GUI
   ↓
Save names to clusters
   ↓
Preview move plan
   ↓
Run move plan
   ↓
Move files into dated folders
```

---

## Roadmap

The next direction is to keep pushing Clustree toward a safer triage queue with manual control.

### 0.2.0 - Settings and version foundation

Implemented:

- App version constant.
- Version shown at startup, in window title, in settings, and in status bar.
- Settings pane.
- Settings saved to `clustree_settings.json`.
- Cluster gap moved from hardcoded value into settings.
- Cluster gap presets:
  - Tight: 3 hours
  - Normal: 12 hours
  - Travel: 36 hours
  - Vacation blob: 72 hours
  - Custom: user-defined hours
- Active cluster gap shown in the status bar.
- Thumbnail size setting.

### 0.3.0 / 0.4.0 - Triage queue and dry-run move plan

Implemented first pass:

- Naming a cluster only saves `assigned_name` in the database.
- Pressing Enter in the name field saves the name, but does not move files.
- Cluster names are shown directly in the cluster list.
- Added `Save Name`, `Preview Plan`, and `Run Plan` buttons.
- `Run Plan` stays disabled until a dry-run preview exists.
- Preview supports a full batch plan for all named active clusters.
- Preview writes a JSON plan file:

```text
clustree_move_plan_YYYYMMDD_HHMMSS.json
```

Still needed:

- Better plan preview table UI instead of plain text.
- Executed-plan archive.
- Undo / rollback support.
- Dry-run-only mode.

### 0.5.0 - Manual cluster editing

Automatic time clustering is useful, but humans know when the park walk turned into soba.

Planned thumbnail context menu:

- Split before this photo
- Split after this photo
- Move selected to new cluster
- Move selected to existing cluster
- Open file location
- Mark ignored / duplicate later

Planned cluster-list context menu:

- Rename cluster
- Merge with previous cluster
- Merge with next cluster
- Delete empty cluster
- Recalculate cluster dates/counts

### 0.6.0 - Thumbnail and video improvements

- Add thumbnail cache in `.clustree_cache/thumbs/`.
- Reuse cached thumbnails when reopening a cluster.
- Add real video thumbnails via ffmpeg.
- Add video creation-time extraction via ffprobe.
- Consider faster preview scaling while loading, then nicer scaling when idle.

### 0.7.0 - Duplicate handling

- Add duplicate review screen.
- Show original/duplicate groups.
- Add `Move duplicates to _TRASH_DUPLICATES` action.
- Keep duplicate action manual at first. Automatic duplicate deletion is how tools become villains.

### 0.8.0 - Recovery and safety

- Add undo / recovery log.
- Save executed move plan.
- Support rollback from executed plan where possible.
- Add output destination selector.
- Add clear warning before moving real files.

### Later ideas

- Fast vs Accurate metadata mode.
- Better progress reporting in the GUI instead of terminal goblin noises.
- Multi-root scan sessions.
- Folder-level ignore rules.
- Side-by-side duplicate comparison.
- Open created folder after run.
- Optional compact/light theme tweaks.

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

That stage requires undo logs, thumbnail caching, manual split/merge, and more abuse testing. The goblin is awake, and now at least has brakes.
