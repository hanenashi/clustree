import os
import re
import shutil
import warnings
from pathlib import Path

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QProgressBar,
    QLineEdit, QPushButton, QMessageBox, QFileDialog,
    QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox
)

# Silence the High Sierra SIP deprecation warning
warnings.filterwarnings("ignore", message="sipPyTypeDict.. is deprecated")

from PyQt5.QtGui import QPixmap, QIcon, QImage
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal

# Import the core engine to run from the UI
from core.app_config import (
    APP_VERSION,
    CLUSTER_GAP_PRESETS,
    AppSettings,
    load_settings,
    save_settings,
)
from core.crawler import Crawler
from core.metadata import MetadataExtractor
from core.cluster import ClusterEngine


class SettingsDialog(QDialog):
    """Small settings pane for the first configurable Clustree options."""
    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clustree Settings")
        self.settings = AppSettings(
            cluster_gap_preset=settings.cluster_gap_preset,
            cluster_gap_hours=settings.cluster_gap_hours,
            thumbnail_size=settings.thumbnail_size,
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
        return AppSettings(
            cluster_gap_preset=preset_name,
            cluster_gap_hours=self.gap_hours_spin.value(),
            thumbnail_size=self.thumbnail_size_spin.value(),
        ).normalize()


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
    thumb_ready = pyqtSignal(str, str, QImage)
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
                
            file_path = f['original_path']
            file_name = Path(file_path).name

            if file_path.lower().endswith(('.jpg', '.jpeg', '.png')):
                img = QImage(file_path)
                img = img.scaled(
                    self.thumbnail_size,
                    self.thumbnail_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb_ready.emit(file_path, file_name, img)
            else:
                self.thumb_ready.emit(file_path, file_name, QImage()) 
                
            self.progress.emit(i + 1)
            
        self.finished.emit()

    def stop(self):
        self.is_running = False


class ClusterListWidget(QListWidget):
    """Custom ListWidget for the sidebar to handle drag-and-drop reassignment."""
    file_reassigned = pyqtSignal(str, int) # Emits: file_path, new_cluster_id

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        # Only accept drops coming from the thumbnail grid
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
        
        # Handle multiple selected items being dragged
        for item in source_widget.selectedItems():
            file_path = item.data(Qt.ItemDataRole.UserRole)
            self.file_reassigned.emit(file_path, new_cluster_id)
            
            # Remove the thumbnail from the grid visually
            source_widget.takeItem(source_widget.row(item))

        event.accept()


class ClustreeWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.settings = load_settings()
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
        
        # Use our new custom drag-and-drop list widget
        self.cluster_list = ClusterListWidget()
        self.cluster_list.setFixedWidth(300)
        self.cluster_list.itemClicked.connect(self.start_loading_cluster)
        self.cluster_list.file_reassigned.connect(self.handle_file_reassigned)
        
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
        
        # NEW Drag and Drop Settings for the Grid
        self.thumbnail_grid.setDragEnabled(True)
        self.thumbnail_grid.setAcceptDrops(False) # Stop the green plus self-copy bug
        self.thumbnail_grid.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection) # Allow multi-select
        
        action_layout = QHBoxLayout()
        self.rename_input = QLineEdit()
        self.rename_input.setPlaceholderText("Enter Event Name (e.g., Park Trip, Beach Day)...")
        self.rename_input.returnPressed.connect(self.commit_event) 
        self.rename_input.setEnabled(False)
        
        self.commit_btn = QPushButton("Commit & Move Event")
        self.commit_btn.setEnabled(False)
        self.commit_btn.clicked.connect(self.commit_event)
        
        action_layout.addWidget(self.rename_input)
        action_layout.addWidget(self.commit_btn)
        
        right_panel.addWidget(self.grid_header)
        right_panel.addWidget(self.progress_bar)
        right_panel.addWidget(self.thumbnail_grid)
        right_panel.addLayout(action_layout)
        
        main_layout.addLayout(right_panel)
        self.statusBar()
        self.update_status()
        self.load_clusters()

    def update_status(self, message="Ready"):
        self.statusBar().showMessage(
            f"{message} | Clustree {APP_VERSION} | Gap: {self.settings.cluster_gap_hours}h | Thumb: {self.settings.thumbnail_size}px"
        )

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec_() != QDialog.Accepted:
            return

        self.settings = dialog.get_settings()
        save_settings(self.settings)
        self.thumbnail_grid.setIconSize(QSize(self.settings.thumbnail_size, self.settings.thumbnail_size))
        self.update_status("Settings saved")

    def handle_file_reassigned(self, file_path, new_cluster_id):
        """Updates the DB when a thumbnail is dropped onto a new cluster."""
        cursor = self.db.conn.cursor()
        cursor.execute("UPDATE files SET cluster_id = ? WHERE original_path = ?", (new_cluster_id, file_path))
        
        # Dynamically recalculate all active cluster file counts
        cursor.execute('''
            UPDATE clusters 
            SET file_count = (SELECT COUNT(id) FROM files WHERE files.cluster_id = clusters.id AND files.status != 'archived')
        ''')
        self.db.conn.commit()
        
        # Refresh sidebar so the bracketed numbers update [11 files] -> [12 files]
        self.load_clusters()
        self.update_status("File reassigned")

    def select_and_scan_folder(self):
        target_dir = QFileDialog.getExistingDirectory(self, "Select Directory to Ingest")
        if not target_dir:
            return
            
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning...")
        self.settings_btn.setEnabled(False)
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
        self.scan_btn.setText("Scan Folder...")
        self.grid_header.setText("<b>Scan complete! Select a new cluster on the left.</b>")
        self.load_clusters()
        self.update_status("Scan complete")

    def load_clusters(self):
        self.cluster_list.clear()
        cursor = self.db.conn.cursor()
        # Only show clusters that actually have files left in them (count > 0)
        cursor.execute("SELECT id, start_date, file_count FROM clusters WHERE status != 'archived' AND file_count > 0 ORDER BY start_date ASC")
        clusters = cursor.fetchall()
        
        for cluster in clusters:
            cid = cluster['id']
            date = cluster['start_date'].split(' ')[0]
            count = cluster['file_count']
            
            item = QListWidgetItem(f"Event {cid} ({date})\n[{count} files]")
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self.cluster_list.addItem(item)

    def start_loading_cluster(self, item):
        if self.thumb_worker and self.thumb_worker.isRunning():
            self.thumb_worker.stop()
            self.thumb_worker.wait()
            
        self.thumbnail_grid.clear()
        self.current_cluster_id = item.data(Qt.ItemDataRole.UserRole)
        
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT original_path FROM files WHERE cluster_id = ? ORDER BY computed_date ASC", (self.current_cluster_id,))
        files = cursor.fetchall()
        
        self.grid_header.setText(f"<b>Viewing Event {self.current_cluster_id} ({len(files)} files)</b>")
        self.rename_input.setEnabled(True)
        self.commit_btn.setEnabled(True)
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

    def add_thumbnail(self, file_path, file_name, qimage):
        thumb_item = QListWidgetItem()
        
        if not qimage.isNull():
            pixmap = QPixmap.fromImage(qimage)
            thumb_item.setIcon(QIcon(pixmap))
        else:
            thumb_item.setText("Video File")
            
        thumb_item.setToolTip(file_name)
        thumb_item.setData(Qt.ItemDataRole.UserRole, file_path)
        self.thumbnail_grid.addItem(thumb_item)

    def _safe_event_name(self, event_name):
        """Creates a filesystem-friendly event name while keeping it readable."""
        safe_name = re.sub(r'[<>:"\\|?*/]+', '-', event_name.strip())
        safe_name = re.sub(r'\s+', '_', safe_name)
        safe_name = safe_name.strip(' ._-')
        return safe_name or "Unnamed_Event"

    def _unique_path(self, path: Path) -> Path:
        """Returns a non-existing path by appending _2, _3, etc. if needed."""
        if not path.exists():
            return path

        parent = path.parent
        stem = path.stem
        suffix = path.suffix
        counter = 2

        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def commit_event(self):
        event_name = self.rename_input.text().strip()
        if not event_name or not self.current_cluster_id:
            return

        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, original_path, computed_date FROM files WHERE cluster_id = ? ORDER BY computed_date ASC", (self.current_cluster_id,))
        files = cursor.fetchall()

        if not files:
            return

        base_date = files[0]['computed_date'].split(' ')[0]
        safe_name = self._safe_event_name(event_name)
        
        target_dir = Path(files[0]['original_path']).parent.parent / f"{base_date}_{safe_name}"
        target_dir.mkdir(parents=True, exist_ok=True)

        move_plan = []
        for f in files:
            old_path = Path(f['original_path'])
            date_compact = f['computed_date'].replace("-", "").replace(":", "").replace(" ", "_")
            new_filename = f"{date_compact}_{safe_name}_{old_path.name}"
            new_path = self._unique_path(target_dir / new_filename)
            move_plan.append((f['id'], old_path, new_path))

        try:
            for file_id, old_path, new_path in move_plan:
                if not old_path.exists():
                    cursor.execute("UPDATE files SET status = 'missing' WHERE id = ?", (file_id,))
                    continue

                shutil.move(str(old_path), str(new_path))
                cursor.execute("UPDATE files SET original_path = ?, status = 'archived' WHERE id = ?", (str(new_path), file_id))

            cursor.execute("UPDATE clusters SET assigned_name = ?, status = 'archived' WHERE id = ?", (event_name, self.current_cluster_id))
            self.db.conn.commit()
            
            self.thumbnail_grid.clear()
            self.rename_input.clear()
            self.rename_input.setEnabled(False)
            self.commit_btn.setEnabled(False)
            self.grid_header.setText("<b>Select a cluster to view media...</b>")
            
            self.load_clusters()
            self.update_status("Event moved")
            
        except Exception as e:
            self.db.conn.rollback()
            self.update_status("Move failed")
            QMessageBox.critical(self, "Error Moving Files", f"An error occurred: {str(e)}")
