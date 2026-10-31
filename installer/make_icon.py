"""Draw the app icon: the llama from the setup page's game, on a page, on a blue tile.
Original pixel art, from the same rows of text as game.js; no outside artwork.

    python installer/make_icon.py OUT.ico [PREVIEW.png]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

COLORS = {"o": (74, 48, 32), "c": (244, 233, 207), "b": (201, 154, 107), "p": (233, 163, 168),
          "e": (27, 27, 27)}
LLAMA = [                       # game.js SPRITES.run1
    "...........oo...",
    "..........ocpo..",
    "..........occo..",
    ".........occeco.",
    ".........occcccoo",
    ".........occcco..",
    ".........occo....",
    ".........occo....",
    ".........occo....",
    ".oooooooobcco....",
    "ocbcbcbcbcccco...",
    "occcccccccccco...",
    "occcccccccccco...",
    ".occcccccccco....",
    "..oco....oco.....",
    "..oco.....oco....",
    "..oo.......oo....",
]
BLUE, PAGE, LINES = (31, 58, 95), (255, 255, 255), (157, 183, 214)


def draw(size: int) -> Image.Image:
    """The icon at `size` pixels: drawn on a 32-pixel grid, then scaled without blur."""
    grid = 32
    img = Image.new("RGBA", (grid, grid), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, grid - 1, grid - 1), radius=6, fill=BLUE)
    d.polygon([(6, 4), (21, 4), (26, 9), (26, 28), (6, 28)], fill=PAGE)      # a page
    d.polygon([(21, 4), (21, 9), (26, 9)], fill=LINES)                       # folded corner
    for y in (9, 12, 15):
        d.line((9, y, 18, y), fill=LINES)
    for y, row in enumerate(LLAMA):                                          # the llama
        for x, ch in enumerate(row):
            if ch != ".":
                img.putpixel((x + 12, y + 13), COLORS[ch] + (255,))
    return img.resize((size, size), Image.NEAREST)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "app.ico")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big = draw(256)
    big.save(out, sizes=[(s, s) for s in sizes],
             append_images=[draw(s) for s in sizes if s != 256])
    if len(sys.argv) > 2:
        big.save(sys.argv[2])
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
