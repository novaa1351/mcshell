# Testing MCShell — M8 onward

`docs/testing.md` is the prototype's book: M0 through M7, the walkthroughs that
proved the shell worked at all. It stays as it is. **This file starts at M8**, so
you can check what changed without reading past everything that already passed.

Same rules as before. Everything here runs in a **nested Sway** on the existing
desktop; nothing logs you out and nothing touches the host session.

```bash
session/start-nested.sh      # was `sway -c session/sway.dev.conf`; see docs/testing3.md
```

The key table and escape hatches in `docs/testing.md` still apply — `$mod` is
**Alt**, `$hatch` is **Ctrl+Alt**. The one entry that has changed meaning:

| Key | Was | Now |
|---|---|---|
| `$mod+o` | Raise Minecraft **and** open the overview | Raise Minecraft. Nothing opens over it. |

The real session's `Super` changed the same way, and for the same reason.

**If a change seems not to have taken effect, check this first:**

```bash
session/diagnose.sh          # the "mod jar" section
```

It compares the installed jar against the last one built and, more usefully,
says whether the running client started *before* the jar was installed — which
is the case that reads as "my change did nothing" while the file on disk is
perfectly correct. It cost a full test round once. Only the Prism instance can
go stale; the dev client compiles from source every launch.

Before testing the real session rather than the dev client:

```bash
session/prism/install-mod.sh          # build + install, so you are not testing a stale jar
systemctl --user restart mcshelld     # the protocol gained three messages in M8
```

---

## The M8 walkthrough — the hotbar is real items

The one-line version of what changed: the nine hotbar slots hold actual
`ItemStack`s now, drawn by Minecraft, instead of icons painted over the vanilla
hotbar. Everything below follows from that.

### 1. The applications are items

Assign a few apps if the hotbar is empty (`E` → chest button → click an app →
click a slot). Then look at the hotbar.

Each assigned slot should hold an item showing that application's real icon.
**Hover one in the inventory** (`E`) and it should name itself — "Firefox", not
`firefox.desktop`. **Select one** and it should be in your hand, icon and all,
in both first and third person (`F5`).

*If the icon is missing in the hand but fine in the GUI*, that is the render
layer or the quad winding in `AppItemRenderer`, not the item — the GUI and the
world go through the same `getModel` hook, so the item itself is fine.

*If it names itself `firefox.desktop`*, the daemon's `name` field is not
arriving; check `journalctl --user -u mcshelld` and that the daemon was
restarted.

### 2. Running, count, launching

Open an application from its slot. Its item should pick up the **enchantment
glint** — the real one, not a drawn approximation. Open a second window of the
same app and the stack should read **2**.

In the moment between the launch and the window appearing, the item should be
**faded**. It is faded in the inventory and in your hand too, which the old
overlay could not do.

The window count is a real stack size now, so M2's "the count does not draw on
the HUD" gap is gone rather than fixed. If you see no number on a stack of two,
that is a new bug, not the old one.

### 3. Real items and applications share the inventory

Give yourself something — `/give @s oak_log 5` — and put it in the hotbar.

* Wood and applications should coexist, nine slots between them.
* Picking up items should **never** land wood in a slot holding an application.
  Vanilla does this for us: a slot with an application in it is neither empty
  nor stackable-with, so its pickup search skips it.
* The 27 storage slots hold whatever you put in them, like any survival world.

### 4. An application stack is atomic

With an application of two or more windows:

| Gesture | Expected |
|---|---|
| Right-click the stack in the inventory | **Nothing.** No split. |
| Drag-distribute across slots with right-drag | **Nothing.** |
| Double-click it | **Nothing.** No gather. |
| `Q` over the slot | **Nothing.** |
| `Q` holding it in the world | **Nothing.** |
| Left-click to pick the whole stack up | Works. |
| Shift-click it into storage | Works — and unassigns the slot. |

Then do all of the same to a stack of wood. **Every one should behave
normally.** If wood has stopped splitting, the rule in `AppClicks` is matching
too widely.

### 5. Rearranging

* **Drag an application from slot 1 to slot 3.** It should settle in 3 and stay
  there. The daemon is told after the fact and answers with a taskbar, so a
  refusal looks like it snapping back — `journalctl --user -u mcshelld -f` says
  why.
* **Drag one into the 27.** The slot unassigns and the item disappears on the
  next push.
* **Swap two applications** with a number key. Both assignments follow.

### 6. The thing that will look like a bug

Drag out an application that is running but was **never assigned** — one that
borrowed a slot because it was open. It comes straight back.

That is correct and long-standing: a transient slot exists so a running
application always has somewhere to say so. There is no assignment to remove,
so removing it removes nothing. Moving one to a different slot *does* stick,
because putting it somewhere deliberately is the choice a transient lacks.

### 7. Your things are left alone

Fill hotbar slot 1 with wood, leave 2–9 empty, and open an application that is
not assigned to any slot.

It should take an **empty** slot, not slot 1. The mod tells the daemon which
slots hold ordinary items and the daemon sorts empty ones first. Only with all
nine holding something does it disturb one — moving that item into storage, or
dropping it at your feet when all 36 slots are full.

### 8. Holding an application focuses it

Focus an application (right-click its slot, or click its window). The hotbar
selection should move to that application: it is what you are holding.

**It must never stop you scrolling.** Play the game with an application merely
open and the selection is yours; scroll all nine slots freely. The write only
happens when an application *gains* focus, which is a moment when the keyboard
belongs to that application anyway.

---

## The M8 walkthrough — the world is the hotbar

The overview's nine-slot row is gone. The bindings live on the item.

### 1. The four gestures

Hold an application and, **looking at the world**:

| Gesture | Expected |
|---|---|
| Right-click | Focus it, or launch it if it is not running |
| Shift+right-click | Launch another window, running or not |
| Left-click | Focus it, then cycle its windows |
| Shift+middle-click | Close a window — politely, not a kill |

Each should work whether you are pointing at the stone platform, at the void,
or at nothing in particular. They go in at `MinecraftClient` rather than at the
item, precisely so that pointing somewhere different does not change what a
click means.

### 2. Held buttons

**Hold right-click down.** Exactly one thing should happen — one focus, or one
launch. If holding shift+right-click opens a stream of windows, the
release-before-it-counts-again guard in `AppGestures` is not working.

### 3. What you give up

**You cannot mine while holding an application.** Left-click means cycle now,
and the two want the same button. Switch to a pickaxe and mining works
normally. This is deliberate — the world is a platform over a void.

### 4. The overview is a terminal panel

