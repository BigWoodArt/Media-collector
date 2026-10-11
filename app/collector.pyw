"""Media Collector without a console window (double-click this, or use run.bat).
If it fails to start, the reason is written to collector_crash.log next to this file."""
import os
import sys
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))
try:
    from ui.collector_app import main
    main()
except Exception:
    with open("collector_crash.log", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    try:
        import tkinter
        from tkinter import messagebox
        r = tkinter.Tk()
        r.withdraw()
        messagebox.showerror("Media Collector", "It failed to start. Details are in collector_crash.log")
    except Exception:
        pass
    sys.exit(1)
