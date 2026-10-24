"""The command bar: run one line of shell and stream what it prints.

Backs `command_submit`. Knows nothing about Minecraft or about where its output
is drawn — it emits `command_start`, `output`, `command_end` and lets the mod
decide between chat and the overview panel.

This is **not a terminal emulator**. There is no PTY, stdin is `/dev/null`, and
ANSI escapes are stripped rather than interpreted. `vim` and `htop` are expected
to be run as real windows, which is what the trailing `&` is for.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shlex
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

from . import protocol as p
from .paths import ASKPASS

log = logging.getLogger(__name__)

# Long enough for a build, short enough that a command which will never finish
# does not hold the bar forever. A command that legitimately runs longer than
# this wants to be a window, not a chat line.
TIMEOUT = 60.0

# Grace between asking the process group to stop and insisting.
KILL_GRACE = 3.0

# Caps. Both also keep one run's output well under the 1 MiB wire-line limit,
# which a `cat` of anything sizeable would otherwise blow through.
MAX_LINES = 2000
MAX_LINE_CHARS = 512

# Read size. Also the natural batching unit: one `output` message per read, so a
# fast producer sends few large messages and a slow one sends a line at a time.
CHUNK = 4096

# Where sudo is told to ask for a password: paths.ASKPASS. If it is missing,
# nothing is injected and sudo fails the way it would anyway.

# A command runs in its own session with stdin on /dev/null, so sudo has no
# terminal to prompt on and refuses outright. An askpass helper is sudo's own
# answer to that: it asks in a compositor window, which is where CLAUDE.md wants
# credentials to be asked for — never inside the game client, where chat would
# draw the password on screen and keep it in the transcript.
#
# So `sudo` gains `-A`, unless the line already chose how to authenticate. The
# scan stops at the command name so that flags belonging to the program being
# run as root are not mistaken for sudo's. `command sudo` is what stops the
# function from calling itself.
_SUDO_SHIM = """\
sudo() {
    local a
    for a in "$@"; do
        case "$a" in
            -A*|-S*|--askpass|--stdin) command sudo "$@"; return ;;
            --) break ;;
            -*) ;;
            *) break ;;
        esac
    done
    command sudo -A "$@"
}
"""

Emit = Callable[[p.Message], Awaitable[None]]

# CSI sequences (colour, cursor moves) and OSC strings (window titles). Stripped
# rather than rendered — Minecraft draws text, not a terminal.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
# Everything else non-printable, tab excepted. A stray NUL or bell in a line
# would otherwise reach the mod's text renderer.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean(line: str) -> str:
    """Make one line of program output safe to draw as Minecraft text."""
    line = _ANSI.sub("", line)
    # A carriage return means "redraw this line": a progress bar sends several
    # versions of it. Keep the last, which is what a terminal would be showing.
    if "\r" in line:
        line = line.split("\r")[-1]
    line = _CONTROL.sub("", line).rstrip()
    if len(line) > MAX_LINE_CHARS:
        line = line[:MAX_LINE_CHARS] + " …"
    return line


class Shell:
    """One working directory, one command at a time.

    Serialised deliberately: the runs share a cwd and stream into the same
    panel, so two at once would interleave into something unreadable and make
    `cd` ambiguous. A submission while one is running is refused.
    """

    def __init__(self, launch: Callable[[str], Awaitable[bool]] | None = None):
        self.home = Path(os.path.expanduser("~"))
        self.cwd = self.home
        # For `cd -`.
        self._prev = self.home
        self._next_id = 1
        self._current: int | None = None
        self._task: asyncio.Task | None = None
        self._launch = launch

    @property
    def busy(self) -> bool:
        return self._current is not None

    def submit(self, text: str, emit: Emit) -> p.Message | None:
        """Accept a command line and start it.

        Synchronous on purpose: the claim on the shell has to happen before this
        returns, or two submissions arriving in one event-loop turn would both
        see an idle shell. The run itself becomes a task so the daemon keeps
        answering everyone else while a slow command streams.
        """
        text = text.strip()
        if not text:
            # Unreachable from chat, which will not send a blank line, but a
            # hand-written `mcsh` message should get an answer rather than
            # leaving the caller waiting out its timeout.
            return p.Error(message="empty command")
        if self.busy:
            return p.Error(message=f"command {self._current} is still running")

        cmd = self._next_id
        self._next_id += 1
        self._current = cmd
        self._task = asyncio.create_task(self._run(cmd, text, emit), name=f"command-{cmd}")
        return None

    async def stop(self) -> None:
        """Abandon a running command. Called on daemon shutdown."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # -- running -----------------------------------------------------------

    async def _run(self, cmd: int, text: str, emit: Emit) -> None:
        log.info("command %d in %s: %s", cmd, self.cwd, text)
        try:
            await emit(p.CommandStart(cmd=cmd, text=text, cwd=str(self.cwd)))

            if text.endswith("&"):
                code, note = await self._detach(cmd, text[:-1].strip(), emit)
            elif (builtin := self._as_cd(text)) is not None:
                code, note = await self._cd(cmd, builtin, emit)
            elif text == "clear":
                # A builtin because bash's would fail: there is no terminal,
                # so `clear` exits 1 with TERM=dumb and the chat is untouched.
                # Only the bare word — `clear; ls` is bash's business.
                await emit(p.ChatClear(cmd=cmd))
                code, note = 0, ""
            else:
                code, note = await self._capture(cmd, text, emit)

            await emit(p.CommandEnd(cmd=cmd, code=code, note=note))
            log.info("command %d exited %d%s", cmd, code, f" ({note})" if note else "")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("command %d blew up", cmd)
            await emit(p.Output(cmd=cmd, lines=[str(e)], stream="stderr"))
            await emit(p.CommandEnd(cmd=cmd, code=1, note="daemon error"))
        finally:
            self._current = None
            self._task = None

    async def _detach(self, cmd: int, body: str, emit: Emit) -> tuple[int, str]:
        """Launch and let go — the `&` case.

        Handed to Sway's `exec`, the same path a hotbar slot takes, so the app
        belongs to the compositor rather than to the daemon and survives a
        daemon restart. Nothing is captured; a GUI program has no output worth
        putting in chat.
        """
        if not body:
            await emit(p.Output(cmd=cmd, lines=["nothing to launch"], stream="stderr"))
            return 1, ""
        if self._launch is None:
            await emit(p.Output(cmd=cmd, lines=["no compositor to launch into"], stream="stderr"))
            return 1, ""

        # cd into our own working directory first: Sway's exec inherits the
        # compositor's cwd, not ours, and `swayimg shot.png` should mean the
        # file the bar is looking at.
        command = f"cd {shlex.quote(str(self.cwd))} && {body}"
        if not await self._launch(command):
            await emit(p.Output(cmd=cmd, lines=[f"failed to launch {body}"], stream="stderr"))
            return 1, ""
        await emit(p.Output(cmd=cmd, lines=[f"launched {body}"], stream="stdout"))
        return 0, "launched"

    def _as_cd(self, text: str) -> str | None:
        """The argument of a bare `cd` line, or None if this is not one.

        Only a whole line that is nothing but `cd` and at most one argument.
        `cd build && make` still goes to bash, where the directory change is
        scoped to that one command — which is what writing it that way asks
        for.
        """
        try:
            tokens = shlex.split(text)
        except ValueError:
            # Unbalanced quotes. Let bash produce the error message; it words it
            # better than we would.
            return None
        if not tokens or tokens[0] != "cd" or len(tokens) > 2:
            return None
        return tokens[1] if len(tokens) == 2 else "~"

    async def _cd(self, cmd: int, arg: str, emit: Emit) -> tuple[int, str]:
        """The builtin that keeps state.

        Has to be ours: a `cd` run inside `bash -lc` changes a directory that
        stops existing the moment the command exits, so the bar would accept it,
        report nothing, and quietly run the next command somewhere else.
        """
        if arg == "-":
            target = self._prev
        elif arg in ("~", ""):
            target = self.home
        else:
            target = Path(os.path.expanduser(arg))
            if not target.is_absolute():
                target = self.cwd / target

        try:
            resolved = target.resolve(strict=True)
        except OSError:
            await emit(p.Output(cmd=cmd, lines=[f"cd: no such directory: {arg}"], stream="stderr"))
            return 1, ""
        if not resolved.is_dir():
            await emit(p.Output(cmd=cmd, lines=[f"cd: not a directory: {arg}"], stream="stderr"))
            return 1, ""

        self._prev, self.cwd = self.cwd, resolved
        await emit(p.Output(cmd=cmd, lines=[str(resolved)], stream="stdout"))
        return 0, ""

    async def _capture(self, cmd: int, text: str, emit: Emit) -> tuple[int, str]:
        """Run under bash and stream both pipes until it exits."""
        env = dict(os.environ)
        # Ask programs not to colour their output in the first place. Stripping
        # escapes afterwards is the backstop, not the plan.
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"

        # An askpass the user set for themselves wins: theirs is a considered
        # choice about how they are asked for a password, and ours is a default.
        prelude = ""
        if not env.get("SUDO_ASKPASS") and os.access(ASKPASS, os.X_OK):
            env["SUDO_ASKPASS"] = str(ASKPASS)
        if env.get("SUDO_ASKPASS"):
            prelude = _SUDO_SHIM

        try:
            proc = await asyncio.create_subprocess_exec(
                # A login shell: the daemon may have been started from a Sway
                # `exec` with barely any environment, and a bar whose PATH is
                # shorter than the user's terminal PATH would be baffling.
                # The prelude is prepended to what bash runs, never to the
                # `text` the mod echoes: the bar shows the line as typed.
                "bash", "-lc", prelude + text,
                cwd=str(self.cwd),
                # No PTY, so a command that reads stdin gets EOF immediately
                # rather than blocking until the timeout kills it.
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                # Its own process group, so a timeout can stop the whole
                # pipeline instead of only the bash that spawned it.
                start_new_session=True,
            )
        except OSError as e:
            await emit(p.Output(cmd=cmd, lines=[str(e)], stream="stderr"))
            return 1, ""

        budget = [MAX_LINES]
        pumps = [
            asyncio.create_task(self._pump(proc.stdout, "stdout", cmd, emit, budget)),
            asyncio.create_task(self._pump(proc.stderr, "stderr", cmd, emit, budget)),
        ]

        note = ""
        try:
            code = await asyncio.wait_for(asyncio.shield(proc.wait()), TIMEOUT)
        except asyncio.TimeoutError:
            note = f"timed out after {int(TIMEOUT)}s"
            log.warning("command %d %s; terminating", cmd, note)
            code = await self._stop_process(proc)
        except asyncio.CancelledError:
            await self._stop_process(proc)
            for pump in pumps:
                pump.cancel()
            raise

        # Drain whatever is still in the pipes. Bounded: a grandchild that
        # inherited the pipe and outlived the kill would otherwise hold this
        # open, and a finished command must not wedge the bar.
        try:
            await asyncio.wait_for(asyncio.gather(*pumps), 2.0)
        except asyncio.TimeoutError:
            for pump in pumps:
                pump.cancel()

        if budget[0] <= 0:
            note = note or f"output truncated at {MAX_LINES} lines"
        return code, note

    async def _stop_process(self, proc: asyncio.subprocess.Process) -> int:
        """Ask the process group to stop, then insist. Returns the exit code."""
        for sig, grace in ((signal.SIGTERM, KILL_GRACE), (signal.SIGKILL, KILL_GRACE)):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(proc.pid), sig)
            with contextlib.suppress(asyncio.TimeoutError):
                return await asyncio.wait_for(asyncio.shield(proc.wait()), grace)
        return await proc.wait()

    async def _pump(self, stream, name: str, cmd: int, emit: Emit, budget: list[int]) -> None:
        """Forward one pipe, a message per read.

        Reads chunks rather than using `readline`, which raises once a line
        exceeds the stream limit — a minified file or a stray binary would kill
        the run rather than being truncated like every other long line.
        """
        if stream is None:
            return
        partial = b""
        while True:
            chunk = await stream.read(CHUNK)
            if not chunk:
                break
            if budget[0] <= 0:
                continue  # Keep draining so the process is not blocked on a full pipe.
            partial += chunk
            *complete, partial = partial.split(b"\n")
            await self._flush(complete, name, cmd, emit, budget)

        if partial and budget[0] > 0:
            # A last line with no trailing newline.
            await self._flush([partial], name, cmd, emit, budget)

    async def _flush(
        self, raw: list[bytes], name: str, cmd: int, emit: Emit, budget: list[int]
    ) -> None:
        if not raw:
            return
        if len(raw) > budget[0]:
            raw = raw[: budget[0]]
        budget[0] -= len(raw)
        lines = [clean(b.decode("utf-8", errors="replace")) for b in raw]
        if lines:
            await emit(p.Output(cmd=cmd, lines=lines, stream=name))
