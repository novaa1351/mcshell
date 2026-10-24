"""The layer-shell overlay process, and the one pipe into it.

There is exactly one thing in this shell that Minecraft cannot draw: anything
that has to be visible while an application is. In Fork A the game is the
*backdrop* and every window stacks above it, so a toast rendered inside
Minecraft is a toast behind whatever you were looking at when it arrived, and a
volume bar drawn there is invisible at the one moment anybody reaches for the
volume keys — while watching something.

So `session/overlay.py` draws those on layer-shell surfaces in the `overlay`
layer, above every ordinary window including the game's own, out of Minecraft's
own sprites and font. This is the daemon's half: it starts that process, keeps
it alive, and writes one JSON object a line to its stdin. Nothing comes back.

**One process, several surfaces.** Toasts and the OSD are different windows
inside it rather than two programs, because the fragile part is neither of
them — it is `gtk4-layer-shell` having to be in the process before
libwayland-client, which the overlay arranges by re-executing itself once. Two
programs would mean paying that twice, and the failure mode is not cosmetic: a
surface that comes up as an ordinary toplevel is one the daemon then fills to
the screen and focuses, as though the notification overlay were an application
somebody launched. That happened once already.

This lives apart from `notify.py` because it is no longer only notifications.
Audio owns the OSD and has no business reaching through the notification
server to draw one.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os

from .paths import SESSION

log = logging.getLogger(__name__)

#: Run with the system interpreter rather than the daemon's: it needs PyGObject
#: and gtk4-layer-shell, which are system packages with compiled typelibs and
#: have no business in a venv.
PROGRAM = SESSION / "overlay.py"
SYSTEM_PYTHON = "/usr/bin/python3"

#: An overlay that exits this soon after starting could not run — no display,
#: no layer-shell, no GTK. A working one never exits on its own: it reads its
#: stdin until the daemon is gone.
FAILED_WITHIN = 5.0

#: And then it is not started again for this long. Without it the boot screen,
#: which draws every 0.2s, started a Python and GTK process on every tick for
#: its whole ninety seconds; measured, eight in three seconds. With it, the
#: first `send` after a failed start answers that there is nowhere to draw,
#: and the boot loop stops, as it was written to.
COOLDOWN = 60.0


class Overlay:
    """One child process, restarted on demand, written to a line at a time."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._started = 0.0
        self._retry_after = 0.0

    async def send(self, message: dict) -> bool:
        """Draw something. False if there was nowhere to draw it."""
        if not await self._ensure():
            return False
        assert self._proc is not None and self._proc.stdin is not None
        try:
            self._proc.stdin.write((json.dumps(message) + "\n").encode())
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            # It died between the check and the write. Dropped rather than
            # retried: the next one brings a fresh process up, and neither a
            # toast nor a volume bar is worth a second chance a second later.
            log.warning("overlay: went away mid-write")
            now = asyncio.get_running_loop().time()
            if now - self._started < FAILED_WITHIN:
                self._retry_after = now + COOLDOWN
            self._proc = None
            return False
        return True

    async def _ensure(self) -> bool:
        if self._proc is not None and self._proc.returncode is None:
            return True
        now = asyncio.get_running_loop().time()
        if self._proc is not None:
            lived = now - self._started
            if lived < FAILED_WITHIN:
                log.warning("overlay: exited %d after %.1fs; not starting it "
                            "again for %.0fs", self._proc.returncode, lived, COOLDOWN)
                self._retry_after = now + COOLDOWN
            self._proc = None
        if now < self._retry_after:
            return False
        if not PROGRAM.is_file():
            log.warning("overlay: %s is missing", PROGRAM)
            return False
        python = SYSTEM_PYTHON if os.path.exists(SYSTEM_PYTHON) else "python3"
        try:
            self._proc = await asyncio.create_subprocess_exec(
                python, str(PROGRAM),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
            )
        except OSError as e:
            log.warning("overlay: could not start %s: %s", PROGRAM, e)
            self._proc = None
            return False
        self._started = asyncio.get_running_loop().time()
        log.info("overlay: up (pid %d)", self._proc.pid)
        return True

    async def stop(self) -> None:
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(self._proc.wait(), 2.0)
        self._proc = None
