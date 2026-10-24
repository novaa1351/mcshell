"""The Sound page: PipeWire, through `pactl`.

CLAUDE.md's diagram says `wpctl`, and this is `pactl` instead for one reason:
`pactl --format=json` hands over sinks, sources, per-application streams and
card profiles as parsed data, where `wpctl status` prints a box-drawing tree
meant for people. Scraping that tree would put a fragile parser between the
daemon and the truth. Both talk to the same PipeWire.

The other half of the reason is `pactl subscribe`, which streams a line every
time anything changes. That is what lets an open settings page follow a media
key or a headset connecting, instead of showing whatever was true when it
opened. Polling would be the alternative, and a settings page nobody is looking
at should cost nothing.

Keys are `audio.<domain>.<id>.<field>`, where `<id>` may itself contain dots
(device names do) and may be empty, which means "whichever is default":

    audio.sink..volume          the default sink's volume
    audio.stream.6793.mute      one application's stream
    audio.card.alsa_card.pci-0000_00_1f.3.profile
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re

from . import protocol as p

log = logging.getLogger(__name__)

PAGE = "audio"

# pactl subscribe reports every change, and one user action makes several. Wait
# this long for the flurry to end before rebuilding the page.
DEBOUNCE = 0.15

# The OSD gets its own, much shorter one. Rebuilding the Sound page can wait
# 150ms because nobody is watching it change; a volume bar that appears a sixth
# of a second after the key reads as a laggy machine.
OSD_DEBOUNCE = 0.02

# Long enough for a wedged pactl to be obvious, short enough not to hold the
# socket. Nothing here should take more than milliseconds.
TIMEOUT = 5.0


def _volume_of(obj: dict) -> float:
    """Average channel volume, as 0..1."""
    channels = obj.get("volume") or {}
    values = []
    for ch in channels.values():
        pct = str(ch.get("value_percent", "")).rstrip("%")
        try:
            values.append(float(pct) / 100.0)
        except ValueError:
            continue
    if not values:
        return 0.0
    # The average rather than the max: a balance set off-centre should not
    # jump to centred the moment someone touches the slider.
    return round(sum(values) / len(values), 3)


def _describe(obj: dict) -> str:
    """The friendliest name a device has."""
    props = obj.get("properties") or {}
    for candidate in (
        obj.get("description"),
        props.get("device.description"),
        props.get("node.description"),
        obj.get("name"),
    ):
        if candidate:
            return str(candidate)
    return "Unknown device"


def _stream_name(obj: dict) -> tuple[str, str]:
    """An application stream's name, and the second line under it."""
    props = obj.get("properties") or {}
    name = (
        props.get("application.name")
        or props.get("application.process.binary")
        or props.get("media.name")
        or f"Stream {obj.get('index', '?')}"
    )
    detail = props.get("media.name") or ""
    if detail == name:
        detail = ""
    return str(name), str(detail)


def _is_monitor(source: dict) -> bool:
    """Monitors are a sink's own output looped back; not an input device."""
    props = source.get("properties") or {}
    return props.get("device.class") == "monitor" or str(source.get("name", "")).endswith(".monitor")


