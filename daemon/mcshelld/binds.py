"""The Controls page: rebinding Sway's keybindings.

Sway is asked for its own config rather than the config file being hunted down
and its `include` chain followed. Whatever Sway actually loaded is the truth,
and it is one IPC call away.

A change is applied twice: at runtime, so it works immediately, and into a
generated `~/.config/sway/config.d/mcshell-binds.conf`, so it survives a reload.
The mapping itself lives in the daemon's own config dir — the generated file is
an output, and treating it as storage would mean parsing our own output back.

Sway's binds can only be rebound — nothing is added to them or deleted, which
is exactly what Minecraft's own Controls screen does, and it is the screen this
one stands beside. **Binds of your own are a second thing**, kept by the daemon
rather than found in the config: the maker at the top of the page takes a shell
command and a key and holds the pair here.

That separation is what makes the page honest. A bind read out of the config is
somebody's config and the only safe thing to do to it is move it; a bind made
here is ours, so it can also be removed. Mixing them would mean offering to
delete lines out of a file we do not own.

They cannot collide, either, and that is measured rather than assumed: Sway's
`get_config` returns **only the top-level file**, not the `include` chain, so
the `config.d` snippet this module generates is never read back in as though
somebody had written it by hand.

Keys are `controls.<id>.key`, where the id is derived from the command a bind
runs: change a bind's key and it is still the bind that starts a terminal.
The `controls.` is not decoration — settings.py routes a `setting_set` by the
key's first segment and registers a provider under its page name, so a key
prefixed with anything else reaches nobody at all. These were `binds.` until
that was measured.
Ours are `controls.custom.<id>.key` and `controls.custom.<id>.remove`, and
the maker is `controls.new..command`, `controls.new..key` and
`controls.new..add`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import shutil
from pathlib import Path

from . import protocol as p

log = logging.getLogger(__name__)

PAGE = "controls"

#: The longest command the maker will take. The mod's field caps at the same
#: number, so a command that fits on screen is a command that can be saved.
COMMAND_MAX = 256

NEW_GROUP = "New binding"
CUSTOM_GROUP = "My bindings"

# Sway's modifier names, in the order we write them, with what to call them on
# screen. Mod1 and Mod4 are what the config says; Alt and Super are what the
# keyboard says.
MODIFIERS = (
    ("Mod4", "Super"),
    ("Ctrl", "Ctrl"),
    ("Mod1", "Alt"),
    ("Shift", "Shift"),
)
_ALIASES = {
    "mod4": "Mod4", "super": "Mod4", "logo": "Mod4",
    "ctrl": "Ctrl", "control": "Ctrl",
    "mod1": "Mod1", "alt": "Mod1",
    "shift": "Shift",
    "mod2": "Mod2", "mod3": "Mod3", "mod5": "Mod5",
}

_SET = re.compile(r"^\s*set\s+(\$\w+)\s+(.*?)\s*$")
_BINDSYM = re.compile(r"^\s*bindsym\s+(.*)$")
_MODE = re.compile(r"^\s*mode\s+.*\{\s*$")

# GLFW keycode -> X keysym. Letters and digits are computed; this is the rest.
_NAMED = {
    32: "space", 39: "apostrophe", 44: "comma", 45: "minus", 46: "period",
    47: "slash", 59: "semicolon", 61: "equal", 91: "bracketleft",
    92: "backslash", 93: "bracketright", 96: "grave",
    256: "Escape", 257: "Return", 258: "Tab", 259: "BackSpace", 260: "Insert",
    261: "Delete", 262: "Right", 263: "Left", 264: "Down", 265: "Up",
    266: "Prior", 267: "Next", 268: "Home", 269: "End",
    280: "Caps_Lock", 281: "Scroll_Lock", 282: "Num_Lock", 283: "Print",
    284: "Pause",
    320: "KP_Insert", 321: "KP_End", 322: "KP_Down", 323: "KP_Next",
    324: "KP_Left", 325: "KP_Begin", 326: "KP_Right", 327: "KP_Home",
    328: "KP_Up", 329: "KP_Prior", 330: "KP_Delete", 331: "KP_Divide",
    332: "KP_Multiply", 333: "KP_Subtract", 334: "KP_Add", 335: "KP_Enter",
    336: "KP_Equal",
    348: "Menu",
}
# The modifier keys themselves, which can be bound alone.
_MODIFIER_KEYS = {
    340: ("Shift_L", "Shift"), 341: ("Control_L", "Ctrl"),
    342: ("Alt_L", "Mod1"), 343: ("Super_L", "Mod4"),
    344: ("Shift_R", "Shift"), 345: ("Control_R", "Ctrl"),
    346: ("Alt_R", "Mod1"), 347: ("Super_R", "Mod4"),
}
_GLFW_MODS = ((0x8, "Mod4"), (0x2, "Ctrl"), (0x4, "Mod1"), (0x1, "Shift"))


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "mcshell"


def sway_include() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "sway" / "config.d" / "mcshell-binds.conf"


def keys_from_event(glfw_key: int, mods: int) -> str | None:
    """Turn one Minecraft key press into the keys Sway would call it.

    The mod sends the raw GLFW code and modifier bits and nothing else — it
    does not know what a keysym is, and this is the sort of thing that would
    quietly become a second source of truth if it lived on that side.
    """
    if glfw_key in _MODIFIER_KEYS:
        name, own = _MODIFIER_KEYS[glfw_key]
        # Do not write "Mod4+Super_L": holding the key is not also a modifier.
        parts = [mod for bit, mod in _GLFW_MODS if mods & bit and mod != own]
        return "+".join(parts + [name])

    if 65 <= glfw_key <= 90:
        name = chr(glfw_key).lower()
    elif 48 <= glfw_key <= 57:
        name = chr(glfw_key)
    elif 290 <= glfw_key <= 314:
        name = f"F{glfw_key - 289}"
    else:
        name = _NAMED.get(glfw_key)
    if not name:
        return None
    return "+".join([mod for bit, mod in _GLFW_MODS if mods & bit] + [name])


def pretty(keys: str) -> str:
    """How a key combination should read on screen: Ctrl+Alt+d, not Ctrl+Mod1+d."""
    out = []
    for part in keys.split("+"):
        canonical = _ALIASES.get(part.lower(), part)
        label = next((nice for name, nice in MODIFIERS if name == canonical), None)
        out.append(label or part)
    return "+".join(out)


def normalise(keys: str) -> str:
    """Modifier aliases resolved, so two spellings of one combination match."""
    return "+".join(_ALIASES.get(part.lower(), part) for part in keys.split("+"))


class Bind:
    """One `bindsym` line from the config."""

    def __init__(self, keys: str, command: str, flags: str, index: int):
        self.keys = keys
        self.command = command
        self.flags = flags
        digest = hashlib.sha1(f"{index}:{command}".encode()).hexdigest()
        self.id = digest[:8]


def parse_config(text: str) -> list[Bind]:
    """Pull the bindsym lines out of a Sway config.

    Binds inside a `mode` block are skipped: they only apply while that mode is
    active, and a page that mixed them with the everyday ones would be lying
    about what pressing the key does.
    """
    variables: dict[str, str] = {}
    binds: list[Bind] = []
    depth = 0

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if _MODE.match(line):
            depth += 1
            continue
        if depth:
            depth -= line.count("}")
            continue

        setter = _SET.match(line)
        if setter:
            name, value = setter.groups()
            variables[name] = _expand(value, variables)
            continue

        match = _BINDSYM.match(line)
        if not match:
            continue
        rest = _expand(match.group(1), variables).strip()

        flags = []
        while rest.startswith("--"):
            flag, _, rest = rest.partition(" ")
            flags.append(flag)
            rest = rest.strip()
        keys, _, command = rest.partition(" ")
        command = command.strip()
        if not keys or not command:
            continue
        binds.append(Bind(normalise(keys), command, " ".join(flags), len(binds)))
    return binds


def _expand(text: str, variables: dict[str, str]) -> str:
    """Substitute $variables, longest name first so $mod2 beats $mod."""
    for name in sorted(variables, key=len, reverse=True):
        text = text.replace(name, variables[name])
    return text


class Binds:
    """Settings provider for the Controls page."""

    page = PAGE

    def __init__(self, compositor, on_change=None):
        self._compositor = compositor
        self._on_change = on_change
        self._path = config_dir() / "binds.json"
        self._custom_path = config_dir() / "custom-binds.json"
        # command id -> {"original": keys as configured, "keys": keys now}
        self._overrides: dict[str, dict[str, str]] = {}
        # Ours, in the order they were made: {"id", "keys", "command"}.
        self._custom: list[dict[str, str]] = []
        # The half-made bind at the top of the page. Memory only, and
        # deliberately: a command typed but never bound is not a setting, and a
        # daemon restart that resurrected somebody's abandoned draft would be a
        # worse surprise than losing it.
        self._draft_command = ""
        self._draft_keys: str | None = None

    async def start(self) -> bool:
        self._load()
        self._load_custom()
        await self._apply_all()
        return True

    async def stop(self) -> None:
        return None

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text())
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as e:
            log.warning("binds: could not read %s: %s", self._path, e)
            return
        if isinstance(raw, dict):
            self._overrides = {
                k: v for k, v in raw.items()
                if isinstance(v, dict) and "original" in v and "keys" in v
            }
            log.info("binds: loaded %d override(s)", len(self._overrides))

    def _load_custom(self) -> None:
        try:
            raw = json.loads(self._custom_path.read_text())
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as e:
            log.warning("binds: could not read %s: %s", self._custom_path, e)
            return
        if not isinstance(raw, list):
            return
        self._custom = [
            entry for entry in raw
            if isinstance(entry, dict)
            and all(isinstance(entry.get(f), str) and entry.get(f)
                    for f in ("id", "keys", "command"))
        ]
        log.info("binds: loaded %d of my own", len(self._custom))

    def _save_custom(self) -> None:
        self._custom_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._custom_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._custom, indent=2))
        tmp.replace(self._custom_path)
        self._write_include()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._overrides, indent=2, sort_keys=True))
        tmp.replace(self._path)
        self._write_include()

    def _write_include(self) -> None:
        """Regenerate the Sway snippet, so the overrides survive a reload.

        Sway only reads this if the config includes `config.d`. Runtime binds
        are applied regardless, so a missing include costs persistence, not
        function — and it says so at the top of the file it writes.
        """
        path = sway_include()
        lines = [
            "# Generated by mcshelld. Do not edit — rewritten on every change.",
            "#",
            "# Needs `include $HOME/.config/sway/config.d/*.conf` at the end of",
            "# your sway config. Without it these binds still work until Sway",
            "# is reloaded, and are lost after.",
            "",
        ]
        for entry in sorted(self._overrides.values(), key=lambda e: e["command"]):
            lines.append(f"unbindsym {entry['original']}")
            lines.append(f"bindsym {entry['keys']} {entry['command']}")
        if self._custom:
            lines.append("")
            lines.append("# Made on the Controls page.")
            for entry in self._custom:
                lines.append(f"bindsym {entry['keys']} exec {entry['command']}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n")
        except OSError as e:
            log.warning("binds: could not write %s: %s", path, e)

    async def _apply_all(self) -> None:
        """Re-assert everything at startup, in case Sway was restarted."""
        for entry in self._overrides.values():
            await self._apply(entry["original"], entry["keys"], entry["command"])
        for entry in self._custom:
            await self._compositor.bind(entry["keys"], f"exec {entry['command']}")

    async def _apply(self, original: str, keys: str, command: str) -> bool:
        if original != keys:
            await self._compositor.unbind(original)
        return await self._compositor.bind(keys, command)

    # -- reading -----------------------------------------------------------

    async def _binds(self) -> list[Bind]:
        text = await self._compositor.config()
        return parse_config(text) if text else []

    async def items(self) -> list[p.SettingsSchemaItem]:
        if not self._compositor.connected:
            return [p.SettingsSchemaItem(
                key="controls.none..text", type="label", page=PAGE,
                label="Sway is not answering", enabled=False,
            )]

        items = self._maker_rows() + self._custom_rows()

        binds = await self._binds()
        if not binds:
            items.append(p.SettingsSchemaItem(
                key="controls.none..text", type="label", page=PAGE,
                label="Sway reported no keybindings", enabled=False,
            ))
            return items

        for bind in binds:
            override = self._overrides.get(bind.id)
            # What is live, not what the file says: a runtime rebind does not
            # rewrite the config Sway hands back.
            keys = override["keys"] if override else bind.keys
            items.append(p.SettingsSchemaItem(
                key=f"controls.{bind.id}.key", type="keybind", page=PAGE,
                group=_group_of(bind.command), label=_label_of(bind.command),
                detail=bind.command, value=pretty(keys),
                # Reset means "as the config has it", which is the one default
                # that exists here. Equal to `value` until the bind is changed.
                default=pretty(bind.keys),
            ))
        return _grouped(items)

    def _maker_rows(self) -> list[p.SettingsSchemaItem]:
        """The three rows at the top that make a bind out of nothing.

        A command, a key, and the button that puts them together. Three rows
        rather than one because they are three different gestures — typing,
        pressing a key, and committing — and there is no vanilla widget that is
        all three.

        The button greys until both halves are there, which is the whole of the
        validation the player sees before pressing it. Everything else it could
        refuse — the key already being taken, the command being unrunnable —
        can only be known once, at the moment it is asked for.
        """
        ready = bool(self._draft_command and self._draft_keys)
        return [
            p.SettingsSchemaItem(
                key="controls.new..command", type="text", page=PAGE,
                group=NEW_GROUP, label="Command",
                value=self._draft_command, placeholder="flameshot gui",
                detail=_missing(self._draft_command)
                or "Run by sh, the way Sway runs any exec: pipes and && work",
            ),
            p.SettingsSchemaItem(
                key="controls.new..key", type="keybind", page=PAGE,
                group=NEW_GROUP, label="Key",
                value=pretty(self._draft_keys) if self._draft_keys else "",
                detail="The combination that will run it",
            ),
            p.SettingsSchemaItem(
                key="controls.new..add", type="action", page=PAGE,
                group=NEW_GROUP, label="Add binding", enabled=ready,
                detail="" if ready else "Needs a command and a key",
            ),
        ]

    def _custom_rows(self) -> list[p.SettingsSchemaItem]:
        """Ours, each rebindable like any other and removable unlike any other.

        Remove takes the column Reset uses on the binds above. It is free there:
        Reset means "back to what the config says", and a bind that was never in
        the config has nothing to go back to.
        """
        rows = []
        for entry in self._custom:
            rows.append(p.SettingsSchemaItem(
                key=f"controls.custom.{entry['id']}.key", type="keybind", page=PAGE,
                group=CUSTOM_GROUP, label=_trim(entry["command"]),
                detail=_missing(entry["command"]) or entry["command"],
                value=pretty(entry["keys"]),
                extra_label="Remove",
                extra_key=f"controls.custom.{entry['id']}.remove",
            ))
        return rows

    # -- writing -----------------------------------------------------------

    async def set(self, key: str, value) -> str | None:
        if key.startswith("controls.new."):
            return await self._set_draft(key, value)
        if key.startswith("controls.custom."):
            return await self._set_custom(key, value)

        parts = key.split(".")
        if len(parts) < 3 or parts[0] != "controls" or parts[-1] != "key":
            return f"not a keybinding: {key!r}"
        ident = ".".join(parts[1:-1])

        keys = self._keys_from(value)
        if keys is None:
            return "that key cannot be bound"

        bind = next((b for b in await self._binds() if b.id == ident), None)
        if bind is None:
            return "that keybinding is no longer in the config"

        taken = await self._taken(keys, skip_bind=ident)
        if taken is not None:
            return taken

        original = self._overrides.get(ident, {}).get("original", bind.keys)
        if not await self._apply(original, keys, bind.command):
            return "sway refused the binding"

        if keys == original:
            self._overrides.pop(ident, None)
        else:
            self._overrides[ident] = {
                "original": original, "keys": keys, "command": bind.command,
            }
        self._save()
        log.info("bind %s -> %s (%s)", original, keys, bind.command)
        return None

    async def _set_draft(self, key: str, value) -> str | None:
        """The maker's three rows. Two of them only remember; the third acts."""
        field = key.rsplit(".", 1)[-1]

        if field == "command":
            command, error = _clean_command(value)
            if error:
                return error
            self._draft_command = command
            return None

        if field == "key":
            keys = self._keys_from(value)
            if keys is None:
                return "that key cannot be bound"
            self._draft_keys = keys
            return None

        if field != "add":
            return f"not a keybinding: {key!r}"

        command, keys = self._draft_command, self._draft_keys
        if not command or not keys:
            return "a binding needs a command and a key"

        taken = await self._taken(keys)
        if taken is not None:
            return taken

        ident = self._new_id(command)
        if ident is None:
            return "could not name that binding"
        if not await self._compositor.bind(keys, f"exec {command}"):
            return "sway refused the binding"

        self._custom.append({"id": ident, "keys": keys, "command": command})
        self._save_custom()
        # Cleared, so the maker is empty and ready for the next one rather than
        # still showing the bind that is now listed under it.
        self._draft_command = ""
        self._draft_keys = None
        log.info("bind %s -> exec %s (mine)", keys, command)
        return None

    async def _set_custom(self, key: str, value) -> str | None:
        """Rebind or remove one of ours. `controls.custom.<id>.key|remove`."""
        parts = key.split(".")
        if len(parts) != 4:
            return f"not a keybinding: {key!r}"
        ident, field = parts[2], parts[3]

        entry = next((c for c in self._custom if c["id"] == ident), None)
        if entry is None:
            return "that binding is gone"

        if field == "remove":
            await self._compositor.unbind(entry["keys"])
            self._custom.remove(entry)
            self._save_custom()
            log.info("unbind %s (mine)", entry["keys"])
            return None

        if field != "key":
            return f"not a keybinding: {key!r}"

        keys = self._keys_from(value)
        if keys is None:
            return "that key cannot be bound"
        if keys == entry["keys"]:
            return None

        taken = await self._taken(keys, skip_custom=ident)
        if taken is not None:
            return taken

        await self._compositor.unbind(entry["keys"])
        if not await self._compositor.bind(keys, f"exec {entry['command']}"):
            # Put the old one back rather than leaving the command unreachable.
            await self._compositor.bind(entry["keys"], f"exec {entry['command']}")
            return "sway refused the binding"

        log.info("bind %s -> exec %s (was %s)", keys, entry["command"], entry["keys"])
        entry["keys"] = keys
        self._save_custom()
        return None

    async def _taken(self, keys: str, skip_bind: str = "",
                     skip_custom: str = "") -> str | None:
        """Whether something else already answers to this combination.

        Both lists, because Sway would simply let the second `bindsym` win and
        the page would then show two rows claiming one key.
        """
        for bind in await self._binds():
            if bind.id != skip_bind and self._live_keys(bind) == keys:
                return f"{pretty(keys)} is already bound to {bind.command}"
        for entry in self._custom:
            if entry["id"] != skip_custom and entry["keys"] == keys:
                return f"{pretty(keys)} is already bound to {entry['command']}"
        return None

    def _new_id(self, command: str) -> str | None:
        """A short stable name, salted until it does not collide.

        Same shape as a parsed bind's id, and for the same reason: the id
        follows the command, so rebinding a key leaves the row it belongs to.
        """
        for salt in range(1000):
            ident = hashlib.sha1(f"{salt}:{command}".encode()).hexdigest()[:8]
            if not any(entry["id"] == ident for entry in self._custom):
                return ident
        return None

    def _live_keys(self, bind: Bind) -> str:
        override = self._overrides.get(bind.id)
        return override["keys"] if override else bind.keys

    def _keys_from(self, value) -> str | None:
        """A capture from the mod, or a written combination from `mcsh`."""
        if isinstance(value, dict):
            glfw, mods = value.get("glfw"), value.get("mods", 0)
            if not isinstance(glfw, int) or not isinstance(mods, int):
                return None
            return keys_from_event(glfw, mods)
        if isinstance(value, str) and value.strip():
            return normalise(value.strip())
        return None


