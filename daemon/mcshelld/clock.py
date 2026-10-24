"""The local date and time, for the HUD.

Not a settings page: a HUD source, like `battery.py`. The shell had nowhere at
all that said what time it is — Minecraft's own clock is an item that reads the
world's daylight cycle, and this world has neither daylight nor a cycle — so a
desktop made of Minecraft was a desktop you had to open an application to check
the time on.

WHY THE STRING IS BUILT HERE

The mod draws it and knows nothing about it, which is the standing rule, and
here it is also the only way to be right. "Read from the system locale" means
glibc's locale, which is what `strftime` and `nl_langinfo` answer for; the JVM
has its own idea of a default locale, taken from the same environment but
mapped through its own tables, and the two disagree often enough to matter. So
the daemon formats and the mod prints.

TWELVE OR TWENTY-FOUR IS THE LOCALE'S CHOICE, UNLESS IT IS OVERRULED

`nl_langinfo(T_FMT)` is the locale's own time format — `%H:%M:%S` for a
24-hour locale, `%r` or `%I:%M:%S %p` for a 12-hour one. That is the answer to
"what does this machine consider a time", so it is what `system` means. The
two explicit modes exist because a machine running `C.UTF-8` — this one — has
a locale that says 24-hour while its owner may well not.

Seconds are dropped from whatever the locale said. A clock that ticks is a
clock that has to be pushed sixty times a minute, and vanilla's HUD is not a
place anybody reads seconds off.

THE ORDINAL IS ENGLISH-ONLY, AND DELIBERATELY

`strftime` has no ordinal — there is no `%-dth` — and "1st" is not a thing that
survives translation: French wants "1er" on the first and a bare number after
it, German wants "1.", and inventing one per language is a table nobody here
can check. So the suffix is added when the locale's language is English and
left off otherwise, where the date reads `Freitag, Mai 1` in the locale's own
words and word order stays wrong in exactly the way `%A, %B %-d` is wrong. A
locale-correct long date needs CLDR, which is a dependency this does not earn.

`%-I` and `%-d` are glibc's no-pad flag. This is Arch; the host distro is a
locked decision.
"""

from __future__ import annotations

import asyncio
import contextlib
import locale
import logging
import time
from datetime import datetime

log = logging.getLogger(__name__)

#: What the enum row on the General page offers.
MODES = ("system", "12", "24")

_ENGLISH = ("en", "c", "posix")


def _use_system_locale() -> None:
    """Take LC_TIME from the environment. Harmless to call more than once."""
    try:
        locale.setlocale(locale.LC_TIME, "")
    except locale.Error as e:
        # An unset or broken LC_TIME leaves the C locale, which still formats.
        log.warning("clock: keeping the C locale for times (%s)", e)


def _twelve_hour() -> bool:
    """Whether this locale writes times with an AM/PM."""
    try:
        fmt = locale.nl_langinfo(locale.T_FMT)
    except (AttributeError, ValueError):
        return False
    # `%r` is glibc's own "12-hour time" shorthand and is what en_US uses.
    return "%p" in fmt or "%r" in fmt


def _english() -> bool:
    language = (locale.getlocale(locale.LC_TIME)[0] or "C").split("_")[0]
    return language.lower() in _ENGLISH


def _ordinal(day: int) -> str:
    # 11th, 12th, 13th are the exceptions the last digit gets wrong.
    if 11 <= day <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


class Clock:
    """The wall clock, formatted, and a tick on the minute."""

    def __init__(self, on_tick=None, mode: str = "system"):
        self._on_tick = on_tick
        self.mode = mode if mode in MODES else "system"
        self._task: asyncio.Task | None = None
        _use_system_locale()

    # -- formatting --------------------------------------------------------

    def time_format(self) -> str:
        if self.mode == "24":
            return "%H:%M"
        if self.mode == "12":
            return "%-I:%M %p"
        return "%-I:%M %p" if _twelve_hour() else "%H:%M"

    def format(self, when: datetime | None = None) -> tuple[str, str]:
        """(time, date) as they should be drawn — "1:27 PM", "Friday, May 1st"."""
        when = when or datetime.now()
        clock = when.strftime(self.time_format())
        date = when.strftime("%A, %B %-d")
        if _english():
            date += _ordinal(when.day)
        return clock, date

    # -- the tick ----------------------------------------------------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="clock")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        """Fire once a minute, on the minute.

        Slept to the boundary rather than every sixty seconds, so the display
        changes when the minute does. A drifting clock that is right on average
        is still visibly a second or two late every time you look at it.
        """
        while True:
            now = time.time()
            await asyncio.sleep(60.0 - (now % 60.0) + 0.05)
            if self._on_tick is None:
                continue
            res = self._on_tick()
            if asyncio.iscoroutine(res):
                await res
