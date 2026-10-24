# The XP bar is the battery

The charge gauge, and why the game's experience is left alone.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## The XP bar is the battery
- **The bar fills with charge and the level reads `80%`.** The shell has
  nowhere else to put a gauge, and a laptop you have to guess about is a bad
  laptop. Vanilla's geometry and sprites, copied out of `InGameHud` rather
  than approximated.
- **Minecraft's experience is untouched — only undrawn.** Orbs are still
  collected and levels still accrue, so enchanting still works; both HUD
  methods are cancelled and redrawn. Picking up experience therefore cannot
  move the battery gauge, and the two can never disagree on screen. A gauge
  that had to fight the game for the same five pixels would lose one day.
- **Colour is the only state.** Green on the battery, white on mains, red
  below 15% with no cable. The bar sprite never changes. *Mains*, not
  *charging*: a battery at a charge limit reports "Not charging" while
  plugged in, and green there would read as draining.
- **No battery, no gauge.** On a desktop the daemon says `present: false` and
  the mod leaves Minecraft's own XP bar alone. No gauge beats a made-up one.
