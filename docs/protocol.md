# mcshell protocol

Newline-delimited JSON over a unix socket at `$XDG_RUNTIME_DIR/mcshell.sock`.
The daemon listens; the mod connects as a client. Socket mode is `0600`.

`daemon/mcshelld/protocol.py` is the executable copy of this document. **If you
change one, change the other in the same commit.**

Every message is a JSON object with a string `t` field naming its type. Unknown
fields are ignored on decode, so a newer mod talking to an older daemon
degrades rather than disconnecting. An unknown `t`, malformed JSON, or a line
over 1 MiB is an error: the first two get an `error` reply, the last drops the
connection.

Current `proto` version: **1**.

## Mod → daemon

| Message | Fields |
|---|---|
| `hello` | `proto` (int), `mc` (string) |
| `catalog_query` | `text` (string), `tab` (string or null) |
| `slot_assign` | `slot` (int), `app` (string, `.desktop` id) |
| `slot_clear` | `slot` (int) |
| `slots_arrange` | `slots` (object: 1-based slot number → `.desktop` id) |
| `slots_occupied` | `slots` (list of int, 1-based) — slots holding a non-application item |
| `slot_activate` | `slot` (int), `button` (`"left"` \| `"right"` \| `"shift_right"`) |
| `slot_close` | `slot` (int) |
| `command_submit` | `text` (string) — one line of shell; see below |
| `settings_query` | `page` (string or null) — null means every page |
| `setting_set` | `key` (string), `value` (any) |
| `stats_query` | `tab` (`"general"` \| `"disks"`) |
| `stats_watch` | `on` (bool), `sort`, `desc` (bool), `limit` (int) |
| `process_kill` | `pid` (int) |
| `dir_query` | `path` (string, empty = home), `offset` (int), `limit` (int) |
| `power_action` | `action` (`lock` \| `sleep` \| `restart` \| `poweroff`) |
| `overview_set` | `show` (bool) |
| `focus_ack` | `game` (bool) |
| `world_ready` | *(no fields)* — the world is on screen; see below |
| `osd_volume` | *(no fields)* — a volume key was pressed; draw the bar |
| `launch_mode` | `offline` (bool) — from `launch.sh`: the game is starting offline |
| `world_saved` | `id` (int), `ok` (bool), `ms` (int) — the answer to `save_world` |
| `save_world` | *(no fields)* — from a tool such as `mcsh`: save the world now |
| `worlds_query` | *(no fields)* — the Worlds screen opened |
| `world_choose` | `name` (string) — the world the next start opens |
| `world_restart` | *(no fields)* — save, then restart into the chosen world |

```json
{"t":"hello","proto":1,"mc":"1.21.1"}
{"t":"catalog_query","text":"fire","tab":"Browsing"}
{"t":"stats_query","tab":"general"}
{"t":"stats_watch","on":true,"sort":"cpu","desc":true,"limit":128}
{"t":"process_kill","pid":4213}
{"t":"dir_query","path":"/home/you","offset":0,"limit":20}
{"t":"power_action","action":"sleep"}
{"t":"slot_assign","slot":1,"app":"firefox.desktop"}
{"t":"slot_clear","slot":1}
{"t":"slots_arrange","slots":{"1":"firefox.desktop","3":"foot.desktop"}}
{"t":"slots_occupied","slots":[4,5]}
{"t":"slot_activate","slot":1,"button":"right"}
{"t":"slot_activate","slot":1,"button":"shift_right"}
{"t":"slot_close","slot":1}
{"t":"command_submit","text":"git status"}
{"t":"settings_query","page":"audio"}
{"t":"setting_set","key":"audio.sink.volume","value":0.4}
{"t":"overview_set","show":true}
{"t":"focus_ack","game":false}
{"t":"world_ready"}
{"t":"osd_volume"}
{"t":"launch_mode","offline":true}
{"t":"world_saved","id":1,"ok":true,"ms":40}
{"t":"worlds_query"}
{"t":"world_choose","name":"Skyblock"}
{"t":"world_restart"}
```

## Daemon → mod

