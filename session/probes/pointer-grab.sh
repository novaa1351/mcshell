#!/bin/sh
# Print whether any X client is holding the pointer. See pointer-grab.c.
#
# Compiles on first use and caches the binary, so this is one command with no
# setup step. Exits 0 when the pointer is free, 1 when it is held.
set -eu

src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/pointer-grab.c
cache=${XDG_CACHE_HOME:-$HOME/.cache}/mcshell
bin=$cache/pointer-grab

if [ ! -x "$bin" ] || [ "$src" -nt "$bin" ]; then
    mkdir -p "$cache"
    cc -O1 -o "$bin" "$src" -lX11
fi

exec "$bin"
