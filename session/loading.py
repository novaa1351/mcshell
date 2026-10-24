#!/usr/bin/env python3
"""The boot screen: Minecraft's world-generation screen, for the shell's boot.

There are about thirteen seconds between the GDM login and anything that looks
like this desktop, and until now they were spent on sway's flat `#1a1a2e`, then
Prism's launcher window, then Minecraft's own Mojang splash. Three unrelated
pictures, none of which says the shell is coming up.

So one picture replaces all three, and it is the screen the game already shows
while a world is being made: darkened dirt, a percentage, and the chunk map.
The shell's logo goes above it, which is the one thing on screen here that is
ours rather than Minecraft's.

Nothing here is a lookalike. The dirt and the font come out of the installed
client jar the way `lockscreen.py` reads them, and the twelve chunk colours are
the real `LevelLoadingScreen.STATUS_TO_COLOR` — read out of the yarn-mapped
1.21.1 jar with `javap`, not remembered. Getting those wrong would be the tell:
a nearly-right world-gen screen is worse than none.

Two things are ours, and both are forced:

**The grid size.** Vanilla draws a larger square than the region actually
being generated, and the margin between them is the screen's black frame and
grey band. Nothing is being generated here, so there are no numbers to read
and both had to be chosen: 33 chunks drawn, 23 of them generating.

**The order the cells fill in.** Vanilla colours each chunk by the status its
generator has actually reached. We have no generator, so the wavefront is
simulated: cells advance outward from the centre at a constant rate,
and each one walks up through all twelve
statuses over a fixed band of the run. The result is the concentric rings —
white centre, green, navy, grey, black edge — which is what the real screen
looks like, arrived at the way the real screen arrives at it.

    loading.py --progress 0.42 --out /tmp/boot.png     # look at one frame
    loading.py --contact-sheet --out /tmp/sheet.png    # look at all of them
"""

from __future__ import annotations

import argparse
from zipfile import ZipFile

from mcpixels import Surface, decode, find_jar, gui_scale, load_font

#: The same dirt the lock screen tiles, for the same reason: `menu_background`
#: in 1.21 is a flat black overlay, not a picture.
BACKGROUND = "assets/minecraft/textures/block/dirt.png"
#: How far it is darkened. Vanilla's options background tinted by a quarter and
#: then laid black over it; one multiply lands in the same place. Shared with
#: `lockscreen.py` by value rather than by import — they are two screens that
#: happen to agree, not one screen drawn twice.
SHADE = 0.30

WHITE = (0xFF, 0xFF, 0xFF)
#: `Formatting.GRAY`, for the one line that is a remark rather than a reading.
GRAY = (0xAA, 0xAA, 0xAA)

#: `LevelLoadingScreen.STATUS_TO_COLOR`, in generation order. Measured:
#:
#:     javap -p -c -constants net/minecraft/client/gui/screen/world/\
#:         LevelLoadingScreen.class
#:
#: against the yarn-mapped 1.21.1 merged jar in loom's cache.
STATUSES = (
    (0x54, 0x54, 0x54),   # EMPTY
    (0x99, 0x99, 0x99),   # STRUCTURE_STARTS
    (0x5F, 0x61, 0x91),   # STRUCTURE_REFERENCES
    (0x80, 0xB2, 0x52),   # BIOMES
    (0xD1, 0xD1, 0xD1),   # NOISE
    (0x72, 0x68, 0x09),   # SURFACE
    (0x30, 0x35, 0x72),   # CARVERS
    (0x21, 0xC6, 0x00),   # FEATURES
    (0xCC, 0xCC, 0xCC),   # INITIALIZE_LIGHT
    (0xFF, 0xE0, 0xA0),   # LIGHT
    (0xF2, 0x60, 0x60),   # SPAWN
    (0xFF, 0xFF, 0xFF),   # FULL
)
#: A chunk the generator has not reached. Vanilla's map is an
#: `Object2IntOpenHashMap` with `defaultReturnValue(0)`, so a chunk with no
#: status draws as colour 0 — which is why the real screen has a black edge.
UNSTARTED = (0x00, 0x00, 0x00)