def _grouped(items: list[p.SettingsSchemaItem]) -> list[p.SettingsSchemaItem]:
    """Collect each group's rows together, groups in first-appearance order.

    A config interleaves `exec` binds with Sway's own commands freely, and left
    in that order the page grows a second "Applications" heading further down.
    Order within a group is the config's, which is the order the person who
    wrote it chose.
    """
    order: list[str] = []
    for item in items:
        if item.group not in order:
            order.append(item.group)
    return [item for group in order for item in items if item.group == group]


def _clean_command(value) -> tuple[str, str | None]:
    """Check one typed command. Returns the command, and why not if not.

    Deliberately thin. This ends up as `exec <command>` in a Sway bind, which
    Sway hands to `sh -c` — so pipes, `&&` and quoting all work and none of it
    is ours to parse. The only things refused are the ones that would break the
    config line itself, or the row that has to draw it.
    """
    if value is None:
        return "", "a binding needs a command"
    text = str(value).strip()
    if not text:
        # Not an error: clearing the field is how you start again.
        return "", None
    if "\n" in text or "\r" in text:
        return "", "a binding is one line"
    if len(text) > COMMAND_MAX:
        return "", f"that command is longer than {COMMAND_MAX} characters"
    # `exec` is Sway's word, not the command's, and this module adds it. Typing
    # it as well is the obvious mistake and produces `exec exec flameshot`.
    if text.startswith("exec "):
        text = text[5:].strip()
    return text, None


