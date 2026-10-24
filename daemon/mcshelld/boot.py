"""The boot screen's progress, and when to take it down.

There are about thirteen seconds between the GDM login and anything that looks
like this desktop — measured, one login, and written up in CLAUDE.md under
*From login to desktop*. They used to be spent on sway's flat `#1a1a2e`, then
Prism's launcher window, then Minecraft's own Mojang splash: three unrelated
pictures, none of which says the shell is coming up.

`session/loading.py` draws one screen over all three. This decides what it
says.

**The number is honest, and that is the hard part.** A smoothly animating bar
with nothing behind it would be a lie, and this project does not draw those —
the same reason a machine with no battery gets no XP gauge rather than a
made-up one. So the percentage is an estimate against *how long this machine's
last boot actually took*, pinned to real events as they happen:

    daemon up          the catalog is read and the socket is listening
    backdrop mapped    Minecraft has a window; Prism has done its part
    mod connected      `hello` — the game is running our code
    world ready        the world is on screen, and this screen goes away

Between anchors the number is interpolated from the clock; at an anchor it
jumps to that anchor's floor if it was lagging. It never goes backwards, and it
never reaches 100 until the world really is up: the cap is 99, so the last
percent is the one thing on screen that is always true.

**A first boot has nothing to estimate from**, so it uses `DEFAULT_ESTIMATE`
and writes down what it measured. The file is one number.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from xdg import BaseDirectory

log = logging.getLogger(__name__)

#: How often the screen is redrawn. The panel costs 24ms to compose, so five
#: frames a second is about an eighth of one core — during a boot, on a machine
#: that is busy starting Minecraft. Vanilla's own world-gen screen updates as
#: chunks complete rather than smoothly, so this is not even a compromise.
TICK = 0.2

#: What a boot takes when nothing is known about this machine. The measured one
#: was fourteen seconds from sway to the world.
DEFAULT_ESTIMATE = 14.0

#: Never claim to be finished. Only `world_ready` may end this screen, so the
#: last percent is the one number on it that cannot be wrong.
CAP = 0.99

#: The screen comes down after this long whatever happens. A boot that stalls
#: must not leave a full-screen surface over a session nobody can see into: the
#: safety rails in the sway config all still work behind it, but you would be
#: pressing them blind. Generous, because the alternative to a slow boot screen
#: is a torn-looking desktop.
TIMEOUT = 90.0

#: The floor each real event puts under the estimate. Chosen against the
#: measured timeline: the daemon is up two seconds in, Minecraft has a window
#: at about ten, and `hello` lands at twelve of the fourteen.
PHASES = {
    "daemon": 0.10,
    "backdrop": 0.45,
    "mod": 0.80,
}

#: What the screen says under the map when the launcher decided to go offline.
#: Prism's own words, nearly — its prompt said "You are not connected to the
#: Internet, launching in offline mode" — cut to one line of `ascii.png`. Said
#: because an offline login is otherwise indistinguishable from a broken one
#: until the world appears without a skin.
OFFLINE_NOTE = "No internet connection - starting offline"

#: The launcher's windows, and the titles it gives the ones that are only
#: progress. Measured, in a headless sway, on both paths: a normal launch shows
#: "Please wait..." and then "Console window for <instance>"; a launch with no
#: network shows "No internet connection" — the name prompt. Each is followed
#: by " — Prism Launcher <version>".
LAUNCHER = "org.prismlauncher.prismlauncher"
LAUNCHER_PROGRESS = ("Please wait", "Console window")


class Boot:
    """One boot screen, from the daemon starting to the world appearing."""

    def __init__(self, overlay, path: Path | None = None, records: bool = True) -> None:
        #: False for a screen that is not a login — a game restart — whose
        #: duration would be a wrong estimate for the next boot.
        self.records = records
        self.overlay = overlay
        self.path = path or (
            Path(BaseDirectory.save_config_path("mcshell")) / "boot.json")
        self.started = time.monotonic()
        self.estimate = self._load()
        self._floor = 0.0
        self._value = 0.0
        self._task: asyncio.Task | None = None
        self._finished = False
        #: A line under the map, or "" for none.
        self.note = ""

    # -- the numbers ---------------------------------------------------------

    def _load(self) -> float:
        try:
            value = float(json.loads(self.path.read_text())["seconds"])
        except Exception:
            return DEFAULT_ESTIMATE
        # A boot that took a tenth of a second, or an hour, is a stopped clock
        # or a machine that was asleep. Either way it is not an estimate.
        return value if 2.0 <= value <= 120.0 else DEFAULT_ESTIMATE

    def _save(self, seconds: float) -> None:
        try:
            self.path.write_text(json.dumps({"seconds": round(seconds, 2)}))
        except OSError as e:
            log.debug("boot: could not record the timing: %s", e)

    def progress(self) -> float:
        """Where the bar is now. Monotonic, and never past the cap."""
        elapsed = time.monotonic() - self.started
        value = max(self._floor, elapsed / self.estimate)
        # Monotonic: a later anchor with a lower floor, or an estimate that
        # turns out to be short, must never walk the number backwards.
        self._value = min(CAP, max(self._value, value))
        return self._value

    def reached(self, phase: str) -> None:
        """A real event happened. Pull the estimate up to meet it."""
        floor = PHASES.get(phase)
        if floor is not None and floor > self._floor:
            self._floor = floor
            log.debug("boot: %s (floor %.0f%%)", phase, floor * 100)

    def offline(self) -> None:
        """The launcher found no network and is starting the game offline."""
        if not self._finished and self.note != OFFLINE_NOTE:
            self.note = OFFLINE_NOTE
            log.info("boot: the launcher is starting the game offline")

    async def windows(self, windows) -> None:
        """Come down if the launcher is asking somebody something.

        The screen is above every window and takes no input, so a launcher
        dialog under it is a question nobody can see — which is exactly what a
        no-network login used to be: a name prompt in 0.13s, hidden for 90.
        `launch.sh` now answers that one before it is asked; this is for the
        ones it cannot, such as an account that needs signing in again.

        Anything from the launcher that is not a progress window counts. An
        unknown window costs the boot screen; the other mistake costs the
        login.
        """
        if self._finished:
            return
        for w in windows:
            if (w.app_id or "").lower() != LAUNCHER or not w.title:
                continue
            if w.title.startswith(LAUNCHER_PROGRESS):
                continue
            log.warning("boot: the launcher is showing %r; taking the loading "
                        "screen down so it can be answered", w.title)
            await self.finish(record=False)
            return

    def _frame(self) -> dict:
        frame = {"t": "loading", "value": self.progress()}
        if self.note:
            frame["note"] = self.note
        return frame

    # -- the screen ----------------------------------------------------------

    async def start(self) -> None:
        """Put the screen up, and only then start keeping it up to date.

        The first frame is awaited rather than left to the ticker. The caller's
        very next step is `catalog.load()`, which is 1.2s of *synchronous* work
        and would hold the event loop shut — so a task created here would not
        run, the overlay would not even be spawned, and Prism's launcher window
        maps comfortably inside that. Measured: the overlay came up 1.34s after
        the daemon, and Prism starts in the same millisecond as the daemon.
        """
        if self._task is None and not self._finished:
            await self.overlay.send(self._frame())
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        try:
            while not self._finished:
                if time.monotonic() - self.started > TIMEOUT:
                    log.warning(
                        "boot: nothing said the world was up within %.0fs; "
                        "taking the loading screen down anyway", TIMEOUT)
                    await self.finish(record=False)
                    return
                if not await self.overlay.send(self._frame()):
                    # No overlay: it could not start, or layer-shell is not
                    # there. Nothing to drive, and retrying five times a second
                    # for ninety seconds would only fill the log.
                    log.warning("boot: no overlay to draw the loading screen on")
                    self._finished = True
                    return
                await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A boot screen must never be the reason a session fails to come
            # up. Whatever went wrong, stop drawing and let the desktop appear.
            log.exception("boot: giving up on the loading screen")
            with_overlay = self.overlay.send({"t": "loading", "done": True})
            await asyncio.shield(asyncio.ensure_future(with_overlay))
            self._finished = True

    async def finish(self, record: bool = True) -> None:
        """The world is up, or we have waited long enough."""
        if self._finished:
            return
        self._finished = True
        if self._task is not None:
            self._task.cancel()
            self._task = None
        seconds = time.monotonic() - self.started
        if record and self.records:
            # Written only for a boot that actually finished. A timeout would
            # teach the next boot that this machine takes ninety seconds.
            self._save(seconds)
            log.info("boot: the world is up, %.1fs after the daemon", seconds)
        await self.overlay.send({"t": "loading", "done": True})
