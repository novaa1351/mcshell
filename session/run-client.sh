#!/bin/sh
# Dev-only launcher for the Minecraft client. Used two ways in sway.dev.conf:
# as a startup `exec`, so a nested session comes up complete, and bound to
# $hatch+m for a manual restart.
#
# M7 replaces this with `systemctl --user restart mcshell-client` against the
# real Prism instance. Until then the Fabric dev client is what we iterate on,
# and it must be launched from *inside* the nested session so it inherits that
# session's WAYLAND_DISPLAY/DISPLAY — a client started from the host desktop
# renders on the host and talks to the wrong compositor.
#
# The client is identified by a saved process group, not by matching "gradle"
# or "minecraft" against command lines: the shell running this script and any
# editor with the file open match those too, and get killed with it. Same trap
# restart-daemon.sh documents.
#
# The process group matters as well as the pid. `gradlew runClient` forks the
# client into a *child* JVM, so killing gradle alone orphans a running
# Minecraft, which then holds saves/<world>/session.lock and makes the next
# start die with SessionLock$AlreadyLockedException.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
log="$runtime/mcshell-client.log"
pidfile="$runtime/mcshell-client.pid"

if [ ! -x "$repo/mod/gradlew" ]; then
    echo "no gradle wrapper at $repo/mod/gradlew" >&2
    exit 1
fi

# --- stop whatever is already running ---------------------------------------
if [ -f "$pidfile" ]; then
    pgid=$(cat "$pidfile" 2>/dev/null || true)
    if [ -n "${pgid:-}" ] && kill -0 "-$pgid" 2>/dev/null; then
        kill -TERM "-$pgid" 2>/dev/null || true
        i=0
        while kill -0 "-$pgid" 2>/dev/null && [ "$i" -lt 60 ]; do
            sleep 0.25
            i=$((i + 1))
        done
        kill -KILL "-$pgid" 2>/dev/null || true
    fi
    rm -f "$pidfile"
fi

# --- start ------------------------------------------------------------------
# setsid so the launcher is its own process-group leader: its pid is the pgid,
# which is what makes the kill above reach the forked client JVM.
#
# On failure a terminal opens on the tail of the log. Without it a build error
# looks exactly like a working session that just never draws anything, which is
# the least debuggable outcome available.
: > "$log"
setsid sh -c "
    cd '$repo/mod' || exit 1
    ./gradlew --console=plain runClient >>'$log' 2>&1
    status=\$?
    [ \$status -ne 0 ] && ${TERMINAL:-foot} -e sh -c 'tail -n 40 \"$log\"; printf \"\n[client exited — enter to close] \"; read x'
    exit \$status
" &

echo $! > "$pidfile"
