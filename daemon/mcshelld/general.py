"""The General page: the shell's own settings, beside Minecraft's Accessibility.

Every other page is a window onto a subsystem — PipeWire, Sway, NetworkManager.
This one is a window onto MCShell: the handful of choices that exist because
the shell makes them, and that nothing else on the machine has an opinion
about. It sits in the Accessibility lane because that is the last vanilla
options screen with nothing of ours behind it, and because "what does this
shell draw, and what does it record" is the nearest thing the game has to the
subject.

**The lane still crosses both ways.** Minecraft's own accessibility settings —
narrator, text background, high-contrast, the panorama — are real settings for
a real player, and this world is played in. They are one button away in the
bottom-left corner, exactly like Sound, Video and Controls. Network is still
the only page with nowhere to go back to.

WHO OWNS WHAT

Two of these rows are drawn by the mod and mean nothing to the daemon, so
their values live here, in `general.json`:

    clock          whether the HUD draws the wall clock
    clock_format   system / 12 / 24
    battery_color  whether the XP-bar gauge is allowed to change colour

The other three belong to something that already existed, and this page only
routes to them — the setting is stored by whoever acts on it, so there is one
copy of each and nothing to keep in step:

    notifications          notify.py     (also on the Sound page: one switch,
    the notification sound notify.py      two doors — both read the same field)
    screen time            stats.py

THE SOUND IS PICKED IN A REAL WINDOW

No row type draws a text field, the game client is the wrong place to type a
path into, and there is no browse widget to build one out of. There is already
an answer to this shape of problem — the askpass helper, which puts sudo's
prompt on the compositor rather than in chat — and the desktop has a standard
one: `org.freedesktop.portal.FileChooser`, answered here by
xdg-desktop-portal-gtk, which was measured running before this was written. So
the button opens the same file chooser every other application on the machine
opens, and the daemon is handed a path.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
import os
import urllib.parse
from pathlib import Path

from xdg import BaseDirectory

from . import protocol as p
from .clock import MODES
from .notify import SOUND_SUFFIXES
from .osd import DEFAULT_SOUND, SOUNDS

log = logging.getLogger(__name__)

PAGE = "general"

DEFAULTS: dict[str, object] = {
    "clock": True,
    "clock_format": "system",
    "battery_color": True,
    "volume_sound": DEFAULT_SOUND,
}

MODE_LABELS = {"system": "System", "12": "12-hour", "24": "24-hour"}

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
#: How long the file chooser may stay open. Long, because it is a person
#: browsing; finite, because a dialog closed by the compositor rather than by
#: its own buttons never answers, and a task waiting forever is a leak.
PICKER_TIMEOUT = 300.0

_tokens = itertools.count(1)


def _config() -> Path:
    return Path(BaseDirectory.save_config_path("mcshell")) / "general.json"


async def choose_sound() -> tuple[str | None, str | None]:
    """Open the desktop's file chooser. Returns (path, error); both may be None.

    (None, None) is a cancel, which is not an error and should say nothing.

    Written against raw D-Bus messages rather than a proxy object because the
    reply has to be listened for *before* the call is made: the portal answers
    on a `Request` object that does not exist yet, so there is nothing to
    introspect and build a proxy from. Subscribing after the call would be a
    race — small, since a human has to click something first, but a race that
    loses silently and looks like a dialog that did nothing.
    """
    try:
        from dbus_next import BusType, Message, MessageType, Variant
        from dbus_next.aio import MessageBus
    except Exception as e:
        return None, f"dbus-next is unusable ({e})"

    try:
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
    except Exception as e:
        return None, f"no session bus ({e})"

    try:
        token = f"mcshell{os.getpid()}_{next(_tokens)}"
        sender = (bus.unique_name or ":0")[1:].replace(".", "_")
        handle = f"{PORTAL_PATH}/request/{sender}/{token}"

        loop = asyncio.get_running_loop()
        answer: asyncio.Future = loop.create_future()

        def listen(msg) -> None:
            if (msg.message_type is MessageType.SIGNAL
                    and msg.interface == "org.freedesktop.portal.Request"
                    and msg.member == "Response"
                    and not answer.done()):
                answer.set_result(msg.body)

        bus.add_message_handler(listen)
        await bus.call(Message(
            destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus", member="AddMatch", signature="s",
            body=["type='signal',interface='org.freedesktop.portal.Request',"
                  "member='Response'"]))

        # 0 is a glob; the portal's own filter type for a shell pattern.
        # Lists rather than tuples all the way down: dbus-next verifies a
        # STRUCT against `list` specifically and refuses a tuple.
        patterns = [[0, f"*{suffix}"] for suffix in SOUND_SUFFIXES]
        options = {
            "handle_token": Variant("s", token),
            "modal": Variant("b", False),
            "multiple": Variant("b", False),
            "accept_label": Variant("s", "Use this sound"),
            "filters": Variant("a(sa(us))", [["Sound files", patterns],
                                             ["Every file", [[0, "*"]]]]),
        }
        reply = await bus.call(Message(
            destination=PORTAL, path=PORTAL_PATH,
            interface="org.freedesktop.portal.FileChooser", member="OpenFile",
            signature="ssa{sv}", body=["", "MCShell notification sound", options]))

        if reply is None or reply.message_type is MessageType.ERROR:
            detail = reply.body[0] if reply and reply.body else "no reply"
            return None, f"no file chooser: {detail}"

        try:
            code, results = await asyncio.wait_for(answer, PICKER_TIMEOUT)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                await bus.call(Message(
                    destination=PORTAL, path=handle,
                    interface="org.freedesktop.portal.Request", member="Close"))
            return None, "the file chooser was left open"

        if code != 0:                       # 1 is cancelled, 2 is "ended some other way"
            return None, None
        uris = results.get("uris")
        uris = getattr(uris, "value", uris) or []
        if not uris:
            return None, None
        parsed = urllib.parse.urlparse(uris[0])
        if parsed.scheme != "file":
            return None, "that file is not on this machine"
        return urllib.parse.unquote(parsed.path), None
    finally:
        with contextlib.suppress(Exception):
            bus.disconnect()


class General:
    """Settings provider for the General page."""

    page = PAGE

    def __init__(self, clock, notify=None, screentime=None, osd=None,
                 on_change=None, on_hud=None):
        self._clock = clock
        self._notify = notify
        self._screentime = screentime
        self._on_change = on_change
        self._on_hud = on_hud
        # The volume popup, for the one row that chooses its sound.
        self._osd = osd
        self._prefs = dict(DEFAULTS)
        self._picking = False
        self._load()
        self._clock.mode = str(self._prefs["clock_format"])
        if self._osd is not None:
            self._osd.set_sound(str(self._prefs["volume_sound"]))

    # -- the two preferences that are only ever drawn ----------------------

    def _load(self) -> None:
        try:
            saved = json.loads(_config().read_text())
        except Exception:
            return
        if not isinstance(saved, dict):
            return
        # Each key is checked against what it is actually allowed to be, so a
        # hand-edited file with a nonsense value falls back to the default
        # instead of reaching the clock or the OSD.
        allowed = {"clock_format": MODES, "volume_sound": tuple(SOUNDS)}
        for key, default in DEFAULTS.items():
            if key not in saved:
                continue
            value = saved[key]
            if isinstance(default, bool):
                self._prefs[key] = bool(value)
            elif value in allowed.get(key, ()):
                self._prefs[key] = value

    def _save(self) -> None:
        try:
            _config().write_text(json.dumps(self._prefs, indent=2))
        except OSError as e:
            log.warning("general: could not save %s: %s", _config(), e)

    def hud(self) -> p.Hud:
        """What the HUD should be drawing right now."""
        when, date = self._clock.format()
        return p.Hud(
            clock=bool(self._prefs["clock"]),
            time=when, date=date,
            battery_color=bool(self._prefs["battery_color"]),
        )

    # -- reading -----------------------------------------------------------

    async def items(self) -> list[p.SettingsSchemaItem]:
        return (self._display_rows() + self._sound_rows()
                + self._notification_rows() + self._privacy_rows())

    def _sound_rows(self) -> list[p.SettingsSchemaItem]:
        """The noise the volume keys make.

        Its own group rather than filed under Notifications: a notification is
        something an application asked for, and this is the machine answering
        the person holding it.
        """
        if self._osd is None:
            return []
        return [p.SettingsSchemaItem(
            key="general.volume..sound", type="enum", page=PAGE, group="Volume",
            label="Volume key sound",
            value=str(self._prefs["volume_sound"]),
            default=DEFAULT_SOUND,
            detail="Played at the new volume, so you can hear how loud it is",
            options=[p.SettingsOption(id=key, label=label)
                     for key, (label, _) in SOUNDS.items()],
        )]

    def _display_rows(self) -> list[p.SettingsSchemaItem]:
        group = "Display"
        showing = bool(self._prefs["clock"])
        return [
            p.SettingsSchemaItem(
                key="general.clock..show", type="bool", page=PAGE, group=group,
                label="Clock", value=showing,
                detail="The date and time at the top left of the screen",
            ),
            p.SettingsSchemaItem(
                key="general.clock..format", type="enum", page=PAGE, group=group,
                label="Clock format", value=str(self._prefs["clock_format"]),
                options=[p.SettingsOption(id=mode, label=MODE_LABELS[mode])
                         for mode in MODES],
                detail=f"System is {self._clock.time_format()} here",
                enabled=showing,
            ),
            p.SettingsSchemaItem(
                key="general.battery..color", type="bool", page=PAGE, group=group,
                label="Color the battery gauge",
                value=bool(self._prefs["battery_color"]),
                detail="Off = green. On = white on charging, red when low",
            ),
        ]

    def _notification_rows(self) -> list[p.SettingsSchemaItem]:
        group = "Notifications"
        if self._notify is None:
            return []
        # Drawn even when the server never came up, greyed and saying why: a
        # row that vanishes leaves somebody looking for a setting that is not
        # missing, only unavailable.
        live = self._notify.available
        reason = "" if live else "the notification server did not start"
        custom = self._notify.custom is not None
        return [
            p.SettingsSchemaItem(
                key="general.notify..enabled", type="bool", page=PAGE, group=group,
                label="Show notifications", value=bool(self._notify.enabled),
                detail=reason or "Advancement Notifications; above all windows",
                enabled=live,
            ),
            p.SettingsSchemaItem(
                key="general.notify..sound", type="bool", page=PAGE, group=group,
                label="Notification sound", value=bool(self._notify.sound),
                detail=reason or "Also on the Sound menu, both work the same",
                enabled=live and self._notify.enabled,
            ),
            p.SettingsSchemaItem(
                key="general.notify..pick", type="action", page=PAGE, group=group,
                label=f"Sound: {self._notify.sound_name}",
                detail=self._notify.custom or "Choose an audio file",
                enabled=live and not self._picking,
            ),
            p.SettingsSchemaItem(
                key="general.notify..default", type="action", page=PAGE, group=group,
                label="Use the Minecraft sound",
                detail="Puts the level-up back",
                enabled=live and custom,
            ),
        ]

    def _privacy_rows(self) -> list[p.SettingsSchemaItem]:
        if self._screentime is None:
            return []
        return [p.SettingsSchemaItem(
            key="general.screentime..track", type="bool", page=PAGE,
            group="Screen time", label="Track screen time",
            value=bool(self._screentime.tracking),
            detail="Statistics → Machine. Off stops counting; nothing is erased",
        )]

    # -- writing -----------------------------------------------------------

    async def set(self, key: str, value) -> str | None:
        parts = key.split(".")
        if len(parts) < 4 or parts[0] != PAGE:
            return f"not a general setting: {key!r}"
        domain, field = parts[1], parts[-1]

        if domain == "clock":
            return await self._set_clock(field, value)
        if domain == "battery" and field == "color":
            return await self._set_pref("battery_color", bool(value))
        if domain == "volume" and field == "sound":
            if self._osd is None or not self._osd.set_sound(str(value)):
                return f"not a volume sound: {value!r}"
            self._prefs["volume_sound"] = str(value)
            self._save()
            # Played once, for the same reason choosing a notification sound
            # plays it: the point of picking a sound is to find out what it is.
            await self._osd.play()
            return None
        if domain == "notify":
            return await self._set_notify(field, value)
        if domain == "screentime" and field == "track":
            if self._screentime is None:
                return "screen time is not being kept"
            self._screentime.set_tracking(bool(value))
            return None
        return f"unknown general setting: {key!r}"

    async def _set_clock(self, field: str, value) -> str | None:
        if field == "show":
            return await self._set_pref("clock", bool(value))
        if field == "format":
            if value not in MODES:
                return f"not a clock format: {value!r}"
            self._clock.mode = value
            return await self._set_pref("clock_format", value)
        return f"unknown clock setting: {field!r}"

    async def _set_pref(self, name: str, value) -> str | None:
        self._prefs[name] = value
        self._save()
        await self._push_hud()
        return None

    async def _set_notify(self, field: str, value) -> str | None:
        if self._notify is None:
            return "no notification server"
        if field == "enabled":
            self._notify.set_enabled(bool(value))
            return None
        if field == "sound":
            self._notify.set_sound(bool(value))
            return None
        if field == "default":
            self._notify.set_file(None)
            return None
        if field == "pick":
            return await self._pick()
        return f"unknown notification setting: {field!r}"

    async def _pick(self) -> str | None:
        """Open the chooser, and do not block the socket while it is open.

        A file chooser is on screen for as long as somebody is browsing, and
        `set` is awaited inside the client's own request — so this returns at
        once and the page is pushed again when the dialog is answered. The row
        goes grey in the meantime, which is both true and the only honest way
        to say "that button is already doing something".
        """
        if self._picking:
            return "the file chooser is already open"
        self._picking = True
        await self._refresh()
        asyncio.create_task(self._pick_and_apply(), name="notify-sound-pick")
        return None

    async def _pick_and_apply(self) -> None:
        error = None
        try:
            path, error = await choose_sound()
            if path is not None:
                error = self._notify.set_file(path)
                if error is None:
                    # Heard, not merely chosen. The point of picking a sound is
                    # to find out what it sounds like.
                    await self._notify.preview()
        except Exception:
            log.exception("general: the file chooser failed")
            error = "the file chooser failed; see the daemon log"
        finally:
            self._picking = False
        if error:
            log.warning("general: notification sound: %s", error)
        await self._refresh()

    async def _refresh(self) -> None:
        if self._on_change is None:
            return
        res = self._on_change(PAGE)
        if asyncio.iscoroutine(res):
            await res

    async def _push_hud(self) -> None:
        if self._on_hud is None:
            return
        res = self._on_hud()
        if asyncio.iscoroutine(res):
            await res
