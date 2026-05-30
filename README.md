# Clustree

<p align="center">
  <img src="clustree.png" width="400" alt="Clustree icon">
</p>

**Chaos photo-folder ingestion engine.**

Clustree is a Python/PyQt desktop helper for cleaning messy photo and video dumps. It scans media, extracts dates, detects exact duplicates, groups files into time-based events, lets you manually adjust those events, then previews and runs a safe move plan.

It is useful, but still sharp. Test on copied folders first. Memories are not scratch files.

---

## Current state

Implemented now:

- Recursive media scanning.
- SQLite tracking of discovered files.
- Resume-friendly path tracking.
- Size-first duplicate detection.
- SHA-256 hashing only for same-size candidates.
- EXIF / filename / OS-date timeline extraction.
- Time-gap clustering.
- Settings pane.
- Version display in startup/window/settings/status bar.
- Configurable cluster gap presets.
- Configurable thumbnail size.
- Configurable rename pattern.
- PyQt thumbnail triage UI.
- Drag thumbnails between clusters.
- Right-click thumbnail split:
  - split before this photo
  - split after this photo
- Right-click cluster-list merge:
  - merge selected clusters
  - merge with previous cluster
  - merge with next cluster
- Cluster names saved without moving files immediately.
- Dry-run move plan preview.
- Move plan JSON export.
- Confirmed `Run Plan` action.
- Collision-safe output paths.
- Basic missing-file handling.

Still rough:

- No thumbnail cache yet.
- Video thumbnails are placeholders only.
- No ffprobe video creation-time extraction yet.
- No duplicate review screen yet.
- No undo / rollback from executed plan yet.
- Plan preview is plain text, not a nice table.

---

## Quick start

Use the helper script:

```bash
chmod +x run.sh
./run.sh
```

`run.sh` uses `.venv`, installs requirements quietly, and starts `main.py`.

Manual setup:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

On Windows, activation is usually:

```bat
.venv\Scripts\activate
python main.py
```

---

## Current workflow

```text
Select folder
   ↓
Scan media files
   ↓
Store path + size in SQLite
   ↓
Hash only same-size candidates
   ↓
Extract timeline dates
   ↓
Build clusters using selected gap setting
   ↓
Review thumbnails
   ↓
Split / merge / drag as needed
   ↓
Save names to clusters
   ↓
Preview move plan
   ↓
Run move plan
   ↓
Files move into dated folders
```

---

## Settings

Settings are stored locally in:

```text
clustree_settings.json
```

This file is ignored by Git.

Current settings:

- cluster gap preset
- custom cluster gap hours
- thumbnail size
- rename pattern

Cluster gap presets:

```text
Tight - 3 hours
Normal - 12 hours
Travel - 36 hours
Vacation blob - 72 hours
Custom
```

Rename patterns:

```text
Clean sequence: 2026-05-12_sakura_001.jpg
Timestamp:      20260512_121459_sakura.jpg
Keep original:  20260512_121459_sakura_PXL_20260512_031459393.jpg
```

Default is clean sequence.

---

## Output

Current output folder pattern:

```text
YYYY-MM-DD_Event_Name
```

Current default filename pattern:

```text
YYYY-MM-DD_Event_Name_001.ext
```

If a target filename already exists, Clustree appends `_2`, `_3`, etc.

---

## Important files

```text
main.py                 app entry point
gui/main_window.py      PyQt UI, split/merge, plan preview/run
core/app_config.py      version and settings
core/crawler.py         scanner and hash logic
core/database.py        SQLite setup
core/metadata.py        date extraction
core/cluster.py         time-gap clustering
requirements.txt        Python dependencies
run.sh                  Unix/macOS/Termux launcher
```

---

## Roadmap

Next useful chunks:

- Better plan preview table.
- Thumbnail cache in `.clustree_cache/thumbs/`.
- Real video thumbnails via ffmpeg.
- Video creation-time extraction via ffprobe.
- Duplicate review screen.
- Move duplicates to `_TRASH_DUPLICATES` after review.
- Executed-plan archive.
- Undo / rollback where possible.
- Output destination selector.
- Open created folder after run.
- Better GUI progress reporting.

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

## Status

Clustree is currently good for controlled cleanup runs on copied folders.

It is not yet at the “trust it with the only copy of 15 years of family photos” stage. It now has brakes, split, and merge, but still needs undo and more abuse testing before being trusted with the sacred swamp.
