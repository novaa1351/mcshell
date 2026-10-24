# Testing MCShell

Everything here runs in a **nested Sway** on the existing desktop. Nothing logs you
out, and nothing touches the host session.

```bash
sway -c session/sway.dev.conf
```

That one command starts three things: the nested compositor, `mcshelld`, and the
Fabric dev client. Wait for it — the first start compiles the mod, and a cold gradle
daemon adds to that. Up to a couple of minutes of empty screen is normal; after that
it is 20–30 seconds.

$mod is **Alt**. $hatch is **Ctrl+Alt** (the host's Hyprland eats Alt+Shift, so the
escape hatches moved).

| Key | Does |
|---|---|
| `$mod+o` | Raise Minecraft **and** open the overview — the dev stand-in for Super |
| `` ` `` *(in Minecraft)* | Open/close the overview |
| `Escape` *(in the overview)* | Close it |
| `$mod+Return` | kitty |
| `$hatch+Return` | foot — the escape hatch, works when everything else is dead |
| `$hatch+j` | Follow the Minecraft client log |
| `$hatch+l` | Follow the daemon log |
| `$hatch+w` | Dump the live window list |
| `$hatch+m` | Restart the Minecraft client |
| `$hatch+d` | Restart the daemon |
| `$hatch+e` | Exit the nested session |
| `$mod+left-drag` | Move a window |
| `$mod+right-drag` | Resize a window |
| `$mod+f` | Put the focused window back to full screen |

## The M3 walkthrough

The overview only opens **in a world** — on the title screen there is nothing to
overlay, so the key does nothing. Enter a world first.

### 1. The overview opens

Press `` ` ``. Expect a dark panel across the middle: the title `MCShell`, nine
cells numbered 1–9, and a hint line.

If the title reads **`daemon not connected`** in red, the mod is running and the
daemon is not. That distinction is the whole point of the banner — see below.

### 2. A slot has an app in it

```bash
daemon/tools/mcsh '{"t":"slot_assign","slot":1,"app":"kitty.desktop"}'
daemon/tools/mcsh taskbar
```

`taskbar` prints what the daemon believes. Check it against what you see:

```
SLOT  APP            STATE    WINS  ICON
1     kitty.desktop  stopped  0     /kitty.png
```

Reopen the overview. Slot 1 shows a **plain icon** — assigned, not running.

**This is the check that separates a daemon fault from a rendering fault.** If
`mcsh taskbar` is wrong, the bug is in Python. If `mcsh taskbar` is right and the
screen disagrees, the bug is in Java.

### 3. Activating a slot

Right-click slot 1, or press `1`. Expect: the overview closes, kitty opens, and it
takes focus above Minecraft.

In the nested session Sway **tiles** kitty beside Minecraft rather than covering it.
That is correct for now — the fullscreen-behind-everything layout of Fork A is M7
session plumbing, not M3.

### 4. Running, focused, window count

With kitty open, press `$mod+o`. Minecraft comes forward and the overview opens in
one key. Slot 1 now shows:

- a **purple enchantment glint** — running
- a **white border** — focused
- **no number** — one window

Open a second kitty (`$mod+Return`) and press `$mod+o` again. Slot 1 shows a **`2`**
at the bottom-right of the icon.

`mcsh taskbar` should read `running *focused*  2` at the same moment.

### 5. Cycling and closing

All three of these anchor on **the window of that app you were last in**, not on
whatever Sway reports as focused — while the overview is open, the focused window is
always Minecraft.

With three kitty windows open, and returning to the overview via `$mod+o` each time:

- **Right-click** slot 1 → back to the window you were last using.
- **Left-click** slot 1 repeatedly → each click moves to the next window, wrapping
  after the last one. The overview closes on each click, so it is `$mod+o`,
  left-click, `$mod+o`, left-click.
- **Shift+middle-click** slot 1 → closes the window you were last in, and the overview
  stays open so you can close several. The count on the icon drops each time.

Left-click on an app that is *not* running does nothing and the daemon logs
`<app> is not running` — cycling zero windows has no meaning, and launching there
would make left and right identical.

## The M4 walkthrough

### 1. The inventory still works

Press `E`. You get the **real survival inventory** — 27 empty slots, the crafting
grid, your player model. That is deliberate; the shell is a survival world.

Two things are different. Your assigned apps are drawn on the inventory's own
hotbar row, and there is a **chest button just off the panel's bottom-right
corner**. Toggle the recipe book and the button follows the panel.

### 2. The catalog

Click the chest. Expect seven tabs — Games, Web, Work, Media, Tech, Misc, Find —
a grid of app icons, and your nine slots along the bottom.

Cross-check any tab against the daemon:

```bash
daemon/tools/mcsh '{"t":"catalog_query","tab":"Tech"}' -r | head -c 300
```

Same rule as always: if `mcsh` is wrong the bug is in Python, if `mcsh` is right
and the screen disagrees the bug is in Java.

### 3. Assigning an app

Creative-inventory style, not an HTML5 drag — you are not holding the button down.

- **Click an app** → it lifts onto the cursor and follows it, across tabs and
  scrolling.
- **Click a slot** → it lands there. `mcsh taskbar` shows it immediately, and the
  slot row and the HUD hotbar both update.
- **Number keys 1-9** do the same as clicking that slot, while carrying.
- **Click an app out of a slot, then click a different slot** → it moves.
- **Click an app out of a slot, then click outside the panel** → the slot empties.
- **Close the screen while carrying** → nothing changes. The source slot is not
  emptied until the app lands somewhere else or is deliberately thrown away, so
  a mis-pressed Escape cannot lose an assignment.

### 4. Search

