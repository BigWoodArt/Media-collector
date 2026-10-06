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

FONT_FAMILY = "Segoe UI"
FONT_NORMAL = (FONT_FAMILY, 9)
FONT_ITALIC = (FONT_FAMILY, 9, "italic")
FONT_SMALL = (FONT_FAMILY, 8)
FONT_BOLD = (FONT_FAMILY, 9, "bold")
FONT_LABELFRAME = (FONT_FAMILY, 10, "bold")
FONT_HEADER = (FONT_FAMILY, 16, "bold")


def apply_theme(root):
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass

    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL_BG)
    style.configure("TLabelframe", background=BG, bordercolor=VIOLET)
    style.configure("TLabelframe.Label", background=BG, foreground=LIGHT_VIOLET,
                     font=FONT_LABELFRAME)
    style.configure("TLabel", background=BG, foreground=TEXT_FG, font=FONT_NORMAL)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT_SMALL)

    style.configure("TButton", background=CRIMSON, foreground=BTN_FG,
                     borderwidth=0, focusthickness=3, focuscolor=VIOLET,
                     font=FONT_BOLD, padding=6)
    style.map("TButton", background=[("active", VIOLET), ("disabled", DISABLED_BG)])

    style.configure("Plus.TButton", background=PANEL_BG, foreground=LIGHT_VIOLET,
                     borderwidth=1, font=FONT_BOLD, padding=3)
    style.map("Plus.TButton", background=[("active", VIOLET)],
              foreground=[("active", BTN_FG)])

    # Combobox: explicit state maps; clam otherwise paints readonly widgets white.
    style.configure("TCombobox", fieldbackground=PANEL_BG, background=PANEL_BG,
                     foreground=TEXT_FG, arrowcolor=CRIMSON, font=FONT_NORMAL,
                     selectbackground=PANEL_BG, selectforeground=TEXT_FG)
    style.map("TCombobox",
              fieldbackground=[("readonly", PANEL_BG), ("disabled", PANEL_BG)],
              selectbackground=[("readonly", PANEL_BG)],
              selectforeground=[("readonly", TEXT_FG)],
              foreground=[("readonly", TEXT_FG), ("disabled", MUTED)],
              background=[("readonly", PANEL_BG)])
    root.option_add("*TCombobox*Listbox.background", PANEL_BG)
    root.option_add("*TCombobox*Listbox.foreground", TEXT_FG)
    root.option_add("*TCombobox*Listbox.selectBackground", VIOLET)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT_FG)
    root.option_add("*TCombobox*Listbox.font", FONT_NORMAL)

    style.configure("TEntry", fieldbackground=PANEL_BG, foreground=TEXT_FG,
                     insertcolor=TEXT_FG, font=FONT_NORMAL)
    style.map("TEntry", fieldbackground=[("disabled", PANEL_BG)],
              foreground=[("disabled", MUTED)])
    style.configure("Placeholder.TEntry", fieldbackground=PANEL_BG, foreground=MUTED,
                     insertcolor=TEXT_FG, font=FONT_NORMAL)

    style.configure("TProgressbar", troughcolor=PANEL_BG, background=CRIMSON,
                     bordercolor=BG, lightcolor=VIOLET, darkcolor=CRIMSON)

    style.configure("Vertical.TScrollbar", background=PANEL_BG, troughcolor=BG,
                     bordercolor=BG, arrowcolor=LIGHT_VIOLET)
    style.map("Vertical.TScrollbar", background=[("active", VIOLET)])

    style.configure("Treeview", background=PANEL_BG, fieldbackground=PANEL_BG,
                     foreground=TEXT_FG, rowheight=24, borderwidth=0, font=FONT_NORMAL)
    style.map("Treeview", background=[("selected", VIOLET)],
              foreground=[("selected", BTN_FG)])
    style.configure("Treeview.Heading", background=BG, foreground=LIGHT_VIOLET,
                     font=FONT_BOLD, relief="flat")
    style.map("Treeview.Heading", background=[("active", VIOLET)])

    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL_BG, foreground=TEXT_FG,
                     padding=(14, 6), font=FONT_BOLD, borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", CRIMSON)],
              foreground=[("selected", BTN_FG)])


def make_checkbutton(parent, text, variable, **kw):
    """tk.Checkbutton with direct colors (ttk's renders a white box on this theme)."""
    defaults = dict(bg=BG, fg=TEXT_FG, selectcolor=PANEL_BG, activebackground=BG,
                     activeforeground=LIGHT_VIOLET, highlightthickness=0, bd=0,
                     font=FONT_NORMAL)
    defaults.update(kw)
    return tk.Checkbutton(parent, text=text, variable=variable, **defaults)
