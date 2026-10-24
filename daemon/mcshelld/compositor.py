"""Sway integration. ALL i3ipc lives here — nothing else touches the compositor.

Maintains a live view of open windows, kept current by subscribing to Sway's
window and workspace events.

Windows are keyed on ``app_id`` (Wayland) / ``window_class`` (XWayland), never
on PID: Firefox and other multi-process apps fork, so the PID we spawn does not
own the window that eventually appears.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections import defaultdict
from dataclasses import dataclass

from i3ipc import Con
from i3ipc.aio import Connection

from .protocol import WindowInfo

log = logging.getLogger(__name__)

# Events that can change the window set or its attributes. We resync the whole
# tree on any of them rather than patching incrementally — a tree fetch is one
# cheap IPC round trip, window events are human-paced, and it removes an entire
# class of drift bugs (moves between workspaces, scratchpad, layout changes).
# Sway's own change notification for monitors: a mode set, a display plugged
# in, DPMS. Handled apart from the window events because it has nothing to say
# about windows, and a window resync is not free.
_OUTPUT_EVENT = "output"

# How long to give a client to commit a resize before measuring against it.
# See pin_backdrop. Two commands back to back — about a millisecond apart — are
# too close and both miss; two separate `swaymsg` invocations are far enough
# apart to work, so the figure needed is small and this is generous.
_COMMIT = 0.15

# How Minecraft is picked out of the window list. Kept beside each other
# because they are one idea, and shared with session/raise-mc.sh by hand —
# there is no way to include a shell script's variables in a sway config.
BACKDROP_CLASS = 'class="^Minecraft"'
BACKDROP_APP_ID = 'app_id="^[Mm]inecraft"'


_RESYNC_EVENTS = (
    "window::new",
    "window::close",
    "window::focus",
    "window::title",
    "window::move",
    "window::floating",
    "workspace::focus",
)


@dataclass(frozen=True)
class OutputMode:
    """One mode a monitor can be driven at.

    `refresh` is millihertz, which is how Sway reports it and how it must be
    given back — rounding to whole Hz here would make 59.951 unreachable.
    """

    width: int
    height: int
    refresh: int

    @property
    def hz(self) -> float:
        return self.refresh / 1000.0

    def as_sway(self) -> str:
        """The mode written the way Sway's `output ... mode` wants it."""
        return f"{self.width}x{self.height}@{self.hz:.3f}Hz"


@dataclass(frozen=True)
class OutputInfo:
    """One monitor, as far as anything outside this module needs to know."""

    name: str
    description: str
    active: bool
    scale: float
    current: OutputMode | None
    modes: tuple[OutputMode, ...]


def app_id_of(con: Con) -> str | None:
    """The stable identifier for a window.

    Wayland clients set ``app_id``. XWayland clients don't, so fall back to
    ``window_class``.
    """
    if con.app_id:
        return con.app_id
    wc = getattr(con, "window_class", None)
    return wc or None


def is_backdrop(app_id: str | None) -> bool:
    """Whether a window is the Minecraft client, which the shell sits on.

    Takes what `app_id_of` produced, so XWayland's window_class has already
    been folded in and one prefix covers both. Reads the same way the
    BACKDROP_* criteria above do.
    """
    return bool(app_id) and app_id.lower().startswith("minecraft")


def app_windows(tree) -> list:
    """Every application window in the tree, floating ones included.

    Not `tree.leaves()`: i3ipc only accepts containers whose type is exactly
    "con", so a floating window — type "floating_con" — is invisible to it.
    Sway floats dialogs and pop-ups by default and people float windows
    deliberately, and either way the app is running and focusable. Missing them
    would show a running app as stopped and make its slot unclickable.
    """
    return [
        con
        for con in tree
        if con.type in ("con", "floating_con") and not con.nodes and not con.floating_nodes
    ]


