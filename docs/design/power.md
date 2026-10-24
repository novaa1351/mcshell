# Save and Quit is the power menu

Lock, Sleep, Restart and Power Off, the lock screen they share, and saving before shutdown.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## Save and Quit to Title is the power menu
The one button on the pause menu whose vanilla meaning the shell cannot
honour. There is no title screen to go back to — the world *is* the desktop,
and leaving it leaves a logged-in session looking at nothing. So the button
that meant "stop playing" now means **stop using the computer**: Lock Screen,
Sleep, Restart, Power Off, and nothing else.

- **The button keeps its wording**, like *Open to LAN* and *Statistics*. It is
  already the button about leaving, and a renamed one is a tell.
- **Hooked at `GameMenuScreen.disconnect()`**, not by finding the button. That
  is where every route to the title screen ends up, and it is a method with a
  name rather than a lambda inside a grid layout. Cancelling at HEAD costs
  nothing — its first act is to read whether the world is singleplayer.
- **Escape is the way back**, and there is no fifth button for it. Returning
  re-shows the pause menu, and `setScreen` re-runs `init`, so the button
  vanilla disabled on the way in is rebuilt live with nothing to put back.
- **The two that cannot be undone ask first**, in vanilla's own
  `ConfirmScreen`. Lock and Sleep are one password away from where you were;
  Restart and Power Off close every window on the machine and sit one
  button-height from the two that do not.
- **Sleep locks first.** Nothing else in this session would — there is no
  swayidle and no sleep hook — and a laptop that wakes straight onto the
  desktop is not a locked laptop. If the lock will not come up it still
  suspends, and the log says so: a machine that refuses to sleep because of
  its lock screen is worse than one that sleeps unlocked.
- **The lock screen is started by the compositor, never as a child of the
  daemon.** `$mod+Shift+d` restarts the daemon, and a child dies with it —
  unlocking a machine by restarting a service is not a lock screen. Sway's
  `exec` puts it in the compositor's cgroup, where the keybinding's own
  swaylock already lives.
- **`session/lock.sh` is the lock screen, and it is one file.** Both the
  button and `$mod+Shift+l` run it, because the same command written into two
  places eventually will not be the same command.
- **The screen is drawn into the background image.** No lock program draws a
  screen: swaylock shows a colour and a ring and nothing else — no field, no
  cursor, no username — and upstream has no option to draw text (`--clock` and
  `--timestr` belong to swaylock-effects). Everything therefore goes into the
  PNG every route can display, rendered at the output's own resolution so
  nothing is scaled.
  **This was a real failure, not a precaution:** the first time the button was
  used, the screen came up, keys reached swaylock — the ring lit — and no
  password was ever submitted. `pam_unix(swaylock:auth)` logs every attempt
  and the journal had none, across twenty-six minutes and then a held power
  button. The lock worked perfectly and said nothing about how to leave it.
- **What it draws is Minecraft's Direct Connection screen.** `lockscreen.py`
  reads the installed client jar and composes the dirt block tiled at the
  game's own GUI scale, the `widget/button_disabled` sprite, the two
  rectangles `TextFieldWidget` fills, and text set in `font/ascii.png` with
  the game's drop shadow. Nothing is a lookalike; the pixels are Minecraft's.
  Title *Session Locked*, label *Password*, and two buttons — one saying what
  Enter does, one naming `user@host`. Disabled sprites, because swaylock takes
  no mouse and a button that looks clickable and is not would be a lie.
- **The password box is hyprlock's, and it shows what you type.** swaylock has
  no password echo of any kind — no asterisks, no dots, no character count —
  and a static PNG cannot react to a keystroke, so the only way to see
  yourself typing is a different lock program. hyprlock draws a real
  `input-field`, and takes enough theming to be given `TextFieldWidget`'s own
  two rectangles: a one-pixel white border, black inside, square corners,
  square dots. So `lockscreen.py --no-field` leaves a hole in the picture and
  hyprlock fills it with a box you can type into. It is positioned by the
  renderer rather than guessed at — `lockscreen.py` prints where it put the
  field and `lock.sh` writes that into a generated config.
- **Failure is said in colour, not in prose.** The field's outline goes red on
  a wrong password and yellow on caps lock, and `fail_text` is empty. There is
  no Minecraft font on the machine, and a sentence set in DejaVu under a
  screen made of Minecraft's own pixels is the tell.
- **This does not put credentials in the game.** It is a picture of a
  Minecraft screen drawn by a Python script; the password is read by the lock
  program and checked by PAM, exactly as before. Both hyprlock and swaylock
  lock through `ext-session-lock-v1`. The rail is unmoved.
- **Four routes, each a fallback for the one above.** hyprlock over the
  Minecraft screen; swaylock over the same screen with its ring inside the
  drawn field, where it reads as that field's cursor; a plain ImageMagick one
  that at least says what to do; bare swaylock. A lock screen that will not
  draw must still lock, so nothing here is allowed to fail into an unlocked
  machine.
- **No passwords, and nothing needs one.** `CanPowerOff`, `CanReboot` and
  `CanSuspend` all answer `yes` for the active local session, so logind is
  simply asked. Nothing here goes near the credentials rail.
- **Restart and Power Off save the world first, by any route.** Nothing used to:
  at logout or power off sway goes first and the game dies with its display
  (`The Wayland connection broke`, exit 255), and every game log ended partway
  through an autosave with no `Stopping server`. A unit stop hook would run
  after that. So the daemon holds a logind **delay inhibitor**; logind sends
  `PrepareForShutdown(true)` and waits while the daemon asks the mod for
  `save_world` — vanilla's own `/save-all flush`, read out of `SaveAllCommand`
  — and releases the lock on the answer or after 4s, inside logind's 5s cap.
  It covers the power button and a typed `systemctl poweroff` as well as the
  menu, because all of them go through logind. Sleep is not held: memory
  survives a suspend, and the delay would be paid on every lid close.
  `power.ShutdownSave`.
