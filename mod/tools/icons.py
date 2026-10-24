#!/usr/bin/env python3
"""Draw the file tree's 16x16 icons.

Kept as a script rather than as thirteen opaque PNGs, so a colour or a glyph
is a line to edit rather than a binary to redraw. Run it from anywhere:

    python3 mod/tools/icons.py

Everything shares one page: a sheet of paper with a folded corner, the same
size and outline in every icon, so the badge on it is the only thing the eye
has to tell apart. Sixteen pixels is not much room for a picture of a file
format — it is enough for a silhouette, which is how Minecraft's own items
work.
"""

import os
import struct
import zlib

SIZE = 16

# The page. Eleven wide by fourteen tall with a three-pixel fold off the
# top-right corner, which is what makes it a sheet rather than a rectangle.
PAGE_X0, PAGE_X1 = 2, 12
PAGE_Y0, PAGE_Y1 = 1, 14
FOLD_X = 9

OUTLINE = (0x2E, 0x2E, 0x33, 255)
PAPER = (0xF2, 0xF2, 0xEC, 255)
FOLD = (0xC6, 0xC6, 0xBE, 255)

GREY = (0x8A, 0x8A, 0x90, 255)
DARK = (0x3A, 0x3A, 0x42, 255)
BLUE = (0x4A, 0x78, 0xC8, 255)
SKY = (0xA8, 0xD0, 0xE8, 255)
RED = (0xD0, 0x40, 0x30, 255)
GREEN = (0x3F, 0xA0, 0x50, 255)
ORANGE = (0xE0, 0x88, 0x28, 255)
CYAN = (0x38, 0xA8, 0xB8, 255)
YELLOW = (0xE8, 0xC8, 0x30, 255)
CLEAR = (0, 0, 0, 0)


