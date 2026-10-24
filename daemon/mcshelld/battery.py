"""The battery, for the XP bar.

Not a settings page. The XP bar is the battery gauge — the shell has no other
place to show one, and a laptop with no way to see its charge is a laptop you
have to guess about. So this is a HUD source: it reads sysfs, and says so
whenever the answer changes.

sysfs rather than UPower or D-Bus, for the same reason `video.py` reads the
backlight there: it is two small file reads, no subprocess, no session bus, and
nothing to be running for it to work. Polled for the same reason as the
backlight too — the kernel has no event to wait on that does not cost more than
the read does.

`/sys/class/power_supply` holds one directory per supply, each with a `type`:

    BAT1    type=Battery   capacity=80  status="Not charging"  present=1
    ACAD    type=Mains     online=1

Both halves are needed. "Not charging" at 80% on mains is not a fault — it is a
charge limit, and this laptop sits there all day. A gauge that read that as
"discharging" would be wrong every time the machine was plugged in.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from . import protocol as p

log = logging.getLogger(__name__)

SUPPLY_DIR = Path("/sys/class/power_supply")

# A percentage moves once a minute at most and a cable is noticed within five
# seconds of being pulled. Cheap enough to leave running: the whole poll is
# four file reads.
POLL = 5.0


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _read_int(path: Path) -> int | None:
    text = _read(path)
    try:
        return int(text)
    except ValueError:
        return None


class Battery:
    """Reads the battery, and says when it changes."""

    def __init__(self, on_change=None):
        self._on_change = on_change
        self._task: asyncio.Task | None = None
        self._last = p.Battery()

    async def start(self) -> bool:
        self._last = self.read()
        if not self._last.present:
            # A desktop is not a failure. The mod draws Minecraft's own XP bar
            # when there is no battery to draw instead, so nothing here has to
            # pretend there is one.
            log.info("battery: no battery found; the XP bar stays Minecraft's")
        self._task = asyncio.create_task(self._poll(), name="battery-poll")
        return self._last.present

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    def state(self) -> p.Battery:
        return self._last

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(POLL)
            try:
                now = self.read()
            except Exception:
                log.exception("battery: could not be read")
                continue
            if now == self._last:
                continue
            self._last = now
            if self._on_change is not None:
                res = self._on_change(now)
                if asyncio.iscoroutine(res):
                    await res

    # -- reading -----------------------------------------------------------

    def read(self) -> p.Battery:
        """One look at every power supply on the machine."""
        try:
            supplies = sorted(SUPPLY_DIR.iterdir())
        except OSError:
            return p.Battery()

        mains = False
        charging = False
        # Charge is summed as energy where the battery reports it, because two
        # batteries of different sizes do not average. Capacity is the fallback
        # for the ones that only report a percentage.
        energy_now = energy_full = 0
        percents: list[int] = []
        present = False

        for supply in supplies:
            kind = _read(supply / "type")
            if kind == "Mains":
                if _read(supply / "online") == "1":
                    mains = True
                continue
            if kind != "Battery":
                continue
            if _read(supply / "present") == "0":
                continue

            status = _read(supply / "status")
            if status == "Charging":
                charging = True

            now = _read_int(supply / "energy_now")
            full = _read_int(supply / "energy_full")
            if now is None or full is None:
                now = _read_int(supply / "charge_now")
                full = _read_int(supply / "charge_full")
            capacity = _read_int(supply / "capacity")

            if now is not None and full and full > 0:
                energy_now += now
                energy_full += full
                present = True
            elif capacity is not None:
                percents.append(capacity)
                present = True

        if not present:
            return p.Battery()
        if energy_full > 0:
            percent = round(100 * energy_now / energy_full)
        else:
            percent = round(sum(percents) / len(percents))
        return p.Battery(
            present=True,
            percent=max(0, min(100, percent)),
            charging=charging,
            mains=mains,
        )