```json
{"t":"catalog","items":[
  {"id":"firefox.desktop","name":"Firefox",
   "icon_path":"/usr/share/icons/hicolor/48x48/apps/firefox.png",
   "categories":["Network","WebBrowser"],"tab":"Browsing"}]}

{"t":"taskbar","slots":[
  {"i":1,"app":"firefox.desktop","name":"Firefox","icon_path":"...",
   "running":true,"windows":3,"focused":true,"launching":false,
   "transient":false},
  {"i":2,"app":"foot.desktop","name":"foot","icon_path":"...",
   "running":false,"windows":0,"focused":false,"launching":false,
   "transient":false},
  {"i":3,"app":"onlyoffice-desktopeditors.desktop","name":"ONLYOFFICE",
   "icon_path":"...","running":true,"windows":1,"focused":false,
   "launching":false,"transient":true}]}

{"t":"command_start","cmd":7,"text":"git status","cwd":"/home/you/dev/mcshell"}
{"t":"output","cmd":7,"lines":["..."],"stream":"stdout"}
{"t":"command_end","cmd":7,"code":0,"note":""}
{"t":"chat_clear","cmd":8}
{"t":"overview","show":true}
{"t":"focus","game":false}
{"t":"battery","present":true,"percent":80,"charging":false,"mains":true}
{"t":"hud","clock":true,"time":"1:27 PM","date":"Friday, May 1st","battery_color":true}

{"t":"stats","tab":"general","rows":[
  {"label":"OS","value":"Arch Linux x86_64","group":"System","detail":"","fraction":null},
  {"label":"/","value":"24.2 GB of 29.4 GB","group":"Filesystems",
   "detail":"/dev/nvme0n1p2 · ext4","fraction":0.82}]}

{"t":"processes","cpu":24.4,"cores":[13.1,13.9],"mem_used":6300000000,
 "mem_total":16400000000,"swap_used":0,"swap_total":4100000000,
 "load":[2.93,2.18,1.31],"count":346,"procs":[
  {"pid":31416,"name":"brave","cmd":"/opt/brave-bin/brave","user":"nick",
   "cpu":14.1,"mem":4.2,"rss":582000000,"protected":false}]}

{"t":"dir","path":"/home/you","name":"you","total":19,"hidden":21,"offset":0,
 "error":"","entries":[
  {"name":"Documents","path":"/home/you/Documents","kind":"dir"},
  {"name":"notes.md","path":"/home/you/notes.md","kind":"text"},
  {"name":"tax.pdf","path":"/home/you/tax.pdf","kind":"pdf"}]}
{"t":"settings_schema","page":"audio","items":[
  {"key":"audio.sink.volume","type":"float","label":"Volume","group":"Output",
   "page":"audio","value":0.57,"min":0,"max":1,"step":0.01,"unit":"%"},
  {"key":"audio.sink.default","type":"enum","label":"Output device",
   "page":"audio","group":"Output","value":"alsa_output...Speaker__sink",
   "options":[{"id":"alsa_output...Speaker__sink","label":"Speakers"}]}]}
```

`transient` marks a slot nobody assigned. An application running with no slot
of its own is shown in the first free one, for as long as it is open — a file
opened by its handler, or an app whose slot was reassigned while it was still
running. Without it the hotbar describes what someone once chose rather than
what is running, and an application can be open with nothing on screen
admitting it. It behaves like any other slot when clicked; it is simply never
written to disk, and `slot_clear` on one is an error rather than a silent
no-op. Nine slots is nine slots: with the hotbar full, a further application
gets no icon rather than evicting a choice the user made.

### `name`

What the application calls itself, from its `.desktop` file. The hotbar slot is
a real item and this is the name it is held under, so it is what the tooltip
says on hover.

Null for a slot assigned to something no longer installed — there is no
`.desktop` file left to ask. The mod falls back to the desktop id, on the
grounds that `libreoffice-calc.desktop` under a broken slot is more use than a
blank label.

Icons are **filesystem paths, never base64**. Same machine; the mod loads the
path directly and caches the resulting texture keyed on path.

The path always points at a raster image the mod can open. The mod loads icons
with `NativeImage`, which cannot rasterise vectors, so an SVG-only icon is
rendered to a cached PNG under `$XDG_CACHE_HOME/mcshell/icons` and *that* path
is sent. `icon_path` may still be null when the app declares an icon that is not
installed; the mod draws a placeholder.

### `tab`

The creative-mode tab an app belongs in, derived by the daemon from
`categories`. Sent in addition to the raw categories so the mod never owns the
mapping — that would be a decision living in the mod. Values: `Games`,
`Browsing`, `Productivity`, `Media`, `Tech`, `Misc`. Anything unrecognised falls
back to `Misc`.

Deliberately not the freedesktop main categories: those are written for menu
editors, and call a browser "Network" and a terminal "System". The
priority-ordered mapping is `TAB_PRIORITY` in `catalog.py`.

The mod adds a **Search** tab of its own. It is not a category and is never sent
as one — it queries with `text` and no `tab`.

### `catalog` also arrives unasked

When an application is installed or removed while the shell is up, the daemon
rebuilds its catalog and answers each client's **last** `catalog_query` again,
without being asked. Nothing new on the wire: it is the same message, and the
mod already draws whichever `catalog` arrived last. A client that has never
queried is sent nothing. A fresh `taskbar` follows, because the catalog is
also how windows are matched to apps.