class Audio:
    """Settings provider for the Sound page."""

    page = PAGE

    def __init__(self, on_change=None, notifications=None, osd=None):
        self._on_change = on_change
        # The volume popup. Driven from the subscription rather than from the
        # keybinding, so `wpctl` from anywhere — a media key, the command bar,
        # our own slider — draws the same bar. See osd.py.
        self._osd = osd
        #: The last level seen, as (volume, muted). None until the first read,
        #: which is deliberately silent: a daemon coming up is not somebody
        #: changing the volume.
        #:
        #: `_last_level`, not `_level`, and the name is the whole bug it fixes.
        #: There is a `_set_level` method below, and an instance attribute wins
        #: over a method of the same name in Python — silently, at `__init__`,
        #: for the life of the object. Every volume and mute the Sound page
        #: ever sent died on `'NoneType' object is not callable`, and once a
        #: sink event had been seen, `'tuple' object is not callable`. The
        #: media keys kept working throughout because they go straight to
        #: `wpctl` and never come through here, which is what made it look like
        #: a bug about audio playing.
        self._last_level: tuple[int, bool] | None = None
        # The notification server, for the one row below that is not PipeWire's.
        # It lives on this page because "should notifications make a sound" is
        # a question people go to a Sound page to answer, not a Notifications
        # one that would otherwise hold a single switch.
        self._notifications = notifications
        self._sub: asyncio.subprocess.Process | None = None
        self._task: asyncio.Task | None = None
        self._debounce: asyncio.Task | None = None
        self._osd_task: asyncio.Task | None = None
        #: Set when a volume key was pressed, cleared when the bar is drawn.
        #: A press that changes nothing produces no PipeWire event, so this is
        #: the only thing that says the bar should appear anyway.
        self._osd_forced = False
        self.available = False

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> bool:
        """Begin watching PipeWire. False if pactl cannot talk to it."""
        if await self._pactl_json("list", "sinks") is None:
            log.warning("audio: pactl found no PipeWire; the Sound page will be empty")
            self.available = False
            return False
        self.available = True
        # Read once and shown to nobody, so the first real change has something
        # to be different from.
        await self._check_level(announce=False)
        self._task = asyncio.create_task(self._watch(), name="audio-subscribe")
        return True

    async def stop(self) -> None:
        for task in (self._debounce, self._osd_task, self._task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._debounce = self._osd_task = self._task = None
        if self._sub is not None and self._sub.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._sub.terminate()
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(self._sub.wait(), 2.0)
        self._sub = None

    async def _watch(self) -> None:
        """Follow `pactl subscribe`, restarting it if it dies."""
        backoff = 1.0
        while True:
            try:
                self._sub = await asyncio.create_subprocess_exec(
                    "pactl", "subscribe",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as e:
                log.warning("audio: cannot start pactl subscribe: %s", e)
                return
            backoff = 1.0
            assert self._sub.stdout is not None
            async for raw in self._sub.stdout:
                event = raw.decode("utf-8", errors="replace")
                # Our own reads and writes make client events. Reacting to them
                # would mean rebuilding the page every time we built it.
                if "on client" in event:
                    continue
                # Only a sink event can be a volume change, and checking costs
                # two `pactl` calls — not something to do because a stream
                # appeared.
                if "on sink" in event:
                    self._schedule_osd()
                self._schedule()
            await self._sub.wait()
            log.warning("audio: pactl subscribe exited; retrying in %.0fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def _schedule(self) -> None:
        """Coalesce a flurry of events into one rebuild."""
        if self._debounce is not None and not self._debounce.done():
            return

        async def fire() -> None:
            await asyncio.sleep(DEBOUNCE)
            if self._on_change is not None:
                res = self._on_change(PAGE)
                if asyncio.iscoroutine(res):
                    await res

        self._debounce = asyncio.create_task(fire(), name="audio-debounce")

    async def announce_level(self) -> None:
        """Draw the bar because a key was pressed, not because a level moved.

        See `protocol.OsdVolume`. Debounced like the subscription is: a held
        key repeats, and the answer is the same bar every time.
        """
        self._osd_forced = True
        self._schedule_osd()

    def _schedule_osd(self) -> None:
        """Same coalescing as the page, on a much shorter fuse.

        One `wpctl set-volume` makes several sink events; without this, holding
        the key down would run two `pactl` calls per event rather than per
        notch.
        """
        if self._osd is None:
            return
        if self._osd_task is not None and not self._osd_task.done():
            return

        async def fire() -> None:
            await asyncio.sleep(OSD_DEBOUNCE)
            await self._check_level()

        self._osd_task = asyncio.create_task(fire(), name="audio-osd")

    async def _check_level(self, announce: bool = True) -> None:
        """Show the bar if the default sink's level actually moved.

        `pactl subscribe` says a sink changed, not what about it changed, and a
        sink says so for reasons that are not the volume — a stream attaching,
        a port switching, a suspend. Comparing against what was there last is
        the only way to tell, and it is also what keeps the bar from appearing
        when nothing a person did caused it.
        """
        forced, self._osd_forced = self._osd_forced, False
        level = await self._sink_level()
        if level is None:
            return
        previous, self._last_level = self._last_level, level
        if not announce:
            return
        # `forced` is a keypress, and a keypress draws the bar whether or not
        # anything moved — that is the whole point of it. Everything else has
        # to have changed to be worth showing.
        if not forced and (previous is None or previous == level):
            return
        if self._osd is not None:
            volume, muted = level
            await self._osd.volume(volume / 100.0, muted)

    async def _sink_level(self) -> tuple[int, bool] | None:
        """The default sink's volume as a whole percent, and whether it is muted.

        Two small `pactl` calls rather than the whole `list sinks` the page
        builds from: this runs on every notch of a held key, and parsing every
        sink's ports and formats to read one number would be paid there.

        Rounded to a percent because that is what the bar shows. PipeWire's
        cubic mapping means one `5%+` step is not exactly five points, so
        comparing raw floats would call two identical-looking levels different.
        """
        volume = await self._pactl("get-sink-volume", "@DEFAULT_SINK@")
        mute = await self._pactl("get-sink-mute", "@DEFAULT_SINK@")
        if volume is None or mute is None:
            return None
        # "Volume: front-left: 29491 /  45% / -20.81 dB,   front-right: ..."
        percents = [int(m) for m in re.findall(r"/\s*(\d+)%", volume)]
        if not percents:
            log.debug("audio: could not read a level out of %r", volume)
            return None
        return round(sum(percents) / len(percents)), "yes" in mute.lower()

    # -- reading -----------------------------------------------------------

    async def _pactl(self, *args: str) -> str | None:
        """Run pactl and return its stdout, or None if it failed."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pactl", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            log.warning("audio: pactl %s: %s", " ".join(args), e)
            return None
        try:
            out, err = await asyncio.wait_for(proc.communicate(), TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            log.warning("audio: pactl %s timed out", " ".join(args))
            return None
        if proc.returncode != 0:
            log.warning(
                "audio: pactl %s failed: %s",
                " ".join(args), err.decode("utf-8", errors="replace").strip(),
            )
            return None
        return out.decode("utf-8", errors="replace")

    async def _pactl_json(self, *args: str) -> list | None:
        out = await self._pactl("--format=json", *args)
        if out is None:
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            log.warning("audio: pactl %s gave unparseable JSON: %s", " ".join(args), e)
            return None
        return data if isinstance(data, list) else None

    async def silent(self) -> bool:
        """Is the default output muted, or turned all the way down?

        Asked by the notification sound before it plays. A muted machine that
        makes a noise is a broken machine, and this is the one place that
        cannot be answered from a setting: the volume keys go straight to
        `wpctl` so the rails work with the daemon dead, so PipeWire is the only
        thing that knows.

        Fails *open* — a PipeWire that will not answer gets a sound rather than
        silence, because a notification you cannot hear is the failure this
        whole page exists to avoid, and never hearing one again would be worse
        than hearing one you did not want.
        """
        sinks, default = await asyncio.gather(
            self._pactl_json("list", "sinks"),
            self._pactl("get-default-sink"),
        )
        if not sinks:
            return False
        default = (default or "").strip()
        sink = next((d for d in sinks if d.get("name") == default), sinks[0])
        # Zero is its own case, not a rounding of quiet: `wpctl set-volume 5%-`
        # bottoms out at exactly 0 and people use that instead of mute.
        return bool(sink.get("mute")) or _volume_of(sink) <= 0.0

    async def items(self) -> list[p.SettingsSchemaItem]:
        """Build the whole Sound page from one look at PipeWire."""
        sinks, sources, streams, cards, default_sink, default_source = await asyncio.gather(
            self._pactl_json("list", "sinks"),
            self._pactl_json("list", "sources"),
            self._pactl_json("list", "sink-inputs"),
            self._pactl_json("list", "cards"),
            self._pactl("get-default-sink"),
            self._pactl("get-default-source"),
        )
        if sinks is None:
            return [p.SettingsSchemaItem(
                key="audio.status..text", type="label", page=PAGE,
                label="PipeWire is not answering", enabled=False,
            )]

        sources = [s for s in (sources or []) if not _is_monitor(s)]
        default_sink = (default_sink or "").strip()
        default_source = (default_source or "").strip()

        items: list[p.SettingsSchemaItem] = []
        items += self._device_rows(
            "sink", "Output", sinks, default_sink, "Output device")
        items += self._device_rows(
            "source", "Input", sources, default_source, "Input device")

        for stream in streams or []:
            index = stream.get("index")
            if index is None:
                continue
            name, detail = _stream_name(stream)
            items.append(p.SettingsSchemaItem(
                key=f"audio.stream.{index}.volume", type="float", page=PAGE,
                group="Applications", label=name, detail=detail,
                value=_volume_of(stream), min=0.0, max=1.0, step=0.01, unit="%",
            ))
            items.append(p.SettingsSchemaItem(
                key=f"audio.stream.{index}.mute", type="bool", page=PAGE,
                group="Applications", label=f"{name} muted",
                value=bool(stream.get("mute")),
            ))
        if not streams:
            items.append(p.SettingsSchemaItem(
                key="audio.stream..none", type="label", page=PAGE,
                group="Applications", label="Nothing is playing", enabled=False,
            ))

        for card in cards or []:
            name = card.get("name")
            if not name:
                continue
            profiles = card.get("profiles") or {}
            # An unavailable profile is one the hardware cannot do right now —
            # a headset's A2DP while it is connected for calls. Offering it
            # would be offering a button that fails.
            options = [
                p.SettingsOption(id=key, label=str(spec.get("description") or key))
                for key, spec in profiles.items()
                if spec.get("available", True)
            ]
            if len(options) < 2:
                continue
            items.append(p.SettingsSchemaItem(
                key=f"audio.card.{name}.profile", type="enum", page=PAGE,
                group="Devices", label=_describe(card), detail=str(name),
                value=card.get("active_profile"), options=options,
            ))

        items += self._notification_rows()
        return items

    def _notification_rows(self) -> list[p.SettingsSchemaItem]:
        """The one row on this page that is not PipeWire's.

        Drawn even when the notification server failed to come up, disabled
        and saying so: a switch that has silently stopped meaning anything is
        worse than a switch that admits it.
        """
        if self._notifications is None:
            return []
        return [p.SettingsSchemaItem(
            key="audio.notify..sound", type="bool", page=PAGE,
            group="Notifications", label="Notification sound",
            detail="no notification server" if not self._notifications.available
                   else "" if self._notifications.enabled
                   else "notifications are switched off on the General page",
            value=bool(self._notifications.sound),
            enabled=self._notifications.available and self._notifications.enabled,
        )]

    def _device_rows(
        self, domain: str, group: str, devices: list, default: str, label: str
    ) -> list[p.SettingsSchemaItem]:
        """The default-device chooser, and the volume and mute that follow it.

        Volume and mute are shown for the *default* device only. A page with a
        slider per sink would be four sliders on this machine, three of them
        for HDMI ports with nothing plugged in.
        """
        options = [
            p.SettingsOption(id=str(d.get("name")), label=_describe(d))
            for d in devices if d.get("name")
        ]
        current = next((d for d in devices if d.get("name") == default), None)
        if current is None and devices:
            current = devices[0]

        rows = [p.SettingsSchemaItem(
            key=f"audio.{domain}..default", type="enum", page=PAGE, group=group,
            label=label, value=default or (current or {}).get("name"),
            options=options, detail=str((current or {}).get("name") or ""),
            enabled=bool(options),
        )]
        if current is None:
            rows.append(p.SettingsSchemaItem(
                key=f"audio.{domain}..none", type="label", page=PAGE, group=group,
                label="No device", enabled=False,
            ))
            return rows
        rows.append(p.SettingsSchemaItem(
            key=f"audio.{domain}..volume", type="float", page=PAGE, group=group,
            label="Volume", value=_volume_of(current),
            min=0.0, max=1.0, step=0.01, unit="%",
        ))
        rows.append(p.SettingsSchemaItem(
            key=f"audio.{domain}..mute", type="bool", page=PAGE, group=group,
            label="Muted", value=bool(current.get("mute")),
        ))
        return rows

    # -- writing -----------------------------------------------------------

    async def set(self, key: str, value) -> str | None:
        """Apply one change. Returns an error message, or None on success."""
        parts = key.split(".")
        if len(parts) < 4 or parts[0] != "audio":
            return f"not an audio setting: {key!r}"
        domain, field = parts[1], parts[-1]
        ident = ".".join(parts[2:-1])

        if domain == "notify":
            if field != "sound":
                return f"unknown notification setting: {key!r}"
            if self._notifications is None:
                return "no notification server"
            self._notifications.set_sound(bool(value))
            return None

        if domain in ("sink", "source"):
            target = ident or ("@DEFAULT_SINK@" if domain == "sink" else "@DEFAULT_SOURCE@")
            if field == "default":
                if not isinstance(value, str) or not value:
                    return "a default device must be named"
                ok = await self._pactl(f"set-default-{domain}", value)
                return None if ok is not None else f"could not select {value}"
            return await self._set_level(domain, target, field, value)

        if domain == "stream":
            if not ident.isdigit():
                return f"not a stream index: {ident!r}"
            return await self._set_level("sink-input", ident, field, value)

        if domain == "card" and field == "profile":
            if not isinstance(value, str) or not value:
                return "a profile must be named"
            ok = await self._pactl("set-card-profile", ident, value)
            return None if ok is not None else f"could not set profile {value!r}"

        return f"unknown audio setting: {key!r}"

    async def _set_level(self, kind: str, target: str, field: str, value) -> str | None:
        """Volume or mute, for a sink, a source or one application's stream."""
        if field == "volume":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "volume must be a number"
            pct = max(0, min(100, round(float(value) * 100)))
            ok = await self._pactl(f"set-{kind}-volume", target, f"{pct}%")
            return None if ok is not None else "could not set the volume"
        if field == "mute":
            if not isinstance(value, bool):
                return "mute must be true or false"
            ok = await self._pactl(f"set-{kind}-mute", target, "1" if value else "0")
            return None if ok is not None else "could not set mute"
        return f"unknown field {field!r}"
