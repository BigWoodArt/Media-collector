"""Shared crimson-and-violet dark theme for Media Collector."""
import tkinter as tk
from tkinter import ttk

BG = "#1a0f1f"
PANEL_BG = "#2a1530"
CRIMSON = "#dc143c"
VIOLET = "#8a2be2"
LIGHT_VIOLET = "#b57edc"
TEXT_FG = "#f0e6f5"
LOG_BG = "#150a1a"
BTN_FG = "#ffffff"
MUTED = "#7a5a80"
DISABLED_BG = "#4a2a4a"
WINDOW_BG = "#120a16"      # behind the cards
BORDER = "#3b2145"         # card and field outlines

FONT_FAMILY = "Segoe UI"
FONT_NORMAL = (FONT_FAMILY, 10)
FONT_SMALL = (FONT_FAMILY, 9)
FONT_BOLD = (FONT_FAMILY, 10, "bold")
FONT_LABELFRAME = (FONT_FAMILY, 11, "bold")


def apply_theme(root):
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL_BG)
    style.configure("Window.TFrame", background=WINDOW_BG)
    style.configure("Window.TLabel", background=WINDOW_BG, foreground=TEXT_FG, font=FONT_NORMAL)
    style.configure("Window.Muted.TLabel", background=WINDOW_BG, foreground=MUTED, font=FONT_SMALL)
    style.configure("TLabelframe", background=BG, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=BG, foreground=LIGHT_VIOLET,
                     font=FONT_LABELFRAME)
    style.configure("TLabel", background=BG, foreground=TEXT_FG, font=FONT_NORMAL)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)

    style.configure("TButton", background=CRIMSON, foreground=BTN_FG,
                     borderwidth=0, focusthickness=0, focuscolor=BG,
                     font=FONT_BOLD, padding=(14, 7))
    style.map("TButton", background=[("active", VIOLET), ("disabled", DISABLED_BG)])

    style.configure("Accent.TButton", padding=(26, 9))

    # quiet secondary button
    style.configure("Plus.TButton", background=PANEL_BG, foreground=LIGHT_VIOLET, bordercolor=BORDER,
                     lightcolor=PANEL_BG, darkcolor=PANEL_BG, borderwidth=1, font=FONT_BOLD, padding=(12, 6))
    style.map("Plus.TButton", background=[("active", VIOLET), ("disabled", PANEL_BG)],
              foreground=[("active", BTN_FG), ("disabled", MUTED)])

    # Combobox: explicit state maps; clam otherwise paints readonly widgets white.
    style.configure("TCombobox", fieldbackground=PANEL_BG, background=PANEL_BG,
                     foreground=TEXT_FG, arrowcolor=LIGHT_VIOLET, font=FONT_NORMAL,
                     selectbackground=PANEL_BG, selectforeground=TEXT_FG, padding=5,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, arrowsize=14)
    style.map("TCombobox",
              fieldbackground=[("readonly", PANEL_BG), ("disabled", PANEL_BG)],
              selectbackground=[("readonly", PANEL_BG)],
              selectforeground=[("readonly", TEXT_FG)],
              foreground=[("readonly", TEXT_FG), ("disabled", MUTED)],
              background=[("readonly", PANEL_BG)],
              bordercolor=[("focus", VIOLET)], lightcolor=[("focus", VIOLET)], darkcolor=[("focus", VIOLET)])
    root.option_add("*TCombobox*Listbox.background", PANEL_BG)
    root.option_add("*TCombobox*Listbox.foreground", TEXT_FG)
    root.option_add("*TCombobox*Listbox.selectBackground", VIOLET)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT_FG)
    root.option_add("*TCombobox*Listbox.font", FONT_NORMAL)

    style.configure("TEntry", fieldbackground=PANEL_BG, foreground=TEXT_FG,
                     insertcolor=TEXT_FG, font=FONT_NORMAL, padding=5,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.map("TEntry", fieldbackground=[("disabled", PANEL_BG)],
              foreground=[("disabled", MUTED)],
              bordercolor=[("focus", VIOLET)], lightcolor=[("focus", VIOLET)], darkcolor=[("focus", VIOLET)])
    style.configure("Placeholder.TEntry", fieldbackground=PANEL_BG, foreground=MUTED,
                     insertcolor=TEXT_FG, font=FONT_NORMAL)

    style.configure("TProgressbar", troughcolor=PANEL_BG, background=CRIMSON, thickness=8,
                     bordercolor=WINDOW_BG, lightcolor=CRIMSON, darkcolor=CRIMSON)

    # slim scrollbars, no arrow buttons
    for orient, side in (("Vertical", "ns"), ("Horizontal", "ew")):
        name = f"{orient}.TScrollbar"
        style.layout(name, [(f"{orient}.Scrollbar.trough", {"sticky": side, "children": [
            (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        style.configure(name, background=BORDER, troughcolor=BG, bordercolor=BG,
                        lightcolor=BORDER, darkcolor=BORDER, width=10)
        style.map(name, background=[("active", VIOLET), ("pressed", VIOLET)])

    style.configure("Treeview", background=PANEL_BG, fieldbackground=PANEL_BG,
                     foreground=TEXT_FG, rowheight=30, borderwidth=1, font=FONT_NORMAL,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.map("Treeview", background=[("selected", VIOLET)],
              foreground=[("selected", BTN_FG)])
    style.configure("Treeview.Heading", background=BG, foreground=LIGHT_VIOLET,
                     font=FONT_BOLD, relief="flat", padding=(6, 6), borderwidth=0)
    style.map("Treeview.Heading", background=[("active", VIOLET)])

    style.configure("TNotebook", background=WINDOW_BG, borderwidth=0, tabmargins=(0, 0, 0, 6),
                     bordercolor=WINDOW_BG, lightcolor=WINDOW_BG, darkcolor=WINDOW_BG)
    style.configure("TNotebook.Tab", background=WINDOW_BG, foreground=MUTED,
                     padding=(20, 8), font=FONT_BOLD, borderwidth=0,
                     bordercolor=WINDOW_BG, lightcolor=WINDOW_BG, darkcolor=WINDOW_BG)
    style.configure("TSpinbox", fieldbackground=PANEL_BG, foreground=TEXT_FG, background=PANEL_BG,
                     arrowcolor=LIGHT_VIOLET, insertcolor=TEXT_FG, padding=4,
                     bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.map("TNotebook.Tab", background=[("selected", CRIMSON), ("active", PANEL_BG)],
              foreground=[("selected", BTN_FG), ("active", TEXT_FG)],
              expand=[("selected", (0, 0, 0, 0))],
              padding=[("selected", (20, 8)), ("!selected", (20, 8))],
              bordercolor=[("!disabled", WINDOW_BG)], lightcolor=[("!disabled", WINDOW_BG)],
              darkcolor=[("!disabled", WINDOW_BG)])


def make_checkbutton(parent, text, variable, **kw):
    """tk.Checkbutton with direct colors (ttk's renders a white box on this theme)."""
    defaults = dict(bg=BG, fg=TEXT_FG, selectcolor=PANEL_BG, activebackground=BG,
                     activeforeground=LIGHT_VIOLET, highlightthickness=0, bd=0,
                     font=FONT_NORMAL)
    defaults.update(kw)
    return tk.Checkbutton(parent, text=text, variable=variable, **defaults)


def card(parent):
    """A padded panel with a thin outline. Returns (outer, inner): add outer to the layout, fill inner."""
    outer = tk.Frame(parent, bg=BG, highlightbackground=BORDER, highlightcolor=BORDER, highlightthickness=1)
    inner = ttk.Frame(outer, padding=14)
    inner.pack(fill="both", expand=True)
    return outer, inner
