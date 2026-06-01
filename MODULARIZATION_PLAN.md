# Clustree Modularization Plan

Clustree has grown from a small PyQt helper into a real photo triage application. The main risk now is that `gui/main_window.py` becomes a giant everything-file: UI layout, dialogs, workers, thumbnail logic, cluster surgery, move planning, rollback, duplicate cleanup, logging, and file operations all tangled together.

The goal of modularization is not to make the project look fancy. The goal is to make future changes safer.

Do not refactor everything at once. That is how working apps become fossils.

---

## Current problem

`gui/main_window.py` currently acts as:

```text
main window
settings UI
plan preview UI
thumbnail loading controller
cluster list controller
split/merge controller
move plan builder
move plan executor
rollback trigger
duplicate cleanup trigger
DELETE holding handler
log/status handler
```

That works while the app is small. It becomes dangerous once features interact.

Main risks:

```text
- accidental regressions while editing unrelated features
- circular logic hidden inside UI code
- hard-to-test file move / delete / rollback behavior
- very large diffs for small changes
- fear of touching the file
```

When a file becomes scary, it has already won.

---

## Target structure

A sane target structure:

```text
clustree/
  main.py

  core/
    app_config.py
    crawler.py
    database.py
    metadata.py
    cluster.py

  gui/
    main_window.py
    workers.py

    dialogs/
      __init__.py
      settings_dialog.py
      plan_preview_dialog.py
      help_dialog.py
      duplicate_review_dialog.py

    widgets/
      __init__.py
      cluster_list.py
      thumbnail_grid.py
      log_panel.py

    controllers/
      __init__.py
      cluster_actions.py
      move_plan_controller.py
      duplicate_controller.py
      delete_holding_controller.py

    services/
      __init__.py
      thumbnail_cache.py
      ffmpeg_tools.py
      file_ops.py
      move_plan.py
      rollback.py
      duplicate_cleanup.py
```

This is the destination, not the first commit.

---

## Refactor rule

Each extraction should be small enough that the app still runs after the commit.

After every step:

```bash
python -m py_compile core/app_config.py gui/main_window.py main.py
```

On Windows:

```bat
python -m py_compile core\app_config.py gui\main_window.py main.py
start.bat
```

Then commit:

```bash
git add .
git commit -m "extract settings dialog"
```

Small commits. No mega-refactor swamp monster.

---

## Phase 1: Extract dialogs

Safest first move.

Move dialog classes out of `main_window.py`:

```text
gui/dialogs/settings_dialog.py
gui/dialogs/plan_preview_dialog.py
gui/dialogs/help_dialog.py
gui/dialogs/duplicate_review_dialog.py
```

Create:

```text
gui/dialogs/__init__.py
```

Then `main_window.py` imports:

```python
from gui.dialogs.settings_dialog import SettingsDialog
from gui.dialogs.plan_preview_dialog import PlanPreviewDialog
from gui.dialogs.help_dialog import HelpDialog
from gui.dialogs.duplicate_review_dialog import DuplicateReviewDialog
```

Dialogs should not import `main_window.py`.

Good pattern:

```python
dialog = SettingsDialog(self.settings, self)
if dialog.exec_() == QDialog.Accepted:
    self.settings = dialog.get_settings()
```

Bad pattern:

```python
from gui.main_window import ClustreeWindow
```

That creates circular import soup.

---

## Phase 2: Extract workers

Move QThread classes into:

```text
gui/workers.py
```

Likely classes:

```text
IngestionWorker
ThumbnailWorker
```

Then `main_window.py` imports:

```python
from gui.workers import IngestionWorker, ThumbnailWorker
```

Workers are not layout code. Keep threading away from UI wiring.

---

## Phase 3: Extract widgets

Move custom widgets out of `main_window.py`:

```text
gui/widgets/cluster_list.py
gui/widgets/thumbnail_grid.py
gui/widgets/log_panel.py
```

Create:

```text
gui/widgets/__init__.py
```

Widgets should emit signals. They should not secretly rewrite the database.

Good:

```python
file_reassigned = pyqtSignal(str, int)
```

Bad:

```python
self.db.conn.execute(...)
```

---

## Phase 4: Extract thumbnail cache and ffmpeg helpers

Move thumbnail generation and video thumbnail code into services:

```text
gui/services/thumbnail_cache.py
gui/services/ffmpeg_tools.py
```

Example:

```python
# gui/services/ffmpeg_tools.py
from shutil import which

def find_ffmpeg():
    return which("ffmpeg")

def has_ffmpeg():
    return find_ffmpeg() is not None
```

Example:

```python
# gui/services/thumbnail_cache.py
class ThumbnailCache:
    def __init__(self, cache_dir, size):
        self.cache_dir = cache_dir
        self.size = size

    def get_or_create_thumbnail(self, file_path):
        ...
```

Why:

```text
- thumbnail logic is not UI layout
- ffmpeg detection should be testable
- cache invalidation should be isolated
```

---

## Phase 5: Extract move plan service

Most important safety extraction.

Move planning and file-moving logic into:

```text
gui/services/move_plan.py
gui/services/file_ops.py
```

Candidate functions:

```python
def build_move_plan(db, settings):
    ...

def write_move_plan(plan):
    ...

def execute_move_plan(db, plan):
    ...

def write_executed_result(result):
    ...
```

