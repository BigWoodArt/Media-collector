import tkinter as tk

import theme


class Tooltip:
    """Attach a simple hover tooltip to any tkinter/ttk widget."""

    def __init__(self, widget, text, delay=350):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after_id = None
        self._tip_window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None):
        self._after_id = self.widget.after(self.delay, self._show)

    def _show(self):
        if self._tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6

        self._tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        try:
            tw.attributes("-topmost", True)
        except tk.TclError:
            pass

        tk.Label(tw, text=self.text, justify="left", background=theme.PANEL_BG,
                 foreground=theme.TEXT_FG, relief="solid", borderwidth=1,
                 wraplength=280, padx=8, pady=5, font=theme.FONT_NORMAL).pack()

    def _hide(self, event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip_window:
            self._tip_window.destroy()
            self._tip_window = None


def tip(widget, text):
    """Attaches a hover tooltip to an existing widget. Returns the widget."""
    widget.tooltip = Tooltip(widget, text)      # .tooltip.text can be changed later
    return widget


def add_help(parent, text, **pack_kw):
    """Small '(?)' label with a hover tooltip, packed in place."""
    lbl = tk.Label(parent, text="(?)", bg=theme.BG, fg=theme.LIGHT_VIOLET,
                   font=theme.FONT_SMALL, cursor="question_arrow")
    tip(lbl, text)
    lbl.pack(**pack_kw)
    return lbl
