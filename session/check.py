#!/usr/bin/env python3
"""mcshell check — is this machine set up to run MCShell, and what is missing.

The question diagnose.sh does not ask. That one is about a session that is
running and misbehaving; this is about the machine, and it works from any
terminal, in any session or none. Its output is the first thing a bug report
should contain, so it starts with what a reader needs to know and ends with a
verdict.

Everything is checked by command, library or file — never by package name.
Package names are the one thing that differs between distributions, and they
belong in docs and packaging. Each missing thing says what it costs, in three
tiers:

    required   the session cannot start, or a safety rail is gone
    feature    the shell runs, and one named thing does not
    optional   cosmetic

Where another file already decides a name — the layer-shell library in
overlay.py, the polkit agent in sway.conf, the prompters mcshell-askpass tries —
it is read from that file, so the two cannot drift apart.

Exit status 1 if anything required is missing, else 0.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("MCSHELL_ROOT") or Path(__file__).resolve().parents[1])
SESSION = ROOT / "session"
#: A git checkout builds the mod and runs the daemon from its venv; the Arch
#: package installs neither (the jar comes with the release), so the advice
#: for fixing something differs between the two.
CHECKOUT = (ROOT / "mod" / "gradlew").exists()

REQUIRED, FEATURE, OPTIONAL = "required", "feature", "optional"
#: Required too, and counted as such; printed in their own section first,
#: because "is it installed" and "is it set up" are different questions.
SETUP = "setup"
results: list[tuple[str, bool, str, str]] = []  # tier, ok, what, detail


def check(tier: str, ok: bool, what: str, detail: str) -> bool:
    results.append((tier, ok, what, detail))
    return ok


def has(cmd: str) -> bool:
    return shutil.which(cmd) is not None or (cmd.startswith("/") and os.access(cmd, os.X_OK))


def run(*argv: str, timeout: float = 10) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def first_line(text: str) -> str:
    return text.splitlines()[0] if text else "?"


# --- where things are -----------------------------------------------------

def instance_dir() -> Path:
    """The same instance common.sh, worlds.py and install-pack.py resolve."""
    if os.environ.get("MCSHELL_INSTANCE"):
        return Path(os.environ["MCSHELL_INSTANCE"])
    return (Path.home() / ".local/share/PrismLauncher/instances"
            / (os.environ.get("MCSHELL_INSTANCE_NAME") or "MCShell"))


def daemon_path() -> str:
    """The mcshelld the units run: this checkout's venv, else the one on PATH."""
    venv = ROOT / "daemon" / ".venv" / "bin" / "mcshelld"
    return str(venv) if venv.exists() or CHECKOUT else (shutil.which("mcshelld") or "mcshelld")


def daemon_python() -> str:
    """The interpreter the daemon runs under: the checkout's venv, else this one."""
    venv = ROOT / "daemon" / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def terminal() -> tuple[str, str]:
    """What the session will use as $TERMINAL, by start-session.sh's rule."""
    if os.environ.get("TERMINAL"):
        return os.environ["TERMINAL"], "environment"
    for line in run("systemctl", "--user", "show-environment").splitlines():
        if line.startswith("TERMINAL="):
            return line.split("=", 1)[1], "environment.d"
    return "foot", "default"


