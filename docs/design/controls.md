# The Controls screen makes bindings

Rebinding sway's own keys, and binds of the shell's own.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## The Controls screen makes bindings, not just moves them

Two halves, and they are different things on purpose. **Sway's own binds can
only be rebound** — nothing is added to them and nothing is deleted, which is
exactly what Minecraft's Controls screen does, and it is the screen this one
stands beside. **Bindings of your own are the daemon's**, made at the top of
the page out of a command and a key, and those can be removed.

- **Only ours can be deleted, and that is the whole reason they are kept
  apart.** A bind read out of the config is somebody's config, and the only
  safe thing to do to a line you did not write is move it. A bind made here
  belongs to the shell. Offering *Remove* on both would mean offering to
  delete lines out of a file the shell does not own.
- **They cannot collide, and that is measured.** Sway's `get_config` returns
  **only the top-level file**, not the `include` chain — checked against a live
  session, where `for_window` lines from `layout.conf` are absent from the
  reply. So the `config.d` snippet the daemon generates is never read back in
  as though a person had written it, and a bind of ours can never appear twice.
- **The key comes from the same capture the rebinds use**, and the command is
  typed into a real `TextFieldWidget` — vanilla's own, the one `AddServerScreen`
  uses. That is a new row type (`text`) and it is the first typing this shell
  has asked for inside the game. It is allowed here and still barred for
  passwords: the rail was always about credentials, not about keyboards.
- **The command is `sh`'s, because Sway's `exec` is.** It goes into the bind as
  `exec <command>` and Sway hands that to `sh -c`, so pipes and `&&` work and
  none of it is the daemon's to parse. The only refusals are the ones that
  would break the config line — a newline, or 256 characters.
- **"flameshot is not on PATH" is a note, never a refusal.** A binding may
  reasonably name something not installed yet, a shell builtin, or a program
  reached through a variable. So the check is only made on a bare first word,
  and its answer goes in the row's second line where it cannot stop anything.
- **Remove takes the column Reset uses.** It is free there: Reset means *back
  to what the config says*, and a binding that was never in the config has
  nothing to go back to. The mod is told a label and a key to set, and learns
  nothing about what pressing it does.
- **The keys are `controls.…`, and that is load-bearing.** A `setting_set` is
  routed by the key's first segment and a provider is registered under its page
  name, so the `binds.…` keys this page used to send reached nobody: every
  rebind since M6 was refused with *no page owns*, in a log nobody had open.
  Found by measuring the page rather than by reading it.
