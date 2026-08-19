"""Small things that are DRAWN rather than left to Tk: the checkbox mark, the
radio mark and the language flags.

Tk draws its own marks a few pixels big, which looks sloppy, so they are drawn
by hand instead. This module exists so that the drawing lives in ONE place -
the app window and the installer both reach for it, so the two cannot end up
looking different.

Usage:
    canvas = tk.Canvas(parent, width=marks.SIZE, height=marks.SIZE, ...)
    marks.draw(canvas, on=True)
    marks.LanguageFlags(header, self._change_language, "#e6ebf2").pack(...)
"""

import tkinter as tk

import texts

SIZE = 19


def draw(canvas, on, round_mark=False, hovered=False):
    """Repaint the mark: a square for a checkbox, a circle for a radio."""
    canvas.delete("all")
    z = SIZE
    outline = "#8fa0b5" if hovered else "#6b7684"
    if on:
        outline = "#7cc0ff" if hovered else "#4a9eff"
    fill = "#2563eb" if on else "#1b2029"
    if round_mark:
        canvas.create_oval(2, 2, z - 3, z - 3, outline=outline, width=2,
                           fill=fill)
        if on:
            canvas.create_oval(6, 6, z - 7, z - 7, outline="", fill="#ffffff")
    else:
        canvas.create_rectangle(2, 2, z - 3, z - 3, outline=outline, width=2,
                                fill=fill)
        if on:       # tick
            canvas.create_line(5, z // 2, z // 2 - 1, z - 7, z - 6, 5,
                               fill="#ffffff", width=2, capstyle="round",
                               joinstyle="round")


class LanguageFlags(tk.Frame):
    """The language switch: one small flag per language, top right of the
    window.

    Drawn instead of loaded from image files - a bitmap would mean another
    file per language to ship, and at this size a scaled PNG goes soft.

    The current language is marked by a bar UNDER its flag, not by dimming
    the other one: a Tk canvas has no transparency, so "dimmed" would have to
    be a second set of colours for every flag, kept in step by hand.

    It lives here, next to the checkbox mark, because the installer needs the
    same switch. Someone who installed the app in a language they cannot read
    has to be able to change it before uninstalling too - and a flag stays
    readable even then, unlike a drop-down whose label is a word.
    """

    # 3:2, as most flags are. Not smaller: at 30x20 the Union Jack turns into
    # a red smudge, and the project already had to redraw Tk's own tiny
    # checkboxes for the same reason.
    W, H = 36, 24
    UNDERLINE = 3               # the "this one is active" bar
    GAP = 10

    def __init__(self, parent, action, accent):
        super().__init__(parent, bg=parent["bg"])
        for code, name in texts.LANGUAGES:
            canvas = tk.Canvas(self, width=self.W,
                               height=self.H + 2 + self.UNDERLINE,
                               bg=parent["bg"], highlightthickness=0,
                               cursor="hand2")
            canvas.pack(side="left", padx=(self.GAP, 0))
            # the loop variable has to be captured, or every flag would
            # switch to the language of the last one built
            canvas.bind("<Button-1>", (lambda c: lambda e: action(c))(code))
            self._draw(canvas, code, code == texts.language(), accent)

    def _draw(self, canvas, code, active, accent):
        w, h = self.W, self.H
        if code == "cs":
            canvas.create_rectangle(0, 0, w, h / 2, fill="#ffffff", width=0)
            canvas.create_rectangle(0, h / 2, w, h, fill="#d7141a", width=0)
            canvas.create_polygon(0, 0, w * 0.55, h / 2, 0, h,
                                  fill="#11457e", width=0)
        else:
            canvas.create_rectangle(0, 0, w, h, fill="#012169", width=0)
            # The diagonals are POLYGONS, not thick lines: a wide line ends
            # square across its own direction, so at the corners it sticks
            # out past the flag - and a Tk canvas cannot clip it back.
            for t, colour in ((10, "#ffffff"), (3.5, "#c8102e")):
                canvas.create_polygon(0, 0, t, 0, w, h - t, w, h, w - t, h,
                                      0, t, fill=colour, width=0)
                canvas.create_polygon(w, 0, w - t, 0, 0, h - t, 0, h, t, h,
                                      w, t, fill=colour, width=0)
            canvas.create_rectangle(w / 2 - 4.5, 0, w / 2 + 4.5, h,
                                    fill="#ffffff", width=0)
            canvas.create_rectangle(0, h / 2 - 4.5, w, h / 2 + 4.5,
                                    fill="#ffffff", width=0)
            canvas.create_rectangle(w / 2 - 2.5, 0, w / 2 + 2.5, h,
                                    fill="#c8102e", width=0)
            canvas.create_rectangle(0, h / 2 - 2.5, w, h / 2 + 2.5,
                                    fill="#c8102e", width=0)
        # a thin edge, or the white half of a flag bleeds into the dark window
        canvas.create_rectangle(0, 0, w - 1, h - 1, outline="#55606f")
        if active:
            canvas.create_rectangle(0, h + 2, w, h + 2 + self.UNDERLINE,
                                    fill=accent, width=0)
