"""mcshelld — the mcshell daemon.

asyncio unix socket server speaking newline-delimited JSON. The daemon listens;
the Minecraft mod (and the `mcsh` test harness) connect as clients.

M0 scope: transport, logging, and a live Sway window list. No catalog, no slot
state, no launching.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import socket
import struct
import sys
import time
from pathlib import Path

from . import protocol as p
from .audio import Audio
from .battery import Battery
from .binds import Binds
from .catalog import App, Catalog
from .clock import Clock
from .compositor import Compositor, WindowInfo, is_backdrop
from .files import Files
from .general import General
from .power import Power
from .network import Network
from .notify import Notify
from .osd import Osd
from .boot import Boot
from .overlay import Overlay
from .power import SAVE_TIMEOUT, ShutdownSave
from . import worlds
from .settings import Settings
from .stats import SAMPLE, ScreenTime, Stats
from .shell import Shell
from .video import Video
from .state import SLOT_RANGE, SlotError, State

log = logging.getLogger("mcshelld")

MAX_LINE = 1 << 20  # 1 MiB; a single message should never approach this

# How long a slot stays in the dimmed "launching" state before we give up and
# assume the app died or never mapped a window. Generous, because a cold-start
# Electron app on a spinning disk is genuinely slow.
LAUNCH_TIMEOUT = 25.0

# Windows that keep the size they asked for. Everything else the shell puts on
# screen is an application, and an application covers Minecraft rather than
# floating in the middle of it — but a password prompt is not an application,
# and a full-screen sudo prompt would be absurd. These are the prompters
# daemon/tools/mcshell-askpass chooses between, matched case-insensitively;
# add to the list rather than teaching the fill to guess.
#: How long to wait for the game to confirm it has let go of the mouse.
#: Two client ticks plus slack — the mod acts on the tick after the message,
#: and a tick is 50ms. See Daemon.yield_pointer.
POINTER_YIELD_TIMEOUT = 0.25

KEEP_OWN_SIZE = frozenset(
    {"zenity", "ssh-askpass", "x11-ssh-askpass", "fuzzel", "wofi", "rofi",
     # The desktop's file chooser, opened to pick a notification sound. A file
     # browser stretched over a 1920x1080 backdrop is a worse file browser, and
     # this one is a dialog in every sense but Sway's.
     "xdg-desktop-portal-gtk", "xdg-desktop-portal-gnome", "xdg-desktop-portal-kde"}
)

#: The shell's own surfaces, which are not applications. The toast overlay
#: should never be an ordinary window — it asks for a layer surface, and those
#: are not views and never reach this code. But when its layer-shell preload
#: did not take, it came up as a toplevel and the shell resized it to fill the
#: screen and focused it, which is a notification overlay behaving like an
#: application somebody launched. It refuses to open at all now; this is the
#: second lock on the same door.
OWN_SURFACES = frozenset({"dev.mcshell.toasts"})


def socket_path() -> Path:
    """Location of the daemon socket.

    $XDG_RUNTIME_DIR is per-user and tmpfs-backed, so the socket dies with the
    session — which is what we want.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        runtime = f"/run/user/{os.getuid()}"
        log.warning("XDG_RUNTIME_DIR unset, falling back to %s", runtime)
    return Path(runtime) / "mcshell.sock"


