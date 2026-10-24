"""Message types for the mcshell wire protocol.

Single source of truth. Keep in sync with docs/protocol.md — if you change one,
change the other in the same commit.

Transport is newline-delimited JSON over a unix socket. The daemon listens, the
mod connects as a client.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar

PROTO_VERSION = 1


class ProtocolError(Exception):
    """Raised when an inbound line is not a message we can understand."""


# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------


@dataclass
class Message:
    """Base for every wire message.

    Subclasses declare ``t`` as a ClassVar so it is not an __init__ argument,
    but it is re-inserted during serialisation.
    """

    t: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["t"] = self.t
        return d

    def encode(self) -> bytes:
        """Serialise to a single newline-terminated JSON line."""
        return (json.dumps(self.to_dict(), separators=(",", ":")) + "\n").encode()


# ---------------------------------------------------------------------------
# mod -> daemon
# ---------------------------------------------------------------------------


@dataclass
class Hello(Message):
    t: ClassVar[str] = "hello"
    proto: int = PROTO_VERSION
    mc: str = "1.21.1"


@dataclass
class CatalogQuery(Message):
    t: ClassVar[str] = "catalog_query"
    text: str = ""
    tab: str | None = None


@dataclass
class SlotAssign(Message):
    t: ClassVar[str] = "slot_assign"
    slot: int = 0
    app: str = ""


@dataclass
class SlotClear(Message):
    t: ClassVar[str] = "slot_clear"
    slot: int = 0


@dataclass
class SlotsArrange(Message):
    """The hotbar as the player has just arranged it, reported by the mod.

    An observation, not an instruction. The hotbar is real Minecraft items now,
    so the player can drag one to another slot or out of the hotbar entirely
    with ordinary inventory handling; the mod does not interpret that, it just
    notices afterwards that the nine slots no longer hold what it wrote and
    says what they hold instead.

    The daemon diffs this against the taskbar it last built and acts only on
    what actually moved. Sending the whole picture rather than a move is what
    makes it safe to lose one: the next report is absolute, not a delta on a
    state the two ends might disagree about.

    Keys are 1-based slot numbers as strings, since they arrive as JSON object
    keys. A slot the player emptied is absent.
    """

    t: ClassVar[str] = "slots_arrange"
    slots: dict[str, str] = field(default_factory=dict)


@dataclass
class SlotsOccupied(Message):
    """Which hotbar slots hold something that is not an application.

    The hotbar is a real Minecraft inventory now, so a slot can be full of
    wood. That does not stop an application being put there — the mod moves the
    wood into storage, or drops it when there is nowhere left — but it should be
    the last resort rather than the first, and only the mod can see it.

    So the daemon prefers genuinely empty slots when placing a transient, and
    disturbs a slot with something in it only when there is no empty one. Sent
    whenever the set changes, and again on reconnect, since a restarted daemon
    knows nothing about the player's wood.

    1-based slot numbers, matching every other slot number in the protocol.
    """

    t: ClassVar[str] = "slots_occupied"
    slots: list[int] = field(default_factory=list)


@dataclass
class SlotActivate(Message):
    t: ClassVar[str] = "slot_activate"
    slot: int = 0
    #: "right" focuses or launches, "left" cycles that app's windows, and
    #: "shift_right" launches another one whether or not it is already running.
    button: str = "right"  # "left" | "right" | "shift_right"


@dataclass
class SlotClose(Message):
    t: ClassVar[str] = "slot_close"
    slot: int = 0


@dataclass
class CommandSubmit(Message):
    t: ClassVar[str] = "command_submit"
    text: str = ""


@dataclass
class SettingSet(Message):
    t: ClassVar[str] = "setting_set"
    key: str = ""
    value: Any = None


@dataclass
class OverviewSet(Message):
    """Ask the mod to open or close its overview screen.

    The input side of the `overview` push. CLAUDE.md lists only the daemon->mod
    half, which leaves nothing able to produce it; this is what Sway's Super
    binding sends, so raising Minecraft and opening the overview are one
    keystroke rather than two.

    Not a toggle: the daemon cannot know whether the screen is open, since the
    player can close it with Escape without telling anyone. `show` is absolute,
    and re-opening an open overview is a no-op.
    """

    t: ClassVar[str] = "overview_set"
    show: bool = True


# ---------------------------------------------------------------------------
# daemon -> mod
# ---------------------------------------------------------------------------


@dataclass
class CatalogItem:
    id: str
    name: str
    icon_path: str | None = None
    categories: list[str] = field(default_factory=list)
    # Which creative-mode tab this app belongs in. Derived from `categories` by
    # the daemon so the mod never has to own the mapping.
    tab: str = "Utility"


@dataclass
class Catalog(Message):
    t: ClassVar[str] = "catalog"
    items: list[CatalogItem] = field(default_factory=list)


@dataclass
class TaskbarSlot:
    i: int
    app: str | None = None
    # What the application calls itself, for the item's hover name. The mod
    # falls back to the desktop id, which is what an assignment to something no
    # longer installed leaves behind.
    name: str | None = None
    icon_path: str | None = None
    running: bool = False
    windows: int = 0
    focused: bool = False
    # Launched, but no window has been mapped yet. Drawn dimmed.
    launching: bool = False
    # Running, but nobody assigned it. Occupies a free slot for as long as it
    # is open and is forgotten when it closes; nothing is written to disk.
    transient: bool = False


@dataclass
class Taskbar(Message):
    t: ClassVar[str] = "taskbar"
    slots: list[TaskbarSlot] = field(default_factory=list)


@dataclass
class CommandStart(Message):
    """A command has been accepted and is now running.

    Broadcast, not replied: a command typed into `mcsh` should echo in
    Minecraft's chat too, since both are views of the same one shell.

    `cmd` numbers the run. Output streams in as it is produced, so the mod
    needs to know which lines belong together to apply the five-line rule, and
    a bare `output` message cannot say that on its own.
    """

    t: ClassVar[str] = "command_start"
    cmd: int = 0
    text: str = ""
    cwd: str = ""


@dataclass
class Output(Message):
    """A batch of output lines from a running command.

    Sent as the lines arrive rather than once at the end, so a slow build
    scrolls instead of hanging. Lines are already stripped of ANSI escapes and
    control characters — the mod draws Minecraft text, not a terminal.
    """

    t: ClassVar[str] = "output"
    lines: list[str] = field(default_factory=list)
    stream: str = "stdout"  # "stdout" | "stderr"
    cmd: int = 0


@dataclass
class CommandEnd(Message):
    """The command finished. No further `output` will carry this `cmd`.

    The mod holds a command's lines until this arrives: five or fewer go to
    chat, more open the overview panel. Without an explicit end there is no
    moment at which "five or fewer" becomes true.
    """

    t: ClassVar[str] = "command_end"
    cmd: int = 0
    code: int = 0
    # Human-readable reason the run ended other than normally: a timeout, a
    # truncation, or a detached launch. Empty when the command simply exited.
    note: str = ""


@dataclass
class ChatClear(Message):
    """Empty Minecraft's chat, the way F3+D does. What `clear` means here.

    Sent between a run's `command_start` and its `command_end`, and drawn in
    that order, so the echo of `$ clear` goes with everything before it. Typed
    history survives, as it does for F3+D and for a terminal's clear.
    """

    t: ClassVar[str] = "chat_clear"
    cmd: int = 0


@dataclass
class Overview(Message):
    t: ClassVar[str] = "overview"
    show: bool = False


@dataclass
class Focus(Message):
    """Whether the compositor's focus is on Minecraft.

    The mod cannot answer this for itself. Minecraft is an X client under
    XWayland, and X only takes focus off it when another *X* client takes
    focus; move to a native Wayland window and the game still believes it is
    focused, so it goes on holding the pointer. An X grab is server-wide, so
    that grab also eats the button presses of every other X application.

    Sway knows, and we are already watching it, so we say. See
    MCShellClient.followWindowFocus for what the mod does with it.
    """

    t: ClassVar[str] = "focus"
    game: bool = True


@dataclass
class FocusAck(Message):
    """The mod, confirming it has done what a `focus` asked of it.

    The daemon waits for this before it moves the compositor's focus, because
    the order matters and nothing else can tell it when the game has finished.
    See Daemon.yield_pointer.
    """

    t: ClassVar[str] = "focus_ack"
    game: bool = True


@dataclass
class WorldReady(Message):
    """The world is on screen. Sent once, when the game stops loading.

    The boot screen covers sway's flat colour, Prism's launcher and Minecraft's
    own splash, so something has to say when there is finally a desktop behind
    it. Nothing else can: `hello` arrives while the client is still loading a
    world, and the compositor only ever sees a window that has been mapped for
    twenty seconds by then.

    Sent once per client run, not per world load — leaving to the title screen
    and coming back does not put the boot screen up again, because the boot is
    over.
    """

    t: ClassVar[str] = "world_ready"


@dataclass
class OsdVolume(Message):
    """A volume key was pressed. Draw the bar, whatever it now says.

    Not "set the volume" — the key has already done that, straight through
    `wpctl`, before this was sent. This says only that somebody asked.

    It exists because the popup is otherwise driven entirely by
    `pactl subscribe`, which is what lets the command bar, the Sound page's own
    slider and a headset wheel all draw the same bar. Measured: PipeWire emits
    no event at all for a write that lands on the value already there, so
    `5%-` at zero draws nothing and the key reads as broken rather than as
    already-at-zero. At the extremes the only thing that knows a key was
    pressed is the thing that pressed it.

    Sent by `session/volume.sh`, which is what the media keys are bound to.
    """

    t: ClassVar[str] = "osd_volume"


@dataclass
class LaunchMode(Message):
    """How the launcher is starting the game. Only ever sent as offline.

    From `session/prism/launch.sh`, which decides before Prism starts whether
    there is a network to sign in over. With none it launches offline, and
    says so here so the boot screen can tell somebody why — the screen would
    otherwise look the same as a login that has stalled. Best effort: the game
    starts whether or not the daemon hears this.
    """

    t: ClassVar[str] = "launch_mode"
    offline: bool = False


@dataclass
class SaveWorld(Message):
    """Save the world now, and flush it to disk.

    Daemon to mod, before the machine powers off or restarts. The mod runs what
    vanilla's `/save-all flush` runs — `MinecraftServer.saveAll(false, true,
    true)`, player data then every chunk, read out of `SaveAllCommand` with
    `javap` — on the server thread, and answers `world_saved`.

    Also accepted *from* a client, so `mcsh '{"t":"save_world"}'` asks the daemon
    to do the same thing on demand. The mod never sends it, so the direction is
    never ambiguous.
    """

    t: ClassVar[str] = "save_world"
    id: int = 0


@dataclass
class WorldSaved(Message):
    """The answer to `save_world`: whether it worked, and how long it took."""

    t: ClassVar[str] = "world_saved"
    id: int = 0
    ok: bool = False
    ms: int = 0


@dataclass
class WorldsQuery(Message):
    """Pull the world list. The mod asks when the Worlds screen opens."""

    t: ClassVar[str] = "worlds_query"


@dataclass
class WorldInfo:
    """One world on the Worlds screen: a folder under the instance's saves/."""

    name: str = ""
    #: Absolute path to the world's icon.png, or "" when it has none. Minecraft
    #: writes one the first time a world is played, so a fresh template has none.
    icon: str = ""
    #: The icon's mtime in whole seconds. The mod caches textures by path, and
    #: the game overwrites icon.png in place, so the version is what tells a
    #: stale preview from a new one.
    icon_version: int = 0


@dataclass
class Worlds(Message):
    """Every world, which one the next start opens, and which one is running.

    `chosen` and `running` differ after a choice until the game restarts; the
    screen draws both rather than pretending the switch has happened.
    """

    t: ClassVar[str] = "worlds"
    worlds: list[WorldInfo] = field(default_factory=list)
    chosen: str = ""
    running: str = ""


@dataclass
class WorldChoose(Message):
    """Make `name` the world the next start opens. Answered with `worlds`."""

    t: ClassVar[str] = "world_choose"
    name: str = ""


@dataclass
class WorldRestart(Message):
    """Save this world and restart the game into the chosen one.

    Answered `ok` at once and done in the background: the save can take up to
    four seconds, and this socket is the one the pointer handshake uses.
    """

    t: ClassVar[str] = "world_restart"


@dataclass
class StatsRow:
    """One line on the Statistics screen's static tabs.

    Deliberately just text: a label, a value, and an optional second line.
    The General and Disks tabs are readouts, not controls, so there is nothing
    for a row type to vary. `fraction` is the exception — a disk is a thing
    with a proportion, and a bar says that faster than "412 GB of 931 GB".
    """

    label: str
    value: str = ""
    group: str = ""
    detail: str = ""
    #: 0..1, drawn as a usage bar. None means no bar.
    fraction: float | None = None


@dataclass
class StatsQuery(Message):
    """Pull one tab of the Statistics screen."""

    t: ClassVar[str] = "stats_query"
    tab: str = "general"  # "general" | "disks"


@dataclass
class Stats(Message):
    t: ClassVar[str] = "stats"
    tab: str = "general"
    rows: list[StatsRow] = field(default_factory=list)


@dataclass
class ProcessRow:
    """One process, as the task-manager tab draws it.

    `cpu` is a share of the whole machine, not of one core, so the column sums
    to the gauge above it. htop's other convention — 100% meaning one core
    saturated — is more informative to someone who already knows how many
    cores they have, and confusing to everyone else.
    """

    pid: int = 0
    name: str = ""
    cmd: str = ""
    user: str = ""
    cpu: float = 0.0
    mem: float = 0.0
    rss: int = 0
    #: True for the processes this shell is standing on. The mod greys the
    #: kill button; the daemon refuses anyway, because a client is not to be
    #: trusted with that.
    protected: bool = False


@dataclass
class StatsWatch(Message):
    """Start or stop the live process stream.

    Sorting is the daemon's job, which is what keeps this cheap: a machine has
    hundreds of processes and a screen has room for tens, so the mod says what
    order it wants and gets only that many. Sorting in the mod would mean
    sending all of them every second to display a fraction.
    """

    t: ClassVar[str] = "stats_watch"
    on: bool = False
    sort: str = "cpu"  # "cpu" | "mem" | "pid" | "name"
    desc: bool = True
    limit: int = 64


@dataclass
class Processes(Message):
    t: ClassVar[str] = "processes"
    #: Percent of the whole machine, 0..100.
    cpu: float = 0.0
    #: Per-core percentages, in core order.
    cores: list[float] = field(default_factory=list)
    mem_used: int = 0
    mem_total: int = 0
    swap_used: int = 0
    swap_total: int = 0
    load: list[float] = field(default_factory=list)
    count: int = 0
    procs: list[ProcessRow] = field(default_factory=list)


@dataclass
class ProcessKill(Message):
    """Ask for a process to be sent SIGTERM. A request, not a kill."""

    t: ClassVar[str] = "process_kill"
    pid: int = 0


@dataclass
class DirEntry:
    name: str
    path: str
    #: `dir`, or what kind of file it is — the mod has an icon per kind and
    #: falls back to `file`. Decided here because an extension table is data,
    #: and the mod is not where decisions live.
    kind: str = "dir"


@dataclass
class PowerAction(Message):
    """Lock, sleep, restart or power off the machine.

    Sent by the screen the pause menu's *Save and Quit to Title* button opens.
    The daemon answers `ok` as soon as it has accepted the request, not when
    it has finished — a lock screen takes a moment to come up and the socket
    this arrives on is the one the pointer handshake uses. A failure comes
    back afterwards as an `error`.
    """

    t: ClassVar[str] = "power_action"
    #: `lock`, `sleep`, `restart` or `poweroff`. Anything else is refused.
    action: str = ""


@dataclass
class DirQuery(Message):
    """List one directory. An empty path means the home directory."""

    t: ClassVar[str] = "dir_query"
    path: str = ""
    offset: int = 0
    limit: int = 20


@dataclass
class Dir(Message):
    """One directory's subdirectories, a page at a time.

    Directories first, then files, each alphabetically. Files are leaves —
    they are there so that a directory with things in it does not draw as an
    empty one — and carry the kind the mod draws an icon for.

    `total` counts every visible entry, not just the page, so the mod can say
    how many more there are. `hidden` counts the dotted ones left out —
    reported rather than silently dropped, because a home directory has dozens
    and a tree that pretends otherwise is lying about the machine.
    """

    t: ClassVar[str] = "dir"
    path: str = ""
    name: str = ""
    entries: list[DirEntry] = field(default_factory=list)
    total: int = 0
    hidden: int = 0
    offset: int = 0
    #: Why there is nothing here — unreadable, gone, or not a directory.
    error: str = ""


@dataclass
class Battery(Message):
    """The machine's charge, for the XP bar.

    The XP bar is the battery gauge — level text and all — because the shell
    has nowhere else to put one and a laptop you have to guess about is a bad
    laptop. Minecraft's own experience still accrues; it is simply not drawn.

    `charging` and `mains` are both here because they are genuinely different
    things. A battery at a charge limit reads "Not charging" while plugged in,
    and calling that discharging would be wrong every time the machine was on
    mains.

    `present` false means there is no battery — a desktop — and the mod draws
    Minecraft's own XP bar instead of inventing a gauge for a thing that does
    not exist.
    """

    t: ClassVar[str] = "battery"
    present: bool = False
    percent: int = 0
    charging: bool = False
    mains: bool = False


@dataclass
class Hud(Message):
    """Everything the HUD draws that has no message of its own.

    Two things live here so far and they have nothing to do with each other:
    the wall clock, and whether the battery gauge is allowed to change colour.
    What they share is that they are *preferences about drawing* — the mod owns
    neither the value nor the decision, it owns the pixels — and a second
    message per checkbox would be a message per checkbox forever.

    Pushed on connect, on the minute, and whenever a row on the General page
    moves. Never polled: the HUD draws every frame and must never wait.

    `time` and `date` are already formatted, in the machine's own locale. The
    JVM has its own idea of a default locale and the two disagree often enough
    to matter, so the string crosses the socket rather than the instructions
    for building it. See `clock.py`.
    """

    t: ClassVar[str] = "hud"
    #: Draw the clock at all.
    clock: bool = True
    #: "1:27 PM" or "13:27", per the locale and the format setting.
    time: str = ""
    #: "Friday, May 1st".
    date: str = ""
    #: False pins the battery gauge to green. The colours mean something —
    #: white on mains, red below 15% — and somebody who does not want the HUD
    #: changing under them can say so.
    battery_color: bool = True


@dataclass
class SettingsOption:
    """One choice in an `enum` setting.

    `id` is opaque to the mod: it is whatever `setting_set` should send back —
    a PipeWire sink name, a card profile, a Sway output mode. Only `label` is
    ever drawn. Keeping the two apart is what lets a setting be renamed, or
    localised, without the daemon having to recognise the old text.
    """

    id: str
    label: str


@dataclass
class SettingsSchemaItem:
    """One row on a settings page: what to draw, and what it currently is.

    Shape and value travel together on purpose. They change for the same
    reasons — plug in headphones and there is both a new sink to choose and a
    new default selected — so splitting them would mean two messages that are
    only ever correct when they agree.
    """

    key: str
    type: str  # "float" | "int" | "bool" | "enum" | "keybind" | "action"
    #            | "text" | "label"
    label: str
    #: Which vanilla options screen this belongs beside.
    page: str = ""  # "audio" | "video" | "controls" | "network" | "general"
    #: Subheading within the page: "Output", "Input", "Applications".
    group: str = ""
    value: Any = None
    #: What "Reset" puts back, when the row has a meaningful default. Drawn as
    #: a disabled Reset button when it equals `value`, the way Minecraft's own
    #: keybind screen does. None means the row has no default and no button.
    default: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    #: "%" draws the value as a percentage. The wire value stays 0..1, which is
    #: what Minecraft's own sliders hold, so the mod scales only for the label.
    unit: str = ""
    #: `enum` only.
    options: list[SettingsOption] = field(default_factory=list)
    #: Secondary line — a device's real name under its friendly one.
    detail: str = ""
    #: `text` only: what the empty field says it wants.
    placeholder: str = ""
    #: An optional button at the right-hand end of the row. `extra_key` is set
    #: to true when it is pressed, exactly like an `action` row, so the mod
    #: needs to know nothing about what it does. It takes the same column
    #: Reset uses, and a row that wants both would have to grow one — nothing
    #: does: Reset means "back to the configured key" and only rows with a
    #: configured key have one.
    extra_label: str = ""
    extra_key: str = ""
    #: False draws the row greyed and refuses input: a setting that exists but
    #: cannot be changed right now reads better than one that vanishes.
    enabled: bool = True


@dataclass
class SettingsQuery(Message):
    """Pull a settings page. The mod asks when a page opens; pushes follow."""

    t: ClassVar[str] = "settings_query"
    page: str | None = None  # None = every page


@dataclass
class SettingsSchema(Message):
    t: ClassVar[str] = "settings_schema"
    items: list[SettingsSchemaItem] = field(default_factory=list)
    #: Which page this covers, so a push about audio does not look like an
    #: empty video page. Empty string means every page.
    page: str = ""


# ---------------------------------------------------------------------------
# M0 scaffolding
# ---------------------------------------------------------------------------
# These are not in the CLAUDE.md protocol table. They exist so the daemon can
# be driven and inspected from `mcsh` before any of the real surfaces are
# built. Expect `windows` to be replaced by `taskbar` once M1 lands.


@dataclass
class WindowInfo:
    """One live Sway window, as tracked by compositor.py."""

    con_id: int
    app_id: str
    title: str
    workspace: str | None = None
    focused: bool = False
    pid: int | None = None


@dataclass
class WindowsQuery(Message):
    t: ClassVar[str] = "windows_query"


@dataclass
class Windows(Message):
    t: ClassVar[str] = "windows"
    windows: list[WindowInfo] = field(default_factory=list)


@dataclass
class TaskbarQuery(Message):
    """Pull the current taskbar. The mod gets it pushed; mcsh needs to ask."""

    t: ClassVar[str] = "taskbar_query"


@dataclass
class Ping(Message):
    t: ClassVar[str] = "ping"


@dataclass
class Pong(Message):
    t: ClassVar[str] = "pong"


@dataclass
class Error(Message):
    t: ClassVar[str] = "error"
    message: str = ""


@dataclass
class Ok(Message):
    t: ClassVar[str] = "ok"


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------

INBOUND: dict[str, type[Message]] = {
    cls.t: cls
    for cls in (
        Hello,
        CatalogQuery,
        SlotAssign,
        SlotClear,
        SlotsArrange,
        SlotsOccupied,
        SlotActivate,
        SlotClose,
        CommandSubmit,
        SettingSet,
        SettingsQuery,
        StatsQuery,
        StatsWatch,
        DirQuery,
        PowerAction,
        ProcessKill,
        OverviewSet,
        FocusAck,
        WorldReady,
        OsdVolume,
        LaunchMode,
        SaveWorld,
        WorldSaved,
        WorldsQuery,
        WorldChoose,
        WorldRestart,
        WindowsQuery,
        TaskbarQuery,
        Ping,
    )
}


def decode(line: str | bytes) -> Message:
    """Parse one wire line into a Message.

    Unknown keys are dropped rather than raising: the mod may be newer than the
    daemon, and a spurious field should not kill the connection.
    """
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"malformed JSON: {e}") from e

    if not isinstance(raw, dict):
        raise ProtocolError(f"expected a JSON object, got {type(raw).__name__}")

    t = raw.get("t")
    if not isinstance(t, str):
        raise ProtocolError("message is missing a string 't' field")

    cls = INBOUND.get(t)
    if cls is None:
        raise ProtocolError(f"unknown message type {t!r}")

    known = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in raw.items() if k in known}
    try:
        return cls(**kwargs)
    except TypeError as e:
        raise ProtocolError(f"bad fields for {t!r}: {e}") from e
