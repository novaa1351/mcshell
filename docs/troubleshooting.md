# Troubleshooting

Start with `mcshell check`. It lists anything missing and says how to fix it.
Inside a running MCShell session it also runs `mcshell diagnose`.

## The login

MCShell is a second entry on the login screen. Your other desktops are not
changed, and a failed MCShell login cannot lock you out of them.

**What a good login looks like:** Minecraft's world-loading screen with a
percentage, then Tutorial World (or the world you picked) with the hotbar.

**If you land back at the login screen,** sway or the session script failed.
Log into your normal desktop and read:

```bash
cat ~/.local/state/mcshell/session.log
```

It only holds the last MCShell login. In a VM, the usual cause is 3D
acceleration being off.

**If it hangs,** Ctrl+Alt+F3 gives you a text console, which involves none of
MCShell.

**If the loading screen never goes away,** the game did not start. It gives up
after 90 seconds. Press Super+Shift+J for the logs, or from another desktop:

```bash
journalctl --user -u mcshelld -u mcshell-client -b
```

## Keys that work even when everything else is broken

These are sway bindings. They do not need the game or the daemon.

| Key | Does |
|---|---|
| Super+Shift+Return | Terminal |
| Super+Shift+D | Restart the daemon |
| Super+Shift+M | Restart the game (also the way back if you quit it from its menu) |
| Super+Shift+J | Follow the daemon's and the game's logs |
| Super+Shift+C | Reload sway's config |
| Super+Shift+L | Lock |
| Super+Shift+E | Log out |
| Alt+F4 | Close the focused window (does nothing on the game, on purpose) |

## What `mcshell diagnose` tells you

Run it from a terminal inside the session. The line to read first is
Minecraft's window identity. It must be `class='Minecraft* 1.21.1'` with
`shell=xwayland`. If Minecraft has no identity, it started without `DISPLAY`,
fell back to native Wayland, and the shell can't find its own backdrop: the
game sits small in the middle of the screen. `sway.conf` imports `DISPLAY` for
the units; check that line.

## Logging out

Logging out stops the daemon and the game:

```bash
systemctl --user is-active mcshelld mcshell-client   # both: inactive
```

If a game survives a logout, the next login fails with an error about the
world's lock. Stop it and log in again:

```bash
systemctl --user stop mcshell-session.target
```

## Symptoms

| Symptom | Cause | Fix |
|---|---|---|
| MCShell is not on the login screen | The session entry is not installed | `session/install-session.sh` |
| Back at the login screen after logging in | sway or the session script failed | `~/.local/state/mcshell/session.log` |
| Next login fails with a lock error | A game outlived the last logout | `systemctl --user stop mcshell-session.target` |
| Minecraft small and centred | It started without `DISPLAY` | `mcshell diagnose`, see above |
| An app takes the keyboard but not clicks, and the camera is frozen | The game kept the pointer when sway focused a window by itself (a known gap) | Super to go back to the game, then open the app from the hotbar |
| Clicks go missing and you can't tell where | Unknown: measure it | `session/probes/clickprobe.py x11` and `wayland`, then `session/probes/pointer-grab.sh` |
| Right-click on a touchpad does nothing | Touchpads click left with one finger | Two-finger click |
| An app from a terminal shows as not running | Its terminal can't be given an app id | Only foot, footclient, kitty, alacritty and ghostty are supported; others go in `TERMINAL_APP_ID_FLAG` in `daemon/mcshelld/catalog.py` |
| `sudo` in chat says a terminal is required | `daemon/tools/mcshell-askpass` is missing or not executable | `chmod +x daemon/tools/mcshell-askpass` |
| `sudo` in chat says no password prompter is installed | None of the prompters it knows is installed | `pacman -S zenity` |
| The Sound page is empty | The daemon can't reach PipeWire | `daemon/tools/mcsh audio`; if that is empty too, the problem is below MCShell |
| A change to the mod doesn't show up | The instance has the old jar | `session/prism/install-mod.sh` |
| Fabric refuses to start: duplicate mod id | Two copies of a mod in the instance | `mcshell setup` |
| `mcsh` says connection refused | No daemon | Super+Shift+D |

## In a nested session (development)

| Symptom | Cause | Fix |
|---|---|---|
| The nested session is empty, but Minecraft is running somewhere | Prism was already open on your desktop and took the launch | Quit Prism there, then Ctrl+Alt+M |
| An Electron app opens on your desktop, not the nested one | Single-instance apps hand off to their running copy | Quit it on your desktop first |
| Media keys do nothing | Your desktop takes them before the nested sway sees them | Test them in the real session |