class Daemon:
    def __init__(self, path: Path):
        self.path = path
        self.compositor = Compositor(
            on_change=self._on_windows_changed,
            # A monitor changing is a settings event, not a window one —
            # and it leaves the backdrop the wrong size, so it is both.
            on_outputs=self._on_outputs_changed,
        )
        self.catalog = Catalog()
        self.state = State()
        # The command bar. Launches go through the compositor for the same
        # reason slot launches do: the app should belong to Sway, not to us.
        self.shell = Shell(launch=self.compositor.launch)
        # Settings pages. Each provider owns one page and one subsystem; the
        # daemon only routes. Registering a provider is the whole of adding a
        # page, which is the promise M6 is built on.
        # System notifications, drawn as advancement toasts on a layer-shell
        # surface above every window. Nothing on this machine owned
        # org.freedesktop.Notifications before this did, so a Discord ping in
        # the MCShell session used to go nowhere at all. Not a settings page,
        # but it owns one row on the Sound page, which is where somebody looks
        # for a notification sound.
        # One layer-shell process, two surfaces: the toasts and the volume bar.
        # Shared because the hard part is neither of them, it is getting
        # gtk4-layer-shell loaded before libwayland-client. See overlay.py.
        self.overlay = Overlay()
        # `silent` is late-bound on purpose: Audio takes the notifier (it owns
        # the notification rows on the Sound page) and the notifier has to ask
        # Audio whether the machine is muted before it makes a noise. One of
        # the two has to be built first, and a lambda is cheaper than splitting
        # either of them in half.
        self.notify = Notify(self.catalog, self.overlay,
                             silent=lambda: self.audio.silent())
        # The volume popup. Nothing asks it to draw — the Sound page's own
        # PipeWire subscription notices the level moved and tells it.
        self.osd = Osd(self.overlay)
        # The boot screen: one picture over sway's flat colour, Prism's
        # launcher and Minecraft's own splash. It draws on the same overlay
        # for the same reason the other two do — it has to be above every
        # window, and the game is only the last of the three things it covers.
        self.boot = Boot(self.overlay)
        self.settings = Settings()
        self.audio = Audio(on_change=self._settings_changed,
                           notifications=self.notify,
                           osd=self.osd)
        self.settings.register(self.audio)
        self.settings.register(Video(self.compositor, on_change=self._settings_changed))
        self.settings.register(Binds(self.compositor, on_change=self._settings_changed))
        self.settings.register(Network(on_change=self._settings_changed))

        # Not a settings page: the XP bar's numbers. It pushes rather than
        # being asked, because the HUD draws every frame and must never wait.
        self.battery = Battery(on_change=self._battery_changed)

        # The Statistics screen. Screen time is banked by the daemon because
        # the daemon's lifetime *is* the session: it starts with sway and stops
        # with it.
        # Directories, for the Advancements screen. Stateless: it answers
        # one listing per question and remembers nothing, because a directory
        # stops being true the moment somebody saves a file into it.
        self.files = Files()
        # The pause menu's last button. Launched through the compositor, like
        # the shell's `&`, so the lock screen is not a child of a daemon that
        # a keybinding can restart.
        self.power = Power(launch=self.compositor.launch, notify=self.broadcast)
        # Power off and restart wait for the world to be saved. The game dies
        # with its display at logout, so nothing after that point can save it;
        # see power.ShutdownSave.
        self.shutdown_save = ShutdownSave(save=self.save_world)
        #: The background restart the Worlds screen asked for, if one is running.
        self._restart_task: asyncio.Task | None = None
        #: save_world requests still waiting on the mod, by id.
        self._saves: dict[int, asyncio.Future] = {}
        self._save_id = 0
        self.screentime = ScreenTime()
        self.stats = Stats(self.compositor, self.battery, self.screentime)
        # The wall clock, for the HUD. Not a settings page either — it is the
        # other half of what `hud` carries, and the shell had nowhere at all
        # that said what time it is.
        # The mode is the General page's to keep; it sets it from the saved
        # preferences the moment it is built, two lines below.
        self.clock = Clock(on_tick=self._push_hud)
        # The General page, in the Accessibility lane: the shell's own
        # settings. Registered last because it routes to three things that
        # have to exist first — the clock, notifications and screen time.
        self.general = General(self.clock, notify=self.notify,
                               screentime=self.screentime, osd=self.osd,
                               on_change=self._settings_changed,
                               on_hud=self._push_hud)
        self.settings.register(self.general)
        #: Writers that asked for the live process stream, and what they asked
        #: for. Sampling costs 23ms a second, so nothing runs while the tab is
        #: shut.
        self._watchers: set[asyncio.StreamWriter] = set()
        self._watch_sort = ("cpu", True, 64)
        self._watch_task: asyncio.Task | None = None
        #: pid on the other end of each connection, so the game can be
        #: recognised without guessing at Java command lines.
        self._peers: dict[asyncio.StreamWriter, int] = {}
        self._clients: set[asyncio.StreamWriter] = set()
        #: Each client's last catalog search, so a catalog that changes under
        #: an open catalog screen can be answered again without being asked.
        self._catalog_queries: dict[asyncio.StreamWriter, p.CatalogQuery] = {}
        #: Rebuilds the catalog when an application is installed or removed.
        self._catalog_task: asyncio.Task | None = None
        #: The connections that said `hello` — the game, as opposed to `mcsh`
        #: or anything else on the socket. A request only the game can answer
        #: goes here and nowhere else: broadcast, `mcsh` would read its own
        #: `save_world` back as the reply and exit before the answer came.
        self._games: set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None
        self._next_client_id = 1
        # slot -> deadline after which we stop claiming it is still launching
        self._launching: dict[int, float] = {}
        self._expiry_tasks: set[asyncio.Task] = set()
        # Last taskbar actually sent, so we can suppress no-op pushes.
        self._last_taskbar: dict | None = None
        # Whether Minecraft was in the last window set. See _on_windows_changed.
        self._backdrop_seen = False
        # Last answer sent for "is the game the focused window". See _push_focus.
        self._game_focused: bool | None = None
        # Set when the mod confirms it has let go of the mouse. See yield_pointer.
        self._pointer_released = asyncio.Event()
        # con_ids we have already sized. None until the first window sync, so a
        # daemon restart adopts the windows already open instead of throwing
        # every one of them back to full screen. See _fill_new_windows.
        self._filled: set[int] | None = None

        # slot -> desktop id for applications that are running but unassigned.
        # Memory only, and deliberately: an assignment is something the user
        # made and survives a reboot, while this is a description of what
        # happens to be open. See _transient_slots.
        self._transient: dict[int, str] = {}
        # Hotbar slots the mod says hold ordinary Minecraft items. Memory only
        # for the same reason, and it is the mod's observation rather than
        # anything the daemon could work out for itself.
        self._occupied: set[int] = set()
        # Same, per settings page. PipeWire is chatty and most of what it says
        # changes nothing we draw.
        self._last_settings: dict[str, list] = {}

    async def _on_outputs_changed(self) -> None:
        """A monitor changed shape. Redraw the Video page and refit Minecraft.

        The refit is here rather than in the compositor's own event handler
        because it is a decision — that Minecraft is the backdrop and owes the
        whole output — and decisions live on this side.
        """
        await self.push_settings("video")
        await self.compositor.pin_backdrop()

    # -- lifecycle ---------------------------------------------------------

    async def run(self) -> None:
        # Before anything else, because everything else takes time and the
        # screen is what the login is looking at. It needs nothing from the
        # daemon but the overlay, so there is nothing to wait for.
        await self.boot.start()

        self.catalog.load()
        self.state.load()
        await self.compositor.start()
        if not self.compositor.connected:
            log.warning("running without sway; window queries will return empty")
        await self.settings.start()
        try:
            await self.notify.start()
        except Exception:
            # Notifications are the newest thing here and the least load
            # bearing. A shell that will not come up because a toast server
            # failed would be a bad trade.
            log.exception("notify: failed to start")
        await self.battery.start()
        await self.screentime.start()
        await self.clock.start()
        await self.shutdown_save.start()

        # The screen went up first; this is the floor that says the rest of
        # the daemon caught up with it.
        self.boot.reached("daemon")

        self._unlink_stale()
        self._server = await asyncio.start_unix_server(self._handle_client, path=str(self.path))
        # Socket is per-user only. Nothing else on the box should be able to
        # drive the shell.
        os.chmod(self.path, 0o600)
        log.info("listening on %s", self.path)
        self._catalog_task = asyncio.create_task(
            self.catalog.follow(self._catalog_changed), name="catalog-follow")

        loop = asyncio.get_running_loop()
        stop = loop.create_future()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(
                    sig, lambda s=sig: stop.done() or stop.set_result(s)
                )

        try:
            sig = await stop
            log.info("received %s, shutting down", signal.Signals(sig).name)
        finally:
            await self.shutdown()

    def _unlink_stale(self) -> None:
        """Remove a leftover socket from a daemon that didn't exit cleanly.

        Refuses to clobber a socket that something is still listening on, so a
        second daemon can't silently steal the first one's clients.
        """
        if not self.path.exists():
            return
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect(str(self.path))
        except (ConnectionRefusedError, FileNotFoundError):
            log.info("removing stale socket %s", self.path)
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
        else:
            raise SystemExit(
                f"another mcshelld is already listening on {self.path}; refusing to start"
            )
        finally:
            probe.close()

    async def shutdown(self) -> None:
        # Every step is best-effort and independent: a failure part-way through
        # must not skip the socket unlink, or the next start finds a stale
        # socket and refuses to run.
        with contextlib.suppress(Exception):
            # Stops the boot ticker. A session that is torn down mid-boot must
            # not leave a task writing to a pipe that is closing.
            await self.boot.finish(record=False)
        with contextlib.suppress(Exception):
            await self.shutdown_save.stop()
        if self._catalog_task is not None:
            self._catalog_task.cancel()
        try:
            # Disconnect clients *before* waiting on the server. Since 3.12
            # Server.wait_closed() blocks until every existing connection is
            # done, so waiting first means a client that simply stays connected
            # — which the mod always is — holds shutdown open indefinitely.
            for w in list(self._clients):
                with contextlib.suppress(Exception):
                    w.close()
            if self._server is not None:
                self._server.close()
                with contextlib.suppress(Exception, asyncio.TimeoutError):
                    await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
            for task in list(self._expiry_tasks):
                task.cancel()
            try:
                await self.shell.stop()
                await self.settings.stop()
                await self.notify.stop()
                # After it, since the toast server may still have been writing.
                await self.overlay.stop()
                await self.clock.stop()
                await self.battery.stop()
                await self.screentime.stop()
                await self._stop_watch()
            except Exception:
                log.exception("shell shutdown failed")
            try:
                await self.compositor.stop()
            except Exception:
                log.exception("compositor shutdown failed")
        finally:
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
            log.info("stopped")

    # -- client handling ---------------------------------------------------

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        cid = self._next_client_id
        self._next_client_id += 1
        self._clients.add(writer)
        self._note_peer(writer)
        log.info("client %d connected (%d total)", cid, len(self._clients))

        try:
            while True:
                try:
                    line = await reader.readuntil(b"\n")
                except asyncio.IncompleteReadError as e:
                    if e.partial:
                        log.warning("client %d: truncated line, dropping", cid)
                    break
                except asyncio.LimitOverrunError:
                    log.warning("client %d: line exceeded %d bytes, disconnecting", cid, MAX_LINE)
                    break

                line = line.strip()
                if not line:
                    continue

                log.info("client %d -> %s", cid, line.decode("utf-8", errors="replace"))

                try:
                    msg = p.decode(line)
                except p.ProtocolError as e:
                    log.warning("client %d: %s", cid, e)
                    await self._send(writer, p.Error(message=str(e)))
                    continue

                try:
                    reply = await self.dispatch(msg, writer)
                except Exception as e:
                    log.exception("client %d: handler for %r failed", cid, msg.t)
                    reply = p.Error(message=f"internal error handling {msg.t!r}: {e}")

                # A handler may answer with several messages (hello replies ok
                # and then the current taskbar).
                if reply is None:
                    continue
                for out in (reply if isinstance(reply, list) else [reply]):
                    await self._send(writer, out)
        except (ConnectionResetError, BrokenPipeError):
            log.info("client %d reset the connection", cid)
        finally:
            self._clients.discard(writer)
            self._games.discard(writer)
            self._watchers.discard(writer)
            self._catalog_queries.pop(writer, None)
            self._peers.pop(writer, None)
            self.stats.note_clients(set(self._peers.values()))
            if not self._watchers:
                await self._stop_watch()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            log.info("client %d disconnected (%d remain)", cid, len(self._clients))

    async def _send(self, writer: asyncio.StreamWriter, msg: p.Message) -> None:
        try:
            writer.write(msg.encode())
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            self._clients.discard(writer)
            self._games.discard(writer)

    async def broadcast(self, msg: p.Message) -> None:
        """Push an unsolicited message to every connected client."""
        for w in list(self._clients):
            await self._send(w, msg)

    def _catalog_answer(self, query: p.CatalogQuery) -> p.Catalog:
        return p.Catalog(items=[
            p.CatalogItem(
                id=a.id,
                name=a.name,
                icon_path=a.icon_path,
                categories=list(a.categories),
                tab=a.tab,
            )
            for a in self.catalog.query(query.text, query.tab)
        ])

    async def _catalog_changed(self, added: set[str], removed: set[str]) -> None:
        """An application was installed or removed while the shell was up.

        Each client gets its last search answered again, unasked. The mod
        draws whichever `catalog` arrived last and asks afresh whenever the
        screen opens or the tab changes, so a closed screen loses nothing by
        this and an open one fills in with no protocol change and nothing new
        in the mod.

        Then the taskbar, because the catalog is also how a window is matched
        to an app: something installed from a terminal and launched straight
        away had a window nobody could name, and so no slot to borrow.
        """
        for writer, query in list(self._catalog_queries.items()):
            await self._send(writer, self._catalog_answer(query))
        await self.push_taskbar()

    async def _on_windows_changed(self, windows: list[WindowInfo]) -> None:
        """Push a fresh taskbar whenever Sway's window set changes."""
        log.debug("window set changed: %d window(s)", len(windows))
        # Minecraft arriving is the one window event that is about layout
        # rather than about the taskbar. session/layout.conf sizes it as it
        # maps and lands a few pixels short doing so, because at that moment
        # sway is still working from the size the client first asked for; by
        # the time this event arrives the client has committed. Tracked as a
        # transition so it costs one command per client start, not one per
        # window event, and so it fires again if the client is restarted.
        backdrop = any(is_backdrop(w.app_id) for w in windows)
        if backdrop and not self._backdrop_seen:
            await self.compositor.pin_backdrop()
        self._backdrop_seen = backdrop
        await self._push_focus()
        await self.push_taskbar()
        # After the taskbar, not before: filling a window sleeps briefly, and
        # the hotbar should not wait on it.
        await self._adopt_new_windows(windows)
        # Every sync rather than on adoption: a window's title arrives in its
        # own event, after the window does.
        await self.boot.windows(windows)

    def _focus_message(self) -> p.Focus:
        """Who owns the mouse right now, as Sway sees it."""
        focused = self.compositor.focused()
        return p.Focus(game=focused is not None and is_backdrop(focused.app_id))

    async def _push_focus(self) -> None:
        """Tell the mod whether the game still owns the mouse.

        Minecraft cannot see this happen — protocol.Focus explains why — and a
        game that does not know it lost focus keeps the pointer captured: the
        camera turns under the window being used, and every other XWayland
        application stops receiving clicks while still receiving motion, which
        reads as a window you can type into but not click.

        Sent on the change only. This runs on every window event, and most of
        them do not move focus.
        """
        msg = self._focus_message()
        if msg.game == self._game_focused:
            return
        self._game_focused = msg.game
        log.debug("focus: game=%s", msg.game)
        await self.broadcast(msg)

    def _worlds(self) -> p.Worlds:
        return p.Worlds(
            worlds=[p.WorldInfo(name=n, icon=icon, icon_version=v)
                    for n, icon, v in worlds.listing()],
            chosen=worlds.chosen(), running=worlds.running() or "")

    async def _restart_in_background(self) -> None:
        try:
            error = await self.restart_game()
            if error:
                log.warning("world restart failed: %s", error)
                await self.broadcast(p.Error(message=error))
        except Exception:
            log.exception("world restart failed")

    async def restart_game(self) -> str | None:
        """Save, put the boot screen back up, and restart the game.

        For switching worlds without a reboot. The order matters: a unit stop
        kills the game rather than asking it to leave, so the world is saved
        first; and the boot screen goes up before the restart so this does
        not bring back the Prism window and the Mojang splash a login no
        longer shows. The drawn marker is removed so the client's
        ExecStartPre waits for the screen, exactly as it does at login.

        Not recorded as a boot time — a game restart skips the daemon's own
        startup, and would teach the next login to expect a shorter wait.
        """
        if not await self.save_world():
            log.warning("restart_game: no save confirmed; restarting anyway")
        with contextlib.suppress(OSError):
            os.remove(os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp",
                                   "mcshell-boot.drawn"))
        await self.boot.finish(record=False)
        self.boot = Boot(self.overlay, records=False)
        await self.boot.start()
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "restart", "--no-block", "mcshell-client",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        if proc.returncode:
            await self.boot.finish(record=False)
            return err.decode(errors="replace").strip() or "could not restart the game"
        log.info("restart_game: restarting the client")
        return None

    async def save_world(self, timeout: float = SAVE_TIMEOUT) -> bool:
        """Ask the game to save and flush the world, and wait until it has.

        The same shape as the pointer handshake below: send, then wait on the
        answer with a cap. No game connected is an immediate False, not a wait
        — there is nothing to save and a shutdown is holding for the answer.
        """
        if not self._games:
            return False
        self._save_id += 1
        ident = self._save_id
        answer = asyncio.get_running_loop().create_future()
        self._saves[ident] = answer
        try:
            for game in list(self._games):
                await self._send(game, p.SaveWorld(id=ident))
            return await asyncio.wait_for(answer, timeout)
        except asyncio.TimeoutError:
            log.warning("save_world %d: no answer from the game in %.1fs", ident, timeout)
            return False
        finally:
            self._saves.pop(ident, None)

    async def yield_pointer(self) -> None:
        """Make the game let go of the mouse, and wait until it has.

        Ordering, not politeness, and this handshake exists for nothing else.
        Minecraft is an X client, and GLFW hands an X pointer grab back only
        while the X server still says the game is the focused window: the
        ungrab sits inside a `focused?` test, and once Sway has moved focus
        that test is false and the release is quietly skipped. Tell the game
        afterwards and the grab is stranded — the camera stops turning, which
        looks like a fix, while X goes on routing every other X client's clicks
        into a window that is not listening. Measured both ways: release first
        and an XWayland window receives all of its clicks; release after and it
        receives none of them.

        So the game is asked first and answers, and only then does focus move.
        The wait is capped: a mod that is not running, or is busy loading a
        world, must not be able to stop the shell from focusing a window.
        """
        if self._game_focused is False or not self._clients:
            return
        self._game_focused = False
        self._pointer_released.clear()
        await self.broadcast(p.Focus(game=False))
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._pointer_released.wait(), POINTER_YIELD_TIMEOUT)

    def _app_id_for(self, con_id: int) -> str | None:
        return next((w.app_id for w in self.compositor.windows() if w.con_id == con_id), None)

    async def focus_window(self, con_id: int) -> bool:
        """Focus a window, having first taken the mouse back off the game."""
        if not is_backdrop(self._app_id_for(con_id)):
            await self.yield_pointer()
        return await self.compositor.focus_window(con_id)

    async def _adopt_new_windows(self, windows: list[WindowInfo]) -> None:
        """Raise a newly-appeared application, and size it to the screen.

        Fork A wants an application to *cover* Minecraft. Sway floats every
        window (session/layout.conf explains why) and a floating window keeps
        whatever size its client asked for, so somebody has to say how big an
        application should be — and that is a decision, so it is ours.

        Only the first time a window is seen. After that its size belongs to
        the user, and re-filling on the next window event would undo every
        drag they had made.
        """
        live = {w.con_id for w in windows}
        if self._filled is None:
            # First sync. Whatever is open predates us — very likely because
            # the daemon was restarted under a session someone is using.
            self._filled = live
            if any(is_backdrop(w.app_id) for w in windows):
                # Minecraft was already on screen when we started, so this is
                # not a boot: it is `$mod+Shift+d` under a desktop somebody is
                # using. Putting a loading screen over that and leaving it
                # there until the timeout would make restarting the daemon
                # look exactly like a hang.
                await self.boot.finish(record=False)
            return
        self._filled &= live
        for w in windows:
            if w.con_id in self._filled:
                continue
            self._filled.add(w.con_id)
            if is_backdrop(w.app_id):
                # Minecraft has a window. Prism has done its part, and the
                # game is loading — which is most of what is left of the boot.
                self.boot.reached("backdrop")
                continue
            if (w.app_id or "").lower() in OWN_SURFACES:
                continue
            # Focus first, and before the fill, because focusing is what raises
            # a floating window above the backdrop. Sway focuses a new window
            # by default and that is usually enough — but not for a window
            # opened by another application while Minecraft was being raised,
            # which arrived behind the backdrop and unreachable. A dialog gets
            # this too: an unfocused password prompt is worse than a wide one.
            log.debug("adopting new window %d (%s)", w.con_id, w.app_id)
            # Size first, focus last: the moving happens while nothing is
            # focused, so what ends up focused is a window that has already
            # stopped changing shape. Costs nothing and is one less thing
            # happening to the window the user is about to click in.
            if (w.app_id or "").lower() not in KEEP_OWN_SIZE:
                await self.compositor.fill_window(w.con_id)
            await self.focus_window(w.con_id)

    async def _battery_changed(self, state: p.Battery) -> None:
        """The charge moved, or a cable did. Tell everyone."""
        await self.broadcast(state)

    async def _push_hud(self) -> None:
        """A minute passed, or a HUD preference moved. Redraw the top line."""
        await self.broadcast(self.general.hud())

    async def _settings_changed(self, page: str) -> None:
        """A subsystem changed underneath us — tell whoever is looking."""
        await self.push_settings(page)

    async def push_settings(self, page: str) -> p.SettingsSchema:
        """Rebuild one page and broadcast it, unless nothing actually moved."""
        schema = await self.settings.schema(page)
        rows = [item.__dict__ for item in schema.items]
        if self._last_settings.get(page) != rows:
            self._last_settings[page] = rows
            await self.broadcast(schema)
        return schema

    async def push_taskbar(self) -> p.Taskbar:
        """Broadcast the taskbar, but only when it actually differs.

        Sway emits several events per launch (new, focus, and a title event for
        every prompt redraw), and resyncing on each one produced half a dozen
        identical taskbar messages per app start. The taskbar carries no
        titles, so comparing against the last push collapses that to one.
        """
        taskbar = self.build_taskbar()
        snapshot = taskbar.to_dict()
        if snapshot != self._last_taskbar:
            self._last_taskbar = snapshot
            await self.broadcast(taskbar)
        return taskbar

    def _expire_launch_later(self, slot: int) -> None:
        """Re-push once a launch deadline passes.

        Without this, an app that never maps a window leaves its slot dimmed
        until some unrelated Sway event happens to trigger a rebuild.
        """

        async def sweep() -> None:
            await asyncio.sleep(LAUNCH_TIMEOUT + 0.5)
            if self._launching.get(slot, 0.0) <= time.monotonic():
                self._launching.pop(slot, None)
                await self.push_taskbar()

        task = asyncio.create_task(sweep(), name=f"launch-expiry-{slot}")
        self._expiry_tasks.add(task)
        task.add_done_callback(self._expiry_tasks.discard)

    # -- slot logic --------------------------------------------------------

    def app_in_slot(self, slot: int) -> str | None:
        """What a slot currently holds — assigned, or merely running there.

        Transients are real slots for everything except persistence: clicking
        one focuses, cycles and closes the app it shows, because a slot the
        player can see and cannot use would be worse than no slot at all.
        """
        return self.state.get(slot) or self._transient.get(slot)

    def windows_for_app(self, app: App) -> list[WindowInfo]:
        """Every open window belonging to this app.

        Matched through the catalog rather than by comparing app_id strings
        directly, so an app whose windows use a different class than its
        desktop id (Code, PrismLauncher) is still recognised.
        """
        return [
            w for w in self.compositor.windows()
            if w.app_id.lower() in app.wm_classes
        ]

    def _transient_slots(self) -> dict[int, str]:
        """Running applications nobody assigned, placed in the free slots.

        The hotbar used to show assignments only, which made it a description
        of what someone once chose rather than of what is running. Two ways to
        notice: open a file whose handler is an application you never put on
        the hotbar, or reassign a slot whose app is still open. Both leave a
        window running with nothing on screen admitting it exists, and a
        desktop that hides running applications is worse than one with an
        untidy hotbar.

        Sticky, so an icon does not hop slots when an unrelated app closes: a
        transient keeps the slot it was first given for as long as it is
        running and that slot stays unassigned. Nothing here is written to
        disk — an assignment is a choice, this is an observation.

        Nine slots is nine slots. If the hotbar is full, a further application
        gets no icon; the alternative is evicting something the user chose in
        favour of something they did not.
        """
        assigned = dict(self.state.items())
        claimed = {app_id for app_id in assigned.values() if app_id}

        running: dict[str, None] = {}
        for w in self.compositor.windows():
            if is_backdrop(w.app_id):
                continue
            app = self.catalog.match_window(w.app_id)
            # No desktop file means no name and no icon, so there is nothing to
            # draw. Rare, and better than a blank slot that cannot be explained.
            if app is None or app.id in claimed:
                continue
            running[app.id] = None

        self._transient = {
            index: app_id
            for index, app_id in self._transient.items()
            if app_id in running and assigned.get(index) is None
        }
        held = set(self._transient.values())
        free = [
            index
            for index, app_id in assigned.items()
            if app_id is None and index not in self._transient
        ]
        # Empty slots before slots with something in them. The hotbar is a real
        # inventory, so an unassigned slot can still be full of wood; putting an
        # application there costs the player a shuffle into storage, and there
        # is no reason to pay it while a genuinely empty slot is going spare.
        # Stable, so slot order still decides within each group.
        free.sort(key=lambda index: index in self._occupied)
        for app_id in running:
            if app_id in held:
                continue
            if not free:
                # Worth saying out loud. The icon is missing for a reason the
                # user can act on — free a slot — and silence here looks
                # exactly like the bug this whole thing exists to fix.
                log.info("hotbar full; %s is running with no slot to show it", app_id)
                continue
            self._transient[free.pop(0)] = app_id

        return dict(self._transient)

    def build_taskbar(self) -> p.Taskbar:
        """The current hotbar, as nine dense slots."""
        now = time.monotonic()
        slots: list[p.TaskbarSlot] = []
        transient = self._transient_slots()

        for index, app_id in self.state.items():
            transient_here = app_id is None and index in transient
            if transient_here:
                app_id = transient[index]
            if app_id is None:
                slots.append(p.TaskbarSlot(i=index))
                continue

            app = self.catalog.get(app_id)
            if app is None:
                # Assigned to something no longer installed. Keep the slot so
                # the assignment isn't silently lost on an upgrade blip, but
                # show it as empty-handed.
                slots.append(p.TaskbarSlot(i=index, app=app_id))
                continue

            windows = self.windows_for_app(app)
            # A window has appeared, so the app is no longer merely launching.
            if windows and index in self._launching:
                del self._launching[index]
            launching = self._launching.get(index, 0.0) > now

            slots.append(p.TaskbarSlot(
                i=index,
                app=app_id,
                name=app.name,
                icon_path=app.icon_path,
                running=bool(windows),
                windows=len(windows),
                focused=any(w.focused for w in windows),
                launching=launching,
                transient=transient_here,
            ))

        return p.Taskbar(slots=slots)

    async def _arrange(self, arrangement: dict[str, str]) -> p.Message:
        """Apply a hotbar the player rearranged by hand.

        Diffed against the taskbar as last built, not applied wholesale. The
        report describes every slot including the transient ones, and a
        transient is not an assignment — writing the whole picture down would
        quietly turn every application that merely happens to be running into a
        permanent choice the user never made.

        So only what actually moved is acted on:

        * an application somewhere new is assigned there, transient or not,
          because dragging one to a slot is exactly the deliberate act that a
          transient slot is defined as lacking;
        * a slot the player emptied is cleared, unless it was only ever
          transient — there is no assignment to remove, and the application is
          still running, so the hotbar will show it again in the first free
          slot. That is the rule from the beginning: nine slots is nine slots,
          and an application that is open gets to say so.
        """
        taskbar = self.build_taskbar()
        sent = {s.i: s.app for s in taskbar.slots if s.app}

        wanted: dict[int, str] = {}
        for key, app_id in (arrangement or {}).items():
            try:
                slot = self.state.check_slot(int(key))
            except (TypeError, ValueError, SlotError):
                log.warning("arrange: ignoring slot %r", key)
                continue
            if not isinstance(app_id, str) or not app_id:
                continue
            wanted[slot] = app_id

        for slot in SLOT_RANGE:
            now = wanted.get(slot)
            before = sent.get(slot)
            if now == before:
                continue

            if now is None:
                if self.state.get(slot) is None:
                    log.info(
                        "slot %d was showing %s because it is running, not "
                        "because it was assigned; it will come back",
                        slot, before,
                    )
                    continue
                self.state.clear(slot)
                self._launching.pop(slot, None)
                log.info("slot %d cleared by hand", slot)
                continue

            if self.catalog.get(now) is None:
                log.warning("arrange: no such app %r for slot %d", now, slot)
                continue
            self.state.assign(slot, now)
            log.info("slot %d assigned to %s by hand", slot, now)

        return await self.push_taskbar()

    async def _activate(self, slot: int, button: str) -> p.Message:
        """Right-click: focus, or launch if not running. Left-click: cycle.

        Shift+right-click launches another one regardless. Without it the
        hotbar could only ever start an app's first window, and a second one
        had to come from the app's own File > New Window or from `foo &` in
        the command bar — neither of which is the hotbar. Shift is the
        modifier because right-click already means "launch if not running",
        so shift+right reads as launch anyway, and because shift is already
        the guard on the one other action a slot can take (close).

        An app that is single-instance decides for itself what a second launch
        means; some open a window, some raise the one they have. That is the
        app's call, not ours.
        """
        app_id = self.app_in_slot(slot)
        if app_id is None:
            return p.Error(message=f"slot {slot} is empty")

        app = self.catalog.get(app_id)
        if app is None:
            return p.Error(message=f"slot {slot} holds {app_id!r}, which is not installed")

        windows = self.windows_for_app(app)

        if not windows or button == "shift_right":
            if button == "left":
                # Left-click cycles windows; with none open there is nothing to
                # cycle. Launching here would make left and right identical.
                return p.Error(message=f"{app.name} is not running")
            command = app.command(self.catalog.terminal_cmd)
            log.info("slot %d: launching %s -> %s", slot, app.name, command)
            if not await self.compositor.launch(command):
                return p.Error(message=f"failed to launch {app.name}")
            if not windows:
                # Only a cold start dims the slot. An app that is already
                # running is already drawn as running, and build_taskbar drops
                # the marker the moment it sees a window in any case.
                self._launching[slot] = time.monotonic() + LAUNCH_TIMEOUT
                self._expire_launch_later(slot)
            return await self.push_taskbar()

        if button == "left":
            target = self.compositor.next_window_for(windows[0].app_id)
        else:
            # The window you were last in, the way a taskbar returns you to it,
            # rather than the app's oldest window.
            #
            # Not `not w.focused`: Minecraft holds compositor focus for the
            # whole time the overview is open, so no window of the app is ever
            # focused at the moment of the click and that test selected the
            # first window every time.
            target = self.compositor.last_focused_for(windows[0].app_id) or windows[0]
            # Focus follows the window to its workspace, rather than dragging
            # the window here — decided in CLAUDE.md's open question 1.

        if target is None:
            return p.Error(message=f"no window to focus for {app.name}")
        log.info("slot %d: focusing %s con_id=%d", slot, app.name, target.con_id)
        await self.focus_window(target.con_id)
        return await self.push_taskbar()

    async def _close(self, slot: int) -> p.Message:
        """Close one window of the slot's app — the one last used.

        Not the focused one: the overview is a Screen inside Minecraft, so
        Minecraft still holds compositor focus while the player is clicking,
        and asking Sway what is focused now closes the app's oldest window
        instead of the one they just came out of.
        """
        app_id = self.app_in_slot(slot)
        if app_id is None:
            return p.Error(message=f"slot {slot} is empty")
        app = self.catalog.get(app_id)
        if app is None:
            return p.Error(message=f"slot {slot} holds {app_id!r}, which is not installed")

        windows = self.windows_for_app(app)
        if not windows:
            return p.Error(message=f"{app.name} is not running")

        target = self.compositor.last_focused_for(windows[0].app_id) or windows[0]
        log.info("slot %d: closing %s con_id=%d", slot, app.name, target.con_id)
        await self.compositor.close_window(target.con_id)
        return await self.push_taskbar()

    # -- dispatch ----------------------------------------------------------

    def _note_peer(self, writer: asyncio.StreamWriter) -> None:
        """Record which process is on the other end of this socket.

        SO_PEERCRED is the kernel's answer, not the client's, so it cannot be
        lied about. It is how the Minecraft client is recognised as one of the
        processes the task manager must refuse to kill — matching on a Java
        command line would be a guess, and would also protect every other Java
        program on the machine.
        """
        sock = writer.get_extra_info("socket")
        if sock is None:
            return
        try:
            raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                  struct.calcsize("3i"))
            pid, _, _ = struct.unpack("3i", raw)
        except (OSError, struct.error):
            return
        if pid > 0:
            self._peers[writer] = pid
            self.stats.note_clients(set(self._peers.values()))

    # -- the live process stream -------------------------------------------

    async def _start_watch(self, writer: asyncio.StreamWriter, msg: p.StatsWatch) -> None:
        self._watchers.add(writer)
        self._watch_sort = (msg.sort, msg.desc, msg.limit)
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.create_task(self._watch_loop(), name="stats-watch")

    async def _stop_watch(self) -> None:
        task, self._watch_task = self._watch_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _watch_loop(self) -> None:
        """Sample, and send to whoever is looking, until nobody is.

        The first sample of a run is discarded: a CPU percentage is work done
        between two looks, and there is no such thing as the first one.
        """
        self.stats.sample()
        while self._watchers:
            await asyncio.sleep(SAMPLE)
            sort, desc, limit = self._watch_sort
            try:
                snapshot = self.stats.sample(sort, desc, limit)
            except Exception:
                log.exception("stats: sampling failed")
                return
            for writer in list(self._watchers):
                await self._send(writer, snapshot)
        self._watch_task = None

    async def dispatch(self, msg: p.Message,
                       writer: asyncio.StreamWriter | None = None
                       ) -> p.Message | list[p.Message] | None:
        if isinstance(msg, p.Hello):
            if msg.proto != p.PROTO_VERSION:
                return p.Error(
                    message=f"proto {msg.proto} unsupported, daemon speaks {p.PROTO_VERSION}"
                )
            log.info("hello from mc %s (proto %d)", msg.mc, msg.proto)
            # The mod is running, so the client is past its own startup. Not
            # the end of the boot: the world is still loading behind the splash.
            self.boot.reached("mod")
            if writer is not None:
                self._games.add(writer)
            # Hand over current state on connect, so a mod that reconnects
            # after a daemon restart renders immediately instead of waiting for
            # the next window event. Recorded as the last push so the next real
            # change doesn't resend an identical taskbar.
            taskbar = self.build_taskbar()
            self._last_taskbar = taskbar.to_dict()
            focus = self._focus_message()
            self._game_focused = focus.game
            return [p.Ok(), taskbar, focus, self.battery.state(), self.general.hud()]

        if isinstance(msg, p.FocusAck):
            self._pointer_released.set()
            return None

        if isinstance(msg, p.WorldsQuery):
            return self._worlds()

        if isinstance(msg, p.WorldChoose):
            error = worlds.choose(msg.name)
            return p.Error(message=error) if error else self._worlds()

        if isinstance(msg, p.WorldRestart):
            # In the background and answered at once, like power actions: the
            # save can take four seconds and this is the pointer's socket.
            if self._restart_task is not None and not self._restart_task.done():
                return p.Error(message="already restarting")
            running = worlds.running()
            if running is not None and running == worlds.chosen():
                return p.Error(message="that is already the world you are in")
            self._restart_task = asyncio.create_task(self._restart_in_background())
            return p.Ok()

        if isinstance(msg, p.WorldSaved):
            answer = self._saves.get(msg.id)
            if answer is not None and not answer.done():
                answer.set_result(bool(msg.ok))
            log.info("world_saved %d: ok=%s in %dms", msg.id, msg.ok, msg.ms)
            return None

        if isinstance(msg, p.SaveWorld):
            # From a client such as mcsh: the same save a shutdown asks for, on
            # demand. The mod never sends this, so it is never an echo.
            started = time.monotonic()
            ok = await self.save_world()
            return p.WorldSaved(id=self._save_id, ok=ok,
                                ms=round((time.monotonic() - started) * 1000))

        if isinstance(msg, p.OsdVolume):
            # The media keys, saying they were pressed. The volume itself went
            # through `wpctl` before this arrived; this only draws the bar.
            await self.audio.announce_level()
            return None

        if isinstance(msg, p.LaunchMode):
            # The launcher found no network. Only the boot screen cares.
            if msg.offline:
                self.boot.offline()
            return None

        if isinstance(msg, p.WorldReady):
            # The one thing that may end the boot screen normally. Everything
            # else it draws is an estimate; this is the desktop saying it is
            # there.
            await self.boot.finish()
            return None

        if isinstance(msg, p.Ping):
            return p.Pong()

        if isinstance(msg, p.WindowsQuery):
            return p.Windows(windows=self.compositor.windows())

        if isinstance(msg, p.CatalogQuery):
            if writer is not None:
                self._catalog_queries[writer] = msg
            return self._catalog_answer(msg)

        if isinstance(msg, p.SlotAssign):
            if self.catalog.get(msg.app) is None:
                return p.Error(message=f"no such app {msg.app!r}")
            try:
                self.state.assign(msg.slot, msg.app)
            except SlotError as e:
                return p.Error(message=str(e))
            log.info("slot %d assigned to %s", msg.slot, msg.app)
            return await self.push_taskbar()

        if isinstance(msg, p.SlotClear):
            try:
                cleared = self.state.clear(msg.slot)
            except SlotError as e:
                return p.Error(message=str(e))
            # A transient is not an assignment, so there is nothing to clear.
            # Saying so beats a click that appears to do nothing: the icon is
            # there because the app is running, and closing it is what removes
            # it.
            if not cleared and msg.slot in self._transient:
                return p.Error(
                    message=f"slot {msg.slot} is not assigned — "
                    f"it shows {self._transient[msg.slot]} because it is running"
                )
            self._launching.pop(msg.slot, None)
            log.info("slot %d cleared", msg.slot)
            return await self.push_taskbar()

        if isinstance(msg, p.SlotsOccupied):
            occupied = {
                i for i in (msg.slots or [])
                if isinstance(i, int) and i in SLOT_RANGE
            }
            if occupied == self._occupied:
                return p.Ok()
            self._occupied = occupied
            # Where a transient can go may have changed, so the hotbar may have.
            return await self.push_taskbar()

        if isinstance(msg, p.SlotsArrange):
            return await self._arrange(msg.slots)

        if isinstance(msg, p.SlotActivate):
            try:
                slot = self.state.check_slot(msg.slot)
            except SlotError as e:
                return p.Error(message=str(e))
            return await self._activate(slot, msg.button)

        if isinstance(msg, p.SlotClose):
            try:
                slot = self.state.check_slot(msg.slot)
            except SlotError as e:
                return p.Error(message=str(e))
            return await self._close(slot)

        if isinstance(msg, p.OverviewSet):
            # Broadcast rather than reply: the sender is usually `mcsh`, run
            # from a Sway binding, and the message is meant for the mod.
            overview = p.Overview(show=msg.show)
            log.info("overview %s", "show" if msg.show else "hide")
            await self.broadcast(overview)
            return overview

        if isinstance(msg, p.CommandSubmit):
            # Broadcast rather than replied, and the same for every client: the
            # bar and `mcsh` are two views of one shell, so a command typed in
            # either should echo in both. Errors (an empty line, a shell that is
            # busy) go back to the sender alone — nobody else asked.
            return self.shell.submit(msg.text, self.broadcast)

        if isinstance(msg, p.SettingsQuery):
            schema = await self.settings.schema(msg.page)
            if msg.page:
                self._last_settings[msg.page] = [i.__dict__ for i in schema.items]
            return schema

        if isinstance(msg, p.SettingSet):
            error = await self.settings.set(msg.key, msg.value)
            if error is not None:
                log.warning("setting %s rejected: %s", msg.key, error)
                return p.Error(message=error)
            log.info("setting %s = %r", msg.key, msg.value)
            # Broadcast the page rather than reply with it: a volume changed
            # from `mcsh` should move the slider in Minecraft. The subsystem
            # usually tells us too, but not always and not immediately, and a
            # settings page that lags its own click reads as broken.
            page = msg.key.split(".", 1)[0]
            self._last_settings.pop(page, None)
            return await self.push_settings(page)

        if isinstance(msg, p.DirQuery):
            return self.files.list(msg.path, msg.offset, msg.limit)

        if isinstance(msg, p.PowerAction):
            log.info("power action requested: %s", msg.action)
            return await self.power.act(msg.action)

        if isinstance(msg, p.StatsQuery):
            tab = msg.tab or "general"
            if tab == "disks":
                return p.Stats(tab=tab, rows=await self.stats.disks())
            if tab == "general":
                return p.Stats(tab=tab, rows=await self.stats.general())
            return p.Error(message=f"no such statistics tab: {tab!r}")

        if isinstance(msg, p.StatsWatch):
            if writer is None:
                return p.Error(message="stats_watch needs a connection")
            if msg.on:
                await self._start_watch(writer, msg)
            else:
                self._watchers.discard(writer)
                if not self._watchers:
                    await self._stop_watch()
            return p.Ok()

        if isinstance(msg, p.ProcessKill):
            error = self.stats.kill(msg.pid)
            return p.Error(message=error) if error else p.Ok()

        if isinstance(msg, p.TaskbarQuery):
            return self.build_taskbar()

        # Real protocol messages still waiting on their milestone.
        return p.Error(message=f"{msg.t!r} not implemented yet")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mcshelld", description="mcshell daemon")
    ap.add_argument("-s", "--socket", type=Path, default=None, help="socket path override")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    path = args.socket or socket_path()
    daemon = Daemon(path)
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
