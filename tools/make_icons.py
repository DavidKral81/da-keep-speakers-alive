"""
Generates the app icon (keep_alive.ico) + a preview (keep_alive.png).

Everything is drawn at a large resolution and only then scaled down, so that
it stays sharp even at 16 px on the taskbar.

The result is written straight into windows/icons/, which is where the app
loads it from - a tool that saves next to itself would leave the real icons
untouched.

Run:  py tools\\make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "windows" / "icons"
SIZES = [256, 128, 64, 48, 32, 24, 16]
Z = 1024                      # drawing resolution


def background():
    """The backdrop with a diagonal gradient and a soft gloss on top."""
    img = Image.new("RGBA", (Z, Z), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (Z, Z))
    p = gradient.load()
    start, end = (74, 130, 214), (18, 38, 76)     # #4a82d6 -> #12264c
    for y in range(Z):
        for x in range(Z):
            k = (x / Z * 0.35 + y / Z * 0.65)     # diagonal gradient
            p[x, y] = (int(start[0] + (end[0] - start[0]) * k),
                       int(start[1] + (end[1] - start[1]) * k),
                       int(start[2] + (end[2] - start[2]) * k), 255)
    mask = Image.new("L", (Z, Z), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, Z - 1, Z - 1),
                                           radius=int(Z * 0.23), fill=255)
    img.paste(gradient, (0, 0), mask)

    gloss = Image.new("RGBA", (Z, Z), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse(
        (-int(Z * 0.35), -int(Z * 0.75), int(Z * 1.35), int(Z * 0.42)),
        fill=(255, 255, 255, 34))
    img.alpha_composite(Image.composite(
        gloss, Image.new("RGBA", (Z, Z), (0, 0, 0, 0)), mask))
    return img


def speaker(img, color=(255, 255, 255, 255), shadow=True):
    """A speaker with three waves - the motif the tray icon uses as well."""
    if shadow:
        layer = Image.new("RGBA", (Z, Z), (0, 0, 0, 0))
        _speaker_shape(ImageDraw.Draw(layer), (8, 20, 42, 120), offset=Z * 0.02)
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(Z * 0.02)))
    _speaker_shape(ImageDraw.Draw(img), color)


def _speaker_shape(d, color, offset=0.0):
    o = int(offset)
    # the box and the cone
    d.rounded_rectangle((int(Z * .17) + o, int(Z * .40) + o,
                         int(Z * .33) + o, int(Z * .60) + o),
                        radius=int(Z * .03), fill=color)
    d.polygon([(int(Z * .31) + o, int(Z * .41) + o),
               (int(Z * .52) + o, int(Z * .22) + o),
               (int(Z * .52) + o, int(Z * .78) + o),
               (int(Z * .31) + o, int(Z * .59) + o)], fill=color)
    # three waves, each one thinner than the box so they stay separate at 16 px
    for r, width in ((int(Z * .13), int(Z * .050)),
                     (int(Z * .23), int(Z * .048)),
                     (int(Z * .33), int(Z * .046))):
        cx, cy = int(Z * .54) + o, int(Z * .50) + o
        d.arc((cx - r, cy - r, cx + r, cy + r), 300, 60, fill=color, width=width)


def green_circle():
    """Variant B - the same motif in a green circle, like the tray icon.

    The tray icon itself is drawn at 64 px in keep_alive.py (that is all it
    needs); here the same motif is drawn large, so it stays sharp on the
    taskbar too.
    """
    img = Image.new("RGBA", (Z, Z), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((int(Z * .02),) * 2 + (int(Z * .98),) * 2,
                                fill=(34, 160, 80, 255))
    speaker(img, shadow=False)
    return img


def save(img, name):
    OUT.mkdir(parents=True, exist_ok=True)
    small = img.resize((256, 256), Image.LANCZOS)
    small.save(OUT / f"{name}.png")
    small.save(OUT / f"{name}.ico", format="ICO",
               sizes=[(v, v) for v in SIZES])
    print(f"  {name}.ico + {name}.png")


def main():
    blue = background()
    speaker(blue)

    print(f"done ({', '.join(str(v) for v in SIZES)} px) -> {OUT}:")
    save(blue, "keep_alive")             # variant A - blue, used by the window
    save(green_circle(), "keep_alive_green")   # variant B - the tray motif


if __name__ == "__main__":
    main()
