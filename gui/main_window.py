import json
import re
import shutil
import warnings
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QProgressBar,
    QLineEdit, QPushButton, QMessageBox, QFileDialog,
    QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox,
    QPlainTextEdit, QMenu
)

# Silence the High Sierra SIP deprecation warning
warnings.filterwarnings("ignore", message="sipPyTypeDict.. is deprecated")

from PyQt5.QtGui import QPixmap, QIcon, QImage
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal

from core.app_config import (
    APP_VERSION,
    CLUSTER_GAP_PRESETS,
    RENAME_PATTERN_OPTIONS,
    AppSettings,
    load_settings,
    save_settings,
    rename_pattern_label_from_value,
)
from core.crawler import Crawler
from core.metadata import MetadataExtractor
from core.cluster import ClusterEngine


class SettingsDialog(QDialog):
    """Small settings pane for configurable Clustree options."""

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clustree Settings")

        self.settings = AppSettings(
            cluster_gap_preset=settings.cluster_gap_preset,
            cluster_gap_hours=settings.cluster_gap_hours,
            thumbnail_size=settings.thumbnail_size,
            rename_pattern=settings.rename_pattern,
        ).normalize()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.version_label = QLabel(f"Clustree {APP_VERSION}")
        form.addRow("Version:", self.version_label)

        self.gap_preset_combo = QComboBox()
        for preset_name in CLUSTER_GAP_PRESETS.keys():
            self.gap_preset_combo.addItem(preset_name)

        preset_index = self.gap_preset_combo.findText(self.settings.cluster_gap_preset)
        if preset_index < 0:
            preset_index = self.gap_preset_combo.findText("Custom")

        self.gap_preset_combo.setCurrentIndex(preset_index)
        self.gap_preset_combo.currentTextChanged.connect(self.on_gap_preset_changed)
        form.addRow("Cluster gap preset:", self.gap_preset_combo)

        self.gap_hours_spin = QSpinBox()
        self.gap_hours_spin.setRange(1, 168)
        self.gap_hours_spin.setSuffix(" hours")
        self.gap_hours_spin.setValue(self.settings.cluster_gap_hours)
        form.addRow("Cluster gap:", self.gap_hours_spin)

        self.thumbnail_size_spin = QSpinBox()
        self.thumbnail_size_spin.setRange(64, 512)
        self.thumbnail_size_spin.setSingleStep(16)
        self.thumbnail_size_spin.setSuffix(" px")
        self.thumbnail_size_spin.setValue(self.settings.thumbnail_size)
        form.addRow("Thumbnail size:", self.thumbnail_size_spin)

        self.rename_pattern_combo = QComboBox()
        for label in RENAME_PATTERN_OPTIONS.keys():
            self.rename_pattern_combo.addItem(label)

        current_label = rename_pattern_label_from_value(self.settings.rename_pattern)
        pattern_index = self.rename_pattern_combo.findText(current_label)
        if pattern_index < 0:
            pattern_index = 0

        self.rename_pattern_combo.setCurrentIndex(pattern_index)
        form.addRow("Rename pattern:", self.rename_pattern_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.on_gap_preset_changed(self.gap_preset_combo.currentText())

    def on_gap_preset_changed(self, preset_name):
        preset_value = CLUSTER_GAP_PRESETS.get(preset_name)
        is_custom = preset_value is None

        self.gap_hours_spin.setEnabled(is_custom)

        if preset_value is not None:
            self.gap_hours_spin.setValue(preset_value)

    def get_settings(self) -> AppSettings:
        preset_name = self.gap_preset_combo.currentText()
        rename_label = self.rename_pattern_combo.currentText()

        return AppSettings(
            cluster_gap_preset=preset_name,
            cluster_gap_hours=self.gap_hours_spin.value(),
            thumbnail_size=self.thumbnail_size_spin.value(),
            rename_pattern=RENAME_PATTERN_OPTIONS.get(rename_label, "clean_sequence"),
        ).normalize()


class PlanPreviewDialog(QDialog):
    """Read-only dry-run preview window."""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview Move Plan")
        self.resize(900, 650)

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"Plan file: {plan.get('plan_path', '(not saved)')}\n"
            f"Rename pattern: {plan.get('rename_pattern_label', '(unknown)')}\n"
            f"Clusters: {len(plan.get('clusters', []))} | "
            f"Moves: {len(plan.get('moves', []))} | "
            f"Warnings: {len(plan.get('warnings', []))}"
        )
        layout.addWidget(summary)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(self._format_plan(plan))
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _format_plan(self, plan):
        lines = []
        lines.append("CLUSTREE DRY-RUN MOVE PLAN")
        lines.append("=" * 80)
        lines.append(f"Created: {plan.get('created_at')}")
        lines.append(f"Version: {plan.get('app_version')}")
        lines.append(f"Rename pattern: {plan.get('rename_pattern_label', plan.get('rename_pattern'))}")
        lines.append("")

        warnings_list = plan.get("warnings", [])
        if warnings_list:
            lines.append("WARNINGS")
            lines.append("-" * 80)
            for warning in warnings_list:
                lines.append(f"- {warning}")
            lines.append("")

        lines.append("MOVES")
        lines.append("-" * 80)

        for move in plan.get("moves", []):
            lines.append(f"Cluster {move['cluster_id']} | {move['event_name']}")
            lines.append(f"FROM: {move['from']}")
            lines.append(f"TO:   {move['to']}")
            lines.append("")

        if not plan.get("moves"):
            lines.append("No moves planned. Name some clusters first. The goblin waits.")

        return "\n".join(lines)


