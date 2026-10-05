"""DPI-aware presentation primitives; no market or model logic.

Inputs: widget state and already-computed portfolio percentages.
Outputs: on-screen widgets only. Updated 2026-09-06.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

UI_FONT = "Microsoft JhengHei UI"
NUMBER_FONT = "Segoe UI"
UI_COLORS = {
    "background": "#0B0E11", "sidebar": "#101419", "surface": "#171C23",
    "surface_alt": "#202731", "border": "#29313D", "text": "#F0F3F7",
    "muted": "#9BA7B7", "accent": "#F0B90B", "green": "#2ECCA5",
    "red": "#FF8291", "blue": "#8EA9FF", "btc": "#F0B90B",
    "eth": "#8EA9FF", "cash": "#2ECCA5", "track": "#2A333F",
}


def font(size: int = 15, *, bold: bool = False, number: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family=NUMBER_FONT if number else UI_FONT, size=max(13, size),
                       weight="bold" if bold else "normal")


def frame(parent, **kwargs) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0, **kwargs)


STYLE_COLORS = {
    "MetricSuccess.TLabel": "green", "MetricWarning.TLabel": "accent",
    "Positive.TLabel": "green", "Negative.TLabel": "red", "Neutral.TLabel": "muted",
    "Success.TLabel": "green", "Warning.TLabel": "accent", "Danger.TLabel": "red",
}


class Label(ctk.CTkLabel):
    """Native text with semantic colors shared by the snapshot presenter."""
    def __init__(self, parent, text="", *, size=15, bold=False, color="text", number=False, **kwargs):
        super().__init__(parent, text=text, font=font(size, bold=bold, number=number),
                         text_color=UI_COLORS.get(color, color), anchor="w", height=0, **kwargs)

    def configure(self, **kwargs):
        style = kwargs.pop("style", None)
        if style is not None:
            kwargs["text_color"] = UI_COLORS[STYLE_COLORS.get(style, "text")]
        super().configure(**kwargs)


def wrapping_label(parent, text="", *, textvariable=None, color="muted", size=14):
    label = Label(parent, text=text, textvariable=textvariable, color=color,
                  size=size, wraplength=300, justify="left")
    label.pack(fill="x", anchor="w")

    def fit(event):
        logical_width = event.width / ctk.ScalingTracker.get_widget_scaling(label)
        label.configure(wraplength=max(100, logical_width - 4))

    parent.bind("<Configure>", fit, add="+")
    return label


class Button(ctk.CTkButton):
    def __init__(self, parent, text, command, *, primary=False, width=112, **kwargs):
        super().__init__(parent, text=text, command=command, width=width, height=38,
                         corner_radius=9, border_width=0, font=font(14, bold=True),
                         fg_color=UI_COLORS["accent" if primary else "surface_alt"],
                         hover_color="#F8CE3D" if primary else "#303B49",
                         text_color=UI_COLORS["background" if primary else "text"],
                         text_color_disabled=UI_COLORS["muted"], **kwargs)
        self.bind("<Return>", lambda _: self.invoke())
        self.bind("<space>", lambda _: self.invoke())


class Card(ctk.CTkFrame):
    def __init__(self, parent, title="", *, subtitle="", color="text"):
        super().__init__(parent, fg_color=UI_COLORS["surface"], corner_radius=14,
                         border_width=1, border_color=UI_COLORS["border"])
        inner = frame(self)
        inner.pack(fill="both", expand=True, padx=20, pady=18)
        if title:
            Label(inner, title, size=17, bold=True, color=color).pack(anchor="w")
        if subtitle:
            Label(inner, subtitle, size=12, color="muted").pack(anchor="w", pady=(4, 0))
        self.content = frame(inner)
        self.content.pack(fill="both", expand=True, pady=(14 if title else 0, 0))


class AllocationBar(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, height=10, corner_radius=5, fg_color=UI_COLORS["track"])
        self.segments = [ctk.CTkFrame(self, corner_radius=4, fg_color=UI_COLORS[key], height=10)
                         for key in ("btc", "eth", "cash")]

    def set_allocation(self, percentages):
        left = 0.0
        for segment, percent in zip(self.segments, percentages):
            share = min(max(float(percent) / 100, 0), 1 - left)
            if share > 0:
                segment.place(relx=left, rely=0, relwidth=share, relheight=1)
            else:
                segment.place_forget()
            left += share


class Progress(ctk.CTkProgressBar):
    """Expose a numeric maximum while CTk renders a normalized progress value."""
    def __init__(self, parent, maximum, color="accent"):
        self.maximum = maximum
        super().__init__(parent, height=7, corner_radius=4, fg_color=UI_COLORS["track"],
                         progress_color=UI_COLORS[color], border_width=0)
        self.set(0)

    def __setitem__(self, key, value):
        if key != "value":
            raise KeyError(key)
        self.set(max(0, min(1, value / self.maximum)))


class SmoothScrollPage(ctk.CTkFrame):
    """Pixel-based wheel easing; nested text views keep their own scrolling."""
    def __init__(self, parent):
        super().__init__(parent, fg_color=UI_COLORS["background"], corner_radius=0)
        self.canvas = tk.Canvas(self, background=UI_COLORS["background"], highlightthickness=0,
                                borderwidth=0, yscrollincrement=1)
        self.bar = ctk.CTkScrollbar(self, command=self._scrollbar_command, width=10,
                                    button_color=UI_COLORS["track"], button_hover_color=UI_COLORS["muted"])
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y", padx=(6, 0))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = frame(self.canvas)
        self.window_id = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._content_changed, add="+")
        self.canvas.bind("<Configure>", self._viewport_changed)
        self._animation_id = None
        self._target = 0.0
        self.winfo_toplevel().bind("<MouseWheel>", self._wheel, add="+")
        self.bind("<Unmap>", self.stop, add="+")

    def _content_changed(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _viewport_changed(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _scrollbar_command(self, *args):
        self.stop()
        self.canvas.yview(*args)

    def _wheel(self, event):
        if not self.winfo_ismapped() or event.delta == 0:
            return
        widget = event.widget
        while widget is not None and widget is not self:
            if isinstance(widget, (tk.Text, tk.Listbox, ttk.Treeview, ctk.CTkTextbox)):
                return
            widget = getattr(widget, "master", None)
        if widget is not self:
            return
        height = self.content.winfo_height()
        limit = max(0, height - self.canvas.winfo_height())
        if not limit:
            return
        if self._animation_id is None:
            self._target = self.canvas.yview()[0] * height
        delta = event.delta / 120 * 66 * ctk.ScalingTracker.get_widget_scaling(self)
        self._target = min(limit, max(0, self._target - delta))
        if self._animation_id is None:
            self._animate()

    def _animate(self):
        height = max(1, self.content.winfo_height())
        current = self.canvas.yview()[0] * height
        distance = self._target - current
        if abs(distance) < 2:
            self.canvas.yview_moveto(self._target / height)
            self._animation_id = None
            return
        self.canvas.yview_moveto((current + distance * 0.35) / height)
        self._animation_id = self.after(12, self._animate)

    def stop(self, _event=None):
        if self._animation_id is not None:
            self.after_cancel(self._animation_id)
            self._animation_id = None


def configure_theme(root):
    ctk.set_appearance_mode("dark")
    root.configure(fg_color=UI_COLORS["background"])
    # History uses a native table, retaining selection and keyboard navigation.
    style = ttk.Style(root)
    style.theme_use("clam")
    c = UI_COLORS
    style.configure(".", font=(UI_FONT, 11), background=c["background"], foreground=c["text"])
    style.configure("TFrame", background=c["background"])
    style.configure("TLabel", background=c["background"], foreground=c["text"])
    scale = ctk.ScalingTracker.get_window_scaling(root)
    style.configure("Treeview", background=c["surface"], fieldbackground=c["surface"],
                    foreground=c["text"], rowheight=round(34 * scale), borderwidth=0,
                    lightcolor=c["border"], darkcolor=c["border"], bordercolor=c["border"])
    style.map("Treeview", background=[("selected", "#354254")], foreground=[("selected", c["text"])])
    style.configure("Treeview.Heading", background=c["surface_alt"], foreground=c["muted"],
                    padding=(8, 10), relief="flat", font=(UI_FONT, 10, "bold"))
    style.map("Treeview.Heading", background=[("active", c["track"])])