The **Find** tab replaces the title with a text box and queries as you type,
across every tab. `term` finds terminals, `brow` finds browsers — it matches
`GenericName` and `Keywords`, not just names.

Scroll the grid with the mouse wheel; a scrollbar appears when a tab has more
apps than fit.

## The M5 walkthrough

The command bar is Minecraft's chat. Press `T`, type a shell command, press
Enter. Nothing you type goes to the world any more — every plain line is a
command. `/gamerule` and the other slash commands are untouched.

Before touching Minecraft, check the daemon answers on its own. Everything
below works from a terminal, and it is the faster loop:

```bash
daemon/tools/mcsh sh git status
daemon/tools/mcsh sh seq 20
```

`mcsh sh` takes the rest of the line verbatim, so flags need no quoting:
`mcsh sh git rev-parse --abbrev-ref HEAD` works. An argument that itself
contains spaces does need quoting inside one word: `mcsh sh 'grep "a b" f'`.
The same rule as always applies: **if `mcsh sh` is wrong the bug is in Python;
if `mcsh sh` is right and Minecraft disagrees, the bug is in Java.**

### 1. A short command goes to chat

In a world, press `T`, type `whoami`, Enter.

Chat shows the command echoed in grey, then its output in white:

```
$ whoami
nick
```

The echo is the mod's, not Minecraft's — the message was cancelled, so nothing
else would confirm the line was taken. **Up-arrow in chat still recalls what you
typed**, because Minecraft records its own history before the message is sent.

### 2. Five lines is the border

```
seq 5      → five lines in chat
seq 6      → chat says "… output in the overview", and the overview opens
```

Six is the first count that opens the panel. The panel appears above the slot
row, with the working directory in its top-left corner.

**Cross-check when the border looks wrong.** `daemon/tools/mcsh sh seq 6` prints
six lines in the terminal. If it does and chat still shows all six, the rule is
misapplied in `CommandBar`, not in the daemon.

### 3. Output arrives while the command runs

```
for i in 1 2 3 4 5 6 7 8; do echo "tick $i"; sleep 1; done
```

The panel opens on the sixth line and the rest land one a second, live. It does
not sit blank for eight seconds and then fill.

Scroll the panel with the wheel. Scrolled up, arriving lines do **not** drag
what you are reading off the top; at the bottom, it follows the output. A
scrollbar appears on the right once there is more than fits.

The panel is a transcript, not a single command's output: reopen the overview
with `` ` `` and everything run this session is still there, up to 500 lines.

### 4. Failures say so

```
ls /nowhere    → the error in red, then [exit 2] in yellow
```

The error line comes first and the verdict after it. Both are in chat even when
the output went to the panel.

### 5. `cd` sticks

```
cd dev/mcshell     → prints the new path
pwd                → /home/you/dev/mcshell
git status         → runs there, not in $HOME
cd -               → back to where you were
```

`cd` is the daemon's own builtin, not bash's. The path in the panel header is
the directory the *next* command will run in. `cd build && make` is not the
builtin — written that way, bash gets it and the directory change dies with the
command, exactly as it would in a terminal.

### 6. `&` launches a window

```
foot &         → a terminal opens; chat says "launched foot" and [launched]
```

That is the answer for anything without a `.desktop` file. It goes to Sway's
`exec`, so the app belongs to the compositor and survives `$hatch+d`. It
inherits the bar's working directory, so `swayimg shot.png` finds the file the
bar is looking at.

Without the `&`, a GUI program is captured instead, prints nothing, and is
killed at 60 seconds — which is the timeout doing its job, not a bug.

### 7. `sudo` asks in a window

```
sudo id        → a password prompt appears as a real window, above Minecraft
               → uid=0(root) ... in chat
sudo id        → again within a few minutes: no prompt, sudo's timestamp is
                 still good
