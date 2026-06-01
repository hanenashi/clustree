import json
import re
import shutil
import warnings
import hashlib
import subprocess
from datetime import datetime
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QProgressBar,
    QLineEdit, QPushButton, QMessageBox, QFileDialog,
    QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox,
    QPlainTextEdit, QMenu, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QInputDialog, QCheckBox
)

# Silence the High Sierra SIP deprecation warning
warnings.filterwarnings("ignore", message="sipPyTypeDict.. is deprecated")

from PyQt5.QtGui import (
    QPixmap, QIcon, QImage, QDesktopServices,
    QDrag, QPainter, QColor, QBrush
)
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal, QUrl
from PIL import Image, ImageOps

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

IMAGE_THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png")
VIDEO_THUMBNAIL_EXTENSIONS = (".mp4", ".mov", ".avi")
THUMBNAIL_CACHE_VERSION = "thumb-v2-exif-transpose"
MANUAL_CLUSTER_COLORS = (
    "#e3f6df",
    "#dff4ec",
    "#e9f6d8",
    "#dcefd6",
    "#e5f7e9",
)
DELETE_CLUSTER_ID = -1000001
DELETE_CLUSTER_COLOR = "#ffe5e5"


class SettingsDialog(QDialog):
    """Small settings pane for configurable Clustree options."""

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clustree Settings")

        self.settings = AppSettings(
            cluster_gap_preset=settings.cluster_gap_preset,
            cluster_gap_hours=settings.cluster_gap_hours,
            thumbnail_size=settings.thumbnail_size,
            show_thumbnail_file_info=settings.show_thumbnail_file_info,
            rename_pattern=settings.rename_pattern,
            output_root=settings.output_root,
            show_delete_cluster=settings.show_delete_cluster,
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

        self.show_thumbnail_file_info_check = QCheckBox("Show file name and size under thumbnails")
        self.show_thumbnail_file_info_check.setChecked(self.settings.show_thumbnail_file_info)
        form.addRow("Thumbnail labels:", self.show_thumbnail_file_info_check)

        self.rename_pattern_combo = QComboBox()
        for label in RENAME_PATTERN_OPTIONS.keys():
            self.rename_pattern_combo.addItem(label)

        current_label = rename_pattern_label_from_value(self.settings.rename_pattern)
        pattern_index = self.rename_pattern_combo.findText(current_label)
        if pattern_index < 0:
            pattern_index = 0

        self.rename_pattern_combo.setCurrentIndex(pattern_index)
        form.addRow("Rename pattern:", self.rename_pattern_combo)

        output_root_layout = QHBoxLayout()
        self.output_root_input = QLineEdit()
        self.output_root_input.setPlaceholderText("Use a staging folder; leave empty for source-adjacent output")
        self.output_root_input.setText(self.settings.output_root)

        self.output_root_btn = QPushButton("Browse...")
        self.output_root_btn.clicked.connect(self.browse_output_root)

        output_root_layout.addWidget(self.output_root_input)
        output_root_layout.addWidget(self.output_root_btn)
        form.addRow("Staging/output root:", output_root_layout)

        self.show_delete_cluster_check = QCheckBox("Show DELETE cluster")
        self.show_delete_cluster_check.setChecked(self.settings.show_delete_cluster)
        form.addRow("DELETE cluster:", self.show_delete_cluster_check)

        layout.addLayout(form)

        self.cleanup_btn = QPushButton("CLEANUP")
        self.cleanup_btn.clicked.connect(self.request_cleanup)
        layout.addWidget(self.cleanup_btn)

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
            show_thumbnail_file_info=self.show_thumbnail_file_info_check.isChecked(),
            rename_pattern=RENAME_PATTERN_OPTIONS.get(rename_label, "clean_sequence"),
            output_root=self.output_root_input.text().strip(),
            show_delete_cluster=self.show_delete_cluster_check.isChecked(),
        ).normalize()

    def browse_output_root(self):
        output_root = QFileDialog.getExistingDirectory(
            self,
            "Select Staging/Output Root",
            self.output_root_input.text().strip() or "",
        )

        if output_root:
            self.output_root_input.setText(output_root)

    def request_cleanup(self):
        parent = self.parent()
        if parent and hasattr(parent, "cleanup_local_state"):
            parent.cleanup_local_state()


