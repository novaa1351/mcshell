# The world picker

Give Feedback is Worlds..., drawn as Realms' world slots.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## Give Feedback is the world picker, drawn as Realms' world slots

Minecraft already keeps each world's whole state in its own folder under
`saves/`. So switching worlds copies, renames and resets nothing: the launcher
is told a different folder, and every world is exactly as it was left.

- **The pause menu's *Give Feedback* button opens it, as *Worlds...*.** In
  singleplayer the menu builds two link buttons side by side in
  `addFeedbackAndBugsButtons`, both to minecraft.net — in this shell, a browser
  window over the desktop. The first is redirected at the call, so the grid
  lays the replacement out exactly where the original went; *Report Bugs* is
  left alone. Renamed, unlike *Statistics* and *Open to LAN*: those kept their
  words because they are close to what now sits behind them, and "feedback"
  says nothing about worlds. With no daemon the vanilla link is built instead.
- **Each world is a Realms world slot, so you choose by picture.** Realms'
  configure screen is the one place Minecraft shows worlds as images to choose
  between. `RealmsWorldSlotButton` is ported, not reused — it reads a Realms
  server object — with its geometry out of the bytecode: preview 74x74 at (3,3)
  inside the 80x80 `widget/slot_frame`, `icon/checkmark` at (67,4), the name at
  (40,66), a second line at (40,82), slots 98 apart. Four to a page, with
  arrows past that. A world that has never been played has no `icon.png` and
  gets the panorama images Realms uses for a slot with no picture.
- **The tint is Realms', and reads backwards until you see why.** The active
  slot is drawn like a pressed button — preview at 0.56, frame at 0.8, a
  checkmark, no click — while every slot you could switch to is bright. Here
  "active" means the world the next start opens; the running one says *In use*
  underneath.
- **A click marks the world for the next start; a button goes there now.**
  *Restart into …* saves the world first (a unit stop kills the game rather than
  asking it to leave), puts the boot screen back up so the Prism window and the
  Mojang splash stay hidden, removes the drawn marker so `ExecStartPre` waits
  for that screen, and restarts `mcshell-client`. Done in the background and
  answered at once, because the save can take four seconds and the mod's socket
  carries the pointer handshake. That boot is not recorded — a game restart skips
  the daemon's startup and would shorten the next login's estimate.
- **The choice is a file, not a message.** `~/.config/mcshell/world`, one line,
  written atomically by `worlds.py` and read by `session/prism/common.sh`. The
  game has to start with the daemon dead, so the launcher reads it on its own.
  A choice naming a world that is not there, or containing a `/`, falls back
  to `Tutorial World` (M9's default) with a warning in the journal; an environment `MCSHELL_WORLD`
  still wins over both. `launch.sh` writes what it actually launched to
  `$XDG_RUNTIME_DIR/mcshell-world.running`.
- **Previews are paths, and versioned.** `worlds` carries each `icon.png` path
  and its mtime; the screen loads it full size (not the item icons' 16x16) and
  keys the texture on both, because the game rewrites the file in place.
- **Not on the Accessibility page.** It was briefly a row there; a settings row
  cannot show a picture, and two doors onto one choice was not worth keeping.
- **The hotbar follows you; the inventory does not.** Slot assignments live in
  the daemon's config, so the applications are the same in every world. Real
  items are the player's, and the player is per world.
