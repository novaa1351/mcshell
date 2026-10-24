"""Minecraft's own pixels, outside Minecraft.

Two things in this session have to draw a Minecraft screen without being
Minecraft: the lock screen, which cannot be in the game because credentials
never go through the game client, and the notification toasts, which cannot be
in the game because the game is the backdrop and a toast drawn there is behind
every window that matters.

Both draw out of the installed client jar rather than out of lookalikes, so
this is the decoder, the canvas and the font, in one place. A second copy of a
PNG reader and a glyph table would go out of step with the first one, and the
symptom would be a screen that is *nearly* Minecraft, which is worse than one
that is obviously not.

Nothing here knows what it is drawing. The screens do.
"""

from __future__ import annotations

import json
import os
import struct
import unicodedata
import zlib
from pathlib import Path

# --- where Minecraft is ------------------------------------------------------

#: Checked in order. The environment first, so a different install can be
#: pointed at without editing this; then the real session's Prism instance;
#: then the dev client's loom cache.
JAR_CANDIDATES = (
    "$MCSHELL_MC_JAR",
    "~/.local/share/PrismLauncher/libraries/com/mojang/minecraft/1.21.1/"
    "minecraft-1.21.1-client.jar",
    "~/.gradle/caches/fabric-loom/1.21.1/minecraft-client.jar",
)


def find_jar() -> Path | None:
    for candidate in JAR_CANDIDATES:
        path = Path(os.path.expandvars(os.path.expanduser(candidate)))
        if str(path) != candidate and path.is_file():
            return path
    return None


def gui_scale(width: int, height: int) -> int:
    """Minecraft's own auto scale: as large as fits 320x240 of GUI space."""
    scale = 1
    while (scale + 1) <= 6 and width // (scale + 1) >= 320 and height // (scale + 1) >= 240:
        scale += 1
    return scale


# --- PNG in ------------------------------------------------------------------

