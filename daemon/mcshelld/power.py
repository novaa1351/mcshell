"""The machine's power state, for the pause menu's last button.

*Save and Quit to Title* is the one button on the pause menu that has nowhere
to go. There is no title screen to return to — the world is the shell, and
quitting it leaves a logged-in session with a black screen where the desktop
used to be. So the button opens this instead: lock, sleep, restart, power off.
The wording on the button is left alone, the way *Open to LAN* is, because a
renamed one is a tell and this one is already about leaving.

Four verbs and nothing else. Everything here is a request to something that
already knows how to do it — swaylock for the screen, logind for the rest —
and none of it needs a password: `CanPowerOff`, `CanReboot` and `CanSuspend`
all answer `yes` for the active local session, so there is no reason for a
game client to be anywhere near one.

**The lock screen is started by the compositor, not by us.** A child of this
daemon lives in this daemon's cgroup, and `$mod+Shift+d` restarts the daemon —
which would take the lock screen down with it. Unlocking a machine by
restarting a service is not a lock screen. Sway's `exec` puts it in the
compositor's cgroup instead, where it belongs and where the keybinding's own
swaylock goes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import shlex
import shutil
from collections.abc import Awaitable, Callable
from . import protocol as p
from .paths import SESSION

log = logging.getLogger(__name__)

#: The session's lock screen, in one place. `$mod+Shift+l` runs the same
#: script, because the menu and the keybinding have to put up the same screen
#: and a command written into two files eventually will not.
#:
#: It is a script rather than a lock program's command line because none of
#: them draws a screen: the first person to meet swaylock sat in front of a
#: blank one with a ring on it and then held the power button. The script
#: renders Minecraft's own screen into the background image, and picks
#: whichever lock program is installed to draw the field over it.
LOCK_SCRIPT = SESSION / "lock.sh"

#: If the script is missing the machine must still lock. Plain, and ugly, and
#: better than a Lock Screen button that does nothing.
LOCK_FALLBACK = "swaylock -f -c 1a1a2e"

#: What the script may end up running, and therefore what to look for in
#: `/proc` to know the screen is up. In the order `lock.sh` prefers them.
LOCK_PROCESSES = ("hyprlock", "swaylock")

#: How long to wait for the lock to actually be up before suspending anyway.
#: The compositor spawns the lock screen for us, so there is nothing to wait
#: on but the process itself. Generous, because
#: the script renders a background first — measured at well under a second,
#: and a suspend that beats the lock screen is the failure worth avoiding.
LOCK_TIMEOUT = 5.0
LOCK_POLL = 0.05


def lock_command() -> str:
    if LOCK_SCRIPT.is_file():
        return shlex.quote(str(LOCK_SCRIPT))
    log.warning("%s is missing; locking without a prompt", LOCK_SCRIPT)
    return LOCK_FALLBACK

#: What logind is asked for. `sleep` locks first — see `_run`.
SYSTEMCTL = {
    "sleep": "suspend",
    "restart": "reboot",
    "poweroff": "poweroff",
}

ACTIONS = ("lock", "sleep", "restart", "poweroff")

Launch = Callable[[str], Awaitable[bool]]
Notify = Callable[[p.Message], Awaitable[None]]


class PowerError(Exception):
    """Something the user should be told, rather than something to log."""


class Power:
    """Four verbs, each of them a request to something that already does it."""

    def __init__(self, launch: Launch, notify: Notify | None = None) -> None:
        self._launch = launch
        self._notify = notify
        self._doing: asyncio.Task | None = None

    async def act(self, action: str) -> p.Message:
        """Start one action, and answer straight away.

        Run in the background rather than inline: `dispatch` is awaited on the
        client's own socket, the same one the pointer handshake goes down, and
        waiting three seconds for a lock screen to appear there would stall
        the shell. The reply says the request was accepted; a failure comes
        back afterwards as an `error`.
        """
        if action not in ACTIONS:
            return p.Error(message=f"no such power action: {action!r}")
        if self._doing is not None and not self._doing.done():
            return p.Error(message="already doing that")
        self._doing = asyncio.create_task(self._guard(action))
        return p.Ok()

    async def _guard(self, action: str) -> None:
        try:
            await self._run(action)
        except PowerError as e:
            log.warning("power %s failed: %s", action, e)
            if self._notify is not None:
                await self._notify(p.Error(message=str(e)))
        except Exception:
            log.exception("power %s failed", action)

    async def _run(self, action: str) -> None:
        if action == "lock":
            await self._lock()
            return

        if action == "sleep":
            # Locked before suspending, because a laptop that wakes straight
            # onto the desktop is not a locked laptop and nothing else in this
            # session will do it — there is no swayidle here, and no sleep
            # hook. If the lock will not come up we still suspend: a machine
            # that refuses to sleep because of the lock screen is worse than
            # one that sleeps unlocked, and the log says which happened.
            try:
                await self._lock()
            except PowerError as e:
                log.warning("suspending without a lock screen: %s", e)

        verb = SYSTEMCTL[action]
        log.info("power: systemctl %s", verb)
        await self._systemctl(verb)

    async def _lock(self) -> None:
        if not any(shutil.which(name) for name in LOCK_PROCESSES):
            raise PowerError("no lock screen is installed")
        if _locked():
            return
        if not await self._launch(lock_command()):
            raise PowerError("the compositor would not start the lock screen")
        if not await _wait_for_lock():
            raise PowerError("the lock screen did not come up")
        log.info("power: locked")

    @staticmethod
    async def _systemctl(verb: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", verb,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode:
            detail = err.decode(errors="replace").strip().splitlines()
            raise PowerError(detail[-1] if detail else f"systemctl {verb} failed")


def _locked() -> bool:
    """Whether a lock screen is already up.

    Read out of `/proc` rather than run through `pgrep`, because this is polled
    and a subprocess every fifty milliseconds to answer one question is a poor
    trade for a directory listing.
    """
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/comm") as f:
                if f.read().strip() in LOCK_PROCESSES:
                    return True
        except OSError:
            continue        # exited between the listing and the read
    return False


async def _wait_for_lock() -> bool:
    deadline = asyncio.get_running_loop().time() + LOCK_TIMEOUT
    while asyncio.get_running_loop().time() < deadline:
        if _locked():
            return True
        await asyncio.sleep(LOCK_POLL)
    return _locked()


# --- saving the world before the machine goes down -------------------------

LOGIND = "org.freedesktop.login1"
LOGIND_PATH = "/org/freedesktop/login1"
LOGIND_MANAGER = "org.freedesktop.login1.Manager"

#: How long the game gets to save before the machine is let go. logind holds a
#: delay lock for `InhibitDelayMaxUSec` at most — 5s on this machine, measured —
#: and shuts down regardless after that, so the save has to be answered inside
#: it with room left to release the lock.
SAVE_TIMEOUT = 4.0


class ShutdownSave:
    """Hold power off and restart back until the world has been saved.

    Nothing used to save it. Measured across the last five sessions: every
    game log ends partway through a batch of `Saving chunks` lines and none
    records `Stopping server`. At logout or power off sway goes first, and the
    game — an X client — dies with its display: `The Wayland connection broke`,
    exit 255. So at best the world was as fresh as the last autosave, and a
    unit stop hook would run after the crash, which is too late.

    The only moment the world can still be saved is *before* shutdown begins,
    and logind has exactly that: a delay inhibitor. With one held, logind sends
    `PrepareForShutdown(true)` and waits — up to its cap — for the lock to be
    released before it starts tearing the session down.

    That covers every route rather than only the pause menu. Its Restart and
    Power Off are `systemctl`, which asks logind; so is the power button, and so
    is `systemctl poweroff` typed into a terminal. A forced one (`-ff`) skips
    logind and this with it, which is what forcing is for.

    Sleep is not held. A suspended machine keeps everything in memory, and the
    delay would be paid on every lid close.
    """

    def __init__(self, save: Callable[[], Awaitable[bool]]) -> None:
        self._save = save
        self._bus = None
        self._fd: int | None = None
        self._busy: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            from dbus_next import BusType, Message
            from dbus_next.aio import MessageBus
        except ImportError:
            log.warning("shutdown: dbus-next is missing; the world will not be "
                        "saved before power off")
            return
        try:
            # negotiate_unix_fd, because the lock *is* a file descriptor: logind
            # holds power off for as long as it is open, and closing it is the
            # release.
            self._bus = await MessageBus(bus_type=BusType.SYSTEM,
                                         negotiate_unix_fd=True).connect()
            await self._bus.call(Message(
                destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus", member="AddMatch",
                signature="s",
                body=[f"type='signal',interface='{LOGIND_MANAGER}',"
                      "member='PrepareForShutdown'"]))
            self._bus.add_message_handler(self._on_message)
            await self._inhibit()
        except Exception as e:
            # Never a reason for the daemon not to come up. Without the lock the
            # machine powers off exactly as it did before this existed.
            log.warning("shutdown: cannot hold power off for a save: %s", e)

    async def stop(self) -> None:
        self._release()
        if self._bus is not None:
            with contextlib.suppress(Exception):
                self._bus.disconnect()
            self._bus = None

    async def _inhibit(self) -> None:
        from dbus_next import Message, MessageType
        if self._fd is not None or self._bus is None:
            return
        reply = await self._bus.call(Message(
            destination=LOGIND, path=LOGIND_PATH, interface=LOGIND_MANAGER,
            member="Inhibit", signature="ssss",
            body=["shutdown", "MCShell",
                  "Saving the world before the machine goes down", "delay"]))
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(reply.body[0] if reply.body else reply.error_name)
        self._fd = reply.unix_fds[reply.body[0]]
        log.info("shutdown: holding power off and restart for a save")

    def _release(self) -> None:
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None

    def _on_message(self, msg) -> None:
        if msg.member != "PrepareForShutdown" or msg.interface != LOGIND_MANAGER:
            return
        if self._busy is not None and not self._busy.done():
            return
        self._busy = asyncio.create_task(self._prepare(bool(msg.body and msg.body[0])))

    async def _prepare(self, going: bool) -> None:
        if not going:
            # Called off after all — something refused, or it was cancelled.
            # Take the lock back, or the next power off would not wait.
            with contextlib.suppress(Exception):
                await self._inhibit()
            return
        started = time.monotonic()
        try:
            ok = await asyncio.wait_for(self._save(), SAVE_TIMEOUT)
        except asyncio.TimeoutError:
            ok = False
        except Exception:
            log.exception("shutdown: saving the world failed")
            ok = False
        took = time.monotonic() - started
        if ok:
            log.info("shutdown: the world is saved (%.2fs); letting the machine go", took)
        else:
            log.warning("shutdown: no save confirmed after %.2fs; letting the "
                        "machine go anyway", took)
        # Released whatever happened. A game that will not answer must not be
        # able to hold the machine up; logind would override us at its cap
        # regardless, and releasing ourselves is the difference between four
        # seconds and five.
        self._release()
