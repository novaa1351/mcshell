#!/usr/bin/env python3
"""The shell's overlay: advancement toasts, and the volume bar.

Two layer-shell surfaces in one process. They are unrelated things that share
the one hard part — see `ensure_layer_shell` — and neither is worth a second
program that has to get that right again.

WHY THIS IS NOT IN THE MOD

Everything else the shell draws is drawn by Minecraft, and that is the rule.
This cannot be: in Fork A the game is the *backdrop* and every application
window stacks above it, so a toast drawn inside Minecraft is a toast behind
whatever you were actually looking at when the ping arrived. A notification you
have to alt-tab to a game to discover is not a notification.

So it is drawn here, on a layer-shell surface in the `overlay` layer, which
sits above every ordinary window including the game's own. The pixels are still
Minecraft's — the 160x32 `toast/advancement` sprite and `ascii.png`, out of the
installed client jar, exactly as the lock screen does it.

WHAT IS COPIED, AND FROM WHERE

Read out of `AdvancementToast` and `ToastManager$Entry` rather than eyeballed:

    toast          160 x 32          icon at (8, 8), 16x16
    header         (30, 7)           0xFFFF00, and 0xFF88FF for a challenge
    body           (30, 18)          white
    neither line has a drop shadow   -- both drawText calls pass false
    text wraps at  125 px
    visible        5000 ms
    slide          600 ms, f = clamp((now - start) / 600)^2
    on screen at   x - width * f     -- in from the right edge
    stacked every  32 px

The one thing that is ours is which colour a header gets: vanilla picks by
advancement frame, and there are no advancements here, so it picks by urgency.
A critical notification gets the challenge colour.

The surface takes no input at all — its input region is empty, so clicks go
through it to whatever is underneath. Vanilla's toasts cannot be clicked
either, and a strip of the screen that silently eats mouse presses is the
bug this project has already spent a session on once.

THE VOLUME BAR

Minecraft's boss bar, which is the only thing in the game shaped like a
labelled fraction drawn large and briefly over whatever you were doing. Vanilla
`BossBarHud`, again read rather than eyeballed:

    bar            182 x 5           `boss_bar/<colour>_progress` over
                                     `boss_bar/<colour>_background`
    bar at         y = 12            centred, x = width/2 - 91
    name above     y = 12 - 9 = 3    centred, white, *with* a drop shadow
    progress       the sprite cropped to round(182 * value)

It does not slide and does not fade. Vanilla's boss bars do neither, and a bar
that animated on every notch of a held volume key would be a strobe.

Reads one JSON object a line on stdin:

    {"t":"toast","title":"...","body":"...","icon":"/path/to.png","urgency":1}
    {"t":"close","id":7}
    {"t":"osd","text":"Volume 45%","value":0.45,"color":"white","ms":1400}

and draws it. Nothing is sent back; the daemon decides everything — including
what the bar says, so that the only thing on this side is how to draw a
labelled fraction in a colour.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path
from zipfile import ZipFile

from mcpixels import Surface, decode, find_jar, gui_scale, load_font
from loading import Screen as BootScreen

TOAST = "assets/minecraft/textures/gui/sprites/toast/advancement.png"
BOSS_BAR = "assets/minecraft/textures/gui/sprites/boss_bar/%s_%s.png"
#: Only the two the daemon can ask for. Vanilla ships seven; loading five that
#: nothing sends would be five PNG decodes at startup for nothing.
BAR_COLOURS = ("white", "red")

# Vanilla's geometry, in GUI pixels. See the table above.
W, H = 160, 32
ICON_X, ICON_Y, ICON = 8, 8, 16
TEXT_X, HEADER_Y, BODY_Y = 30, 7, 18
WRAP = 125
PITCH = 32

YELLOW = (0xFF, 0xFF, 0x00)
CHALLENGE = (0xFF, 0x88, 0xFF)
WHITE = (0xFF, 0xFF, 0xFF)

# The bar, in GUI pixels. Vanilla's own numbers; see the table above.
BAR_W, BAR_H = 182, 5
BAR_Y = 9          # 12 - 3: the name's row is the top of our surface
OSD_W, OSD_H = BAR_W, BAR_Y + BAR_H
#: Where vanilla puts the name, measured from the top of the screen. The bar
#: itself then lands on vanilla's y = 12.
OSD_TOP = 3
OSD_MS = 1400

SLIDE_MS = 600
VISIBLE_MS = 5000
#: How many are on screen at once. Vanilla's manager keeps a queue and shows
#: what fits; five rows of 32 is 160 GUI pixels, about a fifth of the screen,
#: which is as much of it as a notification may have.
MAX = 5

#: Where the shell's own logo lives. Beside this file rather than in the mod's
#: resources: it is drawn out here, by Python, on a layer-shell surface, and
#: the game never sees it.
LOGO = str(Path(__file__).resolve().parent / "assets" / "logo.png")

#: Touched the first time the boot screen is actually painted.
#:
#: `mcshell-client.service` waits for this before starting Prism, because the
#: boot screen covers Prism's launcher window and cannot cover a window that
#: appeared first. Everything else about the boot is a race this process cannot
#: win from a standing start: it has a Python interpreter, an LD_PRELOAD
#: re-exec and a GTK import to get through, and Prism is a compiled Qt
#: application that systemd starts in the same millisecond as the daemon.
#:
#: Written from the draw handler rather than from `show_loading`, so it means
#: the frame reached the compositor and not merely that one was composed.
DRAWN = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "mcshell-boot.drawn")


def downscale(pixels, size: int = ICON):
    """Nearest neighbour to 16x16, the way the mod does it for hotbar icons.

    Nearest rather than an average because the result is drawn at Minecraft's
    scale beside Minecraft's own art, and a smoothed icon next to a pixel one
    reads as a foreign object rather than as a small icon.
    """
    height = len(pixels)
    width = len(pixels[0])
    return [[pixels[y * height // size][x * width // size] for x in range(size)]
            for y in range(size)]


class Toaster:
    """Turns a notification into pixels. Knows nothing about windows."""

    def __init__(self, scale: int) -> None:
        jar = find_jar()
        if jar is None:
            raise SystemExit("no Minecraft client jar found")
        with ZipFile(jar) as zf:
            _, _, self.sprite = decode(zf.read(TOAST))
            self.font = load_font(zf)
        self.scale = scale
        self._icons: dict[str, list | None] = {}

    def icon(self, path: str | None):
        """One decode per file for the life of the process.

        A notification icon is an application's icon and the same application
        notifies over and over; decoding a 48x48 PNG in pure Python for every
        Discord message would be paid on the one path where latency shows.
        """
        if not path:
            return None
        if path not in self._icons:
            try:
                with open(path, "rb") as f:
                    _, _, pixels = decode(f.read())
                self._icons[path] = downscale(pixels)
            except Exception as e:                  # any unreadable icon
                print(f"toasts: {path}: {e}", file=sys.stderr, flush=True)
                self._icons[path] = None
        return self._icons[path]

    def render(self, title: str, body: str, icon: str | None,
               urgency: int = 1) -> Surface:
        s = self.scale
        surface = Surface(W * s, H * s)
        surface.blit(self.sprite, 0, 0, s)

        pixels = self.icon(icon)
        if pixels is not None:
            surface.blit(pixels, ICON_X * s, ICON_Y * s, s)

        header = CHALLENGE if urgency >= 2 else YELLOW
        for text, y, colour in ((title, HEADER_Y, header), (body, BODY_Y, WHITE)):
            if not text:
                continue
            line = self.font.trim(" ".join(text.split()), WRAP)
            self.font.draw(surface, line, TEXT_X * s, y * s, s, colour,
                           shadow=False)
        return surface


class Bar:
    """Minecraft's boss bar, with whatever the daemon wants written over it.

    Takes the font rather than loading one: `ascii.png` is decoded in pure
    Python and there is no reason to pay for it twice in one process.
    """

    def __init__(self, scale: int, font) -> None:
        jar = find_jar()
        if jar is None:
            raise SystemExit("no Minecraft client jar found")
        self.sprites: dict[str, tuple] = {}
        with ZipFile(jar) as zf:
            for colour in BAR_COLOURS:
                _, _, background = decode(zf.read(BOSS_BAR % (colour, "background")))
                _, _, progress = decode(zf.read(BOSS_BAR % (colour, "progress")))
                self.sprites[colour] = (background, progress)
        self.font = font
        self.scale = scale

    def render(self, text: str, value: float, colour: str) -> Surface:
        s = self.scale
        surface = Surface(OSD_W * s, OSD_H * s)
        background, progress = self.sprites.get(colour, self.sprites[BAR_COLOURS[0]])
        surface.blit(background, 0, BAR_Y * s, s)

        # Vanilla crops the progress sprite rather than scaling it, so the
        # bar's end is a hard edge at a whole pixel like every other one.
        filled = int(round(BAR_W * min(1.0, max(0.0, value))))
        if filled:
            surface.blit(progress, 0, BAR_Y * s, s, sw=filled)

        line = self.font.trim(text, BAR_W)
        x = (BAR_W - self.font.width(line)) // 2
        # With a shadow, unlike a toast: the boss bar's name has one, and this
        # is drawn over an arbitrary desktop rather than over its own panel.
        self.font.draw(surface, line, x * s, 0, s, WHITE, shadow=True)
        return surface


class Toast:
    """One live toast, and where it is in its 600ms slide."""

    def __init__(self, surface: Surface, duration: int, image=None,
                 ident: int = 0) -> None:
        self.ident = ident
        # A toast queued behind five others has not started yet, so its five
        # seconds have not started either. Vanilla's manager queues rather
        # than dropping, and a notification that lived out its whole life
        # off screen was never a notification.
        self.started = False
        self.surface = surface
        # Converted once, here, and not in the draw handler: turning 640x128
        # pixels into premultiplied BGRA is pure Python and this draws sixty
        # times a second.
        self.buffer = None
        self.image = image
        self.duration = duration
        self.start = time.monotonic() * 1000
        self.hiding = False
        self.hide_start = 0.0

    def progress(self, now: float) -> float:
        """Vanilla's easing: the square of the clamped fraction of 600ms."""
        start = self.hide_start if self.hiding else self.start
        f = min(1.0, max(0.0, (now - start) / SLIDE_MS))
        f = f * f
        return 1.0 - f if self.hiding else f

    def step(self, now: float) -> bool:
        """False once it has finished sliding back out."""
        if not self.hiding and now - self.start > SLIDE_MS + self.duration:
            self.dismiss(now)
        return not (self.hiding and now - self.hide_start > SLIDE_MS)

    def dismiss(self, now: float) -> None:
        if not self.hiding:
            self.hiding = True
            self.hide_start = now