### `launching`

The slot has been activated and the app spawned, but no window has appeared
yet. Drawn dimmed. Cleared when a matching window maps, or abandoned after 25
seconds if none ever does.

### `slots_arrange`

The hotbar as the player has just arranged it by hand.

The nine slots are real Minecraft items, so an application can be dragged to
another slot, shift-clicked into storage, swapped with a number key, or thrown
out of the window — all of it ordinary inventory handling. The mod does not
interpret any of those gestures. It notices, on the tick afterwards, that the
hotbar no longer holds what it wrote, and reports what it holds instead. Every
way of moving a stack is covered by covering none of them specifically.

An **observation, not an instruction**. The daemon diffs it against the taskbar
it last built and acts only on what actually moved:

* an application in a slot it was not in is assigned there — including a
  transient one, since dragging an application somewhere is precisely the
  deliberate act a transient slot is defined as lacking;
* a slot the player emptied is cleared, unless it was only ever transient.
  There is no assignment to remove, the application is still running, and so it
  reappears in the first free slot. Nine slots is nine slots.

The whole picture is sent rather than a move, which is what makes it safe to
drop one: the next report is absolute, not a delta against a state the two ends
could disagree about. The reply is an ordinary `taskbar`, so anything the daemon
refuses is put back by the reconcile it triggers.

An application stack is **atomic** and the mod enforces that before any of this:
a right-click split, a drag-to-distribute, a double-click gather and a
single-item throw are all refused, because the stack count is the window count
and half a window is not a thing. Whole-stack moves are all allowed. `Q` is
refused on an application as well — dragging one out of the hotbar is deliberate
enough to mean it, a keypress with the world in front of you is not.

### `slots_occupied`

Which hotbar slots hold something that is not an application.

The hotbar is a real Minecraft inventory, so a slot can be full of wood, and the
daemon cannot see that. It matters when a running application nobody assigned
needs somewhere to go: an occupied slot is a worse home than an empty one,
because putting an application there costs the player a shuffle into storage —
or, with all 36 slots full, an item dropped on the floor.

So the daemon prefers empty slots and disturbs an occupied one only when there
is no empty one left. Slot order still decides within each group.

Sent whenever the set changes, and again whenever the mod reconnects: a
restarted daemon has forgotten, and this is only ever sent on a change, so a
slot that has not moved since would otherwise never be mentioned again.

### `slot_activate`

Three values, because a slot has three things it can be asked to do.

`right` focuses the app, or launches it if nothing is running — the window it
returns to is the one you were last in, not the app's oldest. `left` cycles
through that app's windows, and is an error when the app is not running:
launching there would make the two buttons identical.

`shift_right` launches another one whether or not the app is already running.
Without it the hotbar could only ever start an app's *first* window; a second
had to come from the app's own File > New Window, or from a trailing `&` in the
command bar, neither of which is the hotbar. Shift is the modifier because
right-click already means "launch if not running", so shift+right reads as
launch anyway, and because shift is already the guard on the only other thing a
slot can be asked to do. A double-click was the other candidate and does not
work here: left-click cycles, so a double-click would have to cycle once on its
way to meaning something else.

A cold start dims the slot while the window is on its way (see `launching`); a
second window does not, because the app is already drawn as running. What a
second launch *means* is the app's decision — a single-instance app may open a
window or may just raise the one it has.

### `overview_set` and `overview`

`overview_set` is the input side of the `overview` push, and the one message in
the mod → daemon table that CLAUDE.md does not list. Without it nothing would
ever produce an `overview`. It is bound to Super in the Sway config, so raising
Minecraft and opening the overview are one keystroke:

```
bindsym $mod exec swaymsg '[class="(?i)minecraft.*"] focus'; mcsh overview
```

The daemon does not interpret it — it rebroadcasts it verbatim as `overview` to
every client and echoes it to the sender.

`show` is absolute, never a toggle. The player can close the overview with
Escape without telling anyone, so the daemon cannot know whether it is open, and
a toggle would desynchronise the first time that happened. Re-showing an open
overview is a no-op.

### `focus`

Whether the compositor's focus is on Minecraft. Outbound only — nothing the mod
can send produces it, and the mod never argues with it.

Minecraft is an X client under XWayland, and X takes focus away from it only
when another *X* client takes focus. Move to a native Wayland window and the
game still believes it is focused, so it goes on holding the pointer; because an
X grab is server-wide, that also swallows the button presses of every other X
application. The result reads as a window you can type into but not click.

