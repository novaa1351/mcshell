#!/usr/bin/env python3
"""Build the Prism instance as a Modrinth modpack: dist/mcshell-<version>.mrpack.

What it carries is what the instance is made of, and nothing about how Prism
is configured: Minecraft 1.21.1, the Fabric loader, the pinned mods out of
mods.tsv by URL and hash, and our own jar inside the pack. Java, heap, JVM
flags, the console and options.txt are Prism's settings or the game's, which a
modpack cannot express — setup.sh still settles those, after an import exactly
as it does today.

The mods are not copied into the pack. Each is listed with its Modrinth URL,
size, sha1 and sha512, and Prism downloads and checks it on import. sha1 is
computed here from a file whose sha512 has first been checked against
mods.tsv, so it is as trustworthy as the pin it came from.

Reproducible: entries are written in order with a fixed timestamp, so the
same inputs give the same bytes.

    session/prism/mrpack.py            # needs mod/build/libs/mcshell-<v>.jar
"""

import hashlib
import json
import re
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MODS_TSV = REPO / "session" / "prism" / "mods.tsv"
GRADLE = REPO / "mod" / "gradle.properties"

MINECRAFT = "1.21.1"
#: What the instance has run since M7 — read out of its mmc-pack.json — rather
#: than gradle.properties' loader_version, which is what the mod compiles
#: against. A pack ships the runtime that was measured.
FABRIC_LOADER = "0.19.5"

#: The zip's one timestamp: the day the pack format was adopted.
EPOCH = (2026, 10, 17, 0, 0, 0)


def gradle(key: str) -> str:
    for line in GRADLE.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{GRADLE}: no {key}")


def pins() -> list[tuple[str, str, str]]:
    rows = []
    for line in MODS_TSV.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, sha512, url = line.split("\t")
        rows.append((name, sha512, url))
    return rows


def fetch(name: str, sha512: str, url: str, cache: Path) -> bytes:
    """The pinned file's bytes, from the instance or the cache or the URL."""
    for candidate in (instance_mods() / name, cache / name):
        if candidate.is_file():
            body = candidate.read_bytes()
            if hashlib.sha512(body).hexdigest() == sha512:
                return body
    print(f"fetching {name}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=60) as reply:
        body = reply.read()
    if hashlib.sha512(body).hexdigest() != sha512:
        raise SystemExit(f"{name}: sha512 does not match mods.tsv")
    cache.mkdir(parents=True, exist_ok=True)
    (cache / name).write_bytes(body)
    return body


def instance_mods() -> Path:
    import os
    instance = os.environ.get("MCSHELL_INSTANCE") or str(
        Path.home() / ".local/share/PrismLauncher/instances"
        / (os.environ.get("MCSHELL_INSTANCE_NAME") or "MCShell"))
    return Path(instance) / "minecraft" / "mods"


def our_jar(version: str) -> Path:
    jar = REPO / "mod" / "build" / "libs" / f"mcshell-{version}.jar"
    if not jar.is_file():
        raise SystemExit(f"{jar} is not built: run session/prism/install-mod.sh "
                         "or mod/gradlew -p mod build")
    return jar


def build() -> Path:
    version = gradle("mod_version")
    cache = Path(tempfile.gettempdir()) / "mcshell-mrpack-cache"
    files = []
    for name, sha512, url in pins():
        if not re.match(r"https://cdn\.modrinth\.com/", url):
            raise SystemExit(f"{name}: {url} is not a Modrinth CDN URL")
        body = fetch(name, sha512, url, cache)
        files.append({
            "path": f"mods/{name}",
            "hashes": {"sha1": hashlib.sha1(body).hexdigest(), "sha512": sha512},
            "env": {"client": "required", "server": "unsupported"},
            "downloads": [url],
            "fileSize": len(body),
        })

    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": version,
        "name": "MCShell",
        "summary": "Minecraft as the desktop shell. Not an official Minecraft "
                   "product; not approved by or associated with Mojang or Microsoft.",
        "files": files,
        "dependencies": {"minecraft": MINECRAFT, "fabric-loader": FABRIC_LOADER},
    }

    jar = our_jar(version)
    out = REPO / "dist" / f"mcshell-{version}.mrpack"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        entries = [
            ("modrinth.index.json", (json.dumps(index, indent=2) + "\n").encode()),
            (f"overrides/mods/{jar.name}", jar.read_bytes()),
        ]
        for path, body in entries:
            info = zipfile.ZipInfo(path, EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, body)
    return out


if __name__ == "__main__":
    out = build()
    # The path alone on stdout, so a script can take it; the rest is for people.
    print(out)
    print(f"{out.stat().st_size} bytes, sha256 "
          f"{hashlib.sha256(out.read_bytes()).hexdigest()}", file=sys.stderr)
