"""Application catalog: .desktop parsing, icon resolution, search.

Backed by freedesktop `.desktop` files found on XDG_DATA_DIRS, parsed with
pyxdg. Knows nothing about slots, windows or Minecraft — it answers "what
applications exist on this machine, and how do I identify their windows".
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Awaitable, Callable

import xdg.IconTheme
from xdg import BaseDirectory
from xdg.DesktopEntry import DesktopEntry
from xdg.IconTheme import getIconPath

log = logging.getLogger(__name__)

# librsvg's renderer, used to turn SVG-only icons into something the mod can
# load. Looked up once: it is either installed or it is not, and probing per
# icon would fork nothing useful 39 times.
_RSVG = which("rsvg-convert")

#: How often the applications directories are looked at, in seconds. Each look
#: is one `stat` per directory — five on this machine — so this is about how
#: soon a new app should appear, not about cost.
POLL = 2.0

#: How long the directories must stay unchanged before the catalog is rebuilt.
#: An install is not one write: pacman extracts a package file by file, an
#: upgrade replaces the .desktop file under the old one, and a transaction can
#: be several packages. Rebuilding mid-way would read half an install.
SETTLE = 2.0

#: How long after a rescan to look once more, for a new app that came up with
#: no icon. A .desktop file and its icon usually land in the same transaction,
#: but not always — an icon theme in another package, a hook that runs after.
SECOND_LOOK = 6.0

# Freedesktop categories mapped onto the creative-mode tabs named in CLAUDE.md.
#
# The tabs are deliberately not the freedesktop main categories. Those are
# written for menu editors, not for someone deciding where their browser lives:
# Firefox is "Network", a terminal is "System", and GIMP and VLC share nothing.
# These six are named the way a person would say them out loud.
#
# Order is priority — an app tagged Development;TextEditor lands in the first
# entry it matches, so the more specific line must come first. The cases that
# actually decide the order:
#
#   Game before everything     Steam declares Network;FileTransfer;Game
#   WebBrowser before Network  every browser is also Network
#   Development before TextEditor
#                              VS Code is Utility;TextEditor;Development;IDE
#                              and belongs with the dev tools, while gedit is
#                              Utility;TextEditor and belongs with the writing
#   Settings before System     control panels are nearly always tagged both
#   Monitor before Network     Wireshark is Network;Monitor;System
#   Network last of the above  so a network *dev* tool still lands in Tech
TAB_PRIORITY: list[tuple[str, str]] = [
    # Games
    ("Game", "Games"),

    # Browsing — the machine talking to other machines
    ("WebBrowser", "Browsing"),
    ("Email", "Browsing"),
    ("Chat", "Browsing"),
    ("InstantMessaging", "Browsing"),
    ("IRCClient", "Browsing"),
    ("VideoConference", "Browsing"),
    ("Telephony", "Browsing"),
    ("News", "Browsing"),
    ("Feed", "Browsing"),
    ("P2P", "Browsing"),
    ("RemoteAccess", "Browsing"),

    # Tech — things you use to change the machine itself
    ("Development", "Tech"),
    ("IDE", "Tech"),
    ("Building", "Tech"),
    ("Debugger", "Tech"),
    ("RevisionControl", "Tech"),
    ("Settings", "Tech"),
    ("TerminalEmulator", "Tech"),
    ("Monitor", "Tech"),
    ("Security", "Tech"),
    ("PackageManager", "Tech"),
    ("Emulator", "Tech"),
    ("System", "Tech"),

    # Productivity — reading, writing, planning
    ("Office", "Productivity"),
    ("WordProcessor", "Productivity"),
    ("Spreadsheet", "Productivity"),
    ("Presentation", "Productivity"),
    ("TextEditor", "Productivity"),
    ("Calendar", "Productivity"),
    ("ContactManagement", "Productivity"),
    ("ProjectManagement", "Productivity"),
    ("Finance", "Productivity"),
    ("Dictionary", "Productivity"),
    ("Publishing", "Productivity"),
    ("Education", "Productivity"),
    ("Science", "Productivity"),

    # Media — pictures and sound, made or played
    ("Graphics", "Media"),
    ("Photography", "Media"),
    ("AudioVideo", "Media"),
    ("Audio", "Media"),
    ("Video", "Media"),
    ("Music", "Media"),
    ("Player", "Media"),
    ("Recorder", "Media"),

    # The generic network tag, after every specific one above.
    ("Network", "Browsing"),

    # Utility is freedesktop's own catch-all, so it maps to ours.
    ("Utility", "Misc"),
    ("Accessibility", "Misc"),
]

# Tab order in the catalog browser, left to right. The mod adds its own Search
# tab, which is not a category — it queries across all of them.
TABS = ["Games", "Browsing", "Productivity", "Media", "Tech", "Misc"]

DEFAULT_TAB = "Misc"

# How to tell each terminal emulator what app_id to give its window.
#
# A console app's window belongs to the *terminal*, not to the app: launching
# Vim runs `foot -e vim`, and Sway sees one more window with app_id "foot".
# Nothing can then tell that window apart from a plain terminal, so a slot
# holding Vim shows as stopped, cannot be focused, and cannot be closed.
#
# Naming the window on the way out fixes it at the source. Terminals that offer
# no such flag fall through to the old behaviour rather than being launched with
# a flag they will reject.
TERMINAL_APP_ID_FLAG: dict[str, str] = {
    "foot": "--app-id",
    "footclient": "--app-id",
    "kitty": "--class",
    "alacritty": "--class",
    "ghostty": "--class",
}

# Prefix for those synthetic app_ids. Namespaced so it cannot collide with a
# real application's own app_id.
TERMINAL_APP_ID_PREFIX = "mcshell."

# Exec field codes. Everything here is either a file/URL argument we have none
# of, or metadata the launcher is not required to supply, so all of them are
# dropped. %% is an escaped literal percent and is handled separately.
FIELD_CODES = re.compile(r"%[fFuUdDnNickvm]")


@dataclass(frozen=True)
class App:
    """One launchable application."""

    id: str                     # desktop file id, e.g. "firefox.desktop"
    name: str
    icon_path: str | None
    categories: tuple[str, ...]
    tab: str
    exec_line: str              # field codes already stripped
    terminal: bool              # needs a terminal emulator wrapped around it
    workdir: str | None
    wm_classes: frozenset[str]  # lowercase app_id candidates for its windows
    startup_wm_class: str | None  # the authoritative one, when declared
    generic_name: str           # e.g. "Web Browser" for Firefox
    keywords: tuple[str, ...]
    source: str                 # path of the .desktop file

    @property
    def terminal_app_id(self) -> str:
        """The app_id given to this app's terminal window. See TERMINAL_APP_ID_FLAG."""
        return TERMINAL_APP_ID_PREFIX + self.id.removesuffix(".desktop")

    def command(self, terminal_cmd: str = "foot") -> str:
        """The shell command that launches this app."""
        if not self.terminal:
            return self.exec_line

        try:
            argv = shlex.split(terminal_cmd)
        except ValueError:
            argv = terminal_cmd.split()
        flag = TERMINAL_APP_ID_FLAG.get(Path(argv[0]).name) if argv else None
        if flag is None:
            return f"{terminal_cmd} -e {self.exec_line}"
        return f"{terminal_cmd} {flag}={shlex.quote(self.terminal_app_id)} -e {self.exec_line}"