def decode(data: bytes) -> tuple[int, int, list[list[tuple[int, int, int, int]]]]:
    """Enough of PNG to read Minecraft's textures. RGBA rows out."""
    pos = 8
    idat = b""
    palette = trns = None
    width = height = depth = colour = 0
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", chunk[:10])
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            trns = chunk
        pos += 12 + length

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    bits = channels * depth
    stride = (width * bits + 7) // 8
    step = max(1, bits // 8)

    raw = zlib.decompress(idat)
    lines: list[bytes] = []
    previous = bytearray(stride)
    at = 0
    for _ in range(height):
        filt = raw[at]
        at += 1
        line = bytearray(raw[at:at + stride])
        at += stride
        for i in range(stride):
            a = line[i - step] if i >= step else 0
            b = previous[i]
            c = previous[i - step] if i >= step else 0
            if filt == 1:
                line[i] = (line[i] + a) & 255
            elif filt == 2:
                line[i] = (line[i] + b) & 255
            elif filt == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif filt == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc
                                      else b if pb <= pc else c)) & 255
        previous = line
        lines.append(bytes(line))

    out = []
    for line in lines:
        row = []
        for x in range(width):
            if colour == 3:
                if depth == 8:
                    index = line[x]
                else:
                    per = 8 // depth
                    shift = 8 - depth * (x % per + 1)
                    index = (line[x // per] >> shift) & ((1 << depth) - 1)
                r, g, b = palette[index * 3:index * 3 + 3]
                alpha = trns[index] if trns and index < len(trns) else 255
                row.append((r, g, b, alpha))
            elif colour == 6:
                px = line[x * 4:x * 4 + 4]
                row.append((px[0], px[1], px[2], px[3]))
            elif colour == 2:
                px = line[x * 3:x * 3 + 3]
                row.append((px[0], px[1], px[2], 255))
            elif colour == 4:
                px = line[x * 2:x * 2 + 2]
                row.append((px[0], px[0], px[0], px[1]))
            else:
                row.append((line[x], line[x], line[x], 255))
        out.append(row)
    return width, height, out


# --- the canvas --------------------------------------------------------------

def _rgba(colour) -> tuple[int, int, int, int]:
    return colour if len(colour) == 4 else (*colour, 255)


class Surface:
    """Physical pixels, RGBA, one flat bytearray.

    RGBA rather than RGB because a toast is a rounded rectangle over whatever
    is behind it; the lock screen fills every pixel and simply never uses the
    alpha it is given.
    """

    def __init__(self, width: int, height: int, colour=(0, 0, 0, 0)) -> None:
        self.width = width
        self.height = height
        self.stride = width * 4
        self.data = bytearray(bytes(_rgba(colour)) * (width * height))

    def tile(self, texture, scale: int, shade: float = 1.0) -> None:
        """Minecraft's own tiled background, darkened as the game does."""
        size = len(texture)
        block = size * scale
        # One block of rows built once, then handed out to every row that
        # repeats it. Copied rather than shared: the blits below mutate.
        pattern: list[bytes] = []
        for y in range(block):
            source = texture[(y // scale) % size]
            line = bytearray()
            for px in source:
                line += bytes((int(px[0] * shade), int(px[1] * shade),
                               int(px[2] * shade), px[3])) * scale
            repeats = self.width // (size * scale) + 1
            pattern.append(bytes(line * repeats)[:self.stride])
        for y in range(self.height):
            start = y * self.stride
            self.data[start:start + self.stride] = pattern[y % block]

    def fill(self, x: int, y: int, w: int, h: int, colour) -> None:
        x0, x1 = max(0, x), min(self.width, x + w)
        if x1 <= x0:
            return
        run = bytes(_rgba(colour)) * (x1 - x0)
        for j in range(max(0, y), min(self.height, y + h)):
            start = j * self.stride + x0 * 4
            self.data[start:start + len(run)] = run

    def blit(self, texture, x: int, y: int, scale: int,
             sx: int = 0, sy: int = 0, sw: int | None = None, sh: int | None = None,
             tint: tuple[int, int, int] | None = None) -> None:
        """Nearest-neighbour, alpha as a cutout.

        Every texture this draws is 0 or 255 — measured, not assumed: the
        advancement toast's only transparent pixels are the eighteen in its
        four rounded corners.
        """
        sw = sw if sw is not None else len(texture[0])
        sh = sh if sh is not None else len(texture)
        for j in range(sh):
            source = texture[sy + j]
            for i in range(sw):
                px = source[sx + i]
                if not px[3]:
                    continue
                r, g, b = px[0], px[1], px[2]
                if tint is not None:
                    r = r * tint[0] // 255
                    g = g * tint[1] // 255
                    b = b * tint[2] // 255
                run = bytes((r, g, b, px[3])) * scale
                left = x + i * scale
                if left < 0 or left >= self.width:
                    continue
                for k in range(scale):
                    row = y + j * scale + k
                    if 0 <= row < self.height:
                        start = row * self.stride + left * 4
                        self.data[start:start + scale * 4] = run

    def png(self) -> bytes:
        raw = bytearray()
        for y in range(self.height):
            raw += b"\x00"
            raw += self.data[y * self.stride:(y + 1) * self.stride]

        def chunk(kind: bytes, body: bytes) -> bytes:
            block = kind + body
            return (struct.pack(">I", len(body)) + block
                    + struct.pack(">I", zlib.crc32(block)))

        return (b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", self.width, self.height,
                                             8, 6, 0, 0, 0))
                # Level 1: these images are mostly a repeated tile, so this is
                # within a few percent of level 9 and several times faster.
                + chunk(b"IDAT", zlib.compress(bytes(raw), 1))
                + chunk(b"IEND", b""))

    def write(self, path: str) -> None:
        Path(path).write_bytes(self.png())

    def cairo(self) -> bytearray:
        """The same pixels as cairo's ARGB32: premultiplied, native order.

        Little-endian only, which every machine this runs on is.

        A surface with no transparency in it needs no premultiplying at all —
        the conversion is purely a red/blue swap — and an extended-slice
        assignment on a bytearray does that in C rather than a Python loop.
        Measured on the boot screen's 1920x1080 background: **566ms the long
        way, 10ms this way**, byte for byte the same answer, with the opacity
        test itself costing 3ms. That is the difference between a loading
        screen that appears before Prism's window and one that does not.

        Toasts and the volume bar are rounded rectangles, so they keep the
        long path; they are small and it does not matter there.
        """
        data = self.data
        alpha = data[3::4]
        if alpha.count(255) == len(alpha):
            out = bytearray(len(data))
            out[0::4] = data[2::4]
            out[1::4] = data[1::4]
            out[2::4] = data[0::4]
            out[3::4] = alpha
            return out

        out = bytearray(len(self.data))
        for i in range(0, len(data), 4):
            a = data[i + 3]
            if a == 255:
                out[i] = data[i + 2]
                out[i + 1] = data[i + 1]
                out[i + 2] = data[i]
                out[i + 3] = 255
            elif a:
                out[i] = data[i + 2] * a // 255
                out[i + 1] = data[i + 1] * a // 255
                out[i + 2] = data[i] * a // 255
                out[i + 3] = a
        return out


# --- Minecraft's font --------------------------------------------------------

#: The sheet, and the file that says which glyph is in which cell. The layout
#: is *not* Latin-1 — cell 0xB0 is a box-drawing character, not a degree sign —
#: so the mapping is read rather than assumed.
FONT_TEXTURE = "assets/minecraft/textures/font/ascii.png"
FONT_PROVIDER = "assets/minecraft/font/include/default.json"

#: What to do with a character the sheet has never had. Punctuation that
#: word processors and chat clients insert without being asked, mostly:
#: a message that arrives with a real em dash in it should not lose the dash.
#: Anything in the sheet already is left alone, so the guillemets and the
#: pound sign that *are* in there never reach this table.
SUBSTITUTES = {
    0x00A0: " ", 0x2007: " ", 0x202F: " ", 0x2009: " ", 0x200A: " ",
    0x2010: "-", 0x2011: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-",
    0x2015: "-", 0x2212: "-",
    0x2018: "'", 0x2019: "'", 0x201B: "'", 0x2032: "'",
    0x201C: '"', 0x201D: '"', 0x201E: '"', 0x2033: '"',
    0x201A: ",", 0x2026: "...", 0x2022: "*", 0x00B7: "*",
    0x2039: "<", 0x203A: ">", 0x2190: "<-", 0x2192: "->",
    0x00A9: "(c)", 0x00AE: "(R)", 0x2122: "(TM)",
}


def load_font(zf) -> "Font":
    """The game's own font, sheet and layout together."""
    _, _, sheet = decode(zf.read(FONT_TEXTURE))
    chars = None
    try:
        for provider in json.loads(zf.read(FONT_PROVIDER))["providers"]:
            if str(provider.get("file", "")).endswith("ascii.png"):
                chars = provider["chars"]
                break
    except Exception:
        pass                # an older jar; fall back to the cell order
    return Font(sheet, chars)


class Font:
    """`ascii.png`: sixteen by sixteen cells of eight by eight pixels.

    Advances are measured out of the sheet the way the game measures them —
    the rightmost lit column plus two, and four for a space — so a line of
    text here is the same width it would be in the game.
    """

    CELL = 8

    def __init__(self, sheet, chars: list[str] | None = None) -> None:
        self.sheet = sheet
        if chars is None:
            chars = ["".join(chr(r * 16 + c) for c in range(16))
                     for r in range(16)]
        self.cells: dict[int, tuple[int, int]] = {}
        for row, line in enumerate(chars):
            for col, ch in enumerate(line):
                if ch != "\x00":
                    self.cells[ord(ch)] = (col, row)
        self.advance: dict[int, int] = {}
        for code, (col, row) in self.cells.items():
            right = -1
            for x in range(self.CELL):
                for y in range(self.CELL):
                    if sheet[row * self.CELL + y][col * self.CELL + x][3]:
                        right = max(right, x)
                        break
            self.advance[code] = 4 if right < 0 else right + 2
        self.advance[32] = 4

    def encode(self, text: str) -> str:
        """The same text, in characters this font actually has.

        Notification bodies are whatever an application felt like sending, and
        the game's ASCII sheet is ninety-five glyphs. Accents are stripped to
        their base letter, the punctuation people paste is replaced, and an
        emoji is dropped rather than drawn as a question mark — a line of
        question marks says less than the words on either side of it.
        """
        out = []
        for ch in text:
            code = ord(ch)
            if code in self.cells:
                out.append(ch)
                continue
            sub = SUBSTITUTES.get(code)
            if sub is None:
                sub = "".join(c for c in unicodedata.normalize("NFKD", ch)
                              if ord(c) in self.cells)
            if not sub:
                if unicodedata.category(ch) in ("So", "Sk", "Cf", "Mn", "Cs",
                                                "Co", "Cc"):
                    continue
                sub = "?"
            out.append(sub)
        return "".join(out)

    def width(self, text: str) -> int:
        return sum(self.advance.get(ord(c), 0) for c in self.encode(text))

    def trim(self, text: str, limit: int) -> str:
        """Cut to fit, the way vanilla cuts a line that will not fit.

        An ellipsis rather than an overflow, because a notification's text is
        whatever an application felt like sending and a toast is 160 pixels
        wide no matter what that was.
        """
        text = self.encode(text)
        if self.width(text) <= limit:
            return text
        ellipsis = "..."
        room = limit - self.width(ellipsis)
        if room <= 0:
            return ""
        out = ""
        used = 0
        for ch in text:
            step = self.advance.get(ord(ch), 0)
            if used + step > room:
                break
            out += ch
            used += step
        return out.rstrip() + ellipsis

    def draw(self, surface: Surface, text: str, x: int, y: int, scale: int,
             colour: tuple[int, int, int], shadow: bool = True) -> None:
        """One line of text. `shadow` because the game is not consistent:
        screens draw with it, `AdvancementToast` draws without it."""
        text = self.encode(text)
        # Minecraft's drop shadow: the same glyphs one pixel down and right, at
        # a quarter of the brightness.
        dark = tuple((c & 0xFC) >> 2 for c in colour)
        passes = ((dark, 1, 1), (colour, 0, 0)) if shadow else ((colour, 0, 0),)
        for pass_colour, dx, dy in passes:
            cursor = x + dx * scale
            for ch in text:
                code = ord(ch)
                cell = self.cells.get(code)
                if cell is None:
                    continue
                if code != 32:
                    self._glyph(surface, cell[0], cell[1], cursor,
                                y + dy * scale, scale, pass_colour)
                cursor += self.advance.get(code, 0) * scale

    def _glyph(self, surface, col, row, x, y, scale, colour):
        run = bytes((*colour, 255)) * scale
        for j in range(self.CELL):
            source = self.sheet[row * self.CELL + j]
            for i in range(self.CELL):
                if not source[col * self.CELL + i][3]:
                    continue
                left = x + i * scale
                if left < 0 or left >= surface.width:
                    continue
                for k in range(scale):
                    line = y + j * scale + k
                    if 0 <= line < surface.height:
                        start = line * surface.stride + left * 4
                        surface.data[start:start + scale * 4] = run
