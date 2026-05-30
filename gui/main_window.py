import os
import shutil
import warnings
from pathlib import Path

from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QListWidget, QListWidgetItem, QLabel, QProgressBar,
                             QLineEdit, QPushButton, QMessageBox, QFileDialog)

# Silence the High Sierra SIP deprecation warning
warnings.filterwarnings("ignore", message="sipPyTypeDict.. is deprecated")

from PyQt5.QtGui import QPixmap, QIcon, QImage
from PyQt5.QtCore import Qt, QSize, QThread, pyqtSignal

# Import the core engine to run from the UI
from core.crawler import Crawler
from core.metadata import MetadataExtractor
from core.cluster import ClusterEngine


class IngestionWorker(QThread):
    """Background thread to run the 3-phase engine without freezing the GUI."""
    finished = pyqtSignal()

    def __init__(self, db, target_dir):
        super().__init__()
        self.db = db
        self.target_dir = target_dir

    def run(self):
        # Phase 1
        crawler = Crawler(self.db)
        crawler.scan_directory(self.target_dir)

        # Phase 2
        extractor = MetadataExtractor(self.db)
        extractor.process_pending_files()

        # Phase 3
        cluster_engine = ClusterEngine(self.db, max_gap_hours=12)
        cluster_engine.build_clusters()

        self.finished.emit()


class ThumbnailWorker(QThread):
    """Background thread to safely load and scale images without freezing the UI."""
    progress = pyqtSignal(int)
    thumb_ready = pyqtSignal(str, str, QImage)
    finished = pyqtSignal()

    def __init__(self, files):
        super().__init__()
        self.files = files
        self.is_running = True

    def run(self):
        for i, f in enumerate(self.files):
            if not self.is_running:
                break
                
            file_path = f['original_path']
            file_name = Path(file_path).name

            if file_path.lower().endswith(('.jpg', '.jpeg', '.png')):
                img = QImage(file_path)
                img = img.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.thumb_ready.emit(file_path, file_name, img)
            else:
                self.thumb_ready.emit(file_path, file_name, QImage()) 
                
            self.progress.emit(i + 1)
            
        self.finished.emit()

    def stop(self):
        self.is_running = False


class ClustreeWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Clustree 🌳 - Triage")
        self.resize(1200, 800)
        self.current_cluster_id = None
        self.thumb_worker = None
        self.ingestion_worker = None
        
        # Main Layout Setup
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # --- Left Panel: Cluster List & Controls ---
        left_panel = QVBoxLayout()
        
        # New: Top control bar for the left panel
        left_header_layout = QHBoxLayout()
        left_header_layout.addWidget(QLabel("<b>Detected Events</b>"))
        
        self.scan_btn = QPushButton("Scan Folder...")
        self.scan_btn.clicked.connect(self.select_and_scan_folder)
        left_header_layout.addWidget(self.scan_btn)
        
        left_panel.addLayout(left_header_layout)
        
        self.cluster_list = QListWidget()
        self.cluster_list.setFixedWidth(300)
        self.cluster_list.itemClicked.connect(self.start_loading_cluster)
        
        left_panel.addWidget(self.cluster_list)
        main_layout.addLayout(left_panel)
        
        # --- Right Panel: Triage & Rename ---
        right_panel = QVBoxLayout()
        
        # Header & Progress
        self.grid_header = QLabel("<b>Select a cluster to view media...</b>")
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        
        # Thumbnail Grid
        self.thumbnail_grid = QListWidget()
        self.thumbnail_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnail_grid.setIconSize(QSize(200, 200))
        self.thumbnail_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnail_grid.setSpacing(10)
        
        # Action Bar (Bottom)
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
        
        # Assemble Right Panel
        right_panel.addWidget(self.grid_header)
        right_panel.addWidget(self.progress_bar)
        right_panel.addWidget(self.thumbnail_grid)
        right_panel.addLayout(action_layout)
        
        main_layout.addLayout(right_panel)
        
        self.load_clusters()

    def select_and_scan_folder(self):
        """Opens a folder picker and kicks off the background ingestion engine."""
        target_dir = QFileDialog.getExistingDirectory(self, "Select Directory to Ingest")
        if not target_dir:
            return
            
        # Lock UI slightly to show work is happening
        self.scan_btn.setEnabled(False)
        self.scan_btn.setText("Scanning...")
        self.grid_header.setText("<b>⚙️ Engine running. Check terminal for live progress...</b>")
        self.thumbnail_grid.clear()
        
        # Fire up the engine in the background
        self.ingestion_worker = IngestionWorker(self.db, target_dir)
        self.ingestion_worker.finished.connect(self.on_scan_complete)
        self.ingestion_worker.start()

    def on_scan_complete(self):
        """Called when the backend engine finishes its run."""
        self.scan_btn.setEnabled(True)
        self.scan_btn.setText("Scan Folder...")
        self.grid_header.setText("<b>✅ Scan complete! Select a new cluster on the left.</b>")
        self.load_clusters()

    def load_clusters(self):
        """Fetches pending clusters from the DB and populates the sidebar."""
        self.cluster_list.clear()
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, start_date, file_count FROM clusters WHERE status != 'archived' ORDER BY start_date ASC")
        clusters = cursor.fetchall()
        
        for cluster in clusters:
            cid = cluster['id']
            date = cluster['start_date'].split(' ')[0]
            count = cluster['file_count']
            
            item = QListWidgetItem(f"Event {cid} ({date})\n[{count} files]")
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self.cluster_list.addItem(item)

    def start_loading_cluster(self, item):
        """Initiates the background thread to load images."""
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
        
        self.progress_bar.setMaximum(len(files))
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        
        self.thumb_worker = ThumbnailWorker(files)
        self.thumb_worker.thumb_ready.connect(self.add_thumbnail)
        self.thumb_worker.progress.connect(self.progress_bar.setValue)
        self.thumb_worker.finished.connect(self.progress_bar.hide)
        self.thumb_worker.start()

    def add_thumbnail(self, file_path, file_name, qimage):
        """Slot to safely add the constructed image to the UI thread."""
        thumb_item = QListWidgetItem()
        
        if not qimage.isNull():
            pixmap = QPixmap.fromImage(qimage)
            thumb_item.setIcon(QIcon(pixmap))
        else:
            thumb_item.setText("🎥 Video File")
            
        thumb_item.setToolTip(file_name)
        thumb_item.setData(Qt.ItemDataRole.UserRole, file_path)
        self.thumbnail_grid.addItem(thumb_item)

    def commit_event(self):
        """Renames, moves files, and marks the cluster as archived."""
        event_name = self.rename_input.text().strip()
        if not event_name or not self.current_cluster_id:
            return

        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, original_path, computed_date FROM files WHERE cluster_id = ? ORDER BY computed_date ASC", (self.current_cluster_id,))
        files = cursor.fetchall()

        if not files:
            return

        base_date = files[0]['computed_date'].split(' ')[0]
        safe_name = event_name.replace(" ", "_").replace("/", "-")
        
        target_dir = Path(files[0]['original_path']).parent.parent / f"{base_date}_{safe_name}"
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            for f in files:
                old_path = Path(f['original_path'])
                date_compact = f['computed_date'].replace("-", "").replace(":", "").replace(" ", "_")
                new_filename = f"{date_compact}_{safe_name}_{old_path.name}"
                new_path = target_dir / new_filename

                shutil.move(str(old_path), str(new_path))
                cursor.execute("UPDATE files SET original_path = ?, status = 'archived' WHERE id = ?", (str(new_path), f['id']))

            cursor.execute("UPDATE clusters SET assigned_name = ?, status = 'archived' WHERE id = ?", (event_name, self.current_cluster_id))
            self.db.conn.commit()
            
            self.thumbnail_grid.clear()
            self.rename_input.clear()
            self.rename_input.setEnabled(False)
            self.commit_btn.setEnabled(False)
            self.grid_header.setText("<b>Select a cluster to view media...</b>")
            
            self.load_clusters()
            
        except Exception as e:
            QMessageBox.critical(self, "Error Moving Files", f"An error occurred: {str(e)}")
