# The volume popup is a boss bar

Vanilla's boss bar on the overlay, what drives it, and the sound it makes.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## The volume popup is a boss bar

Pressing a volume key changed the volume and said nothing. The only way to
find out how loud the machine now was, was to play something or open the
Sound page — which is a settings screen, two menus deep, for a question
answered by a number.

- **A boss bar, because that is the shape of the answer.** Vanilla's
  `boss_bar/white_progress` over its background, 182x5, centred at the top of
  the screen with the name above it — vanilla's own `BossBarHud` geometry, and
  the only thing in the game that is a labelled fraction drawn large, briefly,
  over whatever you were doing. Nothing was invented; a bar was chosen.
- **Muted is the red sprite and the word.** A muted sink still has a volume,
  so the bar's own length cannot say it. Red says it and the level stays
  legible underneath, which is what you want when the next thing you do is
  unmute.
- **It draws on the overlay, not in Minecraft** — the same reason as the
  toasts, only more so. Application windows stack above the game, and the
  moment anybody reaches for the volume keys is the moment they are watching
  something, which is exactly when a HUD element inside Minecraft is hidden.
- **Driven by the change, and nudged by the keypress.** The popup hangs off
  the daemon's `pactl subscribe` feed, so `wpctl` from the command bar, our
  own slider, a headset wheel and the media key all draw the same bar — a
  binding that drew it itself would cover one of those four. That is still
  how every actual change gets on screen.
  **The exception is a press that changes nothing.** Measured: PipeWire emits
  no event at all for a write landing on the value already there — `5%-` at
  zero, `5%+` at a hundred, mute while muted are each *zero* sink events,
  where a real change is one. So at the extremes the subscription has nothing
  to react to, no bar appears, and the key reads as broken rather than as
  already-at-zero. Only the thing that pressed the key knows it happened, so
  `session/volume.sh` says so with `osd_volume` and the daemon draws the bar
  whatever it says. Sent on every press, not just the no-op ones: finding out
  whether the value moved costs two `wpctl get-volume` calls at 16ms, and
  saying so costs 7ms.
  **The rail is unmoved.** `volume.sh` runs the same `wpctl` call first and
  unconditionally, so the volume still changes with the daemon dead, with
  Minecraft dead, and over the lock screen — measured with `mcshelld` stopped.
  Only the popup is lost without a daemon, and the popup is the daemon's.
- **The first reading is silent, and so is a level that did not move** —
  unless a key was pressed, per the bullet above.
  `pactl subscribe` says a sink changed, not what about it changed, and a sink
  says so for a stream attaching or a port switching. The level is compared
  against the last one, rounded to a percent — PipeWire's cubic mapping means
  `5%+` is not exactly five points, and comparing raw floats would call two
  identical bars different.
- **It does not slide or fade.** Vanilla's boss bars do neither, and this
  arrives once per notch of a held key; an entrance animation would be a
  strobe rather than a readout.
- **The sound is the point, not decoration.** A UI click played *after* the
  change goes through the sink that just changed, so how loud it is *is* the
  answer — a number you can hear. The choice is on the Accessibility page,
  because the one certain thing about a noise a machine makes at you is that
  somebody will want a different one: the click, the hurt "oof"
  (`damage/hit1.ogg`), a note block, or nothing. Off still draws the bar; the
  bar is the part that says what happened.
- **One overlay process, two surfaces.** Toasts and the bar are different
  windows in `session/overlay.py` rather than two programs, because the
  fragile part is neither of them — it is `gtk4-layer-shell` having to be
  loaded before libwayland-client, and a second program would mean getting
  that right twice. The daemon's half moved out of `notify.py` into
  `overlay.py` for the same reason it is not called toasts any more: audio has
  no business reaching through the notification server to draw a bar.
