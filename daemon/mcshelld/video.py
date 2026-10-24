"""The Video page: the backlight, and how the monitor is being driven.

Two subsystems that have nothing to do with each other and belong on one
screen. Brightness is `brightnessctl`, which on a modern system does not need
write access to `/sys/class/backlight` at all — it asks logind, so it works for
whoever owns the active session without a udev rule or a group.

Modes are Sway's, reached through `compositor.py`. Nothing here knows what
i3ipc is, which is the standing rule: all of it lives in that one module.

Changing a mode resizes the output Minecraft is fullscreen on, so the shell
visibly reshuffles when one is applied. That is Sway doing as it was told.

Keys follow the same `<domain>.<id>.<field>` shape as the Sound page:

    video.output.eDP-1.resolution
    video.output.eDP-1.refresh
    video.output.eDP-1.scale
    video.backlight.intel_backlight.brightness
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from . import protocol as p

log = logging.getLogger(__name__)

PAGE = "video"

BACKLIGHT_DIR = Path("/sys/class/backlight")

# Backlight has no event to subscribe to — logind does not broadcast one and
# inotify does not work on sysfs. So it is polled, but the poll is two file
# reads rather than a subprocess, which is cheap enough to leave running.
POLL = 2.0

# Never all the way off: a screen at zero looks broken and cannot be found
# again by the person who has to see the slider to fix it.
MIN_BRIGHTNESS = 0.01

# Offered whatever the monitor is at now. Anything else it is already set to
# is added, so a scale set from the config file is not silently absent.
SCALES = (1.0, 1.25, 1.5, 1.75, 2.0)

TIMEOUT = 5.0


def _scale_label(scale: float) -> str:
    return f"{scale:g}×"


class Video:
    """Settings provider for the Video page."""

    page = PAGE

    def __init__(self, compositor, on_change=None):
        self._compositor = compositor
        self._on_change = on_change
        self._task: asyncio.Task | None = None
        self._last: dict[str, int] = {}

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> bool:
        self._last = self._read_backlights()
        if self._last:
            self._task = asyncio.create_task(self._watch(), name="backlight-poll")
        return True

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _watch(self) -> None:
        """Notice the brightness keys being pressed."""
        while True:
            await asyncio.sleep(POLL)
            current = self._read_backlights()
            if current != self._last:
                self._last = current
                if self._on_change is not None:
                    res = self._on_change(PAGE)
                    if asyncio.iscoroutine(res):
                        await res

    # -- backlight ---------------------------------------------------------

    def _read_backlights(self) -> dict[str, int]:
        """Raw brightness per device. Missing or unreadable devices are skipped."""
        found: dict[str, int] = {}
        try:
            devices = sorted(BACKLIGHT_DIR.iterdir())
        except OSError:
            return found
        for device in devices:
            try:
                found[device.name] = int((device / "brightness").read_text().strip())
            except (OSError, ValueError):
                continue
        return found

    def _max_brightness(self, device: str) -> int:
        try:
            return int((BACKLIGHT_DIR / device / "max_brightness").read_text().strip())
        except (OSError, ValueError):
            return 0

    async def _set_brightness(self, device: str, value: float) -> str | None:
        percent = max(MIN_BRIGHTNESS, min(1.0, value)) * 100
        try:
            proc = await asyncio.create_subprocess_exec(
                "brightnessctl", "-d", device, "set", f"{percent:.0f}%",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            return f"brightnessctl: {e}"
        try:
            _, err = await asyncio.wait_for(proc.communicate(), TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return "brightnessctl timed out"
        if proc.returncode != 0:
            detail = err.decode("utf-8", errors="replace").strip().splitlines()
            return detail[-1] if detail else "brightnessctl failed"
        # Our own change should not also arrive as a poll a moment later.
        self._last = self._read_backlights()
        return None

    # -- reading -----------------------------------------------------------

    async def items(self) -> list[p.SettingsSchemaItem]:
        items: list[p.SettingsSchemaItem] = []
        outputs = [o for o in await self._compositor.outputs() if o.active]

        if not self._compositor.connected:
            items.append(p.SettingsSchemaItem(
                key="video.output..none", type="label", page=PAGE, group="Display",
                label="Sway is not answering", enabled=False,
            ))
        elif not outputs:
            items.append(p.SettingsSchemaItem(
                key="video.output..none", type="label", page=PAGE, group="Display",
                label="No active monitor", enabled=False,
            ))

        for output in outputs:
            group = "Display" if len(outputs) == 1 else output.name
            items += self._output_rows(output, group)

        for device, raw in sorted(self._read_backlights().items()):
            maximum = self._max_brightness(device)
            if maximum <= 0:
                continue
            items.append(p.SettingsSchemaItem(
                key=f"video.backlight.{device}.brightness", type="float", page=PAGE,
                group="Backlight", label="Brightness", detail=device,
                value=round(raw / maximum, 3), min=0.0, max=1.0, step=0.01, unit="%",
            ))
        return items

    def _output_rows(self, output, group: str) -> list[p.SettingsSchemaItem]:
        current = output.current
        rows: list[p.SettingsSchemaItem] = []

        # Resolutions, largest first. Duplicates collapse: a monitor lists one
        # entry per refresh rate, and picking 1920x1080 should be one choice.
        sizes: list[tuple[int, int]] = []
        for mode in output.modes:
            if (mode.width, mode.height) not in sizes:
                sizes.append((mode.width, mode.height))
        sizes.sort(key=lambda wh: wh[0] * wh[1], reverse=True)

        rows.append(p.SettingsSchemaItem(
            key=f"video.output.{output.name}.resolution", type="enum", page=PAGE,
            group=group, label="Resolution", detail=output.description,
            value=f"{current.width}x{current.height}" if current else None,
            options=[p.SettingsOption(id=f"{w}x{h}", label=f"{w} × {h}") for w, h in sizes],
            # Greyed when the monitor offers one size, which for a laptop panel
            # is the normal case — most eDP panels advertise their native mode
            # and nothing else, so the row is real, correct, and has nothing to
            # pick. Enabled-with-one-option would render as a live control that
            # does nothing when clicked, which reads as a bug. Same rule as the
            # refresh row below.
            enabled=len(sizes) > 1,
        ))

        # Refresh rates available *at the current resolution*. A list that
        # included every rate the panel can do at any size would offer choices
        # that silently change the resolution as well.
        if current is not None:
            rates = sorted({
                mode.refresh for mode in output.modes
                if mode.width == current.width and mode.height == current.height
            }, reverse=True)
            rows.append(p.SettingsSchemaItem(
                key=f"video.output.{output.name}.refresh", type="enum", page=PAGE,
                group=group, label="Refresh rate", value=str(current.refresh),
                options=[p.SettingsOption(id=str(r), label=f"{r / 1000:g} Hz") for r in rates],
                enabled=len(rates) > 1,
            ))

        scales = sorted(set(SCALES) | {round(output.scale, 2)})
        rows.append(p.SettingsSchemaItem(
            key=f"video.output.{output.name}.scale", type="enum", page=PAGE,
            group=group, label="Scale", value=f"{round(output.scale, 2):g}",
            options=[p.SettingsOption(id=f"{s:g}", label=_scale_label(s)) for s in scales],
        ))
        return rows

    # -- writing -----------------------------------------------------------

    async def set(self, key: str, value) -> str | None:
        parts = key.split(".")
        if len(parts) < 4 or parts[0] != "video":
            return f"not a video setting: {key!r}"
        domain, field = parts[1], parts[-1]
        ident = ".".join(parts[2:-1])

        if domain == "backlight" and field == "brightness":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return "brightness must be a number"
            if ident not in self._read_backlights():
                return f"no backlight called {ident!r}"
            return await self._set_brightness(ident, float(value))

        if domain == "output":
            return await self._set_output(ident, field, value)

        return f"unknown video setting: {key!r}"

    async def _set_output(self, name: str, field: str, value) -> str | None:
        if not isinstance(value, str) or not value:
            return f"{field} must be named"

        output = next((o for o in await self._compositor.outputs() if o.name == name), None)
        if output is None:
            return f"no monitor called {name!r}"

        if field == "scale":
            try:
                scale = float(value)
            except ValueError:
                return f"not a scale: {value!r}"
            if not 0.1 <= scale <= 6.0:
                return "scale must be between 0.1 and 6"
            ok = await self._compositor.set_output(name, f"scale {scale:g}")
            return None if ok else "sway refused the scale"

        mode = self._pick_mode(output, field, value)
        if isinstance(mode, str):
            return mode
        ok = await self._compositor.set_output(name, f"mode {mode.as_sway()}")
        return None if ok else "sway refused the mode"

    def _pick_mode(self, output, field: str, value: str):
        """The mode a resolution or refresh choice means. A string is an error."""
        current = output.current
        if field == "resolution":
            try:
                width, height = (int(part) for part in value.lower().split("x", 1))
            except ValueError:
                return f"not a resolution: {value!r}"
            candidates = [m for m in output.modes if m.width == width and m.height == height]
            if not candidates:
                return f"{value} is not a mode this monitor has"
            # The fastest the monitor will go at that size. Picking anything
            # else would be choosing a refresh rate on the player's behalf,
            # and the row below this one is where that choice lives.
            return max(candidates, key=lambda m: m.refresh)

        if field == "refresh":
            if current is None:
                return "the monitor is not driving a mode"
            try:
                refresh = int(value)
            except ValueError:
                return f"not a refresh rate: {value!r}"
            for mode in output.modes:
                if (mode.width, mode.height) == (current.width, current.height) \
                        and mode.refresh == refresh:
                    return mode
            return f"{refresh / 1000:g} Hz is not available at this resolution"

        return f"unknown field {field!r}"