class PlanPreviewDialog(QDialog):
    """Dry-run preview window with a real table instead of a path wall."""

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview Move Plan")
        self.resize(1100, 700)

        layout = QVBoxLayout(self)

        summary = QLabel(
            f"Plan file: {plan.get('plan_path', '(not saved)')}\n"
            f"Rename pattern: {plan.get('rename_pattern_label', '(unknown)')}\n"
            f"Folder pattern: {plan.get('folder_pattern', '(unknown)')}\n"
            f"Clusters: {len(plan.get('clusters', []))} | "
            f"Moves: {len(plan.get('moves', []))} | "
            f"Warnings: {len(plan.get('warnings', []))}"
        )
        layout.addWidget(summary)

        self.folder_table = QTableWidget()
        self.folder_table.setColumnCount(6)
        self.folder_table.setHorizontalHeaderLabels(["Event Folder", "Media", "Date Audit", "OS Fallback", "Target", "Status"])
        self.folder_table.setRowCount(len(plan.get("clusters", [])))
        self.folder_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.folder_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.folder_table.setAlternatingRowColors(True)

        for row_index, cluster in enumerate(plan.get("clusters", [])):
            target_path = Path(cluster.get("target_dir", ""))
            status = "Merge" if target_path.exists() else "New"

            values = [
                cluster.get("folder_name", ""),
                str(cluster.get("file_count", "")),
                cluster.get("date_audit", ""),
                str(cluster.get("os_fallback_count", 0)),
                str(target_path),
                status,
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index in (1, 3, 5):
                    item.setTextAlignment(Qt.AlignCenter)
                self.folder_table.setItem(row_index, column_index, item)

        folder_header = self.folder_table.horizontalHeader()
        folder_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        folder_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        folder_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        folder_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        folder_header.setSectionResizeMode(4, QHeaderView.Stretch)
        folder_header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        layout.addWidget(QLabel("<b>Event folders</b>"))
        layout.addWidget(self.folder_table)

        layout.addWidget(QLabel("<b>File moves</b>"))
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Kind", "Cluster", "Event", "Date Source", "From", "To", "Status"])
        self.table.setRowCount(len(plan.get("moves", [])))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)

        for row_index, move in enumerate(plan.get("moves", [])):
            source_path = Path(move.get("from", ""))
            target_path = Path(move.get("to", ""))
            status = "OK" if source_path.exists() else "Missing source"

            values = [
                move.get("kind", "media"),
                str(move.get("cluster_id", "")),
                move.get("event_name", ""),
                move.get("date_source", ""),
                str(source_path),
                str(target_path),
                status,
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index in (0, 1, 3, 6):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, column_index, item)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        layout.addWidget(self.table)

        warnings_box = QPlainTextEdit()
        warnings_box.setReadOnly(True)
        warnings_box.setMaximumHeight(120)

        warnings_list = plan.get("warnings", [])
        if warnings_list:
            warnings_box.setPlainText("\n".join(f"- {warning}" for warning in warnings_list))
        else:
            warnings_box.setPlainText("No warnings.")

        layout.addWidget(warnings_box)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class DuplicateReviewDialog(QDialog):
    """Duplicate groups from already-computed file hashes."""

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Duplicate Review")
        self.resize(1050, 650)
        self.groups = groups
        self.cleanup_requested = False

        layout = QVBoxLayout(self)

        duplicate_file_count = sum(len(group["files"]) for group in groups)
        duplicate_bytes = sum(group["file_size"] * len(group["files"]) for group in groups)
        potential_savings = sum(group["file_size"] * (len(group["files"]) - 1) for group in groups)

        summary = QLabel(
            f"Groups: {len(groups)} | "
            f"Files in duplicate groups: {duplicate_file_count} | "
            f"Duplicate bytes: {duplicate_bytes:,} | "
            f"Potential savings after review: {potential_savings:,}"
        )
        layout.addWidget(summary)

        layout.addWidget(QLabel("<b>Duplicate groups</b>"))
        self.group_table = QTableWidget()
        self.group_table.setColumnCount(5)
        self.group_table.setHorizontalHeaderLabels(["Hash", "Files", "Size", "Potential Savings", "First Path"])
        self.group_table.setRowCount(len(groups))
        self.group_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.group_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.group_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.group_table.setAlternatingRowColors(True)

        for row_index, group in enumerate(groups):
            values = [
                group["file_hash"][:16],
                str(len(group["files"])),
                f"{group['file_size']:,}",
                f"{group['file_size'] * (len(group['files']) - 1):,}",
                group["files"][0]["original_path"] if group["files"] else "",
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setData(Qt.ItemDataRole.UserRole, row_index)
                self.group_table.setItem(row_index, column_index, item)

        group_header = self.group_table.horizontalHeader()
        group_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        group_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        group_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        group_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        group_header.setSectionResizeMode(4, QHeaderView.Stretch)

        self.group_table.itemSelectionChanged.connect(self.on_group_selection_changed)
        layout.addWidget(self.group_table)

        layout.addWidget(QLabel("<b>Files in selected group</b>"))
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(6)
        self.file_table.setHorizontalHeaderLabels(["Keep?", "ID", "Status", "Cluster", "Date", "Path"])
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.file_table.setAlternatingRowColors(True)

        file_header = self.file_table.horizontalHeader()
        file_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        file_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        file_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        file_header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        file_header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        file_header.setSectionResizeMode(5, QHeaderView.Stretch)

        layout.addWidget(self.file_table)

        note = QLabel("Primary rows are kept. Review rows can be moved into per-folder _TRASH_DUPLICATES.")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        cleanup_button = buttons.addButton("Move Review Files...", QDialogButtonBox.DestructiveRole)
        cleanup_button.clicked.connect(self.request_cleanup)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        if groups:
            self.group_table.selectRow(0)

    def on_group_selection_changed(self):
        selected_rows = self.group_table.selectionModel().selectedRows()
        if not selected_rows:
            self.file_table.setRowCount(0)
            return

        row = selected_rows[0].row()
        item = self.group_table.item(row, 0)
        group_index = item.data(Qt.ItemDataRole.UserRole) if item else row
        files = self.groups[group_index]["files"]

        self.file_table.setRowCount(len(files))
        for row_index, file_info in enumerate(files):
            keep_label = "primary" if row_index == 0 else "review"
            values = [
                keep_label,
                str(file_info["id"]),
                file_info.get("status") or "",
                str(file_info.get("cluster_id") or ""),
                file_info.get("computed_date") or "",
                file_info.get("original_path") or "",
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index in (0, 1, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self.file_table.setItem(row_index, column_index, item)

    def request_cleanup(self):
        self.cleanup_requested = True
        self.accept()


class IngestionWorker(QThread):
    """Background thread to run the 3-phase engine without freezing the GUI."""

    progress_message = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, db, target_dir, cluster_gap_hours=12):
        super().__init__()
        self.db = db
        self.target_dir = target_dir
        self.cluster_gap_hours = cluster_gap_hours

    def run(self):
        self.progress_message.emit("Scanning media files...")
        crawler = Crawler(self.db)
        scan_summary = crawler.scan_directory(
            self.target_dir,
            progress_callback=self._on_scan_progress,
        )
        self.progress_message.emit(
            "Scan indexed "
            f"{scan_summary['inserted']} new / {scan_summary['scanned']} seen "
            f"({scan_summary['skipped']} known)"
        )

        self.progress_message.emit("Extracting capture dates...")
        extractor = MetadataExtractor(self.db)
        metadata_summary = extractor.process_pending_files(
            progress_callback=self._on_metadata_progress,
        )
        self.progress_message.emit(
            "Date extraction processed "
            f"{metadata_summary['processed']} file(s)"
        )

        self.progress_message.emit("Building time clusters...")
        cluster_engine = ClusterEngine(self.db, max_gap_hours=self.cluster_gap_hours)
        cluster_summary = cluster_engine.build_clusters()
        self.progress_message.emit(
            "Built "
            f"{cluster_summary['clusters']} event(s) from {cluster_summary['files']} file(s)"
        )

        self.progress_message.emit("Scan complete")
        self.finished.emit()

    def _on_scan_progress(self, scanned, inserted, skipped):
        self.progress_message.emit(
            f"Scanning media files... {scanned} seen, {inserted} new, {skipped} known"
        )

    def _on_metadata_progress(self, processed, total, file_name, source_label):
        self.progress_message.emit(
            f"Extracting capture dates... {processed}/{total} ({source_label}: {file_name})"
        )


class ThumbnailWorker(QThread):
    """Background thread to safely load and scale images without freezing the UI."""

    progress = pyqtSignal(int)
    thumb_ready = pyqtSignal(int, str, str, int, QImage)
    finished = pyqtSignal()

    def __init__(self, files, thumbnail_size=200):
        super().__init__()
        self.files = files
        self.thumbnail_size = thumbnail_size
        self.cache_dir = Path(".clustree_cache") / "thumbs"
        self.is_running = True

    def _cache_path_for(self, file_path: str):
        path = Path(file_path)

        try:
            stat = path.stat()
        except OSError:
            return None

        payload = "|".join(
            [
                str(path.resolve()),
                str(stat.st_mtime_ns),
                str(stat.st_size),
                str(self.thumbnail_size),
                THUMBNAIL_CACHE_VERSION,
            ]
        )
        digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()

        return self.cache_dir / f"{digest}.png"

    def _save_thumbnail_cache(self, cache_path, img):
        if not cache_path or img.isNull():
            return

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(cache_path), "PNG")
        except OSError:
            pass

    def _load_or_create_image_thumbnail(self, file_path: str):
        cache_path = self._cache_path_for(file_path)

        if cache_path and cache_path.exists():
            cached = QImage(str(cache_path))
            if not cached.isNull():
                return cached

        img = self._load_image_with_exif_orientation(file_path)
        if img.isNull():
            return QImage()

        img = img.scaled(
            self.thumbnail_size,
            self.thumbnail_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        self._save_thumbnail_cache(cache_path, img)

        return img

    def _load_image_with_exif_orientation(self, file_path: str):
        try:
            with Image.open(file_path) as pil_image:
                pil_image = ImageOps.exif_transpose(pil_image)
                pil_image = pil_image.convert("RGBA")
                width, height = pil_image.size
                image_bytes = pil_image.tobytes("raw", "RGBA")
        except Exception:
            return QImage(file_path)

        qimage = QImage(
            image_bytes,
            width,
            height,
            width * 4,
            QImage.Format_RGBA8888,
        )

        return qimage.copy()

    def _load_or_create_video_thumbnail(self, file_path: str):
        cache_path = self._cache_path_for(file_path)

        if cache_path and cache_path.exists():
            cached = QImage(str(cache_path))
            if not cached.isNull():
                return cached

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path or not cache_path:
            return QImage()

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            command = [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                "00:00:01",
                "-i",
                file_path,
                "-frames:v",
                "1",
                "-vf",
                f"scale={self.thumbnail_size}:{self.thumbnail_size}:force_original_aspect_ratio=decrease",
                str(cache_path),
            ]
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.CalledProcessError):
            return QImage()

        img = QImage(str(cache_path))
        if img.isNull():
            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                pass

        return img

    def run(self):
        for i, f in enumerate(self.files):
            if not self.is_running:
                break

            file_id = f["id"]
            file_path = f["original_path"]
            file_size = f["file_size"] or 0
            file_name = Path(file_path).name

            lower_path = file_path.lower()

            if lower_path.endswith(IMAGE_THUMBNAIL_EXTENSIONS):
                img = self._load_or_create_image_thumbnail(file_path)
                self.thumb_ready.emit(file_id, file_path, file_name, file_size, img)
            elif lower_path.endswith(VIDEO_THUMBNAIL_EXTENSIONS):
                img = self._load_or_create_video_thumbnail(file_path)
                self.thumb_ready.emit(file_id, file_path, file_name, file_size, img)
            else:
                self.thumb_ready.emit(file_id, file_path, file_name, file_size, QImage())

            self.progress.emit(i + 1)

        self.finished.emit()

    def stop(self):
        self.is_running = False


class ThumbnailGridWidget(QListWidget):
    """Thumbnail grid with a compact drag image for multi-file reassignment."""

    def startDrag(self, supported_actions):
        items = self.selectedItems()
        if not items:
            return

        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.setPixmap(self._build_drag_pixmap(len(items)))
        drag.setHotSpot(drag.pixmap().rect().center())
        drag.exec_(supported_actions, Qt.MoveAction)

    def _build_drag_pixmap(self, item_count):
        width = 180
        height = 72
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setBrush(QColor(38, 58, 73, 235))
        painter.setPen(QColor(92, 172, 238))
        painter.drawRoundedRect(1, 1, width - 2, height - 2, 8, 8)

        painter.setPen(QColor(255, 255, 255))
        label = "1 file" if item_count == 1 else f"{item_count} files"
        painter.drawText(
            pixmap.rect(),
            Qt.AlignmentFlag.AlignCenter,
            f"Move {label}",
        )

        painter.end()
        return pixmap


class ClusterListWidget(QListWidget):
    """Custom ListWidget for the sidebar to handle drag-and-drop reassignment."""

    file_reassigned = pyqtSignal(str, int)  # Emits: file_path, new_cluster_id

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self._drop_target_item = None

    def _set_drop_target_item(self, item):
        if item == self._drop_target_item:
            return

        self._clear_drop_target_item()

        if item:
            item.setBackground(QBrush(QColor("#246b8f")))
            item.setForeground(QBrush(QColor("#ffffff")))
            self._drop_target_item = item

    def _clear_drop_target_item(self):
        if not self._drop_target_item:
            return

        try:
            self._drop_target_item.setBackground(QBrush())
            self._drop_target_item.setForeground(QBrush())
        except RuntimeError:
            pass
        finally:
            self._drop_target_item = None

    def dragEnterEvent(self, event):
        if event.source() and event.source() != self:
            event.accept()
        else:
            self._clear_drop_target_item()
            event.ignore()

    def dragMoveEvent(self, event):
        if not event.source() or event.source() == self:
            self._clear_drop_target_item()
            event.ignore()
            return

        target_item = self.itemAt(event.pos())
        self._set_drop_target_item(target_item)

        if target_item:
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._clear_drop_target_item()
        event.accept()

    def dropEvent(self, event):
        target_item = self.itemAt(event.pos())

        if not target_item or event.source() == self:
            self._clear_drop_target_item()
            event.ignore()
            return

        new_cluster_id = target_item.data(Qt.ItemDataRole.UserRole)
        if new_cluster_id == DELETE_CLUSTER_ID:
            self._clear_drop_target_item()
            event.ignore()
            return

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

        self._clear_drop_target_item()
        event.accept()


class ClustreeWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()

        self.db = db
        self.settings = load_settings()
        self.current_move_plan = None
        self.manual_cluster_colors = {}
        self.manual_cluster_color_index = 0

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
        self.cluster_list.itemSelectionChanged.connect(self.refresh_cluster_list_styles)

        left_panel.addWidget(self.cluster_list)
        main_layout.addLayout(left_panel)

        # --- Right Panel: Triage & Rename ---
        right_panel = QVBoxLayout()

        self.grid_header = QLabel("<b>Select a cluster to view media...</b>")

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()

        self.thumbnail_grid = ThumbnailGridWidget()
        self.thumbnail_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnail_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnail_grid.setSpacing(10)
        self.thumbnail_grid.setWordWrap(True)
        self.thumbnail_grid.setTextElideMode(Qt.TextElideMode.ElideMiddle)
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

        self.undo_run_btn = QPushButton("Undo Last Run")
        self.undo_run_btn.clicked.connect(self.rollback_latest_run)

        self.duplicate_review_btn = QPushButton("Duplicate Review")
        self.duplicate_review_btn.clicked.connect(self.open_duplicate_review)

        self.undo_duplicate_btn = QPushButton("Undo Dupes")
        self.undo_duplicate_btn.clicked.connect(self.rollback_latest_duplicate_cleanup)

        plan_layout.addWidget(self.preview_btn)
        plan_layout.addWidget(self.run_plan_btn)
        plan_layout.addWidget(self.undo_run_btn)
        plan_layout.addWidget(self.duplicate_review_btn)
        plan_layout.addWidget(self.undo_duplicate_btn)

        right_panel.addWidget(self.grid_header)
        right_panel.addWidget(self.progress_bar)
        right_panel.addWidget(self.thumbnail_grid)
        right_panel.addLayout(name_layout)
        right_panel.addLayout(plan_layout)

        main_layout.addLayout(right_panel)

        self.statusBar()
        self._apply_thumbnail_grid_settings()
        self.update_status()
        self.load_clusters()

    def update_status(self, message="Ready"):
        pattern_label = rename_pattern_label_from_value(self.settings.rename_pattern).split(" - ")[0]
        output_label = self.settings.output_root or "source-adjacent"

        self.statusBar().showMessage(
            f"{message} | Clustree {APP_VERSION} | "
            f"Gap: {self.settings.cluster_gap_hours}h | "
            f"Thumb: {self.settings.thumbnail_size}px | "
            f"Rename: {pattern_label} | "
            f"DELETE: {'on' if self.settings.show_delete_cluster else 'off'} | "
            f"Staging: {output_label}"
        )

    def invalidate_plan(self):
        self.current_move_plan = None
        self.run_plan_btn.setEnabled(False)

    def _apply_thumbnail_grid_settings(self):
        thumb_size = self.settings.thumbnail_size
        self.thumbnail_grid.setIconSize(QSize(thumb_size, thumb_size))

        if self.settings.show_thumbnail_file_info:
            self.thumbnail_grid.setGridSize(QSize(thumb_size + 74, thumb_size + 58))
        else:
            self.thumbnail_grid.setGridSize(QSize(thumb_size + 26, thumb_size + 28))

    def build_duplicate_groups(self):
        cursor = self.db.conn.cursor()
        cursor.execute(
            """
            SELECT file_hash, file_size, COUNT(*) AS file_count
            FROM files
            WHERE file_hash IS NOT NULL
              AND file_hash != ''
              AND status NOT IN ('archived', 'duplicate_trash')
            GROUP BY file_hash, file_size
            HAVING COUNT(*) > 1
            ORDER BY file_count DESC, file_size DESC
            """
        )

        groups = []
        for group in cursor.fetchall():
            cursor.execute(
                """
                SELECT id, original_path, cluster_id, status, computed_date, is_duplicate
                FROM files
                WHERE file_hash = ?
                  AND file_size = ?
                  AND status NOT IN ('archived', 'duplicate_trash')
                ORDER BY is_duplicate ASC, computed_date ASC, id ASC
                """,
                (group["file_hash"], group["file_size"]),
            )

            groups.append(
                {
                    "file_hash": group["file_hash"],
                    "file_size": group["file_size"] or 0,
                    "files": [dict(row) for row in cursor.fetchall()],
                }
            )

        return groups

    def open_duplicate_review(self):
        groups = self.build_duplicate_groups()

        if not groups:
            QMessageBox.information(
                self,
                "Duplicate Review",
                "No duplicate hash groups found yet. Run a scan first, or scan folders with exact same-size duplicates.",
            )
            return

        dialog = DuplicateReviewDialog(groups, self)
        if dialog.exec_() == QDialog.Accepted and dialog.cleanup_requested:
            self.move_review_duplicates(groups)

    def build_duplicate_trash_plan(self, groups):
        plan = {
            "app_version": APP_VERSION,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy": "keep first ordered file in each exact hash group; move the remaining review files",
            "trash_folder": "_TRASH_DUPLICATES",
            "groups": [],
            "moves": [],
            "warnings": [],
        }
        reserved_paths = set()

        for group_index, group in enumerate(groups, start=1):
            files = group.get("files", [])
            if len(files) < 2:
                continue

            primary = files[0]
            review_files = files[1:]
            plan["groups"].append(
                {
                    "group": group_index,
                    "file_hash": group.get("file_hash"),
                    "file_size": group.get("file_size", 0),
                    "primary": primary.get("original_path"),
                    "review_count": len(review_files),
                }
            )

            for file_info in review_files:
                old_path = Path(file_info.get("original_path") or "")
                if old_path.parent.name == "_TRASH_DUPLICATES":
                    plan["warnings"].append(f"Already in duplicate trash: {old_path}")
                    continue

                requested_path = old_path.parent / "_TRASH_DUPLICATES" / old_path.name
                new_path, had_collision = self._unique_planned_path_with_collision(
                    requested_path,
                    reserved_paths,
                )

                if had_collision:
                    plan["warnings"].append(f"Duplicate trash collision adjusted: {requested_path} -> {new_path}")

                plan["moves"].append(
                    {
                        "file_id": file_info.get("id"),
                        "cluster_id": file_info.get("cluster_id"),
                        "file_hash": group.get("file_hash"),
                        "file_size": group.get("file_size", 0),
                        "primary_path": primary.get("original_path"),
                        "from": str(old_path),
                        "to": str(new_path),
                    }
                )

        return plan

    def _write_duplicate_cleanup_result(self, result):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_dir = Path(".clustree_cache") / "duplicate_runs"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"clustree_duplicate_cleanup_{timestamp}.json"

        result["result_path"] = str(result_path)
        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return result_path

    def _latest_duplicate_cleanup_result_path(self):
        result_dir = Path(".clustree_cache") / "duplicate_runs"
        candidates = sorted(result_dir.glob("clustree_duplicate_cleanup_*.json"))
        return candidates[-1] if candidates else None

    def _write_duplicate_rollback_result(self, result):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_dir = Path(".clustree_cache") / "duplicate_rollbacks"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"clustree_duplicate_rollback_{timestamp}.json"

        result["result_path"] = str(result_path)
        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return result_path

    def rollback_latest_duplicate_cleanup(self):
        result_path = self._latest_duplicate_cleanup_result_path()

        if not result_path:
            QMessageBox.information(self, "No Duplicate Rollback", "No duplicate cleanup archive was found.")
            return

        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(self, "Duplicate Rollback Failed", f"Could not read duplicate cleanup archive:\n{e}")
            return

        rollback_moves = result.get("rollback_moves", [])
        if not rollback_moves:
            QMessageBox.information(
                self,
                "No Duplicate Rollback",
                "The latest duplicate cleanup archive has no rollback moves.",
            )
            return

        blocked = []
        for move in rollback_moves:
            current_path = Path(move.get("from", ""))
            original_path = Path(move.get("to", ""))

            if not current_path.exists():
                blocked.append(f"Missing duplicate-trash file: {current_path}")
            elif original_path.exists():
                blocked.append(f"Original path already exists: {original_path}")

        if blocked:
            QMessageBox.warning(
                self,
                "Duplicate Rollback Blocked",
                "Rollback would not be safe:\n\n" + "\n".join(blocked[:12]),
            )
            return

        reply = QMessageBox.question(
            self,
            "Undo Duplicate Cleanup",
            f"Move {len(rollback_moves)} duplicate file(s) back using:\n{result_path}\n\n"
            "This changes files on disk.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        cursor = self.db.conn.cursor()
        restored = []
        failed = []
        touched_clusters = set()

        for move in rollback_moves:
            current_path = Path(move["from"])
            original_path = Path(move["to"])
            file_id = move.get("file_id")
            cluster_id = move.get("cluster_id")

            if cluster_id:
                touched_clusters.add(cluster_id)

            try:
                original_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current_path), str(original_path))

                if file_id is not None:
                    cursor.execute(
                        "UPDATE files SET original_path = ?, status = 'clustered' WHERE id = ?",
                        (str(original_path), file_id),
                    )

                restored.append(move)

            except Exception as e:
                failed_move = dict(move)
                failed_move["error"] = str(e)
                failed.append(failed_move)

        for cluster_id in touched_clusters:
            self._recalculate_cluster_dates_and_count(cursor, cluster_id)

        self.db.conn.commit()

        rollback_result = {
            "app_version": APP_VERSION,
            "rolled_back_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_result_path": str(result_path),
            "restored": restored,
            "failed": failed,
        }
        rollback_path = self._write_duplicate_rollback_result(rollback_result)

        self.invalidate_plan()
        self.load_clusters()
        current_item = self.cluster_list.currentItem()
        if current_item:
            self.start_loading_cluster(current_item)

        self.update_status(f"Duplicate rollback complete: {len(restored)} restored, {len(failed)} failed")

        QMessageBox.information(
            self,
            "Duplicate Rollback Complete",
            f"Restored: {len(restored)}\nFailed: {len(failed)}\n\nResult saved:\n{rollback_path}",
        )

    def move_review_duplicates(self, groups):
        plan = self.build_duplicate_trash_plan(groups)
        move_count = len(plan["moves"])

        if not move_count:
            QMessageBox.information(self, "Duplicate Cleanup", "No review duplicate files are available to move.")
            return

        warning_text = ""
        if plan["warnings"]:
            warning_text = "\n\nWarnings:\n" + "\n".join(plan["warnings"][:8])

        reply = QMessageBox.question(
            self,
            "Move Review Duplicates",
            f"Move {move_count} reviewed duplicate file(s) into _TRASH_DUPLICATES?\n\n"
            "Primary files remain in place. This changes files on disk."
            f"{warning_text}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        cursor = self.db.conn.cursor()
        touched_clusters = set()
        result = {
            "app_version": APP_VERSION,
            "executed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy": plan["strategy"],
            "trash_folder": plan["trash_folder"],
            "groups": plan["groups"],
            "warnings": plan["warnings"],
            "moved": [],
            "missing": [],
            "failed": [],
            "rollback_moves": [],
            "result_path": None,
        }

        for move in plan["moves"]:
            file_id = move.get("file_id")
            old_path = Path(move["from"])
            new_path = Path(move["to"])
            cluster_id = move.get("cluster_id")

            if cluster_id:
                touched_clusters.add(cluster_id)

            try:
                if not old_path.exists():
                    if file_id is not None:
                        cursor.execute(
                            "UPDATE files SET status = 'missing' WHERE id = ?",
                            (file_id,),
                        )
                    result["missing"].append(move)
                    continue

                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(new_path))

                if file_id is not None:
                    cursor.execute(
                        "UPDATE files SET original_path = ?, status = 'duplicate_trash' WHERE id = ?",
                        (str(new_path), file_id),
                    )

                result["moved"].append(move)
                result["rollback_moves"].append(
                    {
                        "file_id": file_id,
                        "cluster_id": cluster_id,
                        "from": str(new_path),
                        "to": str(old_path),
                    }
                )

            except Exception as e:
                failed_move = dict(move)
                failed_move["error"] = str(e)
                result["failed"].append(failed_move)

        for cluster_id in touched_clusters:
            self._recalculate_cluster_dates_and_count(cursor, cluster_id)

        self.db.conn.commit()
        result_path = self._write_duplicate_cleanup_result(result)

        moved = len(result["moved"])
        missing = len(result["missing"])
        failed = len(result["failed"])

        self.invalidate_plan()
        self.load_clusters()
        current_item = self.cluster_list.currentItem()
        if current_item:
            self.start_loading_cluster(current_item)

        self.update_status(f"Duplicate cleanup complete: {moved} moved, {missing} missing, {failed} failed")

        QMessageBox.information(
            self,
            "Duplicate Cleanup Complete",
            f"Moved: {moved}\nMissing: {missing}\nFailed: {failed}\n\nResult saved:\n{result_path}",
        )

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)

        if dialog.exec_() != QDialog.Accepted:
            return

        self.settings = dialog.get_settings()
        save_settings(self.settings)

        self._apply_thumbnail_grid_settings()
        self.invalidate_plan()
        self.load_clusters()
        if self.current_cluster_id == DELETE_CLUSTER_ID and not self.settings.show_delete_cluster:
            self.current_cluster_id = None
            self.thumbnail_grid.clear()
            self.grid_header.setText("<b>Select a cluster to view media...</b>")
        elif self.current_cluster_id and self.current_cluster_id != DELETE_CLUSTER_ID:
            self.load_cluster_by_id(self.current_cluster_id)
        self.update_status("Settings saved")

    def cleanup_local_state(self):
        if self.thumb_worker and self.thumb_worker.isRunning():
            QMessageBox.warning(self, "Cleanup Blocked", "Wait for thumbnail loading to finish first.")
            return

        if self.ingestion_worker and self.ingestion_worker.isRunning():
            QMessageBox.warning(self, "Cleanup Blocked", "Wait for the current scan to finish first.")
            return

        db_path = Path(self.db.db_path)
        cache_path = Path(".clustree_cache")

        reply = QMessageBox.warning(
            self,
            "CLEANUP",
            "Wipe Clustree caches and the local database?\n\n"
            f"Cache: {cache_path}\n"
            f"Database: {db_path}\n\n"
            "Source photos are not touched, but all scan/cluster state will be lost.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        removed = []
        failed = []

        try:
            self.db.close()
        except Exception:
            pass

        if cache_path.exists():
            try:
                shutil.rmtree(cache_path)
                removed.append(str(cache_path))
            except Exception as e:
                failed.append(f"{cache_path}: {e}")

        for candidate in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            if not candidate.exists():
                continue

            try:
                candidate.unlink()
                removed.append(str(candidate))
            except Exception as e:
                failed.append(f"{candidate}: {e}")

        self.db = self.db.__class__(db_path)
        self.current_move_plan = None
        self.current_cluster_id = None
        self.manual_cluster_colors = {}
        self.manual_cluster_color_index = 0
        self.run_plan_btn.setEnabled(False)
        self.thumbnail_grid.clear()
        self.rename_input.clear()
        self.rename_input.setEnabled(False)
        self.save_name_btn.setEnabled(False)
        self.grid_header.setText("<b>Cleanup complete. Scan a folder to start again.</b>")
        self.load_clusters()

        if failed:
            QMessageBox.warning(
                self,
                "Cleanup Partially Failed",
                "Some files could not be removed:\n\n" + "\n".join(failed[:8]),
            )
            self.update_status(f"Cleanup partial: {len(removed)} removed, {len(failed)} failed")
            return

        self.update_status(f"Cleanup complete: {len(removed)} removed")
        QMessageBox.information(
            self,
            "Cleanup Complete",
            "Removed:\n" + ("\n".join(removed) if removed else "Nothing to remove."),
        )

    def handle_file_reassigned(self, file_path, new_cluster_id):
        """Updates the DB when a thumbnail is dropped onto a new cluster."""
        if new_cluster_id == DELETE_CLUSTER_ID:
            return

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
        self.ingestion_worker.progress_message.connect(self.on_ingestion_progress)
        self.ingestion_worker.finished.connect(self.on_scan_complete)
        self.ingestion_worker.start()

    def on_ingestion_progress(self, message):
        self.grid_header.setText(f"<b>{message}</b>")
        self.update_status(message)

    def on_scan_complete(self):
        self.scan_btn.setEnabled(True)
        self.settings_btn.setEnabled(True)
        self.preview_btn.setEnabled(True)

        self.scan_btn.setText("Scan Folder...")
        self.grid_header.setText("<b>Scan complete! Select a cluster on the left.</b>")

        self.load_clusters()
        self.update_status("Scan complete")

    def load_clusters(self):
        self.cluster_list._clear_drop_target_item()
        self.cluster_list.clear()

        row_offset = 0
        if self.settings.show_delete_cluster:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, DELETE_CLUSTER_ID)
            item.setData(Qt.ItemDataRole.UserRole + 1, 0)
            item.setSizeHint(QSize(320, 50))
            self.cluster_list.addItem(item)
            self.cluster_list.setItemWidget(item, self._build_delete_cluster_row_widget())
            row_offset = 1

        cursor = self.db.conn.cursor()
        cursor.execute(
            """
            SELECT id, start_date, file_count, assigned_name, manual_kind
            FROM clusters
            WHERE status != 'archived'
              AND file_count > 0
            ORDER BY
              CASE WHEN manual_kind = 'temp' THEN 0 ELSE 1 END,
              CASE WHEN manual_kind = 'temp' THEN id END ASC,
              start_date ASC,
              id ASC
            """
        )
        clusters = cursor.fetchall()

        self._sync_manual_cluster_colors(clusters)

        for row_index, cluster in enumerate(clusters, start=row_offset):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, cluster["id"])
            item.setData(Qt.ItemDataRole.UserRole + 1, row_index)
            item.setSizeHint(QSize(320, 58))
            self.cluster_list.addItem(item)
            self.cluster_list.setItemWidget(item, self._build_cluster_row_widget(cluster, row_index))

        if self.current_cluster_id:
            self._select_cluster_list_item(self.current_cluster_id)
        else:
            self.refresh_cluster_list_styles()

    def _cluster_display_name(self, cluster):
        assigned_name = (cluster["assigned_name"] or "").strip()
        return assigned_name if assigned_name else f"Event {cluster['id']}"

    def _build_delete_cluster_row_widget(self):
        widget = QWidget()
        widget.setObjectName("clusterRow")

        outer = QVBoxLayout(widget)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(2)

        name_label = QLabel("Name: DELETE")
        name_label.setObjectName("clusterName")

        count_label = QLabel("Permanent delete target | empty")
        count_label.setObjectName("clusterCount")

        outer.addWidget(name_label)
        outer.addWidget(count_label)

        self._apply_cluster_row_style(widget, DELETE_CLUSTER_ID, 0, selected=False)
        return widget

    def _is_manual_cluster(self, cluster):
        try:
            return cluster["manual_kind"] == "temp"
        except (KeyError, IndexError):
            return cluster["id"] in self.manual_cluster_colors

    def _sync_manual_cluster_colors(self, clusters):
        active_manual_ids = []

        for cluster in clusters:
            if not self._is_manual_cluster(cluster):
                continue

            cluster_id = cluster["id"]
            active_manual_ids.append(cluster_id)
            if cluster_id not in self.manual_cluster_colors:
                self.manual_cluster_colors[cluster_id] = self._next_manual_cluster_color()

        for cluster_id in list(self.manual_cluster_colors):
            if cluster_id not in active_manual_ids:
                self.manual_cluster_colors.pop(cluster_id, None)

    def _cluster_row_background(self, cluster_id, row_index):
        if cluster_id == DELETE_CLUSTER_ID:
            return DELETE_CLUSTER_COLOR

        if cluster_id in self.manual_cluster_colors:
            return self.manual_cluster_colors[cluster_id]

        return "#ffffff" if row_index % 2 == 0 else "#f3f3f3"

    def _build_cluster_row_widget(self, cluster, row_index):
        widget = QWidget()
        widget.setObjectName("clusterRow")

        outer = QVBoxLayout(widget)
        outer.setContentsMargins(8, 5, 8, 5)
        outer.setSpacing(2)

        top_line = QHBoxLayout()
        top_line.setContentsMargins(0, 0, 0, 0)

        name_label = QLabel(f"Name: {self._cluster_display_name(cluster)}")
        name_label.setObjectName("clusterName")

        date_text = "" if self._is_manual_cluster(cluster) else (
            cluster["start_date"].split(" ")[0] if cluster["start_date"] else "unknown-date"
        )
        date_label = QLabel(date_text)
        date_label.setObjectName("clusterDate")
        date_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        top_line.addWidget(name_label, 1)
        top_line.addWidget(date_label, 0)

        cluster_kind = "Manual temp" if self._is_manual_cluster(cluster) else f"Event {cluster['id']}"
        count_label = QLabel(f"{cluster_kind} | {cluster['file_count']} file(s)")
        count_label.setObjectName("clusterCount")

        outer.addLayout(top_line)
        outer.addWidget(count_label)

        self._apply_cluster_row_style(widget, cluster["id"], row_index, selected=False)
        return widget

    def _apply_cluster_row_style(self, widget, cluster_id, row_index, selected=False):
        background = self._cluster_row_background(cluster_id, row_index)
        border_left = "#3178c6" if selected else "transparent"
        border_left_width = "4px" if selected else "4px"

        widget.setStyleSheet(
            f"""
            QWidget#clusterRow {{
                background: {background};
                border-bottom: 1px solid #d7d7d7;
                border-left: {border_left_width} solid {border_left};
            }}
            QLabel#clusterName {{
                color: #111111;
                font-weight: 600;
            }}
            QLabel#clusterDate {{
                color: #4b5563;
                font-size: 11px;
            }}
            QLabel#clusterCount {{
                color: #4b5563;
                font-size: 11px;
            }}
            """
        )

    def refresh_cluster_list_styles(self):
        for row in range(self.cluster_list.count()):
            item = self.cluster_list.item(row)
            widget = self.cluster_list.itemWidget(item)
            if not widget:
                continue

            cluster_id = item.data(Qt.ItemDataRole.UserRole)
            row_index = item.data(Qt.ItemDataRole.UserRole + 1)
            self._apply_cluster_row_style(
                widget,
                cluster_id,
                row_index if row_index is not None else row,
                selected=item.isSelected() or cluster_id == self.current_cluster_id,
            )

    def _select_cluster_list_item(self, cluster_id):
        for row in range(self.cluster_list.count()):
            item = self.cluster_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == cluster_id:
                self.cluster_list.setCurrentItem(item)
                item.setSelected(True)
                self.refresh_cluster_list_styles()
                return

        self.refresh_cluster_list_styles()

    def start_loading_cluster(self, item):
        cluster_id = item.data(Qt.ItemDataRole.UserRole)
        if cluster_id == DELETE_CLUSTER_ID:
            self.load_delete_cluster()
            return

        self.load_cluster_by_id(cluster_id)

    def load_delete_cluster(self):
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.stop()
            self.thumb_worker.wait()

        self.thumbnail_grid.clear()
        self.current_cluster_id = DELETE_CLUSTER_ID
        self._select_cluster_list_item(DELETE_CLUSTER_ID)
        self.grid_header.setText("<b>DELETE cluster (empty)</b>")
        self.rename_input.clear()
        self.rename_input.setEnabled(False)
        self.save_name_btn.setEnabled(False)
        self.progress_bar.hide()
        self.update_status("Viewing DELETE cluster")

    def load_cluster_by_id(self, cluster_id):
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.stop()
            self.thumb_worker.wait()

        self.thumbnail_grid.clear()
        self.current_cluster_id = cluster_id
        self._select_cluster_list_item(cluster_id)

        cursor = self.db.conn.cursor()

        cursor.execute(
            "SELECT assigned_name FROM clusters WHERE id = ?",
            (self.current_cluster_id,),
        )
        cluster = cursor.fetchone()
        assigned_name = (cluster["assigned_name"] or "") if cluster else ""

        cursor.execute(
            """
            SELECT id, original_path, file_size
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
        self.rename_input.setPlaceholderText(
            f"Event {cluster_id} (display only; save a real name to include in plan)..."
        )
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

    def _format_file_size(self, size_bytes):
        try:
            size_bytes = int(size_bytes or 0)
        except (TypeError, ValueError):
            size_bytes = 0

        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.0f} KB"

        return f"{size_bytes} B"

    def _thumbnail_label(self, file_name, file_size):
        if not self.settings.show_thumbnail_file_info:
            return ""

        return f"{file_name}\n{self._format_file_size(file_size)}"

    def add_thumbnail(self, file_id, file_path, file_name, file_size, qimage):
        thumb_item = QListWidgetItem()

        if not qimage.isNull():
            pixmap = QPixmap.fromImage(qimage)
            thumb_item.setIcon(QIcon(pixmap))
        else:
            thumb_item.setText("Video File")

        label = self._thumbnail_label(file_name, file_size)
        if label:
            thumb_item.setText(label)

        thumb_item.setToolTip(f"{file_name}\n{self._format_file_size(file_size)}\n{file_path}")
        thumb_item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "id": file_id,
                "path": file_path,
                "name": file_name,
                "size": file_size,
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
            if cluster_id is not None and cluster_id != DELETE_CLUSTER_ID:
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

        if item.data(Qt.ItemDataRole.UserRole) == DELETE_CLUSTER_ID:
            return

        if not item.isSelected():
            self.cluster_list.clearSelection()
            item.setSelected(True)
            self.cluster_list.setCurrentItem(item)

        selected_ids = self._selected_cluster_ids()
        if not selected_ids:
            return

        menu = QMenu(self)

        rename_action = None
        merge_selected_action = None
        merge_previous_action = None
        merge_next_action = None

        if len(selected_ids) >= 2:
            merge_selected_action = menu.addAction(f"Merge selected clusters ({len(selected_ids)})")
        else:
            rename_action = menu.addAction("Rename cluster...")
            menu.addSeparator()
            merge_previous_action = menu.addAction("Merge with previous cluster")
            merge_next_action = menu.addAction("Merge with next cluster")

        action = menu.exec_(self.cluster_list.mapToGlobal(pos))

        if rename_action and action == rename_action:
            self.rename_cluster_from_menu(selected_ids[0])
            return

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

    def rename_cluster_from_menu(self, cluster_id):
        cursor = self.db.conn.cursor()
        cursor.execute(
            "SELECT assigned_name FROM clusters WHERE id = ?",
            (cluster_id,),
        )
        cluster = cursor.fetchone()
        current_name = (cluster["assigned_name"] or "").strip() if cluster else ""

        new_name, accepted = QInputDialog.getText(
            self,
            "Rename Cluster",
            f"Name for Event {cluster_id}:",
            text=current_name,
        )

        if not accepted:
            return

        new_name = new_name.strip()
        cursor.execute(
            "UPDATE clusters SET assigned_name = ? WHERE id = ?",
            (new_name or None, cluster_id),
        )
        self.db.conn.commit()

        self.invalidate_plan()
        self.load_clusters()
        self.load_cluster_by_id(cluster_id)
        self.update_status(f"Renamed Event {cluster_id}")

    def _active_cluster_ids_in_order(self):
        """Returns active cluster IDs in sidebar order."""
        cursor = self.db.conn.cursor()
        cursor.execute(
            """
            SELECT id
            FROM clusters
            WHERE status != 'archived'
              AND file_count > 0
            ORDER BY
              CASE WHEN manual_kind = 'temp' THEN 0 ELSE 1 END,
              CASE WHEN manual_kind = 'temp' THEN id END ASC,
              start_date ASC,
              id ASC
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

        if not item.isSelected():
            self.thumbnail_grid.clearSelection()
            item.setSelected(True)
            self.thumbnail_grid.setCurrentItem(item)

        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return

        file_id = payload.get("id")
        file_name = payload.get("name", "this photo")
        selected_file_ids = self._selected_thumbnail_file_ids()

        if not file_id:
            return

        menu = QMenu(self)

        delete_action = None
        if self.settings.show_delete_cluster:
            delete_action = menu.addAction(f"DELETE selected permanently ({len(selected_file_ids)})")
            font = delete_action.font()
            font.setBold(True)
            delete_action.setFont(font)
            menu.addSeparator()

        new_temp_cluster_action = menu.addAction(f"Move selected to new temp cluster ({len(selected_file_ids)})")
        existing_cluster_actions = {}
        candidate_clusters = self._candidate_manual_target_clusters()
        if candidate_clusters:
            existing_menu = menu.addMenu("Move selected to existing cluster")
            for cluster in candidate_clusters:
                action = existing_menu.addAction(self._cluster_menu_label(cluster))
                if self._is_manual_cluster(cluster):
                    action.setIcon(self._cluster_color_icon(cluster))
                    font = action.font()
                    font.setBold(True)
                    action.setFont(font)
                existing_cluster_actions[action] = cluster["id"]

        menu.addSeparator()
        split_before_action = menu.addAction(f"Split before {file_name}")
        split_after_action = menu.addAction(f"Split after {file_name}")

        action = menu.exec_(self.thumbnail_grid.mapToGlobal(pos))

        if delete_action and action == delete_action:
            self.permanently_delete_selected_files(selected_file_ids)
        elif action == new_temp_cluster_action:
            self.move_selected_thumbnails_to_temp_cluster(selected_file_ids)
        elif action in existing_cluster_actions:
            self.move_selected_thumbnails_to_existing_cluster(
                selected_file_ids,
                existing_cluster_actions[action],
            )
        elif action == split_before_action:
            self.split_current_cluster_at_file(file_id=file_id, clicked_file_goes_to_new=True)
        elif action == split_after_action:
            self.split_current_cluster_at_file(file_id=file_id, clicked_file_goes_to_new=False)

    def _selected_thumbnail_file_ids(self):
        file_ids = []

        for item in self.thumbnail_grid.selectedItems():
            payload = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(payload, dict):
                continue

            file_id = payload.get("id")
            if file_id is not None and file_id not in file_ids:
                file_ids.append(file_id)

        return file_ids

    def _candidate_manual_target_clusters(self):
        cursor = self.db.conn.cursor()
        cursor.execute(
            """
            SELECT id, start_date, file_count, assigned_name, manual_kind
            FROM clusters
            WHERE status != 'archived'
              AND file_count > 0
              AND id != ?
            ORDER BY
              CASE WHEN manual_kind = 'temp' THEN 0 ELSE 1 END,
              CASE WHEN manual_kind = 'temp' THEN id END ASC,
              CASE WHEN assigned_name IS NULL OR TRIM(assigned_name) = '' THEN 0 ELSE 1 END,
              start_date ASC,
              id ASC
            """,
            (self.current_cluster_id,),
        )
        return cursor.fetchall()

    def _cluster_menu_label(self, cluster):
        name_label = self._cluster_display_name(cluster)
        if self._is_manual_cluster(cluster):
            return f"Manual temp {cluster['id']} ({cluster['file_count']} files) - {name_label}"

        date_label = cluster["start_date"].split(" ")[0] if cluster["start_date"] else "unknown-date"
        return f"Event {cluster['id']} ({date_label}, {cluster['file_count']} files) - {name_label}"

    def _cluster_color_icon(self, cluster):
        cluster_id = cluster["id"]
        color = self.manual_cluster_colors.get(cluster_id)
        if not color:
            return QIcon()

        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(QColor("#7aa874"))
        painter.drawRoundedRect(1, 1, 12, 12, 3, 3)
        painter.end()
        return QIcon(pixmap)

    def _selected_files_in_current_cluster(self, cursor, file_ids):
        if not self.current_cluster_id or not file_ids:
            return []

        placeholders = ",".join("?" for _ in file_ids)
        cursor.execute(
            f"""
            SELECT id, computed_date
            FROM files
            WHERE cluster_id = ?
              AND id IN ({placeholders})
              AND status != 'archived'
            ORDER BY computed_date ASC, id ASC
            """,
            [self.current_cluster_id] + file_ids,
        )
        return cursor.fetchall()

    def _selected_file_paths_in_current_cluster(self, cursor, file_ids):
        if not self.current_cluster_id or not file_ids or self.current_cluster_id == DELETE_CLUSTER_ID:
            return []

        placeholders = ",".join("?" for _ in file_ids)
        cursor.execute(
            f"""
            SELECT id, original_path
            FROM files
            WHERE cluster_id = ?
              AND id IN ({placeholders})
              AND status != 'archived'
            ORDER BY computed_date ASC, id ASC
            """,
            [self.current_cluster_id] + file_ids,
        )
        return cursor.fetchall()

    def _delete_files_from_source_and_database(self, cursor, file_rows):
        result = {
            "deleted": [],
            "missing": [],
            "failed": [],
        }

        for row in file_rows:
            file_id = row["id"]
            original_path = Path(row["original_path"])

            try:
                if original_path.exists():
                    if not original_path.is_file():
                        result["failed"].append(
                            {"file_id": file_id, "path": str(original_path), "error": "Path is not a file"}
                        )
                        continue

                    original_path.unlink()
                    result["deleted"].append({"file_id": file_id, "path": str(original_path)})
                else:
                    result["missing"].append({"file_id": file_id, "path": str(original_path)})

                cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))

            except Exception as e:
                result["failed"].append(
                    {"file_id": file_id, "path": str(original_path), "error": str(e)}
                )

        return result

    def permanently_delete_selected_files(self, file_ids):
        if not self.current_cluster_id or not file_ids or self.current_cluster_id == DELETE_CLUSTER_ID:
            return

        cursor = self.db.conn.cursor()
        selected_files = self._selected_file_paths_in_current_cluster(cursor, file_ids)

        if not selected_files:
            QMessageBox.warning(
                self,
                "DELETE Failed",
                "No selected files are still part of the current cluster.",
            )
            return

        preview_paths = "\n".join(str(Path(row["original_path"]).name) for row in selected_files[:8])
        extra = len(selected_files) - 8
        if extra > 0:
            preview_paths += f"\n...and {extra} more"

        reply = QMessageBox.warning(
            self,
            "Really DELETE?",
            f"Permanently delete {len(selected_files)} source file(s) and remove them from Clustree?\n\n"
            f"{preview_paths}\n\nThis cannot be undone by Clustree.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        source_cluster_id = self.current_cluster_id

        try:
            result = self._delete_files_from_source_and_database(cursor, selected_files)
            self._recalculate_cluster_dates_and_count(cursor, source_cluster_id)
            self.db.conn.commit()

            self.invalidate_plan()
            self.load_clusters()

            deleted_count = len(result["deleted"])
            missing_count = len(result["missing"])
            failed_count = len(result["failed"])

            cursor.execute(
                "SELECT file_count FROM clusters WHERE id = ?",
                (source_cluster_id,),
            )
            cluster = cursor.fetchone()
            if cluster and cluster["file_count"] > 0:
                self.load_cluster_by_id(source_cluster_id)
            else:
                self.thumbnail_grid.clear()
                self.rename_input.clear()
                self.rename_input.setEnabled(False)
                self.save_name_btn.setEnabled(False)
                self.current_cluster_id = None

            self.update_status(
                f"DELETE complete: {deleted_count} deleted, {missing_count} missing removed, {failed_count} failed"
            )

            QMessageBox.information(
                self,
                "DELETE Complete",
                f"Deleted from disk: {deleted_count}\n"
                f"Missing but removed from DB: {missing_count}\n"
                f"Failed: {failed_count}",
            )

        except Exception as e:
            self.db.conn.rollback()
            QMessageBox.critical(
                self,
                "DELETE Failed",
                f"Could not complete DELETE:\n{str(e)}",
            )

    def _next_manual_cluster_color(self):
        color = MANUAL_CLUSTER_COLORS[self.manual_cluster_color_index % len(MANUAL_CLUSTER_COLORS)]
        self.manual_cluster_color_index += 1
        return color

    def move_selected_thumbnails_to_temp_cluster(self, file_ids):
        """Creates a manual cluster from the selected thumbnails, independent of date gaps."""
        if not self.current_cluster_id or not file_ids:
            return

        cursor = self.db.conn.cursor()
        selected_files = self._selected_files_in_current_cluster(cursor, file_ids)

        if not selected_files:
            QMessageBox.warning(
                self,
                "Temp Cluster Failed",
                "No selected files are still part of the current cluster.",
            )
            return

        selected_ids = [row["id"] for row in selected_files]
        selected_dates = [row["computed_date"] for row in selected_files if row["computed_date"]]
        start_date = selected_dates[0] if selected_dates else None
        end_date = selected_dates[-1] if selected_dates else None

        try:
            cursor.execute(
                """
                INSERT INTO clusters (start_date, end_date, file_count, assigned_name, manual_kind, status)
                VALUES (?, ?, ?, ?, 'temp', 'pending')
                """,
                (start_date, end_date, len(selected_ids), None),
            )
            new_cluster_id = cursor.lastrowid
            self.manual_cluster_colors[new_cluster_id] = self._next_manual_cluster_color()

            selected_placeholders = ",".join("?" for _ in selected_ids)
            cursor.execute(
                f"""
                UPDATE files
                SET cluster_id = ?
                WHERE id IN ({selected_placeholders})
                """,
                [new_cluster_id] + selected_ids,
            )

            self._recalculate_cluster_dates_and_count(cursor, self.current_cluster_id)
            self._recalculate_cluster_dates_and_count(cursor, new_cluster_id)
            self.db.conn.commit()

            self.invalidate_plan()
            self.load_clusters()
            self.load_cluster_by_id(new_cluster_id)

            self.update_status(
                f"Moved {len(selected_ids)} file(s) into temp Event {new_cluster_id}"
            )

        except Exception as e:
            self.db.conn.rollback()
            QMessageBox.critical(
                self,
                "Temp Cluster Failed",
                f"Could not create temp cluster:\n{str(e)}",
            )

    def move_selected_thumbnails_to_existing_cluster(self, file_ids, target_cluster_id):
        """Moves selected thumbnails into an already-existing manual target cluster."""
        if not self.current_cluster_id or not file_ids or target_cluster_id == self.current_cluster_id:
            return

        cursor = self.db.conn.cursor()
        selected_files = self._selected_files_in_current_cluster(cursor, file_ids)

        if not selected_files:
            QMessageBox.warning(
                self,
                "Move Failed",
                "No selected files are still part of the current cluster.",
            )
            return

        selected_ids = [row["id"] for row in selected_files]

        try:
            placeholders = ",".join("?" for _ in selected_ids)
            cursor.execute(
                f"""
                UPDATE files
                SET cluster_id = ?
                WHERE id IN ({placeholders})
                """,
                [target_cluster_id] + selected_ids,
            )

            source_cluster_id = self.current_cluster_id
            self._recalculate_cluster_dates_and_count(cursor, source_cluster_id)
            self._recalculate_cluster_dates_and_count(cursor, target_cluster_id)
            self.db.conn.commit()

            self.invalidate_plan()
            self.load_clusters()
            self.load_cluster_by_id(target_cluster_id)

            self.update_status(
                f"Moved {len(selected_ids)} file(s) into Event {target_cluster_id}"
            )

        except Exception as e:
            self.db.conn.rollback()
            QMessageBox.critical(
                self,
                "Move Failed",
                f"Could not move files to existing cluster:\n{str(e)}",
            )

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
        if not self.current_cluster_id or self.current_cluster_id == DELETE_CLUSTER_ID:
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

    def _safe_folder_event_name(self, event_name):
        """Creates a folder-safe event name in the style of the existing FOTO pool."""
        safe_name = re.sub(r'[<>:"\\|?*/]+', "-", event_name.strip())
        safe_name = re.sub(r"\s+", " ", safe_name)
        safe_name = safe_name.strip(" .-")

        return safe_name or "Unnamed Event"

    def _build_target_dir(self, first_source_path: Path, computed_date: str, folder_event_name: str) -> Path:
        computed_date = computed_date or "1970-01-01 00:00:00"
        date_part = computed_date.split(" ")[0]
        year, month, day = date_part.split("-")

        if self.settings.output_root:
            return Path(self.settings.output_root) / year / f"{year} {month}.{day} {folder_event_name}"

        file_event_name = self._safe_event_name(folder_event_name)
        return first_source_path.parent.parent / f"{date_part}_{file_event_name}"

    def _build_output_filename(self, old_path: Path, computed_date: str, safe_name: str, sequence_number: int) -> str:
        """
        Builds the output filename according to the selected rename pattern.

        clean_sequence:
            2026-05-12_sakura_001.jpg

        timestamp:
            20260512_121459_sakura.jpg

        keep_original:
            20260512_121459_sakura_PXL_20260512_031459393.jpg

        imagee_smart:
            20260512_sakura_PXL_20260512_031459393.jpg
        """
        suffix = old_path.suffix
        computed_date = computed_date or "1970-01-01 00:00:00"

        date_part = computed_date.split(" ")[0]
        imagee_date_part = date_part.replace("-", "")
        timestamp_part = computed_date.replace("-", "").replace(":", "").replace(" ", "_")

        if self.settings.rename_pattern == "timestamp":
            return f"{timestamp_part}_{safe_name}{suffix}"

        if self.settings.rename_pattern == "keep_original":
            return f"{timestamp_part}_{safe_name}_{old_path.name}"

        if self.settings.rename_pattern == "imagee_smart":
            if old_path.name.startswith(imagee_date_part):
                return old_path.name

            return f"{imagee_date_part}_{safe_name}_{old_path.name}"

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

    def _unique_planned_path_with_collision(self, path: Path, reserved_paths: set):
        candidate = self._unique_planned_path(path, reserved_paths)
        return candidate, candidate != path

    def _path_is_relative_to(self, child: Path, parent: Path) -> bool:
        try:
            child.resolve().relative_to(parent.resolve())
            return True
        except (OSError, ValueError):
            return False

    def _add_output_root_warnings(self, plan):
        if not self.settings.output_root:
            return

        output_root = Path(self.settings.output_root).expanduser()
        output_root_text = str(output_root).replace("\\", "/").rstrip("/").lower()

        if output_root.anchor and output_root == Path(output_root.anchor):
            plan["warnings"].append(f"Staging/output root looks like a drive/root folder: {output_root}")

        if output_root_text in {"e:/foto", "/mnt/e/foto"} or output_root_text.startswith(("e:/foto/", "/mnt/e/foto/")):
            plan["warnings"].append(
                f"Staging/output root is inside the stable FOTO pool; use a separate staging folder if you plan manual promotion: {output_root}"
            )

        if not output_root.exists():
            plan["warnings"].append(f"Staging/output root does not exist yet: {output_root}")
        elif not output_root.is_dir():
            plan["warnings"].append(f"Staging/output root is not a folder: {output_root}")

    def _iter_sidecar_paths(self, media_path: Path):
        """Returns sidecars that should follow the renamed media file."""
        if media_path.suffix.lower() not in {".jpg", ".jpeg", ".mov", ".mp4"}:
            return []

        sidecars = []
        seen = set()

        for suffix in (".AAE", ".aae"):
            candidate = media_path.with_suffix(suffix)
            key = str(candidate).lower()

            if key in seen:
                continue

            seen.add(key)
            if candidate.exists():
                sidecars.append(candidate)

        return sidecars

    def _date_source_label(self, row):
        if row["exif_date"]:
            return "metadata"

        if row["regex_date"]:
            return "filename"

        if row["os_date"] and row["computed_date"] == row["os_date"]:
            return "os"

        return "unknown"

    def _audit_cluster_dates(self, cluster_id, files, folder_date, plan):
        dated_files = [row for row in files if row["computed_date"]]
        file_days = sorted({row["computed_date"].split(" ")[0] for row in dated_files})
        os_fallback_count = sum(1 for row in files if self._date_source_label(row) == "os")
        missing_date_count = len(files) - len(dated_files)

        if not file_days:
            date_audit = "No dates"
            plan["warnings"].append(f"Event {cluster_id} has no computed dates.")
        elif len(file_days) == 1 and file_days[0] == folder_date:
            date_audit = "OK"
        elif len(file_days) == 1:
            date_audit = f"Mismatch: {file_days[0]}"
            plan["warnings"].append(
                f"Event {cluster_id} folder date {folder_date} differs from file date {file_days[0]}."
            )
        else:
            date_audit = f"Multi-day: {file_days[0]}..{file_days[-1]}"
            plan["warnings"].append(
                f"Event {cluster_id} spans multiple file dates ({', '.join(file_days[:5])}"
                f"{'...' if len(file_days) > 5 else ''}) but will be staged under {folder_date}."
            )

        if os_fallback_count:
            plan["warnings"].append(
                f"Event {cluster_id} has {os_fallback_count} file(s) dated only from OS timestamps."
            )

        if missing_date_count:
            plan["warnings"].append(
                f"Event {cluster_id} has {missing_date_count} file(s) without a computed date."
            )

        return {
            "date_audit": date_audit,
            "file_dates": file_days,
            "os_fallback_count": os_fallback_count,
            "missing_date_count": missing_date_count,
        }

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
            "output_root": self.settings.output_root,
            "folder_pattern": (
                "<staging/output root>\\YYYY\\YYYY MM.DD Event Name"
                if self.settings.output_root
                else "source-adjacent YYYY-MM-DD_Event_Name"
            ),
            "plan_path": None,
            "clusters": [],
            "moves": [],
            "warnings": [],
        }

        reserved_paths = set()
        planned_sidecar_sources = set()
        self._add_output_root_warnings(plan)

        for cluster in clusters:
            cluster_id = cluster["id"]
            event_name = cluster["assigned_name"].strip()
            safe_name = self._safe_event_name(event_name)
            folder_event_name = self._safe_folder_event_name(event_name)

            cursor.execute(
                """
                SELECT id, original_path, exif_date, regex_date, os_date, computed_date
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

            target_dir = self._build_target_dir(
                first_source_path=Path(files[0]["original_path"]),
                computed_date=files[0]["computed_date"] or cluster["start_date"],
                folder_event_name=folder_event_name,
            )
            folder_date = (files[0]["computed_date"] or cluster["start_date"]).split(" ")[0]
            cluster_audit = self._audit_cluster_dates(cluster_id, files, folder_date, plan)

            if target_dir.exists():
                plan["warnings"].append(f"Target folder already exists and will be merged into: {target_dir}")

            plan["clusters"].append(
                {
                    "cluster_id": cluster_id,
                    "event_name": event_name,
                    "safe_name": safe_name,
                    "folder_name": target_dir.name,
                    "target_dir": str(target_dir),
                    "file_count": len(files),
                    **cluster_audit,
                }
            )

            for sequence_number, f in enumerate(files, start=1):
                old_path = Path(f["original_path"])
                computed_date = f["computed_date"] or cluster["start_date"]

                if self.settings.output_root and self._path_is_relative_to(target_dir, old_path.parent):
                    plan["warnings"].append(
                        f"Target folder is inside source folder for {old_path}: {target_dir}"
                    )

                new_filename = self._build_output_filename(
                    old_path=old_path,
                    computed_date=computed_date,
                    safe_name=safe_name,
                    sequence_number=sequence_number,
                )
                requested_path = target_dir / new_filename
                new_path, had_collision = self._unique_planned_path_with_collision(
                    requested_path,
                    reserved_paths,
                )

                if not old_path.exists():
                    plan["warnings"].append(f"Missing source file: {old_path}")

                if had_collision:
                    plan["warnings"].append(f"Target collision adjusted: {requested_path} -> {new_path}")

                plan["moves"].append(
                    {
                        "kind": "media",
                        "file_id": f["id"],
                        "cluster_id": cluster_id,
                        "event_name": event_name,
                        "date_source": self._date_source_label(f),
                        "from": str(old_path),
                        "to": str(new_path),
                    }
                )

                for sidecar_path in self._iter_sidecar_paths(old_path):
                    sidecar_source_key = str(sidecar_path).lower()
                    if sidecar_source_key in planned_sidecar_sources:
                        continue

                    planned_sidecar_sources.add(sidecar_source_key)

                    sidecar_requested_path = new_path.with_suffix(sidecar_path.suffix)
                    sidecar_new_path, sidecar_had_collision = self._unique_planned_path_with_collision(
                        sidecar_requested_path,
                        reserved_paths,
                    )

                    if sidecar_had_collision:
                        plan["warnings"].append(
                            f"Sidecar target collision adjusted: {sidecar_requested_path} -> {sidecar_new_path}"
                        )

                    plan["moves"].append(
                        {
                            "kind": "sidecar",
                            "file_id": None,
                            "cluster_id": cluster_id,
                            "event_name": event_name,
                            "from": str(sidecar_path),
                            "to": str(sidecar_new_path),
                            "sidecar_for": str(old_path),
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

    def _write_executed_result(self, result):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_dir = Path(".clustree_cache") / "executed_plans"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"clustree_executed_plan_{timestamp}.json"

        result["result_path"] = str(result_path)

        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return result_path

    def _open_created_folders(self, folder_paths):
        opened = 0

        for folder_path in folder_paths[:5]:
            path = Path(folder_path)
            if not path.exists():
                continue

            if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                opened += 1

        if len(folder_paths) > 5:
            self.update_status(f"Opened {opened} folders; {len(folder_paths) - 5} more are listed in the result JSON")
        else:
            self.update_status(f"Opened {opened} created folders")

    def _latest_executed_result_path(self):
        result_dir = Path(".clustree_cache") / "executed_plans"
        candidates = sorted(result_dir.glob("clustree_executed_plan_*.json"))
        return candidates[-1] if candidates else None

    def rollback_latest_run(self):
        result_path = self._latest_executed_result_path()

        if not result_path:
            QMessageBox.information(self, "No Rollback", "No executed plan archive was found.")
            return

        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(self, "Rollback Failed", f"Could not read rollback archive:\n{e}")
            return

        rollback_moves = result.get("rollback_moves", [])
        if not rollback_moves:
            QMessageBox.information(self, "No Rollback", "The latest executed plan has no rollback moves.")
            return

        blocked = []
        for move in rollback_moves:
            current_path = Path(move.get("from", ""))
            original_path = Path(move.get("to", ""))

            if not current_path.exists():
                blocked.append(f"Missing moved file: {current_path}")
            elif original_path.exists():
                blocked.append(f"Original path already exists: {original_path}")

        if blocked:
            QMessageBox.warning(
                self,
                "Rollback Blocked",
                "Rollback would not be safe:\n\n" + "\n".join(blocked[:12]),
            )
            return

        reply = QMessageBox.question(
            self,
            "Undo Last Run",
            f"Move {len(rollback_moves)} file(s) back using:\n{result_path}\n\nThis changes files on disk.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        cursor = self.db.conn.cursor()
        restored = []
        failed = []

        for move in rollback_moves:
            current_path = Path(move["from"])
            original_path = Path(move["to"])

            try:
                original_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current_path), str(original_path))

                if move.get("kind") == "media" and move.get("file_id") is not None:
                    cursor.execute(
                        "UPDATE files SET original_path = ?, status = 'clustered' WHERE id = ?",
                        (str(original_path), move["file_id"]),
                    )

                restored.append(move)

            except Exception as e:
                failed_move = dict(move)
                failed_move["error"] = str(e)
                failed.append(failed_move)

        if not failed:
            for cluster_id in result.get("archived_cluster_ids", []):
                cursor.execute(
                    "UPDATE clusters SET status = 'pending' WHERE id = ?",
                    (cluster_id,),
                )
                self._recalculate_cluster_dates_and_count(cursor, cluster_id)

        self.db.conn.commit()

        rollback_result = {
            "app_version": APP_VERSION,
            "rolled_back_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_result_path": str(result_path),
            "restored": restored,
            "failed": failed,
        }
        rollback_path = self._write_rollback_result(rollback_result)

        self.current_move_plan = None
        self.run_plan_btn.setEnabled(False)
        self.load_clusters()
        self.thumbnail_grid.clear()

        self.update_status(f"Rollback complete: {len(restored)} restored, {len(failed)} failed")

        QMessageBox.information(
            self,
            "Rollback Complete",
            f"Restored: {len(restored)}\nFailed: {len(failed)}\n\nResult saved:\n{rollback_path}",
        )

    def _write_rollback_result(self, result):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result_dir = Path(".clustree_cache") / "rollback_results"
        result_dir.mkdir(parents=True, exist_ok=True)
        result_path = result_dir / f"clustree_rollback_{timestamp}.json"

        result["result_path"] = str(result_path)
        result_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return result_path

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
        touched_clusters = set()

        result = {
            "app_version": APP_VERSION,
            "executed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_plan_path": self.current_move_plan.get("plan_path"),
            "rename_pattern": self.current_move_plan.get("rename_pattern"),
            "rename_pattern_label": self.current_move_plan.get("rename_pattern_label"),
            "output_root": self.current_move_plan.get("output_root"),
            "folder_pattern": self.current_move_plan.get("folder_pattern"),
            "moved": [],
            "rollback_moves": [],
            "missing": [],
            "failed": [],
            "created_dirs": [],
            "archived_cluster_ids": [],
            "result_path": None,
        }
        created_dirs = []

        for move in self.current_move_plan["moves"]:
            file_id = move["file_id"]
            move_kind = move.get("kind", "media")
            old_path = Path(move["from"])
            new_path = Path(move["to"])
            touched_clusters.add(move["cluster_id"])

            try:
                if not old_path.exists():
                    if move_kind == "media" and file_id is not None:
                        cursor.execute(
                            "UPDATE files SET status = 'missing' WHERE id = ?",
                            (file_id,),
                        )

                    result["missing"].append(move)
                    continue

                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_path), str(new_path))

                if move_kind == "media" and file_id is not None:
                    cursor.execute(
                        "UPDATE files SET original_path = ?, status = 'archived' WHERE id = ?",
                        (str(new_path), file_id),
                    )

                    created_dir = str(new_path.parent)
                    if created_dir not in created_dirs:
                        created_dirs.append(created_dir)

                result["moved"].append(move)
                result["rollback_moves"].append(
                    {
                        "kind": move_kind,
                        "file_id": file_id,
                        "cluster_id": move.get("cluster_id"),
                        "event_name": move.get("event_name"),
                        "from": str(new_path),
                        "to": str(old_path),
                    }
                )

            except Exception as e:
                failed_move = dict(move)
                failed_move["error"] = str(e)
                result["failed"].append(failed_move)

        if result["failed"]:
            for cluster_id in touched_clusters:
                self._recalculate_cluster_dates_and_count(cursor, cluster_id)
        else:
            for cluster_id in touched_clusters:
                cursor.execute(
                    "UPDATE clusters SET status = 'archived' WHERE id = ?",
                    (cluster_id,),
                )
                result["archived_cluster_ids"].append(cluster_id)

        self.db.conn.commit()
        result["created_dirs"] = created_dirs
        result_path = self._write_executed_result(result)

        moved = len(result["moved"])
        missing = len(result["missing"])
        failed = len(result["failed"])

        self.current_move_plan = None
        self.run_plan_btn.setEnabled(False)

        self.thumbnail_grid.clear()
        self.rename_input.clear()
        self.rename_input.setEnabled(False)
        self.save_name_btn.setEnabled(False)
        self.current_cluster_id = None

        self.load_clusters()
        self.update_status(f"Run complete: {moved} moved, {missing} missing, {failed} failed")

        QMessageBox.information(
            self,
            "Run Complete",
            f"Moved: {moved}\nMissing: {missing}\nFailed: {failed}\n\nResult saved:\n{result_path}",
        )

        if moved and created_dirs:
            reply = QMessageBox.question(
                self,
                "Open Created Folders",
                f"Open {min(len(created_dirs), 5)} created folder(s) now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )

            if reply == QMessageBox.Yes:
                self._open_created_folders(created_dirs)
