"""Main window, three columns:
  left   - Find (real matches, most popular first) and Add by name; Add moves a pick to the centre
  centre - the searches to run (tag, source, quality, limit)
  right  - big preview of the latest/clicked download, and a strip of recent downloads (X deletes one)
The footer (progress, Stop, Start) is packed first so it can never be pushed out of view; Log is its own tab."""
import datetime
import os
import platform
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import theme
from core import collector, settings
from core.collector import Collection, Job, Options, Pick
from core.thumbs import make_thumb
from core.util import open_path
from sources import SOURCE_CLASSES, SOURCE_BY_ID
from ui import tiles
from ui.tooltip import add_help, tip

try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

QUALITIES = ("Any", "Good", "Best")
TYPES = (("image", "Images"), ("video", "Videos"), ("audio", "Audio"))
MIN_MATCH_SIZE = 100          # "Hide small matches" floor
STRIP_THUMB, STRIP_GAP, STRIP_MAX = 72, 6, 300
MAX_LOG_LINES = 50000
NOTICE = ("This tool collects media from public sites, several of which host adult material (18+ only).\n\n"
          "It is unofficial and for personal use. You are responsible for following each site's rules and "
          "your local laws. Requests are paced, it never bypasses logins or paywalls, and it never collects "
          "material involving minors (a built-in, non-removable filter).\n\nContinue?")


