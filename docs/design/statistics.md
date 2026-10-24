# The Statistics screen is the machine's

Machine, Processes and Storage, and the rules for the kill button.

Moved out of CLAUDE.md word for word on 2026-10-16, so that file stays
short enough to read in full every session. The reasons below are the
point: read them before changing the thing they describe.

## The Statistics screen is the machine's
Three tabs, standing where Minecraft's three stood. Vanilla's screen is
**buried**, not moved aside — blocks mined and mobs killed in a superflat
void with spawning off are three screens of zeroes. The pause-menu button
keeps saying *Statistics*, which needs no argument.

- **Machine** — what this computer is: OS, kernel, host, packages, CPU, GPU,
  memory, display, battery, and screen time. Static; read when the tab opens.
- **Processes** — a task manager. The one place function is allowed to beat
  the look: right-aligned numeric columns, because that is what makes numbers
  comparable and Minecraft has no vocabulary for it. Sortable by clicking a
  column. **Live only while it is on screen** — a sample costs the daemon
  ~23ms, so nothing is sampled until asked and the stream stops when the
  screen closes or the client disconnects.
- **Storage** — mounted filesystems with usage bars, and the physical drives.

**Sorting and cutting are the daemon's**, not the mod's: hundreds of
processes, room for tens, so the mod asks for an order and gets that many
rows. Process CPU is a share of the *whole machine*, so the column sums to
the gauge above it.

**The kill button sends SIGTERM and nothing else** — a request, like
`slot_close`. It refuses the processes the shell stands on: init, sway, the
daemon, and the game. The game is found through `SO_PEERCRED` on its own
socket, never by matching a Java command line, which would have protected
every other Java program on the machine too.

**Screen time is time in MCShell**, not time powered on — the daemon's
lifetime is the session. Banked into per-day buckets every minute, so a
crash costs a minute and a restart cannot double-count.
