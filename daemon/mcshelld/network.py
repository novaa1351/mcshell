"""The Network page: NetworkManager and BlueZ, on one screen.

Three subsystems that share nothing but the question "am I connected to
anything" — Wi-Fi, the ethernet port, and Bluetooth. They are one page with
three groups rather than three pages, because the answer a person came looking
for is usually just that one.

`nmcli` rather than NetworkManager's D-Bus API, and for the reason M6 chose
`pactl` over `wpctl`: `nmcli -t` hands over devices, saved profiles, scan
results and active connections as delimited fields, and `nmcli monitor` streams
a line every time any of it changes — which is what lets an open page follow a
cable being plugged in instead of polling. NM's D-Bus surface is large, its
secret-agent flow for passwords is a protocol of its own, and `dbus-next` is not
even installed. CLAUDE.md's diagram says D-Bus; this is the same departure, made
the same way.

Bluetooth is `bluetoothctl`, which does take one-shot commands, plus `gdbus
monitor` for the same live-update reason. BlueZ has no CLI with `nmcli`'s
`-t`, so this half parses human output; it is kept to the two lines that have
never changed shape (`Device <mac> <name>` and `Key: value`).

Keys are `network.<domain>.<id>.<field>`, where `<id>` may contain dots — an
SSID can be anything at all — and may be empty for "the one there is":

    network.wifi..enabled           the radio
    network.ap.<ssid>.connect       one network in range
    network.saved.<uuid>.forget     one stored profile
    network.wired.<device>.connect  the ethernet port
    network.bt.<mac>.connect        one Bluetooth device

Nothing here blocks. Connecting to a network takes seconds to tens of seconds
and the daemon reads one client message at a time, so an awaited `nmcli device
wifi connect` would stall the mod's socket — including the pointer handshake,
which is the one thing in this daemon that must never wait. Actions are started
and left to run; `nmcli monitor` reports what became of them, and anything that
fails is put back on the page as a line rather than as a reply nobody is still
listening for.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import protocol as p

log = logging.getLogger(__name__)

PAGE = "network"

# NetworkManager narrates a connection in a dozen lines. Wait for the flurry to
# end before rebuilding, the way the Sound page waits out PipeWire.
DEBOUNCE = 0.4

# Reads only. Every one of these is a local query that should take milliseconds;
# long enough for a wedged nmcli to be obvious, short enough not to hold the
# socket.
TIMEOUT = 8.0

# Writes: how long an action is given before it is killed. Association plus DHCP
# on a slow AP is genuinely tens of seconds.
ACTION_TIMEOUT = 90.0

# How long a failure stays on the page. Long enough to read, short enough that
# it does not become furniture.
NOTICE_TTL = 20.0

# `bluetoothctl scan on` never returns on its own — it is a REPL command. Its
# --timeout flag is what makes it a one-shot.
SCAN_SECONDS = 10

# bluetoothctl waits for org.bluez to appear rather than failing, so with the
# service stopped every call hangs until something kills it. Measured: 8s of a
# stalled socket the first time the page was opened. Hence its own short
# timeout, and hence the snapshot below.
BT_TIMEOUT = 3.0

# How often the Bluetooth snapshot is refreshed when nothing has said it
# changed. This is not how the page keeps up — gdbus does that — it is how the
# page notices BlueZ starting or stopping, which is the one event a watcher
# attached to BlueZ cannot report.
BT_POLL = 20.0

# The password prompt for a secured network. The same helper `sudo` uses, for
# the same reason: CLAUDE.md's rail is that credentials are asked for in a real
# compositor window and never inside the game client.
ASKPASS = Path(__file__).resolve().parents[1] / "tools" / "mcshell-askpass"


# Signal strength, in words, because the number is never still. Measured over
# a couple of minutes on one desk: the same access point read 92 and then 85,
# and every one of those changes would relabel a row and reorder the list under
# the cursor. Four buckets change when the answer changes, and Minecraft does
# not put percentages on things anyway.
SIGNAL_WORDS = ((70, "strong"), (45, "good"), (20, "weak"), (0, "faint"))


def _strength(signal: int) -> tuple[int, str]:
    """A signal as (bucket, word). Sorting on the bucket keeps the list still."""
    for index, (floor, word) in enumerate(SIGNAL_WORDS):
        if signal >= floor:
            return len(SIGNAL_WORDS) - index, word
    return 0, SIGNAL_WORDS[-1][1]


def _split(line: str) -> list[str]:
    """Split one `nmcli -t` record.

    `nmcli` escapes a literal colon as `\\:` and a backslash as `\\\\`, which
    matters more here than anywhere else in this daemon: an SSID is arbitrary
    bytes, and `str.split(":")` would quietly cut one in half.
    """
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


@dataclass
class Device:
    name: str
    type: str
    state: str
    connection: str

    @property
    def connected(self) -> bool:
        return self.state.startswith("connected")

    @property
    def busy(self) -> bool:
        return self.state.startswith("connecting") or self.state.startswith("deactivating")


@dataclass
class AccessPoint:
    ssid: str
    signal: int
    security: str
    in_use: bool

    @property
    def secured(self) -> bool:
        # nmcli prints an empty SECURITY for an open network, and "--" for one
        # it could not read.
        return self.security not in ("", "--")


@dataclass
class Saved:
    name: str
    uuid: str
    type: str
    autoconnect: bool
    device: str


@dataclass
class BluetoothDevice:
    mac: str
    name: str
    paired: bool = False
    connected: bool = False


@dataclass
class Bluetooth:
    """What BlueZ says about itself, or why it said nothing."""

    running: bool = False
    powered: bool = False
    controller: str = ""
    devices: list[BluetoothDevice] = field(default_factory=list)


class Network:
    """Settings provider for the Network page."""

    page = PAGE

    def __init__(self, on_change=None):
        self._on_change = on_change
        self._watchers: list[asyncio.Task] = []
        self._subs: list[asyncio.subprocess.Process] = []
        self._debounce: asyncio.Task | None = None
        # One action at a time. Two overlapping connects would race for the
        # radio and neither result would mean anything.
        self._action: asyncio.Task | None = None
        self._doing = ""
        self._notice = ""
        self._notice_until = 0.0
        self.available = False
        # BlueZ, as of the last look. Never read live while building the page:
        # see BT_TIMEOUT. The page is a render of this, and this is kept
        # current by its own task.
        self._bt = Bluetooth()
        self._bt_wake = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> bool:
        """Begin watching. False if NetworkManager is not answering."""
        if shutil.which("nmcli") is None:
            log.warning("network: nmcli is not installed; the Network page will be empty")
            return False
        if await self._nmcli("-t", "-f", "RUNNING", "general") is None:
            log.warning("network: NetworkManager is not answering")
            return False
        self.available = True
        self._spawn("nmcli-monitor", self._watch_nmcli())
        if shutil.which("bluetoothctl"):
            self._spawn("bluez-poll", self._watch_bluetooth())
            if shutil.which("gdbus"):
                self._spawn("bluez-monitor", self._watch_bluez())
        return True

    async def stop(self) -> None:
        for task in (*self._watchers, self._debounce, self._action):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._watchers.clear()
        self._debounce = self._action = None
        for sub in self._subs:
            if sub.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    sub.terminate()
                with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                    await asyncio.wait_for(sub.wait(), 2.0)
        self._subs.clear()

    def _spawn(self, name: str, coro) -> None:
        self._watchers.append(asyncio.create_task(coro, name=name))

    async def _watch_nmcli(self) -> None:
        await self._follow("nmcli", ("nmcli", "monitor"))

    async def _watch_bluez(self) -> None:
        """Follow BlueZ's property changes.

        `gdbus monitor` rather than `dbus-monitor`: BlueZ's signals are
        broadcast, so an ordinary AddMatch is enough to see them, where
        dbus-monitor asks the system bus to make it a monitor and is refused
        for anyone but root.
        """
        await self._follow("bluez", ("gdbus", "monitor", "--system", "--dest", "org.bluez"),
                           self._bt_wake.set)

    async def _watch_bluetooth(self) -> None:
        """Keep the Bluetooth snapshot current, off the page's critical path.

        Woken by gdbus when BlueZ says something, and otherwise on a slow poll
        — which is not belt and braces. gdbus dies with the service it is
        watching, so a stopped bluetoothd is exactly the case its own watcher
        cannot report, and the poll is what turns "the service is not running"
        back into a working section when someone starts it.
        """
        while True:
            before = self._bt
            self._bt = await self._read_bluetooth()
            if self._bt != before:
                self._schedule()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._bt_wake.wait(), BT_POLL)
            self._bt_wake.clear()

    async def _follow(self, what: str, argv: tuple[str, ...], on_line=None) -> None:
        """Rebuild the page on every line one of these prints, forever."""
        react = on_line if on_line is not None else self._schedule
        backoff = 1.0
        while True:
            try:
                sub = await asyncio.create_subprocess_exec(
                    *argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as e:
                log.warning("network: cannot start %s: %s", " ".join(argv), e)
                return
            self._subs.append(sub)
            assert sub.stdout is not None
            async for _ in sub.stdout:
                react()
            await sub.wait()
            with contextlib.suppress(ValueError):
                self._subs.remove(sub)
            # A BlueZ that is not running takes gdbus down with it, over and
            # over. Back off rather than spin, and say so once a minute at most.
            log.info("network: %s watcher exited; retrying in %.0fs", what, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    def _schedule(self) -> None:
        if self._debounce is not None and not self._debounce.done():
            return

        async def fire() -> None:
            await asyncio.sleep(DEBOUNCE)
            if self._on_change is not None:
                res = self._on_change(PAGE)
                if asyncio.iscoroutine(res):
                    await res

        self._debounce = asyncio.create_task(fire(), name="network-debounce")

    # -- running things ----------------------------------------------------

    async def _run(self, argv: list[str], timeout: float = TIMEOUT) -> tuple[int, str, str]:
        """Run a command to completion. Returns (code, stdout, stderr)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return 127, "", str(e)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            return 124, "", f"{argv[0]} timed out"
        return (
            proc.returncode or 0,
            out.decode("utf-8", errors="replace"),
            err.decode("utf-8", errors="replace"),
        )

    async def _nmcli(self, *args: str) -> str | None:
        code, out, err = await self._run(["nmcli", *args])
        if code != 0:
            log.warning("network: nmcli %s failed: %s", " ".join(args), err.strip())
            return None
        return out

    async def _btctl(self, *args: str, timeout: float = BT_TIMEOUT) -> str | None:
        code, out, err = await self._run(["bluetoothctl", *args], timeout)
        if code != 0:
            return None
        return out

    @staticmethod
    def _reason(out: str, err: str, fallback: str) -> str:
        """The one line worth showing out of whatever a tool printed."""
        for text in (err, out):
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                return lines[-1].removeprefix("Error: ")
        return fallback

    def _say(self, message: str) -> None:
        self._notice = message
        self._notice_until = time.monotonic() + NOTICE_TTL
        self._schedule()

    def _begin(self, what: str, coro) -> str | None:
        """Start a background action, or say why it cannot start now."""
        if self._action is not None and not self._action.done():
            # Closed, not dropped: an un-awaited coroutine is a RuntimeWarning
            # and a leak, and this path is reached by double-clicking a button.
            coro.close()
            return f"still {self._doing}"
        self._notice = ""
        self._doing = what

        async def run() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("network: %s failed", what)
                self._say(f"{what}: {e}")
            finally:
                self._doing = ""
                self._schedule()

        self._action = asyncio.create_task(run(), name=f"network-{what}")
        # Redraw at once so the page says what it is doing rather than sitting
        # unchanged until NetworkManager gets round to mentioning it.
        self._schedule()
        return None

    # -- reading -----------------------------------------------------------

    async def _devices(self) -> list[Device]:
        out = await self._nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        devices: list[Device] = []
        for line in (out or "").splitlines():
            fields = _split(line)
            if len(fields) >= 4 and fields[1] not in ("loopback", "wifi-p2p"):
                devices.append(Device(fields[0], fields[1], fields[2], fields[3]))
        return devices

    async def _access_points(self) -> list[AccessPoint]:
        """Every network in range, strongest first, one row per name.

        A single network is several APs — two bands, or a mesh — and nmcli lists
        each. Collapsing them by name is what makes the list a list of places
        rather than a list of radios; NetworkManager picks the band itself.
        """
        out = await self._nmcli(
            "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "no")
        best: dict[str, AccessPoint] = {}
        for line in (out or "").splitlines():
            fields = _split(line)
            if len(fields) < 4 or not fields[1]:
                # An empty SSID is a hidden network. There is nothing to click:
                # joining one needs its name typed, and no row type can.
                continue
            try:
                signal = int(fields[2])
            except ValueError:
                signal = 0
            ap = AccessPoint(fields[1], signal, fields[3].strip(), fields[0].strip() == "*")
            seen = best.get(ap.ssid)
            if seen is None or ap.signal > seen.signal:
                best[ap.ssid] = AccessPoint(
                    ap.ssid, ap.signal, ap.security, ap.in_use or (seen.in_use if seen else False))
            elif ap.in_use:
                seen.in_use = True
        # By strength bucket, then by name. Sorting on the raw number would
        # shuffle the rows every time NetworkManager rescanned.
        return sorted(best.values(),
                      key=lambda a: (-_strength(a.signal)[0], a.ssid.lower()))

    async def _saved(self) -> list[Saved]:
        out = await self._nmcli(
            "-t", "-f", "NAME,UUID,TYPE,AUTOCONNECT,DEVICE", "connection", "show")
        saved: list[Saved] = []
        for line in (out or "").splitlines():
            fields = _split(line)
            if len(fields) >= 5 and fields[2] not in ("loopback",):
                saved.append(Saved(fields[0], fields[1], fields[2],
                                   fields[3] == "yes", fields[4]))
        return saved

    async def _addresses(self, device: str) -> tuple[str, str]:
        """One device's IPv4 address and gateway, either possibly empty."""
        out = await self._nmcli("-t", "-f", "IP4.ADDRESS,IP4.GATEWAY", "device", "show", device)
        address = gateway = ""
        for line in (out or "").splitlines():
            key, _, value = line.partition(":")
            if key.startswith("IP4.ADDRESS") and not address:
                address = value
            elif key == "IP4.GATEWAY" and value != "--":
                gateway = value
        return address, gateway

    async def _read_bluetooth(self) -> Bluetooth:
        show = await self._btctl("show")
        if show is None:
            return Bluetooth()
        state = Bluetooth(running=True)
        for line in show.splitlines():
            key, _, value = line.strip().partition(":")
            value = value.strip()
            if key == "Powered":
                state.powered = value.startswith("yes")
            elif key == "Name" and not state.controller:
                state.controller = value
            elif key == "Alias":
                state.controller = value
        if not state.powered:
            # An unpowered adapter still remembers its devices, but nothing can
            # be done with them and a list of dead buttons is worse than none.
            return state

        known = self._device_lines(await self._btctl("devices"))
        paired = set(self._device_lines(await self._btctl("devices", "Paired")))
        connected = set(self._device_lines(await self._btctl("devices", "Connected")))
        state.devices = [
            BluetoothDevice(mac, name, mac in paired, mac in connected)
            for mac, name in known.items()
        ]
        # Connected first, then paired, then whatever the last scan turned up.
        state.devices.sort(key=lambda d: (not d.connected, not d.paired, d.name.lower()))
        return state

    @staticmethod
    def _device_lines(out: str | None) -> dict[str, str]:
        """Parse `Device AA:BB:CC:DD:EE:FF Some Name` lines."""
        found: dict[str, str] = {}
        for line in (out or "").splitlines():
            parts = line.strip().split(" ", 2)
            if len(parts) >= 2 and parts[0] == "Device":
                found[parts[1]] = parts[2] if len(parts) > 2 else parts[1]
        return found

    # -- the page ----------------------------------------------------------

    async def items(self) -> list[p.SettingsSchemaItem]:
        if not self.available:
            return [_label("network.wifi..none", "Wi-Fi",
                           "NetworkManager is not answering")]

        # Read the busy flag once, before anything is awaited. An action can
        # finish part-way through building the page, and half a page that
        # thinks it is busy beside half that does not is a page with two
        # opinions — some buttons greyed, some not, for no reason a person
        # could see.
        notice = self._current_notice()
        busy = bool(self._doing)

        devices, aps, saved = await asyncio.gather(
            self._devices(), self._access_points(), self._saved())

        rows: list[p.SettingsSchemaItem] = []
        rows += await self._wifi_rows(devices, aps, saved, busy)
        rows += await self._wired_rows(devices, saved, busy)
        rows += self._bluetooth_rows(self._bt, busy)

        if notice:
            rows.insert(0, _label("network.notice..text", "Wi-Fi", notice))
        return rows

    def _current_notice(self) -> str:
        if self._doing:
            return f"{self._doing[0].upper()}{self._doing[1:]}…"
        if self._notice and time.monotonic() < self._notice_until:
            return self._notice
        self._notice = ""
        return ""

    async def _wifi_rows(self, devices: list[Device], aps: list[AccessPoint],
                         saved: list[Saved], busy: bool) -> list[p.SettingsSchemaItem]:
        group = "Wi-Fi"
        device = next((d for d in devices if d.type == "wifi"), None)
        radio = (await self._nmcli("-t", "radio", "wifi") or "").strip() == "enabled"

        rows = [p.SettingsSchemaItem(
            key="network.wifi..enabled", type="bool", page=PAGE, group=group,
            label="Wi-Fi", value=radio,
            # Live even while an action is running, unlike everything else on
            # the page. It is the way out of a connect that has hung: with the
            # radio greyed too there would be nothing left to press.
            enabled=device is not None,
            detail=device.name if device else "no wireless adapter",
        )]

        if device is None:
            return rows
        if not radio:
            rows.append(_label("network.wifi..status", group, "The radio is off"))
            return rows

        if device.connected:
            address, gateway = await self._addresses(device.name)
            where = device.connection or "a network"
            detail = address.split("/")[0] if address else "no address"
            rows.append(_label("network.wifi..status", group,
                               f"Connected to {where} · {detail}",
                               detail=f"gateway {gateway}" if gateway else ""))
            rows.append(p.SettingsSchemaItem(
                key="network.wifi..disconnect", type="action", page=PAGE, group=group,
                label="Disconnect", enabled=not busy,
            ))
        else:
            rows.append(_label("network.wifi..status", group, _state_text(device)))

        rows.append(p.SettingsSchemaItem(
            key="network.wifi..scan", type="action", page=PAGE, group=group,
            label="Scan for networks", enabled=not busy,
        ))

        known = {s.name for s in saved if s.type == "802-11-wireless"}
        for ap in aps:
            here = ap.ssid in known
            marks = [_strength(ap.signal)[1], "open" if not ap.secured else ap.security]
            if here:
                marks.append("saved")
            rows.append(p.SettingsSchemaItem(
                key=f"network.ap.{ap.ssid}.connect", type="action", page=PAGE,
                group="Networks in range",
                label=f"{ap.ssid} · {' · '.join(marks)}",
                # No percentage here either, tempting as a tooltip is: the
                # rows are compared field by field to decide whether the page
                # is worth pushing, so a number that moves would rebuild every
                # widget on the page each time NetworkManager rescanned.
                detail=f"{ap.ssid} — {'secured with ' + ap.security if ap.secured else 'open'}",
                # The one you are on is not a thing to click. Disconnect is a
                # row of its own above, where it can be found without hunting
                # for the network you happen to be joined to.
                enabled=not ap.in_use and not busy,
            ))

        for profile in sorted(saved, key=lambda s: s.name.lower()):
            if profile.type != "802-11-wireless":
                continue
            rows.append(p.SettingsSchemaItem(
                key=f"network.saved.{profile.uuid}.forget", type="action", page=PAGE,
                group="Saved networks", label=f"Forget {profile.name}",
                detail="Deletes the stored password too", enabled=not busy,
            ))
        return rows

    async def _wired_rows(self, devices: list[Device], saved: list[Saved],
                          busy: bool) -> list[p.SettingsSchemaItem]:
        group = "Wired"
        wired = [d for d in devices if d.type == "ethernet"]
        if not wired:
            return [_label("network.wired..none", group, "No ethernet port")]

        rows: list[p.SettingsSchemaItem] = []
        for device in wired:
            if device.connected:
                address, gateway = await self._addresses(device.name)
                rows.append(_label(f"network.wired.{device.name}.status", group,
                                   f"Connected · {address.split('/')[0] or 'no address'}",
                                   detail=f"{device.name} · gateway {gateway}"))
                rows.append(p.SettingsSchemaItem(
                    key=f"network.wired.{device.name}.disconnect", type="action", page=PAGE,
                    group=group, label="Disconnect", enabled=not busy,
                ))
            else:
                # "unavailable" is nmcli for a port with no cable in it, which
                # is the normal state of a laptop and not an error.
                rows.append(_label(f"network.wired.{device.name}.status", group,
                                   _state_text(device), detail=device.name))
                rows.append(p.SettingsSchemaItem(
                    key=f"network.wired.{device.name}.connect", type="action", page=PAGE,
                    group=group, label="Connect",
                    enabled=device.state != "unavailable" and not busy,
                ))

        for profile in saved:
            if profile.type != "802-3-ethernet":
                continue
            rows.append(p.SettingsSchemaItem(
                key=f"network.saved.{profile.uuid}.autoconnect", type="bool", page=PAGE,
                group=group, label="Connect automatically", detail=profile.name,
                value=profile.autoconnect, enabled=not busy,
            ))
        return rows

    def _bluetooth_rows(self, state: Bluetooth, busy: bool) -> list[p.SettingsSchemaItem]:
        group = "Bluetooth"
        if not state.running:
            return [_label("network.bt..status", group,
                           "The Bluetooth service is not running",
                           detail="systemctl enable --now bluetooth")]

        rows = [p.SettingsSchemaItem(
            key="network.bt..powered", type="bool", page=PAGE, group=group,
            label="Bluetooth", value=state.powered,
            detail=state.controller, enabled=not busy,
        )]
        if not state.powered:
            return rows

        rows.append(p.SettingsSchemaItem(
            key="network.bt..scan", type="action", page=PAGE, group=group,
            label="Scan for devices", detail=f"{SCAN_SECONDS} seconds",
            enabled=not busy,
        ))
        if not state.devices:
            rows.append(_label("network.bt..none", group, "Nothing found yet"))
        for device in state.devices:
            marks = []
            if device.connected:
                marks.append("connected")
            elif device.paired:
                marks.append("paired")
            action = "disconnect" if device.connected else "connect"
            rows.append(p.SettingsSchemaItem(
                key=f"network.bt.{device.mac}.{action}", type="action", page=PAGE,
                group=group,
                label=f"{'Disconnect' if device.connected else 'Connect'} {device.name}"
                      + (f" · {' · '.join(marks)}" if marks else ""),
                detail=device.mac, enabled=not busy,
            ))
        return rows

    # -- writing -----------------------------------------------------------

    async def set(self, key: str, value) -> str | None:
        parts = key.split(".")
        if len(parts) < 4 or parts[0] != PAGE:
            return f"not a network setting: {key!r}"
        domain, field_name = parts[1], parts[-1]
        ident = ".".join(parts[2:-1])

        if not self.available:
            return "NetworkManager is not answering"

        if domain == "wifi":
            return await self._set_wifi(field_name, value)
        if domain == "ap":
            return self._begin(f"connecting to {ident}", self._connect_ap(ident))
        if domain == "saved":
            return await self._set_saved(ident, field_name, value)
        if domain == "wired":
            return await self._set_wired(ident, field_name)
        if domain == "bt":
            return await self._set_bluetooth(ident, field_name, value)
        return f"unknown network setting: {key!r}"

    async def _set_wifi(self, field_name: str, value) -> str | None:
        if field_name == "enabled":
            if not isinstance(value, bool):
                return "Wi-Fi must be on or off"
            code, out, err = await self._run(
                ["nmcli", "radio", "wifi", "on" if value else "off"])
            return None if code == 0 else self._reason(out, err, "the radio refused")
        if field_name == "scan":
            return self._begin("scanning", self._scan_wifi())
        if field_name == "disconnect":
            device = next((d for d in await self._devices() if d.type == "wifi"), None)
            if device is None:
                return "no wireless adapter"
            return self._begin("disconnecting", self._disconnect(device.name))
        return f"unknown Wi-Fi setting: {field_name!r}"

    async def _set_saved(self, uuid: str, field_name: str, value) -> str | None:
        if field_name == "forget":
            return self._begin("forgetting", self._forget(uuid))
        if field_name == "autoconnect":
            if not isinstance(value, bool):
                return "autoconnect must be on or off"
            code, out, err = await self._run([
                "nmcli", "connection", "modify", uuid,
                "connection.autoconnect", "yes" if value else "no"])
            return None if code == 0 else self._reason(out, err, "NetworkManager refused")
        return f"unknown saved-network setting: {field_name!r}"

    async def _set_wired(self, device: str, field_name: str) -> str | None:
        if field_name == "connect":
            return self._begin(f"connecting {device}", self._connect_device(device))
        if field_name == "disconnect":
            return self._begin(f"disconnecting {device}", self._disconnect(device))
        return f"unknown wired setting: {field_name!r}"

    async def _set_bluetooth(self, mac: str, field_name: str, value) -> str | None:
        if field_name == "powered":
            if not isinstance(value, bool):
                return "Bluetooth must be on or off"
            code, out, err = await self._run(
                ["bluetoothctl", "power", "on" if value else "off"], BT_TIMEOUT)
            self._bt_wake.set()
            return None if code == 0 else self._reason(out, err, "the adapter refused")
        if field_name == "scan":
            return self._begin("scanning for devices", self._scan_bluetooth())
        if field_name in ("connect", "disconnect"):
            return self._begin(f"{field_name}ing {mac}", self._bluetooth_link(mac, field_name))
        return f"unknown Bluetooth setting: {field_name!r}"

    # -- the actions themselves --------------------------------------------

    async def _scan_wifi(self) -> None:
        code, out, err = await self._run(["nmcli", "device", "wifi", "rescan"], 30.0)
        if code != 0:
            # "Scanning not allowed immediately following previous scan" is
            # normal and not worth a red line on the page.
            reason = self._reason(out, err, "scan failed")
            if "immediately following" not in reason:
                self._say(reason)

    async def _disconnect(self, device: str) -> None:
        code, out, err = await self._run(
            ["nmcli", "device", "disconnect", device], ACTION_TIMEOUT)
        if code != 0:
            self._say(self._reason(out, err, "could not disconnect"))

    async def _connect_device(self, device: str) -> None:
        code, out, err = await self._run(
            ["nmcli", "device", "connect", device], ACTION_TIMEOUT)
        if code != 0:
            self._say(self._reason(out, err, "could not connect"))

    async def _forget(self, uuid: str) -> None:
        code, out, err = await self._run(["nmcli", "connection", "delete", uuid])
        if code != 0:
            self._say(self._reason(out, err, "could not forget it"))

    async def _connect_ap(self, ssid: str) -> None:
        """Join a network, asking for its password in a real window if needed."""
        saved = next((s for s in await self._saved()
                      if s.type == "802-11-wireless" and s.name == ssid), None)
        if saved is not None:
            code, out, err = await self._run(
                ["nmcli", "connection", "up", saved.uuid], ACTION_TIMEOUT)
            if code == 0:
                return
            # A stored password that no longer works is the common case here,
            # so fall through and ask rather than reporting a dead end.
            log.info("network: saved profile for %s failed: %s", ssid, err.strip())

        ap = next((a for a in await self._access_points() if a.ssid == ssid), None)
        if ap is None:
            self._say(f"{ssid} is no longer in range")
            return

        argv = ["nmcli", "device", "wifi", "connect", ssid]
        if ap.secured:
            password = await self._ask_password(ssid)
            if password is None:
                self._say("Cancelled")
                return
            argv += ["password", password]

        code, out, err = await self._run(argv, ACTION_TIMEOUT)
        if code != 0:
            self._say(self._reason(out, err, f"could not join {ssid}"))

    async def _ask_password(self, ssid: str) -> str | None:
        """The password, from a compositor window. None if cancelled.

        It reaches `nmcli` on its command line, which is visible in `/proc` for
        the lifetime of that call. That is the same exposure every desktop
        Wi-Fi helper has — NetworkManager's alternative is registering as a
        D-Bus secret agent — and it is a deliberate trade, written down here so
        it is a decision rather than an oversight. What matters more is where
        the password was typed: a real window, never the game.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                str(ASKPASS), f"Password for {ssid}:",
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            self._say(f"no password prompter: {e}")
            return None
        try:
            out, err = await asyncio.wait_for(proc.communicate(), ACTION_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        if proc.returncode != 0:
            detail = err.decode("utf-8", errors="replace").strip()
            if detail:
                log.info("network: askpass: %s", detail)
            return None
        password = out.decode("utf-8", errors="replace").rstrip("\n")
        return password or None

    async def _scan_bluetooth(self) -> None:
        code, out, err = await self._run(
            ["bluetoothctl", "--timeout", str(SCAN_SECONDS), "scan", "on"],
            SCAN_SECONDS + 10.0)
        self._bt_wake.set()
        if code != 0:
            self._say(self._reason(out, err, "could not scan"))

    async def _bluetooth_link(self, mac: str, action: str) -> None:
        """Connect or disconnect one device, pairing first if it is new.

        BlueZ refuses to connect to a device it has never paired with, and the
        page cannot tell a user to go and pair it somewhere else — that is what
        this page is for. Pairing without an agent works for anything that does
        not need a PIN typed, which is most things; a keyboard will still have
        to be paired elsewhere.
        """
        if action == "connect":
            paired = set(self._device_lines(await self._btctl("devices", "Paired")))
            if mac not in paired:
                code, out, err = await self._run(["bluetoothctl", "pair", mac], ACTION_TIMEOUT)
                if code != 0:
                    self._say(self._reason(out, err, f"could not pair {mac}"))
                    return
                await self._run(["bluetoothctl", "trust", mac])

        code, out, err = await self._run(["bluetoothctl", action, mac], ACTION_TIMEOUT)
        self._bt_wake.set()
        if code != 0:
            self._say(self._reason(out, err, f"could not {action} {mac}"))


def _label(key: str, group: str, text: str, detail: str = "") -> p.SettingsSchemaItem:
    return p.SettingsSchemaItem(
        key=key, type="label", page=PAGE, group=group,
        label=text, detail=detail, enabled=False,
    )


def _state_text(device: Device) -> str:
    """nmcli's device state, in words a person would use."""
    state = device.state
    if state == "unavailable":
        return "Cable not connected" if device.type == "ethernet" else "Unavailable"
    if state == "disconnected":
        return "Not connected"
    if state.startswith("connecting"):
        return "Connecting…"
    if state.startswith("unmanaged"):
        return "Not managed by NetworkManager"
    return state[:1].upper() + state[1:]