class IngestionWorker(QThread):
    """Background thread to run the 3-phase engine without freezing the GUI."""

    finished = pyqtSignal()

    def __init__(self, db, target_dir, cluster_gap_hours=12):
        super().__init__()
        self.db = db
        self.target_dir = target_dir
        self.cluster_gap_hours = cluster_gap_hours

    def run(self):
        crawler = Crawler(self.db)
        crawler.scan_directory(self.target_dir)

        extractor = MetadataExtractor(self.db)
        extractor.process_pending_files()

        cluster_engine = ClusterEngine(self.db, max_gap_hours=self.cluster_gap_hours)
        cluster_engine.build_clusters()

        self.finished.emit()


class ThumbnailWorker(QThread):
    """Background thread to safely load and scale images without freezing the UI."""

    progress = pyqtSignal(int)
    thumb_ready = pyqtSignal(int, str, str, QImage)
    finished = pyqtSignal()

    def __init__(self, files, thumbnail_size=200):
        super().__init__()
        self.files = files
        self.thumbnail_size = thumbnail_size
        self.is_running = True

    def run(self):
        for i, f in enumerate(self.files):
            if not self.is_running:
                break

            file_id = f["id"]
            file_path = f["original_path"]
            file_name = Path(file_path).name

            if file_path.lower().endswith((".jpg", ".jpeg", ".png")):
                img = QImage(file_path)
                img = img.scaled(
                    self.thumbnail_size,
                    self.thumbnail_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb_ready.emit(file_id, file_path, file_name, img)
            else:
                self.thumb_ready.emit(file_id, file_path, file_name, QImage())

            self.progress.emit(i + 1)

        self.finished.emit()

    def stop(self):
        self.is_running = False


class ClusterListWidget(QListWidget):
    """Custom ListWidget for the sidebar to handle drag-and-drop reassignment."""

    file_reassigned = pyqtSignal(str, int)  # Emits: file_path, new_cluster_id

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.source() and event.source() != self:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.source() and event.source() != self:
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        target_item = self.itemAt(event.pos())

        if not target_item or event.source() == self:
            event.ignore()
            return

        new_cluster_id = target_item.data(Qt.ItemDataRole.UserRole)
        source_widget = event.source()

        for item in source_widget.selectedItems():
            payload = item.data(Qt.ItemDataRole.UserRole)

            if isinstance(payload, dict):
                file_path = payload.get("path")
            else:
                file_path = payload

            if not file_path:
                continue

            self.file_reassigned.emit(file_path, new_cluster_id)
            source_widget.takeItem(source_widget.row(item))

        event.accept()


class ClustreeWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()

        self.db = db
        self.settings = load_settings()
        self.current_move_plan = None

        self.setWindowTitle(f"Clustree {APP_VERSION} - Triage")
        self.resize(1200, 800)

        self.current_cluster_id = None
        self.thumb_worker = None
        self.ingestion_worker = None

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # --- Left Panel: Cluster List & Controls ---
        left_panel = QVBoxLayout()

        left_header_layout = QHBoxLayout()
        left_header_layout.addWidget(QLabel("<b>Detected Events</b>"))

        self.scan_btn = QPushButton("Scan Folder...")
        self.scan_btn.clicked.connect(self.select_and_scan_folder)
        left_header_layout.addWidget(self.scan_btn)

        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        left_header_layout.addWidget(self.settings_btn)

        left_panel.addLayout(left_header_layout)

        self.cluster_list = ClusterListWidget()
        self.cluster_list.setFixedWidth(330)
        self.cluster_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.cluster_list.itemClicked.connect(self.start_loading_cluster)
        self.cluster_list.file_reassigned.connect(self.handle_file_reassigned)
        self.cluster_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cluster_list.customContextMenuRequested.connect(self.show_cluster_context_menu)

        left_panel.addWidget(self.cluster_list)
        main_layout.addLayout(left_panel)

        # --- Right Panel: Triage & Rename ---
        right_panel = QVBoxLayout()

        self.grid_header = QLabel("<b>Select a cluster to view media...</b>")

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()

        self.thumbnail_grid = QListWidget()
        self.thumbnail_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnail_grid.setIconSize(QSize(self.settings.thumbnail_size, self.settings.thumbnail_size))
        self.thumbnail_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnail_grid.setSpacing(10)
        self.thumbnail_grid.setDragEnabled(True)
        self.thumbnail_grid.setAcceptDrops(False)
        self.thumbnail_grid.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.thumbnail_grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.thumbnail_grid.customContextMenuRequested.connect(self.show_thumbnail_context_menu)

        name_layout = QHBoxLayout()

        self.rename_input = QLineEdit()
        self.rename_input.setPlaceholderText("Event name for selected cluster (saved only, no moving)...")
        self.rename_input.returnPressed.connect(self.save_cluster_name)
        self.rename_input.setEnabled(False)

        self.save_name_btn = QPushButton("Save Name")
        self.save_name_btn.setEnabled(False)
        self.save_name_btn.clicked.connect(self.save_cluster_name)

        name_layout.addWidget(self.rename_input)
        name_layout.addWidget(self.save_name_btn)

        plan_layout = QHBoxLayout()

        self.preview_btn = QPushButton("Preview Plan")
        self.preview_btn.clicked.connect(self.preview_move_plan)

        self.run_plan_btn = QPushButton("Run Plan")
        self.run_plan_btn.setEnabled(False)
        self.run_plan_btn.clicked.connect(self.run_move_plan)

        plan_layout.addWidget(self.preview_btn)
        plan_layout.addWidget(self.run_plan_btn)

        right_panel.addWidget(self.grid_header)
        right_panel.addWidget(self.progress_bar)
        right_panel.addWidget(self.thumbnail_grid)
        right_panel.addLayout(name_layout)
        right_panel.addLayout(plan_layout)

        main_layout.addLayout(right_panel)

        self.statusBar()
        self.update_status()
        self.load_clusters()

    def update_status(self, message="Ready"):
        pattern_label = rename_pattern_label_from_value(self.settings.rename_pattern).split(" - ")[0]

        self.statusBar().showMessage(
            f"{message} | Clustree {APP_VERSION} | "
            f"Gap: {self.settings.cluster_gap_hours}h | "
            f"Thumb: {self.settings.thumbnail_size}px | "
            f"Rename: {pattern_label}"
        )

    def invalidate_plan(self):
        self.current_move_plan = None
        self.run_plan_btn.setEnabled(False)

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)

        if dialog.exec_() != QDialog.Accepted:
            return

        self.settings = dialog.get_settings()
        save_settings(self.settings)

        self.thumbnail_grid.setIconSize(QSize(self.settings.thumbnail_size, self.settings.thumbnail_size))
        self.invalidate_plan()
        self.update_status("Settings saved")

    def handle_file_reassigned(self, file_path, new_cluster_id):
        """Updates the DB when a thumbnail is dropped onto a new cluster."""
        cursor = self.db.conn.cursor()
        cursor.execute(
            "UPDATE files SET cluster_id = ? WHERE original_path = ?",
            (new_cluster_id, file_path),
        )

        self._recalculate_all_cluster_counts(cursor)
        self.db.conn.commit()

        self.invalidate_plan()
        self.load_clusters()
        self.update_status("File reassigned")

    def select_and_scan_folder(self):
        target_dir = QFileDialog.getExistingDirectory(self, "Select Directory to Ingest")

        if not target_dir:
            return

        self.invalidate_plan()

        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning...")
        self.settings_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)

        self.grid_header.setText("<b>Engine running. Check terminal for live progress...</b>")
        self.thumbnail_grid.clear()

        self.update_status(f"Scanning with {self.settings.cluster_gap_hours}h cluster gap")

        self.ingestion_worker = IngestionWorker(
            self.db,
            target_dir,
            cluster_gap_hours=self.settings.cluster_gap_hours,
        )
        self.ingestion_worker.finished.connect(self.on_scan_complete)
        self.ingestion_worker.start()

    def on_scan_complete(self):
        self.scan_btn.setEnabled(True)
        self.settings_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)

        self.scan_btn.setText("Scan Folder...")
        self.grid_header.setText("<b>Scan complete! Select a cluster on the left.</b>")

        self.load_clusters()
        self.update_status("Scan complete")

    def load_clusters(self):
        self.cluster_list.clear()

        cursor = self.db.conn.cursor()
        cursor.execute(
            """
            SELECT id, start_date, file_count, assigned_name
            FROM clusters
            WHERE status != 'archived'
              AND file_count > 0
            ORDER BY start_date ASC, id ASC
            """
        )
        clusters = cursor.fetchall()

        for cluster in clusters:
            cid = cluster["id"]
            date = cluster["start_date"].split(" ")[0] if cluster["start_date"] else "unknown-date"
            count = cluster["file_count"]
            name = (cluster["assigned_name"] or "").strip()
            name_line = f"Name: {name}" if name else "Name: (unnamed)"

            item = QListWidgetItem(f"Event {cid} ({date})\n[{count} files] | {name_line}")
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self.cluster_list.addItem(item)

    def start_loading_cluster(self, item):
        cluster_id = item.data(Qt.ItemDataRole.UserRole)
        self.load_cluster_by_id(cluster_id)

    def load_cluster_by_id(self, cluster_id):
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.stop()
            self.thumb_worker.wait()

        self.thumbnail_grid.clear()
        self.current_cluster_id = cluster_id

        cursor = self.db.conn.cursor()

        cursor.execute(
            "SELECT assigned_name FROM clusters WHERE id = ?",
            (self.current_cluster_id,),
        )
        cluster = cursor.fetchone()
        assigned_name = (cluster["assigned_name"] or "") if cluster else ""

        cursor.execute(
            """
            SELECT id, original_path
            FROM files
            WHERE cluster_id = ?
              AND status != 'archived'
            ORDER BY computed_date ASC, id ASC
            """,
            (self.current_cluster_id,),
        )
        files = cursor.fetchall()

        self.grid_header.setText(f"<b>Viewing Event {self.current_cluster_id} ({len(files)} files)</b>")

        self.rename_input.setEnabled(True)
        self.save_name_btn.setEnabled(True)
        self.rename_input.setText(assigned_name)
        self.rename_input.setFocus()

        self.update_status(f"Viewing Event {self.current_cluster_id}")

        self.progress_bar.setMaximum(len(files))
        self.progress_bar.setValue(0)
        self.progress_bar.show()

        self.thumb_worker = ThumbnailWorker(files, thumbnail_size=self.settings.thumbnail_size)
        self.thumb_worker.thumb_ready.connect(self.add_thumbnail)
        self.thumb_worker.progress.connect(self.progress_bar.setValue)
        self.thumb_worker.finished.connect(self.progress_bar.hide)
        self.thumb_worker.start()

    def add_thumbnail(self, file_id, file_path, file_name, qimage):
        thumb_item = QListWidgetItem()

        if not qimage.isNull():
            pixmap = QPixmap.fromImage(qimage)
            thumb_item.setIcon(QIcon(pixmap))
        else:
            thumb_item.setText("Video File")

        thumb_item.setToolTip(file_name)
        thumb_item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "id": file_id,
                "path": file_path,
                "name": file_name,
            },
        )

        self.thumbnail_grid.addItem(thumb_item)

    # -------------------------------------------------------------------------
    # Cluster list context menu / merge
    # -------------------------------------------------------------------------

    def _selected_cluster_ids(self):
        """Returns selected cluster IDs from the left cluster list in visible order."""
        selected_raw = []

        for item in self.cluster_list.selectedItems():
            cluster_id = item.data(Qt.ItemDataRole.UserRole)
            if cluster_id is not None:
                selected_raw.append(cluster_id)

        ordered = []
        for row in range(self.cluster_list.count()):
            item = self.cluster_list.item(row)
            cluster_id = item.data(Qt.ItemDataRole.UserRole)
            if cluster_id in selected_raw and cluster_id not in ordered:
                ordered.append(cluster_id)

        return ordered

    def show_cluster_context_menu(self, pos):
        """
        Right-click menu for the cluster list.

        Supports:
        - merge selected clusters
        - merge single cluster with previous
        - merge single cluster with next
        """
        item = self.cluster_list.itemAt(pos)

        if not item:
            return

        if not item.isSelected():
            self.cluster_list.clearSelection()
            item.setSelected(True)
            self.cluster_list.setCurrentItem(item)

        selected_ids = self._selected_cluster_ids()
        if not selected_ids:
            return

        menu = QMenu(self)

        merge_selected_action = None
        merge_previous_action = None
        merge_next_action = None

        if len(selected_ids) >= 2:
            merge_selected_action = menu.addAction(f"Merge selected clusters ({len(selected_ids)})")
        else:
            merge_previous_action = menu.addAction("Merge with previous cluster")
            merge_next_action = menu.addAction("Merge with next cluster")

        action = menu.exec_(self.cluster_list.mapToGlobal(pos))

        if merge_selected_action and action == merge_selected_action:
            self.merge_clusters(selected_ids)
            return

        if merge_previous_action and action == merge_previous_action:
            neighbor_ids = self._neighbor_cluster_ids(selected_ids[0])
            if neighbor_ids["previous"] is None:
                QMessageBox.information(self, "Cannot Merge", "There is no previous cluster.")
                return
            self.merge_clusters([neighbor_ids["previous"], selected_ids[0]])
            return

        if merge_next_action and action == merge_next_action:
            neighbor_ids = self._neighbor_cluster_ids(selected_ids[0])
            if neighbor_ids["next"] is None:
                QMessageBox.information(self, "Cannot Merge", "There is no next cluster.")
                return
            self.merge_clusters([selected_ids[0], neighbor_ids["next"]])
            return

    def _active_cluster_ids_in_order(self):
        """Returns active cluster IDs in sidebar order."""
        cursor = self.db.conn.cursor()
        cursor.execute(
            """
            SELECT id
            FROM clusters
            WHERE status != 'archived'
              AND file_count > 0
            ORDER BY start_date ASC, id ASC
            """
        )
        return [row["id"] for row in cursor.fetchall()]

    def _neighbor_cluster_ids(self, cluster_id):
        """Returns previous/next active cluster IDs for one cluster."""
        ids = self._active_cluster_ids_in_order()

        if cluster_id not in ids:
            return {"previous": None, "next": None}

        index = ids.index(cluster_id)

        previous_id = ids[index - 1] if index > 0 else None
        next_id = ids[index + 1] if index < len(ids) - 1 else None

        return {
            "previous": previous_id,
            "next": next_id,
        }

    def merge_clusters(self, cluster_ids):
        """
        Merges several clusters into the first cluster ID in the list.

        Files are reassigned in DB only.
        No disk files are moved here.
        """
        cluster_ids = [cid for cid in cluster_ids if cid is not None]

        deduped = []
        for cid in cluster_ids:
            if cid not in deduped:
                deduped.append(cid)

        cluster_ids = deduped

        if len(cluster_ids) < 2:
            return

        target_cluster_id = cluster_ids[0]
        source_cluster_ids = cluster_ids[1:]

        reply = QMessageBox.question(
            self,
            "Merge Clusters",
            f"Merge {len(cluster_ids)} clusters into Event {target_cluster_id}?\n\n"
            "This only changes Clustree's database grouping. It does not move files on disk.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        cursor = self.db.conn.cursor()

        try:
            placeholders = ",".join("?" for _ in source_cluster_ids)

            cursor.execute(
                f"""
                UPDATE files
                SET cluster_id = ?
                WHERE cluster_id IN ({placeholders})
                  AND status != 'archived'
                """,
                [target_cluster_id] + source_cluster_ids,
            )

            cursor.execute(
                "SELECT assigned_name FROM clusters WHERE id = ?",
                (target_cluster_id,),
            )
            target = cursor.fetchone()
            target_name = (target["assigned_name"] or "").strip() if target else ""

            if not target_name:
                cursor.execute(
                    f"""
                    SELECT assigned_name
                    FROM clusters
                    WHERE id IN ({placeholders})
                      AND assigned_name IS NOT NULL
                      AND TRIM(assigned_name) != ''
                    ORDER BY start_date ASC, id ASC
                    LIMIT 1
                    """,
                    source_cluster_ids,
                )
                source_name_row = cursor.fetchone()

                if source_name_row:
                    cursor.execute(
                        "UPDATE clusters SET assigned_name = ? WHERE id = ?",
                        (source_name_row["assigned_name"], target_cluster_id),
                    )

            cursor.execute(
                f"""
                UPDATE clusters
                SET file_count = 0,
                    status = 'merged'
                WHERE id IN ({placeholders})
                """,
                source_cluster_ids,
            )

            self._recalculate_cluster_dates_and_count(cursor, target_cluster_id)
            self.db.conn.commit()

            self.invalidate_plan()
            self.load_clusters()
            self.load_cluster_by_id(target_cluster_id)

            self.update_status(
                f"Merged {len(cluster_ids)} clusters into Event {target_cluster_id}"
            )

        except Exception as e:
            self.db.conn.rollback()
            QMessageBox.critical(
                self,
                "Merge Failed",
                f"Could not merge clusters:\n{str(e)}",
            )

    # -------------------------------------------------------------------------
    # Thumbnail context menu / split
    # -------------------------------------------------------------------------

    def show_thumbnail_context_menu(self, pos):
        item = self.thumbnail_grid.itemAt(pos)

        if not item or not self.current_cluster_id:
            return

        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return

        file_id = payload.get("id")
        file_name = payload.get("name", "this photo")

        if not file_id:
            return

        menu = QMenu(self)

        split_before_action = menu.addAction(f"Split before {file_name}")
        split_after_action = menu.addAction(f"Split after {file_name}")

        action = menu.exec_(self.thumbnail_grid.mapToGlobal(pos))

        if action == split_before_action:
            self.split_current_cluster_at_file(file_id=file_id, clicked_file_goes_to_new=True)
        elif action == split_after_action:
            self.split_current_cluster_at_file(file_id=file_id, clicked_file_goes_to_new=False)

    def split_current_cluster_at_file(self, file_id, clicked_file_goes_to_new):
        """
        Splits the currently loaded cluster into two clusters.

        clicked_file_goes_to_new=True:
            Split before this photo.
            The clicked photo becomes the first item of the new cluster.

        clicked_file_goes_to_new=False:
            Split after this photo.
            The clicked photo stays in the old cluster.
        """
        if not self.current_cluster_id:
            return

        cursor = self.db.conn.cursor()

        cursor.execute(
            """
            SELECT id, computed_date
            FROM files
            WHERE cluster_id = ?
              AND status != 'archived'
            ORDER BY computed_date ASC, id ASC
            """,
            (self.current_cluster_id,),
        )
        files = cursor.fetchall()

        file_ids = [row["id"] for row in files]

        if file_id not in file_ids:
            QMessageBox.warning(
                self,
                "Split Failed",
                "That file is no longer part of the currently loaded cluster.",
            )
            return

        clicked_index = file_ids.index(file_id)

        if clicked_file_goes_to_new:
            split_index = clicked_index
        else:
            split_index = clicked_index + 1

        if split_index <= 0:
            QMessageBox.information(
                self,
                "Cannot Split",
                "Cannot split before the first file. The old cluster would be empty.",
            )
            return

        if split_index >= len(files):
            QMessageBox.information(
                self,
                "Cannot Split",
                "Cannot split after the last file. The new cluster would be empty.",
            )
            return

        new_files = files[split_index:]
        new_file_ids = [row["id"] for row in new_files]

        new_start = new_files[0]["computed_date"]
        new_end = new_files[-1]["computed_date"]
        new_count = len(new_files)

        try:
            cursor.execute(
                """
                INSERT INTO clusters (start_date, end_date, file_count, assigned_name, status)
                VALUES (?, ?, ?, ?, 'pending')
                """,
                (new_start, new_end, new_count, None),
            )
            new_cluster_id = cursor.lastrowid

            placeholders = ",".join("?" for _ in new_file_ids)
            cursor.execute(
                f"""
                UPDATE files
                SET cluster_id = ?
                WHERE id IN ({placeholders})
                """,
                [new_cluster_id] + new_file_ids,
            )

            self._recalculate_cluster_dates_and_count(cursor, self.current_cluster_id)
            self._recalculate_cluster_dates_and_count(cursor, new_cluster_id)

            self.db.conn.commit()

            self.invalidate_plan()
            self.load_clusters()
            self.load_cluster_by_id(self.current_cluster_id)

            self.update_status(
                f"Split Event {self.current_cluster_id}; created Event {new_cluster_id}"
            )

        except Exception as e:
            self.db.conn.rollback()
            QMessageBox.critical(
                self,
                "Split Failed",
                f"Could not split cluster:\n{str(e)}",
            )

    # -------------------------------------------------------------------------
    # Cluster recalculation helpers
    # -------------------------------------------------------------------------

    def _recalculate_all_cluster_counts(self, cursor):
        cursor.execute(
            """
            UPDATE clusters
            SET file_count = (
                SELECT COUNT(id)
                FROM files
                WHERE files.cluster_id = clusters.id
                  AND files.status != 'archived'
            )
            """
        )

    def _recalculate_cluster_dates_and_count(self, cursor, cluster_id):
        cursor.execute(
            """
            SELECT computed_date
            FROM files
            WHERE cluster_id = ?
              AND status != 'archived'
              AND computed_date IS NOT NULL
            ORDER BY computed_date ASC, id ASC
            """,
            (cluster_id,),
        )
        rows = cursor.fetchall()

        count = len(rows)

        if count == 0:
            cursor.execute(
                """
                UPDATE clusters
                SET start_date = NULL,
                    end_date = NULL,
                    file_count = 0
                WHERE id = ?
                """,
                (cluster_id,),
            )
            return

        start_date = rows[0]["computed_date"]
        end_date = rows[-1]["computed_date"]

        cursor.execute(
            """
            UPDATE clusters
            SET start_date = ?,
                end_date = ?,
                file_count = ?
            WHERE id = ?
            """,
            (start_date, end_date, count, cluster_id),
        )

    # -------------------------------------------------------------------------
    # Naming / plan / run
    # -------------------------------------------------------------------------

    def save_cluster_name(self):
        if not self.current_cluster_id:
            return

        event_name = self.rename_input.text().strip()

        cursor = self.db.conn.cursor()
        cursor.execute(
            "UPDATE clusters SET assigned_name = ? WHERE id = ?",
            (event_name or None, self.current_cluster_id),
        )
        self.db.conn.commit()

        self.invalidate_plan()
        self.load_clusters()
        self.update_status(f"Saved name for Event {self.current_cluster_id}")

    def _safe_event_name(self, event_name):
        """Creates a filesystem-friendly event name while keeping it readable."""
        safe_name = re.sub(r'[<>:"\\|?*/]+', "-", event_name.strip())
        safe_name = re.sub(r"\s+", "_", safe_name)
        safe_name = safe_name.strip(" ._-")

        return safe_name or "Unnamed_Event"

    def _build_output_filename(self, old_path: Path, computed_date: str, safe_name: str, sequence_number: int) -> str:
        """
        Builds the output filename according to the selected rename pattern.

        clean_sequence:
            2026-05-12_sakura_001.jpg

        timestamp:
            20260512_121459_sakura.jpg

        keep_original:
            20260512_121459_sakura_PXL_20260512_031459393.jpg
        """
        suffix = old_path.suffix
        computed_date = computed_date or "1970-01-01 00:00:00"

        date_part = computed_date.split(" ")[0]
        timestamp_part = computed_date.replace("-", "").replace(":", "").replace(" ", "_")

        if self.settings.rename_pattern == "timestamp":
            return f"{timestamp_part}_{safe_name}{suffix}"

        if self.settings.rename_pattern == "keep_original":
            return f"{timestamp_part}_{safe_name}_{old_path.name}"

        return f"{date_part}_{safe_name}_{sequence_number:03d}{suffix}"

    def _unique_planned_path(self, path: Path, reserved_paths: set) -> Path:
        """Returns a non-existing/non-reserved path by appending _2, _3, etc. if needed."""
        candidate = path
        parent = path.parent
        stem = path.stem
        suffix = path.suffix
        counter = 2

        while str(candidate) in reserved_paths or candidate.exists():
            candidate = parent / f"{stem}_{counter}{suffix}"
            counter += 1

        reserved_paths.add(str(candidate))
        return candidate

    def build_move_plan(self):
        cursor = self.db.conn.cursor()
        cursor.execute(
            """
            SELECT id, start_date, assigned_name
            FROM clusters
            WHERE status != 'archived'
              AND file_count > 0
              AND assigned_name IS NOT NULL
              AND TRIM(assigned_name) != ''
            ORDER BY start_date ASC, id ASC
            """
        )
        clusters = cursor.fetchall()

        plan = {
            "app_version": APP_VERSION,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "rename_pattern": self.settings.rename_pattern,
            "rename_pattern_label": rename_pattern_label_from_value(self.settings.rename_pattern),
            "plan_path": None,
            "clusters": [],
            "moves": [],
            "warnings": [],
        }

        reserved_paths = set()

        for cluster in clusters:
            cluster_id = cluster["id"]
            event_name = cluster["assigned_name"].strip()
            safe_name = self._safe_event_name(event_name)

            cursor.execute(
                """
                SELECT id, original_path, computed_date
                FROM files
                WHERE cluster_id = ?
                  AND status != 'archived'
                ORDER BY computed_date ASC, id ASC
                """,
                (cluster_id,),
            )
            files = cursor.fetchall()

            if not files:
                plan["warnings"].append(f"Cluster {cluster_id} has a name but no movable files.")
                continue

            first_date = (files[0]["computed_date"] or cluster["start_date"]).split(" ")[0]
            target_dir = Path(files[0]["original_path"]).parent.parent / f"{first_date}_{safe_name}"

            plan["clusters"].append(
                {
                    "cluster_id": cluster_id,
                    "event_name": event_name,
                    "safe_name": safe_name,
                    "target_dir": str(target_dir),
                    "file_count": len(files),
                }
            )

            for sequence_number, f in enumerate(files, start=1):
                old_path = Path(f["original_path"])
                computed_date = f["computed_date"] or cluster["start_date"]

                new_filename = self._build_output_filename(
                    old_path=old_path,
                    computed_date=computed_date,
                    safe_name=safe_name,
                    sequence_number=sequence_number,
                )
                new_path = self._unique_planned_path(target_dir / new_filename, reserved_paths)

                if not old_path.exists():
                    plan["warnings"].append(f"Missing source file: {old_path}")

                plan["moves"].append(
                    {
                        "file_id": f["id"],
                        "cluster_id": cluster_id,
                        "event_name": event_name,
                        "from": str(old_path),
                        "to": str(new_path),
                    }
                )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_path = Path(f"clustree_move_plan_{timestamp}.json")

        plan["plan_path"] = str(plan_path)

        plan_path.write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return plan

    def preview_move_plan(self):
        self.save_cluster_name()

        plan = self.build_move_plan()
        self.current_move_plan = plan

        self.run_plan_btn.setEnabled(bool(plan.get("moves")))
        self.update_status(f"Preview ready: {len(plan.get('moves', []))} moves")

        dialog = PlanPreviewDialog(plan, self)
        dialog.exec_()

    def run_move_plan(self):
        if not self.current_move_plan or not self.current_move_plan.get("moves"):
            QMessageBox.information(self, "No Plan", "Preview a move plan first.")
            return

        reply = QMessageBox.question(
            self,
            "Run Move Plan",
            f"Move {len(self.current_move_plan['moves'])} files now?\n\nThis changes files on disk.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        cursor = self.db.conn.cursor()
        moved = 0
        missing = 0
        touched_clusters = set()

        try:
            for move in self.current_move_plan["moves"]:
                file_id = move["file_id"]
                old_path = Path(move["from"])
                new_path = Path(move["to"])
                touched_clusters.add(move["cluster_id"])

                if not old_path.exists():
                    missing += 1
                    cursor.execute(
                        "UPDATE files SET status = 'missing' WHERE id = ?",
                        (file_id,),
                    )
                    continue

                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(new_path))

                cursor.execute(
                    "UPDATE files SET original_path = ?, status = 'archived' WHERE id = ?",
                    (str(new_path), file_id),
                )
                moved += 1

            for cluster_id in touched_clusters:
                cursor.execute(
                    "UPDATE clusters SET status = 'archived' WHERE id = ?",
                    (cluster_id,),
                )

            self.db.conn.commit()

            self.current_move_plan = None
            self.run_plan_btn.setEnabled(False)

            self.thumbnail_grid.clear()
            self.rename_input.clear()
            self.rename_input.setEnabled(False)
            self.save_name_btn.setEnabled(False)
            self.current_cluster_id = None

            self.load_clusters()
            self.update_status(f"Run complete: {moved} moved, {missing} missing")

            QMessageBox.information(
                self,
                "Run Complete",
                f"Moved: {moved}\nMissing: {missing}",
            )

        except Exception as e:
            self.db.conn.rollback()
            self.update_status("Run failed")
            QMessageBox.critical(
                self,
                "Error Running Plan",
                f"An error occurred: {str(e)}",
            )