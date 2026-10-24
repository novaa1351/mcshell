# F2 is the desktop's screenshot key

Why the key is taken from the game, and what it does instead.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## F2 is the desktop's screenshot key, not the game's

The shell had no screenshot of its own. Minecraft has F2 and nothing else did,
so a browser or a terminal — every window that stacks above the game in Fork A
— could not be captured at all.

- **Sway sees F2 before any window does, so this takes the key away from
  Minecraft.** Deliberate rather than a cost: the game is the fullscreen
  backdrop, so a grab of the whole output is the same picture Minecraft would
  have saved, and every screenshot now lands in one directory instead of two.
- **What is really lost is the ability to *record* F2** on the Controls page,
  because the key never reaches the game to be captured. Bind something else
  there; `mcsh` can still set it by name.
- **`session/screenshot.sh` is one file**, like `lock.sh`, because the Controls
  page rebinds the key by rewriting `bindsym` and there should be a single
  thing behind it to rebind.
- **The file, and the clipboard.** `grim` with no `-o` composites every output
  to `~/Pictures/Screenshots`, and `wl-copy` holds it for pasting. It announces
  itself through our own notification server, with the screenshot as the
  toast's icon — `Catalog.resolve_icon` takes an absolute path, so the toast
  shows a thumbnail of what was just taken.
- **Anything narrower than the whole screen is a binding of your own.** grim
  and slurp are here, flameshot is not on every machine, and picking one for
  everybody is the kind of choice the bind maker exists to avoid making.