def preview(args) -> None:
    """Render a column to a PNG instead of showing it.

    So that what the toast looks like can be checked by looking at it, without
    a screenshot of the compositor and without waiting for something to ping.
    """
    toaster = Toaster(args.scale)
    lines = [tuple(item.split("|", 2)) for item in args.preview]
    sheet = Surface(W * args.scale, PITCH * args.scale * len(lines),
                    (0x30, 0x30, 0x30, 0xFF))
    for i, item in enumerate(lines):
        title = item[0]
        body = item[1] if len(item) > 1 else ""
        icon = item[2] if len(item) > 2 else None
        toast = toaster.render(title, body, icon or None)
        # Composited rather than copied, so the rounded corners show the
        # background through them here the same way they show the desktop
        # through them on screen.
        for y in range(toast.height):
            row = (i * PITCH * args.scale + y) * sheet.stride
            for x in range(toast.width):
                at = y * toast.stride + x * 4
                if toast.data[at + 3]:
                    sheet.data[row + x * 4:row + x * 4 + 4] = \
                        toast.data[at:at + 4]
    sheet.write(args.out)
    print(args.out)


def preview_osd(args) -> None:
    """Render the bar to a PNG, for the same reason toasts have one: so what it
    looks like can be checked by looking at it."""
    jar = find_jar()
    if jar is None:
        raise SystemExit("no Minecraft client jar found")
    with ZipFile(jar) as zf:
        font = load_font(zf)
    bar = Bar(args.scale, font)
    lines = [item.split("|") for item in args.preview_osd]
    pitch = OSD_H + 4
    sheet = Surface(OSD_W * args.scale, pitch * args.scale * len(lines),
                    (0x30, 0x30, 0x30, 0xFF))
    for i, item in enumerate(lines):
        text = item[0]
        value = float(item[1]) if len(item) > 1 else 1.0
        colour = item[2] if len(item) > 2 else BAR_COLOURS[0]
        drawn = bar.render(text, value, colour)
        for y in range(drawn.height):
            row = (i * pitch * args.scale + y) * sheet.stride
            for x in range(drawn.width):
                at = y * drawn.stride + x * 4
                if drawn.data[at + 3]:
                    sheet.data[row + x * 4:row + x * 4 + 4] = drawn.data[at:at + 4]
    sheet.write(args.out)
    print(args.out)


