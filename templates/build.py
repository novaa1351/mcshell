#!/usr/bin/env python3
"""Make the shipped template worlds out of the pristine snapshots.

The snapshots in ~/.local/share/mcshell/templates were taken 2026-09-13,
before anyone played the worlds, and they are final. But each of them began as
a copy of a world that *had* been played, so each still carries its player:
two UUIDs' worth of playerdata, advancements and stats, and a `Player`
compound in level.dat with an inventory and a position in it. A package must
install no player at all, so what ships is derived from the snapshots rather
than copied:

- `playerdata/`, `advancements/` and `stats/` are left out, whole.
- `level.dat_old` is left out — it is the same level.dat one save earlier.
- `level.dat` loses `Data.Player`, and `LevelName` becomes the folder's name,
  so vanilla's own screens tell the worlds apart. They all said `MCShell`.

Everything else is byte for byte the snapshot's, and the archives are
reproducible: sorted entries, one fixed mtime, no owner, so running this again
gives the same SHA256SUMS. The sources are checked against the sums recorded
here first, so a shipped template can always be traced to its snapshot.

    templates/build.py [SNAPSHOT_DIR]      # writes templates/*.tar.zst
"""

import gzip
import hashlib
import io
import struct
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: The snapshots, as their own SHA256SUMS recorded them on 2026-09-13.
SOURCES = {
    "Island": "8bb8daf1d15e1c7708091725e7e28dbf055f150e6f147abac46324a03686e15d",
    "Skyblock": "bf0c6ccb68318c4d9e6fe9eae49d46cfd0040513122ceb62f753e133a384f38d",
    "Tutorial World": "69aab11903e830d7cd9483588a7da3f98ebf17b8ded9346e2a9bcb1e54e9b589",
}

#: Directories that belong to a player, never to a world.
PERSONAL_DIRS = ("playerdata", "advancements", "stats")
#: Files that are left behind for the same reason.
PERSONAL_FILES = ("level.dat_old", "session.lock")

#: The snapshots' own date, so the archives do not change with the clock.
MTIME = 1789344252  # 2026-09-13 20:04:12 local: the snapshot files' own mtime


# --- NBT, just enough to edit level.dat and write it back unchanged ---------
# Values keep their tag, so what is read is what is written: (tag, value).

def _read(buf: bytes, pos: int, tag: int):
    if tag in (1, 2, 3, 4, 5, 6):
        fmt = ">" + "bhiqfd"[tag - 1]
        return struct.unpack_from(fmt, buf, pos)[0], pos + struct.calcsize(fmt)
    if tag in (7, 11, 12):
        n = struct.unpack_from(">i", buf, pos)[0]
        width = {7: 1, 11: 4, 12: 8}[tag]
        start = pos + 4
        return buf[start:start + n * width], start + n * width
    if tag == 8:
        n = struct.unpack_from(">H", buf, pos)[0]
        return buf[pos + 2:pos + 2 + n].decode("utf-8"), pos + 2 + n
    if tag == 9:
        sub = buf[pos]
        n = struct.unpack_from(">i", buf, pos + 1)[0]
        pos += 5
        items = []
        for _ in range(n):
            value, pos = _read(buf, pos, sub)
            items.append(value)
        return (sub, items), pos
    if tag == 10:
        out = {}
        while True:
            t = buf[pos]
            pos += 1
            if t == 0:
                return out, pos
            n = struct.unpack_from(">H", buf, pos)[0]
            name = buf[pos + 2:pos + 2 + n].decode("utf-8")
            value, pos = _read(buf, pos + 2 + n, t)
            out[name] = (t, value)
    raise ValueError(f"unknown NBT tag {tag} at {pos}")


def _write(out: io.BytesIO, tag: int, value) -> None:
    if tag in (1, 2, 3, 4, 5, 6):
        out.write(struct.pack(">" + "bhiqfd"[tag - 1], value))
    elif tag in (7, 11, 12):
        width = {7: 1, 11: 4, 12: 8}[tag]
        out.write(struct.pack(">i", len(value) // width))
        out.write(value)
    elif tag == 8:
        raw = value.encode("utf-8")
        out.write(struct.pack(">H", len(raw)))
        out.write(raw)
    elif tag == 9:
        sub, items = value
        out.write(struct.pack(">bi", sub, len(items)))
        for item in items:
            _write(out, sub, item)
    elif tag == 10:
        for name, (t, v) in value.items():
            raw = name.encode("utf-8")
            out.write(struct.pack(">bH", t, len(raw)))
            out.write(raw)
            _write(out, t, v)
        out.write(b"\0")
    else:
        raise ValueError(f"unknown NBT tag {tag}")


def nbt_load(raw: bytes) -> tuple[str, dict]:
    if raw[0] != 10:
        raise ValueError("level.dat does not start with a compound")
    n = struct.unpack_from(">H", raw, 1)[0]
    name = raw[3:3 + n].decode("utf-8")
    root, end = _read(raw, 3 + n, 10)
    if end != len(raw):
        raise ValueError(f"{len(raw) - end} trailing bytes in level.dat")
    return name, root


def nbt_dump(name: str, root: dict) -> bytes:
    out = io.BytesIO()
    raw = name.encode("utf-8")
    out.write(struct.pack(">bH", 10, len(raw)))
    out.write(raw)
    _write(out, 10, root)
    return out.getvalue()


# --- the templates ----------------------------------------------------------

def strip_level(raw_gz: bytes, level_name: str) -> bytes:
    raw = gzip.decompress(raw_gz)
    name, root = nbt_load(raw)
    if nbt_dump(name, root) != raw:
        raise SystemExit("level.dat does not round-trip; refusing to edit it")
    _, data = root["Data"]
    data.pop("Player", None)
    data["LevelName"] = (8, level_name)
    return gzip.compress(nbt_dump(name, root), mtime=0)


def personal(rel: str) -> bool:
    parts = rel.split("/")
    return (len(parts) >= 2 and parts[1] in PERSONAL_DIRS) or \
        (len(parts) == 2 and parts[1] in PERSONAL_FILES)


def build(world: str, source: Path, dest: Path) -> None:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != SOURCES[world]:
        raise SystemExit(f"{source}: sha256 {digest} is not the snapshot's")

    entries = []
    with tarfile.open(source, "r:zst") as src:
        for member in src.getmembers():
            rel = member.name.removeprefix("./")
            if personal(rel):
                continue
            body = src.extractfile(member).read() if member.isfile() else None
            if rel == f"{world}/level.dat":
                body = strip_level(body, world)
            entries.append((rel, member, body))

    entries.sort(key=lambda e: e[0])
    with tarfile.open(dest, "w:zst", level=19) as out:
        for rel, member, body in entries:
            info = tarfile.TarInfo(rel)
            info.type = member.type
            info.mode = 0o755 if member.isdir() else 0o644
            info.mtime = MTIME
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            if body is not None:
                info.size = len(body)
                out.addfile(info, io.BytesIO(body))
            else:
                out.addfile(info)


def main() -> None:
    snapshots = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path.home() / ".local/share/mcshell/templates"
    sums = []
    for world in SOURCES:
        dest = HERE / f"{world}.tar.zst"
        build(world, snapshots / f"{world}.tar.zst", dest)
        sums.append(f"{hashlib.sha256(dest.read_bytes()).hexdigest()}  {dest.name}")
        print(f"{dest.name}: {dest.stat().st_size} bytes")
    (HERE / "SHA256SUMS").write_text("\n".join(sums) + "\n")


if __name__ == "__main__":
    main()
