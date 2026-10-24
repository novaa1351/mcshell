"""Hotbar slot assignments and their persistence.

Assignments live in the daemon's config dir, deliberately *not* in the
Minecraft world save: the hotbar is a rendered view of daemon state, and a
world can be deleted and recreated without losing the shell's layout.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path

from xdg import BaseDirectory

log = logging.getLogger(__name__)

# A Minecraft hotbar is nine slots. Slot numbers are 1-based to match the
# number keys that select them.
HOTBAR_SLOTS = 9
SLOT_RANGE = range(1, HOTBAR_SLOTS + 1)


def default_path() -> Path:
    return Path(BaseDirectory.save_config_path("mcshell")) / "slots.json"


class SlotError(ValueError):
    """Raised for a slot number outside the hotbar."""


class State:
    """Slot -> desktop id, persisted as JSON.

    Slots are sparse in storage and dense on the wire: only assigned slots are
    written to disk, but `items()` always yields all nine so the mod can render
    the hotbar without reasoning about gaps.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or default_path()
        self._slots: dict[int, str] = {}

    # -- persistence -------------------------------------------------------

    def load(self) -> None:
        """Read assignments from disk. A missing or corrupt file is not fatal.

        Losing a hotbar layout is annoying; refusing to start the shell because
        of a bad JSON file is worse. A corrupt file is moved aside so the next
        save doesn't have to fight it, and the user can inspect it.
        """
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            self._slots = {}
            return
        except (json.JSONDecodeError, OSError) as e:
            broken = self.path.with_suffix(".json.broken")
            log.warning("unreadable slot file %s (%s); moving to %s", self.path, e, broken)
            with contextlib.suppress(OSError):
                self.path.rename(broken)
            self._slots = {}
            return

        slots: dict[int, str] = {}
        for key, value in (raw.get("slots") or {}).items():
            try:
                slot = int(key)
            except (TypeError, ValueError):
                continue
            if slot in SLOT_RANGE and isinstance(value, str) and value:
                slots[slot] = value
        self._slots = slots
        log.info("loaded %d slot assignment(s) from %s", len(slots), self.path)

    def save(self) -> None:
        """Write assignments atomically.

        Written to a temp file in the same directory and renamed, so a crash
        mid-write cannot truncate an existing layout.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "slots": {str(k): v for k, v in sorted(self._slots.items())}}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".slots-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(payload, f, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    # -- accessors ---------------------------------------------------------

    @staticmethod
    def check_slot(slot: int) -> int:
        """Validate a slot number, raising SlotError.

        Public because callers validate before acting, so a bad slot becomes a
        clean protocol error rather than an exception mid-operation.
        """
        if slot not in SLOT_RANGE:
            raise SlotError(f"slot {slot} out of range 1..{HOTBAR_SLOTS}")
        return slot

    def get(self, slot: int) -> str | None:
        return self._slots.get(self.check_slot(slot))

    def assign(self, slot: int, app_id: str) -> None:
        if not app_id:
            raise SlotError("app id must not be empty")
        self._slots[self.check_slot(slot)] = app_id
        self.save()

    def clear(self, slot: int) -> bool:
        """Empty a slot. Returns True if something was actually removed."""
        removed = self._slots.pop(self.check_slot(slot), None) is not None
        if removed:
            self.save()
        return removed

    def items(self) -> list[tuple[int, str | None]]:
        """All nine slots in order, unassigned ones as None."""
        return [(i, self._slots.get(i)) for i in SLOT_RANGE]

    def assigned(self) -> dict[int, str]:
        return dict(self._slots)