`` ` `` still opens it. It should now contain **only** the output panel: title,
working directory, scrolling transcript. No slot row.

* Run a command with more than five lines of output. It opens by itself and
  fills live.
* Scroll it. Scroll up mid-command and it should hold position while output
  arrives underneath; at the bottom it should follow.
* Open it having run nothing and it should say so rather than drawing an empty
  box.

### 5. Super does not cover the hotbar

From an application, press `$mod+o` (`Super` in the real session). Minecraft
raises and **nothing opens over it**. The hotbar is right there, so a panel on
top of it would hide the thing you pressed the key to get back to.

---

## The M8 walkthrough — the catalog looks like Minecraft

### 1. The chrome

`E`, then the chest tab. The panel should be vanilla's creative inventory
texture — light grey, real slot wells, a real scrollbar — not a dark box. Hover
a slot and you should get vanilla's white slot highlight.

Compare it side by side with `/gamemode creative` and the real creative screen.
The panel, the slot grid and the scrollbar should line up exactly; the geometry
is copied from `CreativeInventoryScreen`, not approximated.

### 2. The tabs are items

Seven tabs along the top, each an item, no words:

| Tab | Item | Why |
|---|---|---|
| Games | Diamond sword | what the game calls combat |
| Browsing | Compass | finding your way |
| Productivity | Crafting table | making things |
| Media | Jukebox | playing things |
| Tech | Redstone | the game's machinery |
| Misc | Barrel | everything else |
| Search | Spyglass | looking for one thing |

**Hover each one — it must name itself.** That tooltip is what makes an
unlabelled row learnable; without it the icons are a guessing game.

The selected tab should sit *in front* of the panel edge and the others *behind*
it, which is what makes them read as tabs rather than as buttons in a row.

### 3. The chest tab

The catalog opener should be a creative tab tucked under the **top-left** edge
of the survival inventory, not a button floating off the corner.

* It should look tucked *under* the panel, overlapping it by a few pixels.
* **Toggle the recipe book.** The panel slides sideways and the tab must go with
  it — it is positioned every frame for exactly this.
* Hovering it should say "Applications".

### 4. The scrollbar

Open the **Search** tab and leave the box empty, so every application is listed
and the list overflows.

* The wheel scrolls it, a row a notch, as before.
* **Press and hold left-click on the scroller and drag.** The list should follow
  the cursor, the scroller should stay under it, and it should keep following
  even when you drag sideways off the bar — vanilla only lets go on the button
  release.
* Clicking anywhere on the *track* should jump the scroller there.
* On a tab with five rows or fewer the scroller draws greyed out and neither
  gesture moves it.

### 5. Nothing about assignment changed

The gesture is as it was: click an app to pick it up, click a hotbar slot to put
it down, click outside to throw it away, and `1`–`9` while carrying. The bottom
row is now your **real hotbar**, so wood shows up there too.

---

## The M8 walkthrough — the Network page

Reached from the **pause menu**: `Esc`, then **Open to LAN**. The button keeps
its vanilla wording on purpose — it is close enough to what the page is about
that nobody has to hunt for it, and a renamed button is one more tell that this
is not quite Minecraft. What it opens is the machine's network settings; the
LAN screen itself is unreachable, because a shell that can publish itself to
the local network because somebody pressed a button in a settings menu is a
surprise, not a feature.

Everything below can also be driven without Minecraft:

```bash
mcsh network                                     # the whole page
mcsh set network.wifi..scan true                 # press a button
```

### 1. It opens, and it opens fast

* `Esc` → **Open to LAN**. The page should be *there*, not appear a beat later.
  Eight seconds of nothing was the first version of this: `bluetoothctl` does
  not fail when its service is stopped, it waits, and it was being called while
  the page was being built. If this ever hangs again, that is the shape of it.
* Unlike Sound, Video and Controls, there is **no button back to a Minecraft
  page** in the bottom left. There is nothing on the other side.

### 2. Wi-Fi

* The top row is the radio. Turning it off should empty the list below and
  leave the row saying "The radio is off"; turning it back on should refill it
  within a second or two, with no Scan needed.
* The status line names the network and the address you have on it.
* **The network you are on is greyed** in the list. Disconnect is its own row
  higher up, so it can be found without hunting for the row you happen to be
  joined to.
* Strengths read `strong` / `good` / `weak` / `faint`, not percentages, and the
  list is sorted by those. That is deliberate: the number moves every time
  NetworkManager rescans, and a list sorted on it reorders under your cursor.

### 3. Joining a network

* Click one you are not on. A **password window opens on the compositor** — not
  in the game, not in chat. Same helper `sudo` uses, for the same reason.
* Cancel it: the page should say `Cancelled` and change nothing.
* Get it wrong: the page should say what NetworkManager said.
* A **saved** network should join with no prompt at all.
* While any of this is happening, every other button on the page is greyed and
  the top line says what is going on. **The Wi-Fi toggle stays live on purpose**
  — it is the way out of a connect that has hung.
* **Forget** removes a saved network and its stored password.

### 4. Wired

With no cable in the port, the row should say **Cable not connected** and the
Connect button should be greyed — that is a laptop's normal state, not an
error. Plug a cable in **while the page is open**: it should notice by itself,
within about a second. Nothing polls; `nmcli monitor` says so.

### 5. Bluetooth

With `bluetooth.service` stopped, the section is one line saying so. Start it
(`sudo systemctl enable --now bluetooth`) and the section should fill in **while
the page is open**, within twenty seconds — that is the one BlueZ event a
watcher attached to BlueZ cannot report, so it is polled.

* The power toggle, then **Scan for devices** — ten seconds, and the list fills
  as things answer.
* Clicking an unpaired device pairs, trusts and connects it in one go. Anything
  that needs a PIN typed — a keyboard — still has to be paired elsewhere.
* Clicking a connected device disconnects it.

---

## The M8 walkthrough — the XP bar is the battery

Nothing to open. Look at the bottom of the screen.

### 1. It reads the machine

* The number over the bar should be your **charge as a percentage**, with the
  `%` — not a level. Check it against `cat /sys/class/power_supply/BAT*/capacity`.
* The bar should be **that fraction full**, in vanilla's green.
* `mcsh -r hello` prints the same numbers the HUD is drawing; if the two
  disagree, the mod is stale, not the daemon.

### 2. It follows the cable

* **Unplug the charger.** Within about five seconds the number should turn
  **green**. Plug it back in: **white**.
* White is *mains*, not *charging*. This laptop stops charging at 80% and sits
  there — plugged in and not charging — and it should read white the whole
  time, because green means draining.
* Let it fall below **15%** on the battery and the number turns **red**. Red
  only ever appears with no cable attached: a warning to find a charger is
  pointless when you are holding one.

### 3. Minecraft's experience is still there, and still invisible

This is the part worth actually trying, because it is the one that could go
wrong quietly.

```
/xp add @s 500 points
```

* The bar must **not move**. The number must **not change**.
* `/xp query @s levels` should show the levels really did go up — they are
  accruing, just not drawn.
* An enchanting table should still work off those levels. The game's own
  screens are about experience and still say so; only the HUD stopped.

### 4. It disappears where the XP bar always did

* `F1` hides it with the rest of the HUD.
* `/gamemode creative` removes it, exactly as it removes the XP bar. Back to
  survival and it returns.

---

## The M8 walkthrough — the Statistics screen

`Esc` → **Statistics**. Minecraft's own three tabs should be gone entirely,
with no button back to them.

Drivable without Minecraft:

```bash
mcsh stats            # the Machine tab
mcsh disks            # the Storage tab
mcsh '{"t":"stats_watch","on":true,"limit":10}'   # then read the socket
```

### 0. You can get out of it

The first version of this could not be left — Done and Escape both went
straight back to the Machine tab.

* **Done** should return to the pause menu. So should **Escape**.
* From any of the three tabs, not just the one you opened on.

### 1. Machine

Check a few against the machine itself — `fastfetch` is a good second opinion:

* OS, kernel, host, CPU, GPU, memory, display. The GPU line should name
  **both** cards on this laptop, Intel and NVIDIA.
* **Nothing should overlap anything.** Rows with a second, dimmer line under
  them — Display, Battery, the filesystems on the Storage tab — used to be
  written over by the row beneath. A value too long to fit beside its label
  should end in an ellipsis, not run back under the label.
* **Packages** should match `pacman -Qq | wc -l`. It is counted by reading
  pacman's database directory, not by running pacman.
* **Screen time** starts at zero and only counts time this daemon has been
  running — time in the shell, not time powered on. Leave the shell running
  for a few minutes and reopen the tab; Today should have moved. It is banked
  every minute, so it survives a `systemctl --user restart mcshelld`.

### 2. Processes

* CPU and memory gauges up top, then a sortable table. **The first second
  reads zero CPU** and that is not a bug: a CPU percentage is work done
  between two looks, and there has only been one.
* **Click a column header** to sort by it; click it again to reverse.
  Numbers start high-to-low, names start at A. The sort happens in the
  daemon, so what you get back is already in that order.
* Compare against `htop`. Process CPU here is a share of the **whole
  machine**, so a fully busy core on a 16-thread machine reads about 6%,
  where htop would say 100%.
* **Select a row and press End Process.** It sends SIGTERM — a request, not a
  kill. Try it on something harmless (`foot`, a spare browser window).
* **Select `sway`, `java`, `mcshelld` or `systemd`.** The button must go grey.
  Those hold the session up. Even if you get past the button, the daemon
  refuses: `mcsh '{"t":"process_kill","pid":1}'` should answer with an error.
* Close the screen and watch `journalctl --user -u mcshelld -f`: the stream
  should stop. Nothing is sampled while nobody is looking.

### 3. The scrollbar drags

On any tab that overflows: **press and hold left-click on the bar and drag**.
The list follows, and keeps following if you drag sideways off it — only the
button release lets go. The same is now true on the settings pages and the
command output panel, so check one of those too if you are passing.

### 4. Storage

Every mounted filesystem with a usage bar, then the physical drives. Compare
with `df -h` and `lsblk`. Bars go amber past 75% and red past 90%.

---

## The M8 walkthrough — the Advancements screen is the filesystem

`Esc` → **Advancements** (or `L` in game). Minecraft's own advancement tabs
should be gone entirely, with no way back to them.

Drivable without Minecraft, which is where to start:

```bash
mcsh '{"t":"dir_query","path":"","offset":0,"limit":20}'   # the home directory
mcsh '{"t":"dir_query","path":"'"$HOME"'/Downloads","offset":0,"limit":20}'
mcsh '{"t":"dir_query","path":"/root","offset":0,"limit":20}'    # permission denied
mcsh '{"t":"dir_query","path":"/etc/hostname","offset":0,"limit":20}'  # not a directory
```

Every entry carries a `kind` — `dir`, or what kind of file it is. That is the
daemon's answer and the icon follows from it, so a wrong icon is a line in
`KINDS` in `daemon/mcshelld/files.py`, not a texture.

### 0. You can get out of it

Do this first, and only this, before touching anything else. **`Esc` closes
the screen**, back to the pause menu you came from — not back into the file
tree. If it loops, stop and say so; nothing below is testable from inside a
screen you cannot leave.

### 1. One folder, in the middle

On opening there is a single node: your home directory, a folder icon in a
**grey** frame, centred in the window. The window is vanilla's frame at
vanilla's pixel scale, but **grown to fill the screen** — nine-sliced, so the
corners are whole and the edges repeat. Check the border for a seam and the
corners for a stretch; there should be neither. The title bar reads the home
path.

Hovering the folder shows its name and nothing else.

### 2. One click opens, the same click closes

Click the home folder. Its frame turns **gold** and its children fan out to the
right, joined by vanilla's white-on-black elbow lines. Click one of those and
it grows its own.

Click the gold folder again: the branch disappears and the frame goes grey.
That is the whole interaction — there is no second button, and right-click
should do **nothing at all** anywhere on this screen.

Click a folder with nothing in it: it goes gold with no branch, which is how
an empty directory looks. Click it again and it goes grey.

Count the children against `ls ~` — dotted entries are deliberately not there.
Hover the now-expanded home folder: under the name there should be a dim
`N hidden` line. Check it against `ls -A ~ | grep -c '^\.'`.

Closing and reopening is also how you refresh. Make a directory in another
terminal (`mkdir ~/zzz-test`), close the home folder, open it again, and it
should be there.

### 3. Files, with icons

Expand something with a mix in it — `~/Downloads` is the obvious one. Files sit
**after** the directories, alphabetically, each with an icon for what it is:

| Icon | Kind | Looks like |
|---|---|---|
| folder | `dir` | a manila folder |
| page, blank | `file` | anything unrecognised |
| grey lines | `text` | `.txt` `.md` `.log` |
| blue header | `doc` | `.docx` `.odt` `.epub` |
| red bar | `pdf` | `.pdf` `.ps` |
| green grid | `sheet` | `.xlsx` `.csv` |
| orange bars | `slides` | `.pptx` `.odp` |
| sun and hill | `image` | `.png` `.jpg` `.svg` |
| music note | `audio` | `.mp3` `.flac` |
| play triangle | `video` | `.mp4` `.mkv` |
| cyan lines | `code` | `.py` `.java` `.sh` |
| gear | `config` | `.json` `.yaml` `.conf` |
| zipper | `archive` | `.zip` `.tar.gz` `.jar` |
| letter A | `font` | `.ttf` `.otf` |
| chip | `binary` | `.so` `.AppImage` `.exe` |

**Clicking a file does nothing.** No expansion, no sound, no frame change —
this is a picture of the filesystem, not a file manager. Hovering one shows
its name.

If an icon is wrong, that is `KINDS` in `files.py`. If an icon is *missing* —
the purple and black tile — that is a kind the daemon named and the mod has no
texture for, which should be impossible; say so, it is a bug.

### 4. Dragging pans, and does not open anything

Press and hold left-click on the **background** and drag: the tree moves under
the window, clamped so it cannot be dragged off into nowhere. Scroll wheel
moves it vertically.

Now the case that matters: **press on a folder, drag well away, release.** The
tree should pan and the folder must **not** expand. Then click the same folder
without moving — it expands. Three pixels is the whole margin.

### 5. A crowded directory steps rather than sprawls

Find one with more than twenty subdirectories:

```bash
ls -d /usr/lib/*/ | wc -l
```

Expand it. Exactly twenty children — directories and files together — and a
last node reading `… N more`, drawn as an **empty frame** because it is a
control rather than something on the disk. Click
it: the same twenty slots now hold the next page, with `… previous 20` at the
top. Step forward to the end — the last page should be short, and there should
be no `… more` node after it.

### 6. What it does not do

Nothing opens, renames, moves or deletes. Files are drawn so that a directory
with things in it does not look empty, and that is all they are for.

---

## The M8 walkthrough — Save and Quit to Title is the power menu

`Esc` → **Save and Quit to Title**. The title screen should be unreachable:
four buttons and nothing else.

Drivable without Minecraft, and this is where to start, because three of the
four are hard to walk back:

```bash
mcsh '{"t":"power_action","action":"nonsense"}'   # refused
mcsh '{"t":"power_action","action":"lock"}'       # this one really locks
```

### 0. You can get out of it

Again first. **`Esc` goes back to the pause menu**, and the *Save and Quit to
Title* button there should be **live**, not greyed out — vanilla disables it on
the way in, and returning rebuilds the screen. Press it again and the power
menu should open a second time. If it is grey, say so.

There is deliberately no Back button. Four buttons was the ask, and Escape is
how every Minecraft screen is left.

### 1. Lock Screen

Press it. The menu should close **back to the world**, not to the pause menu,
and the lock should come up over everything — the same screen `$mod+Shift+l`
gives, because both run the same script. It should look like Minecraft's
**Direct Connection** screen:

* tiled dirt, at the same GUI scale the game uses on this monitor
* **Session Locked** as the title, in Minecraft's font with its drop shadow
* **Password** as the field label, and a text field below it
* two greyed buttons: *Press Enter to Unlock* and `Nick@archlinux`

Type your password. **A square dot appears per character** — that is
hyprlock's `input-field`, coloured as `TextFieldWidget`'s own two rectangles
and placed exactly where the picture leaves a hole for it. Enter turns the
outline blue and then unlocks, onto Minecraft where you left it. Type it wrong
deliberately: the outline goes **red**, and nothing is written in words. Caps
lock turns it yellow. There is no failure message because there is no
Minecraft font on the machine to set one in.

If you see a **ring** in the middle of the field instead of dots, hyprlock is
missing and you are on route 2 — swaylock over the same picture, with the ring
standing in for the cursor. It lights per keystroke, goes blue while verifying
and red when wrong. It still locks; it just cannot echo.

Check the render on its own without locking anything:

```bash
session/lockscreen.py --width 1920 --height 1080 --out /tmp/lock.png \
  --secondary "$(id -un)@$(uname -n)"      # the field, drawn, for swaylock
session/lockscreen.py --width 1920 --height 1080 --out /tmp/lock2.png \
  --no-field --secondary "$(id -un)@$(uname -n)"   # the hole, for hyprlock
```

Both print the layout back as `NAME=value` lines, which is what `lock.sh`
evals to place the field or the ring.

It reads the dirt, the button sprite and the font out of the installed client
jar. If it cannot find one, it exits non-zero and `lock.sh` falls through to a
plain ImageMagick screen, and then to bare swaylock — all four routes lock,
and only the first two are pretty.

Whatever happens, the journal has the truth — `pam_unix` logs every attempt:

```bash
journalctl -b | grep -E 'pam_unix\((hyprlock|swaylock)'
```

**No lines at all means no password was ever submitted**, which is a different
bug from one that was submitted and rejected. That distinction is the whole
reason this section exists.

**If you cannot get back in:** `Ctrl+Alt+F2` for a TTY, log in there, and
`loginctl terminate-session $XDG_SESSION_ID` — or `sudo systemctl restart gdm`
— to get back to the greeter. Do **not** kill the lock program: the compositor holds
the session lock, so a dead lock client leaves the session locked with nothing
drawing on it. The power button is not the escape hatch.

Then the case that matters: with the lock up, **do not touch anything for a
moment and check the daemon is still alive**:

```bash
systemctl --user status mcshelld
```

Now the hazard this was built around. From a second machine or a TTY:

```bash
systemctl --user restart mcshelld
```

**The lock must stay up.** It is started through Sway's `exec`, so it lives in
the compositor's cgroup rather than the daemon's. If restarting the daemon
unlocks the machine, that is a security bug, not a papercut — report it.

### 2. Sleep

Press it. The screen should lock **and then** the machine should suspend. Wake
it: you should be on swaylock, not on the desktop.

If it suspends without locking, the log says why:

```bash
journalctl --user -u mcshelld | grep -i 'suspending without'
```

### 3. Restart and Power Off ask first

Both should open **vanilla's confirmation screen** — the plain "Yes / No" one —
saying every open application will be closed. **No** returns to the power menu.
Yes does the thing.

Test **No** on both before you test Yes on either.

### 4. Nothing needs a password

None of the four should raise the askpass window or a polkit prompt. logind
allows all three for the active local session:

```bash
busctl call org.freedesktop.login1 /org/freedesktop/login1 \
  org.freedesktop.login1.Manager CanPowerOff     # s "yes"
```

If one of them silently does nothing, that is the answer to check first — a
`challenge` there means polkit wants an authentication this menu will not do.

---

## The M8 walkthrough — notifications are advancement toasts

Nothing owned `org.freedesktop.Notifications` on this machine before this, so
before M8 a Discord ping in the MCShell session went nowhere at all. Now it
arrives as the advancement toast, in the top-right corner, **above every
window** — a layer-shell surface in the `overlay` layer, not something drawn
inside Minecraft, because Minecraft is the backdrop and a toast drawn there
would be behind whatever you were actually looking at.

### 1. The daemon is the notification server

```bash
busctl --user status org.freedesktop.Notifications | head -2
gdbus call --session --dest org.freedesktop.Notifications \
    --object-path /org/freedesktop/Notifications \
    --method org.freedesktop.Notifications.GetServerInformation
```

Expect the PID of `mcshelld`, and `('mcshell', 'mcshell', '0.0.0', '1.2')`.
`GetCapabilities` answers `['body', 'icon-static']` and deliberately nothing
else: there are no actions because the surface takes no clicks, and no
`body-markup` because the game's font has one weight.

If `busctl` says the name is not activatable, something raced a daemon
restart. Send again.

### 2. One toast

```bash
notify-send -a Discord -h string:desktop-entry:discord \
    "Discord" "nick: are we still on for tonight?"
```

Watch for, in order:

* it **slides in from the right**, over 600ms, easing as `f²` — vanilla's own
  curve, read out of `ToastManager$Entry`;
* the **Discord icon at 16x16** on the left, nearest-neighbour downscaled from
  the same file the hotbar uses;
* the summary in **yellow** on the header line, the body in white under it,
  **neither with a drop shadow** — that is vanilla's `AdvancementToast`, which
  passes `false` to both `drawText` calls;
* the **level-up sound**;
* it leaves after five seconds, sliding back the way it came.

Then check it is not a window:

```bash
swaymsg -t get_tree -r | grep -c dev.mcshell.toasts     # must be 0
```

**Zero is the pass.** A layer surface is not a view and never appears in the
tree. If it is there, the layer-shell preload did not take and the shell will
have filled it to the screen and focused it — see §5.

### 3. Everything at once

```bash
send() { notify-send "$@"; python3 -c 'import time; time.sleep(0.7)'; }
send -a Discord   -h string:desktop-entry:discord "Discord" "#general — 3 new messages"
send -a Obsidian  -h string:desktop-entry:obsidian "Obsidian" "Vault synced"
send -a Brave     -h string:desktop-entry:brave-browser "Brave" "Download finished"
send -u critical  -a "Prism Launcher" \
     -h string:desktop-entry:org.prismlauncher.PrismLauncher \
     "Prism Launcher" "Instance crashed — exit code 1"
send -a Kitty     -h string:desktop-entry:kitty "Sixth Toast" "this one had to queue"
send -a Nothing   "No Icon" "and the sprite still draws"
```

* They **stack downward every 32 GUI pixels**, five at a time.
* The critical one's header is **magenta** (`0xFF88FF`), vanilla's challenge
  colour. Everything else is yellow. Urgency is the only thing here that is
  ours rather than copied — vanilla picks by advancement frame and there are
  no advancements.
* The sixth **waits for a slot** rather than living out its five seconds off
  screen, then slides in when one frees.
* The one with no icon draws the sprite and the text, and no icon. It does not
  draw Minecraft's missing-texture check.
* You hear **one** level-up, not seven: two notifications inside 0.75s are one
  sound, or a group chat catching up after a resume would play twenty.

### 4. Clicks go through it

With a toast on screen, click **through** where it is — on the window
underneath, on the Minecraft world behind everything. The click must land on
what is under the toast, not on the toast.

The surface's input region is empty, deliberately. Vanilla's toasts cannot be
clicked either, and a strip of the screen that silently eats mouse presses is
the bug this project already spent a session on.

### 5. Replacing, and the text nobody controls

```bash
id=$(notify-send -p -a Discord -h string:desktop-entry:discord \
     "Discord" "typing...")
notify-send -r "$id" -a Discord -h string:desktop-entry:discord \
     "Discord" "nick: never mind"
```

The toast **changes in place** and does not slide out and back in — a music
player updating its own track would otherwise read as two.

```bash
notify-send "Café — Björk" "naïve … <b>bold</b> &amp; a line far longer than a hundred and twenty five pixels"
```

Accents are stripped to their base letters, the punctuation people paste is
replaced (`—` → `-`, `…` → `...`), markup is stripped rather than drawn, and
what will not fit is cut with an ellipsis at vanilla's own 125px wrap width.
`ascii.png` is ninety-five glyphs and a notification body is whatever an
application felt like sending; emoji are dropped rather than drawn as question
marks, so an emoji-only message can arrive as an empty body line.

### 6. Looking at a toast without waiting for one

```bash
session/overlay.py --scale 4 --out /tmp/toast.png \
    --preview "Discord|a message|/usr/share/icons/hicolor/256x256/apps/discord.png" \
    --preview "No Icon|the sprite still draws|"
```

Renders the column to a PNG instead of showing a window. Use this to check the
pixels — it needs no compositor, no daemon and nothing to ping.

### 7. If nothing appears

```bash
journalctl --user -u mcshelld -n 40 | grep -i notify
pgrep -af overlay.py
tr '\0' '\n' < /proc/$(pgrep -f overlay.py | head -1)/environ | grep LD_PRELOAD
```

Expect `serving org.freedesktop.Notifications`, `toast overlay up (pid N)`, and
`LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so` on the overlay.

That preload is load-bearing and was a real failure, not a precaution.
gtk4-layer-shell hooks `wl_display_connect`, so it has to be in the process
before libwayland-client is, which a Python import cannot arrange —
`overlay.py` re-executes itself once to manage it. Measured:

| preload | `Gtk4LayerShell.is_supported()` |
|---|---|
| none | False |
| `liblayer-shell-preload.so` | False |
| `libgtk4-layer-shell.so` | **True** |

Without it the overlay came up as an **ordinary toplevel**, and the daemon
filled it to the screen and focused it as though the notification overlay were
an application somebody launched (`adopting new window N (dev.mcshell.toasts)`
in the journal). It now refuses to open at all rather than open the wrong kind
of window.

---

## The M8 walkthrough — the clock, and the shell's own settings

Two things at once, because they arrived together: a HUD element that says
what time it is, and the page that switches it off. The page is the
**Accessibility** lane — the last vanilla options screen with nothing of ours
behind it.

Both halves need the new jar and a restarted daemon:

```bash
session/prism/install-mod.sh          # then $mod+Shift+m to restart the client
systemctl --user restart mcshelld     # or $mod+Shift+d
```

### 1. The clock is on screen

Look at the **top-left corner** of Minecraft, at the margin the chat uses.

```
10:13 AM – Monday, September 7th
```

The time is yellow, the separator and date are white, both with vanilla's drop
shadow. Check, in order:

* it says the **right time** — the same as `date` in a terminal;
* it **changes on the minute**, not a second or two after it;
* **F1 hides it**, along with the rest of the HUD;
* **F3 replaces it** — the debug overlay draws in the same corner and is the
  more urgent of the two;
* opening the inventory or a settings screen leaves it drawn behind, like
  every other HUD element.

There is **no sun or moon** beside it. The reference this was built from shows
one because that mod displays the world's time too; this world has
`doDaylightCycle false` and a void sky.

### 2. The page

`Esc` → **Options…** → **Accessibility Settings…**. The shell's page opens,
titled **MCShell**, and Minecraft's own accessibility settings are one button
away in the bottom-left — **Minecraft Accessibility…** — exactly like Sound,
Video and Controls. That button crosses back.

On Minecraft's own screen, look at the bottom edge: **Done is alone and
centred**, and there is no *Accessibility Guide* beside the return button.
Vanilla puts two buttons in that footer and the guide sat on top of the lane
switch. If you see them overlapping, the mod jar in the Prism instance is
older than the fix — run `session/prism/install-mod.sh` and restart the
client.

Eight rows in three groups. Without Minecraft:

```bash
mcsh general
```

### 3. The clock's two rows

* **Clock** off → the top-left corner empties within a second, and the format
  row below greys out with it.
* **Clock format** → *12-hour* gives `10:13 AM`, *24-hour* gives `10:13`, and
  *System* is whatever `nl_langinfo(T_FMT)` says. Hover it: the tooltip names
  the format the locale actually asked for. On this machine `LANG=C.UTF-8`,
  which says 24-hour — so *System* and *24-hour* look identical here, and
  that is correct rather than broken.

Both survive a daemon restart; they are in `~/.config/mcshell/general.json`.

```bash
mcsh set general.clock..format '"12"'
mcsh set general.clock..show false
```

Watching the pushes, with no Minecraft at all:

```bash
python3 - <<'EOF'
import json, socket, time
s = socket.socket(socket.AF_UNIX); s.connect("/run/user/1000/mcshell.sock")
s.sendall(b'{"t":"hello","proto":1,"mc":"1.21.1"}\n')
end = time.time() + 75
while time.time() < end:
    for line in s.recv(65536).split(b"\n"):
        if b'"hud"' in line:
            print(time.strftime("%H:%M:%S"), line.decode())
EOF
```

One `hud` on connect, one at exactly `:00` of the next minute, and one per
toggle. **Measured**, on 2026-09-07: `10:12:02` then `10:13:00`.

### 4. The battery gauge's colour

**Colour the battery gauge** off pins the XP bar's number green. On mains it
stops going white; below 15% on battery it stops going red. On again and both
come back. The bar sprite itself never changes either way — only the number's
colour ever did.

### 5. Notifications, from the other side

Three rows, and one of them is also on the Sound page:

* **Show notifications** off → `notify-send -a Discord "x" "y"` draws nothing
  and plays nothing. On → it does both.
  **Measured**: no `pw-play` process with the switch off, one with it on.
* **Notification sound** is the same value as the row on the Sound page. Turn
  it off here and it is off there; the Sound page's row greys out entirely
  when notifications are off, and says why.

### 6. Choosing a sound

**Sound: Minecraft level-up** opens the desktop's file chooser — a real
window, `xdg-desktop-portal-gtk`, titled *MCShell notification sound*. It is
the same dialog every other application on this machine opens, and it is where
the setting goes for the same reason sudo's password prompt is a window: no
settings row draws a text field, and the game client is the wrong place to
type a path into.

* While it is open the row is **greyed** — a button already doing something
  should say so.
* Cancel, or close the window from the compositor, and **nothing is said**. A
  cancel is not an error.
* Pick a `.wav`, `.mp3`, `.ogg`, `.flac` or `.opus` and it **plays once,
  immediately**. The point of choosing a sound is to find out what it sounds
  like.
* The row's label becomes the file's name, and **Use the Minecraft sound**
  un-greys beside it.
* Anything else — a `.txt`, a file that has since been deleted — is refused,
  and the daemon log says why. libsndfile 1.2.2 is what `pw-play` decodes
  with; mp3 was **measured** rather than assumed (`pw-play` exits 0 on one).
* A long file is **cut off at five seconds**. **Measured**: a 20-second mp3
  gives a player that lives 5.0s.

The dialog keeps its own size — it is in `KEEP_OWN_SIZE` beside the askpass
prompters, because a file browser stretched over the whole backdrop is a worse
file browser. GTK remembers the size you last left it at, so if it comes up
full-screen once, resize it and it stays resized.

### 7. Screen time

**Track screen time** off, then look at **Statistics → Machine**: the four
Screen time rows stop moving and a fifth appears reading **Tracking · Off**.
Frozen numbers with nothing saying why would read as a broken clock.

Nothing is erased. Switch it back on and the totals resume from where they
were — the mark advances while tracking is off, so re-enabling does not bank
the hour it was off for.

```bash
mcsh set general.screentime..track false
mcsh '{"t":"stats_query","tab":"general"}'
grep tracking ~/.config/mcshell/screentime.json
```

---

## The M8 walkthrough — screenshots, and bindings of your own

Needs `swaymsg reload` (or a fresh login) once, so Sway picks up the new `F2`
line in `session/sway.conf`, and `systemctl --user restart mcshelld`.

### 1. F2 takes a picture of the whole screen

Open something over Minecraft — a browser, a terminal — and press **F2**.

* A toast slides in top-right: **Screenshot saved**, with the file's name
  under it and a thumbnail of the shot itself as the icon.
* The file is in `~/Pictures/Screenshots/Screenshot_<date>_<time>.png`, and it
  is the *whole* screen, the window included.
* It is on the clipboard too. Paste it into anything that takes an image.

```bash
ls -t ~/Pictures/Screenshots | head -3
```

**Minecraft's own F2 is gone**, and that is the design: Sway sees the key
before any window does. With the game as the fullscreen backdrop the picture
is the same one, and it now lands in one directory rather than two.

If nothing happens, the reload did not take:

```bash
swaymsg -t get_config | grep -n 'bindsym F2'      # should print the line
~/dev/mcshell/session/screenshot.sh; echo $?      # should print 0
```

A failure says so in a toast of its own — *grim is not installed*, *cannot
write to …* — rather than in a log.

### 2. The bind maker

`Esc` → **Options…** → **Controls…** → **Machine Controls…**. Three rows sit
above everything else, under **New binding**:

| Row | What it is |
|---|---|
| Command | a text field — click it and type |
| Key | the same capture the rebinds below use |
| Add binding | greyed until both are filled |

Type `flameshot gui` into **Command** and press **Enter**. The field keeps
what you typed. Click **Key**, press **Shift+F2**. **Add binding** goes live;
press it.

* The three rows empty, ready for the next one.
* A new group appears under them — **My bindings** — with one row:
  `flameshot gui`, `Shift+F2`, and a **Remove** button where Reset sits on the
  binds below.
* Press **Shift+F2** anywhere. Flameshot's region selector comes up.

Without Minecraft:

```bash
mcsh set controls.new..command 'flameshot gui'
mcsh set controls.new..key Shift+F2
mcsh set controls.new..add true
mcsh controls | grep 'My bindings'
```

### 3. What it refuses

* **A key something already has.** Try `Super+Return` — *Super+Return is
  already bound to exec foot*. It checks Sway's binds and ours both.
* **Plain F2.** You cannot even record it: Sway eats the key, so Minecraft
  never sees it. This is the one thing binding F2 costs. `mcsh set
  controls.new..key F2` still works if you really mean it.
* **A command that is not installed.** It is *allowed* — the row's second line
  just says `flameshot is not on PATH`. A binding may name something you are
  about to install, or a shell builtin, and a refusal there would be wrong.
* **`exec` typed in front.** Stripped, not refused: Sway's `exec` is added by
  the daemon and `exec exec flameshot` is the obvious mistake.

### 4. It survives everything

```bash
systemctl --user restart mcshelld     # or $mod+Shift+d
cat ~/.config/sway/config.d/mcshell-binds.conf
```

The binding is re-applied at startup and written into the generated snippet
under `# Made on the Controls page.`, so a `swaymsg reload` keeps it too.
`~/.config/mcshell/custom-binds.json` is where it actually lives — the snippet
is an output, and is never read back.

### 5. Remove

Click **Remove**. The row goes, the group goes with it when it was the last
one, and the key stops working immediately.

```bash
mcsh set controls.custom.<id>.remove true
```

### 6. Rebinding still works — and used to not

```bash
mcsh controls                                   # ids are in the first column
mcsh set controls.5d312a8c.key Super+Shift+F9   # lock.sh moves
mcsh set controls.5d312a8c.key Super+Shift+l    # and back
```

These keys were `binds.…` until this session. A `setting_set` is routed by the
key's first segment and the provider is registered under its page name, so
every rebind since M6 was answered with *no page owns 'binds.…'* — in a log
nobody had open. If you see that message again, a key has lost its prefix.

## The M8 walkthrough — the volume popup

Needs `systemctl --user restart mcshelld`. Nothing in the Sway config changes:
the media keys are still bound straight to `wpctl`.

### 1. It appears

Press **volume up**. A boss bar slides — no, *appears*, it does not animate —
at the top centre of the screen: **Volume 62%** in white with a drop shadow,
the 182x5 white bar filled to match, gone after 1.4 seconds. A click plays at
the new level, which is the point: you can hear how loud 62% is.

Press it four more times quickly. The bar stays up and its number climbs; it
does not restart an entrance on every notch. The clicks thin out — one every
90ms at most — rather than becoming a tone.

Press **mute**. The bar goes red and reads **Muted**, still filled to the
level it was, because a muted sink still has a volume and the next thing you
do is unmute.

**It is above everything.** Open a browser full-screen over Minecraft and do
it again. That is the whole reason it is not a HUD element in the game.

### 2. It is not the keybinding

The popup hangs off the daemon's PipeWire subscription, not off the key. So
all of these draw it:

```bash
wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+      # from the command bar
mcsh set audio.sink..volume 0.3                # our own Sound page
```

And so does a headset with its own wheel, or another application taking the
sink down. A binding that drew the bar itself would cover one of the four.

**It does not fire when nothing moved.** Restarting the daemon reads the level
once and shows nothing; plugging in headphones without a level change shows
nothing.

### 3. What it looks like, without a compositor

The bar renders to a PNG the same way toasts do, so it can be checked by
looking at it:

```bash
session/overlay.py --scale 4 --out /tmp/osd.png \
  --preview-osd 'Volume 50%|0.5|white' \
  --preview-osd 'Muted|0.75|red'
```

### 4. The sound

`Esc` → **Options…** → **Accessibility Settings…** → **Volume key sound**.
Four choices, and each one plays as you select it:

| Choice | Asset |
|---|---|
| Click | `random/click.ogg` — the menu tick |
| Hurt | `damage/hit1.ogg` — the oof |
| Note block | `note/harp.ogg` |
| Off | nothing; the bar still draws |

```bash
mcsh set general.volume..sound hurt
mcsh set general.volume..sound kazoo    # -> not a volume sound: 'kazoo'
```

It survives a restart — `~/.config/mcshell/general.json`, `volume_sound`.

### 5. One overlay, two surfaces

The toasts and the bar are two windows in one process. Send a notification and
change the volume; `pgrep` finds one `overlay.py`, not two.

```bash
pgrep -af session/overlay.py
notify-send -a MCShell "still working" "after the refactor"
```

**Neither is ever a toplevel.** That is the failure this guards against — a
layer-shell surface that comes up as an ordinary window is one the daemon
fills to the screen and focuses, as though the overlay were an application:

```bash
swaymsg -t get_tree -r | grep -c dev.mcshell.toasts     # must be 0
```

## The boot phase — what a login actually does

Not a walkthrough with steps to pass: there is only one way to run it, which is
to log out and log back in, and that is deliberate — MCShell is a *second* GDM
entry, so a broken config costs a session pick rather than a login. This is
what to look at afterwards.

`docs/testing.md` §*The M7 walkthrough — the real session* is still the
reference for installing it, the first login, and *When it comes up wrong*.
That book is closed to new material, not to reading.

### 1. The two logs

```bash
journalctl --user -u mcshelld -u mcshell-client -b        # the units
less ~/.local/state/mcshell/session.log                   # sway, truncated per login
```

`$mod+Shift+j` opens the first. The second is the only copy of why a login
failed once the journal has rolled — and it also collects the stderr of every
application started from the shell, so expect Electron warnings and
`vaInitialize failed` in it. That is a known rough edge, not a fault.

### 2. The sequence, and roughly when

```bash
# what actually happened, in order
journalctl --user -u mcshelld -b -o short-iso | grep -v DEBUG | head -20
head -1 ~/.local/state/mcshell/session.log        # when sway started
```

Measured once, 2026-09-07, on this laptop:

| | |
|---|---|
| `+0s` | GDM runs `start-session.sh`, sway starts |
| `+1s` | both units Started |
| `+3s` | daemon ready — catalog, sway IPC, slots, binds, notifications, listening |
| `+3-13s` | Prism's own windows appear, get adopted and filled, and go |
| `+13s` | the mod connects: `hello`, proto 1, mc 1.21.1 |
| `+15s` | `focus_ack game:true` — the world is up and has the pointer |

If the mod never connects, the daemon is up and the game is not: read
`mcshell-client` in the journal, and try `session/prism/launch.sh` by hand from
a terminal (`$mod+Shift+Return`).

### 3. It cleans up after itself

The failure this guards against is Minecraft outliving the logout while still
holding the world's `session.lock`, which makes the *next* login fail with a
complaint about the lock rather than about the real cause.

```bash
# after logging out and back in, from a TTY or the new session
pgrep -af prismlauncher ; pgrep -af mcshelld     # should be one each, this session's
```

`start-session.sh` stops `mcshell-session.target` after sway exits, which is
the whole reason that script runs outside sway.

### 4. The units are the repo's

```bash
session/install-session.sh --user-only    # idempotent; re-run after moving the checkout
systemctl --user cat mcshelld.service | grep ExecStart
```

`@REPO@` is substituted at install time, so a moved checkout is one re-run away
from correct. Re-running is always safe.

### 5. When it comes up wrong

```bash
session/diagnose.sh
```

Reach for it first. Reach for `session/probes/` instead when the symptom is
input — clicks going nowhere, the camera stuck — because that is the class of
bug this project has already spent a session on.

## The boot screen

One picture over the whole login. Minecraft's world-generation screen, drawn
out of the client jar by `session/loading.py`, with the shell's logo above it.
It replaces the three unrelated things a login used to show: sway's flat
`#1a1a2e`, then Prism's launcher window, then Minecraft's own Mojang splash.

### 1. What it looks like, without logging out

The whole screen renders to a PNG, which is the only way to check it without
ending your session:

```bash
cd session
python3 loading.py --progress 0.5 --logo assets/logo.png --out /tmp/boot.png
python3 loading.py --progress 0    --logo assets/logo.png --out /tmp/boot0.png
python3 loading.py --progress 0.99 --logo assets/logo.png --out /tmp/boot99.png
```

At 0 the map is solid black inside its grey margin; by half it is a bullseye of
vanilla's chunk-status colours; near the end it is white with a warm ring at the
edge. The twelve colours are the real `LevelLoadingScreen.STATUS_TO_COLOR`, read
out of the yarn-mapped jar with `javap` rather than remembered:

```bash
javap -p -c -constants \
  -cp ~/.gradle/caches/fabric-loom/minecraftMaven/net/minecraft/minecraft-merged/\
1.21.1-net.fabricmc.yarn.1_21_1.1.21.1+build.3-v2/*.jar \
  net.minecraft.client.gui.screen.world.LevelLoadingScreen | grep 'int '
```

**The grey band and black frame are not decoration.** Vanilla draws a bigger
square than the region being generated, and the margin chunks only ever reach
`STRUCTURE_STARTS`. That is what the frame is. Getting it wrong was the first
version's tell — the square read as a progress box rather than as Minecraft.

### 2. The percentage is an estimate, and it is honest about it

There is no real progress to read, so it is interpolated against **how long
this machine's last boot took**, pinned up by real events as they land, and
capped at 99. Only `world_ready` from the mod finishes it.

```bash
cat ~/.config/mcshell/boot.json      # {"seconds": 13.8} — written each boot
```

A first boot, or a nonsense file, falls back to 14 seconds. A boot that timed
out is deliberately *not* recorded, so one bad login cannot teach the next one
that boots take ninety seconds.

### 3. It must not appear over a working desktop

This is the failure that matters, because `$mod+Shift+d` restarts the daemon
whenever anything is being debugged, and a fresh daemon knows nothing about the
desktop already on screen. Two independent guards:

```bash
$mod+Shift+d            # restart the daemon under a running session
```

**Nothing should appear.** The daemon sees Minecraft's window already mapped at
its first window sync and cancels the screen before drawing a frame; separately
the mod re-sends `world_ready` on every reconnection. Either alone is enough.

If a screen does appear and stays, it comes down by itself after 90 seconds,
and every sway binding works throughout — the surface takes no keyboard and its
input region is empty, so clicks pass through it.

### 4. It has to beat Prism's window — so the game waits instead

Two rounds of this. The first was the daemon wasting its first second:

```
22:57:21.611  mcshelld        Started
22:57:21.613  mcshell-client  Started    <- Prism, 2ms later
22:57:22.793  catalog: 83 apps
22:57:22.948  overlay: up                <- 1.34s in
```

`catalog.load()` is 1.2s of *synchronous* work, so a task created before it
never runs. Awaiting the first frame instead put it at **T+0.016s**, and
`Surface.cairo` grew an opaque fast path that took the background from 566ms to
18ms. Check it stayed fixed with:

```bash
journalctl --user -u mcshelld -b | grep -E "overlay: up|catalog"
# "overlay: up" must come BEFORE the catalog line
```

That was not enough, and the reason is worth keeping. The overlay still has a
Python interpreter, an `LD_PRELOAD` re-exec and a GTK import to get through.
Measured, painting into a nested compositor:

| | |
|---|---|
| warm | ~0.9s |
| first run | **~2.9s** |

A login is always the first run. Prism is compiled Qt and wins that
comfortably, which is exactly the 1–3 seconds of launcher you could see.

**So the game waits.** `overlay.py` touches
`$XDG_RUNTIME_DIR/mcshell-boot.drawn` from its draw handler — meaning the frame
reached the compositor — and `mcshell-client.service` has an `ExecStartPre`
that blocks on it, giving up after eight seconds. `After=mcshelld.service` was
already there and buys about two milliseconds, because `Type=simple` means
"started" is "forked".

```bash
session/prism/wait-for-boot-screen.sh   # returns at once if the marker is there
ls -l $XDG_RUNTIME_DIR/mcshell-boot.drawn
```

**A dead end worth not repeating.** `GTK_USE_PORTAL=0` and disabling the a11y
bridge looked like a 3x win — 2.87s to 0.90s — and it was an artefact of test
order. Alternating the two conditions showed them equal from the second run on;
only the *first* run of any sequence is slow, in both. Stopping the portal
services before each run did not change that either. The cost is a genuine
cold-start and it is not the portals. Run the control.

### 5. The first two seconds

The daemon does not exist yet, so nothing can draw. `start-session.sh` renders
the same dirt to `$XDG_STATE_HOME/mcshell/loading-bg.png` before starting sway
and writes `~/.config/sway/config.d/mcshell-boot-bg.conf` pointing at it, so the
login opens on the boot screen's own ground and the layer-shell surface comes up
over an identical background.

Measured, in a headless nested sway, because both halves were assumptions:

* a later `output * bg` in `config.d` **does** override the earlier
  `solid_color` — sway logs `Config stored for output *` with the new value;
* `output * bg <path> fill #1a1a2e` falls back to the colour when the file is
  missing — `Cannot access file ..., using fallback '#1a1a2e'` — rather than
  erroring and leaving the output blank.

So a picture that fails to render costs the picture, never the login.

```bash
# what a real login does, before sway exists to be asked
cat ~/.config/sway/config.d/mcshell-boot-bg.conf
ls -l ~/.local/state/mcshell/loading-bg.png
```

### 6. `world_ready` comes from the mod, so install the jar

The first run of this failed exactly here, and it is worth writing down because
nothing about the symptom points at it. The boot screen ran to its 90-second
timeout every time and the log said `nothing said the world was up within 90s`
— which reads as a broken message, a broken guard, or a broken daemon. It was
none of those. **The Prism instance was running a jar built hours earlier**,
with no `world_ready` in it at all, so the game could not have sent one.

```bash
session/prism/install-mod.sh        # after every Java change. Every one.

# and to check what is actually installed, which is the faster question:
unzip -p ~/.local/share/PrismLauncher/instances/MCShell/minecraft/mods/mcshell-*.jar \
  dev/mcshell/net/DaemonConnection.class | grep -c world_ready
```

`gradlew build` is not enough and the dev client hides this — `runClient` loads
the mod straight out of `build/`, so only the real session can catch it.
`install-mod.sh` says the same thing in its own header. It is still the easiest
mistake in this repo to make.

### 7. A second overlay can now be tested beside the real one

It could not, and the reason cost an hour. `overlay.py` built a
`Gtk.Application` with a bus-unique id, so a second copy started for testing
handed its activation to the session's own overlay and exited — no windows, no
error, an empty log. That reads exactly like a program that ran fine and drew
nothing.

It is now `Gio.ApplicationFlags.NON_UNIQUE`. Uniqueness bought nothing: the
overlay is a private child of the daemon, started and stopped with it. So this
works, and it is how the surface finally got looked at rather than assumed:

```bash
# nested, headless, so nothing appears on the real desktop
WLR_BACKENDS=headless sway -c /tmp/headless.conf &
export SWAYSOCK=$XDG_RUNTIME_DIR/sway-ipc.1000.<pid>.sock WAYLAND_DISPLAY=wayland-2
printf '{"t":"loading","value":0.45}\n' | python3 session/overlay.py &
grim -o HEADLESS-1 /tmp/proof.png
```

`busctl --user list | grep mcshell` still shows the id; it is kept because the
daemon's `OWN_SURFACES` matches on it if a window ever comes up plain.

### 8. The whole thing, at a login

The only real test, and it costs a logout. Watch it in the log afterwards:

```bash
journalctl --user -u mcshelld -b | grep -i boot
```

Expect `boot: the world is up, N.Ns after the daemon`. What you should *not*
see at any point: Prism's launcher window, the Mojang splash, or a flat colour.

## The notification sound, and a muted machine

A notification arriving on a muted laptop at 0% used to play at full volume,
*and* put the volume back to what it had been. Both halves have one cause and
one fix.

**It was never the daemon.** Nothing in `mcshelld` writes volume or mute
outside an explicit change on the Sound page — checked by grep and by
measurement: `pw-play` on a muted sink, and then a real notification through
our own bus name, both left `0.00 [MUTED]` untouched.

**It is WirePlumber restoring a route.** Each output route keeps its own saved
volume and mute:

```bash
grep -iE "volume|mute" ~/.local/state/wireplumber/default-routes
# ...:output:Speaker    = {"channelVolumes":[0.0,0.0], "mute":true}
# ...:output:Headphones = {"channelVolumes":[0.166,0.166], "mute":false}
```

Opening a stream wakes a suspended sink, and the route's saved state is applied
as it comes back — which is exactly "the volume reset to what it was
originally, and the sound played at that volume".

**The fix is to not ask for the sound.** `Audio.silent()` asks PipeWire whether
the default sink is muted or at zero, and `Notify._play` skips the sound if it
is. PipeWire rather than a setting, because the volume keys go straight to
`wpctl` so that the rails work with the daemon dead — no setting knows the
answer. It fails *open*: PipeWire not answering gets a sound, because never
hearing a notification again is the worse failure.

Not making the sound also means not waking the sink, so the volume is never
restored either. Both halves, one fix.

```bash
wpctl set-mute @DEFAULT_AUDIO_SINK@ 1; wpctl set-volume @DEFAULT_AUDIO_SINK@ 0
notify-send "test" "should be silent, and the volume must not move"
wpctl get-volume @DEFAULT_AUDIO_SINK@     # still 0.00 [MUTED]
```

Measured across all three states: muted+0% -> no player; unmuted at 0% -> no
player; unmuted at 25% -> `pw-play`. The toast still appears in every case —
the switch is about noise, not about notifications.

## The GPU nag bar

sway's red *"Proprietary GPU drivers are not supported by sway"* bar, which
appeared at every login and sat above everything — the boot screen included,
since swaynag is a layer-shell surface like our own.

```bash
# who fires it: any machine with these drivers loaded
for c in /sys/class/drm/card*/device/uevent; do grep -h DRIVER= "$c"; done | sort -u
#   DRIVER=i915
#   DRIVER=nvidia      <- this is what sway is objecting to

