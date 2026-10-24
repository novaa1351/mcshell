"""Directories, for the Advancements screen.

Minecraft's advancement window is already a tree: nodes on a grid, branches
drawn between a parent and its children, panned around behind a stone
background. A filesystem is the same shape, so the screen is kept and the
contents replaced.

One listing at a time, on demand. The tree starts at the home directory with
nothing under it and grows a branch only when something is clicked, which is
the one real difference from vanilla's screen — an advancement tree is known in
advance and a filesystem is not. Nothing is walked recursively and nothing is
cached: a directory read is a syscall, and the answer stops being true the
moment somebody saves a file.

Files are listed beside the directories, because a directory with things in it
that draws as empty is worse than no picture at all. They are leaves and
nothing else — nothing opens one, and nothing here could decide what opening
one would mean. What each one *is* is decided here rather than in the mod: an
extension is data, and the table below is a line per format.

Hidden entries are left out, and counted. A home directory has dozens of them
and they would outnumber the ones anybody came looking for several times over
on the very first click; saying how many were skipped keeps that honest rather
than silent.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from . import protocol as p

log = logging.getLogger(__name__)

#: How many children a single expansion shows. The screen pans, but a
#: directory with two hundred entries would make a column five thousand pixels
#: tall out of one click, and there would be no way back but to collapse it.
PAGE = 20

#: What a file *is*, for the icon the mod draws. Extensions, lowercased,
#: without the dot. The mod has one 16x16 texture per kind and falls back to
#: `file`, so adding a format here is a line, and adding a *kind* is a line
#: here and a glyph in `mod/tools/icons.py`.
#:
#: Deliberately not mimetypes.guess_type: it answers `text/plain` for a shell
#: script and a changelog alike, has no opinion at all about a `.rs` file, and
#: what it does know is keyed to a system database that differs between
#: machines. This table is small, and it is the same everywhere.
KINDS: dict[str, tuple[str, ...]] = {
    "audio": ("mp3", "flac", "wav", "ogg", "opus", "m4a", "aac", "wma", "mid", "midi", "aiff"),
    "video": ("mp4", "mkv", "webm", "avi", "mov", "wmv", "flv", "m4v", "mpg", "mpeg", "ts"),
    "image": ("png", "jpg", "jpeg", "gif", "bmp", "svg", "webp", "ico", "tif", "tiff",
              "heic", "avif", "xcf", "psd", "raw", "cr2", "nef", "dng"),
    "pdf": ("pdf", "ps", "eps", "djvu"),
    "doc": ("doc", "docx", "odt", "rtf", "epub", "mobi", "azw3", "pages", "tex"),
    "sheet": ("xls", "xlsx", "ods", "csv", "tsv", "numbers"),
    "slides": ("ppt", "pptx", "odp", "key"),
    "text": ("txt", "md", "markdown", "rst", "log", "nfo", "org", "adoc"),
    "code": ("py", "java", "c", "h", "cc", "cpp", "hpp", "cs", "rs", "go", "js", "mjs",
             "cjs", "ts", "jsx", "tsx", "sh", "bash", "zsh", "fish", "rb", "pl", "php",
             "lua", "vim", "el", "kt", "kts", "swift", "scala", "clj", "hs", "ml", "r",
             "sql", "asm", "s", "gradle", "cmake", "mk", "patch", "diff", "ipynb"),
    "config": ("json", "yaml", "yml", "toml", "ini", "conf", "cfg", "xml", "properties",
               "desktop", "service", "socket", "target", "rules", "env", "lock"),
    "archive": ("zip", "tar", "gz", "tgz", "xz", "bz2", "zst", "7z", "rar", "jar", "iso",
                "img", "deb", "rpm", "pkg", "apk", "cab", "dmg"),
    "font": ("ttf", "otf", "woff", "woff2", "ttc", "pfb", "bdf", "pcf"),
    "binary": ("exe", "appimage", "bin", "so", "o", "a", "dll", "dylib", "elf", "ko",
               "class", "pyc", "wasm", "msi"),
}

#: The files that carry their type in their name rather than after a dot.
NAMES: dict[str, str] = {
    "makefile": "code",
    "dockerfile": "code",
    "cmakelists.txt": "code",
    "readme": "text",
    "license": "text",
    "copying": "text",
    "changelog": "text",
    "pkgbuild": "code",
}

#: Built once, so the lookup is a dict hit rather than a walk of the table.
_BY_EXT: dict[str, str] = {
    ext: kind for kind, exts in KINDS.items() for ext in exts
}


def kind_of(name: str) -> str:
    """What kind of file this is, by its name alone.

    Nothing is opened and nothing is sniffed. The tree is a picture of the
    filesystem, and a picture that cost a read of every file in a directory
    would not be worth having.
    """
    lowered = name.lower()
    if lowered in NAMES:
        return NAMES[lowered]
    _, dot, ext = lowered.rpartition(".")
    if not dot or not ext:
        return "file"
    # `foo.tar.gz` is an archive either way; `.bashrc` has no extension at all,
    # it has a name that starts with a dot, and it never reaches here.
    return _BY_EXT.get(ext, "file")


def home() -> Path:
    return Path(os.path.expanduser("~"))


class Files:
    """One directory at a time, on request."""

    def list(self, path: str, offset: int = 0, limit: int = PAGE) -> p.Dir:
        """The subdirectories of one directory, a page at a time."""
        target = home() if not path else Path(path)
        try:
            # Resolved so that a symlink reports where it actually went, and
            # so two routes to one directory cannot become two different nodes
            # that disagree with each other.
            target = target.resolve()
        except OSError as e:
            return p.Dir(path=str(target), name=target.name, error=str(e))

        if not target.is_dir():
            return p.Dir(path=str(target), name=_name(target),
                         error="not a directory")

        dirs: list[tuple[str, str]] = []
        files: list[tuple[str, str]] = []
        hidden = 0
        try:
            with os.scandir(target) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        hidden += 1
                        continue
                    try:
                        is_dir = entry.is_dir()
                    except OSError:
                        # A dangling symlink, or a mount that went away
                        # between the readdir and the stat. Shown as a file:
                        # it is certainly not a branch.
                        is_dir = False
                    (dirs if is_dir else files).append((entry.name, entry.path))
        except PermissionError:
            return p.Dir(path=str(target), name=_name(target),
                         error="permission denied")
        except OSError as e:
            return p.Dir(path=str(target), name=_name(target), error=str(e))

        # Directories first, then files, each alphabetically. The convention
        # every file manager uses, and here it also keeps the branches of the
        # tree together at the top of a column instead of scattered among its
        # leaves.
        def order(entry):
            return (entry[0].lower(), entry[0])
        dirs.sort(key=order)
        files.sort(key=order)
        visible = [(name, path, "dir") for name, path in dirs]
        visible += [(name, path, kind_of(name)) for name, path in files]

        total = len(visible)
        # Not clamped back into range: an offset past the end returns an
        # empty page rather than sliding to the last one, so the screen's
        # "more" node cannot walk backwards when a directory shrinks.
        offset = max(0, offset)
        page = visible[offset:offset + max(1, limit)]

        return p.Dir(
            path=str(target),
            name=_name(target),
            entries=[p.DirEntry(name=name, path=path, kind=kind)
                     for name, path, kind in page],
            total=total,
            hidden=hidden,
            offset=offset,
        )


def _name(path: Path) -> str:
    """What to call a directory. `/` has no name of its own."""
    return path.name or str(path)
