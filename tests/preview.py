"""Render the settings window into a PNG so it can be SEEN how it looks.

Why this exists: measuring (width, padding, number of widgets) cannot reveal
that something looks sloppy - a tiny arrow, a small checkbox, poor contrast.
This script produces images that get looked at before a release.

It draws through PrintWindow (the window renders itself into memory), so the
shot comes out even when the screen is locked or something covers the window -
an ordinary screenshot would capture the lock screen in that case.

Usage:
    py tests\\preview.py            # wide (two columns) and narrow (one), cs
    py tests\\preview.py 900        # one width only
    py tests\\preview.py 1400 en    # the English version
    py tests\\preview.py 1400 cs --problem
                                    # ... showing a pulse that reached some
                                    # speakers and not others, so the warning
                                    # line can be looked at as well

The images land in _output\\ next to the project.
"""

import ctypes
import sys
import time
import tkinter as tk
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from PIL import Image

# the app lives one level up in windows\
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "windows"))

import keep_alive as K                                  # noqa: E402

PW_RENDERFULLCONTENT = 0x00000002
OUTPUT = Path(__file__).resolve().parent.parent / "_output"


def _capture(window, path):
    """Save the window contents into a PNG. Returns (width, height)."""
    window.update_idletasks()
    window.update()
    hwnd = int(window.frame(), 16)
    # the size MUST come from the window frame (GetWindowRect), not from
    # winfo_width/height - those return the interior without the title bar,
    # whereas PrintWindow draws the whole window including the bar. With the
    # wrong size the bottom of the image is cut off by the height of the bar
    # and it looks as if the app content were cut off.
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top

    u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
    window_dc = u32.GetWindowDC(hwnd)
    dc = g32.CreateCompatibleDC(window_dc)
    bmp = g32.CreateCompatibleBitmap(window_dc, width, height)
    g32.SelectObject(dc, bmp)
    if not u32.PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT):
        raise RuntimeError("PrintWindow failed - the window was not rendered")

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    header = BMI()
    header.biSize = ctypes.sizeof(BMI)
    header.biWidth = width
    header.biHeight = -height           # negative = top down
    header.biPlanes = 1
    header.biBitCount = 32
    data = ctypes.create_string_buffer(width * height * 4)
    g32.GetDIBits(dc, bmp, 0, height, data, ctypes.byref(header), 0)

    img = Image.frombuffer("RGBA", (width, height), data, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(path)

    g32.DeleteObject(bmp)
    g32.DeleteDC(dc)
    u32.ReleaseDC(hwnd, window_dc)
    return width, height


def main():
    OUTPUT.mkdir(exist_ok=True)
    problem = "--problem" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    widths = [int(args[0])] if args else [1400, 720]
    language = args[1] if len(args) > 1 else K.texts.language()
    K.texts.set_language(language)

    # A pulse that never happened would leave the status card half empty -
    # and the status card is the part worth looking at.
    K.ENGINE.last_at = time.monotonic() - 12
    K.ENGINE.last_wall = datetime.now()
    K.ENGINE.count = 4

    if problem:
        # Exactly the situation the user reported: the system default output
        # got the pulse, the saved USB speakers were unplugged. The headline
        # must NOT claim the pulse failed, and the reason must be readable.
        K.ENGINE.error = K.tx(
            "err_device_gone",
            name="Reproduktory (4 - USB Advanced Audio Device)")
        K.ENGINE.partly = True

    # Closing the window remembers its size and position - and the sizes here
    # are made up for the shot. Without putting it back, the user's window
    # would open next time exactly where the preview needed it.
    remembered = K.CFG.get("window_geometry", "")

    root = tk.Tk()
    root.withdraw()
    settings = K.Settings(root)

    def save():
        for width in widths:
            settings.open()
            window = settings.win
            window.geometry(f"{width}x900+40+40")
            window.update()
            time.sleep(0.8)              # let the redraw after the resize finish
            # A pulse in mid-flight, so the bar is actually IN the picture -
            # an empty track would say nothing about how it looks while it
            # does its job. Nothing plays; only the two numbers are set.
            K.ENGINE.playing_span = 2.0
            K.ENGINE.playing_from = time.monotonic() - 1.1
            settings._animate()
            # The status card is refreshed by a once-a-second ticker, which
            # may not have run yet when the shot is taken - ask for it.
            settings._refresh_status()
            window.update()
            suffix = "-problem" if problem else ""
            name = f"preview-settings-{width}-{language}{suffix}.png"
            print(f"{name}: {_capture(window, OUTPUT / name)}")
            # the bottom of the window - that is where content gets cut off
            # and unreachable. Scroll only AFTER the layout has settled.
            window.update()
            settings.canvas.yview_moveto(1.0)
            window.update()
            time.sleep(0.3)
            name = f"preview-settings-{width}-{language}{suffix}-bottom.png"
            print(f"{name}: {_capture(window, OUTPUT / name)}")
            K.ENGINE.playing_from = 0.0     # stop the faked pulse again
            settings.close()
        root.destroy()

    root.after(1200, save)
    root.mainloop()

    K.CFG["window_geometry"] = remembered
    K.save_cfg(K.CFG)


if __name__ == "__main__":
    main()