Sway knows, and the daemon is watching it for the taskbar anyway, so the daemon
answers. Sent on the change only, since every window event asks the question and
most of them do not move focus, and once more on `hello` so a reconnecting mod
does not sit on a stale answer.

`game:false` releases the cursor. `game:true` re-takes it, but only with no
screen open — raising the game while the overview is up must not grab the
pointer out from under the panel being read.

The mod answers each one with `focus_ack`, and the daemon waits for it — up to
250ms — before it moves the compositor's focus. That order is the whole point.
GLFW gives an X pointer grab back only while X still says the game is the
focused window; once Sway has moved focus, the ungrab is skipped and the grab is
stranded. The camera stops turning, which looks like a fix, while X goes on
delivering every other X client's clicks to a window that is not listening.
Measured both ways: release first and an XWayland window receives all of its
clicks, release after and it receives none.

### The command bar

`command_submit` carries one line typed into Minecraft's chat. Every plain chat
line is one — the mod cancels the outgoing message and sends this instead.
Minecraft's own slash commands are untouched and never reach the daemon.

The answer is three messages, broadcast to **every** client rather than replied
to the sender, so a command typed into `mcsh` echoes in Minecraft's chat and one
typed in chat is visible to a tailing `mcsh`. They are the same shell, seen from
two places.

| Message | Direction | Fields |
|---|---|---|
| `command_submit` | mod → daemon | `text` (string) |
| `command_start` | daemon → mod | `cmd` (int), `text` (string), `cwd` (string) |
| `output` | daemon → mod | `cmd` (int), `lines` (list of string), `stream` |
| `command_end` | daemon → mod | `cmd` (int), `code` (int), `note` (string) |
| `chat_clear` | daemon → mod | `cmd` (int) |

`cmd` numbers the run, counting from 1 within a daemon lifetime. It exists
because output **streams**: lines are sent as they are produced, so a slow build
scrolls rather than hanging, and without a run number the mod could not tell
which lines belong together.

That grouping is what makes the hybrid rule work. The mod holds a run's lines
until `command_end`: five or fewer go to Minecraft's chat, more open the
scrolling panel in the overview. A run that crosses five lines while still
running opens the panel immediately and fills it live — the threshold is
decided by the mod, and the daemon emits the same messages either way.

Ordering within one `cmd` is guaranteed: `command_start`, then every `output`,
then `command_end`. Two commands cannot interleave; the daemon runs one at a
time and a second submission while one is running is refused with an `error`.

`stream` is `"stdout"` or `"stderr"`. They are separate messages, so the mod can
colour them differently; interleaving between the two is not preserved.

Lines are ready to draw: ANSI escapes and other control characters are stripped
by the daemon, since the mod draws Minecraft text and this is not a terminal
emulator. Lines longer than 512 characters are cut, and a run stops forwarding
after 2000 lines — `note` on `command_end` says so. Both caps also keep a run's
output under the 1 MiB wire-line limit.

#### `note` and `code`

`code` is the process exit status, or negative for a signal (`-15` when the
60-second timeout terminates it). `note` is empty for an ordinary exit and
otherwise says in words why the run ended: `timed out after 60s`,
`output truncated at 2000 lines`, `launched`.

#### Trailing `&`, `cd`, and `clear`

Three things the daemon handles itself rather than handing to `bash`:

- A command ending in `&` is **detached**: it goes to Sway's `exec`, the same
  path a hotbar slot launch takes, so the app belongs to the compositor and
  outlives a daemon restart. Nothing is captured; `command_end` arrives at once
  with `note` `launched`. This is how you start a GUI program that has no
  `.desktop` file.
- `cd` is a builtin. The daemon keeps one working directory, starting at
  `$HOME`, and every later command runs there. `cd` with no argument goes home,
  `cd -` returns to the previous directory, and the new path is reported as a
  single output line. A `cd` handled by `bash` would change a directory that
  ceases to exist a moment later, which would make the bar quietly lie.
- `clear`, alone on the line, empties Minecraft's chat the way F3+D does:
  `chat_clear` arrives between that run's `command_start` and `command_end`,
  so the echoed `$ clear` is cleared with everything else. Typed history (the
  up arrow) is kept. Handed to `bash` it would exit 1 — there is no terminal
  to clear — and leave the chat as it was.

Everything else runs as `bash -lc <text>` with stdin on `/dev/null`. A login
shell because the daemon may be started from a Sway `exec` with a thin
environment, and `/dev/null` because there is no PTY: a command that reads stdin
gets EOF rather than hanging forever.

The same absence of a PTY is why `sudo` cannot ask for a password on its own, so
the daemon exports `SUDO_ASKPASS` and prepends a `sudo` function that adds `-A`
unless the line already picked how to authenticate. The prompt is then a
compositor window. `command_start.text` is still the line as typed — the shim is
prepended to what bash runs, not to what the mod echoes.