```

The prompt is `rofi` on this machine — whatever `daemon/tools/mcshell-askpass`
finds first. It is a compositor window on purpose: a password typed into chat
would be drawn on screen and kept in the transcript, and CLAUDE.md keeps
credentials out of the game client.

Press Escape at the prompt and sudo says `no password was provided`, exit 1.

Two things that are *not* bugs:

- **`sudo pacman -Syu` still fails**, at "Proceed with installation? [Y/n]".
  Askpass answers for the password, not for the program's own questions, and
  stdin is `/dev/null`. Use `--noconfirm`, or `foot -e sudo pacman -Syu &`.
- **The 60-second timeout runs while the prompt is open.** Leave the prompt
  sitting there and the command is killed under it.

### 8. The edges

| Type this | Expect |
|---|---|
| `sleep 90` | killed at 60s, `[exit -15, timed out after 60s]` |
| `seq 3000` | 2000 lines, then `[output truncated at 2000 lines]` |
| `cat` | returns at once — stdin is `/dev/null`, so it sees EOF |
| `vim` | two "not a terminal" warnings, then it hangs until the timeout kills it. Use `vim &`, or a slot |
| a second command while one runs | `command N is still running`, in the daemon log |

## The M6 walkthrough — Sound

Options > Sound is now two screens, and **the machine's is the one that
opens**. A **Minecraft Sound…** button in its bottom-left crosses to
Minecraft's own, which is unchanged and has a **System Sound…** button in the
same corner to come back. Minecraft's sliders still control Minecraft. These
control PipeWire.

Check the daemon first, from a terminal:

```bash
daemon/tools/mcsh audio                       # the whole page as a table
daemon/tools/mcsh set audio.sink..volume 0.4  # 40%
daemon/tools/mcsh set audio.sink..mute true
```

The value is read as JSON, so `0.4` is a number and `true` is a boolean;
anything that is not valid JSON is taken as a string, which is what device
names and card profiles are. **If `mcsh audio` is wrong the bug is in Python;
if `mcsh audio` is right and Minecraft disagrees, the bug is in Java.**

The double dot in `audio.sink..volume` is not a typo. Keys are
`audio.<domain>.<id>.<field>`, and an empty id means "whichever is default" —
`audio.stream.6793.volume` names one application's stream the same way.

### 1. Crossing over

Escape > Options > Sound. The machine's page opens straight away.

It shows four groups: Output, Input, Applications, Devices. Every word on it
came from the daemon — the mod does not know what a sink is. The world behind
is dimmed and the list sits between two separator bars, the same furniture
every vanilla options screen has.

**Minecraft Sound…** crosses to Minecraft's own page; **System Sound…** in the
same corner comes back. Done goes up a level, to Options, the same as vanilla's
own Done — it is vanilla's Done, delegated to.

The crossing is a one-shot exemption from the redirect, so the failure to watch
for is a bounce: clicking **Minecraft Sound…** and landing straight back here.

### 2. The volume slider is the real volume

Drag Output > Volume. Release.

```
pactl get-sink-volume @DEFAULT_SINK@     → matches what the slider says
```

It reports on release, not while dragging: a message a pixel would be answered
with a fresh page each time and the handle would fight the mouse.

### 3. It follows changes it did not make

Leave the page open and change the volume from outside — the media keys on the
keyboard, or `pactl set-sink-volume @DEFAULT_SINK@ 20%` in a terminal.

The slider moves within a moment. That is `pactl subscribe`: the daemon is told,
rebuilds the page and pushes it. A change that alters nothing the page draws is
not pushed at all, so this is not a poll and does not run when nobody is looking.

### 4. Applications appear as they play

Start something that makes noise — a video in a browser. Under **Applications**
a row appears named after it, with its own volume and mute. Stop it and the row
goes away, replaced by "Nothing is playing".

Minecraft's own audio shows up here too, as `java`. Turning that one down is
not the same as Minecraft's master slider: this is the machine's mixer, that is
the game's.

### 5. Output device, and profiles

Output device cycles through the sinks — speakers, the three HDMI outputs, a
Bluetooth headset if one is connected. Each click switches immediately, because
that is what a vanilla cycling button does.

Two things to know rather than be surprised by:

- **Cycling walks through every device to get back.** With four sinks, picking
  the one before the current one means three clicks. Shift-click cycles the
  other way.
- **A card's profile list includes "Off".** Cycling onto it silences that card
  until you cycle past it. It is a real setting doing what it says, not a fault.

### 6. Edges

| Do this | Expect |
|---|---|
| `mcsh set audio.sink..volume '"loud"'` | `volume must be a number` |
| `mcsh set audio.sink..mute 0.5` | `mute must be true or false` |
| `mcsh set video.brightness 0.5` | `no page owns 'video.brightness'` — the page is not built yet |
| restart the daemon (`$hatch+d`) with the page open | it goes empty, then refills when the socket returns |
| unplug the audio device the page is showing | the page rebuilds around what is left |

## The M6 walkthrough — Display

Options > Video opens the machine's display settings; **Minecraft Video…**
bottom-left crosses to Minecraft's own.

With Sodium installed, "Minecraft's own" is Sodium's screen, not vanilla's —
Sodium replaces it, and for a while that took the System Display page with it,
because the lane only knew the vanilla class. It now knows both, matched by
class name so the mod still builds and runs without Sodium present. The
crossing behaves the same in both directions; the thing to look at is whether
the **System Display…** button in Sodium's bottom-left corner lands on top of
anything Sodium draws there. If it does, say so — it is a coordinate in
`SettingsIntegration`, not a design.

```bash
daemon/tools/mcsh video
daemon/tools/mcsh set video.backlight.intel_backlight.brightness 0.4
```

### 1. Brightness

Drag it. The panel changes as you drag-release, and

```
cat /sys/class/backlight/intel_backlight/brightness
```

agrees. Press the brightness keys on the keyboard with the page open and the
slider follows within about two seconds — that one is polled, not pushed,
because logind broadcasts nothing and inotify does not work on sysfs.

It refuses to go all the way to zero. A screen at zero cannot be turned back up
by someone who has to see the slider to do it.

Worth knowing: this works without Nick being in the `video` group and without a
udev rule, because brightnessctl here is built against logind and asks it. If it
ever stops working, that is the thing that changed.

### 2. Resolution, refresh, scale

Three cycling buttons for the monitor Sway is driving.

**Resolution is greyed on this laptop, and that is correct.** The panel
advertises 1920x1080 and nothing else — two modes, both that size, differing
only in refresh:

```bash
cat /sys/class/drm/card1-eDP-1/modes      # 1920x1080, twice
```

So there is one resolution to offer and the row has nothing to pick. Refresh is
the live control there: 144.15 Hz and 60.20 Hz. Nested, both are greyed —
sway's nested output has exactly one mode, the size of its window — so the
resolution and refresh rows can only really be tested on real hardware or
against a monitor with more than one mode.

**Changing a mode resizes the output Minecraft is fullscreen on.** The shell
visibly reshuffles. That is Sway doing as it was told, not a fault.

Refresh rate lists only the rates available at the resolution you are on, so
picking one never silently changes the resolution too. Picking a resolution
takes the fastest mode at that size, because the row below it is where refresh
is chosen.

### 3. Edges

| Do this | Expect |
|---|---|
| `mcsh set video.output.eDP-1.scale 40` | `scale must be between 0.1 and 6` |
| `mcsh set video.output.eDP-1.resolution 800x600` | `800x600 is not a mode this monitor has` |
| open the page with no Sway (`mcsh video` outside the session) | `Sway is not answering`, and brightness still works |

## The M6 walkthrough — Keybinds

Options > Controls opens the machine's keybindings: everything Sway has a
`bindsym` for, named by what it runs. **Minecraft Keys…** crosses to
Minecraft's own controls.

Sway is asked for its config rather than the file being found and its `include`
chain followed, so what you see is what Sway actually loaded.

```bash
daemon/tools/mcsh controls
daemon/tools/mcsh set binds.2b802168.key Mod4+t   # ids come from the listing
```

### 1. Rebinding

The page is laid out like Minecraft's own Key Binds: what the bind runs on the
left, its key in a column, **Reset** after it. Reset is greyed until the bind
has actually been changed, and it puts back whatever the Sway config says —
that is the only default that exists here.

Click the key. It reads `> key <` in yellow and waits. Press a combination.

The change takes effect **immediately** — the daemon tells Sway at runtime — and
is also written to `~/.config/sway/config.d/mcshell-binds.conf` so it survives a
reload. `sway.dev.conf` now includes that directory at the end.

Check both halves:

```bash
swaymsg -t get_config | grep -c bindsym       # unchanged; runtime binds are not in it
cat ~/.config/sway/config.d/mcshell-binds.conf
cat ~/.config/mcshell/binds.json
```

Escape, or a click anywhere, abandons a capture without binding anything.

### 2. The thing that will look like a bug

**A combination Sway already has bound cannot be captured.** Sway grabs it and
Minecraft never sees the keypress, so the row sits there waiting. This is Sway
working correctly, and it means rebinding onto a free combination is the path
that works. Binding onto a taken one is refused anyway, naming what has it.

While a row is armed, the line under the list says so. When the daemon refuses
a change, its reason appears there in red for a few seconds — a refusal used to
go to the client log only, which made a rejected rebind look exactly like a
rebind that did nothing.

Bare modifiers can be bound: press and release Super alone with nothing after it.

### 3. Edges

| Do this | Expect |
|---|---|
| bind onto a combination already in use | `Super+Return is already bound to exec kitty` |
| rebind, then `$hatch+c` to reload Sway | the new key still works — that is what the include is for |
| rebind, then restart the daemon | overrides are re-applied at startup |
| a bind inside a `mode` block | not listed; it only applies inside that mode |
| rebind, then Reset | back to the config's key, and the override disappears from `binds.json` |

## Media and brightness keys

The keyboard's own volume, mute and brightness keys are bound in
`sway.dev.conf`, not in the daemon. They have to work when mcshelld is dead,
which is the same reason the safety rails are bound there.

Press them with the Sound or Video page open: the sliders follow. Volume is
pushed the moment it changes, brightness within about two seconds.

Volume caps at 100% — `wpctl`'s `-l 1.0`, which `pactl` cannot do. Past that is
clipping, not loudness.

**The XF86 keys cannot be tested in the nested session.** Hyprland binds volume
itself — `~/.config/hypr/config/keybindings.conf` lines 52-55, through
swayosd-client — and `swayosd-libinput-backend` is running besides. The host
acts on the press and the nested Sway never sees it, so our binding cannot
fire. It is the same shape as Super belonging to the host, and it cannot arise
in the real session where Sway is the only compositor.

So dev gets stand-ins, the way Super gets `$mod+o`:

| Key | Does |
|---|---|
| `$hatch+=` / `$hatch+-` | volume up / down |
| `$hatch+0` | mute |
| `$hatch+]` / `$hatch+[` | brightness up / down |

To confirm the host is the one answering: press volume up, then
`pactl get-sink-volume @DEFAULT_SINK@`. If it moved, Hyprland handled it and
everything is working — one level up from where you were looking.

## Known broken

- **The window count does not draw on the hotbar HUD.** It draws correctly in the
  overview. Deliberately parked: the fix is to draw the digits ourselves rather than
  to keep fighting Minecraft's text batching.

- **Brave, Claude Desktop and other Electron apps open on the *host* desktop, not
  in the nested session.** They are single-instance: the copy you launch finds the
  lock in `~/.config` left by the copy already running under Hyprland, hands it the
  "open a window" request, and exits. The running instance then opens that window
  where *it* lives. Sway never sees it, so the slot correctly reports nothing.

  Not a daemon bug, and it cannot happen in the real session (M7) — there is no
  other session to hand off to. To test one of these apps in the nested session,
  quit it on the host first; the nested session then owns the instance.

- **Prism Launcher is one of those single-instance apps, and it matters more.**
  If the Prism GUI is open on the host desktop, `session/prism/launch.sh` inside
  a nested session hands the launch to it, and Minecraft opens on the *host*.
  The nested session sees no window at all while the game is plainly running —
  measured, not guessed. Quit Prism on the host before testing the real client
  nested. Cannot happen in the real session, for the usual reason.

- **Eight apps have no icon at all** and draw as a plain grey square: Rofi and
  the Avahi entries, mostly. Their `.desktop` files name an icon that is not
  installed. Hovering names them. A letter tile would read better than a blank.

## The M7 walkthrough — the layout

Fork A, finally: Minecraft fills the screen, apps sit above it, Super puts
Minecraft back on top. `session/layout.conf` is the whole of it — everything
floats, and focusing a floating window raises it.

Reload after pulling this: `$hatch+c`. If Minecraft is already running it will
not move on its own, because a `for_window` rule only fires when a window maps.
Press `$mod+o` (Super, in the real session) and it snaps to the whole screen.

### 1. Minecraft fills the screen

No border, no title bar, no gap at any edge. If there is a hairline of
background down one side, the pin missed; say so rather than nudging it.

### 2. An app opens *over* Minecraft, and covers it

Right-click a hotbar slot. The app fills the whole screen on top of Minecraft
— no game showing round the edges, and Minecraft does not shrink to make room.
Open a second app: it covers the first.

There is a brief flash at its own size first. The compositor floats it, the
daemon fills it a moment later, and that gap is visible. With `mcshelld` dead
the app stays at its own size, which is the same thing not finishing.

Then move it: **$mod + left-drag** anywhere on the window, or drag its
titlebar. **$mod + right-drag** resizes. A window you have moved stays where
you put it — the fill happens once, when the window appears, so opening
another app does not shove this one back to full screen.

### 2a. The sudo prompt is not an application

```
sudo -v
```

in the chat bar. The password prompt is a window like every other one here, so
this is checking that it was *spared* the fill: it should come up small, in the
middle, not filling the screen. If it arrives full-screen, its app_id is
missing from `KEEP_OWN_SIZE` in `daemon/mcshelld/main.py` — `$hatch+w` prints
it.

### 3. Super buries them again

`$mod+o`. Minecraft comes to the front and covers both windows; they are still
running, and the hotbar still shows them with a glint and their window counts.
Right-click one of those slots and it comes back to the front.

### 4. The Video page does not leave Minecraft the wrong size

Options → Video, change the **scale** — resolution is greyed on this panel
(see the M6 Display walkthrough for why) and scale changes the output's shape
just as well. Minecraft still fills the screen afterwards. This is the daemon's
doing, not the config's: sway clamps floating windows into a new mode rather
than growing them, so `mcshelld` re-pins the backdrop whenever an output
changes shape.

Change it back and check again — both directions matter, and shrinking is the
one that used to leave a border.

### 5. Edges

- **Do not put Minecraft in its own fullscreen mode** (its video settings, or
  F11). That makes it a fullscreen *container*, and sway then draws nothing else
  on the workspace — apps would launch and be invisible. Windowed is correct;
  the layout fills the screen for you.
- Restarting the client re-pins the backdrop, so `$hatch+m` is a valid way out
  if the geometry ever looks wrong.
- With the daemon dead, everything above still works except step 4: the rules
  live in the compositor, and only the re-pin after a mode change is ours.

## The M7 walkthrough — the Prism instance

The real session runs a **Prism instance**, not the Fabric dev client. CLAUDE.md
keeps them separate deliberately, and this is the one that has to work at login.

`session/prism/` owns it:

| file | what it does |
|---|---|
| `setup.sh` | All of the below, idempotent. Run it whenever you are unsure what the instance is running. |
| `install-mod.sh` | Build the mod, clear the old jar, copy the new one in. **Run after every change to the Java side.** |
| `mods.tsv` | The pinned performance mods, each with the sha512 `setup.sh` verifies. |
| `launch.sh` | Start the client and join the shell world. `--offline` skips the Microsoft round trip. |
| `common.sh` | Where the instance is. Sourced, not run. |

The instance name and paths are overridable by environment —
`MCSHELL_INSTANCE_NAME`, `MCSHELL_INSTANCE`, `MCSHELL_WORLD` — so a second
instance can be built beside this one without editing anything.

`install-mod.sh` exists because of a failure mode with no symptom. The dev
client loads the mod straight out of `mod/build/libs`, so it is always current;
the Prism instance loads whatever jar was copied in last. Without this step a
fix appears to have silently not worked. The first run of it here replaced a
jar six days stale.

### Creating the instance and the world — once, by hand

Prism has no command line for creating an instance, and a world is a directory
of NBT that is far easier to make in the game than to synthesise. Both are
one-time jobs; the scripts assume they exist.

**The instance.** In Prism: Add Instance → Minecraft **1.21.1** → **Fabric**,
named **`MCShell`**. Do not launch it yet — `setup.sh` pins the JVM first.
(`-l/--launch` takes the instance *ID*, which is the directory name; created
this way the name and the ID are the same string.)

**The world.** Launch, Singleplayer → Create New World, named **`MCShell`** —
no spaces, because the folder name is what `launch.sh` passes to `--world`.
Game Mode Survival, Difficulty Peaceful, **Allow Cheats on**. World Type
**Superflat** → Customize → Presets → **The Void**. Then, in that order:

```
/time set noon
/gamerule doDaylightCycle false
/gamerule doWeatherCycle false
/gamerule doMobSpawning false
/gamerule randomTickSpeed 0
/gamerule keepInventory true
/worldborder set 32
```

The first two are ordered, not arbitrary: freezing the daylight cycle freezes
whatever time it currently is, so a shell built in the wrong order is a
permanently dim one. Then Esc → **Save and Quit**, so `level.dat` is written.

```bash
ls ~/.local/share/PrismLauncher/instances/MCShell/minecraft/saves/   # -> MCShell
```

The Void preset drops you on a small stone platform. If you spawn falling,
`keepInventory` is already on — `/gamemode creative`, fly back up,
`/gamemode survival`. There is nothing under the platform.

### 1. Setup is idempotent

```bash
./session/prism/setup.sh
```

Run it twice. The second run prints no `fetching` lines — a mod already in
place with the right sha512 is left alone — and ends at `instance ready`. If it
warns about a missing world, the world name does not match `MCSHELL_WORLD`.

A `sha512 mismatch` is a real failure and stops the run. It means the download
was truncated, redirected or replaced; it is not something to retry past.

### 2. The nested test

`session/sway.dev.conf` chooses between the two clients near the top:

```
set $client $repo/session/run-client.sh
# set $client $repo/session/prism/launch.sh
```

Swap which line is commented, then start the nested session as usual. **Quit
the Prism GUI on the host first** — see Known broken; otherwise the game opens
on your real desktop and the nested session stays empty.

### 3. What to check in-game

- **It joins the world directly.** No title screen, no world list.
- **The backdrop fills the screen** and behaves exactly as it does under the dev
  client — the layout walkthrough above applies unchanged. The real client
  reports window class `Minecraft* 1.21.1` under XWayland, which is what
  `layout.conf` matches on.
- **The hotbar is there**, which means the mod loaded and reached the daemon.
  In the instance log (`minecraft/logs/latest.log`) that reads as
  `mcshell client ready; daemon socket /run/user/1000/mcshell.sock`.
- **Clicking a window does not pause the game.** `pauseOnLostFocus` is off. If
  the pause menu appears behind every window you open, `options.txt` was
  rewritten by a later in-game change; re-run `setup.sh`.
- **No Prism console window.** It is configured to appear only on failure.

### 4. The offline escape hatch

```bash
./session/prism/launch.sh --offline
```

Should reach the world with no Microsoft round trip, as `Player` rather than
your profile — a different UUID, so a different player entity in the same
world. Worth exercising once now rather than on the day a stale token is the
only thing between you and a desktop.

### 5. Edges

- **Do not add mods through the Prism GUI** and expect them to survive. Anything
  `setup.sh` installed is tracked in `minecraft/mods/.mcshell-managed` and
  removed when it leaves `mods.tsv`; anything you added yourself is left alone,
  but is also not reproducible. Pin it in `mods.tsv` instead.
- **Bumping a mod** is an edit to `mods.tsv` — take the new sha512 from
  Modrinth's API, not from the file you just downloaded, which proves only that
  the file is the file.
- **`options.txt` is a default, not a lock.** Minecraft rewrites it wholesale on
  exit, so an in-game change sticks until `setup.sh` runs again.
- The instance is pinned to `/usr/lib/jvm/java-21-openjdk/bin/java` on the
  instance itself, not left to Prism's global setting. This machine's default
  `java` is 26, which will not run 1.21.1 at all.

## The M7 walkthrough — the real session

The last piece, and the only one that can cost you a login rather than a
session pick. It is built so that it cannot: **MCShell is a second entry in
GDM's picker**, beside GNOME, Hyprland and Sway, all of which are untouched.

| file | what it is |
|---|---|
| `sway.conf` | The real session. Includes `layout.conf`, so what runs at login is byte for byte what was tested nested. |
| `start-session.sh` | What GDM runs. Sets `XDG_CURRENT_DESKTOP`, logs, and stops the units after sway exits. |
| `close-focused.sh` | Alt+F4, refusing on the backdrop. |
| `systemd/*.in` | The two units and the target, templated on the repo path. |
| `mcshell.desktop.in` | The GDM entry. |
| `install-session.sh` | Installs all of the above. Idempotent. |

**GDM, not greetd.** CLAUDE.md originally said greetd, and the milestone's
actual requirement is a *second* session entry with Hyprland still selectable.
GDM already does that, and replacing a working display manager is the one
change in this project that could cost a login instead of a session pick.

### 0. Install it

```bash
./session/install-session.sh
```

Checks its prerequisites first and names the missing package rather than
failing later. Writes three unit files under `~/.config/systemd/user/`, then
asks for sudo once, for `/usr/share/wayland-sessions/mcshell.desktop` — GDM
reads that directory and nothing under `$HOME`, which is the only reason root
is involved. Re-run it after moving the checkout; everything is templated on
the repo path.

### 1. The first login

Log out. At GDM: your name, then the **gear icon**, then **MCShell**.

Expect a blue screen for a few seconds — that is `swaybg`, and it exists so a
slow start does not look like a dead one — then Minecraft, full screen, already
in the shell world, hotbar drawn.

**If it fails you land back at the GDM login screen** with every session still
in the picker, and GDM's remembered default is the last session that *worked*,
so a failed MCShell login does not become your new default. Pick Hyprland and
you are back to normal. The reason will be in
`~/.local/state/mcshell/session.log`, which is truncated per login so what you
open is this attempt and not a year of them.

If it hangs rather than exits, **Ctrl+Alt+F3** is a text console. That path
involves none of this code.

### 1a. When it comes up wrong

```bash
./session/diagnose.sh
```

From a terminal inside the session — `Super+Shift+Return` opens one. It prints
what the shell can actually see, in the order the questions have cost time:
which compositor, what identity each window has, whether the units are alive,
what the daemon sees, and what environment the units were given.

The line to read first is **`app_id` / `class` for Minecraft**. It must be
`class='Minecraft* 1.21.1'` with `shell=xwayland`. If it shows no identity at
all, `DISPLAY` was missing when the client started: Minecraft chooses its
windowing backend at startup and GLFW falls back to Wayland with no DISPLAY,
and that client sets no `app_id` and has no `window_class`. Nothing in the
shell can match a window with no identity — `layout.conf` cannot pin it and the
daemon skips it as unaddressable — so Minecraft floats at 854x480 in the middle
of the screen and the shell cannot see its own backdrop. `sway.conf` imports
DISPLAY for exactly this reason; `launch.sh` warns into the journal if it is
missing anyway.

### 2. The keys that must work before anything else

These are the escape hatches, and they are compositor bindings precisely so
they work with the daemon and Minecraft both dead. Try them early.

| key | what |
|---|---|
| `Super+Shift+Return` | a `foot` terminal |
| `Super+Shift+d` | restart the daemon |
| `Super+Shift+m` | restart the Minecraft client |
| `Super+Shift+j` | tail both units' logs |
| `Super+Shift+c` | reload sway's config |
| `Super+Shift+l` | lock the screen |
| `Super+Shift+e` | log out, after a confirmation |

`Super+Shift+m` is the way back if you ever quit Minecraft from its own menu.
Quitting is an exit 0 and deliberate, so the unit does not restart it — only a
crash restarts.

### 3. Super, and the thing to watch for

`Super` on its own raises Minecraft and opens the overview, which is CLAUDE.md's
display model. A bare modifier can only be bound on *release*, because on press
sway cannot yet know whether you meant Super or Super+something.

**So this is the first thing to test, and the most likely thing to be wrong.**
Do these, in order, and watch whether the overview opens when it should not:

1. `Super`+drag a window to move it. Release.
2. `Super`+right-drag to resize. Release.
3. `Super+f` to put it back to full screen.

If the overview opens after any of those, sway is firing the release binding
even though the modifier was used in a combination. Say so — the answer is
either a guard in `raise-mc.sh` or dropping the bare binding. **`Super+o` does
the identical thing and cannot misfire**, so the shell is usable either way
while that is settled.

### 3a. Right-click, on a touchpad

**Right-click is what launches an app.** Left-click only focuses and cycles the
windows of one already running, so left-clicking a stopped app does nothing at
all — correctly, and indistinguishably from a broken shell.

This laptop's touchpad has one physical button under the whole surface and
advertises a right button it does not have; libinput says so on every start
(`kernel bug: clickpad advertising right button`). `sway.conf` sets
`click_method clickfinger`, so **two fingers is right-click**, three is middle.
Tap-to-click is on.

If a slot still does nothing, check which button actually arrived:

```bash
journalctl --user -u mcshelld -n 20 | grep slot_activate
```

`"button":"left"` on a stopped app is the shell behaving correctly. The number
keys 1-9 always launch, whatever the pointer is doing.

### 3b. Opening a file, and the window that answers

Open a `.md` from a file manager. Whatever `.desktop` claims that type opens
it, and that application was never assigned to a slot — this is the path that
found three separate gaps, so check all three:

1. **It is on top and you can type into it.** The daemon focuses a new window
   as well as filling it, and focuses it first: focusing is what raises a
   floating window above the backdrop.
2. **You can click in it without doing anything else first**, and Minecraft is
   not still turning its camera under it. These are one thing. Minecraft holds
   the mouse while it is in the game, it runs under XWayland, and a client
   holding the pointer there holds it for the whole X server — so every other
   XWayland application kept receiving pointer motion and no button presses,
   which reads as a window you can type into and cannot click. Native Wayland
   applications were never affected, which is why this only ever showed up on
   things like OnlyOffice. The mod now releases the cursor whenever the game
   loses the compositor's focus. If it comes back, that is the first thing to
   check — `pauseOnLostFocus` is off by design, so vanilla's own release does
   not run.
3. **Its icon is on the hotbar**, in the first free slot, for as long as it is
   open. **This needs a free slot** — with all nine assigned there is nowhere
   to put it, and the daemon says so once per rebuild:
   `hotbar full; <app> is running with no slot to show it`.

### 4. Closing a window from the keyboard

`Alt+F4` on a focused application closes it. So does `Super+Shift+q`.

Then press either **while looking at Minecraft**. Nothing should happen. Sway
bindings fire whatever is focused and the compositor sees the key before the
application does, so an unguarded `Alt+F4` would close the desktop;
`close-focused.sh` refuses on the backdrop. Verified in a headless lab against
a window with Minecraft's `app_id`, but verify it here too — it is the one
binding whose failure mode is losing the shell.

Both use sway's `kill`, a polite close request rather than a signal: an editor
with unsaved work still gets to argue.

### 5. Media keys, for the first time for real

Volume, mute, brightness, play/pause/next/previous. These have never once been
testable — nested, Hyprland bound them itself and `swayosd-libinput-backend`
took the rest, so the host acted on every press and the nested sway never saw
one. This session has no host. The `$hatch` stand-ins are gone from this
config; the real keys are bound.

Open the Sound page and press a volume key: it should move on its own, because
the daemon watches PipeWire rather than polling.

### 6. Logging out leaves nothing behind

`Super+Shift+e`, confirm, and you are back at GDM.

```bash
systemctl --user is-active mcshelld mcshell-client   # both inactive
```

This matters more than it sounds. Minecraft holds the world's `session.lock`,
and a copy still running after a logout makes the *next* login fail with an
error about the lock rather than about the real cause. `start-session.sh` stops
the target after sway exits for exactly that reason, and the target stopping the
units was verified in a lab.

### 7. Getting back to your other desktops

Log out, gear icon, pick GNOME or Hyprland. Nothing about them changed — this
milestone added a file to `/usr/share/wayland-sessions/`, it did not modify a
display manager. The only shared state is
`~/.config/sway/config.d/mcshell-binds.conf`, which the Controls page writes and
which only sway sessions read.

## When something is wrong

| Symptom | Cause | Fix |
|---|---|---|
| Nested Sway comes up empty, no Minecraft | Client failed to start | `$hatch+j`, read the log. A build error also pops a terminal on the tail by itself. |
| A new window takes the keyboard but clicks do nothing (XWayland apps only) | Minecraft is still holding the pointer, and an X grab is server-wide | Fixed in the mod: it releases the cursor when the game loses focus. Reopening the app from the hotbar is the by-hand workaround |
| Minecraft small and centered, shell cannot see it | Client started without `DISPLAY`, so GLFW used Wayland and the window has no identity | `./session/diagnose.sh`; ensure `sway.conf`'s import line includes DISPLAY |
| Right-clicking a hotbar slot does nothing | Touchpad has no right button; clicks arrive as left, which does not launch | Two-finger click, or the number keys. `click_method clickfinger` is in `sway.conf` |
| MCShell missing from GDM's picker | Session entry not installed | `./session/install-session.sh` — it asks for sudo for that one file |
| MCShell login drops straight back to GDM | sway or the session script failed | `~/.local/state/mcshell/session.log`, from any other session |
| Blue screen, no Minecraft | Client unit failed | `Super+Shift+j`, or `journalctl --user -u mcshell-client -n 50` |
| Next login fails complaining about a lock | A Minecraft outlived the last logout | `systemctl --user stop mcshell-session.target`, then log in again |
| Overview opens after a `Super`+drag | Sway fires the release binding after a combination | Known, see the real-session walkthrough §3. Use `Super+o` meanwhile |
| Nested session empty, but Minecraft is plainly running somewhere | Prism was already open on the host and took the launch | Quit Prism on the host, relaunch |
| Prism client starts, but a fix you just made is missing | Stale jar in the instance | `./session/prism/install-mod.sh` |
| Fabric refuses to start: duplicate mod id | Two jars of the same mod in `minecraft/mods` | `./session/prism/setup.sh`, which retires what it installed before |
| Overview title says `daemon not connected` | Daemon died or never started | `$hatch+d`, then `$hatch+l` to watch it come back |
| `sudo` says `a terminal is required` | The daemon did not set `SUDO_ASKPASS` — `daemon/tools/mcshell-askpass` is missing or not executable | `chmod +x daemon/tools/mcshell-askpass` |
| `sudo` says `no password prompter installed` | None of the prompters the helper knows are installed | `pacman -S zenity`, or add yours to the list in the helper |
| System Sound page is empty | Daemon not connected, or pactl cannot reach PipeWire | `mcsh audio` from a terminal; if that is empty too the fault is below the daemon |
| No **System Sound…** button on Minecraft's Sound screen | The mod did not load, or `SettingsIntegration` never registered | `$hatch+j` and read the client log |
| `` ` `` does nothing | Not in a world, or the key is rebound | Enter a world. Options > Controls > MCShell to check the binding. |
| `$mod+o` opens the overview but does not raise Minecraft | Window match failed | `$hatch+w` — Minecraft should be there as class `Minecraft* 1.21.1`. If it shows an `app_id` instead, the client is running native Wayland and `session/raise-mc.sh` needs that criteria widened. |
| Slot is empty in the overview but `mcsh taskbar` shows an app | Icon failed to load | The cell falls back to a grey square. Check `icon_path` in `mcsh taskbar` exists. |
| Slot shows `stopped` while the app is plainly open | Window not matched | `$hatch+w` and compare `app_id` against the `.desktop` file's `StartupWMClass`/`Exec` |
| Left-click always lands on the same window, or close takes the wrong one | Focus history lost — the daemon was restarted since you last used the app | Focus any window of that app once; the order rebuilds from there |
| Client dies on start with `SessionLock$AlreadyLockedException` | An orphaned client still holds the world | `$hatch+m` — it kills the whole process group, which is what orphans it otherwise |
| `mcsh` says connection refused | No daemon | `$hatch+d` |
| A console app (vim, btop, yazi) shows stopped although its terminal is open | Terminal does not support an app-id flag | The daemon names those windows `mcshell.<app>` via `--app-id`/`--class`; only foot, footclient, kitty, alacritty and ghostty are wired up. `$hatch+w` will show `foot` instead. Add the terminal to `TERMINAL_APP_ID_FLAG` in `catalog.py`. |
| Clicks vanish and you cannot tell where they go | Unknown — stop guessing | `session/probes/clickprobe.py x11` and `session/probes/clickprobe.py wayland`, then `session/probes/pointer-grab.sh`. Motion rising while clicks stay at zero means the buttons are going elsewhere; X and Wayland clients failing differently means an X grab |
| An XWayland app takes keyboard but no clicks, and the Minecraft camera is frozen | The pointer grab was stranded — Sway focused a window before the daemon could ask the game to let go (see Known gaps) | Press Super to go back to Minecraft, close the overview so the game takes the mouse, then open the app from the hotbar. Confirm with `mcsh windows`; the daemon logs `focus: game=` on every change |
| An Electron app opens on the host desktop | Single-instance hand-off | See Known broken. Quit it on the host first. |
| Chat sends your line to the world instead of running it | The mod's chat hook never registered | `$hatch+j` — the client log should carry `mcshell client ready` at startup |
| A command prints nothing and chat shows only the echo | It really printed nothing, or it is still running | `$hatch+l`; the daemon logs every command and its exit code |
| `daemon not connected` when you press Enter in chat | Daemon died | `$hatch+d`. The command is not queued — it is refused, so nothing runs late |

Two logs, and both are worth reading before guessing:

```bash
tail -f $XDG_RUNTIME_DIR/mcshelld.log         # daemon:  every message in and out
tail -f $XDG_RUNTIME_DIR/mcshell-client.log   # gradle, then Minecraft's own stdout
```

The daemon log at `-v` prints every line it receives. If a click produced nothing,
look there first: a message that never arrives is a mod bug, and a message that
arrives and does nothing is a daemon bug.

## Without Minecraft at all

The daemon is fully drivable from the harness, and that is usually the faster loop:

```bash
daemon/tools/mcsh ping
daemon/tools/mcsh windows
daemon/tools/mcsh taskbar
daemon/tools/mcsh overview                      # opens the overview in a running client
daemon/tools/mcsh '{"t":"slot_activate","slot":1,"button":"right"}'
daemon/tools/mcsh sh git status                 # a command bar line
daemon/tools/mcsh audio                         # the Sound page
daemon/tools/mcsh set audio.sink..volume 0.4
```
