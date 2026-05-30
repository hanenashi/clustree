import os
from pathlib import Path
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QListWidget, QListWidgetItem, QLabel, QScrollArea,
                             QGridLayout)
from PyQt5.QtGui import QPixmap, QIcon
from PyQt5.QtCore import Qt, QSize

class ClustreeWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Clustree 🌳 - Triage")
        self.resize(1200, 800)
        
        # Main Layout Setup
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # --- Left Panel: Cluster List ---
        left_panel = QVBoxLayout()
        self.cluster_list = QListWidget()
        self.cluster_list.setFixedWidth(300)
        self.cluster_list.itemClicked.connect(self.load_cluster_media)
        
        left_panel.addWidget(QLabel("<b>Detected Events (Clusters)</b>"))
        left_panel.addWidget(self.cluster_list)
        main_layout.addLayout(left_panel)
        
        # --- Right Panel: Thumbnail Grid ---
        right_panel = QVBoxLayout()
        self.grid_header = QLabel("<b>Select a cluster to view media...</b>")
        
        # Using a QListWidget in IconMode is a fast, native way to build a wrapping grid
        self.thumbnail_grid = QListWidget()
        self.thumbnail_grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnail_grid.setIconSize(QSize(200, 200))
        self.thumbnail_grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnail_grid.setSpacing(10)
        
        right_panel.addWidget(self.grid_header)
        right_panel.addWidget(self.thumbnail_grid)
        main_layout.addLayout(right_panel)
        
        # Populate the left panel
        self.load_clusters()

    def load_clusters(self):
        """Fetches all magic clusters from the DB and populates the sidebar."""
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT id, start_date, file_count FROM clusters ORDER BY start_date ASC")
        clusters = cursor.fetchall()
        
        for cluster in clusters:
            cid = cluster['id']
            date = cluster['start_date'].split(' ')[0]  # Just grab YYYY-MM-DD
            count = cluster['file_count']
            
            display_text = f"Event {cid} ({date}) \n[{count} files]"
            
            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, cid) # Store the ID secretly in the item
            self.cluster_list.addItem(item)

    def load_cluster_media(self, item):
        """Loads thumbnails for the selected cluster."""
        self.thumbnail_grid.clear()
        cluster_id = item.data(Qt.ItemDataRole.UserRole)
        
        cursor = self.db.conn.cursor()
        cursor.execute("SELECT original_path FROM files WHERE cluster_id = ? ORDER BY computed_date ASC", (cluster_id,))
        files = cursor.fetchall()
        
        self.grid_header.setText(f"<b>Viewing Event {cluster_id} ({len(files)} files)</b>")
        
        for f in files:
            file_path = f['original_path']
            
            # Create Thumbnail
            thumb_item = QListWidgetItem()
            
            if file_path.lower().endswith(('.jpg', '.jpeg', '.png')):
                pixmap = QPixmap(file_path).scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                thumb_item.setIcon(QIcon(pixmap))
            else:
                # Placeholder for videos for now
                thumb_item.setText("🎥 Video File")
                
            thumb_item.setToolTip(Path(file_path).name)
            self.thumbnail_grid.addItem(thumb_item)