def short(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    def trim(x):
        return f"{x:.1f}".rstrip("0").rstrip(".")
    return f"{trim(n / 1_000_000)}M" if n >= 1_000_000 else f"{trim(n / 1000)}k" if n >= 10_000 else str(n)


class CollectorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Media Collector")
        self.geometry("1320x820")
        self.minsize(1080, 600)
        self.configure(bg=theme.BG)
        theme.apply_theme(self)
        ttk.Style().configure("TSpinbox", fieldbackground=theme.PANEL_BG, foreground=theme.TEXT_FG,
                              background=theme.PANEL_BG, arrowcolor=theme.CRIMSON, insertcolor=theme.TEXT_FG)
        self.cfg = settings.load()
        self.rows = {}                 # tree iid -> Pick (the searches to run)
        self.matches = []              # last Find results (unfiltered)
        self.recent = []               # newest first: {"item","pick","pil","photo"}
        self.current = None            # entry shown in the big preview
        self.log_lines = []
        self.job = None
        self.collection = None
        self._suggest_token = 0
        self._suggest_q = queue.Queue()
        self._big_photo = None
        self._resize_job = None
        self._build()
        self._log(f"Media Collector {settings.APP_VERSION} started", "debug")
        self._load_collection(self.cfg.get("last_collection") or "My collection")
        self.after(100, self._poll)
        self.after(300, self._first_run_notice)

    # ================================================================ layout
    def _build(self):
        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=12, pady=(10, 4))
        ttk.Label(top, text="Collection", font=theme.FONT_BOLD).pack(side="left")
        self.col_var = tk.StringVar()
        self.col_box = ttk.Combobox(top, textvariable=self.col_var, width=30)
        self.col_box.pack(side="left", padx=8)
        self.col_box.bind("<<ComboboxSelected>>", lambda e: self._load_collection(self.col_var.get()))
        self.col_box.bind("<Return>", lambda e: self._load_collection(self.col_var.get()))
        tip(self.col_box, "A collection is a themed folder that remembers its searches and what it has fetched. "
                          "Pick one, or type a new name and press Enter.")
        for text, cmd, hint in (("Settings", self._settings, "Collections folder and site accounts/keys."),
                                ("Export ZIP", self._export_zip, "Zip the collection's media."),
                                ("Open folder", self._open_folder, "Show this collection's files.")):
            tip(ttk.Button(top, text=text, command=cmd), hint).pack(side="right", padx=(6, 0))

        # footer first: always visible, whatever the window size
        foot = ttk.Frame(self)
        foot.pack(side="bottom", fill="x", padx=12, pady=(4, 10))
        self.progress = ttk.Progressbar(foot, mode="determinate")
        self.progress.pack(fill="x", pady=(0, 6))
        row = ttk.Frame(foot)
        row.pack(fill="x")
        self.status = ttk.Label(row, text="Ready.", style="Muted.TLabel")
        self.status.pack(side="left")
        self.start_btn = ttk.Button(row, text="Start", command=self._start)
        self.start_btn.pack(side="right")
        self.stop_btn = ttk.Button(row, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="right", padx=6)

        self.nb = ttk.Notebook(self)
        self.nb.pack(side="top", fill="both", expand=True, padx=12, pady=4)
        collect = ttk.Frame(self.nb)
        logtab = ttk.Frame(self.nb)
        self.nb.add(collect, text="Collect")
        self.nb.add(logtab, text="Log")

        pane = tk.PanedWindow(collect, orient="horizontal", bg=theme.BG, sashwidth=6, bd=0, sashrelief="flat")
        pane.pack(fill="both", expand=True, pady=(6, 0))
        left, centre, right = ttk.Frame(pane), ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, minsize=250, width=290, stretch="never")
        pane.add(centre, minsize=380, stretch="always")
        pane.add(right, minsize=300, width=400, stretch="never")
        self._build_left(left)
        self._build_centre(centre)
        self._build_right(right)
        self._build_log(logtab)

    # ---------------------------------------------------------------- left: find + add by name
    def _build_left(self, f):
        # lower controls are packed first (side=bottom) so a short window shrinks the list, not these
        nb = ttk.LabelFrame(f, text="Add by name")
        nb.pack(side="bottom", fill="x", pady=(6, 0))
        self.add_site = tk.StringVar(value=SOURCE_CLASSES[0].label)
        cb = ttk.Combobox(nb, textvariable=self.add_site, state="readonly",
                          values=[c.label for c in SOURCE_CLASSES])
        cb.pack(fill="x", padx=6, pady=(6, 2))
        cb.bind("<<ComboboxSelected>>", lambda e: self._sync_add_hint())
        rr = ttk.Frame(nb)
        rr.pack(fill="x", padx=6, pady=2)
        self.add_var = tk.StringVar()
        ent = ttk.Entry(rr, textvariable=self.add_var)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda e: self._add_named())
        ttk.Button(rr, text="Add  →", command=self._add_named).pack(side="left", padx=(6, 0))
        self.add_hint = ttk.Label(nb, text="", style="Muted.TLabel", wraplength=260)
        self.add_hint.pack(anchor="w", padx=6, pady=(0, 6))
        self._sync_add_hint()

        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", pady=4)
        ttk.Button(bar, text="Add  →", command=self._add_matches).pack(side="right")
        self.hide_small = tk.BooleanVar(value=True)
        theme.make_checkbutton(bar, f"Hide small (<{MIN_MATCH_SIZE})", self.hide_small,
                               command=self._render_matches).pack(side="left")

        ttk.Label(f, text="Find", font=theme.FONT_LABELFRAME, foreground=theme.LIGHT_VIOLET).pack(anchor="w")
        r = ttk.Frame(f)
        r.pack(fill="x", pady=(2, 2))
        self.query_var = tk.StringVar()
        self.query_entry = ttk.Entry(r, textvariable=self.query_var, font=(theme.FONT_FAMILY, 10))
        self.query_entry.pack(side="left", fill="x", expand=True, ipady=2)
        self.query_entry.bind("<Return>", lambda e: self._find())
        ttk.Button(r, text="Find", command=self._find).pack(side="left", padx=(6, 0))
        add_help(r, "Asks every site for its own real matches (subreddits, tags, communities), most popular "
                    "first. Select one or more and press Add.", side="left", padx=4)
        self.find_status = ttk.Label(f, text="Type a topic and press Find.", style="Muted.TLabel", wraplength=270)
        self.find_status.pack(anchor="w", pady=(0, 4))

        box = ttk.Frame(f)
        box.pack(fill="both", expand=True)
        self.match_tree = ttk.Treeview(box, columns=("name", "size"), show="headings", selectmode="extended",
                                       height=4)
        self.match_tree.heading("name", text="Match")
        self.match_tree.heading("size", text="Size")
        self.match_tree.column("name", width=170, minwidth=80, stretch=True)
        self.match_tree.column("size", width=56, minwidth=40, stretch=False, anchor="e")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.match_tree.yview)
        self.match_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.match_tree.pack(side="left", fill="both", expand=True)
        self.match_tree.bind("<Double-1>", lambda e: self._add_matches())
        self.match_tree.bind("<Return>", lambda e: self._add_matches())

    # ---------------------------------------------------------------- centre: searches
    def _build_centre(self, f):
        # bottom controls first, so a short window shrinks the table, not the buttons
        self.adv = ttk.Frame(f)
        self.adv.pack(side="bottom", fill="x")
        self.sort_var, self.time_var = tk.StringVar(), tk.StringVar()
        adv_row = ttk.Frame(self.adv)
        ttk.Label(adv_row, text="Sort").pack(side="left")
        ttk.Combobox(adv_row, textvariable=self.sort_var, width=14, state="readonly",
                     values=[""] + sorted({o for c in SOURCE_CLASSES for o in c.sort_options})).pack(side="left", padx=4)
        ttk.Label(adv_row, text="Time").pack(side="left", padx=(8, 0))
        ttk.Combobox(adv_row, textvariable=self.time_var, width=8, state="readonly",
                     values=[""] + sorted({o for c in SOURCE_CLASSES for o in c.time_options})).pack(side="left", padx=4)
        ttk.Label(adv_row, text="blank = from Quality", style="Muted.TLabel").pack(side="left", padx=6)
        self._adv_row = adv_row

        op = ttk.Frame(f)
        op.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Label(op, text="Type").pack(side="left")
        self.type_vars = {}
        for key, text in TYPES:
            v = tk.BooleanVar(value=key in self.cfg.get("types", ["image", "video"]))
            self.type_vars[key] = v
            theme.make_checkbutton(op, text, v).pack(side="left", padx=3)
        self.random_var = tk.BooleanVar(value=bool(self.cfg.get("randomize")))
        theme.make_checkbutton(op, "Shuffle", self.random_var).pack(side="left", padx=(10, 0))
        self.adv_var = tk.BooleanVar(value=False)

        ed2 = ttk.Frame(f)
        ed2.pack(side="bottom", fill="x", pady=(2, 0))
        ttk.Button(ed2, text="Remove selected", command=self._remove_selected).pack(side="left")
        ttk.Button(ed2, text="Clear all", style="Plus.TButton", command=self._clear_rows).pack(side="left", padx=6)
        theme.make_checkbutton(ed2, "Advanced", self.adv_var, command=self._toggle_adv).pack(side="right")

        ed = ttk.Frame(f)
        ed.pack(side="bottom", fill="x", pady=(4, 2))
        ttk.Label(ed, text="Quality").pack(side="left")
        self.quality_var = tk.StringVar(value=self.cfg.get("quality", "Good"))
        ttk.Combobox(ed, textvariable=self.quality_var, values=QUALITIES, state="readonly",
                     width=7).pack(side="left", padx=(4, 10))
        ttk.Label(ed, text="Limit").pack(side="left")
        self.limit_var = tk.IntVar(value=int(self.cfg.get("limit", 50)))
        ttk.Spinbox(ed, from_=1, to=2000, width=6, textvariable=self.limit_var).pack(side="left", padx=(4, 10))
        tip(ttk.Button(ed, text="Apply", command=self._apply_selected),
            "Apply: sets Quality and Limit on the selected searches in the list. New searches you add start with these values."
            ).pack(side="left")
        add_help(ed, "Any = everything. Good / Best = better-rated posts; each site translates it its own way "
                     "(minimum score, top of the month/year, ...).", side="left", padx=6)

        self.count_lbl = ttk.Label(f, text="", style="Muted.TLabel", wraplength=440)
        self.count_lbl.pack(side="bottom", anchor="w")

        ttk.Label(f, text="Searches to run", font=theme.FONT_LABELFRAME,
                  foreground=theme.LIGHT_VIOLET).pack(anchor="w")
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True, pady=(2, 4))
        self.tree = ttk.Treeview(box, columns=("tag", "source", "quality", "limit"), show="headings",
                                 selectmode="extended", height=4)
        for col, text, w, mw, anchor, stretch in (("tag", "Tag / name", 150, 80, "w", True),
                                                  ("source", "Source", 90, 60, "w", False),
                                                  ("quality", "Quality", 64, 50, "center", False),
                                                  ("limit", "Limit", 50, 40, "e", False)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, minwidth=mw, anchor=anchor, stretch=stretch)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Delete>", lambda e: self._remove_selected())

    # ---------------------------------------------------------------- right: preview + recent strip
    def _build_right(self, f):
        strip = ttk.Frame(f)
        strip.pack(side="bottom", fill="x", pady=(2, 0))
        self.strip = tk.Canvas(strip, height=STRIP_THUMB + 10, bg=theme.LOG_BG, highlightthickness=0)
        hs = ttk.Scrollbar(strip, orient="horizontal", command=self.strip.xview)
        self.strip.configure(xscrollcommand=hs.set)
        self.strip.pack(fill="x")
        hs.pack(fill="x")
        self.strip.bind("<Button-1>", self._on_strip_click)
        self.strip.bind("<MouseWheel>", lambda e: self.strip.xview_scroll(-1 * (e.delta // 120 or 1), "units"))
        self.strip.bind("<Button-4>", lambda e: self.strip.xview_scroll(-2, "units"))
        self.strip.bind("<Button-5>", lambda e: self.strip.xview_scroll(2, "units"))
        ttk.Label(f, text="Recent downloads (click to view, ✕ to delete)",
                  style="Muted.TLabel").pack(side="bottom", anchor="w")
        self.caption = ttk.Label(f, text="Downloads appear here.", style="Muted.TLabel", wraplength=380)
        self.caption.pack(side="bottom", anchor="w", pady=(4, 2))
        self.big = tk.Canvas(f, bg=theme.LOG_BG, highlightthickness=1, highlightbackground=theme.PANEL_BG)
        self.big.pack(side="top", fill="both", expand=True)
        self.big.bind("<Configure>", lambda e: self._schedule_redraw())

    # ---------------------------------------------------------------- log tab
    def _build_log(self, f):
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(6, 4))
        ttk.Button(bar, text="Export log", command=self._export_log).pack(side="left")
        ttk.Button(bar, text="Clear", style="Plus.TButton", command=self._clear_log).pack(side="left", padx=6)
        ttk.Label(bar, text="Verbose, for bug fixing. API keys are never written to it.",
                  style="Muted.TLabel").pack(side="left", padx=8)
        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True)
        self.log = tk.Text(wrap, bg=theme.LOG_BG, fg=theme.TEXT_FG, insertbackground=theme.TEXT_FG,
                           font=("Consolas", 9), relief="flat", wrap="none", state="disabled")
        ys = ttk.Scrollbar(wrap, orient="vertical", command=self.log.yview)
        xs = ttk.Scrollbar(f, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        xs.pack(fill="x")
        self.log.tag_config("error", foreground=theme.CRIMSON)
        self.log.tag_config("warning", foreground=theme.LIGHT_VIOLET)
        self.log.tag_config("debug", foreground=theme.MUTED)

    def _log(self, msg, level="info"):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"{stamp} [{level.upper():7}] {msg}"
        self.log_lines.append(line)
        if len(self.log_lines) > MAX_LOG_LINES:
            del self.log_lines[:MAX_LOG_LINES // 10]
        self.log.config(state="normal")
        self.log.insert("end", line + "\n", level)
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear_log(self):
        self.log_lines.clear()
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _export_log(self):
        dest = filedialog.asksaveasfilename(
            parent=self, defaultextension=".txt", filetypes=[("Text file", "*.txt")],
            initialfile=f"media-collector-log-{datetime.datetime.now():%Y%m%d-%H%M%S}.txt")
        if not dest:
            return
        creds = sorted(f"{s}.{k}" for s, d in settings.credentials_for(self.cfg).items() for k in d)
        head = [f"Media Collector {settings.APP_VERSION}",
                f"Python {sys.version.split()[0]} on {platform.platform()}",
                f"Pillow: {'yes' if HAVE_PIL else 'NO'}   ffmpeg: {'yes' if _ffmpeg() else 'no'}",
                f"Collection: {self.collection.name}   searches: {len(self.rows)}",
                f"Credential fields set (values hidden): {', '.join(creds) or 'none'}",
                "-" * 60]
        try:
            with open(dest, "w", encoding="utf-8") as f:
                f.write("\n".join(head + self.log_lines) + "\n")
            self._status(f"Log saved to {dest}")
        except OSError as ex:
            messagebox.showerror("Export failed", str(ex), parent=self)

    # ================================================================ small helpers
    def _status(self, text):
        self.status.config(text=text)

    def _toggle_adv(self):
        if self.adv_var.get():
            self._adv_row.pack(fill="x", pady=(4, 0))
        else:
            self._adv_row.pack_forget()

    def _sync_add_hint(self):
        cls = next((c for c in SOURCE_CLASSES if c.label == self.add_site.get()), None)
        self.add_hint.config(text=(cls.query_hint if cls else ""))

    def _first_run_notice(self):
        if self.cfg.get("accepted_notice"):
            return
        if messagebox.askyesno("Before you start", NOTICE, parent=self):
            self.cfg["accepted_notice"] = True
            settings.save(self.cfg)
        else:
            self.destroy()

    # ================================================================ collections
    def _collection_names(self):
        root = self.cfg["output_dir"]
        try:
            return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
        except OSError:
            return []

    def _busy(self):
        return bool(self.job and self.job.thread and self.job.thread.is_alive())

    def _load_collection(self, name):
        name = (name or "").strip() or "My collection"
        if self._busy():
            messagebox.showinfo("Busy", "Stop the current run before switching collections.", parent=self)
            self.col_var.set(self.collection.name if self.collection else name)
            return
        self.collection = Collection(self.cfg["output_dir"], name)
        self.col_var.set(name)
        self.cfg["last_collection"] = name
        names = self._collection_names()
        self.col_box.config(values=names if name in names else names + [name])
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        for p in self.collection.picks:
            self._insert_row(p)
        self.recent.clear()
        self._show(None)
        self._draw_strip()
        self._update_count()
        self._log(f"collection '{name}' loaded from {self.collection.dir}: {len(self.rows)} saved search(es), "
                  f"{len(self.collection.seen)} remembered item(s)", "debug")
        self._status(f"Collection '{name}': {len(self.collection.seen)} item(s) remembered.")

    def _persist_picks(self):
        self.collection.picks = list(self.rows.values())
        try:
            self.collection.save()
        except OSError as ex:
            self._log(f"couldn't save searches: {ex}", "error")

    def _open_folder(self):
        os.makedirs(self.collection.dir, exist_ok=True)
        open_path(self.collection.dir)

    def _export_zip(self):
        dest = filedialog.asksaveasfilename(parent=self, defaultextension=".zip",
                                            initialfile=f"{self.collection.name}.zip",
                                            filetypes=[("ZIP archive", "*.zip")])
        if not dest:
            return
        try:
            n = self.collection.export_zip(dest)
            self._status(f"Exported {n} file(s) to {dest}")
            self._log(f"exported {n} file(s) to {dest}", "debug")
        except OSError as ex:
            messagebox.showerror("Export failed", str(ex), parent=self)

    def _settings(self):
        SettingsDialog(self, self.cfg, on_save=self._settings_saved)

    def _settings_saved(self):
        settings.save(self.cfg)
        self._log("settings saved", "debug")
        self._load_collection(self.collection.name)

    # ================================================================ left column logic
    def _find(self):
        q = self.query_var.get().strip()
        if not q:
            return
        self._suggest_token += 1
        token = self._suggest_token
        self.find_status.config(text=f"Asking {len(SOURCE_CLASSES)} sites for matches to '{q}'...")
        self._log(f"find '{q}' (asking {len(SOURCE_CLASSES)} sites)", "debug")

        def work():
            self._suggest_q.put((token, q, collector.suggest_all(q)))
        threading.Thread(target=work, daemon=True).start()

    def _show_matches(self, token, q, found):
        if token != self._suggest_token:
            return
        self.matches = found
        per = {}
        for m in found:
            per[m["site"]] = per.get(m["site"], 0) + 1
        self._log(f"find '{q}': {len(found)} match(es): " + ", ".join(f"{k}={v}" for k, v in sorted(per.items())),
                  "debug")
        self._render_matches()

    def _render_matches(self):
        self.match_tree.delete(*self.match_tree.get_children())
        shown = 0
        for i, m in enumerate(self.matches):
            if self.hide_small.get() and m["count"] is not None and m["count"] < MIN_MATCH_SIZE:
                continue
            self.match_tree.insert("", "end", iid=str(i), values=(m["label"], short(m["count"])))
            shown += 1
        hidden = len(self.matches) - shown
        if not self.matches:
            self.find_status.config(text="No matches. Some sites have no search: use Add by name below.")
        else:
            self.find_status.config(text=f"{shown} match(es), most popular first"
                                         + (f" ({hidden} small hidden)." if hidden else "."))

    def _new_pick(self, source_id, value, label):
        return Pick(source_id, value, label, self.quality_var.get(), self._limit())

    def _limit(self):
        try:
            return max(1, int(self.limit_var.get()))
        except (tk.TclError, ValueError):
            return 50

    def _add_matches(self):
        for iid in self.match_tree.selection():
            m = self.matches[int(iid)]
            self._add_pick(self._new_pick(m["source"], m["value"], m["label"]))

    def _add_named(self):
        label, value = self.add_site.get(), self.add_var.get().strip()
        cls = next((c for c in SOURCE_CLASSES if c.label == label), None)
        if not cls or not value:
            return
        self._add_pick(self._new_pick(cls.id, value, f"{cls.label} {value}"))
        self.add_var.set("")

    # ================================================================ centre column logic
    def _iid(self, pick):
        return f"{pick.source_id}|{pick.value.strip().lower()}"

    def _insert_row(self, pick):
        cls = SOURCE_BY_ID.get(pick.source_id)
        iid = self._iid(pick)
        if iid in self.rows:
            return False
        self.rows[iid] = pick
        self.tree.insert("", "end", iid=iid, values=(pick.value, cls.label if cls else pick.source_id,
                                                      pick.quality or "Good", pick.limit or self._limit()))
        return True

    def _add_pick(self, pick):
        if self._insert_row(pick):
            self._log(f"added search {pick.source_id}:{pick.value} quality={pick.quality} limit={pick.limit}",
                      "debug")
            self._persist_picks()
            self._update_count()
        else:
            self._status(f"'{pick.value}' is already in the list.")

    def _apply_selected(self):
        q, lim = self.quality_var.get(), self._limit()
        for iid in self.tree.selection():
            p = self.rows[iid]
            p.quality, p.limit = q, lim
            self.tree.set(iid, "quality", q)
            self.tree.set(iid, "limit", lim)
        self._persist_picks()

    def _remove_selected(self):
        for iid in self.tree.selection():
            self.rows.pop(iid, None)
            self.tree.delete(iid)
        self._persist_picks()
        self._update_count()

    def _clear_rows(self):
        if self.rows and messagebox.askyesno("Clear all", "Remove every search from the list?\n"
                                             "(Downloaded files stay.)", parent=self):
            self.rows.clear()
            self.tree.delete(*self.tree.get_children())
            self._persist_picks()
            self._update_count()

    def _update_count(self):
        n = len(self.rows)
        self.count_lbl.config(text=(f"{n} search(es). Select rows and press Remove, or Delete key." if n else
                                    "Nothing here yet: Find a topic on the left, select matches, press Add →"))

    # ================================================================ running
    def _start(self):
        picks = list(self.rows.values())
        if not picks:
            messagebox.showinfo("Nothing to run", "Add at least one search first: Find a topic and press Add →, "
                                "or use Add by name.", parent=self)
            return
        types = {k for k, v in self.type_vars.items() if v.get()}
        if not types:
            messagebox.showinfo("No type chosen", "Tick Images, Videos, or Audio.", parent=self)
            return
        default_limit = self._limit()
        self.cfg.update(limit=default_limit, quality=self.quality_var.get(), types=sorted(types),
                        randomize=self.random_var.get())
        settings.save(self.cfg)
        opts = Options(limit=default_limit, quality=self.quality_var.get(), types=types,
                       randomize=self.random_var.get(), sort=self.sort_var.get(), time_range=self.time_var.get())
        self._limits = {self._iid(p): (p.limit or default_limit) for p in picks}
        self._done_total = 0
        self.progress.config(value=0, maximum=max(1, sum(self._limits.values())))
        self.job = Job(self.collection, picks, opts, settings.credentials_for(self.cfg))
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._status(f"Running {len(picks)} search(es)...")
        self._log(f"RUN {len(picks)} search(es), types={sorted(types)}, default limit={default_limit}", "debug")
        self.job.start()

    def _stop(self):
        if self.job:
            self.job.stop()
            self._status("Stopping after the current download...")
            self._log("stop requested", "debug")

    def _poll(self):
        try:
            while True:
                self._show_matches(*self._suggest_q.get_nowait())
        except queue.Empty:
            pass
        try:
            for _ in range(80):
                if not self.job:
                    break
                self._handle(self.job.events.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _handle(self, ev):
        kind = ev[0]
        if kind == "log":
            self._log(ev[1], ev[2])
        elif kind == "progress":
            self._status(f"{ev[3]} ({ev[1]})")
        elif kind == "item":
            self._add_recent(ev[1], ev[2], ev[3])
            self.progress.step(1)
        elif kind == "pick_done":
            _, pick, count, status, detail = ev
            self._done_total += self._limits.get(self._iid(pick), 0)
            self.progress.config(value=max(self.progress["value"], min(self._done_total, self.progress["maximum"])))
            self._log(f"DONE {pick.label or pick.value}: {status}" + (f" - {detail}" if detail else f" ({count} new)"),
                      "error" if status == "failed" else "info")
        elif kind == "done":
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.progress.config(value=self.progress["maximum"])
            self._status(f"{'Stopped' if ev[2] else 'Finished'}: {ev[1]} new item(s).")
            self._log(f"RUN {'stopped' if ev[2] else 'finished'}: {ev[1]} new item(s)", "debug")

    # ================================================================ right column: preview + strip
    def _add_recent(self, pick, item, pil):
        self.recent.insert(0, {"item": item, "pick": pick, "pil": pil, "photo": None})
        del self.recent[STRIP_MAX:]
        self._draw_strip()
        self.strip.xview_moveto(0)
        self._show(self.recent[0])

    def _schedule_redraw(self):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(80, lambda: self._show(self.current))

    def _show(self, entry):
        self.current = entry
        c = self.big
        c.delete("all")
        w, h = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        if entry is None:
            c.create_text(w // 2, h // 2, text="Downloads appear here", fill=theme.MUTED, font=theme.FONT_NORMAL)
            self.caption.config(text="Downloads appear here.")
            self._draw_strip()
            return
        item = entry["item"]
        photo = None
        if HAVE_PIL:
            try:
                if item.media_type == "image":
                    with Image.open(item.file_path) as im:
                        im = im.convert("RGB")
                        im.thumbnail((w - 8, h - 8))
                        photo = ImageTk.PhotoImage(im)
                elif item.media_type == "video":
                    pil = make_thumb(item.file_path, "video", size=max(w, h))
                    photo = tiles.photo(pil, "video", w - 8, h - 8)
                else:
                    photo = tiles.photo(None, item.media_type, min(w, h) - 8, min(w, h) - 8)
            except Exception as ex:
                self._log(f"preview failed for {item.file_path}: {type(ex).__name__}: {ex}", "warning")
        self._big_photo = photo
        if photo:
            c.create_image(w // 2, h // 2, image=photo)
        else:
            c.create_text(w // 2, h // 2, text=f"{item.media_type}\n(no preview)", fill=theme.LIGHT_VIOLET)
        self.caption.config(text=f"{entry['pick'].label or entry['pick'].value}  ·  {os.path.basename(item.file_path)}"
                                 f"  ·  {item.media_type}")
        self._draw_strip()

    def _draw_strip(self):
        c, T, G = self.strip, STRIP_THUMB, STRIP_GAP
        c.delete("all")
        for i, e in enumerate(self.recent):
            x, y = G + i * (T + G), 5
            sel = e is self.current
            c.create_rectangle(x, y, x + T, y + T, fill=theme.PANEL_BG,
                               outline=theme.VIOLET if sel else theme.PANEL_BG, width=3 if sel else 1)
            if e["photo"] is None:
                e["photo"] = tiles.photo(e["pil"], e["item"].media_type, T - 4, T - 4)
            if e["photo"]:
                c.create_image(x + T // 2, y + T // 2, image=e["photo"])
            c.create_rectangle(x + T - 18, y, x + T, y + 18, fill=theme.CRIMSON, outline="")
            c.create_text(x + T - 9, y + 9, text="✕", fill=theme.BTN_FG, font=(theme.FONT_FAMILY, 9, "bold"))
        c.configure(scrollregion=(0, 0, G + len(self.recent) * (T + G), T + 10))

    def _on_strip_click(self, ev):
        T, G = STRIP_THUMB, STRIP_GAP
        cx, cy = self.strip.canvasx(ev.x), self.strip.canvasy(ev.y)
        i = int((cx - G) // (T + G))
        if i < 0 or i >= len(self.recent) or not (G + i * (T + G) <= cx <= G + i * (T + G) + T) or cy < 5 or cy > 5 + T:
            return
        x0 = G + i * (T + G)
        if cx >= x0 + T - 18 and cy <= 5 + 18:
            self._delete_recent(i)
        else:
            self._show(self.recent[i])

    def _delete_recent(self, i):
        e = self.recent.pop(i)
        self.collection.reject(e["item"].post_id, e["item"].file_path)   # deletes the file; never fetched again
        try:
            self.collection.save()
        except OSError as ex:
            self._log(f"couldn't save collection: {ex}", "error")
        self._log(f"deleted {e['item'].post_id} ({os.path.basename(e['item'].file_path)}); won't be fetched again",
                  "debug")
        if e is self.current:
            self._show(self.recent[min(i, len(self.recent) - 1)] if self.recent else None)
        else:
            self._draw_strip()
        self._status("Deleted. It won't be fetched again.")


def _ffmpeg():
    from core.thumbs import FFMPEG_AVAILABLE
    return FFMPEG_AVAILABLE


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.configure(bg=theme.BG)
        self.transient(parent)
        self.cfg, self.on_save, self.vars = cfg, on_save, {}
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=14, pady=12)
        r = ttk.Frame(body)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text="Collections folder", width=22).pack(side="left")
        self.out_var = tk.StringVar(value=cfg["output_dir"])
        ttk.Entry(r, textvariable=self.out_var, width=40).pack(side="left")
        ttk.Button(r, text="Browse", command=self._browse).pack(side="left", padx=6)
        ttk.Label(body, text="Accounts and keys are all optional unless noted. Stored only in "
                             "collector_settings.json next to the program.", style="Muted.TLabel",
                  wraplength=560).pack(anchor="w", pady=(8, 2))
        for site, arg, label, hint in settings.CRED_FIELDS:
            r = ttk.Frame(body)
            r.pack(fill="x", pady=2)
            ttk.Label(r, text=label, width=22).pack(side="left")
            var = tk.StringVar(value=str((cfg["credentials"].get(site) or {}).get(arg, "")))
            self.vars[(site, arg)] = var
            ttk.Entry(r, textvariable=var, width=40,
                      show="" if arg in ("user_id", "base_url", "instance") else "•").pack(side="left")
            add_help(r, hint, side="left", padx=8)
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="Save", command=self._save).pack(side="right")
        ttk.Button(row, text="Cancel", style="Plus.TButton", command=self.destroy).pack(side="right", padx=6)
        self.grab_set()

    def _browse(self):
        d = filedialog.askdirectory(parent=self, initialdir=self.out_var.get())
        if d:
            self.out_var.set(d)

    def _save(self):
        self.cfg["output_dir"] = self.out_var.get().strip() or self.cfg["output_dir"]
        creds = dict(self.cfg.get("credentials") or {})      # keep fields for sites not shown (e.g. disabled ones)
        for (site, arg), var in self.vars.items():
            creds.setdefault(site, {})[arg] = var.get().strip()
        self.cfg["credentials"] = creds
        self.on_save()
        self.destroy()


def main():
    CollectorApp().mainloop()