#: gtk4-layer-shell hooks `wl_display_connect`, so it has to be in the process
#: before libwayland-client is. An import cannot manage that from Python, which
#: is why this re-executes itself once with the library preloaded.
PRELOAD = "/usr/lib/libgtk4-layer-shell.so"
PRELOADED = "MCSHELL_TOASTS_PRELOADED"


def ensure_layer_shell() -> None:
    """Put the library in front of libwayland-client, then come back as a new
    process.

    Measured on this machine: `Gtk4LayerShell.is_supported()` is False with no
    preload and False with the `liblayer-shell-preload.so` shim, and True with
    the library itself. Getting this wrong is not a cosmetic failure — the
    window comes up as an ordinary toplevel, which the daemon then adopts into
    a hotbar slot as though the notification overlay were an application
    somebody launched. That is exactly what happened the first time.

    Done here rather than in the unit or in the daemon's spawn so that running
    this by hand behaves the same way the daemon's copy does.
    """
    if os.environ.get(PRELOADED) or not os.path.exists(PRELOAD):
        return
    env = dict(os.environ)
    env[PRELOADED] = "1"
    existing = env.get("LD_PRELOAD", "")
    env["LD_PRELOAD"] = f"{PRELOAD}:{existing}" if existing else PRELOAD
    os.execve(sys.executable, [sys.executable, *sys.argv], env)


