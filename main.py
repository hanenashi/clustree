import os
from pathlib import Path
from core.database import ClustreeDB
from core.crawler import Crawler
from core.metadata import MetadataExtractor

def main():
    print("🌳 Starting Clustree Engine...")
    
    # Initialize Database
    db = ClustreeDB("clustree_test.db")
    
    # --- Phase 1: Ingestion & Deduplication ---
    test_folder = input("Enter path to a test directory (e.g., C:/temp/photos): ").strip()
    
    if not os.path.exists(test_folder):
        print("Path not found. Exiting.")
        return

    print("\n--- Phase 1: Crawling & Hashing ---")
    crawler = Crawler(db)
    crawler.scan_directory(test_folder)

    # --- Phase 2: Timeline Extraction ---
    print("\n--- Phase 2: Extracting Timelines ---")
    extractor = MetadataExtractor(db)
    extractor.process_pending_files()

    print("\n✅ Run complete. Check 'clustree_test.db' using an SQLite viewer to inspect the results.")
    db.close()

if __name__ == "__main__":
    main()
