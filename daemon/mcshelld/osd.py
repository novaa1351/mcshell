"""The volume popup, and the sound it makes.

The media keys are bound straight to `wpctl` in the Sway config and always have
been — a safety rail that works with the daemon dead. Nothing about that
changes here. The daemon already watches PipeWire so the Sound page can follow
a keypress, and this hangs off the same subscription: the volume moved, so say
what it moved to.

Driving it from the *change* rather than from the *keypress* is what makes it
right in the cases nobody thinks about. `wpctl` typed into the command bar, the
slider on our own Sound page, a headset with its own wheel, another application
taking the sink down — all of them are somebody changing the volume, and all of
them get the same bar. A binding that drew the popup itself would show it for
exactly one of the four.

WHY IT IS NOT DRAWN IN MINECRAFT

Same reason as the toasts, only more so. In Fork A application windows stack
above the game, and the moment anybody reaches for the volume keys is the
moment they are watching something — which is to say, the one moment a HUD
element inside Minecraft is certainly hidden. So it goes on the layer-shell
overlay, above every window.

WHAT IT LOOKS LIKE

Minecraft's boss bar: the 182x5 `boss_bar/white_progress` sprite over its
background, centred at the top of the screen with the name above it, which is
where and how vanilla draws one. That is not a costume — a boss bar *is* a
labelled fraction, drawn large, briefly, over whatever you were doing. Nothing
else in the game is that shape. Muted swaps the sprite for the red one and the
label for the word, so the level is still legible while it is silenced.

THE SOUND

A UI click, played after the change, through the sink that just changed — so
how loud it is *is* the answer. The choice of sound is on the Accessibility
page, because the one thing certain about a noise the machine makes at you is
that somebody will want a different one, or none.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import time

from .notify import PLAYERS, asset_path

log = logging.getLogger(__name__)

#: How long the bar stays up after the last change. Long enough to read at a
#: glance, short enough that holding the key down never leaves it behind.
VISIBLE_MS = 1400

#: Sway repeats a held binding about 25 times a second and every repeat is a
#: real volume change, so every repeat would be a `pw-play`. This is the
#: shortest gap that still reads as a tick per notch rather than as a tone.
SOUND_GAP = 0.09

#: The bar's sprite colour, which is a `boss_bar/<colour>_progress` in the
#: client jar. Red is not decoration: it is the only state the bar cannot show
#: by its own length, since a muted sink still has a volume.
NORMAL = "white"
MUTED = "red"

#: What the Accessibility page offers. `""` is the sound being off; the popup
#: is still drawn, because the popup is the part that says what happened.
SOUNDS: dict[str, tuple[str, str]] = {
    "click": ("Click", "minecraft/sounds/random/click.ogg"),
    "hurt": ("Hurt", "minecraft/sounds/damage/hit1.ogg"),
    "note": ("Note block", "minecraft/sounds/note/harp.ogg"),
    "none": ("Off", ""),
}
DEFAULT_SOUND = "click"


class Osd:
    """Draws the bar, and makes the noise. Owns neither the volume nor the key."""

    def __init__(self, overlay) -> None:
        self._overlay = overlay
        self.sound = DEFAULT_SOUND
        self._at = 0.0
        self._reap: set[asyncio.Task] = set()
        #: Resolved once. An asset store that has moved since startup is a
        #: broken install, not a case to re-check on every keypress.
        self._files = {
            key: (asset_path(asset) if asset else None)
            for key, (_, asset) in SOUNDS.items()
        }
        missing = [k for k, (_, a) in SOUNDS.items() if a and not self._files[k]]
        if missing:
            log.info("osd: no asset for %s; those choices stay silent",
                     ", ".join(missing))

    def sound_label(self, key: str | None = None) -> str:
        return SOUNDS.get(key or self.sound, SOUNDS[DEFAULT_SOUND])[0]

    def set_sound(self, key: str) -> bool:
        if key not in SOUNDS:
            return False
        self.sound = key
        return True

    async def volume(self, level: float, muted: bool, *, quiet: bool = False) -> None:
        """Say that the volume is now this. `quiet` draws without the click."""
        level = min(1.0, max(0.0, level))
        percent = round(level * 100)
        await self._overlay.send({
            "t": "osd",
            # The daemon decides what it says; the overlay only knows how to
            # draw a labelled bar in a colour. Same split as everywhere else.
            "text": "Muted" if muted else f"Volume {percent}%",
            "value": level,
            "color": MUTED if muted else NORMAL,
            "ms": VISIBLE_MS,
        })
        if not quiet:
            await self.play()

    async def play(self) -> None:
        """The click, through the sink that just changed, so it lands at the
        new level. That is the whole point of it — a number you can hear."""
        path = self._files.get(self.sound)
        if not path:
            return
        now = time.monotonic()
        if now - self._at < SOUND_GAP:
            return
        self._at = now
        for player in PLAYERS:
            if shutil.which(player) is None:
                continue
            try:
                proc = await asyncio.create_subprocess_exec(
                    player, path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except OSError as e:
                log.debug("osd: %s: %s", player, e)
                continue
            task = asyncio.create_task(self._reaped(proc), name="osd-sound")
            self._reap.add(task)
            task.add_done_callback(self._reap.discard)
            return

    async def _reaped(self, proc) -> None:
        """Wait for the child so it does not become a zombie. No timeout: every
        one of these is a Minecraft sound effect under two seconds long."""
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 10.0)
