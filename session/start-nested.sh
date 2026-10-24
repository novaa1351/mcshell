#!/bin/sh
# Dev only: the nested session, in a window on the host desktop.
#
# The counterpart of start-session.sh, and for the same reason: sway.dev.conf
# has no path to the checkout in it, so something that knows where it lives has
# to say. Arguments go on to sway, so `start-nested.sh -d` is a debug log.

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export MCSHELL_ROOT="$repo"
export TERMINAL="${TERMINAL:-kitty}"
exec sway -c "$repo/session/sway.dev.conf" "$@"