def _strip_field_codes(exec_line: str) -> str:
    """Remove Exec field codes, per the Desktop Entry Specification."""
    # Guard %% first so a literal percent isn't seen as a code.
    out = exec_line.replace("%%", "\x00")
    out = FIELD_CODES.sub("", out)
    return " ".join(out.replace("\x00", "%").split())


def _wm_class_candidates(
    entry: DesktopEntry, app_id: str, exec_line: str, terminal: bool = False
) -> frozenset[str]:
    """Plausible Sway app_id / window_class values for this app's windows.

    StartupWMClass is authoritative when present, but only 18 of 157 files on a
    typical Arch install set it, so fall back to the desktop file's own id and
    the basename of the executable. Matching is done case-insensitively because
    XWayland classes are routinely capitalised ("Code", "PrismLauncher") while
    Wayland app_ids are not.
    """
    out: set[str] = set()

    wmclass = entry.getStartupWMClass()
    if wmclass:
        out.add(wmclass)

    # "firefox.desktop" -> "firefox"; also keep the reverse-DNS tail, since
    # org.gnome.Nautilus.desktop produces app_id "org.gnome.Nautilus".
    stem = app_id.removesuffix(".desktop")
    out.add(stem)
    if "." in stem:
        out.add(stem.rsplit(".", 1)[-1])

    try:
        argv = shlex.split(exec_line)
    except ValueError:
        argv = exec_line.split()
    if argv:
        out.add(Path(argv[0]).name)

    if terminal:
        # The window this app will actually get, when the terminal accepts an
        # app_id flag. Without it the executable basename ("vim") is the only
        # candidate, and no window ever carries it.
        out.add(TERMINAL_APP_ID_PREFIX + app_id.removesuffix(".desktop"))
        # ...and drop the basename, which cannot match and would otherwise let
        # a console app claim a class it can never own.
        out.discard(Path(argv[0]).name if argv else "")

    return frozenset(c.lower() for c in out if c)


