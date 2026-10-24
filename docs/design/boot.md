# The boot

From login to desktop: the boot screen, offline logins, the GPU warning, and the measured sequence.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## The boot screen is the world-generation screen

The login used to show three unrelated pictures in about thirteen seconds:
sway's flat `#1a1a2e`, then Prism's launcher window filled to the screen by
the daemon, then Minecraft's own Mojang splash. Nothing in any of them said
this shell was coming up. One picture replaces all three, and it is the
screen the game already shows while a world is being made.

- **The pixels are Minecraft's**, out of the installed client jar, the way
  the lock screen and the toasts do it — `session/mcpixels.py`, shared.
  Darkened dirt, the percentage in `ascii.png` with the game's drop shadow,
  and the chunk map.
- **The twelve chunk colours are the real ones.** `LevelLoadingScreen`'s
  `STATUS_TO_COLOR`, read out of the yarn-mapped 1.21.1 jar with `javap` —
  measured, not remembered, because a nearly-right world-gen screen is the
  tell. Unstarted chunks are black, which is not a choice either: vanilla's
  map is an `Object2IntOpenHashMap` with `defaultReturnValue(0)`.
- **The grey band and the black frame are the margin.** Vanilla draws a
  bigger square than the region being generated, and the chunks in between
  only ever reach `STRUCTURE_STARTS`. The first version had no margin and
  read as a progress box rather than as Minecraft; this is the detail that
  fixed it.
- **Two numbers are ours, and both are forced.** How big the map is, and how
  fast the wavefront moves — there is no world being generated here, so
  there is no tracker to ask. The front advances linearly in *radius*. Area
  pacing is what a spiral generator really does and it was tried first; it
  collapses the coloured band to two rings for most of the run, because most
  of a square's area is in its outer rings. Measured by rendering it.
- **The percentage is an estimate and it never lies about being one.** It is
  interpolated against how long *this machine's last boot* took, pulled up to
  a floor by each real event — the daemon listening, the backdrop mapped,
  `hello` — and **capped at 99**. Only `world_ready` from the mod may finish
  it, so the last percent is the one number on screen that cannot be wrong.
  A boot that times out is not recorded, or one bad login would teach the
  next that boots take ninety seconds.
- **It must never appear over a working desktop**, because `$mod+Shift+d`
  restarts the daemon and a fresh daemon knows nothing about what is already
  on screen. Two independent locks: the daemon cancels the screen if
  Minecraft's window is already mapped at its first window sync, and the mod
  re-sends `world_ready` on every reconnection rather than once per run.
  Either alone is enough, which is the point.
- **It takes no input, and there is a timeout.** Empty input region and no
  keyboard, like the other two overlay surfaces, so every safety rail in the
  sway config works while it is up. It comes down after 90 seconds whatever
  happens: a boot screen must never be the reason a session looks hung.
- **No overlay, no boot screen, and no retrying.** An overlay that exits
  within 5s of starting could not run (no display, no layer-shell, no GTK, no
  client jar); a working one never exits while the daemon lives. `overlay.py`
  then answers *nowhere to draw* for 60s, and the boot loop stops at that
  answer. Before 2026-10-19 only an overlay that failed to *launch* counted,
  so one that launched and died was started again every 0.2s tick for the
  whole 90s — eight processes in three seconds, measured by
  `daemon/tests/test_overlay.py`.
- **Three surfaces, because only one of them moves.** The background and the
  logo are built once — 18ms and 32ms — and the percentage and map are 24ms,
  five times a second. Measured; it is the whole reason `loading.py` is split
  the way it is.
- **The screen is the daemon's first act, and that was a bug once.** It used
  to go up after the catalog loaded, which is 1.2s of *synchronous* work with
  the event loop shut, so the overlay was not even spawned until 1.34s in —
  and `mcshell-client.service` starts in the same millisecond as the daemon,
  so Prism's launcher window won that race and was visible over the boot
  screen. Now the first frame is handed over at **T+0.016s**. The other half
  of the same fix was `Surface.cairo`: converting the background was 566ms
  until it grew a fast path for surfaces with no transparency, which is a
  red/blue swap done by slice assignment in C rather than a Python loop.
  **18ms, byte for byte the same answer.**
- **The first two seconds are sway's**, before the daemon exists to draw
  anything. `start-session.sh` renders the same dirt to a PNG and points
  `output * bg` at it through a generated `config.d` snippet, with sway's own
  fallback colour on the line — measured, in a headless nested sway, that a
  later `output * bg` overrides the earlier `solid_color` and that a missing
  file falls back to the colour rather than erroring. A picture that fails to
  render costs the picture, never the login.
- **Prism's window is covered, not hidden.** The daemon still adopts it like
  any application; the boot screen is simply above it. Giving one window an
  exception in the adoption path would be a special case in the part of the
  daemon that has fewest.
