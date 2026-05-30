import sys
import os
from pathlib import Path
from PyQt5.QtWidgets import QApplication

from core.database import ClustreeDB
from gui.main_window import ClustreeWindow

def main():
    print("🌳 Booting Clustree UI...")
    
    # We skip the crawler phases for now and just open the DB we already built
    db = ClustreeDB("clustree_test.db")
    
    # Start PyQt5 Application
    app = QApplication(sys.argv)
    
    # Set global dark-ish theme (optional, but easy on the eyes)
    app.setStyle("Fusion")
    
    window = ClustreeWindow(db)
    window.show()
    
    # Run the event loop
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