class Compositor:
    """Live view of Sway's window tree.

    Usage::

        comp = Compositor()
        await comp.start()
        comp.windows()                  # list[WindowInfo]
        comp.windows_for("firefox")     # list[WindowInfo]
    """

    def __init__(self, on_change=None, on_outputs=None):
        self._conn: Connection | None = None
        self._windows: dict[int, WindowInfo] = {}
        # con_ids most-recently-focused first. See _touch_focus.
        self._focus_order: list[int] = []
        self._main_task: asyncio.Task | None = None
        self._on_change = on_change
        self._on_outputs = on_outputs
        self.connected = False

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> bool:
        """Connect and begin tracking. Returns False if Sway isn't reachable.

        A missing compositor is not fatal: the daemon still serves clients, it
        just reports an empty window list. This keeps `mcsh` usable outside a
        Sway session.
        """
        sock = os.environ.get("SWAYSOCK")
        try:
            self._conn = await Connection(auto_reconnect=False).connect()
        except Exception as e:
            log.warning("could not connect to sway (SWAYSOCK=%s): %s", sock, e)
            self._conn = None
            return False

        log.info("connected to sway via %s", sock or "<autodetected socket>")

        for event in _RESYNC_EVENTS:
            self._conn.on(event, self._handle_event)
        self._conn.on(_OUTPUT_EVENT, self._handle_output_event)

        await self._resync()
        self._main_task = asyncio.create_task(self._run(), name="sway-events")
        self.connected = True
        return True

    async def stop(self) -> None:
        conn, self._conn = self._conn, None
        task, self._main_task = self._main_task, None

        # main_quit() before cancelling: it asks conn.main() to return, and it
        # resolves an internal future that raises InvalidStateError if main()
        # has already finished. Cancelling first guarantees that race.
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.main_quit()

        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self.connected = False

    async def _run(self) -> None:
        assert self._conn is not None
        try:
            await self._conn.main()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("sway event loop died; window list is now stale")
        finally:
            self.connected = False

    # -- event handling ----------------------------------------------------

    async def _handle_event(self, conn, event) -> None:
        change = getattr(event, "change", "?")
        await self._resync()
        log.debug("sway event %s -> %d window(s)", change, len(self._windows))
        if self._on_change is not None:
            try:
                res = self._on_change(self.windows())
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                log.exception("compositor change callback raised")

    async def _handle_output_event(self, conn, event) -> None:
        """A monitor changed. No window moved, so the window map is left alone."""
        if self._on_outputs is None:
            return
        try:
            res = self._on_outputs()
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            log.exception("compositor output callback raised")

    async def _resync(self) -> None:
        """Rebuild the window map from a fresh copy of Sway's tree."""
        assert self._conn is not None
        tree = await self._conn.get_tree()
        focused = tree.find_focused()
        focused_id = focused.id if focused else None

        fresh: dict[int, WindowInfo] = {}
        for con in app_windows(tree):
            app_id = app_id_of(con)
            if app_id is None:
                # Not an application window we can address (e.g. a bare
                # container). Skipped rather than guessed at.
                continue
            ws = con.workspace()
            fresh[con.id] = WindowInfo(
                con_id=con.id,
                app_id=app_id,
                title=con.name or "",
                workspace=ws.name if ws else None,
                focused=con.id == focused_id,
                pid=con.pid,
            )
        self._windows = fresh
        self._touch_focus(focused_id)

    def _touch_focus(self, con_id: int | None) -> None:
        """Record that `con_id` is focused, newest first, and forget dead windows.

        Sway answers "which window is focused *now*", and now is always
        Minecraft while the overview is open: it is a Screen inside the game,
        not a window of its own, so the game keeps compositor focus the whole
        time the player is looking at the panel. Any decision made from the
        live focus flag therefore sees no window of the app selected and falls
        back to the first one, which is how left-click cycling stuck on one
        window and shift+middle closed the oldest rather than the one just
        being used.

        Keeping the order here rather than in main.py means anything that has
        to pick *a* window of an app picks the same one.
        """
        if con_id is not None:
            if con_id in self._focus_order:
                self._focus_order.remove(con_id)
            self._focus_order.insert(0, con_id)
        self._focus_order = [c for c in self._focus_order if c in self._windows]

    # -- queries -----------------------------------------------------------

    def windows(self) -> list[WindowInfo]:
        """All tracked windows, ordered by app_id then con_id for stable output."""
        return sorted(self._windows.values(), key=lambda w: (w.app_id, w.con_id))

    def windows_for(self, app_id: str) -> list[WindowInfo]:
        return [w for w in self.windows() if w.app_id == app_id]

    def by_app_id(self) -> dict[str, list[WindowInfo]]:
        grouped: dict[str, list[WindowInfo]] = defaultdict(list)
        for w in self.windows():
            grouped[w.app_id].append(w)
        return dict(grouped)

    def focused(self) -> WindowInfo | None:
        return next((w for w in self._windows.values() if w.focused), None)

    # -- actions -----------------------------------------------------------

    async def _command(self, cmd: str, quiet: bool = False) -> bool:
        """Run a Sway command, logging any per-command failure.

        `quiet` is for commands whose criteria are *expected* to match nothing
        sometimes. Sway answers those with success=false and "No matching
        node.", which is a fact, not a fault.
        """
        if self._conn is None:
            log.warning("not connected to sway; dropping command %r", cmd)
            return False
        try:
            replies = await self._conn.command(cmd)
        except Exception:
            log.exception("sway command failed: %r", cmd)
            return False
        ok = True
        for reply in replies:
            if not reply.success:
                ok = False
                if quiet:
                    log.debug("sway: %r: %s", cmd, getattr(reply, "error", "?"))
                else:
                    log.warning(
                        "sway rejected %r: %s", cmd, getattr(reply, "error", "?")
                    )
        return ok

    async def launch(self, command: str) -> bool:
        """Start an application.

        Handed to Sway's own `exec` rather than spawned by the daemon. The app
        then belongs to the compositor, so restarting the daemon does not kill
        running applications and the daemon never accumulates children. We give
        up the PID by doing this, which costs nothing: windows are matched on
        app_id, never on PID.
        """
        return await self._command(f"exec {command}")

    async def focus_window(self, con_id: int) -> bool:
        """Focus a window, following it to whichever workspace it is on."""
        return await self._command(f"[con_id={con_id}] focus")

    async def close_window(self, con_id: int) -> bool:
        """Ask a window to close. Sway's `kill` is a polite request, not SIGKILL."""
        return await self._command(f"[con_id={con_id}] kill")

    async def _fill_output(self, *criteria: str, quiet: bool = False) -> bool:
        """Resize whatever matches to the whole output, and put it at 0,0.

        Resizes twice with a pause between, and both halves of that are
        load-bearing. The first resize lands a few pixels short — 1278x715 on
        a 1280x720 output — because sway works `100ppt` out against the size
        the client has actually committed to, which at that moment is still
        the old one. The second resize, against the committed size, is exact,
        and every resize after it is a no-op. Measured at four resolutions.

        Hence the pause: the two must straddle the client's commit. Two
        commands in one message never work (sway takes the whole message
        against one snapshot), and neither do two messages sent back to back —
        that was the version that looked right and wasn't.

        Returns whether anything matched.
        """
        hit = False
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(_COMMIT)
            for one in criteria:
                hit |= await self._command(
                    f"[{one}] resize set 100ppt 100ppt, move position 0 0",
                    quiet=quiet,
                )
        return hit

    async def fill_window(self, con_id: int) -> bool:
        """Size one window to the whole screen, so it covers the backdrop.

        Used on applications as they appear. See session/layout.conf for why
        the size an application opens at is decided here rather than there.
        """
        return await self._fill_output(f"con_id={con_id}")

    async def pin_backdrop(self) -> bool:
        """Resize Minecraft back to the whole output.

        session/layout.conf pins it there when the window maps, but a mode or
        scale change afterwards leaves it the old size — sway clamps floating
        windows into the new output area rather than growing them to fill it,
        and it re-runs no `for_window` rule to say otherwise. Changing the
        resolution from the Video page is exactly that case, so the daemon
        repairs the backdrop when an output changes under it.

        Both criteria are tried for the reason raise-mc.sh tries both: the
        client is XWayland today and reports a window_class, and the app_id
        line matches nothing until the day it runs native. So at most one of
        them ever matches, and neither does when Minecraft is not running —
        a daemon with no client is the normal state under `mcsh`. Quiet for
        that reason, and it says nothing when the backdrop was not found.
        """
        return await self._fill_output(BACKDROP_CLASS, BACKDROP_APP_ID, quiet=True)

    async def outputs(self) -> list[OutputInfo]:
        """The monitors Sway knows about.

        Converted out of i3ipc's own types deliberately. This module is the
        only thing allowed to know what i3ipc is, and handing its objects to
        callers would leak that everywhere they went.
        """
        if self._conn is None:
            return []
        try:
            replies = await self._conn.get_outputs()
        except Exception:
            log.exception("could not read sway outputs")
            return []

        outputs = []
        for reply in replies:
            modes = tuple(
                OutputMode(int(m.width), int(m.height), int(m.refresh))
                for m in (getattr(reply, "modes", None) or [])
            )
            raw = getattr(reply, "current_mode", None)
            current = (
                OutputMode(int(raw.width), int(raw.height), int(raw.refresh))
                if raw is not None else None
            )
            make = (getattr(reply, "make", "") or "").strip()
            model = (getattr(reply, "model", "") or "").strip()
            described = " ".join(
                part for part in (make, model) if part and part.lower() != "unknown")
            outputs.append(OutputInfo(
                name=reply.name,
                description=described or reply.name,
                active=bool(getattr(reply, "active", False)),
                scale=float(getattr(reply, "scale", 1.0) or 1.0),
                current=current,
                modes=modes,
            ))
        return outputs

    async def config(self) -> str:
        """Sway's config as it actually loaded it — the top-level file only.

        Asked for rather than read off disk: finding the file means guessing
        which of several paths was used, and whichever one Sway chose is the
        one it will answer with.

        **`include` is not expanded**, and that is measured rather than
        assumed: against a live session the reply carries the `include` lines
        themselves and none of `layout.conf`'s `for_window` rules. Two things
        follow. The Controls page lists the binds in the main file and no
        others — which is what somebody editing that file would expect — and
        the `config.d` snippet binds.py generates is never read back in as
        though a person had written it, so a binding the shell made cannot
        appear twice on the page that made it.
        """
        if self._conn is None:
            return ""
        try:
            reply = await self._conn.get_config()
        except Exception:
            log.exception("could not read the sway config")
            return ""
        return getattr(reply, "config", "") or ""

    async def bind(self, keys: str, command: str) -> bool:
        """Bind a key combination, effective immediately."""
        return await self._command(f"bindsym {keys} {command}")

    async def unbind(self, keys: str) -> bool:
        return await self._command(f"unbindsym {keys}")

    async def set_output(self, name: str, args: str) -> bool:
        """Configure a monitor: `set_output("eDP-1", "scale 1.5")`."""
        return await self._command(f'output "{name}" {args}')

    def last_focused_for(self, app_id: str) -> WindowInfo | None:
        """The app's most recently focused window, or None if never focused.

        Anchors both cycling and closing. Unlike `focused`, this still answers
        while Minecraft holds compositor focus — which it does for the whole
        time the overview is open.
        """
        for con_id in self._focus_order:
            window = self._windows.get(con_id)
            if window is not None and window.app_id == app_id:
                return window
        return None

    def next_window_for(self, app_id: str) -> WindowInfo | None:
        """The window to focus when cycling through an app's windows.

        Returns the one after the app's most recently focused window in con_id
        order, wrapping around. An app that has never held focus starts at its
        first window.
        """
        windows = self.windows_for(app_id)
        if not windows:
            return None
        anchor = self.last_focused_for(app_id)
        if anchor is None:
            return windows[0]
        for index, window in enumerate(windows):
            if window.con_id == anchor.con_id:
                return windows[(index + 1) % len(windows)]
        return windows[0]
