# MCShell

A Linux desktop shell where Minecraft is the control surface. Minecraft provides the
launcher, taskbar, window switcher, settings, and command bar. Application windows are
**real windows** managed by a real compositor (Sway), not rendered inside Minecraft.

This is not WaylandCraft. We never render app surfaces into the game world and never
translate input into Wayland clients. Minecraft is a shell, not a compositor.

## Locked decisions

These are settled. Do not propose alternatives unless explicitly asked.

| Decision | Value |
|---|---|
| Minecraft | Java Edition **1.21.1**, pinned permanently |
| Modloader | **Fabric** (client-side only) |
| JDK | **21** (required by 1.21.1) |
| Compositor | **Sway** (i3 IPC via `i3ipc-python`) |
| Daemon language | **Python 3**, asyncio |
| Transport | Newline-delimited JSON over unix socket at `$XDG_RUNTIME_DIR/mcshell.sock` |
| Host distro | Arch Linux |
| Display model | **Fork A** — MC fullscreen, apps raise above it, Super returns to MC (and opens nothing over it) |
| Monitors | Single |
| World | Superflat void, 2x2 chunks, survival-flavored, world border 32. A new install boots into **Tutorial World**, one of the shipped templates |

## Core architectural rule

**The mod is dumb. The daemon is smart.**

The mod renders state and forwards input events. It knows nothing about Sway, D-Bus,
PipeWire, `.desktop` files, or process management. All logic, state, and system
integration lives in the daemon.

This is load-bearing for two reasons: the daemon is testable without launching
Minecraft, and the client stays swappable if we ever migrate off the JVM. Do not let
logic drift into the Java side. If you find yourself writing a decision in the mod,
it belongs in the daemon.