def _missing(command: str) -> str:
    """"flameshot is not installed", when it is not — as a note, never a refusal.

    A bind may reasonably name something not installed yet, or a shell builtin,
    or a program reached through a variable this cannot resolve. So only the
    plainest case is checked — a bare first word — and the answer goes in the
    row's second line rather than into anything that can refuse.
    """
    head = command.strip().split(" ", 1)[0] if command.strip() else ""
    if not head or "=" in head or "/" in head or "$" in head:
        return ""
    return "" if shutil.which(head) else f"{head} is not on PATH"


LABEL_MAX = 44


def _trim(text: str) -> str:
    """A command, cut to the width the row's left column has for it."""
    text = text.strip()
    if len(text) <= LABEL_MAX:
        return text
    keep = LABEL_MAX - 1
    return text[: keep // 2] + "…" + text[-(keep - keep // 2):]


def _label_of(command: str) -> str:
    """A bind's name is what it does. `exec` is noise; the program is the point."""
    text = command.strip()
    if text.startswith("exec "):
        text = text[5:].strip()
    if text.startswith("--no-startup-id "):
        text = text[16:].strip()

    # A small sh program is named by what it ends up running: the rail's
    # `sh -c '… && exec $TERMINAL || exec foot'` reads as "kitty or foot".
    unwrapped = _exec_targets(text)
    if unwrapped:
        text = unwrapped

    # A bind that runs a script is named by the script, not by where it lives —
    # which for the session's own is `$MCSHELL_ROOT/session/…`, not a path.
    # And one that runs `$TERMINAL` is named by what that is: the program.
    head, sep, tail = text.partition(" ")
    head = _expand_env(head)
    if "/" in head:
        head = head.rsplit("/", 1)[1]
    text = head + sep + tail

    if len(text) <= LABEL_MAX:
        return text
    # Cut from the middle. Two binds that differ only in the last few
    # characters — one log file against another — are told apart by their
    # ends, and cutting there would leave the page with two identical rows.
    keep = LABEL_MAX - 1
    return text[: keep // 2] + "…" + text[-(keep - keep // 2):]


def _exec_targets(text: str) -> str:
    """For `sh -c '<program>'`, the programs it execs, joined with "or"."""
    try:
        argv = shlex.split(text)
    except ValueError:
        return ""
    if len(argv) != 3 or argv[0] not in ("sh", "bash") or argv[1] != "-c":
        return ""
    try:
        words = shlex.split(argv[2])
    except ValueError:
        return ""
    targets = [_expand_env(words[i + 1]) for i, w in enumerate(words[:-1]) if w == "exec"]
    return " or ".join(dict.fromkeys(t for t in targets if t))


_DEFAULTED = re.compile(r"\$\{(\w+):-([^}]*)\}")


def _expand_env(word: str) -> str:
    """`$NAME` and `${NAME:-default}` as sh would expand them, for a label.

    Only ever for display: the command itself keeps the variable, so it means
    whatever the variable means when the key is pressed.
    """
    word = _DEFAULTED.sub(lambda m: os.environ.get(m[1]) or m[2], word)
    return os.path.expandvars(word)


def _group_of(command: str) -> str:
    """Sway's own commands on one side, things it starts on the other."""
    return "Applications" if command.strip().startswith("exec") else "Window management"
