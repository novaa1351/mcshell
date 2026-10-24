"""The Statistics screen: what this machine is, what it is doing, and what it holds.

Three tabs, standing where Minecraft's own three stood. The vanilla screen is
buried rather than moved aside — the shell's statistics are the machine's, and
how many zombies you have killed in a void world with mob spawning off is not
a number anyone came to read.

    General    what the machine is. Static: read when the tab opens.
    Processes  what it is doing. Live, and only while someone is looking.
    Disks      what it holds. Static, same as General.

Everything is read from `/proc`, `/sys` and `/etc`, with no `psutil`, no D-Bus
and — apart from naming the GPU — no subprocesses. That is not frugality for
its own sake: a full scan of every process on this machine measured 5.8ms in
Python, which is cheap enough to do once a second forever, and a dependency
that has to be installed is a dependency that will one day not be.

Screen time is banked here too, because nothing else was tracking it. It counts
time this daemon was running, which is time spent in the shell — not time the
machine was powered on. Per-day buckets on disk, written every minute, so a
crash costs a minute rather than a session and a restart cannot double-count.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import pwd
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

from xdg import BaseDirectory

from . import protocol as p

log = logging.getLogger(__name__)

PROC = Path("/proc")
SYS = Path("/sys")
DMI = SYS / "devices/virtual/dmi/id"
PACMAN_DB = Path("/var/lib/pacman/local")

#: uid -> name. A passwd lookup can hit NSS and a network, and the answer for
#: a given uid does not change while the shell is running.
_USERS: dict[int, str] = {}

CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")

# How often the live tab is resampled. A task manager that updates slower than
# this feels broken; faster than this is a stopwatch nobody asked for.
SAMPLE = 1.0

# How often screen time is written down. A minute is the most a crash can lose.
BANK = 60.0

# Never killable, whatever a client asks. Everything the shell is standing on:
# the compositor, this daemon, the game, and init. See `_protected`.
PROTECTED_NAMES = frozenset({"systemd", "sway", "swaybg", "mcshelld"})


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _bytes(count: float) -> str:
    """A size, in the unit a person would say it in."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(count) < 1024 or unit == "TB":
            return f"{count:.0f} {unit}" if unit in ("B", "KB") else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} TB"


def _duration(seconds: float) -> str:
    """A span, in the two largest units that say anything."""
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