class Catalog:
    """The set of installed applications.

    Call `load()` to scan; `query()` to search; `match_window()` to go the
    other way, from a live window's app_id back to the app that owns it.
    """

    def __init__(self, icon_size: int = 48, terminal_cmd: str | None = None):
        self.icon_size = icon_size
        # $TERMINAL, which start-session.sh exports and sway hands the units.
        self.terminal_cmd = terminal_cmd or os.environ.get("TERMINAL") or "foot"
        self.apps: dict[str, App] = {}
        self._by_wm_class: dict[str, str] = {}
        self._raster_cache = Path(
            BaseDirectory.xdg_cache_home) / "mcshell" / "icons"
        #: pyxdg's icon caches are module globals with no locking, and a
        #: rescan runs on a worker thread while notifications resolve icons on
        #: the event loop. One lookup at a time.
        self._icons = threading.Lock()

    # -- loading -----------------------------------------------------------

    def search_dirs(self) -> list[Path]:
        """`applications` dirs, most-specific first.

        BaseDirectory.xdg_data_dirs already puts XDG_DATA_HOME ahead of
        XDG_DATA_DIRS, which is the precedence we want: a user's override of a
        system .desktop file wins.
        """
        return [Path(d) / "applications" for d in BaseDirectory.xdg_data_dirs]

    def load(self) -> int:
        """(Re)scan every applications dir. Returns the number of apps found."""
        self.install(self.scan())
        log.info("catalog: %d apps from %d dirs", len(self.apps), len(self.search_dirs()))
        return len(self.apps)

    def install(self, apps: dict[str, App]) -> None:
        """Make a finished scan the catalog. Cheap, and on the caller's thread."""
        self.apps = apps
        self._reindex()

    def scan(self) -> dict[str, App]:
        """Read every .desktop file and resolve every icon, touching nothing.

        Separate from `install` so it can run on a worker thread: it is 0.38s
        warm and 0.75s cold — measured — and the event loop carries the pointer
        handshake, which gives up after 250ms.
        """
        apps: dict[str, App] = {}

        for base in self.search_dirs():
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*.desktop")):
                # Desktop ids are relative to the applications dir, with
                # subdirectory separators becoming dashes: kde/foo.desktop is
                # the id "kde-foo.desktop".
                app_id = str(path.relative_to(base)).replace(os.sep, "-")
                if app_id in apps:
                    continue  # earlier (more specific) dir already won
                app = self._parse(path, app_id)
                if app is not None:
                    apps[app_id] = app
        return apps

    # -- following installs --------------------------------------------------

    def signature(self) -> tuple:
        """What the applications directories look like, as cheaply as asked.

        A directory's mtime moves whenever an entry is created, removed or
        renamed into it — which is every way an install, an upgrade or an
        uninstall touches a .desktop file. A directory that does not exist yet
        counts too: Flatpak's export directories are made by the first Flatpak
        install, and on this machine neither exists.
        """
        out = []
        for base in self.search_dirs():
            try:
                out.append((str(base), base.stat().st_mtime_ns))
            except OSError:
                out.append((str(base), None))
        return tuple(out)

    async def follow(self, on_change: Callable[[set[str], set[str]], Awaitable[None]]) -> None:
        """Rebuild the catalog whenever an application is installed or removed.

        Until this, the catalog was read once, when the daemon started, so an
        app installed mid-session did not exist as far as the shell could tell
        until the next login — not in the catalog, and not in the hotbar either,
        because a window can only borrow a slot if the catalog knows whose it is.

        Polled, not watched. inotify has no binding in the standard library,
        directories come into existence later (Flatpak's), and five `stat`
        calls every two seconds cost nothing measurable. What it does not see
        is an existing .desktop file edited in place — that is not an install.

        `on_change(added, removed)` is awaited with desktop ids after each
        rebuild that changed anything.
        """
        seen = self.signature()
        while True:
            await asyncio.sleep(POLL)
            now = self.signature()
            if now == seen:
                continue
            # Wait for the install to finish: unchanged for SETTLE seconds.
            while True:
                await asyncio.sleep(SETTLE)
                later = self.signature()
                if later == now:
                    break
                now = later
            seen = now
            await self._rebuild(on_change)

    async def _rebuild(self, on_change, retry: bool = True) -> None:
        before = self.apps
        self._forget_icons()
        try:
            apps = await asyncio.to_thread(self.scan)
        except Exception:
            log.exception("catalog: rescan failed; keeping the old one")
            return
        self.install(apps)
        added, removed = set(apps) - set(before), set(before) - set(apps)
        # An app that was already there but looks different now — an icon that
        # turned up, a rename in an upgrade — is a change worth redrawing too.
        changed = {a for a in apps.keys() & before.keys() if apps[a] != before[a]}
        log.info("catalog: rescanned, %d apps (+%d %s, -%d %s, ~%d)", len(apps),
                 len(added), sorted(added), len(removed), sorted(removed), len(changed))
        if added or removed or changed:
            await on_change(added, removed)
        # A new app that came up without an icon gets one more look, in case
        # its icon landed a moment after its .desktop file.
        if retry and any(apps[a].icon_path is None for a in added):
            await asyncio.sleep(SECOND_LOOK)
            await self._rebuild(on_change, retry=False)

    def _parse(self, path: Path, app_id: str) -> App | None:
        try:
            entry = DesktopEntry(str(path))
        except Exception as e:
            log.debug("skipping %s: unparseable (%s)", path, e)
            return None

        if entry.getType() != "Application":
            return None
        # NoDisplay means "valid, but not for menus" — 76 of 157 files on a
        # stock Arch install, mostly MIME handlers. Hidden means "deleted".
        if entry.getNoDisplay() or entry.getHidden():
            return None

        exec_line = _strip_field_codes(entry.getExec())
        if not exec_line:
            return None

        # TryExec names a binary whose absence means the app isn't really
        # installed, even though its .desktop file is still on disk.
        try_exec = entry.getTryExec()
        if try_exec and not self._exists(try_exec):
            return None

        name = entry.getName() or app_id.removesuffix(".desktop")
        categories = tuple(c for c in entry.getCategories() if c)
        try:
            keywords = tuple(k for k in entry.getKeywords() if k)
        except Exception:
            keywords = ()

        return App(
            id=app_id,
            name=name,
            icon_path=self.resolve_icon(entry.getIcon()),
            categories=categories,
            tab=self._tab_for(categories),
            exec_line=exec_line,
            terminal=bool(entry.getTerminal()),
            workdir=entry.getPath() or None,
            wm_classes=_wm_class_candidates(
                entry, app_id, exec_line, terminal=bool(entry.getTerminal())
            ),
            startup_wm_class=entry.getStartupWMClass() or None,
            generic_name=entry.getGenericName() or "",
            keywords=keywords,
            source=str(path),
        )

    @staticmethod
    def _exists(binary: str) -> bool:
        if os.path.isabs(binary):
            return os.access(binary, os.X_OK)
        return which(binary) is not None

    @staticmethod
    def _tab_for(categories: tuple[str, ...]) -> str:
        present = {c for c in categories}
        for category, tab in TAB_PRIORITY:
            if category in present:
                return tab
        return DEFAULT_TAB

    def resolve_icon(self, icon: str | None) -> str | None:
        """Resolve an Icon= value to a filesystem path the mod can load.

        Raster formats are preferred: the mod loads icons with NativeImage,
        which cannot rasterise vectors. When only an SVG exists it is rendered
        to a cached PNG here rather than handed over as-is — on this machine 39
        of 81 apps are SVG-only, including Files, Settings and every GNOME app,
        and a catalog of blank tiles is not a catalog.

        Rasterising is the daemon's job by the same rule as everything else:
        the mod is handed a path it can open, and never has to know that some
        icons arrived in a format it cannot read.
        """
        if not icon:
            return None
        with self._icons:
            return self._resolve_icon(icon)

    def _forget_icons(self) -> None:
        """Make the next lookups read the icon directories afresh.

        pyxdg caches directory listings and decides when to re-read them by a
        theme's *top* directory's mtime — one value shared across every base
        directory — which an icon installed into an existing `48x48/apps`
        does not move. Measured: the same new icon was found by a fresh
        process and missed by the running daemon. Clearing the caches before a
        rescan costs nothing measurable (0.742s against 0.720s) and makes the
        answer whatever is on disk now.
        """
        with self._icons:
            xdg.IconTheme.theme_cache.clear()
            xdg.IconTheme.dir_cache.clear()
            xdg.IconTheme.icon_cache.clear()

    def _resolve_icon(self, icon: str) -> str | None:
        if os.path.isabs(icon):
            if not os.path.exists(icon):
                return None
            return self._rasterise(icon) if icon.endswith(".svg") else icon

        try:
            found = getIconPath(icon, self.icon_size, extensions=["png", "xpm"])
        except Exception:
            found = None
        if found and os.path.exists(found):
            return found

        try:
            found = getIconPath(icon, self.icon_size, extensions=["svg"])
        except Exception:
            found = None
        if found and os.path.exists(found):
            return self._rasterise(found)
        return None

    def _rasterise(self, svg: str) -> str | None:
        """Render an SVG to a cached PNG, returning its path.

        Cached under the source path, its mtime and the target size, so a
        themed icon that changes on disk is re-rendered and an unchanged one
        costs a stat. Returns the SVG unchanged if there is no rasteriser: the
        mod already draws a placeholder for an icon it cannot load, which is a
        better outcome than the daemon refusing to mention the app at all.
        """
        if _RSVG is None:
            return svg
        try:
            mtime = os.path.getmtime(svg)
        except OSError:
            return None

        key = hashlib.sha256(
            f"{svg}\n{mtime}\n{self.icon_size}".encode()
        ).hexdigest()[:32]
        out = self._raster_cache / f"{key}.png"
        if out.exists():
            return str(out)

        try:
            self._raster_cache.mkdir(parents=True, exist_ok=True)
            # To a temporary name then renamed: two daemons starting at once
            # must not hand the mod a half-written PNG.
            tmp = out.with_suffix(".png.part")
            subprocess.run(
                [_RSVG, "-w", str(self.icon_size), "-h", str(self.icon_size),
                 "-o", str(tmp), svg],
                check=True, capture_output=True, timeout=10,
            )
            tmp.replace(out)
            return str(out)
        except Exception as e:
            log.debug("could not rasterise %s: %s", svg, e)
            return svg

    @staticmethod
    def _class_rank(app: App, cls: str) -> int:
        """How much to trust `cls` as an identifier for `app`. Lower is better.

        Several apps can claim the same candidate — foot.desktop and
        foot-server.desktop both yield "foot", the latter only because its Exec
        happens to start with the foot binary. Without ranking, whichever was
        scanned first won, and a window with app_id "foot" was attributed to
        the server entry.
        """
        # Unique by construction: we chose it, and it is namespaced.
        if app.terminal and cls == app.terminal_app_id.lower():
            return 0
        if app.startup_wm_class and cls == app.startup_wm_class.lower():
            return 0
        if cls == app.id.removesuffix(".desktop").lower():
            return 1
        return 2

    def _reindex(self) -> None:
        """Build the app_id -> desktop id lookup used by match_window()."""
        best: dict[str, tuple[int, str]] = {}
        for app in self.apps.values():
            for cls in app.wm_classes:
                rank = (self._class_rank(app, cls), app.id)
                if cls not in best or rank < best[cls]:
                    best[cls] = rank
        self._by_wm_class = {cls: app_id for cls, (_, app_id) in best.items()}

    # -- queries -----------------------------------------------------------

    def get(self, app_id: str) -> App | None:
        return self.apps.get(app_id)

    def match_window(self, window_app_id: str) -> App | None:
        """Find the app owning a window with this app_id, or None."""
        if not window_app_id:
            return None
        found = self._by_wm_class.get(window_app_id.lower())
        return self.apps.get(found) if found else None

    def query(self, text: str = "", tab: str | None = None, limit: int = 200) -> list[App]:
        """Search apps by name, ranked best-first.

        Empty text lists everything (optionally filtered to a tab), sorted by
        name — that is the browse case, not the search case.
        """
        pool = [a for a in self.apps.values() if tab is None or a.tab == tab]

        needle = text.strip().lower()
        if not needle:
            return sorted(pool, key=lambda a: a.name.lower())[:limit]

        # Sorted on the key alone, and the key ends in the desktop id. Sorting
        # whole tuples means Python falls through to comparing the App when the
        # score *and* the name tie, and App is not orderable — a TypeError that
        # takes the query down. Two entries for the same program is all it
        # takes: this machine ships evince.desktop and org.gnome.Evince.desktop,
        # both named "Document Viewer", and any search matching both crashed.
        # The id is unique by construction, so the order is total and stable.
        scored: list[tuple[int, str, str, App]] = []
        for app in pool:
            score = _score(needle, app)
            if score > 0:
                scored.append((-score, app.name.lower(), app.id, app))
        scored.sort(key=lambda row: row[:3])
        return [row[3] for row in scored[:limit]]


def _score(needle: str, app: App) -> int:
    """Rank one app against a search string. 0 means no match.

    Ordered so that typing "fir" puts Firefox above anything merely containing
    those letters: whole-name prefix beats word prefix beats substring beats
    subsequence.
    """
    name = app.name.lower()

    if name == needle:
        return 1000
    if name.startswith(needle):
        return 900 - len(name)
    if any(word.startswith(needle) for word in name.split()):
        return 800 - len(name)
    if needle in name:
        return 700 - len(name)
    if needle in app.id.lower():
        return 600 - len(name)
    # GenericName and Keywords are how "term" finds a terminal emulator and
    # "browser" finds Brave — neither word appears in those apps' names.
    if any(k.lower().startswith(needle) for k in app.keywords):
        return 580 - len(name)
    if app.generic_name and needle in app.generic_name.lower():
        return 560 - len(name)
    if any(needle in k.lower() for k in app.keywords):
        return 540 - len(name)
    if _subsequence(needle, name):
        return 500 - len(name)
    return 0


def _subsequence(needle: str, haystack: str) -> bool:
    """True if every character of needle appears in haystack, in order."""
    it = iter(haystack)
    return all(c in it for c in needle)
