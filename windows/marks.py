"""How a checkbox and a radio mark are drawn.

Tk draws its own marks a few pixels big, which looks sloppy, so they are drawn
by hand instead. This module exists so that the drawing lives in ONE place -
the app window today, the installer tomorrow.

Usage:
    canvas = tk.Canvas(parent, width=marks.SIZE, height=marks.SIZE, ...)
    marks.draw(canvas, on=True)
"""

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