### Settings

`settings_query` pulls a page; `settings_schema` answers, and is pushed again
whenever anything on that page changes. `setting_set` changes one row.

The schema carries **shape and current value together**. They change for the
same reasons — plug in headphones and there is both a new device in the list
and a new default selected — so two messages would only ever be right when
they agreed with each other. Rebuilding a page is cheap; a page is tens of
rows, not thousands.

| Field | Meaning |
|---|---|
| `key` | Opaque id, sent back by `setting_set`. Namespaced: `audio.sink.volume` |
| `type` | `float`, `int`, `bool`, `enum`, `keybind`, `action`, `text`, `label` |
| `label` | What to draw |
| `page` | `audio`, `video`, `controls`, `network`, `general` — which vanilla screen it sits beside |
| `group` | Subheading within the page: `Output`, `Input`, `Applications` |
| `value` | Current value. A float, a bool, or an option `id` for an enum |
| `default` | What Reset restores. Absent means the row has no default |
| `min` / `max` / `step` | Numbers only |
| `unit` | `"%"` means draw the value as a percentage |
| `options` | `enum` only: `{"id": ..., "label": ...}`, in the order to show them |
| `detail` | Secondary line — a device's real name under its friendly one |
| `enabled` | False draws the row greyed and refuses input |
| `placeholder` | `text` only: what an empty field says it wants |
| `extra_label` / `extra_key` | An extra button at the end of the row, and the key it sets to true |

`unit: "%"` keeps the wire value at 0..1 rather than 0..100 because that is
what Minecraft's own sliders hold internally, so the mod scales for the label
and nothing else. A slider drag is local until release: the mod sends one
`setting_set`, not one per frame.

The mod never learns what a key *means*. It draws a row of the type it was
given and sends the key back with a new value, which is what makes a new
setting a daemon-side change — the promise M6 is built on.

An unknown key, or a value of the wrong type, gets an `error` reply and
changes nothing. The refreshed schema is broadcast to every client, so a
volume changed from `mcsh` moves the slider in Minecraft.

#### `keybind`

A row whose value is a key combination, written the way Sway writes it —
`Mod4+Shift+Return`, already prettified to `Super+Shift+Return` for drawing.

Setting one is the one place a value is not a plain scalar. The mod sends what
the keyboard gave it and nothing more:

```json
{"t":"setting_set","key":"controls.4f2a91c3.key","value":{"glfw":257,"mods":8}}
```

`glfw` is the raw GLFW key code and `mods` its modifier bitmask (1 shift,
2 control, 4 alt, 8 super). The daemon turns that into a keysym. Doing it in
the mod would put a second, quietly diverging table of key names on the far
side of the socket — the mod does not know what a keysym is and should not
learn.

`default` on a keybind row is the key the Sway config gives it. Reset is drawn
disabled while the two agree, and clicking it sends the default back as an
ordinary `setting_set` — there is no separate reset message, because there does
not need to be one.

A string is accepted too, so a binding can be set from `mcsh`:

```bash
mcsh set controls.4f2a91c3.key Mod4+t
```

A combination already bound to something else is refused, naming what has it.

The `controls.` prefix is load-bearing rather than cosmetic. A `setting_set` is
routed to a provider by the key's **first segment**, and a provider is
registered under its page name — so a Controls row keyed `binds.…` is a row
nothing can answer for. It was exactly that until it was measured, and every
rebind was silently refused with *no page owns*.

#### `text`

A row whose value is a line the player types. Vanilla's own `TextFieldWidget`,
laid out like a `keybind` row: the name on the left, the field filling the rest.

It reports on **Enter, on losing focus, and on leaving the screen** — not on
every keystroke. An accepted `setting_set` re-pushes the whole page, so a
per-keystroke row would rebuild the widget being typed into, a character at a
time. For the same reason the mod holds off applying a push while a field has
focus; the push is not dropped, it lands as soon as the field is let go.

```json
{"t":"setting_set","key":"controls.new..command","value":"flameshot gui"}
```

#### `extra_label` / `extra_key`

A second button at the right-hand end of any row, in the column Reset uses.
Pressing it sends `{"key": <extra_key>, "value": true}` — it is an `action` row
that happens to share a line with something else, and the mod learns nothing
about what it does. Reset and an extra cannot both appear, and nothing wants
both: Reset means *back to what the config says*, and only a row that came from
the config has one.

#### Pushes without a query

Settings change behind the shell's back: a media key, a headset connecting,
another mixer. The daemon watches for that (`pactl subscribe` for audio) and
re-pushes the affected page, so an open settings screen follows along instead
of showing what was true when it opened.

