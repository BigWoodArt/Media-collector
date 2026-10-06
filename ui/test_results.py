import tkinter as tk
from tkinter import ttk

import theme
from core.util import open_path
from ui.tiles import photo as tile_photo

COLORS = {"ok": "#5fd38d", "empty": "#e0b84a", "fail": theme.CRIMSON,
          "stopped": theme.MUTED, "rejected": theme.MUTED}


class TestResultsWindow(tk.Toplevel):
    """One row per request: thumbnail, site/query, status, timing, detail."""

    def __init__(self, parent, results, test_dir=None):
        super().__init__(parent)
        self.title("Site check results")
        self.configure(bg=theme.BG)
        self.geometry("760x560")
        self.transient(parent)
        self._photos = []
        self._test_dir = test_dir
        counts = {}
        for r in results:
            counts[r["result"]] = counts.get(r["result"], 0) + 1
        summary = "   ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "no results"
        tk.Label(self, text=f"Site check finished - {summary}", bg=theme.BG, fg=theme.CRIMSON,
                 font=theme.FONT_LABELFRAME).pack(anchor="w", padx=14, pady=(12, 2))
        tk.Label(self, text="One tiny search per site. \"ok\" = live and returning files; \"empty\" = the site answered but "
                            "nothing matched; \"fail\" = a real error (down, blocked, or needs a key in Settings).",
                 bg=theme.BG, fg=theme.MUTED, font=theme.FONT_SMALL, wraplength=720,
                 justify="left").pack(anchor="w", padx=14, pady=(0, 6))

        outer = tk.Frame(self, bg=theme.BG)
        outer.pack(fill="both", expand=True, padx=14)
        canvas = tk.Canvas(outer, bg=theme.BG, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=theme.BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        for r in results:
            self._row(body, r)

        btns = tk.Frame(self, bg=theme.BG)
        btns.pack(fill="x", padx=14, pady=10)
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        if test_dir:
            ttk.Button(btns, text="Open sample files",
                       command=lambda: open_path(test_dir)).pack(side="right")

    def _row(self, parent, r):
        row = tk.Frame(parent, bg=theme.PANEL_BG)
        row.pack(fill="x", pady=3)
        item = r["item"]
        ph = tile_photo(r["thumb"], item.media_type if item is not None else "image", 84, 84) \
            if item is not None else None
        if ph is not None:
            self._photos.append(ph)
        thumb = tk.Label(row, bg=theme.PANEL_BG, image=ph or "", text="" if ph else "-",
                         fg=theme.MUTED, width=None if ph else 11)
        thumb.pack(side="left", padx=6, pady=6)
        info = tk.Frame(row, bg=theme.PANEL_BG)
        info.pack(side="left", fill="x", expand=True, pady=4)
        tk.Label(info, text=f"{r['result'].upper()}", bg=theme.PANEL_BG,
                 fg=COLORS.get(r["result"], theme.TEXT_FG), font=theme.FONT_BOLD).pack(anchor="w")
        tk.Label(info, text=f"{r['label']}   search: {r['query']}   ({r['elapsed']}s)",
                 bg=theme.PANEL_BG, fg=theme.TEXT_FG, font=theme.FONT_NORMAL).pack(anchor="w")
        http = r.get("http") or []
        bad = [c for c in http if c.get("error") or (c.get("status") or 0) >= 400]
        shown = bad[:2] or http[:1]
        line = f"{len(http)} HTTP call(s), {len(bad)} failed"
        for c in shown:
            line += f"\n  {c.get('status')}  {c['url'][:110]}" + (
                f"  <- {(c.get('body') or c.get('error') or '')[:100]}" if bad else "")
        tk.Label(info, text=line, bg=theme.PANEL_BG, fg=theme.MUTED, font=("Consolas", 8),
                 wraplength=560, justify="left").pack(anchor="w")
        if r["detail"]:
            tk.Label(info, text=r["detail"], bg=theme.PANEL_BG, fg=theme.MUTED,
                     font=theme.FONT_SMALL, wraplength=560, justify="left").pack(anchor="w")
        elif r["item"] is not None:
            tk.Label(info, text=r["item"].caption[:90], bg=theme.PANEL_BG, fg=theme.MUTED,
                     font=theme.FONT_SMALL).pack(anchor="w")

    def destroy(self):
        import shutil
        d, self._test_dir = getattr(self, "_test_dir", None), None
        super().destroy()
        if d and "mc_sitecheck_" in str(d):
            shutil.rmtree(d, ignore_errors=True)       # the one-file-per-site samples are temporary
