"""Nuke GUI startup entry point for the standalone Node Graph Pie."""

from pathlib import Path
import sys
import traceback

import nuke


if nuke.GUI:
    library = str(Path(__file__).resolve().parent / "_lib")
    if library not in sys.path:
        sys.path.insert(0, library)
    try:
        import studio_pie_menu

        studio_pie_menu.install(nuke)
    except Exception:
        print("[Node Graph Pie] Startup failed. See traceback below.")
        traceback.print_exc()
