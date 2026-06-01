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
- Configurable staging/output root for manual promotion into a stable photo pool.
- GUI phase messages during scan/date/cluster ingestion.
- GUI ingestion progress counts for scanning, date extraction, and clustering.
- PyQt thumbnail triage UI.
- Thumbnail cache in `.clustree_cache/thumbs/`.
- EXIF orientation-aware image thumbnails.
- Optional video thumbnails via `ffmpeg`.
- Drag thumbnails between clusters.
- Right-click thumbnail split:
  - split before this photo
  - split after this photo
- Right-click selected thumbnails:
  - move selected to a new temp manual cluster for date-independent repeated subjects
  - move selected into an existing manual cluster
- Right-click cluster-list merge:
  - merge selected clusters
  - merge with previous cluster
  - merge with next cluster
- Cluster names saved without moving files immediately.
- Dry-run move plan preview.
- Event-folder checklist in move plan preview.
- Staging date audit for multi-day events and OS-timestamp fallbacks.
- Move plan JSON export.
- Confirmed `Run Plan` action.
- Compact multi-thumbnail drag preview.
- Highlighted cluster drop target during thumbnail reassignment.
- Duplicate review screen for exact hash groups.
- Confirmed duplicate cleanup into per-folder `_TRASH_DUPLICATES`.
- Duplicate cleanup archive in `.clustree_cache/duplicate_runs/`.
- `Undo Dupes` rollback from the latest duplicate cleanup archive.
- Collision-safe output paths.
- Same-stem `.AAE` sidecar moves for iPhone imports.
- Move-plan warnings for existing target folders, target collisions, missing sources, and output-root issues.
- Move-plan warnings for date-audit issues before staging.
- Created-folder paths recorded in executed-plan JSON.
- Executed-plan archive in `.clustree_cache/executed_plans/`.
- Rollback move data recorded in executed-plan JSON.
- `Undo Last Run` rollback from the latest executed-plan archive.
- Optional prompt to open created folders after a run.
- Basic missing-file handling.

Still rough:

- Video thumbnails fall back to placeholders when `ffmpeg` is unavailable.

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
- staging/output root

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

Current staging/output folder pattern:

```text
<staging/output root>\YYYY\YYYY MM.DD Event Name
```

Use a staging folder when you want to inspect generated event folders before
manually moving them into a stable pool such as `E:\FOTO`.

If staging/output root is empty, Clustree keeps the older source-adjacent pattern:

```text
YYYY-MM-DD_Event_Name
```

Current default filename pattern:

```text
YYYY-MM-DD_Event_Name_001.ext
```

If a target filename already exists, Clustree appends `_2`, `_3`, etc.

Same-stem iPhone `.AAE` sidecars follow the renamed media file when present.
For example, `IMG_1234.JPG` and `IMG_1234.AAE` become matching target stems.

The move preview audits staged event folders before anything moves. It flags
multi-day clusters, folder/file date mismatches, missing computed dates, and
files dated only from OS timestamps.

After a run, Clustree writes the executed-plan JSON into
`.clustree_cache/executed_plans/`. The result records created target folders and
reverse move data. `Undo Last Run` reads the latest archive, refuses unsafe
overwrites, moves files back, restores media rows to `clustered`, and reactivates
archived clusters when the rollback completes without failures. Rollback result
JSON is written under `.clustree_cache/rollback_results/`. Clustree can open up
to five created folders on request.

Thumbnails are cached under `.clustree_cache/thumbs/`. The cache key includes
file path, file size, modified time, and configured thumbnail size, so edited
or resized source files regenerate thumbnails automatically.
JPEG orientation metadata is applied before image thumbnails are cached, so
portrait phone photos should display upright in the triage grid.

If `ffmpeg` is available on `PATH`, Clustree extracts cached thumbnail frames
for `.mp4`, `.mov`, and `.avi` files. Without `ffmpeg`, videos keep the plain
placeholder thumbnail.

The Duplicate Review screen lists exact duplicate groups that already have
computed hashes. Clustree keeps the first ordered file in each exact hash group
as primary. Review rows can be moved into a `_TRASH_DUPLICATES` folder beside
their current source folder after confirmation. Cleanup results, warnings, and
reverse move data are written under `.clustree_cache/duplicate_runs/`.
`Undo Dupes` reads the latest cleanup archive, refuses unsafe overwrites, moves
files back, restores rows to `clustered`, and writes rollback results under
`.clustree_cache/duplicate_rollbacks/`.

For repeated everyday subjects that should not be grouped by capture date, select
thumbnails inside an event and use `Move selected to new temp cluster` from the
thumbnail context menu. Clustree creates a normal pending cluster from that
manual selection; name it like any other event before previewing/exporting. To
keep adding more shots to that subject later, use `Move selected to existing
cluster` from the same menu.

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

- Real-world polish after a larger import dry run.

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
