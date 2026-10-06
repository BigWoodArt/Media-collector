"""Main window: search box -> real matches as tick-chips -> Start -> live preview grid (click to reject)."""
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import theme
from core import collector, settings
from core.collector import Collection, Job, Options, Pick
from core.util import open_path
from sources import SOURCE_CLASSES, SOURCE_BY_ID
from ui import tiles
from ui.tooltip import add_help, tip

TILE = 128
GAP = 8
QUALITIES = ("Any", "Good", "Best")
TYPES = (("image", "Images"), ("video", "Videos"), ("audio", "Audio"))
NOTICE = ("This tool collects media from public sites, several of which host adult material (18+ only).\n\n"
          "It is unofficial and for personal use. You are responsible for following each site's rules and "
          "your local laws. Requests are paced, it never bypasses logins or paywalls, and it never collects "
          "material involving minors (a built-in, non-removable filter).\n\nContinue?")


class CollectorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Media Collector")
        self.geometry("980x860")
        self.minsize(760, 640)
        self.configure(bg=theme.BG)
        theme.apply_theme(self)
        ttk.Style().configure("TSpinbox", fieldbackground=theme.PANEL_BG, foreground=theme.TEXT_FG,
                              background=theme.PANEL_BG, arrowcolor=theme.CRIMSON, insertcolor=theme.TEXT_FG)
        self.cfg = settings.load()
        self.chips = {}            # (source, value) -> {"pick", "var", "widget"}
        self.tiles = []            # {"item", "pick", "pil", "photo", "rejected", "ids": canvas ids}
        self.job = None
        self.collection = None
        self._suggest_q = queue.Queue()
        self._suggest_token = 0
        self._build()
        self._load_collection(self.cfg.get("last_collection") or "My collection")
        self.after(100, self._poll)
        self.after(300, self._first_run_notice)

    # ---------------------------------------------------------------- layout
    def _build(self):
        pad = dict(padx=12)
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(10, 4), **pad)
        ttk.Label(top, text="Collection", font=theme.FONT_BOLD).pack(side="left")
        self.col_var = tk.StringVar()
        self.col_box = ttk.Combobox(top, textvariable=self.col_var, width=28)
        self.col_box.pack(side="left", padx=8)
        self.col_box.bind("<<ComboboxSelected>>", lambda e: self._load_collection(self.col_var.get()))
        self.col_box.bind("<Return>", lambda e: self._load_collection(self.col_var.get()))
        tip(self.col_box, "A collection is a themed folder. Pick one or type a new name and press Enter. "
                          "It remembers what it has fetched, so running again only adds new items.")
        for text, cmd, hint in (("Open folder", self._open_folder, "Show this collection's files."),
                                ("Export ZIP", self._export_zip, "Zip the collection's media."),
                                ("Settings", self._settings, "Output folder and site accounts/keys.")):
            tip(ttk.Button(top, text=text, command=cmd), hint).pack(side="right", padx=(6, 0))

        sf = ttk.Frame(self)
        sf.pack(fill="x", pady=4, **pad)
        self.query_var = tk.StringVar()
        self.query_entry = ttk.Entry(sf, textvariable=self.query_var, font=(theme.FONT_FAMILY, 11))
        self.query_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.query_entry.bind("<Return>", lambda e: self._find())
        ttk.Button(sf, text="Find", command=self._find).pack(side="left", padx=(8, 0))
        add_help(sf, "Type a topic. Every site is asked for its own real matches (subreddits, tags, "
                     "communities), shown below with their size. Tick the ones you want.", side="left", padx=6)
        self.find_status = ttk.Label(self, text="Type a topic and press Find.", style="Muted.TLabel")
        self.find_status.pack(anchor="w", **pad)

        mbox = ttk.LabelFrame(self, text="Matches (tick to include)")
        mbox.pack(fill="x", pady=6, **pad)
        self.chip_area = tk.Frame(mbox, bg=theme.BG)
        self.chip_area.pack(fill="x", padx=6, pady=6)

        add = ttk.Frame(self)
        add.pack(fill="x", pady=2, **pad)
        ttk.Label(add, text="Add by name").pack(side="left")
        self.add_site = tk.StringVar(value=SOURCE_CLASSES[0].label)
        cb = ttk.Combobox(add, textvariable=self.add_site, state="readonly", width=14,
                          values=[c.label for c in SOURCE_CLASSES])
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._sync_add_hint())
        self.add_var = tk.StringVar()
        ent = ttk.Entry(add, textvariable=self.add_var, width=30)
        ent.pack(side="left")
        ent.bind("<Return>", lambda e: self._add_named())
        ttk.Button(add, text="Add", style="Plus.TButton", command=self._add_named).pack(side="left", padx=6)
        self.add_hint = ttk.Label(add, text="", style="Muted.TLabel")
        self.add_hint.pack(side="left", padx=4)
        self._sync_add_hint()

        opts = ttk.Frame(self)
        opts.pack(fill="x", pady=(8, 2), **pad)
        ttk.Label(opts, text="Quality").pack(side="left")
        self.quality_var = tk.StringVar(value=self.cfg.get("quality", "Good"))
        for q in QUALITIES:
            tk.Radiobutton(opts, text=q, value=q, variable=self.quality_var, bg=theme.BG, fg=theme.TEXT_FG,
                           selectcolor=theme.PANEL_BG, activebackground=theme.BG,
                           activeforeground=theme.LIGHT_VIOLET, highlightthickness=0,
                           font=theme.FONT_NORMAL).pack(side="left", padx=3)
        add_help(opts, "Any = everything. Good / Best = better-rated posts. Each site translates it its own way "
                       "(minimum score, top of the month/year, ...).", side="left", padx=4)
        ttk.Label(opts, text="   Per site").pack(side="left")
        self.limit_var = tk.IntVar(value=int(self.cfg.get("limit", 50)))
        ttk.Spinbox(opts, from_=1, to=2000, width=6, textvariable=self.limit_var).pack(side="left", padx=4)
        self.type_vars = {}
        ttk.Label(opts, text="   Type").pack(side="left")
        for key, text in TYPES:
            v = tk.BooleanVar(value=key in self.cfg.get("types", ["image", "video"]))
            self.type_vars[key] = v
            theme.make_checkbutton(opts, text, v).pack(side="left", padx=3)
        self.random_var = tk.BooleanVar(value=bool(self.cfg.get("randomize")))
        theme.make_checkbutton(opts, "Shuffle", self.random_var).pack(side="left", padx=(8, 0))
        self.adv_var = tk.BooleanVar(value=False)
        theme.make_checkbutton(opts, "Advanced", self.adv_var, command=self._toggle_adv).pack(side="right")

        self.adv = ttk.Frame(self)
        self.sort_var, self.time_var = tk.StringVar(), tk.StringVar()
        ttk.Label(self.adv, text="Sort (sites that have one)").pack(side="left")
        self.sort_box = ttk.Combobox(self.adv, textvariable=self.sort_var, width=16, state="readonly",
                                     values=[""] + sorted({o for c in SOURCE_CLASSES for o in c.sort_options}))
        self.sort_box.pack(side="left", padx=6)
        ttk.Label(self.adv, text="Time").pack(side="left")
        self.time_box = ttk.Combobox(self.adv, textvariable=self.time_var, width=10, state="readonly",
                                     values=[""] + sorted({o for c in SOURCE_CLASSES for o in c.time_options}))
        self.time_box.pack(side="left", padx=6)
        ttk.Label(self.adv, text="Blank = chosen by Quality. A value a site doesn't know is ignored by that site.",
                  style="Muted.TLabel").pack(side="left", padx=6)

        pv = self.preview_box = ttk.LabelFrame(self, text="Live preview (click a picture to reject it)")
        pv.pack(fill="both", expand=True, pady=6, **pad)
        bar = ttk.Frame(pv)
        bar.pack(fill="x", padx=6, pady=(4, 0))
        self.reject_btn = ttk.Button(bar, text="Remove rejected (0)", command=self._remove_rejected)
        self.reject_btn.pack(side="right")
        self.count_lbl = ttk.Label(bar, text="0 items", style="Muted.TLabel")
        self.count_lbl.pack(side="left")
        wrap = ttk.Frame(pv)
        wrap.pack(fill="both", expand=True, padx=6, pady=6)
        self.canvas = tk.Canvas(wrap, bg=theme.LOG_BG, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._reflow())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120 or 1), "units"))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(2, "units"))

        foot = ttk.Frame(self)
        foot.pack(fill="x", pady=(2, 10), **pad)
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
        self.log_btn = ttk.Button(row, text="Log", style="Plus.TButton", command=self._toggle_log)
        self.log_btn.pack(side="right", padx=6)
        self.log = tk.Text(foot, height=7, bg=theme.LOG_BG, fg=theme.TEXT_FG, insertbackground=theme.TEXT_FG,
                           font=("Consolas", 9), relief="flat", wrap="word", state="disabled")
        self.log.tag_config("error", foreground=theme.CRIMSON)
        self.log.tag_config("warning", foreground=theme.LIGHT_VIOLET)
        self._log_shown = False

    # ---------------------------------------------------------------- small helpers
    def _toggle_adv(self):
        if self.adv_var.get():
            self.adv.pack(fill="x", padx=12, pady=2, before=self.preview_box)
        else:
            self.adv.pack_forget()

    def _toggle_log(self):
        self._log_shown = not self._log_shown
        if self._log_shown:
            self.log.pack(fill="x", pady=(6, 0))
        else:
            self.log.pack_forget()

    def _write_log(self, msg, level="info"):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n", level)
        self.log.see("end")
        self.log.config(state="disabled")

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

    # ---------------------------------------------------------------- collections
    def _collection_names(self):
        root = self.cfg["output_dir"]
        try:
            return sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
        except OSError:
            return []

    def _load_collection(self, name):
        name = (name or "").strip() or "My collection"
        if self.job and self.job.thread and self.job.thread.is_alive():
            messagebox.showinfo("Busy", "Stop the current run before switching collections.", parent=self)
            self.col_var.set(self.collection.name if self.collection else name)
            return
        self.collection = Collection(self.cfg["output_dir"], name)
        self.col_var.set(name)
        self.cfg["last_collection"] = name
        names = self._collection_names()
        self.col_box.config(values=names if name in names else names + [name])
        self._clear_tiles()
        self._status(f"Collection '{name}': {len(self.collection.seen)} item(s) remembered.")

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
        except OSError as ex:
            messagebox.showerror("Export failed", str(ex), parent=self)

    def _settings(self):
        SettingsDialog(self, self.cfg, on_save=self._settings_saved)

    def _settings_saved(self):
        settings.save(self.cfg)
        self._load_collection(self.collection.name)

    def _status(self, text):
        self.status.config(text=text)

    # ---------------------------------------------------------------- finding matches
    def _find(self):
        q = self.query_var.get().strip()
        if not q:
            return
        self._suggest_token += 1
        token = self._suggest_token
        self.find_status.config(text=f"Asking {len(SOURCE_CLASSES)} sites for matches to '{q}'...")

        def work():
            self._suggest_q.put((token, q, collector.suggest_all(q)))
        threading.Thread(target=work, daemon=True).start()

    def _show_matches(self, token, q, found):
        if token != self._suggest_token:
            return
        for key in [k for k, c in self.chips.items() if not c["var"].get()]:
            self.chips.pop(key)["widget"].destroy()
        for m in found:
            key = (m["source"], m["value"].lower())
            if key not in self.chips:
                self._add_chip(Pick(m["source"], m["value"], m["label"]), count=m["count"], ticked=False)
        self._layout_chips()
        kinds = len({m["source"] for m in found})
        self.find_status.config(text=(f"{len(found)} match(es) from {kinds} site(s)." if found else
                                      "No matches. Some sites have no search: use Add by name."))

    def _add_chip(self, pick, count=None, ticked=True):
        var = tk.BooleanVar(value=ticked)
        text = pick.label or f"{pick.source_id} {pick.value}"
        if count:
            text += f"  ({self._short(count)})"
        w = tk.Checkbutton(self.chip_area, text=text, variable=var, bg=theme.PANEL_BG, fg=theme.TEXT_FG,
                           selectcolor=theme.VIOLET, activebackground=theme.VIOLET, activeforeground=theme.BTN_FG,
                           highlightthickness=0, bd=0, padx=8, pady=3, font=theme.FONT_NORMAL, indicatoron=False)
        self.chips[pick.key()] = {"pick": pick, "var": var, "widget": w}
        return w

    @staticmethod
    def _short(n):
        try:
            n = int(n)
        except (TypeError, ValueError):
            return str(n)
        return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1000:.0f}k" if n >= 10_000 else str(n)

    def _layout_chips(self):
        for c in self.chips.values():
            c["widget"].grid_forget()
        width = max(self.chip_area.winfo_width(), 600)
        x = row = col = 0
        for c in self.chips.values():
            w = c["widget"]
            need = w.winfo_reqwidth() + 6
            if x + need > width and col:
                row, col, x = row + 1, 0, 0
            w.grid(row=row, column=col, padx=3, pady=3, sticky="w")
            x += need
            col += 1

    def _add_named(self):
        label, value = self.add_site.get(), self.add_var.get().strip()
        cls = next((c for c in SOURCE_CLASSES if c.label == label), None)
        if not cls or not value:
            return
        pick = Pick(cls.id, value, f"{cls.label} {value}")
        if pick.key() not in self.chips:
            self._add_chip(pick, ticked=True)
        else:
            self.chips[pick.key()]["var"].set(True)
        self.add_var.set("")
        self._layout_chips()

    # ---------------------------------------------------------------- running
    def _selected(self):
        return [c["pick"] for c in self.chips.values() if c["var"].get()]

    def _start(self):
        picks = self._selected()
        if not picks:
            messagebox.showinfo("Nothing selected", "Press Find and tick at least one match, or use Add by name.",
                                parent=self)
            return
        types = {k for k, v in self.type_vars.items() if v.get()}
        if not types:
            messagebox.showinfo("No type chosen", "Tick Images, Videos, or Audio.", parent=self)
            return
        try:
            limit = max(1, int(self.limit_var.get()))
        except (tk.TclError, ValueError):
            messagebox.showinfo("Per site", "Enter a whole number.", parent=self)
            return
        self.cfg.update(limit=limit, quality=self.quality_var.get(), types=sorted(types),
                        randomize=self.random_var.get())
        settings.save(self.cfg)
        opts = Options(limit=limit, quality=self.quality_var.get(), types=types, randomize=self.random_var.get(),
                       sort=self.sort_var.get(), time_range=self.time_var.get())
        self.job = Job(self.collection, picks, opts, settings.credentials_for(self.cfg))
        self.total_picks, self.done_picks = len(picks), 0
        self.progress.config(value=0, maximum=len(picks) * limit)
        self._progress_base = 0
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._status(f"Running {len(picks)} source(s)...")
        self.job.start()

    def _stop(self):
        if self.job:
            self.job.stop()
            self._status("Stopping after the current download...")

    def _poll(self):
        try:
            while True:
                self._show_matches(*self._suggest_q.get_nowait())
        except queue.Empty:
            pass
        try:
            for _ in range(60):
                ev = self.job.events.get_nowait() if self.job else None
                if ev is None:
                    break
                self._handle(ev)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _handle(self, ev):
        kind = ev[0]
        if kind == "log":
            self._write_log(ev[1], ev[2])
        elif kind == "progress":
            self._status(f"{ev[3]} ({ev[1]})")
        elif kind == "item":
            self._add_tile(ev[1], ev[2], ev[3])
            self.progress.step(1)
        elif kind == "pick_done":
            _, pick, count, status, detail = ev
            self.done_picks += 1
            note = f"{pick.label or pick.value}: {status}" + (f" - {detail}" if detail else f" ({count})")
            self._write_log(note, "error" if status == "failed" else "info")
            self.progress.config(value=self.done_picks * (self.progress["maximum"] / max(self.total_picks, 1)))
        elif kind == "done":
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.progress.config(value=self.progress["maximum"])
            self._status(f"{'Stopped' if ev[2] else 'Finished'}: {ev[1]} new item(s). "
                         "Click pictures to reject any you don't want.")

    # ---------------------------------------------------------------- preview grid
    def _clear_tiles(self):
        self.canvas.delete("all")
        self.tiles.clear()
        self._update_counts()

    def _add_tile(self, pick, item, pil):
        photo = tiles.photo(pil, item.media_type, TILE, TILE)
        self.tiles.append({"item": item, "pick": pick, "photo": photo, "rejected": False, "ids": []})
        self._place(len(self.tiles) - 1, create=True)
        self._update_counts()
        self._scrollregion()

    def _cols(self):
        return max(1, (self.canvas.winfo_width() - GAP) // (TILE + GAP))

    def _place(self, i, create=False):
        t, cols = self.tiles[i], self._cols()
        x, y = GAP + (i % cols) * (TILE + GAP), GAP + (i // cols) * (TILE + GAP)
        if create:
            t["ids"] = [
                self.canvas.create_rectangle(x, y, x + TILE, y + TILE, fill=theme.PANEL_BG, outline=theme.PANEL_BG),
                self.canvas.create_image(x + TILE // 2, y + TILE // 2, image=t["photo"]) if t["photo"] else
                self.canvas.create_text(x + TILE // 2, y + TILE // 2, text=t["item"].media_type,
                                        fill=theme.LIGHT_VIOLET),
                self.canvas.create_text(x + TILE // 2, y + TILE // 2, text="✕", fill=theme.CRIMSON,
                                        font=(theme.FONT_FAMILY, 56, "bold"), state="hidden")]
        else:
            rect, img, mark = t["ids"]
            self.canvas.coords(rect, x, y, x + TILE, y + TILE)
            self.canvas.coords(img, x + TILE // 2, y + TILE // 2)
            self.canvas.coords(mark, x + TILE // 2, y + TILE // 2)

    def _reflow(self):
        for i in range(len(self.tiles)):
            self._place(i)
        self._scrollregion()
        self._layout_chips()

    def _scrollregion(self):
        rows = (len(self.tiles) + self._cols() - 1) // self._cols()
        self.canvas.configure(scrollregion=(0, 0, 0, GAP + rows * (TILE + GAP)))

    def _on_click(self, e):
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        cols = self._cols()
        cx, cy = int((x - GAP) // (TILE + GAP)), int((y - GAP) // (TILE + GAP))
        if cx < 0 or cx >= cols or cy < 0:
            return
        i = cy * cols + cx
        if i >= len(self.tiles):
            return
        t = self.tiles[i]
        t["rejected"] = not t["rejected"]
        rect, img, mark = t["ids"]
        self.canvas.itemconfigure(rect, outline=theme.CRIMSON if t["rejected"] else theme.PANEL_BG,
                                  width=3 if t["rejected"] else 1)
        self.canvas.itemconfigure(mark, state="normal" if t["rejected"] else "hidden")
        self.canvas.tag_raise(mark)
        self._update_counts()

    def _update_counts(self):
        n = sum(t["rejected"] for t in self.tiles)
        self.reject_btn.config(text=f"Remove rejected ({n})")
        self.count_lbl.config(text=f"{len(self.tiles)} item(s)")

    def _remove_rejected(self):
        bad = [t for t in self.tiles if t["rejected"]]
        if not bad:
            return
        for t in bad:
            self.collection.reject(t["item"].post_id, t["item"].file_path)
        self.collection.save()
        keep = [t for t in self.tiles if not t["rejected"]]
        self.canvas.delete("all")
        self.tiles = []
        for t in keep:
            self.tiles.append({**t, "ids": []})
            self._place(len(self.tiles) - 1, create=True)
        self._scrollregion()
        self._update_counts()
        self._status(f"Removed {len(bad)} item(s); they won't be fetched again.")


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
            ttk.Entry(r, textvariable=var, width=40, show="" if arg in ("user_id", "base_url", "instance") else "•"
                      ).pack(side="left")
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
        creds = {}
        for (site, arg), var in self.vars.items():
            creds.setdefault(site, {})[arg] = var.get().strip()
        self.cfg["credentials"] = creds
        self.on_save()
        self.destroy()


def main():
    CollectorApp().mainloop()