The GUI should do:

```python
plan = build_move_plan(self.db, self.settings)
dialog = PlanPreviewDialog(plan, self)
result = execute_move_plan(self.db, self.current_move_plan)
```

Services return data. They do not show message boxes.

Good service:

```python
return {"moved": moved, "missing": missing, "failed": failed}
```

Bad service:

```python
QMessageBox.information(...)
```

---

## Phase 6: Extract rollback service

Move rollback / undo logic into:

```text
gui/services/rollback.py
```

Candidate functions:

```python
def find_latest_executed_plan(cache_dir):
    ...

def rollback_executed_plan(db, executed_plan_path):
    ...

def write_rollback_result(result):
    ...
```

Rollback rules:

```text
- never overwrite an existing file
- skip missing moved files
- record every skipped item
- restore database rows only for successfully rolled-back files
- write rollback result JSON
```

---

## Phase 7: Extract cluster actions

Move split, merge, temp cluster, drag-to-cluster, and DELETE holding database logic into:

```text
gui/controllers/cluster_actions.py
gui/controllers/delete_holding_controller.py
```

Candidate functions:

```python
def split_cluster_at_file(db, cluster_id, file_id, clicked_file_goes_to_new):
    ...

def merge_clusters(db, cluster_ids):
    ...

def move_files_to_cluster(db, file_ids, target_cluster_id):
    ...

def create_temp_cluster_from_files(db, file_ids):
    ...

def move_files_to_delete_holding(db, file_ids):
    ...

def restore_files_from_delete_holding(db, file_ids):
    ...
```

GUI handles menus and confirmation dialogs. Controllers handle database updates and recalculation.

---

## Phase 8: Extract duplicate cleanup

Move duplicate review data and cleanup logic into:

```text
gui/services/duplicate_cleanup.py
gui/controllers/duplicate_controller.py
```

Candidate functions:

```python
def list_duplicate_groups(db):
    ...

def build_duplicate_cleanup_plan(db, selected_file_ids):
    ...

def execute_duplicate_cleanup(db, plan):
    ...

def rollback_latest_duplicate_cleanup(db):
    ...
```

The duplicate dialog should display data. It should not own deletion logic.

---

## Phase 9: Thin down main_window.py

Long-term goal:

```python
class ClustreeWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.settings = load_settings()

        self.setup_ui()
        self.connect_signals()
        self.load_clusters()

    def setup_ui(self):
        ...

    def connect_signals(self):
        ...

    def refresh_after_cluster_change(self):
        self.invalidate_plan()
        self.load_clusters()
        if self.current_cluster_id:
            self.load_cluster_by_id(self.current_cluster_id)
```

`main_window.py` should mostly contain:

```text
- layout setup
- signal wiring
- refresh orchestration
- small UI event handlers
```

It should not contain:

```text
- raw file moving
- rollback algorithms
- duplicate cleanup logic
- thumbnail cache internals
- ffmpeg subprocess details
```

Boring main windows are good. Boring code survives.

---

## Suggested commit order

Recommended order:

```text
1. extract settings dialog
2. extract plan preview dialog
3. extract help dialog
4. extract duplicate review dialog
5. extract workers
6. extract cluster list widget
7. extract thumbnail cache service
8. extract ffmpeg tools
9. extract move plan service
10. extract rollback service
11. extract cluster actions controller
12. extract duplicate cleanup service
13. thin main_window setup_ui/connect_signals
```

Do not combine these unless the diff is tiny.

---

## Import rules

Allowed direction:

```text
main_window.py -> dialogs
main_window.py -> widgets
main_window.py -> controllers
controllers -> services
services -> core/database-ish objects
```

Avoid:

```text
dialogs -> main_window.py
services -> main_window.py
core -> gui
```

`core/` should never import `gui/`.

The core should remain usable without PyQt.

---

## UI/service boundary

Use this rule:

```text
If code shows a QMessageBox, it belongs in GUI.
If code moves files, updates DB, or writes JSON, it probably belongs in a service/controller.
```

Good service:

```python
def execute_move_plan(db, plan):
    return result
```

Good GUI:

```python
result = execute_move_plan(self.db, plan)
QMessageBox.information(self, "Run Complete", format_result(result))
```

Bad service:

```python
def execute_move_plan(db, plan):
    QMessageBox.information(...)
```

Bad GUI:

```python
shutil.move(...)
cursor.execute(...)
json.dump(...)
```

---

## Testing strategy after modularization

Once move-plan and rollback are services, make simple smoke scripts.

Possible folder:

```text
tests/
  smoke_test.py
  fixtures/
```

First tests:

```text
scan -> cluster -> preview -> run -> undo
split -> merge -> preview
duplicate cleanup -> undo dupes
DELETE holding -> return files
```

No need for a giant test framework immediately. A basic repeatable smoke script already beats clicking everything manually.

---

## Final goal

The final goal is not "many files".

The final goal is:

```text
main_window.py is safe to edit
file-moving logic is testable
rollback logic is isolated
dialogs are replaceable
workers are understandable
future features do not require touching everything
```

Clustree is now powerful enough that structure matters.

Tiny scalpel first. Chainsaw never.
