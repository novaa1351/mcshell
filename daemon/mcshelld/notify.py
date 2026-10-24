"""System notifications, as advancement toasts.

Nothing on this machine owns `org.freedesktop.Notifications` — measured, not
assumed: there is no mako, no dunst, no swaync, and `busctl` finds no owner. So
in the MCShell session a Discord ping currently goes nowhere at all. This takes
the name and draws what arrives.

WHAT IS HERE AND WHAT IS IN THE MOD

Nothing is in the mod. This is the one thing the shell draws that Minecraft
cannot: in Fork A the game is the backdrop and application windows stack above
it, so a toast rendered inside Minecraft is a toast behind whatever you were
looking at when it arrived. `session/overlay.py` draws it on a layer-shell
surface in the `overlay` layer instead, above every ordinary window including
the game's own, out of Minecraft's own sprite and font.

The split is the usual one. This decides — which icon, which colour, how long,
whether a sound plays — and the overlay renders. It is handed one JSON object a
line on its stdin and answers nothing back. The process itself is
`overlay.Overlay`, shared with the volume OSD, because the overlay stopped
being only about notifications.

WHERE THE ICON COMES FROM

In order, first hit wins:

    the `desktop-entry` hint      the sender naming its own .desktop file
    the `app_icon` argument       an icon name, or a path
    the `image-path` hint         some senders put a file here instead
    the app name, in the catalog  a last guess, by matching what it calls itself

All of them end at `Catalog.resolve_icon`, which is the same resolver the
hotbar uses, so a notification's icon and its application's item are the same
picture — including the SVG rasterising, which the toast renderer could not do
for itself.

WHAT IS DELIBERATELY NOT SUPPORTED

Actions. The overlay takes no input at all: its input region is empty so that
clicks pass through to whatever is underneath, which means there is nothing to
click a button on. Declaring `actions` and then dropping them would make
senders draw buttons that cannot be pressed, so the capability is not claimed.

`body-markup`, for the same reason: the game's font has one weight and no
colour changes mid-line. Markup that arrives anyway is stripped rather than
drawn, because `<b>hello</b>` on a toast is worse than `hello`.
"""

from __future__ import annotations

import asyncio
import contextlib
import glob
import html
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

from xdg import BaseDirectory

log = logging.getLogger(__name__)

BUS_NAME = "org.freedesktop.Notifications"
OBJECT_PATH = "/org/freedesktop/Notifications"

#: Vanilla's own toast lifetime. A sender asking for -1 (its default) or 0
#: (never) gets this: there is no notification centre to go and find a toast in
#: later, and one that never leaves would hold a slot in a column of five
#: forever.
DEFAULT_MS = 5000
MAX_MS = 20000

#: The level-up sound, in Minecraft's content-addressed asset store. Found
#: through the index that names it, because the file itself is called
#: `b9c60e80...` and nothing else says what it is.
SOUND_ASSET = "minecraft/sounds/random/levelup.ogg"
ASSET_ROOTS = (
    "$MCSHELL_MC_ASSETS",
    "~/.local/share/PrismLauncher/assets",
    "~/.minecraft/assets",
)
PLAYERS = ("pw-play", "paplay")
#: A sound the player picked is cut off here. The default is 1.5 seconds; an
#: album track chosen by accident would otherwise play to the end of the album
#: track, five seconds after the toast it belonged to had gone.
SOUND_LIMIT = 5.0
#: What the file chooser will offer, and what `pw-play` will actually decode:
#: libsndfile 1.2.2 is on this machine and reads mp3 (measured — `pw-play`
#: exits 0 on one). Anything else is refused rather than silently never heard.
SOUND_SUFFIXES = (".ogg", ".oga", ".mp3", ".wav", ".flac", ".opus", ".aiff", ".aif")
#: Two notifications in the same instant are one sound. A group chat catching
#: up after a resume would otherwise play twenty.
SOUND_GAP = 0.75

