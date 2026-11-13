"""Entry point for the desktop app (PyInstaller builds SCCBroadcastEngine.exe from this)."""
import sys

from sccbe.gui import main

if __name__ == "__main__":
    sys.exit(main())