def page_cells():
    """The paper, the fold flap, and the outline that rings them."""
    body = set()
    for y in range(PAGE_Y0, PAGE_Y1 + 1):
        for x in range(PAGE_X0, PAGE_X1 + 1):
            if x - FOLD_X > y - PAGE_Y0:
                continue        # cut away by the fold
            body.add((x, y))
    flap = {(x, y) for (x, y) in body if x >= FOLD_X and y <= PAGE_Y0 + 3}
    outline = {
        (x, y) for (x, y) in body
        if any((x + dx, y + dy) not in body for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
    }
    return body, flap, outline


BODY, FLAP, OUTLINE_CELLS = page_cells()
INTERIOR = BODY - OUTLINE_CELLS


def blank():
    return [[CLEAR] * SIZE for _ in range(SIZE)]


def page():
    grid = blank()
    for (x, y) in BODY:
        grid[y][x] = PAPER
    for (x, y) in FLAP:
        grid[y][x] = FOLD
    for (x, y) in OUTLINE_CELLS:
        grid[y][x] = OUTLINE
    return grid


def put(grid, cells, colour, clip=True):
    for (x, y) in cells:
        if clip and (x, y) not in INTERIOR:
            continue
        if 0 <= x < SIZE and 0 <= y < SIZE:
            grid[y][x] = colour


def rect(x0, y0, x1, y1):
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def rows(spec, x0, y0):
    """A little ASCII sprite: '.' is nothing, anything else is a pixel."""
    out = []
    for j, line in enumerate(spec):
        for i, ch in enumerate(line):
            if ch != ".":
                out.append((x0 + i, y0 + j))
    return out


def lines(*ys, x0=4, x1=10):
    out = []
    for y in ys:
        out += rect(x0, y, x1, y)
    return out


ICONS = {}


def icon(name):
    def wrap(fn):
        ICONS[name] = fn
        return fn
    return wrap


@icon("file")
def _file():
    return page()


@icon("text")
def _text():
    g = page()
    put(g, lines(6, 8, 10), GREY)
    put(g, rect(4, 12, 8, 12), GREY)
    return g


@icon("doc")
def _doc():
    g = page()
    put(g, rect(4, 5, 10, 6), BLUE)
    put(g, lines(8, 10), GREY)
    put(g, rect(4, 12, 8, 12), GREY)
    return g


@icon("pdf")
def _pdf():
    g = page()
    put(g, rect(3, 8, 11, 11), RED)
    put(g, [(4, 9), (4, 10), (6, 9), (6, 10), (8, 9), (8, 10), (10, 9), (10, 10)], PAPER)
    return g


@icon("sheet")
def _sheet():
    g = page()
    put(g, rect(4, 5, 10, 6), GREEN)
    put(g, lines(8, 10, 12), GREEN)
    put(g, rect(6, 7, 6, 12) + rect(8, 7, 8, 12), GREEN)
    return g


@icon("slides")
def _slides():
    g = page()
    put(g, rect(4, 10, 4, 12), ORANGE)
    put(g, rect(6, 7, 6, 12), ORANGE)
    put(g, rect(8, 9, 8, 12), ORANGE)
    put(g, rect(10, 6, 10, 12), ORANGE)
    put(g, rect(3, 13, 11, 13), GREY)
    return g


@icon("image")
def _image():
    g = page()
    put(g, rect(4, 5, 10, 12), SKY)
    put(g, rect(5, 6, 6, 7), YELLOW)
    put(g, rows([
        "...X...",
        "..XXX..",
        ".XXXXX.",
        "XXXXXXX",
    ], 4, 9), GREEN)
    return g


@icon("audio")
def _audio():
    g = page()
    put(g, rect(7, 5, 7, 11), DARK)
    put(g, rows([
        "XX",
        "XX",
        ".X",
    ], 8, 5), DARK)
    put(g, rect(4, 10, 6, 12), DARK)
    put(g, rect(7, 12, 7, 12), DARK)
    return g


@icon("video")
def _video():
    g = page()
    put(g, rows([
        "X......",
        "XXX....",
        "XXXXX..",
        "XXXXXXX",
        "XXXXX..",
        "XXX....",
        "X......",
    ], 4, 6), DARK)
    return g


@icon("code")
def _code():
    # Ragged lines rather than angle brackets. A pair of chevrons is one pixel
    # wide at this size and reads as parentheses; indentation reads as source
    # at a glance, and the colour is what separates it from a plain text file.
    g = page()
    put(g, rect(4, 6, 7, 6), CYAN)
    put(g, rect(6, 8, 10, 8), CYAN)
    put(g, rect(6, 10, 8, 10), CYAN)
    put(g, rect(4, 12, 9, 12), CYAN)
    return g


@icon("config")
def _config():
    g = page()
    put(g, rows([
        ".X.X.X.",
        ".XXXXX.",
        "XXX.XXX",
        "XX...XX",
        "XXX.XXX",
        ".XXXXX.",
        ".X.X.X.",
    ], 4, 6), GREY)
    return g


@icon("archive")
def _archive():
    g = page()
    put(g, rect(7, 4, 7, 13), DARK)
    for y in range(5, 14):
        put(g, [(6, y) if y % 2 == 0 else (8, y)], GREY)
    put(g, rect(6, 3, 8, 4), GREY)
    return g


@icon("font")
def _font():
    g = page()
    put(g, rows([
        "...X...",
        "..X.X..",
        "..X.X..",
        ".X...X.",
        ".XXXXX.",
        ".X...X.",
        "X.....X",
        "X.....X",
    ], 4, 5), DARK)
    return g


@icon("binary")
def _binary():
    g = page()
    put(g, rect(4, 7, 10, 11), DARK)
    put(g, rect(6, 8, 8, 10), GREY)
    put(g, [(5, 6), (7, 6), (9, 6), (5, 12), (7, 12), (9, 12)], DARK)
    return g


def write(path, grid):
    raw = b"".join(b"\x00" + b"".join(bytes(p) for p in row) for row in grid)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "src", "main", "resources",
                       "assets", "mcshell", "textures", "gui", "file")
    os.makedirs(out, exist_ok=True)
    for name, draw in ICONS.items():
        write(os.path.join(out, name + ".png"), draw())
    print(f"wrote {len(ICONS)} icons to {os.path.normpath(out)}")


if __name__ == "__main__":
    main()