_TAG = re.compile(r"<[^>]+>")


def _config() -> Path:
    return Path(BaseDirectory.save_config_path("mcshell")) / "notifications.json"


def plain(text: str) -> str:
    """Body markup out, entities decoded, whitespace collapsed to one line."""
    return " ".join(html.unescape(_TAG.sub("", text)).split())


def asset_path(name: str) -> str | None:
    """Where one of Minecraft's assets actually is, or None if it is not here.

    Minecraft's asset store is content-addressed: the file is called
    `b9c60e80...` and nothing on disk says what it is. The index that ships
    with the version is the only thing that maps a name to a hash, so every
    lookup goes through it.

    Public because the OSD needs the same three lines for its own sounds, and
    two copies of an asset-store walk would eventually disagree about which
    index wins.
    """
    for root in ASSET_ROOTS:
        base = Path(os.path.expandvars(os.path.expanduser(root)))
        if str(base) == root or not base.is_dir():
            continue
        for index in sorted(glob.glob(str(base / "indexes" / "*.json")), reverse=True):
            try:
                objects = json.load(open(index))["objects"]
            except Exception:
                continue
            entry = objects.get(name)
            if not entry:
                continue
            digest = entry["hash"]
            candidate = base / "objects" / digest[:2] / digest
            if candidate.is_file():
                return str(candidate)
    return None


def sound_path() -> str | None:
    """Where `levelup.ogg` is: a toast's own sound."""
    return asset_path(SOUND_ASSET)