# sway names the cure itself
strings /usr/bin/sway | grep "To remove this message"
```

Suppressed with `SWAY_UNSUPPORTED_GPU=true`, exported by `start-session.sh`.
The variable rather than the equivalent `--unsupported-gpu` flag, and the
reason is the login path:

```bash
sway --definitely-not-a-flag --validate -c session/sway.conf   # exit 1
SWAY_TOTALLY_MADE_UP=true sway --validate -c session/sway.conf # exit 0
```

An unrecognised flag would cost a login; an unrecognised variable costs
nothing. Both forms work on sway 1.12.

**Check after the next login** that the bar is gone *and* that the fact is not:

```bash
pgrep -af swaynag                                    # nothing
grep -i "Proprietary" ~/.local/state/mcshell/session.log
```

The log line is a separate call site in sway from the nag, so it is expected to
survive — but that is the one half of this not yet confirmed on a real login.

## The Sound page could never set anything

Every volume and mute the Sound page sent had failed since the volume popup was
built, with `audio.sink..mute could not be set: 'tuple' object is not callable`.
The media keys worked throughout, which is what made it look like a bug about
audio playing — they go straight to `wpctl` and never reach the daemon at all.

**It was a name collision, and Python makes it silent.**

```python
self._level: tuple[int, bool] | None = None   # __init__
async def _level(self, kind, target, field, value)   # ...and a method
```

An instance attribute shadows a method of the same name, from `__init__`, for
the life of the object. So `await self._level(...)` was never the method. Before
any sink event it raised `'NoneType' object is not callable`; after one, the
attribute held a tuple and the message changed to the one above — which is why
it seemed to depend on whether something was playing. It did not:

```bash
# with nothing playing at all
python -c "from mcshelld.audio import Audio; a=Audio(); print(callable(getattr(a,'_level',None)))"
# False
```

Renamed to `_last_level` (the attribute) and `_set_level` (the method). The
whole class of bug is findable mechanically, and the sweep is worth re-running
after anything that adds state to a class:

```bash
python3 - <<'EOF'
import ast, pathlib
for path in pathlib.Path(".").rglob("*.py"):
    if any(x in path.parts for x in (".venv","build","__pycache__")): continue
    for cls in [n for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.ClassDef)]:
        methods = {n.name for n in cls.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assigned = {sub.attr for node in ast.walk(cls)
                    for t in (node.targets if isinstance(node, ast.Assign)
                              else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign))
                              else [])
                    for sub in ([t] if not isinstance(t, ast.Tuple) else t.elts)
                    if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                    and sub.value.id == "self"}
        if methods & assigned:
            print(path, cls.name, sorted(methods & assigned))