#: How much of the map actually generates, and how much is drawn around it.
#:
#: Vanilla draws a *larger* square than the region being generated:
#: `WorldGenerationProgressTracker.forSpawnChunks` takes `getStartRegionSize`
#: twice, once for the centre and once for the whole map. The margin chunks get
#: their structure starts computed and nothing else, ever — which is exactly
#: the reference screenshot's black frame and grey band, and it is the detail
#: that makes the square read as Minecraft's rather than as a progress box.
#:
#: The numbers are ours, because nothing here is generating a world and there
#: is no tracker to ask. They are chosen to match the proportions of the real
#: screen.
CENTER_RADIUS = 11          # generates, all the way to FULL
STRUCT_MARGIN = 3           # gets STRUCTURE_STARTS and stops there
RADIUS = 16                 # drawn; the outermost rings never start at all
#: GUI pixels per chunk. Vanilla's `LevelLoadingScreen` passes 2.
CELL = 2

#: How much of the run one chunk spends walking from EMPTY to FULL, as a
#: fraction of the map's radius. This is the width of the coloured band between
#: the finished middle and the edge that has not started.
#:
#: The wavefront advances linearly in *radius*, not in area. Area-pacing is
#: what a spiral generator really does and it was tried first; it collapses the
#: band to two rings for most of the run, because seven eighths of a square's
#: area is in its outer half. Measured by rendering it. Constant radius is what
#: the screen looks like.
BAND = 0.8

LOGO_GAP = 10       # GUI pixels between the logo and the percentage
TEXT_GAP = 8        # and between the percentage and the map
NOTE_GAP = 8        # and between the map and the note under it


def status(distance: int, progress: float) -> tuple[int, int, int]:
    """The colour of one chunk at Chebyshev distance `distance` from spawn."""
    if distance > CENTER_RADIUS:
        # Outside the region being generated. Structure starts reach a little
        # way past it and nothing else does, so this band is grey for the whole
        # boot and the rings beyond it are never touched.
        if progress > 0.0 and distance <= CENTER_RADIUS + STRUCT_MARGIN:
            return STATUSES[1]
        return UNSTARTED

    # Scaled by 1 + BAND so the outermost generated ring reaches FULL exactly
    # as the run ends, rather than a band short of it.
    front = progress * (1.0 + BAND)
    local = (front - distance / CENTER_RADIUS) / BAND
    if local <= 0.0:
        return UNSTARTED
    return STATUSES[min(len(STATUSES) - 1, int(local * len(STATUSES)))]


