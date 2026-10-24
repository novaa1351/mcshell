#!/bin/sh
# The session the display manager starts. Named in mcshell.desktop, and the only thing that
# runs outside sway — which is what makes it the place to clean up afterwards.
#
# Everything here is deliberately small. If this script is wrong the session
# does not start at all, and the failure lands you back at the login screen
# with every other session still in the picker. That is the whole reason
# MCShell is a second entry rather than a replacement for one.

set -u

repo=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

# Sway nags, in a red bar across the top of the screen, whenever it finds a
# proprietary Nvidia or DisplayLink driver: "Proprietary GPU drivers are not
# supported by sway. Do not report issues." It is a layer-shell surface, so it
# sits above everything including the boot screen, and it comes back at every
# single login until it is clicked away.
#
# That message is aimed at someone running sway directly, and it is asking them
# not to file sway bugs. It is the right message for that person and the wrong
# one for a desktop: this is a hybrid-graphics laptop where the game runs on the
# Intel iGPU and the dGPU exists to PRIME-offload applications, which is exactly
# the configuration the shell is built for. Nothing is being hidden — sway still
# logs the driver it found to session.log, where the fact belongs.
#
# The environment variable rather than `--unsupported-gpu`, though sway's own
# message offers both and both work here. Measured: an unrecognised *flag* makes
# sway exit 1, and this script is the one place where being wrong costs a login
# rather than a session pick. An unrecognised environment variable is ignored.
export SWAY_UNSUPPORTED_GPU=true

# What the desktop calls itself. xdg-desktop-portal-wlr keys off
# XDG_CURRENT_DESKTOP to decide it is the portal in charge, so screen sharing
# and file pickers from applications depend on this line.
export XDG_CURRENT_DESKTOP=sway
export XDG_SESSION_DESKTOP=mcshell

# A log that outlives the session, because the thing you most want to read is
# the reason the last login failed, and by then the journal is the only other
# copy. State, not cache: it is small and it is worth keeping.
state="${XDG_STATE_HOME:-$HOME/.local/state}/mcshell"
mkdir -p "$state"
log="$state/session.log"

# Truncated per login rather than appended, so what you open is this session
# and not a year of them.
: >"$log"
printf '=== %s ===\n' "$(date -Is)" >>"$log"

# VMware's virtual GPU (vmwgfx): sway draws in software, or nothing that uses
# the GPU can show a window. Before wlroots accepts a client's GPU buffer it
# imports it on the render node and closes the handle again
# (check_import_dmabuf), and vmwgfx refuses the close, so sway disconnects the
# client — XWayland first, and Minecraft with it. No setting skips the check.
# The pixman renderer advertises no GPU buffers at all, so every client falls
# back to shared memory. Measured on a VMware VM with
# session/probes/xwayland-gl.sh: of four variants only pixman kept both an X
# and a native Wayland OpenGL client alive, and with it a real login reached
# the world. The cost is that the game renders on llvmpipe there.
#
# By the kernel driver of each DRM card, so only that GPU is affected; real
# hardware keeps the GPU. A WLR_RENDERER already set is the user's and wins.
if [ -z "${WLR_RENDERER:-}" ]; then
	for card in /sys/class/drm/card*; do
		[ -e "$card/device/driver" ] || continue
		if [ "$(basename "$(readlink -f "$card/device/driver")")" = vmwgfx ]; then
			export WLR_RENDERER=pixman
			printf 'VMware GPU (vmwgfx): WLR_RENDERER=pixman, software rendering\n' >>"$log"
			break
		fi
	done
fi

# The first two seconds of a login are sway's own flat colour, before the
# daemon exists to draw anything. Painting the boot screen's own background
# there means the whole login is one picture rather than a colour that turns
# into one: `loading.py` renders the dirt at this monitor's GUI scale, and the
# daemon's layer-shell surface comes up over the top of an identical ground.
#
# Written as a config.d snippet rather than into sway.conf because it can fail
# — no client jar, no output to measure — and the flat colour in sway.conf has
# to stay as the fallback. Removed first, so a render that fails now cannot
# leave last login's picture behind at a resolution this monitor no longer has.
# Last login's marker, if the runtime directory outlived it. The client unit
# waits on this one, and a stale copy would let Prism straight past.
rm -f "${XDG_RUNTIME_DIR:-/tmp}/mcshell-boot.drawn"

bg="$state/loading-bg.png"
snippet="${XDG_CONFIG_HOME:-$HOME/.config}/sway/config.d/mcshell-boot-bg.conf"
rm -f "$snippet"
mkdir -p "$(dirname "$snippet")"
if size=$(wlr-randr --json 2>/dev/null | \
		python3 -c 'import json,sys
for o in json.load(sys.stdin):
    for m in o.get("modes", []):
        if m.get("current"):
            print(m["width"], m["height"]); raise SystemExit
raise SystemExit(1)' 2>/dev/null); then
	:
else
	# No compositor to ask yet — this runs before sway. Fall back to the
	# kernel's idea of the panel, and then to a common size.
	size=$(python3 - <<-'EOF' 2>/dev/null || echo "1920 1080"
	import glob, re
	for path in sorted(glob.glob("/sys/class/drm/*/modes")):
	    try:
	        first = open(path).readline().strip()
	    except OSError:
	        continue
	    m = re.fullmatch(r"(\d+)x(\d+)", first)
	    if m:
	        print(m.group(1), m.group(2))
	        break
	else:
	    raise SystemExit(1)
	EOF
	)
fi
if PYTHONPATH="$repo/session" python3 "$repo/session/loading.py" \
		--width "${size% *}" --height "${size#* }" \
		--progress 0 --logo "$repo/session/assets/logo.png" \
		--out "$bg" >>"$log" 2>&1 && [ -s "$bg" ]; then
	# The trailing colour is sway's own fallback for a background it cannot
	# read, and it is the same one sway.conf sets. Measured: sway logs
	# "using fallback" and stores solid_color, rather than erroring and
	# leaving the output with nothing. So a picture that goes missing between
	# here and sway reading it costs the picture, never the session.
	printf 'output * bg %s fill #1a1a2e\n' "$bg" >"$snippet"
else
	printf 'boot background: not rendered; keeping the solid colour\n' >>"$log"
fi

# The terminal, which is the user's choice: $TERMINAL. GDM starts this script
# with its own short environment — measured, no login shell between the two —
# so a variable set in a shell profile may never arrive. systemd's user
# manager reads ~/.config/environment.d at its start, whatever the display
# manager, so that is the place to set it and this asks there second.
if [ -z "${TERMINAL:-}" ]; then
	TERMINAL=$(systemctl --user show-environment 2>/dev/null | sed -n 's/^TERMINAL=//p')
fi
export TERMINAL="${TERMINAL:-foot}"

# The one place the checkout's location is known, handed to sway and through
# it to every binding. sway.conf has no path of its own.
export MCSHELL_ROOT="$repo"

sway -c "$repo/session/sway.conf" >>"$log" 2>&1
status=$?

# sway has exited, so the session is over. Stop what it started rather than
# leaving it to the user manager: Minecraft holds the world's session.lock, and
# a copy still running at the next login makes that login fail with an error
# about the lock rather than about the real cause.
systemctl --user stop mcshell-session.target >>"$log" 2>&1 || true

exit $status
