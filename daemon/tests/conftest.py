"""Run the real daemon, and talk to it the way `mcsh` and the mod do.

Each test gets a daemon of its own, started as a process exactly as systemd
starts it, on a socket of its own, and drives it with newline-delimited JSON.
Nothing is imported from the daemon and nothing is mocked inside it; what is
tested is what goes over the socket.

**It must not touch the machine it runs on.** A daemon started on a
developer's desktop would otherwise take the notification name on the session
bus, take a logind inhibitor, follow PipeWire and NetworkManager, and could run
`systemctl poweroff`. So each one gets:

- its own HOME and XDG directories, including the runtime directory where
  PipeWire's and Wayland's sockets would be found;
- both D-Bus addresses pointed at a socket that does not exist;
- no WAYLAND_DISPLAY, DISPLAY or SWAYSOCK — sway is absent unless a test
  starts one (see `sway` below);
- a PATH holding only what is listed in `ALLOWED`. Every other program is
  missing rather than stubbed, which the daemon already treats as a note and
  never as a failure — the same path a user without the optional tools takes.

The command bar is the one exception, by design: it runs `bash -l`, whose
profile puts the system PATH back, so a test's command line runs real
programs. Tests only give it harmless ones.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

#: The daemon's whole PATH. bash for the command bar; the rest are what the
#: command bar's own tests run before the login profile is read.
ALLOWED = ("bash", "sh", "env", "echo", "cat", "ls", "pwd", "sleep", "true", "false")


class Client:
    """One connection, read a line at a time.

    The daemon pushes things nobody asked for (a taskbar on connect, a clock
    on the minute), and the order of two pushes is the daemon's business — a
    setting that moves the HUD sends `hud` before the page. So a message is
    found by its type, and whatever is passed over on the way stays in
    `pending` for the next wait, rather than being lost to it.
    """

    def __init__(self, path: Path) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(path))
        self.file = self.sock.makefile("rwb")
        self.pending: list[dict] = []
        self.seen: list[dict] = []

    def send(self, msg: dict | str) -> None:
        line = msg if isinstance(msg, str) else json.dumps(msg)
        self.file.write(line.encode() + b"\n")
        self.file.flush()

    def recv(self, timeout: float = 5.0) -> dict:
        """The next message off the wire, whatever it is."""
        self.sock.settimeout(timeout)
        try:
            line = self.file.readline()
        except TimeoutError:
            raise TimeoutError(f"nothing within {timeout:.1f}s; saw "
                               f"{[m.get('t') for m in self.seen]}") from None
        if not line:
            raise ConnectionError("daemon closed the connection")
        msg = json.loads(line)
        self.seen.append(msg)
        return msg

    def until(self, t: str, timeout: float = 5.0, where=lambda m: True) -> dict:
        """The first message of type `t` that satisfies `where`.

        An `error` while waiting for anything else fails at once, with the
        daemon's own words — a refusal is not a timeout.
        """
        for msg in self.pending:
            if msg.get("t") == t and where(msg):
                self.pending.remove(msg)
                return msg
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"no {t!r} within {timeout}s; saw "
                                   f"{[m.get('t') for m in self.seen]}")
            msg = self.recv(left)
            if msg.get("t") == t and where(msg):
                return msg
            if msg.get("t") == "error" and t != "error":
                raise AssertionError(f"daemon refused, waiting for {t!r}: "
                                     f"{msg.get('message')}")
            self.pending.append(msg)

    def ask(self, msg: dict, t: str, timeout: float = 5.0, **kw) -> dict:
        self.send(msg)
        return self.until(t, timeout, **kw)

    def close(self) -> None:
        self.file.close()
        self.sock.close()


class Daemon:
    """A running mcshelld, and the private world it runs in."""

    def __init__(self, root: Path, data_dirs: list[Path], extra_env: dict[str, str]):
        self.root = root
        self.home = root / "home"
        self.runtime = root / "run"
        self.socket = self.runtime / "mcshell.sock"
        self.bin = root / "bin"
        self.log = root / "daemon.log"
        for d in (self.home, self.runtime, self.bin):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ALLOWED:
            real = shutil.which(name)
            # Exists already when a test restarts a daemon in the same root.
            if real and not (self.bin / name).exists():
                (self.bin / name).symlink_to(real)

        # MCSHELL_TEST_INSTALLED=<an extracted package> runs the same tests
        # against what a package installs instead of against this checkout:
        # its daemon from its site-packages, its tree as the root.
        installed = os.environ.get("MCSHELL_TEST_INSTALLED")
        if installed:
            site = next(Path(installed).glob("usr/lib/python3*/site-packages"))
            extra_env = {"PYTHONPATH": str(site),
                         "MCSHELL_ROOT": str(Path(installed) / "usr/share/mcshell"),
                         **extra_env}

        nobus = f"unix:path={root / 'no-such-bus'}"
        self.env = {
            "HOME": str(self.home),
            "USER": os.environ.get("USER", "test"),
            "LANG": "C.UTF-8",
            "PATH": str(self.bin),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "XDG_STATE_HOME": str(self.home / ".local/state"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_DATA_DIRS": os.pathsep.join(str(d) for d in data_dirs),
            "DBUS_SESSION_BUS_ADDRESS": nobus,
            "DBUS_SYSTEM_BUS_ADDRESS": nobus,
            "MCSHELL_ROOT": str(Path(__file__).resolve().parents[2]),
            **extra_env,
        }
        self.proc: subprocess.Popen | None = None
        self.clients: list[Client] = []

    def start(self, timeout: float = 15.0) -> Daemon:
        with open(self.log, "ab") as log:
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "mcshelld.main", "-v"],
                env=self.env, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, cwd=self.home,
                # A session of its own, as systemd gives it. The daemon
                # protects its whole process group from process_kill, and
                # sharing pytest's would protect everything a test starts.
                start_new_session=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"daemon exited {self.proc.returncode}:\n{self.log_text()}")
            if self.socket.exists():
                try:
                    self.connect().close()
                    return self
                except OSError:
                    pass
            time.sleep(0.05)
        raise TimeoutError(f"daemon never listened:\n{self.log_text()}")

    def connect(self) -> Client:
        client = Client(self.socket)
        self.clients.append(client)
        return client

    def stop(self) -> int | None:
        for client in self.clients:
            try:
                client.close()
            except OSError:
                pass
        self.clients.clear()
        if self.proc is None or self.proc.poll() is not None:
            return self.proc.returncode if self.proc else None
        self.proc.send_signal(signal.SIGTERM)
        try:
            return self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise

    def log_text(self) -> str:
        return self.log.read_text(errors="replace") if self.log.exists() else ""


@pytest.fixture
def root():
    # Short, because a unix socket path past 108 bytes fails, and pytest's
    # tmp_path can be longer than that by itself.
    path = Path(tempfile.mkdtemp(prefix="mcsh-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def make_daemon(root):
    """A factory, for the tests that start the same daemon twice."""
    made: list[Daemon] = []

    def make(data_dirs: list[Path] | None = None, **extra_env: str) -> Daemon:
        d = Daemon(root, data_dirs or [FIXTURES / "share"], extra_env)
        made.append(d)
        return d

    yield make
    for d in made:
        d.stop()
        # Shown by pytest only when the test failed.
        print(f"--- daemon log ({d.log}) ---\n{d.log_text()}")


@pytest.fixture
def daemon(make_daemon) -> Daemon:
    return make_daemon().start()


@pytest.fixture
def client(daemon) -> Client:
    return daemon.connect()