**Use vanilla Minecraft rendering; do not invent UI.** A shell that reads as a
resource pack is finished. One that reads as a web app embedded in a game is a
different project. (M8's rule, and it still holds.)

## Architecture

```
Minecraft (Fabric mod)          mcshelld (Python)               System
──────────────────────          ─────────────────               ──────
hotbar overlay          ◄──┐    state store              ┌──► Sway IPC (i3ipc)
overview Screen         ◄──┼──► event router             ├──► .desktop catalog (pyxdg)
app catalog browser     ◄──┤    adapter dispatch    ─────┼──► PipeWire (pactl)
chat command bar        ◄──┤                             ├──► NetworkManager (nmcli)
socket client thread    ───┘                             └──► brightnessctl
```

## Repo layout

```
mcshell/
├── CLAUDE.md
├── CONTRIBUTING.md          # for people: the split, running it, tests and lint
├── .github/                 # CI (build, pytest, ruff, shellcheck), releases on a tag
├── ruff.toml, .shellcheckrc # lint rules: bugs, not style; versions pinned in CI
├── bin/mcshell              # check, setup, diagnose — a dispatcher, nothing more
├── daemon/
│   ├── mcshelld/
│   │   ├── main.py          # asyncio server, accept loop
│   │   ├── protocol.py      # message types — single source of truth
│   │   ├── compositor.py    # ALL i3ipc lives here, nothing else touches sway
│   │   ├── catalog.py       # .desktop parsing, icon theme resolution
│   │   ├── shell.py         # command bar: run a line, stream its output
│   │   ├── settings.py      # settings hub: pages, and who answers for them
│   │   ├── audio.py         # the Sound page, via pactl
│   │   ├── video.py         # the Video page: backlight + sway outputs
│   │   ├── binds.py         # the Controls page: rebinding sway keys
│   │   ├── network.py       # the Network page: nmcli, and BlueZ
│   │   ├── battery.py       # the charge, for the XP bar
│   │   ├── clock.py         # the local date and time, for the HUD
│   │   ├── boot.py          # how far the boot is, and when to stop saying so
│   │   ├── worlds.py        # which world the shell boots into
│   │   ├── general.py       # the Accessibility lane: the shell's own settings
│   │   ├── stats.py         # the Statistics screen, and screen time
│   │   ├── files.py         # directories, for the Advancements file tree
│   │   ├── power.py         # lock, sleep, restart, power off
│   │   ├── notify.py        # org.freedesktop.Notifications, and what a toast says
│   │   ├── overlay.py       # the layer-shell process both surfaces are drawn on
│   │   ├── osd.py           # the volume popup, and the sound it makes
│   │   ├── paths.py         # where session/ is: $MCSHELL_ROOT, else the checkout
│   │   └── state.py         # slot assignments, persistence
│   ├── tests/               # pytest: the real daemon, sealed off, over its socket
│   ├── tools/mcsh           # CLI test harness
│   ├── tools/mcshell-askpass  # sudo's password prompt, as a real window
│   └── pyproject.toml
├── mod/                     # Fabric gradle project
│   ├── tools/icons.py       # draws the file tree's icons; run it, don't redraw them
│   └── src/main/java/dev/mcshell/
│       ├── MCShellClient.java  # entry point, client tick, the cursor handshake
│       ├── net/             # socket client, and the state the renderer reads
│       ├── hud/             # the battery gauge, and the clock
│       ├── render/          # the app item's model and quad, icon textures
│       ├── screen/          # the output panel, catalog, settings, inventory hook
│       └── command/         # the chat command bar and its output panel
├── session/
│   ├── layout.conf          # Fork A: what floats, and what the backdrop is
│   ├── prism/               # the real client: build, install, pin, launch, online?
│   ├── lock.sh              # the lock screen: one file, two callers
│   ├── screenshot.sh        # F2, for the whole desktop rather than the game
│   ├── volume.sh            # the volume keys, and the nudge that draws the bar
│   ├── raise-mc.sh          # Super: put the backdrop back in front
│   ├── close-focused.sh     # Alt+F4, refusing on the backdrop
│   ├── fill.sh              # size a window to the whole output
│   ├── lockscreen.py        # draws it, out of Minecraft's own textures
│   ├── mcpixels.py          # Minecraft's PNG decoder, canvas and font, shared
│   ├── overlay.py           # toasts and the volume bar, above every window
│   ├── probes/              # instruments: who holds the pointer, what got clicked
│   ├── sway.dev.conf        # nested dev testing
│   ├── start-nested.sh      # dev only: runs it, and says where the checkout is
│   ├── restart-daemon.sh    # dev only; the real session uses systemctl
│   ├── run-client.sh        # dev only; the real session uses systemctl
│   ├── sway.conf            # the real session
│   ├── start-session.sh     # what GDM runs; stops the units after sway exits
│   ├── install-session.sh   # units + the GDM entry, idempotent
│   ├── diagnose.sh          # what the shell can see when it comes up wrong
│   ├── check.py             # is this machine set up, and what is missing
│   └── systemd/             # two units and a target, templated on the repo path
├── templates/               # the shipped worlds, made from the snapshots by build.py
└── docs/
    ├── protocol.md          # every message, in sync with protocol.py
    ├── design/              # one file per feature: the spec, and why it is so
    ├── m9.md                # the current milestone's plan
    ├── milestones.md        # what M0–M8 were
    ├── troubleshooting.md   # for people: the login, the rails, what to read
    └── testing/             # the sign-off walkthroughs: m0-m7, m8, m9 (current)
```

## Protocol

Newline-delimited JSON. Daemon listens, mod connects as client. Keep
`docs/protocol.md` and `daemon/mcshelld/protocol.py` in sync — if you change one,
change the other in the same commit.

### Mod → daemon

```json
{"t":"hello","proto":1,"mc":"1.21.1"}
{"t":"catalog_query","text":"fire","tab":"Network"}
{"t":"slot_assign","slot":1,"app":"firefox.desktop"}
{"t":"slot_clear","slot":1}
{"t":"slot_activate","slot":1,"button":"right"}
{"t":"slot_activate","slot":1,"button":"shift_right"}
{"t":"focus_ack","game":false}
{"t":"slot_close","slot":1}
{"t":"command_submit","text":"git status"}
{"t":"setting_set","key":"audio.volume","value":0.4}
```

### Daemon → mod

```json
{"t":"catalog","items":[
  {"id":"firefox.desktop","name":"Firefox",
   "icon_path":"/usr/share/icons/hicolor/48x48/apps/firefox.png",
   "categories":["Network","WebBrowser"]}]}

{"t":"taskbar","slots":[
  {"i":1,"app":"firefox.desktop","icon_path":"...","running":true,
   "windows":3,"focused":true},
  {"i":2,"app":"foot.desktop","icon_path":"...","running":false,"windows":0}]}

{"t":"output","lines":["..."],"stream":"stdout"}
{"t":"overview","show":true}
{"t":"focus","game":false}
{"t":"hud","clock":true,"time":"1:27 PM","date":"Friday, May 1st",
 "battery_color":true}

{"t":"settings_schema","items":[
  {"key":"audio.volume","type":"float","min":0,"max":1,"label":"Volume"}]}
```

Icons are sent as **filesystem paths, never base64**. Same machine; the mod loads the
path directly and caches the resulting texture by path.

## Behavior spec

Each heading is a summary. **The doc it names is the spec**, with the reasons
and the measurements behind every rule; read it before changing that feature.
The rules look arbitrary without them, and several were reached by shipping
the obvious version first and watching it fail.

### Hotbar, visual state, click bindings — `docs/design/hotbar.md`
Nine slots of real `mcshell:app` stacks, derived from every `taskbar` push; a
click is reported, never applied. Application stacks are atomic and never land
on the ground. Glint = running, count = windows, selection follows focus, dim =
launching — vanilla's own components. Right-click focuses or launches,
left-click cycles, shift+right launches another, shift+middle closes; number
keys only select. A running app with no slot borrows a free one, in memory.

### The XP bar is the battery — `docs/design/battery.md`
Vanilla's bar and sprites, filled with charge; experience still accrues but is
undrawn. Colour is the only state. No battery, no gauge.

### Statistics is the machine — `docs/design/statistics.md`
Machine, Processes (live only while on screen; sorting and cutting are the
daemon's), Storage. Kill is SIGTERM only and refuses init, sway, the daemon and
the game (found by `SO_PEERCRED`). Screen time is time in MCShell.

### Advancements is the filesystem — `docs/design/advancements.md`
Vanilla's window to the pixel, grown not scaled; the tree is discovered a click
at a time, never cached. One button opens and shuts. File kinds are the
daemon's, icons the mod's. Twenty children per expansion; dotfiles hidden and
counted.

### Save and Quit is the power menu — `docs/design/power.md`
Lock, Sleep, Restart, Power Off; the last two confirm. The lock screen is
`session/lock.sh`, started by the compositor and never a child of the daemon;
it draws Minecraft's Direct Connection screen out of the client jar, with
hyprlock's field, and has four fallback routes that all lock. A logind delay
inhibitor saves the world before any shutdown.

### Notifications are advancement toasts — `docs/design/notifications.md`
The daemon owns `org.freedesktop.Notifications`; `session/overlay.py` draws on
a layer-shell surface above every window, takes no input, and draws in
software. Geometry out of `AdvancementToast`. gtk4-layer-shell must be
preloaded — getting that wrong opens an ordinary window, which happened.

### Accessibility is the shell's own settings — `docs/design/accessibility.md`
Clock, battery colour, volume-key noise, notifications and their sound, screen
time. Vanilla's screen stays one button away; its *Accessibility Guide* button
is never added. The sound is picked in the portal's file chooser, not typed.

### The volume popup is a boss bar — `docs/design/volume.md`
Drawn on the overlay, driven by `pactl subscribe` and nudged by
`session/volume.sh` for presses PipeWire reports nothing for. `volume.sh` runs
`wpctl` first and unconditionally — the rail.

### Controls makes bindings — `docs/design/controls.md`
Sway's binds can only be rebound; binds made here are the daemon's and can be
removed. Keys are `controls.…` (load-bearing). Commands are `sh`'s; a missing
program is a note, never a refusal.

### F2 is the desktop's screenshot key — `docs/design/screenshot.md`
`session/screenshot.sh`: the whole output to `~/Pictures/Screenshots` and the
clipboard, announced with a thumbnail toast.

### The clock — `docs/design/clock.md`
Top left, HUD text. `clock.py` formats with glibc's locale and the mod only
prints the string. No seconds; pushed on the minute.

### The boot — `docs/design/boot.md`
One picture over the whole login: Minecraft's world-generation screen on the
overlay, with a percentage estimated against the last boot and capped at 99
until `world_ready`. It must never appear over a working desktop (two
independent locks), takes no input, and times out at 90s. The client unit waits
for its first frame. A login with no network launches offline, decided before
Prism is asked. sway's GPU nag is silenced by environment variable, never by
flag. The doc also holds the measured login sequence and how the units, logs
and `start-session.sh` fit together.

### Give Feedback is the world picker — `docs/design/worlds.md`
Realms' world slots, by picture. A click marks the next start; *Restart into*
saves first and goes now. The choice is a file, `~/.config/mcshell/world`, so
the launcher reads it with the daemon dead. The hotbar follows you between
worlds; the inventory does not.

### Catalog browser — `docs/design/catalog.md`
`E` opens the real survival inventory; a creative-style tab opens the catalog.
Vanilla chrome to the pixel; tabs carry items, never words. Six tabs plus
Search, mapped in `catalog.py`. New apps appear without a restart.

### Command bar — `docs/design/command-bar.md`
Every plain chat line is a command; slash commands are untouched. Up to five
lines in chat, more in the panel; output streams. `&` detaches through sway;
`cd` and `clear` are builtins; `sudo` asks through askpass in a real window.
Not a terminal: no PTY.

### Window matching
Match on Sway's `app_id` (Wayland) / `window_class` (XWayland), **never on PID**.
Firefox and other multi-process apps fork, so the spawned PID does not own the window.

## Environment

Arch. Assume nothing is installed; check first.

```bash
# JDK
sudo pacman -S jdk21-openjdk

# Python — PEP 668 is enforced, system pip WILL refuse. Use uv or a venv.
uv venv && uv pip install i3ipc pyxdg dbus-next

# Compositor
sudo pacman -S sway foot     # foot is the fallback; $TERMINAL picks another
```

## Testing workflow

**Sway runs nested.** Never test by logging out of the daily-driver session.

```bash
session/start-nested.sh
```

This gives a full Sway instance in a window on the existing desktop, with its own IPC
socket. Not `sway -c session/sway.dev.conf` directly: neither sway config holds a
path to the checkout, and the script is what exports `$MCSHELL_ROOT` for them, the
way `start-session.sh` does for the real session. The daemon must be launched
**from inside** the nested session (via an `exec` line in `sway.dev.conf`) so it
inherits the nested `$SWAYSOCK` rather than the host's.

The daemon is testable with no Minecraft at all via the CLI harness:

```bash
$ mcsh '{"t":"catalog_query","text":"fire"}'
$ mcsh '{"t":"slot_assign","slot":1,"app":"firefox.desktop"}'
$ mcsh '{"t":"slot_activate","slot":1,"button":"right"}'   # spawns Firefox
```

Build and verify as much as possible through `mcsh` before writing Java. Real stack
traces beat Minecraft crash logs.

`daemon/tests/` does the same thing automatically, and CI runs it on every
push: each test starts a real daemon in a private home with no sway, no D-Bus
and ten programs on PATH, and talks to it over its socket. It cannot touch the
running session — that isolation was measured from the daemon's own log, and
it is the reason the suite may be run at any time. A change to a message's
behaviour should come with a test there.

```bash
daemon/.venv/bin/python -m pytest -q daemon/tests     # needs: uv pip install -e '.[test]'
```

The Fabric dev client (`./gradlew runClient`) and the real Prism instance are
**different installs**. Dev client for iteration; Prism instance for session testing.

### Instruments

`session/probes/` holds the two that answer questions nothing else can. They exist
because the cursor bug was invisible to Sway, to the daemon, and to the game's own
logs, and it stayed unfixed for as long as it was argued about rather than measured.

```bash
session/probes/pointer-grab.sh          # is any X client holding the pointer?
session/probes/clickprobe.py x11        # a window that counts what it receives
session/probes/clickprobe.py wayland    # the same window, as a native client
```

Open one probe of each kind. **They fail differently, and that difference is the
diagnosis**: an X grab is server-wide, so a stranded one takes the clicks of every
XWayland application and leaves native Wayland ones untouched. Motion rising while
clicks stay at zero means events reach the screen and the buttons go elsewhere.

`session/diagnose.sh` answers the wider question — what the shell can see, which
windows have an identity, what the units are doing. Reach for it first when the
session comes up wrong; reach for the probes when input is the thing misbehaving.

`mcshell check` (`session/check.py`) answers the one before it: is this
machine set up at all. Every dependency by tier — required, feature, optional —
with what its absence costs, checked by command or file and never by package
name, then the setup itself. It works from any session, and inside MCShell it
appends `diagnose.sh`. A bug report starts with its output. When code starts
depending on a new program, add it to `session/check.py` in the same commit.

## Mod implementation notes

- Unix sockets: `SocketChannel.open(UnixDomainSocketAddress.of(path))`. Java NIO has
  supported this since 16. No JNI, no dependencies.
- Socket runs on its own thread. **Never block the render thread.** Inbound state lands
  in an `AtomicReference<TaskbarState>` the renderer reads; outbound events go on a queue.
- Reconnect with backoff — the daemon will be restarted constantly during development.
- Icons: load via `NativeImage`, upload as `DynamicTexture`, cache keyed on path.
  Nearest-neighbour downscale to 16x16 so they read as Minecraft items.
- The overview is a `Screen` subclass — since M8 it holds only the command
  output panel. Opening a Screen releases MC's pointer grab
  automatically — this is how the cursor becomes free without touching input plumbing.
- **The mod must release the cursor when the game loses window focus, and the
  daemon must ask it to *before* focus moves.** Vanilla releases by pausing and
  the shell turns pausing off, so the release has to be put back by hand. It is
  not cosmetic: Minecraft runs under XWayland, and a client holding the pointer
  there holds it for the whole X server, so the game silently ate the button
  presses of every other XWayland application while still letting them see
  pointer motion.
  - The mod cannot notice this on its own. GLFW reports a lost focus only when
    another *X* client takes it, so focusing a native Wayland window left the
    game sure it was still focused. Sway knows, so the daemon says: `focus`.
  - The order is load-bearing. GLFW hands the grab back only while X still says
    the game is focused, so a release sent after Sway has moved focus is
    silently skipped and the grab is stranded — the camera stops, which reads
    as a fix, while every other X client goes on losing its clicks. The daemon
    waits for `focus_ack` before it focuses anything.
  - `MCShellClient.followWindowFocus` and `Daemon.yield_pointer`.
- The Fabric HUD render callback API moved around during the 1.21 line. Check the
  current API surface for 1.21.1 rather than assuming.

## World setup (Prism instance) — `docs/design/prism-instance.md`
Superflat void, world border 32, `keepInventory`, no mob spawning, no weather
or daylight cycle, `randomTickSpeed 0`. Sodium, Lithium, FerriteCore,
ModernFix. Render distance 2, 30fps cap, `-Xmx1G` over a 128M floor that gives
memory back, and `MALLOC_ARENA_MAX=2` from `launch.sh`.

## Milestones

Work one at a time. Do not skip ahead. A milestone is done when Nick has used
it, not when the build is green — that standard is the point.

- **M0–M8: done**, each signed off by Nick using it. M0–M7 are the prototype:
  daemon, mod transport, hotbar, catalog, command bar, settings bridge, the real
  session. M8 was polish, closed 2026-10-14. What each was, and the table of
  everything M8 changed: `docs/milestones.md`.
- **M9** — **Production: from one machine to anyone's. This is the current
  milestone.** The plan, its order, the license trade-offs and the distro tiers
  are in **`docs/m9.md`** — read it first. In short: decide the license and
  check the name against Mojang's guidelines; make the checkout portable;
  automate the Prism instance (`.mrpack`) and the template worlds; pass the
  second-machine test; publish the repository; ship **`mcshell-git` on the AUR
  first**, and only then tier 2 and 3 distros. No new features in M9.

### Known gaps, deliberately left — `docs/design/known-gaps.md`
Not a to-do list; picking one up is Nick's call. A window sway focuses by itself
can strand the pointer grab; eight apps have no icon; media keys cannot be
tested nested; `session.log` collects applications' stderr; single-instance
apps launched from a nested session open on the host (Prism among them).

## Safety rails (M7, but design for them now)

Bound in Sway config so they work even if the daemon and Minecraft are both dead.
All of these are in `session/sway.conf`; `docs/troubleshooting.md` has the full table:

```
bindsym $mod+Shift+Return exec sh -c 'command -v "${TERMINAL%% *}" >/dev/null && exec $TERMINAL || exec foot'
bindsym $mod+Shift+m exec systemctl --user restart mcshell-client
bindsym $mod+Shift+d exec systemctl --user restart mcshelld
```

Closing a window from the keyboard is a rail too, and needed a script rather
than a binding: Sway bindings fire whatever is focused and the compositor sees
the key before the application does, so a bare `Alt+F4` would close Minecraft
when Minecraft is what you are looking at. `session/close-focused.sh` refuses
on the backdrop.

The media and brightness keys belong here too, for the same reason. Brightness
and the player keys are bound to `brightnessctl` and `playerctl` directly. The
volume keys go through `session/volume.sh`, which is still the same rail: it
runs `wpctl` first and unconditionally and only then tells the daemon a key was
pressed, so a dead daemon costs the popup and never the volume. One file behind
them for the reason `lock.sh` and `screenshot.sh` are one file — the Controls
page rebinds these by rewriting `bindsym`. The settings pages follow along
regardless, because the daemon watches PipeWire and polls the backlight.

Daemon runs as a systemd user unit with `Restart=on-failure`.

**Lock screen and polkit prompts stay outside Minecraft.** hyprlock (falling
back to swaylock) plus a normal polkit agent. Never route credentials through a
game client.

## Open questions

Not blocking. Ask before implementing.

*None open.* Template worlds were the last; settled in M9, below.

### Resolved — `docs/design/decisions.md`
Each with its reasons and what was rejected:
template worlds (repo, no player, Tutorial World default); the boot screen;
how the game lets go of the mouse (the daemon asks, and waits for
`focus_ack`); bare Super does not misfire; GDM over greetd; `pactl` over
`wpctl`; activating an app on another workspace switches to it; every chat line
is a command; `sudo` via askpass; output streams; `E` is not an app drawer; the
hotbar can be real items.

## Working style

- Scope each session to one milestone. Do not attempt the whole project.
- **Before changing a feature, read its doc in `docs/design/`.** This file holds
  the rules; those hold the reasons. When a change alters a rule, update the
  doc in the same commit, and the summary here if the summary stops being true.
- **Testing walkthroughs live in `docs/testing/`, one book per milestone:
  `m0-m7.md` and `m8.md` are closed. Write new ones in `m9.md`**, the current
  book. A book that passed is one nobody should have to read past to find the
  current part. They are the maintainer's sign-off record, not contributor
  docs.
  - **What people need when it comes up wrong is `docs/troubleshooting.md`**:
    the login, the keys that always work, `diagnose`, the symptom table. It
    was distilled from the M7 walkthrough and checked against the code on
    2026-10-24; keep it true when a rail, a log or a failure mode changes.
- **The daemon is testable with no Minecraft at all.** `daemon/tools/mcsh`
  drives every page and every message; `mcsh <page>` prints one. Reach for it
  before the game, and for anything in `session/` reach for the previews —
  `overlay.py --preview` and `--preview-osd`, `lockscreen.py` — which render to
  a PNG so a surface can be checked by looking at it rather than by
  screenshotting the compositor.
- Prefer many small commits. This project will break often and walking back matters.
- When adding a protocol message, update `protocol.py` and `docs/protocol.md` together.
- If a task requires a decision not covered here, ask rather than assume — the design
  has a lot of deliberate constraints that look arbitrary out of context.

### Measure. Do not reason about someone else's code.

This cost most of a session and it is the one habit worth carrying forward.

- **Build an instrument before building a fix.** Three consecutive fixes for the
  cursor bug were derived from what the X, GLFW and Sway documentation say ought
  to happen. All three failed. The fourth came from a window that counted its own
  clicks and a probe that asked the X server directly who held the pointer, and it
  landed first time. Reasoning about code you cannot see is a hypothesis. Say so.
- **Verify in the configuration that is failing.** The third of those fixes was
  confirmed 3-of-3 against an XWayland test window — the one case that already
  worked, while every native Wayland app stayed broken. A green test in the wrong
  configuration is worse than no test: it spends Nick's trust and sends him back
  to a bug you told him was fixed.
- **Run a control.** "0 of 3 clicks with Minecraft running, 3 of 3 with it
  stopped" is a finding. "0 of 3 clicks" on its own is an instrument you have not
  checked. Several dead ends here were the harness, not the bug.
- **Nick's observations are data, and usually the best data available.** "The
  camera is still moving behind the window" and "I resized that window myself"
  each redirected the investigation faster than anything measured. When he says
  it did not work, it did not work — do not re-explain why it should have.
- **Say which kind of claim you are making.** *Measured*, *should work* and
  *not tested* are three different things and only one of them is finished.
