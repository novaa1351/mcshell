#!/bin/sh
# Super: raise Minecraft.
#
# CLAUDE.md's display model (Fork A) is that Minecraft fills the screen behind
# everything and apps raise above it, so getting back to the shell means raising
# Minecraft. Everything floats (see session/layout.conf), so raising is what
# focusing already does. Doing it here rather than in the daemon is deliberate:
# this is a plain compositor action and must keep working when the daemon is
# dead.
#
# It used to push the overview as a second step, back when the overview held a
# second copy of the hotbar. The hotbar is real items now and it is already on
# screen the moment Minecraft is raised, so opening a panel over it on the way
# in would cover the thing you pressed Super to get back to. The overview is
# the command-output panel now, and it opens when there is output or when the
# overview key asks for it.
#
# Minecraft is matched on window_class, not app_id: it runs under XWayland, and
# a real 1.21.1 client reports class "Minecraft* 1.21.1" with app_id unset. The
# app_id line is there for the day it runs as a native Wayland client; a
# criteria that matches nothing is a no-op, so trying both costs nothing.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# Raise first, because that is what the key is for and it should feel instant.
swaymsg '[class="^Minecraft"] focus' >/dev/null 2>&1 || true
swaymsg '[app_id="^[Mm]inecraft"] focus' >/dev/null 2>&1 || true

# Then re-assert the geometry, so Super also repairs the layout if anything has
# since moved or resized Minecraft. Usually a no-op. Not one resize but two —
# a window sitting at the wrong size comes out a few pixels short on the first
# one just as a mapping window does, which fill.sh explains.
"$repo/session/fill.sh" 'class="^Minecraft"' 'app_id="^[Mm]inecraft"'
