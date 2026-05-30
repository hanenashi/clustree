import logging
from datetime import datetime
from core.database import ClustreeDB

logger = logging.getLogger(__name__)

class ClusterEngine:
    def __init__(self, db: ClustreeDB, max_gap_hours=12):
        self.db = db
        self.max_gap_seconds = max_gap_hours * 3600

    def build_clusters(self):
        """Groups files into events based on chronological time gaps."""
        cursor = self.db.conn.cursor()
        
        # Get all dated, non-duplicate files sorted chronologically
        cursor.execute('''
            SELECT id, computed_date 
            FROM files 
            WHERE status = 'dated' AND is_duplicate = 0
            ORDER BY computed_date ASC
        ''')
        rows = cursor.fetchall()

        if not rows:
            print("No files available to cluster.")
            return

        clusters = []
        current_cluster = []
        
        for row in rows:
            file_id = row['id']
            try:
                current_time = datetime.strptime(row['computed_date'], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue

            # Start the very first cluster
            if not current_cluster:
                current_cluster = [{'id': file_id, 'time': current_time}]
                continue

            prev_time = current_cluster[-1]['time']
            time_diff = (current_time - prev_time).total_seconds()

            # If within the gap limit, add to current event
            if time_diff <= self.max_gap_seconds:
                current_cluster.append({'id': file_id, 'time': current_time})
            else:
                # Gap exceeded! Save the current cluster and start a new one
                clusters.append(current_cluster)
                current_cluster = [{'id': file_id, 'time': current_time}]

        # Catch the final cluster left in the buffer
        if current_cluster:
            clusters.append(current_cluster)

        self._save_clusters(clusters)

    def _save_clusters(self, clusters):
        """Writes the clustered groups back to the database."""
        cursor = self.db.conn.cursor()
        
        for cluster in clusters:
            start_date = cluster[0]['time'].strftime('%Y-%m-%d %H:%M:%S')
            end_date = cluster[-1]['time'].strftime('%Y-%m-%d %H:%M:%S')
            file_count = len(cluster)
            
            # Create the parent cluster record
            cursor.execute('''
                INSERT INTO clusters (start_date, end_date, file_count)
                VALUES (?, ?, ?)
            ''', (start_date, end_date, file_count))
            
            cluster_id = cursor.lastrowid
            
            # Tag all associated files with this new cluster ID
            file_ids = [(cluster_id, f['id']) for f in cluster]
            cursor.executemany('''
                UPDATE files SET cluster_id = ?, status = 'clustered' WHERE id = ?
            ''', file_ids)
            
        self.db.conn.commit()
        print(f"Created {len(clusters)} magic clusters from {sum(len(c) for c in clusters)} files.")