- **The game waits for the screen, because covering is a race the shell
  loses.** A layer surface cannot cover a window that appeared before it
  existed, and systemd starts the client in the same millisecond as the
  daemon. The daemon hands over the first frame at T+0.016s, but the overlay
  is a Python interpreter, an `LD_PRELOAD` re-exec and a GTK import away from
  painting: measured at **~0.9s warm and ~2.9s on a first run**, which is what
  a login is. Prism is compiled Qt and wins. So `overlay.py` touches
  `$XDG_RUNTIME_DIR/mcshell-boot.drawn` from its *draw handler* — the frame
  reached the compositor, not merely got composed — and the client unit's
  `ExecStartPre` waits for it, giving up after eight seconds so a screen that
  never comes cannot cost the session. Making the shell faster was tried
  first; it only ever narrows a race.

## A login with no network goes offline, and says so

Booting with the wifi off used to be a minute and a half of a boot screen that
looked stuck, and then Prism's "Choose your offline mode player name" window
filling the screen. **Nothing was slow.** Measured in a network namespace with
no route: Prism fails the token refresh in 0.13s and opens that window at
once — underneath the boot screen, which is above every window and takes no
input, until the screen's 90s timeout. A question nobody could see.

- **The launcher decides before Prism is asked.** `session/prism/online.sh`
  answers in milliseconds when NetworkManager already knows: *connected* with
  *full* connectivity is yes (Arch's NetworkManager does a real check against
  `ping.archlinux.org`, so full means the internet answered); *disconnected*
  or *asleep* is no; *connecting* waits up to 10s for the wifi to finish;
  anything else probes Microsoft's sign-in host with curl, 5s at most. Wifi
  came up ten seconds before this morning's login, so the first row is the
  usual one. Not a clear yes is a no — a false offline costs a skin, a false
  online costs the prompt.
- **Offline is `--offline <name>`, with the account's own name**, read out of
  Prism's `accounts.json` (`profile.name`, nothing else). That is what Prism's
  prompt offers pre-filled, so passing it is pressing OK. Measured end to end
  in a headless sway: no prompt, straight to the launch.
- **Nothing is lost by it but the skin.** Read out of the 1.21.1 bytecode: a
  singleplayer world loads its host from the `Player` tag in `level.dat`,
  matched by *name* (`IntegratedServer.isHost`,
  `PlayerManager.loadPlayerData`), so the offline UUID still finds the same
  inventory in the same place.
- **The boot screen says why**, in one grey line under the map: *No internet
  connection - starting offline*. `launch.sh` sends `launch_mode`, best effort,
  because the game must start with the daemon dead. Grey is `Formatting.GRAY`,
  and the words are nearly Prism's own.
- **The prompt is not restyled — it is gone.** Making Prism's Qt window look
  like the lock screen would mean a Prism theme, and Prism's data directory is
  shared with the Prism used outside this shell. Not asking the question beats
  asking it prettily.
- **A launcher window that is not progress takes the boot screen down.** For
  what `launch.sh` cannot foresee — an account that needs signing in again,
  Microsoft down while the wifi is fine. Measured titles: a normal launch shows
  *Please wait...* and *Console window for MCShell*; anything else from
  `org.prismlauncher.PrismLauncher` during the boot is a question, and
  `Boot.windows` lowers the screen so it can be answered. An unknown window
  costs the boot screen; the other mistake costs the login.
- **`launch.sh --online` and `--offline` still force it either way**, for a
  terminal and for testing.

## The GPU warning is not the desktop's to show

sway nags in a red bar whenever it finds a proprietary Nvidia or DisplayLink
driver: *"Proprietary GPU drivers are not supported by sway. Do not report
issues."* On this hybrid-graphics laptop that is every login, and it is a
layer-shell surface, so it covers the boot screen too.

- **It is the right message to the wrong person.** It is aimed at someone
  running sway directly, and what it is really asking is that they not file
  sway bugs. A desktop's user did not choose sway and has nothing to report;
  this configuration — the game on the Intel iGPU, the dGPU kept for
  PRIME-offloading applications — is the one the shell is built for.
- **Not universal, and not one machine's problem either.** sway raises it
  whenever those drivers are loaded, so every Nvidia user sees it and every
  Intel- or AMD-only user never does. That is what makes it worth fixing rather
  than working around: it would greet a large fraction of anybody else who ran
  this.
- **`SWAY_UNSUPPORTED_GPU=true`, not `--unsupported-gpu`.** sway's own message
  offers both and both work. The variable is chosen because `start-session.sh`
  is the one file where being wrong costs a *login* rather than a session pick:
  measured, an unrecognised flag makes sway exit 1, and an unrecognised
  environment variable is ignored.
- **Nothing is hidden.** Only the bar goes. sway still logs the driver it found
  to `session.log`, which is where a fact about the machine belongs — the same
  split as everywhere else here: the log keeps it, the screen does not.

## On VMware's GPU, sway draws in software

Found by the second-machine test, 2026-10-18, in a VMware Workstation VM with
3D acceleration on. The session came up to the boot screen and stayed there:
the game got an OpenGL context and then died with
`XIO: fatal IO error 22 (Invalid argument) on X server ":0"`.

- **The cause is a check, not the buffer.** Before wlroots accepts any
  client's GPU buffer, it imports it on the render node and closes the handle
  again (`check_import_dmabuf`, wlroots 0.20.2). vmwgfx refuses the close, so
  sway posts `importing the supplied dmabufs failed` and disconnects the
  client. XWayland is a client, so every X application goes with it, the game
  first. GNOME on the same VM is unaffected; mutter does not make that check.
