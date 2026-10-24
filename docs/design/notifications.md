# Notifications are advancement toasts

The notification server, and the overlay that draws above every window.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## System notifications are advancement toasts

A Discord ping arrives as the 160x32 `toast/advancement` sprite in the
top-right corner: the application's own icon at 16x16, the summary on the
header line, the body under it. Nothing on this machine owned
`org.freedesktop.Notifications` before this did — no mako, no dunst, no
swaync, and `busctl` found no owner — so in the MCShell session a
notification used to go nowhere at all.

- **This is one of the two things the shell draws that Minecraft does not.**
  In Fork A the game is the *backdrop* and application windows stack above it,
  so a toast rendered inside Minecraft is a toast behind whatever you were
  looking at when it arrived. A notification you have to alt-tab to a game to
  discover is not a notification. `session/overlay.py` draws it on a
  layer-shell surface in the `overlay` layer instead, above every ordinary
  window including the game's own. The volume bar is the other, and shares
  that process.
- **The pixels are still Minecraft's**, out of the installed client jar, the
  way the lock screen does it. Shared with the lock screen, in
  `session/mcpixels.py`.
- **The geometry is read out of `AdvancementToast`, not eyeballed.** Toast
  160x32, icon at (8,8), header at (30,7), body at (30,18), text wrapped at
  125px, neither line with a drop shadow — both `drawText` calls pass
  `false` — visible 5000ms, sliding in from the right over 600ms on
  `f = clamp((now - start) / 600)²`, stacked every 32px. Measured from the
  bytecode, because a toast that is *nearly* vanilla's is the tell.
- **Colour is by urgency**, and it is the one thing here that is ours rather
  than copied. Vanilla picks the header colour by advancement frame; there are
  no advancements, so a critical notification gets the challenge colour
  (`0xFF88FF`) and everything else gets `0xFFFF00`.
- **A muted machine stays silent.** The sound is skipped when the default
  sink is muted or at zero — asked of PipeWire, because the volume keys go
  straight to `wpctl` so no setting knows the answer. Not merely cosmetic:
  opening a stream *wakes* a suspended sink, and WirePlumber then re-applies
  that route's saved volume and mute, which is how a muted laptop ends up
  playing a notification at the level it had an hour ago. Not making the
  sound is both the right behaviour and what stops the sink being woken.
  Fails open — PipeWire not answering gets a sound, since never hearing one
  again is the worse failure.
- **The sound is the XP level-up**, `random/levelup.ogg`, found through
  Minecraft's asset index because the file itself is named after its hash and
  nothing else says what it is. One row on the Sound page switches it off, and
  two notifications inside 0.75s are one sound — a group chat catching up
  after a resume would otherwise play twenty. A sender's `suppress-sound` hint
  is honoured.
- **The surface takes no input at all.** Its input region is empty, so clicks
  pass through to whatever is underneath. Vanilla's toasts cannot be clicked
  either, and a strip of the screen that silently eats mouse presses is the
  bug this project has already spent a session on.
- **Actions and body markup are not claimed.** `GetCapabilities` answers
  `body` and `icon-static` and nothing else, because there is nothing to click
  a button on and the game's font has one weight. Markup that arrives anyway
  is stripped rather than drawn.
- **The icon is the catalog's.** `desktop-entry` hint, then `app_icon`, then
  the `image-path` hint, then the application's name — all of them ending at
  `Catalog.resolve_icon`, so a notification's icon and its application's
  hotbar item are the same picture, SVG rasterising included.
- **Five at once, and the rest queue.** A sixth toast waits for a slot rather
  than living out its five seconds off screen, which is what vanilla's manager
  does. `replaces_id` swaps a toast in place without re-sliding it, so a music
  player updating its own does not read as two.
- **gtk4-layer-shell must be loaded before libwayland-client**, which a Python
  import cannot arrange, so `overlay.py` re-executes itself once with
  `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`. Measured: `is_supported()` is
  False without it, False with the `liblayer-shell-preload.so` shim, True with
  the library. Getting it wrong is not cosmetic — the window comes up as an
  ordinary toplevel, and the daemon fills it to the screen and focuses it as
  though the overlay were an application somebody launched. That happened. It
  now refuses to open at all rather than open the wrong kind of window, and
  `OWN_SURFACES` in `main.py` is the second lock on the same door.
- **It draws in software** — `GSK_RENDERER=cairo`, set by `overlay.py` as a
  default the environment can override. GTK's GL renderer went through glvnd,
  which tries Nvidia's EGL before Mesa's, so a process that draws toasts was
  holding a context on the 4070. Measured: 182MB on GL against 46MB on cairo
  for one toast (167MB to 78MB on the live session), *less* CPU on cairo for
  every surface, and grim found them pixel-identical. Not one machine's
  problem: every Nvidia laptop has that EGL vendor file, and on Mesa alone
  cairo is still 84MB to 46MB.
- **No protocol change, and no mod change.** The daemon decides and the
  overlay renders; they speak one JSON object a line over the overlay's stdin,
  which is not the mod's socket and is documented in `overlay.py`.
