# The clock

The daemon formats, the mod prints.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## The clock is the daemon's, and only the pixels are the mod's

The shell had nowhere at all that said what time it is: Minecraft's clock is
an item that reads the daylight cycle, and this world has neither daylight
nor a cycle.

- **Top left, in vanilla's own margin.** Time in yellow, date in white, one
  drop shadow — HUD text, drawn the way the HUD draws text. Hidden under F1
  and behind F3, like everything else in that corner.
- **The string crosses the socket, not the format.** "Read the system locale"
  means glibc's locale, which is what `strftime` and `nl_langinfo` answer
  for; the JVM has its own idea of a default locale, taken from the same
  environment but mapped through its own tables, and the two disagree often
  enough to matter. So `clock.py` formats and `hud/Clock.java` prints.
- **12- or 24-hour is `nl_langinfo(T_FMT)`'s answer**, which is what *System*
  means. The two explicit modes exist because a machine running `C.UTF-8` —
  this one — has a locale that says 24-hour while its owner may well not.
- **No seconds.** A clock that ticks is a clock pushed sixty times a minute,
  and vanilla's HUD is not where anybody reads seconds off. Pushed on the
  minute, slept to the boundary so the display changes when the minute does.
- **The ordinal is English-only, and deliberately.** `strftime` has no
  ordinal and "1st" does not survive translation — French wants "1er" on the
  first and a bare number after it. A locale-correct long date needs CLDR,
  which is a dependency this does not earn.
- **No sun or moon beside it.** The reference this was built from shows one
  because that mod is displaying the *world's* time as well. This world has
  `doDaylightCycle false` and a void sky, so it would be an icon that never
  changed.