- **Measured with `session/probes/xwayland-gl.sh`**, which runs an X and a
  native Wayland OpenGL client in a hidden sway per variant. On vmwgfx:
  `default` and `WLR_EGL_NO_MODIFIERS=1` lose both; XWayland with `-shm` keeps
  the X client and loses the Wayland one; `WLR_RENDERER=pixman` keeps both.
  No setting skips the check, so only a renderer that offers no GPU buffers at
  all works. Then a real login with pixman reached the world, and every check
  in §Step 4 of `docs/testing3.md` passed.
- **Only that driver.** `start-session.sh` looks at the kernel driver of each
  DRM card and sets `WLR_RENDERER=pixman` when one is `vmwgfx`, and says so in
  `session.log`. Real hardware keeps the GPU: on i915 the same probe gets the
  hardware renderer by default and llvmpipe with pixman. A `WLR_RENDERER` the
  user set wins.
- **The cost is software rendering.** The game runs on llvmpipe in the VM;
  with the mouse fixed, Nick found every feature working. The mouse lag seen
  there was VMware's absolute pointer, not this: *Optimize mouse for games:
  Always* fixed it.
- **It also keeps Sodium off VMware's GPU, which matters.** Launched from Prism
  under GNOME, where the game does run on SVGA3D, Sodium draws no terrain
  until its advanced staging buffers are off. In MCShell, on llvmpipe, the
  terrain shows with Sodium's defaults — measured — so they stay.

## From login to desktop

*Historical: measured 2026-09-07, before the boot screen existed.* The
sequence underneath is unchanged, but what the screen shows during it is now
the boot screen above, and the "open question" it mentions is answered.

Written down because the next thing being worked on lives here rather than in
the mod, and because a cold session otherwise has to reconstruct it from four
files. **Measured on this machine, one login, 2026-09-07.** Treat the timings
as the shape of the thing, not as a spec.

```
19:49:40  GDM runs session/start-session.sh          screen: nothing yet
          -> exports XDG_CURRENT_DESKTOP=sway, truncates the session log
          -> exec sway -c session/sway.conf
19:49:41  sway up; `exec` line starts mcshell-session.target
          both units Started                          screen: #1a1a2e, sway's bg
19:49:43  mcshelld ready: catalog (83 apps), sway IPC,
          slots, binds, the notification server
          listening on $XDG_RUNTIME_DIR/mcshell.sock
   ~43-53 Prism's own windows appear and go. The daemon
          adopts them like any application — fills each
          to the screen and focuses it                screen: the launcher
19:49:53  the mod connects: hello, proto 1, mc 1.21.1  screen: Minecraft, loading
19:49:55  focus_ack game:true — the game has the pointer, the world is up
```

**So there are roughly thirteen seconds between the login and anything that
looks like this shell**, and for most of it the screen is a flat colour and
then somebody else's launcher. Nothing is wrong during that window; there is
simply nothing that says so. See the open question below.

- **`sway.conf` is the top of it.** `output * bg #1a1a2e solid_color` is what
  fills those seconds, and one `exec` line starts the target that starts
  everything else. `start-session.sh` is the only thing that runs *outside*
  sway, which is what makes it the place that cleans up: it stops
  `mcshell-session.target` after sway exits, so Minecraft does not outlive the
  logout still holding the world's `session.lock`.
- **Two units and a target**, templated on the repo path by
  `install-session.sh` — `@REPO@` rather than `%h`, because the checkout is not
  required to live in the home directory. Both are `Restart=on-failure`, and
  `mcshell-client` deliberately does *not* restart on a clean exit: *Save and
  Quit* exits 0 and is a thing somebody meant to do. `$mod+Shift+m` is the way
  back and it is a compositor binding, so it works with everything else dead.
- **The client is Prism, in the foreground.** `session/prism/launch.sh` runs
  `prismlauncher --launch <instance> --world <world>`, so the shell boots into
  the world rather than to a main menu — a desktop nobody has logged into yet.
  `--offline` is the escape hatch, and it exists because here a stale token
  costs a desktop rather than a game.
- **Two logs, and they are not the same.** The units go to the journal
  (`$mod+Shift+j`). sway goes to
  `$XDG_STATE_HOME/mcshell/session.log`, truncated per login. The second one is
  the only copy of why a login failed — and it is also, currently, where every
  application launched from the shell dumps its stderr, because sway's children
  inherit it. See the gaps.
- **`session/diagnose.sh` is the first thing to run when it comes up wrong.**
  `docs/testing.md` §*The M7 walkthrough — the real session* is the boot
  walkthrough; that book is closed for new material but this part of it is
  still the reference, including *When it comes up wrong* and the first-login
  recipe.
- **There is no way to test a login without logging out.** That is the point of
  MCShell being a *second* GDM entry rather than a replacement: a broken config
  costs a session pick, not a login. Nested sway (`sway.dev.conf`) tests the
  layout and the daemon, never this.
