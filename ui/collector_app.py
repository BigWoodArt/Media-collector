"""Main window, three columns:
  left   - Find (real matches, most popular first) and the Add box, which adapts to the chosen site
  centre - the searches to run (status, site, query, sort, limit, options)
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
from core.query_clean import clean_query
from core.thumbs import make_thumb
from core.util import open_path, safe_name
from sources import SOURCE_CLASSES, SOURCE_BY_ID
from ui import tiles
from ui.test_results import TestResultsWindow
from ui.tooltip import add_help, tip

try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

TYPES = (("image", "Images"), ("video", "Videos"), ("audio", "Audio"))
MIN_MATCH_SIZE = 100          # "Hide small matches" floor
STRIP_THUMB, STRIP_GAP, STRIP_MAX = 72, 6, 300
MAX_LOG_LINES = 50000
NOTICE = ("This tool collects media from public sites, several of which host adult material (18+ only).\n\n"
          "It is unofficial and for personal use. You are responsible for following each site's rules and "
          "your local laws. Requests are paced, it never bypasses logins or paywalls, and it never collects "
          "material involving minors (a built-in, non-removable filter).\n\nContinue?")


def _size(n):
    n = float(n or 0)
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{n / 1024:.0f} KB"


def status_text(p, running=False):
    if running:
        return "⏳ running"
    return {"": "● new", "done": f"✓ done ({p.kept})", "empty": "∅ empty - retry", "failed": "✗ failed - retry",
            "stopped": "⏸ stopped"}.get(p.status, p.status)


def status_tag(p, running=False):
    if running:
        return "run"
    return {"done": "ok", "empty": "bad", "failed": "bad", "stopped": "bad"}.get(p.status, "")


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
        self.title(f"Media Collector v{settings.APP_VERSION}")
        self.geometry("1320x820")
        self.minsize(1080, 600)
        self.configure(bg=theme.BG)
        theme.apply_theme(self)
        ttk.Style().configure("TSpinbox", fieldbackground=theme.PANEL_BG, foreground=theme.TEXT_FG,
                              background=theme.PANEL_BG, arrowcolor=theme.CRIMSON, insertcolor=theme.TEXT_FG)
        self.cfg = settings.load()
        self._running_iid = None
        self._wait_what = ""
        self._limits = {}
        self._done_total = 0
        self.rows = {}                 # tree iid -> Pick (the searches to run)
        self.matches = []              # last Find results (unfiltered)
        self.recent = []               # newest first: {"item","pick","pil","photo"}
        self.current = None            # entry shown in the big preview
        self.log_lines = []
        self.job = None
        self.collection = None
        self._suggest_token = 0
        self._suggest_q = queue.Queue()
        self._check_q = queue.Queue()
        self._check_stop = None
        self._big_photo = None
        self._resize_job = None
        self._build()
        self._log(f"Media Collector v{settings.APP_VERSION} started", "debug")
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
        self.check_btn = tip(ttk.Button(top, text="Check all sites", command=self._check_sites),
                             "One tiny search per site: shows which sources are live right now.")
        self.check_btn.pack(side="right", padx=(6, 0))
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
        self._foot_row = row
        self.status = ttk.Label(row, text="Ready.", style="Muted.TLabel")
        self.status.pack(side="left")
        # red flashing dot + note while a site's own rate limit makes us wait (so it's clear it isn't the program)
        self.wait_lbl = ttk.Label(row, text="", foreground=theme.CRIMSON)
        self.wait_dot = tk.Canvas(row, width=14, height=14, bg=theme.BG, highlightthickness=0)
        self.wait_dot.create_oval(2, 2, 12, 12, fill=theme.CRIMSON, outline="", tags="dot")
        self._wait_until, self._wait_on = 0.0, False
        self.after(500, self._flash_wait)
        self.start_btn = ttk.Button(row, text="Start", command=self._start)
        self.start_btn.pack(side="right")
        self.stop_btn = ttk.Button(row, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="right", padx=6)
        self.skip_btn = tip(ttk.Button(row, text="Skip file", command=self._skip, state="disabled"),
                            "Abandon the file that is downloading right now and carry on with the next one.")
        self.skip_btn.pack(side="right")
        # current-file progress sits inline on this line (fixed width, so nothing shifts when it appears)
        self.dl_lbl = ttk.Label(row, text="", style="Muted.TLabel", width=46, anchor="e")
        self.dl_lbl.pack(side="right", padx=(0, 10))

        self.nb = ttk.Notebook(self)
        self.nb.pack(side="top", fill="both", expand=True, padx=12, pady=4)
        collect = ttk.Frame(self.nb)
        logtab = ttk.Frame(self.nb)
        self.nb.add(collect, text="Collect")
        self.nb.add(logtab, text="Log")

        pane = tk.PanedWindow(collect, orient="horizontal", bg=theme.BG, sashwidth=6, bd=0, sashrelief="flat")
        pane.pack(fill="both", expand=True, pady=(6, 0))
        left, centre, right = ttk.Frame(pane), ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, minsize=290, width=330, stretch="never")
        pane.add(centre, minsize=420, stretch="always")
        pane.add(right, minsize=240, width=330, stretch="never")
        self._build_left(left)
        self._build_centre(centre)
        self._build_right(right)
        self._build_log(logtab)

    # ---------------------------------------------------------------- left: find + add by name
    def _build_left(self, f):
        # the Add box is packed first (side=bottom) so a short window shrinks the Find list, not the form
        nb = ttk.LabelFrame(f, text=" Add search ")
        nb.pack(side="bottom", fill="x", pady=(6, 0))
        self._build_add_form(nb)

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
                    "first. Select one or more and press Add →. They use the Limit and Type values below.",
                 side="left", padx=4)
        self.find_status = ttk.Label(f, text="Type a topic and press Find.", style="Muted.TLabel", wraplength=300)
        self.find_status.pack(anchor="w", pady=(0, 4))

        box = ttk.Frame(f)
        box.pack(fill="both", expand=True)
        self.match_tree = ttk.Treeview(box, columns=("name", "size"), show="headings", selectmode="extended",
                                       height=3)
        self.match_tree.heading("name", text="Match")
        self.match_tree.heading("size", text="Size")
        self.match_tree.column("name", width=200, minwidth=80, stretch=True)
        self.match_tree.column("size", width=56, minwidth=40, stretch=False, anchor="e")
        sb = ttk.Scrollbar(box, orient="vertical", command=self.match_tree.yview)
        self.match_tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.match_tree.pack(side="left", fill="both", expand=True)
        self.match_tree.bind("<Double-1>", lambda e: self._add_matches())
        self.match_tree.bind("<Return>", lambda e: self._add_matches())

    def _build_add_form(self, nb):
        """Site-adaptive: Sort choices, Min score, Random/Prioritize and the default Limit follow the site."""
        self.edit_iid = None
        self._ph = False
        self._last_default_limit = ""
        r1 = ttk.Frame(nb)
        r1.pack(fill="x", padx=6, pady=(6, 2))
        self.add_site = tk.StringVar(value=SOURCE_CLASSES[0].label)
        cb = ttk.Combobox(r1, textvariable=self.add_site, state="readonly", values=[c.label for c in SOURCE_CLASSES])
        cb.pack(fill="x")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_site_change())
        self.add_entry = ttk.Entry(nb)
        self.add_entry.pack(fill="x", padx=6, pady=2)
        self.add_entry.bind("<FocusIn>", self._q_focus_in)
        self.add_entry.bind("<FocusOut>", self._q_focus_out)
        self.add_entry.bind("<<Paste>>", lambda e: self.after_idle(self._q_clean))
        self.add_entry.bind("<Return>", lambda e: self._submit())

        r2 = ttk.Frame(nb)
        r2.pack(fill="x", padx=6, pady=2)
        ttk.Label(r2, text="Sort").pack(side="left")
        self.order_cb = ttk.Combobox(r2, state="readonly", width=16)
        self.order_cb.pack(side="left", padx=(4, 2), fill="x", expand=True)
        self.order_help = add_help(r2, "", side="left", padx=(0, 2))
        self.min_frame = ttk.Frame(nb)           # only for sites with a minimum-score choice (boorus)
        ttk.Label(self.min_frame, text="Min score").pack(side="left")
        self.min_cb = ttk.Combobox(self.min_frame, state="readonly", width=8)
        self.min_cb.pack(side="left", padx=4)

        self.r3 = ttk.Frame(nb)
        self.r3.pack(fill="x", padx=6, pady=2)
        ttk.Label(self.r3, text="Limit").pack(side="left")
        self.limit_var = tk.StringVar(value="")      # follows each site's default until you change it
        ttk.Spinbox(self.r3, from_=1, to=2000, width=5, textvariable=self.limit_var).pack(side="left", padx=(4, 8))
        self.r3b = ttk.Frame(nb)
        self.r3b.pack(fill="x", padx=6, pady=2)
        ttk.Label(self.r3b, text="Type").pack(side="left")
        self.type_vars = {}
        for key, text in TYPES:
            v = tk.BooleanVar(value=key in self.cfg.get("types", ["image", "video"]))
            self.type_vars[key] = v
            theme.make_checkbutton(self.r3b, text, v).pack(side="left", padx=(6, 0))

        self.r4 = ttk.Frame(nb)
        self.r4.pack(fill="x", padx=6, pady=2)
        self.random_var = tk.BooleanVar(value=False)
        self.random_check = theme.make_checkbutton(self.r4, "Random", self.random_var)
        self.random_check.pack(side="left")
        self.prio_var = tk.BooleanVar(value=False)
        self.prio_check = theme.make_checkbutton(self.r4, "Prioritize images", self.prio_var)

        r5 = ttk.Frame(nb)
        r5.pack(fill="x", padx=6, pady=(4, 2))
        self.submit_btn = ttk.Button(r5, text="Add  →", command=self._submit)
        self.submit_btn.pack(side="left")
        self.cancel_btn = ttk.Button(r5, text="Cancel edit", style="Plus.TButton", command=self._cancel_edit)
        self.add_hint = ttk.Label(nb, text="", style="Muted.TLabel", wraplength=300)
        self.add_hint.pack(anchor="w", padx=6, pady=(0, 6))
        self._on_site_change()

    # ---- form helpers
    def _cls(self):
        return next((c for c in SOURCE_CLASSES if c.label == self.add_site.get()), SOURCE_CLASSES[0])

    @staticmethod
    def _key(label, choices):
        return next((k for k, lab, _ in choices if lab == label), "")

    @staticmethod
    def _label(key, choices):
        return next((lab for k, lab, _ in choices if k == key), choices[0][1] if choices else "-")

    def _on_site_change(self):
        cls = self._cls()
        if self._ph or not self.add_entry.get().strip():
            self._ph = False
            self.add_entry.delete(0, "end")
            self._apply_placeholder()
        self.order_cb["values"] = [lab for _, lab, _ in cls.order_choices]
        if cls.order_choices:
            self.order_cb.config(state="readonly")
            self.order_cb.set(self._label(cls.default_order, cls.order_choices))
        else:
            self.order_cb.config(state="disabled")
            self.order_cb.set("-")
        self.order_help.tooltip.text = cls.order_help
        self.min_frame.pack_forget()
        if cls.min_score_choices:
            self.min_frame.pack(fill="x", padx=6, pady=2, before=self.r3)
            self.min_cb["values"] = [lab for _, lab, _ in cls.min_score_choices]
            self.min_cb.set(self._label("", cls.min_score_choices))
        self.prio_check.pack_forget()
        if cls.has_media_priority:
            self.prio_check.pack(side="left", padx=(8, 0))
        self.random_var.set(bool(getattr(cls, "default_randomize", False)))
        self.prio_check.config(text=f"Prioritize {cls.priority_media}s")
        self.prio_var.set(bool(cls.default_prioritize))
        default = str(cls.default_limit)
        if self.limit_var.get().strip() in ("", self._last_default_limit):
            self.limit_var.set(default)
        self._last_default_limit = default
        self.add_hint.config(text=f"{cls.label}: {cls.query_hint}")

    def _apply_placeholder(self):
        if not self.add_entry.get().strip():
            self.add_entry.insert(0, self._cls().query_hint)
            self.add_entry.configure(style="Placeholder.TEntry")
            self._ph = True

    def _q_focus_in(self, _=None):
        if self._ph:
            self.add_entry.delete(0, "end")
            self.add_entry.configure(style="TEntry")
            self._ph = False

    def _q_focus_out(self, _=None):
        self._q_clean()
        if not self.add_entry.get().strip():
            self._apply_placeholder()

    def _q_clean(self):
        if self._ph:
            return
        text = self.add_entry.get()
        cleaned = clean_query(self._cls().id, text)
        if cleaned != text.strip():
            self.add_entry.delete(0, "end")
            self.add_entry.insert(0, cleaned)

    def _set_query(self, text):
        self._ph = False
        self.add_entry.configure(style="TEntry")
        self.add_entry.delete(0, "end")
        self.add_entry.insert(0, text)

    def _limit(self):
        try:
            return max(1, int(self.limit_var.get()))
        except (tk.TclError, ValueError):
            return self._cls().default_limit

    def _types(self):
        return ",".join(k for k, _ in TYPES if self.type_vars[k].get())

    # ---------------------------------------------------------------- centre: searches
    def _build_centre(self, f):
        # bottom controls first, so a short window shrinks the table, not the buttons
        self.count_lbl = ttk.Label(f, text="", style="Muted.TLabel", wraplength=560)
        self.count_lbl.pack(side="bottom", anchor="w")
        ed = ttk.Frame(f)
        ed.pack(side="bottom", fill="x", pady=(4, 2))
        for text, cmd, style in (("Edit", self._edit_selected, None), ("Remove", self._remove_selected, "Plus.TButton"),
                                 ("Clear all", self._clear_rows, "Plus.TButton"), ("Re-run", self._rerun_selected, "Plus.TButton")):
            b = ttk.Button(ed, text=text, command=cmd, **({"style": style} if style else {}))
            b.pack(side="left", padx=(0, 6))

        ttk.Label(f, text="Searches to run", font=theme.FONT_LABELFRAME,
                  foreground=theme.LIGHT_VIOLET).pack(anchor="w")
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True, pady=(2, 4))
        cols = (("status", "Status", 100, 70, False), ("site", "Site", 70, 50, False),
                ("query", "Query", 110, 60, True), ("sort", "Sort", 120, 60, False),
                ("limit", "Limit", 40, 32, False), ("opts", "Options", 80, 40, False))
        self.tree = ttk.Treeview(box, columns=[c[0] for c in cols], show="headings", selectmode="extended", height=4)
        for key, title, w, mw, stretch in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=w, minwidth=mw, anchor="e" if key == "limit" else "w", stretch=stretch)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("ok", foreground=theme.LIGHT_VIOLET)
        self.tree.tag_configure("bad", foreground="#ff6b81")
        self.tree.tag_configure("run", foreground="#e0b84a")
        self.tree.bind("<Delete>", lambda e: self._remove_selected())
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())
        self.tree.bind("<Button-3>", self._context_menu)
        self.menu = tk.Menu(self, tearoff=0, bg=theme.PANEL_BG, fg=theme.TEXT_FG,
                            activebackground=theme.VIOLET, activeforeground=theme.BTN_FG)
        self.menu.add_command(label="Edit", command=self._edit_selected)
        self.menu.add_command(label="Re-run", command=self._rerun_selected)
        self.menu.add_command(label="Open folder", command=self._open_pick_folder)
        self.menu.add_separator()
        self.menu.add_command(label="Remove", command=self._remove_selected)

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
        head = [f"Media Collector v{settings.APP_VERSION}",
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

        reports = []

        def work():
            found = collector.suggest_all(q, report=lambda site, n, secs: reports.append((site, n, secs)))
            self._suggest_q.put((token, q, found, reports))
        threading.Thread(target=work, daemon=True).start()

    def _show_matches(self, token, q, found, reports=()):
        if token != self._suggest_token:
            return
        self.matches = found
        per = {}
        for m in found:
            per[m["site"]] = per.get(m["site"], 0) + 1
        self._log(f"find '{q}': {len(found)} match(es): " + ", ".join(f"{k}={v}" for k, v in sorted(per.items())),
                  "debug")
        for site, n, secs in sorted(reports):
            self._log(f"find '{q}': {site} lookup -> {n} result(s) in {secs}s", "debug")
        self._silent = sorted(site for site, n, _ in reports if n == 0)
        self._render_matches()

    def _render_matches(self):
        self.match_tree.delete(*self.match_tree.get_children())
        shown = 0
        for i, m in enumerate(self.matches):
            if (self.hide_small.get() and m["count"] is not None and m["count"] < MIN_MATCH_SIZE
                    and not m.get("nofilter")):
                continue
            self.match_tree.insert("", "end", iid=str(i), values=(m["label"], short(m["count"])))
            shown += 1
        hidden = len(self.matches) - shown
        silent = getattr(self, "_silent", [])
        note = f" No answer from: {', '.join(silent)} (see Log)." if silent else ""
        if not self.matches:
            self.find_status.config(text="No matches. Some sites have no lookup: use the Add search box." + note)
        else:
            self.find_status.config(text=f"{shown} match(es), most popular first"
                                         + (f" ({hidden} small hidden)." if hidden else ".") + note)

    def _new_pick(self, source_id, value, label):
        """A pick from Find: Limit and Type come from the form; Sort/Min score only when it is the form's own site."""
        cls = SOURCE_BY_ID[source_id]
        p = Pick(source_id, value, label, limit=self._limit(), types=self._types(),
                 randomize=bool(getattr(cls, "default_randomize", False)), prioritize=bool(cls.default_prioritize))
        if cls is self._cls():
            p.order = self._key(self.order_cb.get(), cls.order_choices)
            p.min_score = self._key(self.min_cb.get(), cls.min_score_choices)
            p.randomize = self.random_var.get()
            p.prioritize = self.prio_var.get() if cls.has_media_priority else False
        return p

    def _add_matches(self):
        if not self._types():
            messagebox.showinfo("No type chosen", "Tick Images, Videos or Audio in the Add search box.", parent=self)
            return
        for iid in self.match_tree.selection():
            m = self.matches[int(iid)]
            self._add_pick(self._new_pick(m["source"], m["value"], m["label"]))

    def _submit(self):
        """Add button: reads every box in the form (no separate Apply step)."""
        cls = self._cls()
        self._q_clean()
        value = "" if self._ph else self.add_entry.get().strip()
        if not value:
            messagebox.showinfo("Query needed", f"Type something to search for ({cls.query_hint}).", parent=self)
            return
        if not self._types():
            messagebox.showinfo("No type chosen", "Tick Images, Videos or Audio.", parent=self)
            return
        pick = Pick(cls.id, value, f"{cls.label} {value}",
                    order=self._key(self.order_cb.get(), cls.order_choices),
                    min_score=self._key(self.min_cb.get(), cls.min_score_choices),
                    limit=self._limit(), types=self._types(), randomize=self.random_var.get(),
                    prioritize=self.prio_var.get() if cls.has_media_priority else False)
        self.cfg.update(limit=pick.limit, types=pick.types.split(","))
        if self.edit_iid:
            old = self.rows.get(self.edit_iid)
            new_iid = self._iid(pick)
            if new_iid != self.edit_iid and new_iid in self.rows:
                self._status(f"'{value}' is already in the list.")
                return
            fields = ("source_id", "value", "order", "min_score", "limit", "types", "randomize", "prioritize")
            if old and all(getattr(old, f) == getattr(pick, f) for f in fields):
                pick.status, pick.kept = old.status, old.kept     # nothing changed: keep its history
            self._remove_iid(self.edit_iid)
            self._cancel_edit(reset_only=True)
            self._add_pick(pick)
            self._set_query("")
            self._apply_placeholder()
            self._status("Changes saved.")
        elif self._add_pick(pick):
            self._set_query("")
            self._apply_placeholder()
        self.add_entry.focus_set()

    def _edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        p = self.rows[iid]
        cls = SOURCE_BY_ID.get(p.source_id)
        if not cls:
            return
        self.edit_iid = iid
        self.add_site.set(cls.label)
        self._on_site_change()
        self._set_query(p.value)
        if cls.order_choices:
            self.order_cb.set(self._label(p.order or cls.default_order, cls.order_choices))
        if cls.min_score_choices:
            self.min_cb.set(self._label(p.min_score, cls.min_score_choices))
        self.limit_var.set(str(p.limit or cls.default_limit))
        for k, v in self.type_vars.items():
            v.set(k in (p.type_set() or {"image", "video"}))
        self.random_var.set(p.randomize)
        self.prio_var.set(p.prioritize)
        self.submit_btn.config(text="Save changes")
        self.cancel_btn.pack(side="left", padx=6)
        self._status(f"Editing '{p.value}': change the boxes, then Save changes.")

    def _cancel_edit(self, reset_only=False):
        self.edit_iid = None
        self.submit_btn.config(text="Add  →")
        self.cancel_btn.pack_forget()
        if not reset_only:
            self._set_query("")
            self._apply_placeholder()
            self._on_site_change()

    # ================================================================ centre column logic
    def _iid(self, pick):
        return f"{pick.source_id}|{pick.value.strip().lower()}"

    def _sort_text(self, p):
        cls = SOURCE_BY_ID.get(p.source_id)
        if not cls or not cls.order_choices:
            return "-"
        text = self._label(p.order or cls.default_order, cls.order_choices)
        if p.min_score and cls.min_score_choices:
            text += f" · {self._label(p.min_score, cls.min_score_choices)}"
        return text

    def _opts_text(self, p):
        cls = SOURCE_BY_ID.get(p.source_id)
        names = {"image": "img", "video": "vid", "audio": "aud"}
        types = p.type_set()
        parts = [] if types in (set(), {"image", "video"}, {"image", "video", "audio"}) else ["+".join(names[t] for t in names if t in types)]
        if p.randomize:
            parts.append("random")
        if p.prioritize and cls:
            parts.append(f"{cls.priority_media}s first")
        return " ".join(parts)

    def _row_values(self, p, running=False):
        cls = SOURCE_BY_ID.get(p.source_id)
        return (status_text(p, running), cls.label if cls else p.source_id, p.value, self._sort_text(p),
                p.limit or (cls.default_limit if cls else ""), self._opts_text(p))

    def _refresh_row(self, iid, running=False):
        p = self.rows.get(iid)
        if p and self.tree.exists(iid):
            self.tree.item(iid, values=self._row_values(p, running), tags=(status_tag(p, running),))

    def _insert_row(self, pick):
        iid = self._iid(pick)
        if iid in self.rows:
            return False
        self.rows[iid] = pick
        self.tree.insert("", "end", iid=iid, values=self._row_values(pick), tags=(status_tag(pick),))
        return True

    def _add_pick(self, pick):
        if self._insert_row(pick):
            self._log(f"added search {pick.source_id}:{pick.value} order={pick.order or 'default'} "
                      f"min_score={pick.min_score or '-'} limit={pick.limit} types={pick.types}", "debug")
            self._persist_picks()
            self._update_count()
            return True
        self._status(f"'{pick.value}' is already in the list.")
        return False

    def _remove_iid(self, iid):
        self.rows.pop(iid, None)
        if self.tree.exists(iid):
            self.tree.delete(iid)

    def _remove_selected(self):
        for iid in self.tree.selection():
            self._remove_iid(iid)
        self._persist_picks()
        self._update_count()

    def _rerun_selected(self):
        """Forget the last result so the row reads 'new' again (Start still skips files already collected)."""
        for iid in self.tree.selection():
            self.rows[iid].status, self.rows[iid].kept = "", 0
            self._refresh_row(iid)
        self._persist_picks()

    def _context_menu(self, ev):
        iid = self.tree.identify_row(ev.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.menu.tk_popup(ev.x_root, ev.y_root)

    def _open_pick_folder(self):
        for iid in self.tree.selection()[:1]:
            p = self.rows[iid]
            cls = SOURCE_BY_ID.get(p.source_id)
            d = os.path.join(self.collection.dir, safe_name(cls.label if cls else p.source_id), safe_name(p.value)[:40])
            os.makedirs(d, exist_ok=True)
            open_path(d)

    def _clear_rows(self):
        if self.rows and messagebox.askyesno("Clear all", "Remove every search from the list?\n"
                                             "(Downloaded files stay.)", parent=self):
            self.rows.clear()
            self.tree.delete(*self.tree.get_children())
            self._persist_picks()
            self._update_count()

    def _update_count(self):
        n = len(self.rows)
        self.count_lbl.config(text=(f"{n} search(es). Double-click a row to edit it." if n else
                                    "Nothing here yet: Find a topic on the left and press Add →, or fill in the Add search box"))

    # ================================================================ site check
    def _check_sites(self):
        if self._busy() or self._check_stop is not None:
            messagebox.showinfo("Busy", "Wait for the current run or check to finish (or press Stop).", parent=self)
            return
        n = len(SOURCE_CLASSES)
        self._check_stop, self._check_done = threading.Event(), 0
        self.check_btn.config(state="disabled")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress.config(value=0, maximum=n)
        self._status(f"Checking {n} sites (one tiny search each)...")
        self._log(f"SITE CHECK: one item from each of {n} sites", "debug")
        creds, stop = settings.credentials_for(self.cfg), self._check_stop

        def work():
            res, tmp = collector.check_sites(creds, on_result=lambda r: self._check_q.put(("one", r)), stop_event=stop)
            self._check_q.put(("all", res, tmp))
        threading.Thread(target=work, daemon=True).start()

    def _handle_check(self, ev):
        if ev[0] == "one":
            r = ev[1]
            self._check_done += 1
            self.progress.config(value=self._check_done)
            self._status(f"Checking sites... {self._check_done}/{self.progress['maximum']:.0f}  ({r['label']}: {r['result']})")
            self._log(f"site check {r['label']}: {r['result']} in {r['elapsed']}s {r['detail']}".rstrip(),
                      "error" if r["result"] == "fail" else "debug")
            for h in r["http"]:
                line = f"site check {r['label']}: HTTP {h.get('status')} {h.get('ms')}ms {h.get('url')}"
                if h.get("retry"):
                    line += f" retry={h['retry']}"
                if h.get("error"):
                    line += f" ERROR {h['error']}"
                if h.get("body"):
                    line += f" body={h['body'][:300]!r}"
                self._log(line, "debug")
            if r.get("detail"):
                self._log(f"site check {r['label']}: detail: {r['detail']}", "debug")
            return
        _, results, tmp = ev
        self._check_stop = None
        self.check_btn.config(state="normal")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        ok = sum(1 for r in results if r["result"] == "ok")
        self._status(f"Site check done: {ok} of {len(results)} sites live.")
        TestResultsWindow(self, results, tmp)

    # ================================================================ running
    def _start(self):
        picks = list(self.rows.values())
        if not picks:
            messagebox.showinfo("Nothing to run", "Add at least one search first: Find a topic and press Add →, "
                                "or use the Add search box.", parent=self)
            return
        settings.save(self.cfg)
        opts = Options(limit=self._limit(), types={"image", "video"}, max_mb=int(self.cfg.get("max_file_mb") or 0))
        self._limits = {self._iid(p): (p.limit or SOURCE_BY_ID[p.source_id].default_limit) for p in picks}
        self._done_total = 0
        self.progress.config(value=0, maximum=max(1, sum(self._limits.values())))
        self.job = Job(self.collection, picks, opts, settings.credentials_for(self.cfg))
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.skip_btn.config(state="normal")
        self._status(f"Running {len(picks)} search(es)...")
        self._log(f"RUN {len(picks)} search(es)", "debug")
        self._running_iid = None
        self.job.start()

    def _skip(self):
        if self.job and self._busy():
            self.job.skip_current()
            self._log("skip requested for the current download", "debug")

    def _show_dl(self, done, total, bps, url):
        if not done and not total:
            self.dl_lbl.config(text="")
            return
        name = os.path.basename(url.split("?")[0]) or "file"
        name = name if len(name) <= 16 else name[:13] + "..."
        pct = f" ({done * 100 // total}%)" if total else ""
        of = f" of {_size(total)}" if total else ""
        self.dl_lbl.config(text=f"{name}  {_size(done)}{of}{pct}  ·  {_size(bps)}/s")

    def _stop(self):
        if self._check_stop is not None:
            self._check_stop.set()
            self._status("Stopping the site check...")
            return
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
            while True:
                self._handle_check(self._check_q.get_nowait())
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

    def _flash_wait(self):
        import time
        left = self._wait_until - time.time()
        if left > 0:
            self._wait_on = not self._wait_on
            if not self.wait_dot.winfo_manager():
                self.wait_lbl.pack(side="left", padx=(12, 0))
                self.wait_dot.pack(side="left", padx=(8, 0), before=self.wait_lbl)
            self.wait_dot.itemconfig("dot", fill=theme.CRIMSON if self._wait_on else theme.BG)
            self.wait_lbl.config(text=f"{self._wait_what} - waiting {left:.0f}s")
        elif self.wait_dot.winfo_manager():
            self.wait_dot.pack_forget()
            self.wait_lbl.pack_forget()
        self.after(500, self._flash_wait)

    def _handle(self, ev):
        kind = ev[0]
        if kind == "log" and ev[2] == "wait":
            import re, time
            m = re.search(r"WAIT\|([\d.]+)\|(.*)", ev[1])
            if m:
                self._wait_until = time.time() + float(m.group(1))
                self._wait_what = m.group(2)
            return
        if kind == "log":
            self._log(ev[1], ev[2])
        elif kind == "dl":
            self._show_dl(*ev[1:])
        elif kind == "progress":
            self._status(f"{ev[3]} ({ev[1]})")
            self._mark_running(ev[3])
        elif kind == "item":
            self._add_recent(ev[1], ev[2], ev[3])
            self.progress.step(1)
        elif kind == "pick_done":
            _, pick, count, status, detail = ev
            self._refresh_row(self._iid(pick))
            self._done_total += self._limits.get(self._iid(pick), 0)
            self.progress.config(value=max(self.progress["value"], min(self._done_total, self.progress["maximum"])))
            self._log(f"DONE {pick.label or pick.value}: {status}" + (f" - {detail}" if detail else f" ({count} new)"),
                      "error" if status == "failed" else "info")
        elif kind == "done":
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.skip_btn.config(state="disabled")
            self.dl_lbl.config(text="")
            self.progress.config(value=self.progress["maximum"])
            self._status(f"{'Stopped' if ev[2] else 'Finished'}: {ev[1]} new item(s).")
            self._log(f"RUN {'stopped' if ev[2] else 'finished'}: {ev[1]} new item(s)", "debug")

    # ================================================================ right column: preview + strip
    def _mark_running(self, text):
        """Progress text ends 'Site: value'; show that row as running."""
        for iid, p in self.rows.items():
            cls = SOURCE_BY_ID.get(p.source_id)
            if text.endswith(f"{cls.label if cls else p.source_id}: {p.value}"):
                if iid != self._running_iid:
                    prev, self._running_iid = self._running_iid, iid
                    if prev:
                        self._refresh_row(prev)
                    self._refresh_row(iid, running=True)
                return

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
        r = ttk.Frame(body)
        r.pack(fill="x", pady=4)
        ttk.Label(r, text="Skip files over (MB)", width=22).pack(side="left")
        self.max_var = tk.StringVar(value=str(cfg.get("max_file_mb") or 0))
        ttk.Entry(r, textvariable=self.max_var, width=8).pack(side="left")
        add_help(r, "Files bigger than this are skipped before they finish downloading. 0 = no limit. "
                    "Handy for long videos.", side="left", padx=8)
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
            if (site, arg) == ("hentaifoundry", "cookie"):
                self.hf_btn = ttk.Button(r, text="Connect browser", command=self._connect_hf)
                self.hf_btn.pack(side="left", padx=(6, 0))
            if (site, arg) == ("rule34", "cookie"):
                self.r34_btn = ttk.Button(r, text="Connect browser", command=self._connect_rule34)
                self.r34_btn.pack(side="left", padx=(6, 0))
            add_help(r, hint, side="left", padx=8)
        self.status_var = tk.StringVar()
        ttk.Label(body, textvariable=self.status_var, style="Muted.TLabel", wraplength=560).pack(anchor="w", pady=(6, 0))
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(12, 0))
        ttk.Button(row, text="Save", command=self._save).pack(side="right")
        ttk.Button(row, text="Cancel", style="Plus.TButton", command=self.destroy).pack(side="right", padx=6)
        self.grab_set()

    def _connect_hf(self):
        """Open a real browser, let the user pass the bot check, then take over its cookies + User-Agent."""
        import threading
        from core import browser_session
        self.hf_btn.state(["disabled"])
        self.status_var.set("Opening browser...")
        box = {}
        install = self.hf_btn.cget("text") == "Install browser component"

        def work():
            try:
                if install:
                    box["msg"] = "Installing (a minute or two)..."
                    browser_session.install_fallback()
                    box["done"] = "Installed. Click Connect browser."
                else:
                    box["res"] = browser_session.capture_hentai_foundry(
                        status=lambda m: box.__setitem__("msg", m), cancelled=lambda: box.get("stop", False))
            except Exception as ex:
                box["err"] = str(ex)
        threading.Thread(target=work, daemon=True).start()
        self.bind("<Destroy>", lambda e: box.__setitem__("stop", True) if e.widget is self else None)

        def poll():
            if not self.winfo_exists():
                return
            if "res" in box:
                self.vars[("hentaifoundry", "cookie")].set(box["res"]["cookie"])
                self.vars[("hentaifoundry", "user_agent")].set(box["res"]["user_agent"])
                self.status_var.set("Connected. Click Save to keep it.")
                self.hf_btn.state(["!disabled"])
            elif "done" in box:
                self.status_var.set(box["done"])
                self.hf_btn.config(text="Connect browser")
                self.hf_btn.state(["!disabled"])
            elif "err" in box:
                if box["err"] == "NEED_FALLBACK":
                    self.status_var.set("No Chrome or Edge found. Click Install browser component.")
                    self.hf_btn.config(text="Install browser component")
                else:
                    self.status_var.set(box["err"])
                self.hf_btn.state(["!disabled"])
            else:
                if box.get("msg"):
                    self.status_var.set(box["msg"])
                self.after(500, poll)
        poll()

    def _connect_rule34(self):
        """Open a real browser, let the user pass Rule34's CAPTCHA if shown,
        then save the resulting cookies + User-Agent for the site's web fallback."""
        import threading
        from core import browser_session
        self.r34_btn.state(["disabled"])
        self.status_var.set("Opening Rule34 browser...")
        box = {}

        def work():
            try:
                box["res"] = browser_session.capture_rule34(
                    status=lambda m: box.__setitem__("msg", m),
                    cancelled=lambda: box.get("stop", False))
            except Exception as ex:
                box["err"] = str(ex)

        threading.Thread(target=work, daemon=True).start()
        self.bind("<Destroy>", lambda e: box.__setitem__("stop", True) if e.widget is self else None)

        def poll():
            if not self.winfo_exists():
                return
            if "res" in box:
                self.vars[("rule34", "cookie")].set(box["res"]["cookie"])
                self.vars[("rule34", "user_agent")].set(box["res"]["user_agent"])
                self.status_var.set("Rule34 connected. Click Save to keep it.")
                self.r34_btn.state(["!disabled"])
            elif "err" in box:
                if box["err"] == "NEED_FALLBACK":
                    self.status_var.set("No Chrome or Edge found. Install the browser component first.")
                else:
                    self.status_var.set(box["err"])
                self.r34_btn.state(["!disabled"])
            else:
                if box.get("msg"):
                    self.status_var.set(box["msg"])
                self.after(500, poll)
        poll()

    def _browse(self):
        d = filedialog.askdirectory(parent=self, initialdir=self.out_var.get())
        if d:
            self.out_var.set(d)

    def _save(self):
        self.cfg["output_dir"] = self.out_var.get().strip() or self.cfg["output_dir"]
        try:
            self.cfg["max_file_mb"] = max(0, int(self.max_var.get().strip() or 0))
        except ValueError:
            self.cfg["max_file_mb"] = 0
        creds = dict(self.cfg.get("credentials") or {})      # keep fields for sites not shown (e.g. disabled ones)
        for (site, arg), var in self.vars.items():
            creds.setdefault(site, {})[arg] = var.get().strip()
        self.cfg["credentials"] = creds
        self.on_save()
        self.destroy()


def main():
    CollectorApp().mainloop()