class Notify:
    """The session's notification server."""

    def __init__(self, catalog, overlay, silent=None) -> None:
        self.catalog = catalog
        #: Asked whether the machine is muted before any sound is played.
        #: A callable rather than the Audio provider itself, because this needs
        #: one answer and should not learn what a sink is.
        self._silent = silent
        #: Shared with the OSD; started and stopped by the daemon, not here.
        self.overlay = overlay
        self.sound = True
        #: The master switch. Off still answers the bus — a sender that got an
        #: error would retry, or draw its own window — it simply shows nothing.
        self.enabled = True
        #: A sound the player chose, replacing the level-up. None is vanilla's.
        self.custom: str | None = None
        self.available = False
        self._bus = None
        self._next_id = 1
        self._sound_at = 0.0
        self._sound_file: str | None = None
        self._reap: set[asyncio.Task] = set()
        self._load()

    # -- the switches, on the Sound and General pages -----------------------

    def _load(self) -> None:
        try:
            saved = json.loads(_config().read_text())
        except Exception:
            return              # never written, or unreadable: defaults stand
        if not isinstance(saved, dict):
            return
        if "sound" in saved:
            self.sound = bool(saved["sound"])
        if "enabled" in saved:
            self.enabled = bool(saved["enabled"])
        custom = saved.get("file")
        # Checked on the way in rather than on the way out: a sound that was
        # deleted since it was chosen should read as "Minecraft level-up" on
        # the settings page, not as a filename that will never be heard.
        if isinstance(custom, str) and Path(custom).is_file():
            self.custom = custom

    def _save(self) -> None:
        try:
            _config().write_text(json.dumps(
                {"sound": self.sound, "enabled": self.enabled,
                 "file": self.custom}, indent=2))
        except OSError as e:
            log.warning("notify: could not save the notification settings: %s", e)

    def set_sound(self, on: bool) -> None:
        self.sound = bool(on)
        self._save()

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        self._save()

    def set_file(self, path: str | None) -> str | None:
        """Use `path` as the notification sound. Returns an error, or None.

        None puts the level-up back. The suffix is checked because the failure
        it prevents is silent: a player that cannot decode the file exits with
        a message into /dev/null, and the toast simply never makes a noise.
        """
        if path is None:
            self.custom = None
            self._save()
            return None
        chosen = Path(path).expanduser()
        if not chosen.is_file():
            return f"{chosen.name}: not a file"
        if chosen.suffix.lower() not in SOUND_SUFFIXES:
            return f"{chosen.suffix or 'that'} is not a sound this can play"
        self.custom = str(chosen)
        self._save()
        return None

    @property
    def sound_name(self) -> str:
        """What the sound is called, for the row that changes it."""
        return Path(self.custom).name if self.custom else "Minecraft level-up"

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> bool:
        try:
            from dbus_next import BusType, NameFlag, RequestNameReply
            from dbus_next.aio import MessageBus
        except Exception as e:
            log.warning("notify: dbus-next is unusable (%s); no notifications", e)
            return False

        try:
            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
            self._bus.export(OBJECT_PATH, _Interface(self))
            # DO_NOT_QUEUE: if something else is already the notification
            # daemon, say so and stay out of its way rather than waiting to
            # inherit the name at some unpredictable later moment.
            reply = await self._bus.request_name(BUS_NAME, NameFlag.DO_NOT_QUEUE)
        except Exception as e:
            log.warning("notify: could not take %s: %s", BUS_NAME, e)
            return False

        if reply != RequestNameReply.PRIMARY_OWNER:
            log.warning("notify: %s is already owned by something else (%s)",
                        BUS_NAME, reply)
            return False

        self._sound_file = sound_path()
        if self._sound_file is None:
            log.info("notify: no levelup.ogg in the asset store; toasts stay silent")
        self.available = True
        log.info("notify: serving %s", BUS_NAME)
        return True

    async def stop(self) -> None:
        self.available = False
        # The overlay is not ours to stop: the OSD draws on it too, and the
        # daemon shuts it down once.
        if self._bus is not None:
            with contextlib.suppress(Exception):
                self._bus.disconnect()
            self._bus = None

    # -- the notification --------------------------------------------------

    async def post(self, ident: int, app_name: str, app_icon: str,
                   summary: str, body: str, hints: dict) -> None:
        urgency = 1
        raw = hints.get("urgency")
        if raw is not None:
            with contextlib.suppress(TypeError, ValueError):
                urgency = int(getattr(raw, "value", raw))

        timeout = hints.get("_expire", -1)
        ms = DEFAULT_MS if timeout is None or timeout <= 0 else min(int(timeout), MAX_MS)

        if not self.enabled:
            # Accepted and dropped. The sender has already been given an id and
            # believes it succeeded, which is true: this session's answer to a
            # notification is currently to show nothing.
            return

        title = plain(summary) or plain(app_name)
        await self.overlay.send({
            "t": "toast", "id": ident,
            "title": title, "body": plain(body),
            "icon": self.icon_for(app_name, app_icon, hints),
            "urgency": urgency, "ms": ms,
        })

        if self.sound and not _flag(hints.get("suppress-sound")):
            await self._play()

    async def close(self, ident: int) -> None:
        await self.overlay.send({"t": "close", "id": int(ident)})

    def take_id(self) -> int:
        ident = self._next_id
        # Wraps rather than growing without bound; the spec's ids are u32 and
        # nothing here remembers a notification once it has faded.
        self._next_id = self._next_id % 0xFFFF + 1
        return ident

    def icon_for(self, app_name: str, app_icon: str, hints: dict) -> str | None:
        """See the module docstring: four guesses, first hit wins."""
        entry = _text(hints.get("desktop-entry"))
        if entry:
            app_id = entry if entry.endswith(".desktop") else f"{entry}.desktop"
            app = self.catalog.get(app_id)
            if app is None:
                app = self.catalog.get(app_id.lower())
            if app is not None and app.icon_path:
                return app.icon_path

        for candidate in (app_icon, _text(hints.get("image-path")),
                          _text(hints.get("image_path"))):
            if not candidate:
                continue
            if candidate.startswith("file://"):
                candidate = candidate[7:]
            found = self.catalog.resolve_icon(candidate)
            if found:
                return found

        if app_name:
            matches = self.catalog.query(app_name, limit=1)
            if matches and matches[0].icon_path:
                return matches[0].icon_path
        return None

    # -- talking to the overlay --------------------------------------------

    async def _play(self) -> None:
        sound = self.custom or self._sound_file
        if not sound:
            return
        now = time.monotonic()
        if now - self._sound_at < SOUND_GAP:
            return

        # A muted machine stays silent. Checked here rather than left to the
        # sink because playing to a muted sink is not free: opening a stream
        # wakes the device, and WirePlumber re-applies that route's saved
        # volume and mute when it comes back — which is how a muted laptop
        # ends up playing a notification at the volume it had an hour ago.
        # Not making the sound is both the correct behaviour and the thing
        # that stops the sink being woken at all.
        if self._silent is not None:
            try:
                if await self._silent():
                    return
            except Exception as e:
                # Fails open, deliberately. See Audio.silent.
                log.debug("notify: could not ask whether the sink is muted: %s", e)

        self._sound_at = now
        for player in PLAYERS:
            if shutil.which(player) is None:
                continue
            try:
                proc = await asyncio.create_subprocess_exec(
                    player, sound,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as e:
                log.debug("notify: %s: %s", player, e)
                continue
            # Awaited on a task so the child is reaped without the notification
            # waiting for a sound to finish playing — and killed at the limit,
            # so a long file chosen by mistake is a mistake you can hear the end
            # of rather than sit through.
            task = asyncio.create_task(self._until(proc), name="notify-sound")
            self._reap.add(task)
            task.add_done_callback(self._reap.discard)
            return

    async def _until(self, proc) -> None:
        try:
            await asyncio.wait_for(proc.wait(), SOUND_LIMIT)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(proc.wait(), 1.0)

    async def preview(self) -> None:
        """Play the sound now, whatever the dedupe window says.

        Choosing a sound and not hearing it is the one case where the gap that
        stops a group chat playing twenty level-ups is exactly wrong.
        """
        self._sound_at = 0.0
        await self._play()


def _text(value) -> str:
    """A dbus-next Variant, or a plain value, as a string."""
    value = getattr(value, "value", value)
    return value if isinstance(value, str) else ""


def _flag(value) -> bool:
    return bool(getattr(value, "value", value))


def _Interface(owner: "Notify"):
    """Built inside a function because dbus-next is an optional import: the
    daemon has to come up and say why on a machine without it."""
    from dbus_next.service import ServiceInterface, method, signal

    class Interface(ServiceInterface):
        """The freedesktop notification interface, version 1.2."""

        def __init__(self, owner: Notify) -> None:
            super().__init__(BUS_NAME)
            self.owner = owner

        @method()
        def GetServerInformation(self) -> "ssss":
            return ["mcshell", "mcshell", "0.0.0", "1.2"]

        @method()
        def GetCapabilities(self) -> "as":
            # Only what is true. See the module docstring on actions and markup.
            return ["body", "icon-static"]

        @method()
        def Notify(self, app_name: "s", replaces_id: "u", app_icon: "s",
                   summary: "s", body: "s", actions: "as", hints: "a{sv}",
                   expire_timeout: "i") -> "u":
            hints = dict(hints)
            hints["_expire"] = expire_timeout
            # The id is settled here, synchronously, because it is what the
            # sender is told and what it will pass back as `replaces_id`. The
            # drawing is not: the sender is blocked on this reply and a toast
            # is not its business.
            ident = replaces_id or self.owner.take_id()
            asyncio.create_task(self.owner.post(
                ident, app_name, app_icon, summary, body, hints))
            return ident

        @method()
        def CloseNotification(self, id: "u"):
            asyncio.create_task(self.owner.close(id))

        @signal()
        def NotificationClosed(self, id: "u", reason: "u") -> "uu":
            return [id, reason]

    return Interface(owner)
