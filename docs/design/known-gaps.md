# Known gaps

What is known to be wrong or missing, and deliberately left. The three that were struck through as gone (the HUD window count, the flat-colour login, sway's GPU nag) were dropped in the move; their fixes are in hotbar.md and boot.md.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## Known gaps, deliberately left

Not forgotten, not blocking, **and not a to-do list**. Each is written up in
`docs/testing/m0-m7.md`. They are here so that meeting one is recognised rather than
rediscovered; picking one up is Nick's call, not an opening move.

- **A window Sway focuses by itself can strand the pointer grab** (M7). The
  daemon takes the mouse back off the game before it moves focus, because X
  only lets go while the game is still focused. A window Sway focuses on its
  own — `$mod+Shift+Return`'s terminal, spawned straight from the game — beats
  the daemon to it, and the grab is left held: the camera stops, but an
  XWayland application opened afterwards gets no clicks. Native Wayland
  applications are unaffected. It heals itself the next time you return to
  Minecraft and leave through the shell. Fixable by having those bindings ask
  the daemon first (`mcsh` then the exec, so a dead daemon still spawns the
  terminal); not done, because the bindings are safety rails and each one that
  learns about the daemon is one less thing that works when it is dead.
- **Eight apps have no icon at all** and draw as the placeholder tile
  (`assets/mcshell/textures/item/app.png`); their `.desktop` files name an icon
  that is not installed. A letter tile would read better.
- **The media keys cannot be tested from a *nested dev* session.** Hyprland binds
  volume itself and `swayosd-libinput-backend` is running, so the host acts on the
  press and the nested Sway never sees it. The bindings in `sway.dev.conf` are
  right and will work in the real session; dev uses `$hatch`-prefixed stand-ins,
  the way Super does. Same shape as the next one.

- **`session.log` is not only sway's.** sway's children inherit its stderr, so
  the log that exists to explain a failed login also collects the noise of
  every application started from the shell — Electron deprecation warnings,
  `vaInitialize failed`, whatever a browser feels like saying. Measured: 359
  lines after one ordinary session, most of them nothing to do with the
  session. The fix is redirecting the applications rather than the log, which
  means `exec` in `layout.conf` and the daemon's own launch path, so it is not
  a one-liner.
- **In a VMware VM, everything is drawn on the CPU** (M9). sway cannot take GPU
  buffers from clients on vmwgfx, so `start-session.sh` switches it to the
  pixman renderer there, and the game runs on llvmpipe. The real fix is in
  wlroots or the vmwgfx kernel driver, not here; why, and what was measured,
  is in `docs/design/boot.md`. VirtualBox and QEMU/virtio-gpu are untested.
- **Single-instance apps launched from a *nested dev* session appear on the host.**
  Brave, Claude Desktop and other Electron apps hand the request to an instance
  already running under the host compositor, which opens the window there. Not a
  daemon bug and it cannot arise in the real session, where there is no host.
  **Prism Launcher is one of these**, which makes it the one that bites: with the
  Prism GUI open on the host, the real client launches onto the host desktop and
  the nested session stays empty. Quit it there first.
