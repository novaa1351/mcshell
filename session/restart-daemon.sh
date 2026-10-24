#!/bin/sh
# Dev-only restart for mcshelld. Used two ways in sway.dev.conf: as the startup
# `exec`, so the newest nested session takes ownership of the daemon, and bound
# to $hatch+d for a manual restart.
#
# M7 replaces this entirely with `systemctl --user restart mcshelld`.
#
# The daemon is identified by *who holds the socket*, not by matching "mcshelld"
# against command lines. `pkill -f mcshelld` is the obvious approach and it is
# wrong: the shell running this script, an editor with the file open, or a
# terminal where someone typed the path all match it and get killed too.

set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
daemon="$repo/daemon/.venv/bin/mcshelld"
runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
sock="$runtime/mcshell.sock"
log="$runtime/mcshelld.log"

if [ ! -x "$daemon" ]; then
    echo "no daemon at $daemon" >&2
    echo "run: cd '$repo/daemon' && uv venv && uv pip install -e ." >&2
    exit 1
fi

# Whoever is listening on the socket is the daemon to replace.
pid=$(ss -lxnp 2>/dev/null | awk -v s="$sock" '
    index($0, s) && match($0, /pid=[0-9]+/) {
        print substr($0, RSTART + 4, RLENGTH - 4); exit
    }')

if [ -n "${pid:-}" ]; then
    kill "$pid" 2>/dev/null || true
    # Wait for it to release the socket rather than racing its cleanup.
    i=0
    while [ -e "$sock" ] && [ "$i" -lt 50 ]; do
        sleep 0.1
        i=$((i + 1))
    done
    [ -e "$sock" ] && kill -9 "$pid" 2>/dev/null || true
fi

exec "$daemon" -v >>"$log" 2>&1