### `battery`

The XP bar is the machine's battery gauge: the bar fills with charge and the
level reads `80%`. The shell has nowhere else to put one, and a laptop you
have to guess about is a bad laptop.

| Field | Meaning |
|---|---|
| `present` | False on a machine with no battery |
| `percent` | 0–100 |
| `charging` | Current is actually going in |
| `mains` | A cable is plugged in — not the same thing |

`charging` and `mains` are separate because they genuinely differ. A battery
held at a charge limit reports "Not charging" while plugged in, which is a
laptop's normal state all day; treating that as discharging would be wrong
every time the machine was on a cable. The mod colours the number white
whenever either is true, green on the battery, and red below 15% only when
there is no cable — a warning to go and find a charger is pointless when one
is already attached.

`present: false` means the mod draws **Minecraft's own** experience bar
instead. No gauge is better than a gauge for a thing that does not exist.

Minecraft's experience is untouched by any of this. Orbs are still collected
and levels still accrue; the HUD simply stops drawing them, so picking up
experience cannot move the battery gauge and the two can never disagree on
screen.

Pushed on connect, and again whenever the reading changes — never on a timer
that finds nothing new. The daemon polls sysfs every five seconds, which is
four file reads and no subprocess.

### `hud`

Everything the HUD draws that has no message of its own. Two things so far,
and they have nothing to do with each other beyond being the same *kind* of
thing — preferences about drawing, where the mod owns the pixels and neither
the value nor the decision. A message per checkbox would be a message per
checkbox forever.

| Field | Meaning |
|---|---|
| `clock` | Draw the wall clock at the top of the screen |
| `time` | `"1:27 PM"` or `"13:27"`, already formatted |
| `date` | `"Friday, May 1st"` |
| `battery_color` | False pins the battery gauge green |

**The strings are formatted by the daemon, not the mod.** "Read the system
locale" means glibc's locale, which is what `strftime` and `nl_langinfo`
answer for; the JVM has its own idea of a default locale, taken from the same
environment but mapped through its own tables, and the two disagree often
enough to matter. Sending the string also means the clock is pushed once a
minute rather than rebuilt sixty times a second.

Seconds are not sent and not drawn. A clock that ticks is a clock that has to
be pushed sixty times a minute, and vanilla's HUD is not a place anybody reads
seconds off.

Pushed on connect, on the minute (slept to the boundary, so the display
changes when the minute does), and whenever a row on the General page moves.

`battery_color` is the one field here whose absence means *true*: a mod
talking to a daemon that predates it should leave the gauge doing what it
always did.

### Statistics

Three tabs, standing where Minecraft's three stood. `stats_query` pulls a
static one — `general` or `disks` — and `stats` answers with rows of label,
value and an optional `detail` line. `fraction` (0..1) asks for a usage bar;
absent means none.

The live tab is different, because sampling every process on the machine
costs the daemon about 23ms:

```
stats_watch {on: true, sort, desc, limit}   → processes, once a second
stats_watch {on: false}                     → silence
```

Nothing is sampled until a client asks, and the stream stops when the last
watcher goes away — including by disconnecting, which is the case that
matters, since a mod that crashes cannot send an `off`.

**Sorting is the daemon's job.** A machine has hundreds of processes and a
screen has room for tens, so the mod says which order it wants and gets back
only `limit` rows. Sorting in the mod would mean shipping all of them every
second in order to draw a fraction of them. Clicking a column header is a
fresh `stats_watch`.

`cpu` on a process row is a share of the **whole machine**, not of one core,
so the column sums to the gauge above it.

`protected` marks the processes the shell is standing on: init, the
compositor, this daemon, and the game. The mod greys the kill button for
them and `process_kill` refuses them regardless — a client is not to be
trusted with that. The game is identified by `SO_PEERCRED` on its own socket
rather than by its command line, which would also have protected every other
Java program on the machine.

`process_kill` sends **SIGTERM only**. It is a request, like `slot_close`: a
program that wants to save something first is allowed to. It answers `ok`,
or an `error` naming why — a protected process, another user's process, or
one that had already exited.

### Directories

The Advancements screen is a file tree, so it needs one directory at a time
and nothing else. `dir_query` asks; `dir` answers.

```
dir_query {path: "", offset: 0, limit: 20}   → dir, for the home directory
dir_query {path, offset, limit}              → dir, for one of its children
```

Directories come first, then files, each alphabetically. `kind` is `dir`, or
what kind of file it is — `text`, `pdf`, `image`, `audio`, `code`, and the rest
of the table in `files.py`, falling back to `file`. Files are there so that a
directory with things in it does not draw as an empty one; they are leaves and
nothing opens them.