#: GTK's software renderer, rather than whichever GPU it finds first. Measured
#: on this machine, the overlay drawing a toast: 182MB with the default (GL,
#: through glvnd, which tries Nvidia's EGL before Mesa's — so it opened a
#: context on the 4070), 84MB on Mesa, 46MB with cairo, and cairo was cheaper
#: in CPU too: 60ms against 220ms for a toast's slide. Grim found the boot
#: screen, a toast and the volume bar pixel-identical under both. Everything
#: here is a few textures blitted at integer scale, which is no work for a GPU
#: to save. A default, not a rule: `GSK_RENDERER=gl` in the environment wins.
RENDERER = "cairo"


def run(args) -> None:
    ensure_layer_shell()
    os.environ.setdefault("GSK_RENDERER", RENDERER)

    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    import cairo
    from gi.repository import Gio, GLib, Gtk, Gtk4LayerShell as LayerShell

    if not LayerShell.is_supported():
        # Loudly, and without opening anything. A plain window here would be a
        # notification in the middle of the screen that the shell mistakes for
        # an application; nothing at all is the better failure.
        raise SystemExit(
            "toasts: no layer-shell support (compositor, or the preload did "
            "not take). Refusing to open a plain window.")

    toaster = Toaster(args.scale)
    bar = Bar(args.scale, toaster.font)
    scale = args.scale
    live: list[Toast] = []
    # NON_UNIQUE deliberately. This is a private child of the daemon, started
    # and stopped with it, so single-instance semantics buy nothing — and they
    # cost a session-bus registration on a startup path the boot screen is
    # racing Prism on. They also make the process untestable: a second copy
    # started beside the session's own hands its activation to the one already
    # running and exits with no windows and an empty log, which reads exactly
    # like a working program that drew nothing. The id is kept because the
    # daemon's OWN_SURFACES matches on it if a window ever comes up plain.
    app = Gtk.Application(application_id="dev.mcshell.toasts",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)
    state: dict = {}

    def layer(window, namespace: str) -> None:
        """The part both surfaces need, and the part that has to be right.

        `overlay` is the layer above every ordinary window, which is the whole
        point: Minecraft is the backdrop and applications stack on it. -1 on
        the exclusive zone means draw over anything that reserved space, and
        reserve none. No keyboard, ever.
        """
        LayerShell.init_for_window(window)
        LayerShell.set_layer(window, LayerShell.Layer.OVERLAY)
        LayerShell.set_namespace(window, namespace)
        LayerShell.set_exclusive_zone(window, -1)
        LayerShell.set_keyboard_mode(window, LayerShell.KeyboardMode.NONE)

    def transparent(window) -> None:
        """No window background, so only what is painted shows."""
        css = Gtk.CssProvider()
        style = "window { background: transparent; }"
        if hasattr(css, "load_from_string"):
            css.load_from_string(style)
        else:
            css.load_from_data(style.encode())
        Gtk.StyleContext.add_provider_for_display(
            window.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def build():
        """Everything GTK, built inside `activate`.

        GTK4 will not make a widget before the application has initialised it,
        so none of this can happen at import time or in main().
        """
        window = Gtk.Window()
        window.set_decorated(False)
        window.set_default_size(W * scale, MAX * PITCH * scale)
        transparent(window)

        layer(window, "mcshell-toasts")
        LayerShell.set_anchor(window, LayerShell.Edge.TOP, True)
        LayerShell.set_anchor(window, LayerShell.Edge.RIGHT, True)

        area = Gtk.DrawingArea()
        area.set_draw_func(on_draw)
        window.set_child(area)
        state["window"] = window
        state["area"] = area

    def build_osd():
        """The volume bar: the same surface kind, anchored top-centre.

        Anchored to TOP alone, which is how layer-shell centres a surface on
        the axis it is not pinned to. The toasts are top-*right* and 160 wide,
        so on any screen wider than 342 GUI pixels the two cannot touch.
        """
        window = Gtk.Window()
        window.set_decorated(False)
        window.set_default_size(OSD_W * scale, OSD_H * scale)
        transparent(window)

        layer(window, "mcshell-osd")
        LayerShell.set_anchor(window, LayerShell.Edge.TOP, True)
        LayerShell.set_margin(window, LayerShell.Edge.TOP, OSD_TOP * scale)

        area = Gtk.DrawingArea()
        area.set_draw_func(on_draw_osd)
        window.set_child(area)
        state["osd_window"] = window
        state["osd_area"] = area

    def build_loading():
        """The boot screen: the whole output, under nothing.

        Anchored on all four edges, which is how layer-shell says *fill this
        output*. It is the only one of the three surfaces that covers the
        screen, and the only one that is up before there is anything to cover:
        sway's flat colour, then Prism's launcher, then Minecraft's own splash.

        Input passes through it like the other two. A strip of the desktop that
        eats mouse presses is a bug this project has already spent a session
        on; a whole screen that ate them would be that bug with nowhere to
        click away to. The keyboard was never taken, so every safety rail in
        the sway config still works while this is up.
        """
        window = Gtk.Window()
        window.set_decorated(False)
        transparent(window)

        layer(window, "mcshell-loading")
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                     LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(window, edge, True)

        area = Gtk.DrawingArea()
        area.set_draw_func(on_draw_loading)
        window.set_child(area)
        state["boot_window"] = window
        state["boot_area"] = area

    def on_draw_loading(_area, ctx, width, height):
        boot = state.get("boot")
        if boot is None:
            return
        # Three surfaces rather than one, because only the last of them ever
        # changes: the background is 18ms to build and the logo 32ms, both
        # paid once, against 24ms for the percentage and map five times a
        # second. Measured; it is why this is split.
        for key, x, y in (("background", 0, 0),
                          ("emblem", boot["logo_x"], boot["logo_y"]),
                          ("panel", boot["x"], boot["y"]),
                          ("note", boot["note_x"], boot["note_y"])):
            image = boot.get(key)
            if image is not None:
                ctx.set_source_surface(image, x, y)
                ctx.paint()

        if not state.get("drawn"):
            state["drawn"] = True
            try:
                # The session is waiting on this to start the game. Best
                # effort: if it cannot be written the waiter times out and
                # starts Prism anyway, which is the old behaviour.
                with open(DRAWN, "w") as handle:
                    handle.write(str(os.getpid()))
            except OSError as e:
                print(f"overlay: could not mark the boot screen drawn: {e}",
                      file=sys.stderr, flush=True)

    def show_loading(message: dict):
        """Draw the boot screen at some fraction, or take it down.

        The background is built on the first call rather than at startup: a
        session whose daemon is merely being restarted never asks for this
        surface at all, and should not pay to prepare it.
        """
        if message.get("done"):
            return hide_loading()

        boot = state.get("boot")
        if boot is None:
            try:
                # The output's real size, so the dirt is tiled at Minecraft's
                # own GUI scale for this monitor. Asked of sway rather than of
                # the window: this fires while the surface is still hidden, so
                # there is nothing yet to measure.
                width, height = output_size()
                screen = BootScreen(width, height,
                                    LOGO if os.path.exists(LOGO) else None)
                boot = {
                    "screen": screen, "value": -1.0, "panel": None,
                    "text": "", "note": None, "note_x": 0, "note_y": 0,
                    "x": screen.x, "y": screen.y,
                    "logo_x": screen.logo_x, "logo_y": screen.logo_y,
                }
                # Both built once. The buffers are held alongside the images
                # because cairo draws straight out of them.
                for key, canvas in (("background", screen.background()),
                                    ("emblem", screen.emblem())):
                    if canvas is None:
                        continue
                    buffer = boot[key + "_buffer"] = canvas.cairo()
                    boot[key] = cairo.ImageSurface.create_for_data(
                        buffer, cairo.FORMAT_ARGB32, canvas.width,
                        canvas.height, canvas.stride)
            except Exception as e:
                print(f"overlay: loading: {e}", file=sys.stderr, flush=True)
                return False
            state["boot"] = boot

        value = min(1.0, max(0.0, float(message.get("value", 0.0))))
        # Only the integer percentage and the map can change, and both are
        # driven off this number; redrawing an identical frame would be 24ms
        # spent to produce the same pixels.
        if abs(value - boot["value"]) >= 0.001:
            boot["value"] = value
            panel = boot["screen"].panel(value)
            boot["panel_buffer"] = panel.cairo()
            boot["panel"] = cairo.ImageSurface.create_for_data(
                boot["panel_buffer"], cairo.FORMAT_ARGB32,
                panel.width, panel.height, panel.stride)

        # The line under the map: a reason, when the daemon has one. Built
        # only when it changes, which is at most once a boot.
        text = str(message.get("note") or "")
        if text != boot["text"]:
            boot["text"] = text
            built = boot["screen"].note(text)
            if built is None:
                boot["note"] = None
            else:
                canvas, boot["note_x"], boot["note_y"] = built
                boot["note_buffer"] = canvas.cairo()
                boot["note"] = cairo.ImageSurface.create_for_data(
                    boot["note_buffer"], cairo.FORMAT_ARGB32,
                    canvas.width, canvas.height, canvas.stride)

        state["boot_window"].set_visible(True)
        clear_input(state["boot_window"])
        state["boot_area"].queue_draw()
        return False

    def hide_loading():
        state["boot"] = None
        # So the next boot screen — a game restarted into another world —
        # marks itself drawn again, and the client waiting on that can start.
        state["drawn"] = False
        window = state.get("boot_window")
        if window is not None:
            window.set_visible(False)
        return False

    def on_draw(_area, ctx, width, _height):
        now = time.monotonic() * 1000
        for index, toast in enumerate(live[:MAX]):
            # Vanilla: translate(x - width * progress), x being the right edge.
            x = width - toast.surface.width * toast.progress(now)
            ctx.set_source_surface(toast.image, x, index * PITCH * scale)
            ctx.paint()

    def on_draw_osd(_area, ctx, _width, _height):
        osd = state.get("osd")
        if osd is not None:
            ctx.set_source_surface(osd["image"], 0, 0)
            ctx.paint()

    def show_osd(message: dict):
        """Replace what the bar says. Never re-animates: this arrives once per
        notch of a held key, and a bar that restarted its entrance each time
        would be a strobe rather than a readout."""
        try:
            surface = bar.render(
                str(message.get("text", "")),
                float(message.get("value", 0.0)),
                str(message.get("color", BAR_COLOURS[0])))
        except Exception as e:
            print(f"overlay: osd: {e}", file=sys.stderr, flush=True)
            return False
        buffer = surface.cairo()
        image = cairo.ImageSurface.create_for_data(
            buffer, cairo.FORMAT_ARGB32, surface.width, surface.height,
            surface.stride)
        # The buffer is held because cairo draws straight out of it.
        state["osd"] = {
            "image": image, "buffer": buffer,
            "until": time.monotonic() * 1000 + int(message.get("ms", OSD_MS)),
        }
        state["osd_window"].set_visible(True)
        clear_input(state["osd_window"])
        state["osd_area"].queue_draw()
        if not state.get("osd_ticking"):
            state["osd_ticking"] = True
            # Nothing moves while it is up, so this only has to notice when the
            # time is out. A tenth of a second is finer than anybody can see a
            # popup disappear.
            GLib.timeout_add(100, tick_osd)
        return False

    def tick_osd():
        osd = state.get("osd")
        if osd is None or time.monotonic() * 1000 >= osd["until"]:
            state["osd"] = None
            state["osd_window"].set_visible(False)
            state["osd_ticking"] = False
            return False
        return True

    def clear_input(window=None):
        """No clicks, on either surface. They cover strips of every screen they
        are on, and a strip of the desktop that silently eats mouse presses is
        the bug this project has already spent a session on once."""
        surface = (window or state["window"]).get_surface()
        if surface is not None:
            surface.set_input_region(cairo.Region())

    def tick():
        now = time.monotonic() * 1000
        for toast in live[:MAX]:
            if not toast.started:
                toast.started = True
                toast.start = now
        live[:] = [t for t in live[:MAX] if t.step(now)] + live[MAX:]
        if not live:
            # Nothing on screen, so nothing to composite until the next ping.
            state["window"].set_visible(False)
            state["ticking"] = False
            return False
        state["area"].queue_draw()
        return True

    def start_ticking():
        if not state.get("ticking"):
            state["ticking"] = True
            GLib.timeout_add(16, tick)

    def show(message: dict):
        try:
            surface = toaster.render(
                message.get("title", ""), message.get("body", ""),
                message.get("icon"), int(message.get("urgency", 1)))
        except Exception as e:
            print(f"toasts: {e}", file=sys.stderr, flush=True)
            return False
        buffer = surface.cairo()
        image = cairo.ImageSurface.create_for_data(
            buffer, cairo.FORMAT_ARGB32, surface.width, surface.height,
            surface.stride)
        duration = int(message.get("ms", VISIBLE_MS))
        ident = int(message.get("id", 0))

        # `replaces_id` is the spec's way for a music player to update its own
        # toast rather than stack a new one every track. Swapped in place and
        # the clock restarted, but not re-slid: a toast already on screen
        # jumping back off it to come in again would read as two.
        existing = next((t for t in live if ident and t.ident == ident), None)
        if existing is not None and not existing.hiding:
            existing.surface, existing.image, existing.buffer = surface, image, buffer
            existing.duration = duration
            existing.start = time.monotonic() * 1000 - SLIDE_MS
        else:
            toast = Toast(surface, duration, image, ident)
            # Held so the buffer cairo draws straight out of stays alive.
            toast.buffer = buffer
            live.append(toast)

        state["window"].set_visible(True)
        clear_input()
        start_ticking()
        return False

    def close(ident: int):
        now = time.monotonic() * 1000
        for toast in live:
            if toast.ident == ident:
                toast.dismiss(now)
        return False

    def reader():
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            kind = message.get("t")
            if kind == "toast":
                GLib.idle_add(show, message)
            elif kind == "osd":
                GLib.idle_add(show_osd, message)
            elif kind == "loading":
                GLib.idle_add(show_loading, message)
            elif kind == "close":
                GLib.idle_add(close, int(message.get("id", 0)))
        # The daemon is gone. Nothing here is worth outliving it.
        GLib.idle_add(lambda: (app.quit(), False)[1])

    def activate(_app):
        build()
        build_osd()
        build_loading()
        app.add_window(state["window"])
        app.add_window(state["osd_window"])
        app.add_window(state["boot_window"])
        # Hidden until something arrives, so an idle session composites nothing.
        state["window"].set_visible(False)
        state["osd_window"].set_visible(False)
        state["boot_window"].set_visible(False)
        threading.Thread(target=reader, daemon=True).start()

    app.connect("activate", activate)
    app.run([])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=0,
                    help="GUI scale; 0 asks the compositor for the output size")
    ap.add_argument("--preview", action="append", metavar="TITLE|BODY|ICON",
                    help="render a toast to a PNG instead of showing a window")
    ap.add_argument("--preview-osd", action="append", metavar="TEXT|VALUE|COLOUR",
                    help="render the volume bar to a PNG")
    ap.add_argument("--out", default="toast.png")
    args = ap.parse_args()

    if not args.scale:
        args.scale = default_scale()
    if args.preview:
        preview(args)
    elif args.preview_osd:
        preview_osd(args)
    else:
        run(args)


def output_size() -> tuple[int, int]:
    """The active output's pixel size, or a sensible guess.

    The boot screen fills a whole output and the toasts only need its scale, so
    both come from here. A guess is better than a refusal: a loading screen
    tiled at the wrong scale still says the shell is coming up.
    """
    import subprocess
    try:
        out = subprocess.run(["swaymsg", "-t", "get_outputs", "-r"],
                             capture_output=True, text=True, timeout=2).stdout
        for output in json.loads(out):
            mode = output.get("current_mode") or {}
            if output.get("active") and mode.get("width"):
                return mode["width"], mode["height"]
    except Exception:
        pass
    return 1920, 1080


def default_scale() -> int:
    """Minecraft's scale for this monitor, so the toast matches the game's."""
    return gui_scale(*output_size())


if __name__ == "__main__":
    main()
