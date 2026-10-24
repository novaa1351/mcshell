# Milestones M0–M8

What each finished milestone was, as CLAUDE.md recorded it. Strikethrough became *(done)*: ONLYOFFICE drops struck text.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

- **M0** *(done)* — Daemon: socket server + `mcsh` harness + i3ipc window list. No Minecraft.
- **M1** *(done)* — Daemon: catalog, icon resolution, slot state, launch/focus/close via `mcsh`.
- **M2** *(done)* — Mod: socket transport + hotbar overlay reflecting `taskbar` messages.
- **M3** *(done)* — Mod: overview `Screen`, slot activation round-trip. *(Vertical slice done:
  Super → MC raises → right-click slot → app appears over MC.)*
- **M4** *(done)* — Catalog browser UI, drag-to-assign. *(`E` → survival inventory → chest
  button → catalog; click an app, click a slot.)*
- **M5** *(done)* — Command bar + hybrid output. *(Chat is the bar; five lines is where
  chat stops and the overview panel starts. `sudo` asks in a real window.)*
- **M6** *(done)* — Settings bridge (schema-driven, so new settings are a daemon
  change only). Three pages, beside the vanilla screens rather than replacing
  them, reached by a bottom-left button that switches lanes both ways.
  - Sound *(done)* — devices, volume, mute, card profiles, per-application streams.
  - Video *(done)* — brightness, and the output's resolution, refresh rate and scale.
  - Controls *(done)* — rebind existing Sway binds, and *(M8)* make binds of your
    own out of a shell command and a key. Applied at runtime *and* written to
    a generated `~/.config/sway/config.d/mcshell-binds.conf`, so a change works
    at once and survives a reload. See the section on it below.
  - General *(done)* *(added in M8)* — the shell's own settings, in the
    Accessibility lane: the HUD clock, the battery gauge's colours, the
    notification switches and sound, and screen-time tracking. The one page
    whose rows are about MCShell rather than about a subsystem. See the
    section above.
  - Network *(done)* *(added in M8)* — Wi-Fi, the ethernet port and Bluetooth, in
    three groups on one page. It is what the pause menu's **Open to LAN**
    button opens; that button keeps its vanilla wording, because it is close
    enough to the subject that nobody hunts for it and a renamed one is a
    tell. This is the one page with no lane back: a shell that can publish
    itself to the local network from a settings menu is a surprise, not a
    feature. Nothing
    on it that needs typing exists — no static IP, no hidden SSID — because
    the field people would want most is barred from the game client anyway:
    a password is asked for by the askpass helper, in a real window. (There
    *is* a `text` row type now — Controls grew one in M8 — so this is a
    choice about passwords rather than a missing widget.)
- **M7** *(done)* — The real session. Three parts, in this order,
  because only the last one can break logging in.
  - Layout *(done)* — Fork A for real: everything floats, Minecraft is the backdrop
    the rest stack above, Super raises it back. `session/layout.conf`, shared
    by the dev and real configs. Applications open filling the screen — the
    daemon sizes each one as it appears, sparing dialogs — and `$mod`+drag
    moves and resizes them afterwards.
  - Prism instance *(done)* — 1.21.1 + Fabric + the mod jar, the performance mods
    pinned by sha512, 1G of heap on JDK 21, and the world built to the spec
    below. `session/prism/setup.sh` settles all of it and is idempotent;
    `install-mod.sh` is the build-and-install step that stops the real session
    quietly testing a stale jar. The instance and the world are made by hand,
    once — Prism has no command line for creating an instance, and a world is
    easier to make in the game than to synthesise. Recipe in `docs/testing/m0-m7.md`.
  - Session plumbing *(done)* — **GDM**, systemd user units, escape hatches. MCShell
    is added as a *second* session entry; Hyprland stays selectable, so a broken
    config costs a session pick rather than a login. `install-session.sh`
    installs it; `docs/testing/m0-m7.md` walks the first login, and
    `session/diagnose.sh` answers what the shell can actually see when it comes
    up wrong.

- **M8** *(done)* — **Polish. Closed 2026-10-14**, when Nick called the functionality
  complete. The prototype works; this
  is the pass that makes it fit to put in front of someone who is not Nick.
  Two halves, and they share a session:
  - **Visual finish.** How the shell looks and reads. It stays inside the rule
    the hotbar was built on — *use vanilla Minecraft rendering, do not invent
    UI*. That constraint is easiest to lose in exactly this milestone, because
    "make it look better" and "make it look like something else" are one small
    step apart. A shell that reads as a resource pack is finished. One that
    reads as a web app embedded in a game is a different project.
  - **Debugging.** Whatever misbehaves in daily use.
  - **The backlog is Nick's, and this milestone does not presume one.** He
    brings what he hits while using it. The standing known gaps below are
    written down, not queued: do not start on one because it is listed. Ask.
  - **Not M8, however tempting:** deployment, portability, another machine,
    first-run and onboarding, a README, screenshots. Those are a later session
    that is explicitly about them. A polish session that starts writing install
    docs has stopped polishing.
  - **Done so far, across three sessions.** Each has a spec section above and a
    walkthrough in `docs/testing/m8.md`. Read the section before touching the
    thing; the reasons are the point, not the code.

    | | |
    |---|---|
    | The hotbar is real `ItemStack`s | the catalog, the inventory, the click rules |
    | The XP bar is the battery | Statistics is the machine; Advancements is the filesystem |
    | *Save and Quit* is the power menu | the lock screen, drawn out of the client jar |
    | Notifications are advancement toasts | the layer-shell overlay |
    | The Accessibility page is the shell's own settings | the HUD clock |
    | F2 is the desktop's screenshot key | the Controls page makes bindings |
    | The volume popup is a boss bar | the boot screen is the world-gen screen |
    | The GPU nag is not the desktop's | the Sound page can actually set things |
    | *Give Feedback* is the world picker | the world saves before power off |
    | A login with no network goes offline | a new app appears without a restart |

  - **Where it is going next: the boot phase, and the parts that are not the
    mod.** Session plumbing, the units, the scripts, the overlay, the daemon —
    everything in `session/` and `daemon/`. Read *From login to desktop* below
    first; it is the measured sequence and it is the thing a cold session
    otherwise has to reconstruct. The one thing raised and not settled is what
    the screen shows during those seconds, which is in Open questions.
