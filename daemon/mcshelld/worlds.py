"""Which world the shell boots into.

Each world is its own folder under the instance's `saves/`, and Minecraft
already keeps every world's state inside its own folder. So switching worlds
needs nothing copied, renamed or reset: the launcher is simply told a different
folder name, and every world is exactly as it was left when it comes back.

The choice is a one-line file, `~/.config/mcshell/world`, written here and read
by `session/prism/common.sh`. A file rather than a message, because the game has
to start with the daemon dead: the launcher reads it on its own, and falls back
to `Tutorial World` if it names a world that is not there.

What is running is a different fact from what is chosen — the choice takes
effect at the next start — so `launch.sh` writes the folder it actually launched
to `$XDG_RUNTIME_DIR/mcshell-world.running`, and the settings page can say
which is which.
"""

from __future__ import annotations

import os
from pathlib import Path

from xdg import BaseDirectory

#: The world a new install boots into: one of the shipped templates. Kept in
#: step with `session/prism/common.sh`, which falls back to the same name.
DEFAULT = "Tutorial World"


def saves_dir() -> Path:
    """The same instance `session/prism/common.sh` resolves, by the same rules."""
    instance = os.environ.get("MCSHELL_INSTANCE") or os.path.join(
        os.path.expanduser("~/.local/share/PrismLauncher/instances"),
        os.environ.get("MCSHELL_INSTANCE_NAME") or "MCShell")
    return Path(instance) / "minecraft" / "saves"


def choice_path() -> Path:
    return Path(BaseDirectory.save_config_path("mcshell")) / "world"


def running_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "mcshell-world.running"


def available() -> list[str]:
    """Folders under saves/ that are worlds, in the order a person would look."""
    try:
        entries = list(saves_dir().iterdir())
    except OSError:
        return []
    return sorted((e.name for e in entries
                   if "\n" not in e.name and (e / "level.dat").is_file()),
                  key=str.casefold)


def listing() -> list[tuple[str, str, int]]:
    """(name, icon path or "", icon mtime) for every world, for the Worlds screen."""
    out = []
    for name in available():
        icon = saves_dir() / name / "icon.png"
        try:
            out.append((name, str(icon), int(icon.stat().st_mtime)))
        except OSError:
            out.append((name, "", 0))
    return out


def _valid(name: str) -> bool:
    return bool(name) and "/" not in name and name in available()


def chosen() -> str:
    """The world the next start will open. Falls back the way the launcher does."""
    try:
        name = choice_path().read_text().strip("\n")
    except OSError:
        return DEFAULT
    return name if _valid(name) else DEFAULT


def running() -> str | None:
    try:
        return running_path().read_text().strip("\n") or None
    except OSError:
        return None


def choose(name: str) -> str | None:
    """Make `name` the world the next start opens. Returns an error, or None."""
    if not _valid(name):
        return f"there is no world called {name!r}"
    path = choice_path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(name + "\n")
        # Atomic, so a launcher reading at the same moment sees the old choice
        # or the new one, never half of either.
        os.replace(tmp, path)
    except OSError as e:
        return f"could not save the choice: {e}"
    return None
