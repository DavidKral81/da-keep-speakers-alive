"""
Generates the app icon (keep_alive.ico) + a preview (keep_alive.png).

The drawing is NOT here. It is icon_image() in windows/keep_alive.py - the
same function the tray icon uses - and this tool only asks for it at a large
size and saves it. There used to be a second drawing here (a blue rounded
square with a gradient and three waves), so the tray showed one icon and the
Start menu another, which is how the problem came to light. One drawing
cannot drift from itself.

The colour is ORANGE, and deliberately not the green of the tray's "all
good": the icon file sits in the Start menu next to Da BT Dynamic Lock, and
the two must not be mistaken for each other at 16 px.

Drawn at 1024 px and scaled down, so it stays sharp at 16 px on the taskbar.

The result is written straight into windows/icons/, which is where the app
loads it from - a tool that saves next to itself would leave the real icons
untouched.

Run:  py tools\\make_icons.py
"""

import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
# Importing the app to borrow its drawing. It reads its settings on import
# (and writes config.json only when there is none, exactly as a first run
# would), but nothing else happens until main() is called.
sys.path.insert(0, str(HERE.parent / "windows"))
from keep_alive import icon_image                            # noqa: E402

OUT = HERE.parent / "windows" / "icons"
SIZES = [256, 128, 64, 48, 32, 24, 16]

# #e8781a - readable on a light taskbar and on a dark one, and far enough
# from the blue padlock of the sister project to tell them apart small.
ORANGE = (232, 120, 26, 255)

# Pillow draws without antialiasing, so every frame is drawn four times too
# big and scaled down - straight-to-size frames came out with ragged, broken
# waves at 24 and 32 px. What keeps the small ones readable is not the drawing
# size but shown_at: icon_image() thickens the lines and drops the second wave
# based on how big the frame will really be seen.
SUPERSAMPLE = 4


def frame(size):
    """One frame of the icon, drawn big and scaled to `size`."""
    big = icon_image(ORANGE, size * SUPERSAMPLE, shown_at=size)
    return big.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frames = [frame(v) for v in SIZES]
    # append_images: every size comes from its OWN drawing. Handing Pillow a
    # single 256 px image and a list of sizes makes it scale that one down for
    # all of them, which is how the 16 px frame became an orange blob.
    frames[0].save(OUT / "keep_alive.ico", format="ICO",
                   sizes=[(v, v) for v in SIZES],
                   append_images=frames[1:])
    frames[0].save(OUT / "keep_alive.png")
    print(f"done ({', '.join(str(v) for v in SIZES)} px) -> {OUT}:")
    print("  keep_alive.ico + keep_alive.png")


if __name__ == "__main__":
    main()
