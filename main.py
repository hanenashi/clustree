import sys
import os
import warnings
from pathlib import Path
from PyQt5.QtWidgets import QApplication

# Silence the High Sierra SIP deprecation warning
warnings.filterwarnings("ignore", message="sipPyTypeDict.. is deprecated")

from core.database import ClustreeDB
from gui.main_window import ClustreeWindow

def main():
    print("🌳 Booting Clustree UI...")
    
    # Initialize Database
    db = ClustreeDB("clustree_test.db")
    
    # Start PyQt5 Application
    app = QApplication(sys.argv)
    
    # Set global dark-ish theme
    app.setStyle("Fusion")
    
    window = ClustreeWindow(db)
    window.show()
    
    # CRITICAL: This traps the script in an event loop to keep the window open
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