class ScreenTime:
    """Per-day totals of time the shell was running.

    Banked in increments rather than measured start-to-finish, because the
    daemon is restarted constantly during development and a session that ends
    in a crash still happened. Each bank adds the time since the last one, so
    the worst a hard kill can cost is whatever has not been written yet.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or Path(BaseDirectory.save_config_path("mcshell")) / "screentime.json"
        #: Off stops counting; it does not forget. What is already banked is
        #: what the machine actually did, and a switch that quietly deleted
        #: history would be a different, much ruder feature.
        self.tracking = True
        self._days: dict[str, float] = {}
        self._mark = time.monotonic()
        self._task: asyncio.Task | None = None
        self._session = 0.0
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if "tracking" in data:
            self.tracking = bool(data["tracking"])
        days = data.get("days")
        if isinstance(days, dict):
            self._days = {k: float(v) for k, v in days.items()
                          if isinstance(v, (int, float)) and v >= 0}

    def save(self) -> None:
        payload = json.dumps(
            {"version": 1, "tracking": self.tracking, "days": self._days}, indent=1)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Written through a temporary file: a half-written total is worse
            # than a stale one, and this is rewritten every minute.
            with tempfile.NamedTemporaryFile(
                    "w", dir=self.path.parent, delete=False, encoding="utf-8") as fh:
                fh.write(payload)
                temp = Path(fh.name)
            temp.replace(self.path)
        except OSError:
            log.exception("screentime: could not be written to %s", self.path)

    def bank(self) -> None:
        """Add the time since the last bank to today's total.

        The mark moves whether or not tracking is on, so switching it back on
        does not bank the hour it was off for.
        """
        now = time.monotonic()
        elapsed = max(0.0, now - self._mark)
        self._mark = now
        if not self.tracking:
            return
        self._session += elapsed
        today = date.today().isoformat()
        self._days[today] = self._days.get(today, 0.0) + elapsed

    def set_tracking(self, on: bool) -> None:
        """Start or stop counting, keeping the time up to this moment."""
        self.bank()
        self.tracking = bool(on)
        self.save()

    async def start(self) -> None:
        self._mark = time.monotonic()
        self._task = asyncio.create_task(self._run(), name="screentime")

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(BANK)
            self.bank()
            self.save()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self.bank()
        self.save()

    def totals(self) -> tuple[float, float, int, float, float]:
        """(total, today, days recorded, average a day, this session)."""
        # Counted without banking first, then topped up with the unbanked
        # remainder, so the numbers on screen are live rather than a minute old.
        pending = max(0.0, time.monotonic() - self._mark) if self.tracking else 0.0
        days = dict(self._days)
        today = date.today().isoformat()
        days[today] = days.get(today, 0.0) + pending
        total = sum(days.values())
        recorded = len(days)
        average = total / recorded if recorded else 0.0
        return total, days[today], recorded, average, self._session + pending


class Stats:
    """The three tabs, and the sampler behind the live one."""

    def __init__(self, compositor=None, battery=None, screentime: ScreenTime | None = None):
        self._compositor = compositor
        self._battery = battery
        self.screentime = screentime or ScreenTime()
        # Last CPU sample, for the deltas a percentage is made of. There is no
        # such thing as instantaneous CPU use — only work done between two
        # looks — so the first sample after opening the tab reads zero.
        self._last_total: int = 0
        self._last_cores: list[int] = []
        self._last_procs: dict[int, int] = {}
        self._gpu: str | None = None
        #: Pids the shell is standing on, refreshed each sample.
        self._client_pids: set[int] = set()

    # -- the General tab ---------------------------------------------------

    async def general(self) -> list[p.StatsRow]:
        rows: list[p.StatsRow] = []
        os_release = self._os_release()
        meminfo = self._meminfo()

        rows.append(p.StatsRow(group="System", label="OS",
                               value=f"{os_release.get('PRETTY_NAME', 'Linux')} {os.uname().machine}"))
        rows.append(p.StatsRow(group="System", label="Kernel", value=os.uname().release))
        rows.append(p.StatsRow(group="System", label="Host", value=self._host()))
        rows.append(p.StatsRow(group="System", label="Uptime",
                               value=_duration(self._uptime())))
        packages = self._packages()
        rows.append(p.StatsRow(group="System", label="Packages",
                               value=str(packages) if packages else "unknown",
                               detail="pacman" if packages else ""))
        rows.append(p.StatsRow(group="System", label="Shell",
                               value=Path(os.environ.get("SHELL", "")).name or "unknown"))
        rows.append(p.StatsRow(group="System", label="Compositor", value=self._sway_version()))
        rows.append(p.StatsRow(group="System", label="Locale",
                               value=os.environ.get("LANG", "unset")))

        rows.append(p.StatsRow(group="Hardware", label="CPU", value=self._cpu_model(),
                               detail=self._cpu_topology()))
        rows.append(p.StatsRow(group="Hardware", label="GPU", value=self._gpu_model()))
        total = meminfo.get("MemTotal", 0)
        available = meminfo.get("MemAvailable", 0)
        if total:
            rows.append(p.StatsRow(
                group="Hardware", label="Memory",
                value=f"{_bytes(total - available)} / {_bytes(total)}",
                fraction=(total - available) / total))
        swap = meminfo.get("SwapTotal", 0)
        if swap:
            free = meminfo.get("SwapFree", 0)
            rows.append(p.StatsRow(group="Hardware", label="Swap",
                                   value=f"{_bytes(swap - free)} / {_bytes(swap)}",
                                   fraction=(swap - free) / swap))
        for row in await self._display_rows():
            rows.append(row)
        if self._battery is not None:
            state = self._battery.state()
            if state.present:
                where = "charging" if state.charging else ("on mains" if state.mains else "on battery")
                rows.append(p.StatsRow(group="Hardware", label="Battery",
                                       value=f"{state.percent}%", detail=where,
                                       fraction=state.percent / 100))

        total_time, today, days, average, session = self.screentime.totals()
        rows.append(p.StatsRow(group="Screen time", label="Total",
                               value=_duration(total_time),
                               detail=f"over {days} day{'s' if days != 1 else ''}"))
        rows.append(p.StatsRow(group="Screen time", label="Average a day",
                               value=_duration(average)))
        rows.append(p.StatsRow(group="Screen time", label="Today", value=_duration(today)))
        rows.append(p.StatsRow(group="Screen time", label="This session",
                               value=_duration(session)))
        if not self.screentime.tracking:
            # Frozen numbers with nothing saying why would read as a broken
            # clock rather than as a switch somebody turned off.
            rows.append(p.StatsRow(group="Screen time", label="Tracking",
                                   value="Off"))
        return rows

    def _os_release(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for line in _read(Path("/etc/os-release")).splitlines():
            key, _, value = line.partition("=")
            if key:
                found[key] = value.strip().strip('"')
        return found

    def _host(self) -> str:
        vendor = _read(DMI / "sys_vendor")
        product = _read(DMI / "product_name")
        name = " ".join(part for part in (vendor, product) if part)
        return name or "unknown"

    def _uptime(self) -> float:
        try:
            return float(_read(PROC / "uptime").split()[0])
        except (ValueError, IndexError):
            return 0.0

    def _packages(self) -> int:
        """Installed packages, by counting pacman's database directories.

        Not `pacman -Q`: this is one readdir against a directory that is one
        entry per package, and it does not care whether pacman is on PATH.
        The database's own version file is the one non-package entry.
        """
        try:
            return sum(1 for entry in PACMAN_DB.iterdir() if entry.is_dir())
        except OSError:
            return 0

    def _cpu_model(self) -> str:
        for line in _read(PROC / "cpuinfo").splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "model name":
                return value.strip()
        return "unknown"

    def _cpu_topology(self) -> str:
        threads = os.cpu_count() or 0
        cores = 0
        seen: set[tuple[str, str]] = set()
        physical = package = ""
        for line in _read(PROC / "cpuinfo").splitlines():
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if key == "physical id":
                package = value
            elif key == "core id":
                physical = value
                seen.add((package, physical))
        cores = len(seen)
        if cores and threads:
            return f"{cores} cores, {threads} threads"
        return f"{threads} threads" if threads else ""

    def _gpu_model(self) -> str:
        """The graphics card's name, if anything on the machine can name it.

        PCI ids live in a database `lspci` owns, so this is the one place a
        subprocess earns its keep — and it is cached, because a graphics card
        does not change while the shell is running. Without lspci the kernel
        driver is the honest answer: "amdgpu" says more than a raw PCI id.
        """
        if self._gpu is not None:
            return self._gpu
        self._gpu = self._read_gpu()
        return self._gpu

    def _read_gpu(self) -> str:
        if shutil.which("lspci"):
            try:
                out = subprocess.run(["lspci", "-mm"], capture_output=True, text=True,
                                     timeout=3.0).stdout
            except (OSError, subprocess.SubprocessError):
                out = ""
            names = []
            for line in out.splitlines():
                # -mm quotes each field and a device name contains brackets and
                # spaces, so this is shlex's job rather than split's. Fields
                # are: slot, class, vendor, device, then revision and subsystem.
                try:
                    fields = shlex.split(line)
                except ValueError:
                    continue
                if len(fields) > 3 and fields[1] in ("VGA compatible controller",
                                                     "3D controller", "Display controller"):
                    # "NVIDIA Corporation" and "Intel Corporation" say nothing
                    # the first word does not.
                    vendor = fields[2].split()[0] if fields[2] else ""
                    names.append(f"{vendor} {fields[3]}".strip())
            if names:
                return " · ".join(names)

        drivers = []
        for card in sorted(SYS.glob("class/drm/card[0-9]")):
            driver = (card / "device/driver").resolve().name if (card / "device/driver").exists() else ""
            if driver and driver not in drivers:
                drivers.append(driver)
        return " · ".join(drivers) if drivers else "unknown"

    async def _display_rows(self) -> list[p.StatsRow]:
        if self._compositor is None:
            return []
        try:
            outputs = [o for o in await self._compositor.outputs() if o.active]
        except Exception:
            log.exception("stats: could not read the outputs")
            return []
        rows = []
        for output in outputs:
            mode = output.current
            value = (f"{mode.width} × {mode.height} @ {mode.refresh / 1000:g} Hz"
                     if mode else "on")
            rows.append(p.StatsRow(group="Hardware", label="Display", value=value,
                                   detail=f"{output.name} · scale {output.scale:g}"))
        return rows

    def _meminfo(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for line in _read(PROC / "meminfo").splitlines():
            key, _, value = line.partition(":")
            parts = value.split()
            if parts:
                try:
                    # meminfo is in kB, universally, whatever the unit says.
                    found[key.strip()] = int(parts[0]) * 1024
                except ValueError:
                    continue
        return found

    def _sway_version(self) -> str:
        version = os.environ.get("SWAY_VERSION", "")
        return f"Sway {version}" if version else "Sway"

    # -- the Disks tab -----------------------------------------------------

    async def disks(self) -> list[p.StatsRow]:
        """Every real filesystem that is mounted, with what is left on it.

        Filtered to those backed by a block device: a shell's disk page should
        not be forty lines of tmpfs, cgroup and efivarfs. Bind mounts of one
        device show once, at the shortest path, because they are one disk.
        """
        rows: list[p.StatsRow] = []
        seen: dict[str, str] = {}
        for line in _read(PROC / "self/mounts").splitlines():
            fields = line.split()
            if len(fields) < 3 or not fields[0].startswith("/dev/"):
                continue
            device, point, kind = fields[0], fields[1].replace("\\040", " "), fields[2]
            if device in seen and len(seen[device]) <= len(point):
                continue
            seen[device] = point
            try:
                stat = os.statvfs(point)
            except OSError:
                continue
            size = stat.f_blocks * stat.f_frsize
            if size == 0:
                continue
            free = stat.f_bavail * stat.f_frsize
            used = size - stat.f_bfree * stat.f_frsize
            rows.append(p.StatsRow(
                group="Filesystems", label=point,
                value=f"{_bytes(used)} of {_bytes(size)} · {_bytes(free)} free",
                detail=f"{device} · {kind}",
                fraction=used / size if size else 0.0,
            ))
        rows.sort(key=lambda r: r.label)

        for row in self._block_rows():
            rows.append(row)
        if not rows:
            rows.append(p.StatsRow(group="Filesystems", label="No mounted filesystems"))
        return rows

    def _block_rows(self) -> list[p.StatsRow]:
        """The physical drives themselves, whether or not anything is mounted."""
        rows = []
        for block in sorted(SYS.glob("block/*")):
            name = block.name
            if name.startswith(("loop", "ram", "zram", "dm-")):
                continue
            size = _read(block / "size")
            try:
                total = int(size) * 512
            except ValueError:
                continue
            if total == 0:
                continue
            model = _read(block / "device/model") or _read(block / "device/name")
            rotational = _read(block / "queue/rotational") == "1"
            rows.append(p.StatsRow(
                group="Drives", label=f"/dev/{name}", value=_bytes(total),
                detail=" · ".join(part for part in
                                  (model, "spinning" if rotational else "solid state") if part),
            ))
        return rows

    # -- the Processes tab -------------------------------------------------

    def note_clients(self, pids: set[int]) -> None:
        """The pids on the other end of our own sockets — the game, and `mcsh`."""
        self._client_pids = pids

    def sample(self, sort: str = "cpu", desc: bool = True, limit: int = 64) -> p.Processes:
        """One look at every process, and at the machine as a whole."""
        total, cores = self._cpu_times()
        delta_total = max(1, total - self._last_total)
        core_deltas = [max(1, now - was) for now, was in zip(cores, self._last_cores)] \
            if len(cores) == len(self._last_cores) else []
        first = self._last_total == 0

        meminfo = self._meminfo()
        mem_total = meminfo.get("MemTotal", 0)
        mem_used = mem_total - meminfo.get("MemAvailable", 0)
        swap_total = meminfo.get("SwapTotal", 0)
        swap_used = swap_total - meminfo.get("SwapFree", 0)

        procs: list[p.ProcessRow] = []
        now_procs: dict[int, int] = {}
        # Plain strings and os.listdir rather than pathlib, in this loop only.
        # Measured on this machine at ~345 processes: 14ms with Path objects,
        # 8ms without. Everything else here runs when a tab opens; this runs
        # every second for as long as the tab is open.
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            row = self._process(name, delta_total, mem_total, first, now_procs)
            if row is not None:
                procs.append(row)
        self._last_procs = now_procs
        self._last_total = total
        self._last_cores = cores

        keys = {
            "cpu": lambda r: r.cpu,
            "mem": lambda r: r.mem,
            "pid": lambda r: r.pid,
            "name": lambda r: r.name.lower(),
        }
        key = keys.get(sort, keys["cpu"])
        # Name sorts the other way round by nature: A-Z is "ascending" and is
        # what anyone means by sorting a list of names.
        procs.sort(key=key, reverse=desc if sort != "name" else not desc)
        count = len(procs)
        procs = procs[:max(1, limit)]

        # The command line and the owner are two more syscalls each, and they
        # are only ever read — never sorted on — so they are fetched after the
        # list has been cut to what fits on a screen. Measured: it halves the
        # cost of a sample on a machine with three hundred processes.
        for row in procs:
            base = f"/proc/{row.pid}"
            row.cmd = self._cmdline(base) or row.name
            row.user = self._owner(base)

        used_cpu = 0.0
        if not first:
            idle_now, idle_was = self._idle
            used_cpu = max(0.0, min(100.0, 100.0 * (1 - (idle_now - idle_was) / delta_total)))

        return p.Processes(
            cpu=round(used_cpu, 1),
            cores=[round(c, 1) for c in self._core_usage(core_deltas)],
            mem_used=mem_used, mem_total=mem_total,
            swap_used=swap_used, swap_total=swap_total,
            load=list(os.getloadavg()),
            count=count,
            procs=procs,
        )

    def _cpu_times(self) -> tuple[int, list[int]]:
        """Total jiffies, and per-core totals. Idle is remembered on the side."""
        total = 0
        cores: list[int] = []
        idle_now = 0
        core_idles: list[int] = []
        for line in _read(PROC / "stat").splitlines():
            if not line.startswith("cpu"):
                break
            fields = line.split()
            try:
                numbers = [int(f) for f in fields[1:]]
            except ValueError:
                continue
            # user nice system idle iowait irq softirq steal ...
            summed = sum(numbers[:8])
            idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
            if fields[0] == "cpu":
                total, idle_now = summed, idle
            else:
                cores.append(summed)
                core_idles.append(idle)
        self._idle = (idle_now, getattr(self, "_last_idle", idle_now))
        self._last_idle = idle_now
        self._core_idles_now, self._core_idles_was = core_idles, getattr(
            self, "_last_core_idles", core_idles)
        self._last_core_idles = core_idles
        return total, cores

    def _core_usage(self, deltas: list[int]) -> list[float]:
        if not deltas or len(deltas) != len(self._core_idles_now):
            return []
        out = []
        for delta, now, was in zip(deltas, self._core_idles_now, self._core_idles_was):
            out.append(max(0.0, min(100.0, 100.0 * (1 - (now - was) / delta))))
        return out

    def _process(self, name: str, delta_total: int, mem_total: int,
                 first: bool, now_procs: dict[int, int]) -> p.ProcessRow | None:
        pid = int(name)
        base = f"/proc/{name}"
        try:
            with open(f"{base}/stat", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            # A process that exited between the readdir and the read. Normal,
            # and the reason none of this can be written as a straight loop.
            return None
        # The command sits in parentheses and may contain spaces and even a
        # closing bracket, so the fields after it are found from the right.
        head, _, tail = raw.rpartition(")")
        name = head.partition("(")[2]
        fields = tail.split()
        if len(fields) < 13:
            return None
        try:
            ticks = int(fields[11]) + int(fields[12])
        except ValueError:
            return None
        now_procs[pid] = ticks

        cpu = 0.0
        if not first:
            previous = self._last_procs.get(pid)
            if previous is not None:
                cpu = max(0.0, 100.0 * (ticks - previous) / delta_total)

        rss = 0
        try:
            with open(f"{base}/statm", encoding="utf-8") as fh:
                rss = int(fh.read().split()[1]) * PAGE_SIZE
        except (OSError, IndexError, ValueError):
            pass

        return p.ProcessRow(
            pid=pid, name=name,
            cpu=round(cpu, 1),
            mem=round(100.0 * rss / mem_total, 1) if mem_total else 0.0,
            rss=rss,
            protected=self._protected(pid, name),
        )

    @staticmethod
    def _cmdline(base: str) -> str:
        try:
            with open(f"{base}/cmdline", "rb") as fh:
                raw = fh.read()
        except OSError:
            return ""
        return " ".join(raw.decode("utf-8", "replace").split("\0")).strip()

    @staticmethod
    def _owner(base: str) -> str:
        try:
            uid = os.stat(base).st_uid
        except OSError:
            return ""
        try:
            return _USERS[uid]
        except KeyError:
            try:
                _USERS[uid] = pwd.getpwuid(uid).pw_name
            except KeyError:
                _USERS[uid] = str(uid)
            return _USERS[uid]

    def _protected(self, pid: int, name: str) -> bool:
        """Whether this is one of the things the shell is standing on.

        Four kinds: init, this daemon and everything in its process group, the
        clients on the other end of our own sockets — which is how the game
        itself is recognised without guessing at Java command lines — and the
        compositor by name. Killing any of them from inside Minecraft ends the
        session, and a task manager that can end the session by accident is
        worse than no task manager.
        """
        if pid <= 1 or pid == os.getpid():
            return True
        if pid in self._client_pids:
            return True
        try:
            if os.getpgid(pid) == os.getpgid(0):
                return True
        except (OSError, ProcessLookupError):
            pass
        return name in PROTECTED_NAMES

    def kill(self, pid: int) -> str | None:
        """SIGTERM one process. An error message, or None.

        A polite request, like `slot_close`: SIGTERM asks, and a program that
        wants to save something first is allowed to. Nothing here escalates to
        SIGKILL, because a task manager whose button cannot be argued with is
        one bad click from a lost document.
        """
        if not isinstance(pid, int) or pid <= 0:
            return f"not a pid: {pid!r}"
        try:
            name = _read(PROC / str(pid) / "comm")
        except OSError:
            name = ""
        if not name:
            return f"no process {pid}"
        if self._protected(pid, name):
            return f"{name} is part of the shell and cannot be killed here"
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return f"no process {pid}"
        except PermissionError:
            return f"{name} belongs to another user"
        except OSError as e:
            return f"{name}: {e}"
        log.info("stats: sent SIGTERM to %d (%s)", pid, name)
        return None