EOF
```

It reports nothing now. Verify the page itself with `mcsh`, which is the whole
point of the daemon being drivable without the game:

```bash
daemon/tools/mcsh '{"t":"setting_set","key":"audio.sink..volume","value":0.5}'
daemon/tools/mcsh '{"t":"setting_set","key":"audio.sink..mute","value":true}'
wpctl get-volume @DEFAULT_AUDIO_SINK@     # must actually have moved
```

## The volume bar at the extremes

Pressing volume-down at 0 drew nothing, so the key read as unresponsive rather
than as already-at-zero. The cause is not ours — PipeWire emits no event for a
write that lands on the value already there:

```bash
pactl subscribe &        # then, in another shell:
wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.5    # 1 sink event
wpctl set-volume @DEFAULT_AUDIO_SINK@ 0      # 1 sink event
wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-    # 0 — nothing to draw from
```

So relaxing the "did it move" test in `_check_level` would have changed
nothing; there is no event to relax it against. The keys now go through
`session/volume.sh`, which runs `wpctl` and then sends `osd_volume`.

**Check the rail first, because that is what this touched.** The volume must
change with the daemon dead:

```bash
systemctl --user stop mcshelld
session/volume.sh down          # volume must move; only the popup is lost
systemctl --user start mcshelld
```

Then the extremes, watching the screen:

```bash
wpctl set-volume @DEFAULT_AUDIO_SINK@ 0 && session/volume.sh down   # bar, "Volume 0%"
wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 1.0 && session/volume.sh up
```

And the thing that must *not* regress — the bar still appearing only for real
changes when nobody pressed a key. Start playing something: a stream attaching
is a sink event, and it must not pop the bar.

```bash
# missing tools must degrade to "no popup", never to "no volume"
PATH=/usr/bin:/bin session/volume.sh up     # socat present -> socat
# with socat hidden, the python3 fallback carries it; with neither, wpctl still runs
```

## The world is saved before power off

The game never shut down cleanly. At logout or power off sway goes first and the
game dies with its display:

```bash
journalctl --user -u mcshell-client -b -1 | grep -E "Wayland connection broke|exited"
L=~/.local/share/PrismLauncher/instances/MCShell/minecraft/logs
for f in $(ls -t $L/*.log.gz | head -5); do zcat $f | grep -c "Stopping server"; done   # all 0
```

The fix holds logind back instead. Check the lock is held — it is the whole
mechanism, and a daemon that failed to take it powers off exactly as before:

```bash
systemd-inhibit --list | grep MCShell      # shutdown ... delay
```

Then a save on demand, which exercises the mod without powering anything off.
Needs the client restarted once after `install-mod.sh`, so the new jar is loaded:

```bash
daemon/tools/mcsh '{"t":"save_world"}'      # {"t":"world_saved","ok":true,"ms":...}
grep "saved the world for the daemon" ~/.local/share/PrismLauncher/instances/MCShell/minecraft/logs/latest.log
```

**The real test is a restart**, because `PrepareForShutdown` cannot be faked.
After it, read the *previous* boot's daemon log:

```bash
journalctl --user -u mcshelld -b -1 | grep "shutdown:"
# shutdown: the world is saved (0.xxs); letting the machine go
```

And the game log from that session should show the mod's line before the crash:
`saved the world for the daemon in Nms`. A `no save confirmed` line means the
game did not answer in 4s and the machine went anyway — by design, but worth
knowing.

Tested offline against the real logind: the lock is taken at start, released
after a save, taken back when a shutdown is cancelled, and released anyway when
the game never answers.

## Choosing the world

Every world is its own folder under the instance's `saves/`. The pause menu's
*Give Feedback* button — now **Worlds...** — opens a screen of Realms-style
world slots. Nothing is copied or renamed, so each world keeps its own state.

### 1. The door, and what the screen sees

Esc, then **Worlds...** where *Give Feedback* was. *Report Bugs* is still beside
it. The daemon's side, without the game:

```bash
daemon/tools/mcsh '{"t":"worlds_query"}'
```

Every folder with a `level.dat` should be a slot, four to a page. The chosen
world is darkened with a checkmark, like Realms' active slot; the running one
says *In use*. Island, MCShell and Tutorial World show their own `icon.png`;
Skyblock has none until it is first played, and shows a panorama instead.

### 2. Choose one, then restart into it

Click a bright slot. It takes the checkmark and says *Next start*, and **Restart
into …** lights up.

```bash
cat ~/.config/mcshell/world                    # the choice
cat $XDG_RUNTIME_DIR/mcshell-world.running     # what is actually running
```

Press restart. Expect, in order: a save, the boot screen, the new world — **no
Prism window and no Mojang splash**. In the journal:

```bash
journalctl --user -u mcshelld --since -2min | grep -E "world_saved|restart_game|world is up"
```

Go back to the first world the same way and check what you built there is still
there. That is the whole point: state per world. After Skyblock has been played
once, reopen the screen: its panorama should have become its own preview.

### 3. It survives a reboot, and a bad choice cannot stop the game

A reboot should open the chosen world. And the fallback, which needs no reboot
to check:

```bash
XDG_CONFIG_HOME=/tmp/x sh -c 'mkdir -p /tmp/x/mcshell; echo Atlantis > /tmp/x/mcshell/world;
  . session/prism/common.sh; echo "$MCSHELL_WORLD"'
# warning: the chosen world 'Atlantis' is not there; opening MCShell
# MCShell
```

### 4. The templates

Island, Skyblock and Tutorial World were snapshotted before anyone played them:

```bash
cd ~/.local/share/mcshell/templates && sha256sum -c SHA256SUMS
```

To put one back exactly as it was, with the game stopped or in another world:

```bash
S=~/.local/share/PrismLauncher/instances/MCShell/minecraft/saves
rm -rf "$S/Skyblock" && tar --zstd -xf ~/.local/share/mcshell/templates/Skyblock.tar.zst -C "$S"
```

## A login with no network

Prism used to answer a missing network with a full-screen name prompt, hidden
under the boot screen for 90 seconds. Now `launch.sh` asks first and launches
offline, under your own account name, without a prompt.

### 1. The check, on its own

```bash
session/prism/online.sh; echo $?          # 0 with the wifi up
```

Turn the wifi off (`nmcli radio wifi off`) and run it again: **1**, in well
under a second. `nmcli radio wifi on` afterwards.

### 2. The real thing: a login with the wifi off

1. `nmcli radio wifi off` (and unplug ethernet, if any), then log out.
2. Log in to MCShell.
3. **Expect:** the boot screen as usual, with *No internet connection -
   starting offline* in grey under the map within a couple of seconds, and the
   world at about the usual time. No name prompt, no Prism window.
4. In the world: your inventory and position are what you left. The skin is
   the default one — that is the only thing offline costs.
5. Turn the wifi back on. The next login is online again; nothing is
   remembered.

**If the boot screen sits there anyway**, it is a bug, not your network: run
`journalctl --user -u mcshell-client -b | grep -i offline` — `no network:
launching offline` means `launch.sh` decided correctly and the problem is
later; nothing at all means it thought it was online.

### 3. A launcher question is never hidden

Not something to set up on purpose — it needs an account that has to sign in
again. If it happens, the boot screen comes down by itself the moment Prism
shows anything other than its progress windows, and the daemon's journal says
`the launcher is showing '…'; taking the loading screen down`. The window is
Prism's own and still looks like it.

## A newly installed app appears without a restart

The catalog used to be read once at daemon start. Now it follows installs.

### 1. Install something, then look

1. In a terminal window (`Super+Shift+Return`), install any app you do not
   have: e.g. `sudo pacman -S --noconfirm gnome-mines`, or a Flatpak.
2. **Expect:** within about 5 seconds of the install finishing, open `E` →
   the chest tab → the app's tab (or Search) and it is there, with its own
   icon.
3. Right-click it onto the hotbar and launch it, as with any other app.

### 2. With the catalog already open

1. Open the catalog on the Search tab and type part of the new app's name
   *before* installing it — nothing matches.
2. Install it from the command bar or a terminal, and come back to the open
   screen.
3. **Expect:** it appears in the open screen without retyping or switching
   tabs.

### 3. Uninstall

`sudo pacman -R --noconfirm gnome-mines`: within about 5 seconds it is gone from the
catalog. If it was on the hotbar, the slot keeps the assignment and draws
empty, as it always has for an app that is not installed — reinstalling puts
it back.

**If it does not appear:** `journalctl --user -u mcshelld | grep rescanned`.
A line with `+1 ['…desktop']` means the daemon saw it and the problem is on
screen; no line means the install did not reach an applications directory
the daemon reads (`XDG_DATA_DIRS`). An app with `NoDisplay=true` in its
`.desktop` file is deliberately never listed.

## Applications cannot be dropped

Needs the new jar: `session/prism/install-mod.sh`, then `$mod+Shift+m` to
restart the game.

1. With an application in hand, press `Q`, then `Ctrl+Q`. **Expect:** nothing.
2. Press `E`. Hover an application in the hotbar and press `Q`, then `Ctrl+Q`.
   **Expect:** nothing.
3. Pick an application up and click outside the inventory window, with either
   button. **Expect:** it stays on the cursor. Put it back in a hotbar slot.
4. **Control:** do steps 1–3 with a real item (a block of wood). It drops, as
   in vanilla.
5. Still allowed, and unchanged: moving an application between hotbar slots,
   and carrying one up into the 27 to unassign it.

## `clear` empties the chat

Needs the daemon restarted (`$mod+Shift+d`) and the new jar
(`session/prism/install-mod.sh`, then `$mod+Shift+m`).

1. Type a few commands into chat: `echo one`, `echo two`, `ls`.
2. Type `clear`. **Expect:** the chat is empty — no `$ clear` echo, no
   `[exit 1]`. The same as pressing F3+D.
3. Open chat and press the up arrow. **Expect:** `clear`, then `ls`: typed
   history survives, as it does for F3+D.
4. **Control:** `clear; echo hi` is not the builtin. **Expect:** it goes to
   bash and prints `hi`, with the chat left as it was.

## The game's heap gives memory back

`session/prism/setup.sh` now starts the game with `-Xms128m` instead of
`-Xms512m`, plus three G1 flags that let the heap shrink toward what is alive.
Prism reads them at launch, so they need `setup.sh` and then a game restart.

1. Confirm the flags reached Java:

   ```bash
   J=$(pgrep -n -x java); tr '\0' '\n' </proc/$J/cmdline | grep -E '^-X'
   # expect -Xms128m, -Xmx1024m, and the three -XX: flags
   ```

2. Measure, after the game has been up about fifteen minutes:
   `session/probes/footprint.sh`. **Expect** heap committed near 330MB, not
   519MB. Compare `own`, not `total` — `total` moves when another program
   that shares a library opens or closes.
3. **The part only a person can measure:** play with it. A hitch about once a
   minute — turning the camera, walking — would be the periodic collection,
   and is the reason to put it back. Measured pauses average 2ms.
4. **To put it back:** `git revert` the commit, run `setup.sh`, restart the
   game. Save first — `mcsh '{"t":"save_world"}'` — because a unit restart
   stops the game rather than asking it to save.

Before and after, from a fresh start, sampled at the same uptimes
(2026-10-14):

| uptime | heap committed | game PSS | collections / GC seconds |
|---|---|---|---|
| 4.7 min | 519 → 340 | 1,321 → 1,194 | 33 / 0.22 → 96 / 0.47 |
| 10 min | 519 → 335 | 1,288 → 1,131 | 34 / 0.22 → 116 / 0.51 |
| 16 min | 519 → 333 | 1,248 → 1,110 | 37 / 0.24 → 131 / 0.55 |

## The overlay draws in software

The overlay used to open a GL context on the **Nvidia** card to draw a toast:
glvnd tries Nvidia's EGL before Mesa's. It now uses GTK's cairo renderer.
Loaded by restarting the daemon (`$mod+Shift+d`), which respawns the overlay.

1. Send a toast: `notify-send -a Firefox "Footprint" "cairo"`. **Expect:** the
   usual advancement toast, sliding in from the right, Firefox's icon.
2. Press a volume key a few times. **Expect:** the boss bar, as before.
3. Measure it:

   ```bash
   P=$(pgrep -n -f session/overlay.py)
   awk '/^Pss:/{print $2/1024 " MB"}' /proc/$P/smaps_rollup   # ~78; was ~167
   grep -c nvidia /proc/$P/maps                                 # 0; was 155
   fuser /dev/nvidia*                                           # nothing listed
   ```

4. The boot screen is the surface that redraws most (5 a second). It is
   checked at the next login rather than here: **expect** it to look exactly
   as before. Measured headless: pixel-identical, 13% of a core against 18%.
5. **To put it back:** `systemctl --user set-environment GSK_RENDERER=gl`, then
   `$mod+Shift+d`. Step 3 then shows the Nvidia mappings again — that is the
   control. `systemctl --user unset-environment GSK_RENDERER` undoes it.

## Known rough edges (M8)

Written down so meeting one is recognised rather than rediscovered.

* **A transient application cannot be dragged out.** §6 above. Working as
  designed; irritating in practice. Fixable daemon-side with a suppression
  list if it starts to grate.
* **The selected slot syncs to the server lazily.** Vanilla sends it on the
  next interaction rather than every tick, so for a moment the integrated
  server disagrees about what is held. Nothing observes that in singleplayer.
* **Eight apps still have no icon** and draw the placeholder tile at
  `assets/mcshell/textures/item/app.png`. A letter tile would read better.
* **The Network page cannot do anything that needs typing.** Static IP
  addresses, hidden SSIDs and 802.1X are all out, because no settings row type
  draws a text field and the one field people would want most — a Wi-Fi
  password — is barred from the game client by the credentials rail anyway.
  Everything DHCP does works.
* **The file tree does not notice changes on its own.** Nothing watches the
  filesystem; a directory is re-read when it is opened. Something created while
  its parent is already open appears after closing and reopening that parent,
  not before.
* **The power menu has no Back button.** Four buttons was the specification;
  Escape returns to the pause menu.
* **Restart and Power Off do not warn other applications.** They ask logind,
  which stops the session — the same as `systemctl poweroff` in a terminal. An
  editor with unsaved work gets whatever its own crash handling gives it.
* **A file's kind comes from its name alone.** Nothing is opened and nothing is
  sniffed, so a `.txt` full of JSON draws as text and a script with no
  extension draws as a plain page. Reading every file in a directory to draw a
  picture of it would not be worth the syscalls.
* **The Machine and Storage tabs do not refresh while open.** They are read
  once when the tab opens, which is what "static" means here. Switch away and
  back for a fresh reading.
* **Screen time has no history before today.** Nothing was recording it, and
  reconstructing it from boot logs would have counted every Hyprland session
  too.
* **A level-up still plays its sound.** Only the drawing was taken over, so
  crossing a level boundary chimes with nothing on screen to explain it. In a
  void world with no mobs and no ores there is nothing to grant experience, so
  it takes a command to hear it.
* **A toast body is one line, cut at vanilla's 125px.** That is about twenty
  characters, so most of a Discord message is an ellipsis. Vanilla wraps and
  then alternates between the header and the wrapped title on a 1500ms cycle;
  growing the toast instead would mean nine-slicing a sprite that has no
  `.mcmeta` and is not built to be stretched. A notification is a ping, not
  the message.
* **Notifications only arrive from applications started in this session.**
  The daemon owns the bus name on the session bus, so something launched from
  a different login sees a different bus and its pings go nowhere. Nothing new
  — it is how every notification daemon works.
* **A toast on a second monitor is not tested.** The overlay anchors top-right
  on whatever output the compositor gives it and asks for no particular one.
  Single monitor is the design.
* **The clock has no seconds, and no way to ask for them.** It is pushed once
  a minute; seconds would mean sixty pushes a minute for a line of text nobody
  reads that way.
* **The date's ordinal is English-only.** `strftime` has no ordinal and "1st"
  does not survive translation, so a non-English locale gets `Freitag, Mai 1`
  — the locale's own words in English word order. A locale-correct long date
  needs CLDR.
* **The clock is only visible when Minecraft is.** It is a HUD element and Fork
  A puts application windows above the game, so a full-screen browser hides it.
  The toasts are the thing that draws above every window; a clock up there
  would be a permanent strip of screen this shell has not earned.
* **The notification sound is not previewed except when it is chosen.** There
  is no play button on the row — `action` rows are one button each, and a
  second one that only made a noise was not worth the row.
* **A sound file that is deleted later falls back silently.** The path is
  checked when the daemon loads it, so a missing file reads as "Minecraft
  level-up" on the page — but a file deleted while the daemon is running stays
  named until the next restart, and plays nothing.
* **The file chooser needs a portal.** `xdg-desktop-portal-gtk` answers here;
  on a machine with no portal running the button fails and says so in the log,
  and there is no fallback to zenity because zenity is not installed either.

* **A Wi-Fi password reaches `nmcli` on its command line**, so it is visible in
  `/proc` for the length of that call. Same exposure as every desktop Wi-Fi
  helper; NetworkManager's alternative is registering as a D-Bus secret agent.
  Written down in `network.py` beside the code, so it stays a decision.

* **Binding F2 to anything else cannot be done from the game.** Sway takes the
  key before Minecraft sees it, so the capture never fires. `mcsh set
  controls.new..key F2` is the way round, and it is deliberate that it is
  awkward: F2 is the screenshot key now.
* **A made binding is `exec`, always.** There is no way to bind a Sway command
  — `reload`, `kill`, a workspace switch — from the maker. Those are the binds
  already in the config, which can be moved but not added to, and a maker that
  could write either would need a mode switch for a case nobody has asked for.
* **The command is not checked beyond one word.** `_missing` looks at the first
  token only, and says nothing about `sh -c 'thing | other'` or anything
  reached through a variable. It is advice, not validation.
* **A screenshot of a single window is not offered.** grim can do it and the
  shell does not, because choosing the geometry needs a picker and picking one
  for everybody is what the bind maker exists to avoid.
* **The screenshot key is not `--locked`.** Deliberately: the lock screen is
  not something to be photographed by whoever is standing at the machine.
* **`wl-copy` stays running to own the clipboard.** That is how Wayland
  clipboards work — one process per selection — so a screenshot leaves a
  `wl-copy` behind until something else is copied.

* **Brightness has no popup.** The same machinery would do it — the daemon
  polls the backlight for the Video page — but only volume was asked for, and
  a bar that appeared for one of the two media-key pairs and not the other
  would read as a bug rather than as a scope decision. Written here so it is
  the second.
* **The click is a process per notch.** `pw-play` is spawned for each one, at
  most eleven a second. Cheap, but it is not free, and holding volume-up from
  0 to 100 spawns about twenty of them.
* **A muted sink plays no click.** Correct, and worth knowing before reporting
  it: the sound goes through the sink whose level just changed.
* **The bar is not shown over the lock screen.** The media keys are `--locked`
  and still work, but `ext-session-lock-v1` puts the lock surface above every
  layer, including `overlay`. Nothing to fix; a locked machine should not be
  drawing its volume to whoever is standing at it.
* **The white bar is low contrast on a light background.** It is vanilla's own
  white boss bar — 64-grey track, 185-grey fill — and it reads the way it
  reads in the game. A different colour is one line in `osd.py`.

* **A login cannot be tested without logging out.** Nested sway exercises the
  layout, the daemon and every settings page, but never GDM, the units, or
  `start-session.sh`. Anything changed in those three is untested until Nick
  logs in.
* **`session.log` collects the whole session's stderr**, not just sway's,
  because sway's children inherit it. 359 lines after one ordinary session,
  most of it applications. Fixing it means redirecting the applications — the
  `exec` lines and the daemon's launch path — rather than the log.
* ~~**Prism's launcher window is adopted like an application during boot.**~~
  Still adopted — the daemon fills and focuses it as before — but the boot
  screen is a layer-shell surface above every ordinary window, so it is no
  longer *seen*. Covering it was chosen over hiding it: the adoption path is
  the same one every application uses, and giving it an exception for one
  window would be a special case in the part of the daemon that has fewest.
* ~~**About thirteen seconds of the login have nothing to look at.**~~ Answered
  by the boot screen above. The seconds are unchanged — nothing here made the
  login faster — but they now show one picture that says the shell is coming
  up, instead of three that say nothing.
* **`Restart=on-failure` means a clean quit stays quit.** *Save and Quit* exits
  0, so the client unit does not come back; `$mod+Shift+m` is the way back and
  it is a compositor binding, so it works with the daemon and the game both
  dead.