def from_file(path: Path, pattern: str) -> str:
    try:
        m = re.search(pattern, path.read_text(), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


def askpass_helpers() -> list[str]:
    """The prompters mcshell-askpass tries, in its order."""
    text = (ROOT / "daemon" / "tools" / "mcshell-askpass").read_text()
    names = []
    loop = re.search(r"for helper in(.*?)\bdo\b", text, re.S)
    if loop:
        names += [w for w in loop.group(1).replace("\\", " ").split()]
    names += re.findall(r"command -v ([\w./-]+)", text)
    return list(dict.fromkeys(names))


# --- the report -----------------------------------------------------------

def header() -> None:
    version = from_file(ROOT / "mod" / "gradle.properties", r"^mod_version=(.+)$") or "?"
    commit = ""
    if (ROOT / ".git").exists():
        rev = run("git", "-C", str(ROOT), "rev-parse", "--short", "HEAD")
        branch = run("git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD")
        dirty = " +local changes" if run("git", "-C", str(ROOT), "status", "--porcelain") else ""
        commit = f"  ({branch} {rev}{dirty})"
    osname = from_file(Path("/etc/os-release"), r'^PRETTY_NAME="?([^"\n]+)') or platform.system()
    gpus = [re.sub(r'^\S+ "[^"]*" "([^"]*)" "([^"]*)".*', r"\1 \2", line)
            for line in run("lspci", "-mm").splitlines()
            if re.search(r'"(VGA|3D|Display)', line)]
    term, source = terminal()
    in_session = os.environ.get("XDG_SESSION_DESKTOP") == "mcshell"
    rows = [
        ("MCShell", f"{version}{commit}"),
        ("checkout", str(ROOT)),
        ("system", f"{osname}, kernel {platform.release()}"),
        ("sway", first_line(run("sway", "--version")) if has("sway") else "not installed"),
        ("Prism", first_line(run("prismlauncher", "--version")) if has("prismlauncher") else "not installed"),
        ("python", platform.python_version()),
        ("GPU", "; ".join(gpus) or "unknown (no lspci)"),
        ("terminal", f"{term} (from {source})"),
        ("session", "inside MCShell" if in_session else
         f"not MCShell ({os.environ.get('XDG_SESSION_DESKTOP') or 'unknown'})"),
    ]
    print("MCShell check")
    for k, v in rows:
        print(f"  {k:9} {v}")


def dependencies() -> None:
    # Required.
    check(REQUIRED, has("sway") and has("swaymsg"), "sway",
          "the compositor; without it there is no session")
    check(REQUIRED, bool(run("systemctl", "--user", "show-environment")), "systemd user manager",
          "runs the daemon and the game; without it nothing starts")
    py = daemon_python()
    missing = [m for m in ("i3ipc", "xdg")
               if subprocess.run([py, "-c", f"import {m}"], capture_output=True).returncode]
    check(REQUIRED, not missing, "daemon's Python modules",
          f"{py} lacks {', '.join(missing)}; the daemon cannot start" if missing
          else f"i3ipc and pyxdg, under {py}")
    daemon = daemon_path()
    check(REQUIRED, os.access(daemon, os.X_OK), "the daemon",
          f"{daemon} — the shell itself" if os.access(daemon, os.X_OK) else
          "no mcshelld: cd daemon && uv venv && uv pip install -e ." if CHECKOUT
          else "no mcshelld: reinstall the mcshell package")
    check(REQUIRED, has("prismlauncher"), "Prism Launcher",
          "starts the game; without it there is no backdrop and no shell")
    java = from_file(instance_dir() / "instance.cfg", r"^JavaPath=(.+)$") or \
        from_file(SESSION / "prism" / "setup.sh", r"^cfg JavaPath (\S+)")
    jv = first_line(run(java, "-version")) if java and os.access(java, os.X_OK) else ""
    check(REQUIRED, bool(re.search(r'version "21[."]', jv)), "Java 21",
          f"{java}: {jv}" if jv else f"{java or 'no Java path'} is not there; 1.21.1 needs 21")
    locks = [c for c in ("hyprlock", "swaylock") if has(c)]
    check(REQUIRED, bool(locks), "a lock program",
          ", ".join(locks) if locks else "neither hyprlock nor swaylock; the screen cannot lock")
    term = terminal()[0].split()[0]
    check(REQUIRED, has(term) or has("foot"), "a terminal",
          f"{term}" if has(term) else
          ("foot (the fallback; $TERMINAL names " + term + ", which is not installed)")
          if has("foot") else f"neither {term} nor foot; the $mod+Shift+Return rail opens nothing")

    # Features.
    preload = from_file(SESSION / "overlay.py", r'^PRELOAD = "([^"]+)"')
    gi = subprocess.run(["/usr/bin/python3", "-c",
                         "import gi; gi.require_version('Gtk', '4.0'); "
                         "gi.require_version('Gtk4LayerShell', '1.0'); "
                         "from gi.repository import Gtk, Gtk4LayerShell"],
                        capture_output=True, text=True)
    check(FEATURE, bool(preload) and Path(preload).exists() and gi.returncode == 0,
          "the overlay (GTK 4, gtk4-layer-shell)",
          "boot screen, notifications, volume bar" if gi.returncode == 0 and Path(preload).exists()
          else "no boot screen, no notifications, no volume bar — "
               + (f"{preload} missing" if not Path(preload).exists() else
                  first_line(gi.stderr.strip().splitlines()[-1] if gi.stderr.strip() else "import failed")))
    dbus = subprocess.run([py, "-c", "import dbus_next"], capture_output=True).returncode == 0
    check(FEATURE, dbus, "dbus-next",
          "notifications, saving the world before power off, the sound picker" if dbus else
          "no notifications, no save before power off, no sound picker")
    check(FEATURE, has("hyprlock"), "hyprlock",
          "a password field you can see" if has("hyprlock") else
          "the lock screen still locks (swaylock), but shows no typing" if has("swaylock") else
          "a password field you can see — and with no swaylock either, see above")
    check(FEATURE, has("wpctl"), "wpctl", "volume keys and the volume bar")
    check(FEATURE, has("pactl"), "pactl", "the Sound page")
    players = [p for p in ("pw-play", "paplay") if has(p)]
    check(FEATURE, bool(players), "pw-play or paplay",
          "notification and volume-key sounds" + (f" ({players[0]})" if players else ": silent"))
    check(FEATURE, has("nmcli"), "nmcli", "the Network page, and deciding to boot offline")
    check(FEATURE, has("bluetoothctl"), "bluetoothctl", "the Bluetooth group on the Network page")
    check(FEATURE, has("gdbus"), "gdbus", "the Bluetooth group updating live")
    check(FEATURE, has("grim") and has("wl-copy"), "grim and wl-copy", "F2 screenshots")
    check(FEATURE, has("notify-send"), "notify-send", "the toast after a screenshot")
    check(FEATURE, has("brightnessctl"), "brightnessctl", "brightness keys and the Video page's brightness")
    check(FEATURE, has("playerctl"), "playerctl", "media play/pause/next keys")
    check(FEATURE, has("socat"), "socat",
          "the volume bar at 0% and 100%, and the boot screen's offline line")
    polkit = from_file(SESSION / "sway.conf", r"^exec (\S*polkit\S*)")
    check(FEATURE, bool(polkit) and has(polkit), "polkit agent",
          f"administrator prompts from applications ({polkit or 'none named in sway.conf'})")
    helpers = askpass_helpers()
    found = next((h for h in helpers if has(h)), "")
    check(FEATURE, bool(found), "a password prompter",
          f"sudo in the command bar, and Wi-Fi passwords ({found})" if found else
          f"sudo in the command bar cannot ask; tried {', '.join(helpers)}")
    portal = subprocess.run(["busctl", "--user", "introspect", "org.freedesktop.portal.Desktop",
                             "/org/freedesktop/portal/desktop", "org.freedesktop.portal.FileChooser"],
                            capture_output=True, timeout=10).returncode == 0 if has("busctl") else False
    check(FEATURE, portal, "a file chooser portal", "choosing the notification sound")
    check(FEATURE, has("curl"), "curl", "setup's downloads, and the offline check's fallback")
    check(FEATURE, has("zstd") and has("tar"), "zstd and tar", "setup copying in the template worlds")
    check(FEATURE, has("swaybg"), "swaybg",
          "the background sway draws before the boot screen is up (else black)")
    check(FEATURE, has("wlr-randr"), "wlr-randr",
          "the boot background's size before sway starts (falls back to the panel's own mode)")

    # Optional.
    check(OPTIONAL, has("rsvg-convert"), "rsvg-convert", "icons for apps that ship only an SVG")
    check(OPTIONAL, has("magick"), "ImageMagick", "the lock screen's third fallback")
    check(OPTIONAL, has("lspci"), "lspci", "the GPU line on the Statistics screen")


def setup_state() -> None:
    inst = instance_dir()
    made = check(SETUP, (inst / "instance.cfg").exists(), "Prism instance",
                 str(inst) if (inst / "instance.cfg").exists()
                 else f"none at {inst}: run mcshell setup")
    if made:
        try:
            comps = {c["uid"]: c.get("version") for c in
                     json.loads((inst / "mmc-pack.json").read_text())["components"]}
        except (OSError, ValueError, KeyError):
            comps = {}
        mc, loader = comps.get("net.minecraft"), comps.get("net.fabricmc.fabric-loader")
        check(SETUP, mc == "1.21.1" and bool(loader), "instance components",
              f"Minecraft {mc}, Fabric Loader {loader}")

        mods = inst / "minecraft" / "mods"
        bad = []
        for line in (SESSION / "prism" / "mods.tsv").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            name, sha512, _ = line.split("\t")
            f = mods / name
            if not f.is_file() or hashlib.sha512(f.read_bytes()).hexdigest() != sha512:
                bad.append(name)
        check(SETUP, not bad, "pinned mods",
              "all present, hashes match mods.tsv" if not bad else
              f"missing or changed: {', '.join(bad)} — run mcshell setup")
        jars = sorted(p.name for p in mods.glob("mcshell-*.jar"))
        check(SETUP, bool(jars), "the MCShell mod", ", ".join(jars) or "not installed in the instance")

        # By common.sh's rule: the choice if it is a world, else the default.
        choice = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mcshell" / "world"
        chosen = choice.read_text().strip() if choice.exists() else ""
        default = "Tutorial World"
        saves = inst / "minecraft" / "saves"
        def is_world(w):
            return bool(w) and "/" not in w and (saves / w / "level.dat").exists()
        if is_world(chosen) or (not chosen and is_world(default)):
            check(SETUP, True, "the world it boots into", chosen or default)
        elif is_world(default):
            check(SETUP, True, "the world it boots into",
                  f"{default} — the chosen '{chosen}' is not there, so the launcher falls back")
        else:
            what = (f"'{default}' is not" if chosen in ("", default)
                    else f"neither '{chosen}' nor '{default}' is")
            check(SETUP, False, "the world it boots into",
                  f"{what} in {saves}: run mcshell setup")

    accounts = Path.home() / ".local/share/PrismLauncher/accounts.json"
    try:
        kinds = [a.get("type") for a in json.loads(accounts.read_text()).get("accounts", [])]
    except (OSError, ValueError):
        kinds = []
    check(SETUP, "MSA" in kinds, "a Microsoft account in Prism",
          "signed in" if "MSA" in kinds else
          "open Prism once and sign in; until then it asks at every login")

    fix_session = ("run session/install-session.sh" if CHECKOUT
                   else "reinstall the mcshell package")
    entry = Path("/usr/share/wayland-sessions/mcshell.desktop")
    exe = from_file(entry, r"^Exec=(.+)$")
    want = str(SESSION / "start-session.sh")
    check(SETUP, exe == want, "the login screen's session entry",
          f"{entry}" if exe == want else
          (f"{entry} runs {exe}, not this checkout" if exe else f"no {entry}")
          + ("" if exe == want else ": " + fix_session))
    # The files systemd would actually load, wherever they are: this
    # checkout's install-session.sh writes them under ~/.config, the Arch
    # package under /usr/lib, and a user's copy wins over the package's.
    stale, where = [], set()
    for name in ("mcshelld.service", "mcshell-client.service", "mcshell-session.target"):
        loaded = run("systemctl", "--user", "show", "-p", "FragmentPath", "--value", name).strip()
        template = SESSION / "systemd" / (name if name.endswith(".target") else f"{name}.in")
        rendered = template.read_text().replace("@REPO@", str(ROOT)).replace("@MCSHELLD@", daemon_path())
        try:
            if not loaded or Path(loaded).read_text() != rendered:
                stale.append(name)
            else:
                where.add(str(Path(loaded).parent))
        except OSError:
            stale.append(name)
    check(SETUP, not stale, "systemd user units",
          f"current, in {', '.join(sorted(where))}" if not stale else
          f"missing or out of date: {', '.join(stale)} — " + fix_session)


def report() -> int:
    marks = {SETUP: "MISSING", REQUIRED: "MISSING", FEATURE: "lost   ", OPTIONAL: "absent "}
    for title, tiers in (("Setup", (SETUP,)), ("Required", (REQUIRED,)),
                         ("Features", (FEATURE,)), ("Optional", (OPTIONAL,))):
        print(f"\n{title}")
        for tier, ok, what, detail in results:
            if tier in tiers:
                print(f"  {'ok     ' if ok else marks[tier]} {what:38} {detail}")
    broken = [w for t, ok, w, _ in results if t in (SETUP, REQUIRED) and not ok]
    lost = [w for t, ok, w, _ in results if t == FEATURE and not ok]
    print()
    if broken:
        print(f"Not ready: {len(broken)} required thing(s) missing — {', '.join(broken)}.")
    else:
        print("Ready." + (f" {len(lost)} feature(s) unavailable." if lost else " Nothing missing."))
    return 1 if broken else 0


if __name__ == "__main__":
    header()
    setup_state()
    dependencies()
    status = report()
    if os.environ.get("XDG_SESSION_DESKTOP") == "mcshell" and os.environ.get("SWAYSOCK"):
        print("\nThe running session (session/diagnose.sh):")
        sys.stdout.flush()
        subprocess.run([str(SESSION / "diagnose.sh")])
    else:
        print("Not inside an MCShell session; `mcshell diagnose` from one shows the live state.")
    sys.exit(status)
