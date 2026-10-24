# The command bar

Chat as a command line.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## Command bar (Minecraft chat)
- Chat input is a launcher/REPL for things without a `.desktop` file.
- **Every plain chat line is a command.** The mod cancels the outgoing message and
  sends `command_submit`. Minecraft's own slash commands go down a different path and
  are untouched, so `/gamerule` still works.
- **Hybrid output**: ≤5 lines go to chat; longer output opens a scrolling panel in the
  overview Screen. The daemon always emits the same `output` message; the mod decides
  where to draw it.
- **Output streams**, so `output` is bracketed by `command_start` and `command_end`
  and carries a `cmd` number. The mod holds a run's lines until the end to apply the
  five-line rule; a run that crosses five while still running opens the panel and
  fills it live.
- **Trailing `&` detaches**: handed to Sway's `exec`, nothing captured. This is how a
  GUI program with no `.desktop` file gets launched.
- **`cd` is a daemon builtin** over one persistent working directory, because a `cd`
  inside `bash -lc` would change a directory that stops existing a moment later.
- **`clear` is a builtin too**, and empties the chat the way F3+D does —
  `ChatHud.clear(false)`, read out of `Keyboard`, which keeps the up-arrow
  history. Handed to bash it exited non-zero with no terminal to clear and left
  the chat alone. Only the bare word; `clear; ls` is still bash's. The daemon
  sends `chat_clear` inside the run, on the same queue as its echo, so `$ clear`
  goes with the rest. The overview's transcript is kept: that is the panel, not
  chat.
- One command at a time; a submission while one is running is refused. 60s timeout,
  killing the process group. Output capped at 2000 lines and 512 characters a line.
- **`sudo` authenticates through an askpass helper.** There is no tty to prompt
  on, so the daemon sets `SUDO_ASKPASS` and adds `-A`; the password is asked for
  in a compositor window. It answers for the password only — a program's own
  prompts still hit `/dev/null`, so `pacman` wants `--noconfirm` or a terminal.
- This is NOT a terminal emulator. No PTY, no ANSI, no TUI apps. `vim`/`htop` are
  expected to be run as real windows — that is what `&` is for.
