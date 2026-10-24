# Resolved questions

Questions that were open, how each was settled, and what was rejected on the way.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## Resolved

- **Template worlds** (M9): *three ship in the repo, with no player in them,
  and Tutorial World is the default.* A template is a pristine world that
  ships with the shell; `session/prism/seed-worlds.sh`, run by `setup.sh`,
  copies each into `saves/` once and never over a world of the same name.
  The snapshots of Island, Skyblock and Tutorial World (2026-09-13) are final
  and are never edited: `templates/build.py` derives what ships from them,
  verified against their recorded sums.
  - **No player is installed.** All three began as copies of the played
    `MCShell` world, so each carried its player — two UUIDs of `playerdata`,
    `advancements` and `stats`, and a `Player` compound in `level.dat` with a
    hotbar of `mcshell:app` stacks. All of that is left out, `level.dat_old`
    too. Measured: neither UUID appears anywhere in the shipped worlds,
    across every decompressed chunk, where the same search finds them in the
    snapshots.
  - **`LevelName` is the folder's name.** It was `MCShell` in all three.
  - **In the repo, not git-lfs or a release asset**: ~650KB in all, and
    final, so history growth is the only cost and it is paid once.
  - **No "new from template" in the picker.** That is new behaviour, and M9
    has none. A fresh copy is a re-run of `seed-worlds.sh` after moving the
    old one aside.
  - The old `MCShell` default had no pristine copy at all; it was already
    played when the snapshots were taken.

- **What is on screen between the login and the world?** (M8): *the
  world-generation screen.* One picture over the whole login — sway's flat
  colour, Prism's launcher and Minecraft's splash — drawn out of the client
  jar on a layer-shell surface, with the shell's logo above the chunk map and
  a percentage estimated against the last boot. The seconds are unchanged;
  nothing here made the login faster. See the section above.

  Rejected on the way: hiding Prism's window rather than covering it (a
  special case in the adoption path every application shares), and a smoothly
  animating bar with nothing behind it (the same reason a machine with no
  battery gets no XP gauge rather than a made-up one).

- **How does the game let go of the mouse?** (M7): *the daemon asks it to, and
  waits.* Minecraft runs under XWayland, where a pointer grab is server-wide, so
  a game that will not let go eats the button presses of every other X client
  while still letting them see motion — a window you can type into and cannot
  click. Two things had to be true and neither was obvious.
  - The mod cannot notice on its own. GLFW reports a lost focus only when
    another *X* client takes it, so focusing anything native Wayland — a file
    manager, a terminal, most of the desktop — left the game certain it was
    still focused. Sway knows, so the daemon says: the `focus` message.
  - **The order is load-bearing.** GLFW hands the grab back only while X still
    says the game is focused; the ungrab sits inside that test. A release sent
    after Sway has moved focus is silently skipped and the grab is stranded —
    the camera stops, which reads as a fix, while the clicks keep vanishing.
    So the daemon sends `focus`, waits for `focus_ack` (capped at 250ms, since a
    client loading a world must not be able to stall the shell), and only then
    focuses. `Daemon.yield_pointer` and `MCShellClient.followWindowFocus`.

  Rejected: releasing on GLFW's focus callback alone (blind to native Wayland),
  and forcing GLFW through a cursor-mode cycle to make it let go (measured: it
  does not, once X focus has moved). Both were shipped and both were wrong.

- **Does a bare Super binding misfire after Super is used as a modifier?** (M7):
  *no.* A bare modifier can only be bound on release, and whether Sway then
  suppresses that release after a `$mod`+drag or `$mod+f` is undocumented and
  could not be tested headless. Measured in the real session: it does not
  misfire. `bindsym --release Super_L` is the binding CLAUDE.md's display model
  asks for, and `$mod+o` stays bound as a second way in.

- **greetd, or the display manager already installed?** (M7): *GDM.* The
  milestone's requirement is a second session entry with Hyprland still
  selectable, and GDM's session picker already provides exactly that — MCShell
  is one file in `/usr/share/wayland-sessions/`. Replacing a working display
  manager is the single change in this project that could cost a login rather
  than a session pick, and it buys nothing the requirement asks for.

- **`wpctl` or `pactl` for audio?** (M6): *`pactl`.* The diagram above said
  `wpctl`, and this is the one place M6 departs from it. `pactl --format=json`
  hands over sinks, sources, per-application streams and card profiles as
  parsed data; `wpctl status` prints a box-drawing tree meant for people, and
  scraping it would put a fragile parser between the daemon and the truth.
  `pactl subscribe` also streams a line on every change, which is what lets an
  open settings page follow a media key instead of polling. Both talk to the
  same PipeWire.


- **Activating an app on another workspace** (M1): *switch to that workspace.* The
  daemon runs `[con_id=N] focus` and lets Sway follow the window, rather than pulling
  the window to the current workspace. Each workspace keeps the layout you built, and
  it matches how ordinary taskbars behave.

- **What makes a chat line a command?** (M5): *every plain line is one.* Not a prefix
  and not a `/sh` client command. The world is single-player and empty, so there is
  nobody to chat with, and a prefix would cost two keystrokes on every command to
  protect a surface nobody uses. Slash commands are untouched, so `/gamerule` and
  `/worldborder` still work.

- **How does `sudo` get a password?** (M5): *an askpass helper, in a real window.*
  Not chat. Chat echoes what you type and the transcript keeps it, and the
  standing rail is that credentials never route through the game client. sudo's
  own answer to having no tty is `SUDO_ASKPASS`, which puts the prompt where the
  rail already wants it — on the compositor, beside swaylock and polkit. The
  prompter is chosen at runtime by `daemon/tools/mcshell-askpass`; changing it is
  an edit to that file. NOPASSWD sudoers was rejected: it would make a chat bar
  reachable over a unix socket into a passwordless root prompt.

- **Does output stream, or arrive once at the end?** (M5): *it streams.* A build should
  scroll rather than hang. That is what forced `cmd` numbering onto `output`: the mod
  cannot apply the five-line rule to lines it cannot group, so the run is bracketed by
  `command_start` and `command_end`. The threshold itself stays in the mod.

- **Should `E` open the full 27-slot inventory as an extended app drawer?** (M4): *no.*
  `E` opens the real survival inventory. The catalog is the app drawer; a 27-slot
  middle tier would be a second home for apps with nothing to choose between
  them. Assignable slots stay at 9. *(M8: those 27 slots hold real items now —
  the point stands, they are storage, not a second hotbar.)*

- **Can the hotbar be real Minecraft items?** (M8): *yes, and it is.* Long held
  to be impossible because a baked model's quads carry UVs into a texture atlas
  and a `.desktop` icon found at runtime can never be stitched into one. True,
  and not the whole picture: `ItemRenderer.renderItem` tests `isBuiltin()` first,
  and a model that says yes is handed to `BuiltinModelItemRenderer` with a live
  `VertexConsumerProvider` — arbitrary geometry against an arbitrary texture,
  which is how vanilla draws chests and shields. `ItemRenderer.getModel` is the
  single choke point for the GUI, the hand and a dropped stack, so one injection
  covers them all. No atlas, no generated resource pack, no resource reload.

  Registering the item from the client entrypoint looks too late and is not:
  fabric-api's `BootstrapMixin` redirects `Registries.bootstrap()` to
  `Registries.init()`, dropping the freeze from that path.

  Rejected on the way: an item per application (registries freeze, the catalog is
  runtime), and tagging a vanilla item instead of registering one (a paper-based
  application could go in a crafting grid).
