#!/usr/bin/env python3
"""Create the Prism instance from the .mrpack, with no window and no clicks.

Prism can import a .mrpack itself, but measured (2026-10-17, Prism 11.0.3) its
`--import` opens the New Instance dialog and waits for OK, and names the
instance after the file rather than `MCShell`. The Microsoft sign-in is the one
step a person has to take; this is not allowed to be a second.

So this does what Prism's importer does: every file in the pack's index is
downloaded and checked against its sha512 and sha1, `overrides/` is copied
in, and the instance is written in Prism's own format — `instance.cfg` and
`mmc-pack.json`, the files setup.sh already edits. The component list is the
one Prism's importer wrote for this pack, byte for byte, which is also the one
the hand-made instance has run on since M7.

An instance that already exists is never touched: it may be one somebody has
been using for months, and setup.sh is what keeps an existing one current.
It is built beside the instances directory and renamed into place, so a
download that fails halfway leaves nothing behind.

    session/prism/install-pack.py dist/mcshell-0.1.0.mrpack
"""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

#: Where a modpack may send us, per the Modrinth format's own rule.
ALLOWED_HOSTS = ("https://cdn.modrinth.com/", "https://github.com/",
                 "https://raw.githubusercontent.com/", "https://gitlab.com/")

#: LWJGL is what Minecraft 1.21.1 asks for; Minecraft is pinned for good.
LWJGL = "3.3.3"


def instance_dir() -> Path:
    """The same instance common.sh and worlds.py resolve, by the same rules."""
    if os.environ.get("MCSHELL_INSTANCE"):
        return Path(os.environ["MCSHELL_INSTANCE"])
    return (Path.home() / ".local/share/PrismLauncher/instances"
            / (os.environ.get("MCSHELL_INSTANCE_NAME") or "MCShell"))


def components(minecraft: str, loader: str) -> dict:
    """mmc-pack.json as Prism's importer writes it for these versions."""
    return {
        "components": [
            {"cachedName": "LWJGL 3", "cachedVersion": LWJGL, "cachedVolatile": True,
             "dependencyOnly": True, "uid": "org.lwjgl3", "version": LWJGL},
            {"cachedName": "Minecraft",
             "cachedRequires": [{"suggests": LWJGL, "uid": "org.lwjgl3"}],
             "cachedVersion": minecraft, "important": True,
             "uid": "net.minecraft", "version": minecraft},
            {"cachedName": "Intermediary Mappings",
             "cachedRequires": [{"equals": minecraft, "uid": "net.minecraft"}],
             "cachedVersion": minecraft, "cachedVolatile": True, "dependencyOnly": True,
             "uid": "net.fabricmc.intermediary", "version": minecraft},
            {"cachedName": "Fabric Loader",
             "cachedRequires": [{"uid": "net.fabricmc.intermediary"}],
             "cachedVersion": loader, "uid": "net.fabricmc.fabric-loader", "version": loader},
        ],
        "formatVersion": 1,
    }


def safe(path: str) -> PurePosixPath:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts:
        raise SystemExit(f"refusing a path outside the instance: {path}")
    return p


def download(entry: dict) -> bytes:
    for url in entry["downloads"]:
        if not url.startswith(ALLOWED_HOSTS):
            raise SystemExit(f"{entry['path']}: {url} is not a host a modpack may use")
        print(f"  fetching {entry['path']}")
        with urllib.request.urlopen(url, timeout=60) as reply:
            body = reply.read()
        if (len(body) == entry["fileSize"]
                and hashlib.sha512(body).hexdigest() == entry["hashes"]["sha512"]
                and hashlib.sha1(body).hexdigest() == entry["hashes"]["sha1"]):
            return body
        print(f"  {url}: does not match the pack's hashes", file=sys.stderr)
    raise SystemExit(f"{entry['path']}: no download matched its hashes")


def install(pack: Path, target: Path) -> None:
    if (target / "instance.cfg").exists():
        print(f"instance: {target} already exists, left as it is")
        return

    with zipfile.ZipFile(pack) as z:
        index = json.loads(z.read("modrinth.index.json"))
        if index.get("game") != "minecraft" or index.get("formatVersion") != 1:
            raise SystemExit(f"{pack}: not a Minecraft modpack this understands")
        deps = index["dependencies"]
        if set(deps) != {"minecraft", "fabric-loader"}:
            raise SystemExit(f"{pack}: expected Minecraft and Fabric only, got {sorted(deps)}")

        target.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=".mcshell-", dir=target.parent))
        try:
            mc = work / "minecraft"
            for entry in index["files"]:
                if entry.get("env", {}).get("client") == "unsupported":
                    continue
                dest = mc / safe(entry["path"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(download(entry))
            for name in z.namelist():
                for prefix in ("overrides/", "client-overrides/"):
                    if name.startswith(prefix) and not name.endswith("/"):
                        dest = mc / safe(name[len(prefix):])
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(z.read(name))
            (work / "mmc-pack.json").write_text(
                json.dumps(components(deps["minecraft"], deps["fabric-loader"]),
                           indent=4, sort_keys=True) + "\n")
            (work / "instance.cfg").write_text(
                "[General]\nConfigVersion=1.3\nInstanceType=OneSix\n"
                f"name={target.name}\n")
            work.rename(target)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
    print(f"instance: {target} created from {pack.name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.strip().splitlines()[-1])
    install(Path(sys.argv[1]), instance_dir())