**The kind is the daemon's decision, not the mod's.** An extension table is
data, and it lives beside the catalog's category table for the same reason.
The mod holds one texture per kind and falls back to a plain page, so a kind it
has never heard of costs a generic icon rather than a missing-texture tile.

Directory paths come back **resolved**, so a symlink reports where it actually
went and two routes to one directory cannot become two nodes that disagree.
File paths are not: a file is a leaf, resolving one would cost a syscall each,
and it would rename the thing the user is looking at.

`total` counts every visible entry and `offset` says where this page
starts, which is what lets the screen offer a step to the next one rather than
dropping two hundred children into a column five thousand pixels tall. An
offset past the end returns an empty page; it is **not** clamped back into
range, so a step forward cannot silently walk backwards when a directory
shrinks between two queries.

`hidden` counts the dotted entries left out. They are reported rather than
silently dropped: a home directory has dozens of them, they would outnumber
what anybody came looking for on the very first click, and a tree that showed
neither them nor their number would be lying about the machine.

`error` is why there is nothing here — `permission denied`, `not a directory`,
or whatever the kernel said. A node with an error stays a leaf.

Nothing is cached on either side. A directory read is a syscall, and the
answer stops being true the moment somebody saves a file.

### Power

```
power_action {action: "lock" | "sleep" | "restart" | "poweroff"}   → ok
```

What the pause menu's *Save and Quit to Title* button opens. Anything else in
`action` is refused, and only one action runs at a time.

**`ok` means accepted, not finished.** `dispatch` is awaited on the client's
own socket — the one the pointer handshake goes down — so waiting three
seconds for a lock screen to appear there would stall the shell. The work runs
in the background and a failure comes back afterwards as an `error`, which the
screen shows like any other.

`sleep` locks before it suspends, and suspends anyway if the lock will not come
up. The lock screen is started through Sway's `exec` rather than as a child of
the daemon: `$mod+Shift+d` restarts the daemon, and a lock screen that dies
with it is not a lock screen.

### Taskbar delivery

`taskbar` is pushed unsolicited whenever slot or window state actually changes
— the mod does not poll for it. It is also sent once immediately after `hello`,
so a mod reconnecting to a restarted daemon renders straight away.

A client that triggers a slot action receives the resulting taskbar twice: once
as the direct reply to its message, and once as the broadcast that goes to every
connected client. The taskbar is a full state snapshot, so applying it twice is
a no-op.

Pushes are suppressed when the new taskbar is byte-identical to the last one
sent. Sway emits several events per launch, and a window title changes on every
shell prompt redraw; without this the mod would receive a burst of identical
messages per launch and a steady trickle from any open terminal.

## M0 scaffolding

Not part of the design above. These exist so the daemon can be driven and
inspected from `mcsh` before the real surfaces are built. `windows` is expected
to be superseded by `taskbar` once slot state lands in M1.

| Message | Direction | Fields |
|---|---|---|
| `ping` | mod → daemon | — |
| `pong` | daemon → mod | — |
| `windows_query` | mod → daemon | — |
| `windows` | daemon → mod | `windows` (list of window objects) |
| `taskbar_query` | mod → daemon | — (pull the taskbar; the mod gets it pushed) |
| `ok` | daemon → mod | — |
| `error` | daemon → mod | `message` (string) |

A window object:

```json
{"con_id":12,"app_id":"firefox","title":"Example — Mozilla Firefox",
 "workspace":"1","focused":true,"pid":4821}
```

`app_id` is Sway's `app_id` for Wayland clients, falling back to
`window_class` for XWayland. Windows are matched on this, **never on PID** —
Firefox and other multi-process apps fork, so the PID the daemon spawns does
not own the window that appears. `pid` is reported for diagnostics only.

## `world_ready`, and the boot screen

Sent once per **connection** when the world is on screen. It is the only thing
that ends the boot screen normally.

From the moment the daemon starts it draws a full-screen layer-shell surface
over the whole output — Minecraft's world-generation screen, out of the client
jar's own dirt, font and chunk colours, with the shell's logo above it. It
covers the three unrelated pictures a login used to show: sway's flat
`#1a1a2e`, then Prism's launcher window, then Minecraft's Mojang splash. See
`session/loading.py` and CLAUDE.md's *From login to desktop*.

The percentage on it is an estimate, and nothing else can turn it into a fact.
`hello` arrives while the client is still loading a world, and the compositor
has seen Minecraft's window for twenty seconds by then — the game is the only
thing that knows when there is finally a desktop behind the screen. So the
number is interpolated against how long *this machine's last boot* took, pinned
up by real events as they land (the daemon listening, the backdrop being
mapped, `hello`), capped at **99%**, and only this message may finish it.