class Screen:
    """The boot screen, decoded once and drawn in two halves.

    The split is forced by measurement, not by taste. Only the percentage and
    the map ever change, so only those are rebuilt: 24ms a frame against a
    whole screen that would have to be re-tiled, re-composited pixel by pixel
    in Python, and re-converted every time.

    It also puts the one-off cost where it belongs. Converting the background
    to cairo's ARGB was 566ms until `Surface.cairo` grew a fast path for
    surfaces with no transparency — it is now 18ms — and that 548ms was
    landing during the boot, which is the one moment the shell cannot spare
    it: Prism's launcher window maps in that window.

    `preview` composes the two, because a picture to look at wants one image.
    """

    def __init__(self, width: int, height: int, logo: str | None = None) -> None:
        jar = find_jar()
        if jar is None:
            raise SystemExit("no Minecraft client jar found")

        self.width, self.height = width, height
        self.scale = gui_scale(width, height)
        with ZipFile(jar) as zf:
            self.font = load_font(zf)
            _, _, self.dirt = decode(zf.read(BACKGROUND))

        self.logo = None
        if logo:
            with open(logo, "rb") as handle:
                lw, lh, pixels = decode(handle.read())
            self.logo = (lw, lh, pixels)

        # Laid out in GUI pixels, from the map outwards. Vanilla centres the
        # map on the screen and puts the percentage above it; the logo goes
        # above that, which is the only addition.
        size = (RADIUS * 2 + 1) * CELL
        logo_w, logo_h = (self.logo[0], self.logo[1]) if self.logo else (0, 0)
        map_top = height // (2 * self.scale) - size // 2
        text_top = map_top - TEXT_GAP - 8

        # Three surfaces, not one, and the split is measured: 18ms for the
        # background and 32ms for the logo, both once, against 24ms for the
        # percentage and the map on every frame. See the class docstring.
        self.panel_w, self.panel_h = size, (map_top + size) - text_top
        self.x = (width - self.panel_w * self.scale) // 2
        self.y = text_top * self.scale
        self._map_y = (map_top - text_top) * self.scale
        self._centre = self.panel_w * self.scale // 2

        self.logo_x = (width - logo_w * self.scale) // 2
        self.logo_y = (text_top - LOGO_GAP - logo_h) * self.scale

    def background(self) -> Surface:
        """The tiled dirt, and nothing else. Built once."""
        canvas = Surface(self.width, self.height)
        # Two GUI pixels per texel and 32 GUI pixels per tile, as Screen does.
        canvas.tile(self.dirt, self.scale * 2, SHADE)
        return canvas

    def emblem(self) -> Surface | None:
        """The shell's logo, on a transparent ground. Built once; it is the one
        thing on this screen that is ours rather than Minecraft's."""
        if not self.logo:
            return None
        lw, lh, pixels = self.logo
        surface = Surface(lw * self.scale, lh * self.scale)
        # One GUI pixel per source pixel, so the logo is at the same scale as
        # the font below it and the chunks below that.
        surface.blit(pixels, 0, 0, self.scale)
        return surface

    def panel(self, progress: float) -> Surface:
        """The part that moves: the percentage, and the map."""
        scale = self.scale
        surface = Surface(self.panel_w * scale, self.panel_h * scale)

        # Vanilla's `getPercentage` floors rather than rounds, so 99.9% still
        # reads 99 and the number never claims to be done before it is.
        text = f"{int(progress * 100)}%"
        self.font.draw(surface, text,
                       self._centre - self.font.width(text) * scale // 2,
                       0, scale, WHITE)

        size = (RADIUS * 2 + 1) * CELL
        draw_map(surface, self._centre, self._map_y + size * scale // 2,
                 scale, progress)
        return surface

    def note(self, text: str) -> tuple[Surface, int, int] | None:
        """A line under the map, and where it goes. Built once per message.

        Its own surface rather than part of the panel: the panel is as wide as
        the map and redrawn five times a second, and this is three times
        wider and never changes. The words are the daemon's; this only sets
        them — grey, centred, with the font's shadow.
        """
        if not text:
            return None
        scale = self.scale
        width = self.font.width(text) + 1          # +1 for the shadow
        surface = Surface(width * scale, 9 * scale)
        self.font.draw(surface, text, 0, 0, scale, GRAY)
        size = (RADIUS * 2 + 1) * CELL
        x = (self.width - width * scale) // 2
        y = self.y + self._map_y + (size + NOTE_GAP) * scale
        return surface, x, y

    def preview(self, progress: float, note: str = "") -> Surface:
        """All three composed into one image, for looking at.

        The repo's habit: `overlay.py --preview` and `lockscreen.py` both
        render to a PNG, so a surface can be checked by looking at it rather
        than by screenshotting the compositor — which for this screen would
        mean logging out to see it.
        """
        canvas = self.background()
        note_layer = self.note(note) or (None, 0, 0)
        for layer, x, y in ((self.emblem(), self.logo_x, self.logo_y),
                            (self.panel(progress), self.x, self.y),
                            note_layer):
            if layer is None:
                continue
            for j in range(layer.height):
                src = j * layer.stride
                dst = (y + j) * canvas.stride + x * 4
                row = layer.data[src:src + layer.stride]
                # Composited rather than copied: these are mostly transparent,
                # and a straight copy would punch the dirt out around them.
                for i in range(0, len(row), 4):
                    if row[i + 3]:
                        canvas.data[dst + i:dst + i + 4] = row[i:i + 4]
        return canvas


def draw_map(canvas: Surface, cx: int, cy: int, scale: int,
             progress: float) -> None:
    """The chunk map, centred on (cx, cy) in device pixels.

    One `fill` per cell rather than per pixel: at 33x33 that is 1089 fills of a
    tiny rectangle, which is 4ms and keeps the cells on whole GUI pixels the
    way vanilla's are.
    """
    size = RADIUS * 2 + 1
    step = CELL * scale
    left = cx - (size * step) // 2
    top = cy - (size * step) // 2
    # Rings share a colour, so it is worked out once per distance.
    palette = [status(d, progress) for d in range(RADIUS + 1)]
    for row in range(size):
        dy = abs(row - RADIUS)
        for col in range(size):
            distance = dy if dy > abs(col - RADIUS) else abs(col - RADIUS)
            canvas.fill(left + col * step, top + row * step, step, step,
                        palette[distance])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--progress", type=float, default=0.42)
    ap.add_argument("--logo", default=None)
    ap.add_argument("--note", default="")
    ap.add_argument("--out", default="loading.png")
    args = ap.parse_args()

    screen = Screen(args.width, args.height, args.logo)
    screen.preview(args.progress, args.note).write(args.out)
    print(args.out)


if __name__ == "__main__":
    main()