**Once per connection, not once per run**, because `$mod+Shift+d` restarts the
daemon and a fresh daemon knows nothing about the desktop that is already
there. The mod re-sends on reconnect; the daemon independently cancels the
screen if Minecraft's window is already mapped at its first sync. Two locks on
one door, because the failure is a full-screen surface over a working desktop.

There is a timeout as well — 90 seconds — so a boot that never finishes takes
the screen down rather than hiding the session behind it. The sway safety rails
work throughout regardless: the surface takes no keyboard and its input region
is empty, so clicks pass through it.

## `osd_volume`, and the press that changes nothing

Sent by `session/volume.sh`, which is what the media keys are bound to. It does
**not** mean "set the volume" — the key already did that, straight through
`wpctl`, before this was sent. It means only that somebody pressed a key.

The volume popup is normally drawn from the daemon's `pactl subscribe` feed,
which is what lets the command bar, the Sound page's slider, a headset wheel
and the media key all draw the same bar. Measured, per action:

| | sink events |
|---|---|
| a real change | 1 |
| `5%-` while already at 0 | **0** |
| `5%+` while already at 100% | **0** |
| mute while already muted | **0** |

PipeWire says nothing when the value does not move, so at the extremes the
subscription has nothing to react to and the key looks unresponsive rather than
already-at-its-limit. This is the only path that can tell the daemon otherwise.

The daemon reads the level itself and draws whatever it finds — the message
carries no value, because the sender does not know one and should not. It is
debounced like the subscription is: a held key repeats, and the answer is the
same bar every time.

## `launch_mode`, and a login with no network

Sent by `session/prism/launch.sh`, not by the mod, when `online.sh` found no
network and the game is being launched with `--offline`. Only ever sent as
`{"t":"launch_mode","offline":true}`; online is the default and needs no
message. Best effort, one line and close, like `osd_volume`: the game starts
whether or not the daemon hears it.

The daemon puts one line under the boot screen's map saying the game is
starting offline. After the boot is over it is ignored — a game restarted from
the Worlds screen gets a new boot screen, and `launch.sh` runs again and says
it again.

## `save_world` / `world_saved`, and power off

Daemon to mod: `{"t":"save_world","id":1}`. The mod runs what vanilla's
`/save-all flush` runs — `MinecraftServer.saveAll(false, true, true)`, player
data and then every chunk, flushed — on the server thread, and answers
`{"t":"world_saved","id":1,"ok":true,"ms":40}`.

It is sent before the machine powers off or restarts. The daemon holds a logind
*delay* inhibitor (`systemd-inhibit --list` shows it as `MCShell`); logind sends
`PrepareForShutdown(true)`, the daemon asks for the save, waits up to 4s for the
answer, and releases the lock. logind's own cap here is 5s.

Nothing else could save it. At logout or power off sway goes first, and the game
dies with its display — the journal reads `The Wayland connection broke` and the
unit exits 255. Every game log before this ended partway through an autosave with
no `Stopping server`.

**It goes only to the connection that said `hello`**, never broadcast. The
first version broadcast it, and `mcsh` — itself a client — read its own
`save_world` back as the reply and exited before the answer arrived.

A client may also send `{"t":"save_world"}` (no id). The daemon runs the same
save and replies `world_saved`; no game connected is `ok: false` at once.

## The Worlds screen: `worlds_query`, `worlds`, `world_choose`, `world_restart`

The pause menu's *Give Feedback* button opens it. Each world is a folder under
the instance's `saves/`, and every world keeps its own state, so choosing one
only changes which folder the next start opens.

```json
{"t":"worlds","chosen":"Skyblock","running":"MCShell","worlds":[
  {"name":"Island","icon":"/…/saves/Island/icon.png","icon_version":1789345369},
  {"name":"Skyblock","icon":"","icon_version":0}]}
```

- `worlds_query` is answered with `worlds`. So is `world_choose`, or with an
  `error` if no such world exists. The choice is written to
  `~/.config/mcshell/world`, which the launcher reads on its own.
- `icon` is a path, never image data, and `""` for a world nobody has played:
  Minecraft writes `icon.png` the first time. `icon_version` is its mtime, so a
  texture cached by path is reloaded when the game rewrites the file.
- `chosen` and `running` differ after a choice until the game restarts.
  `running` is `""` when the launcher has not recorded it.
- `world_restart` is answered `ok` at once and done in the background — save,
  boot screen, restart `mcshell-client` — because the save can take four seconds
  and this socket carries the pointer handshake. It is refused when the chosen
  world is already running.
