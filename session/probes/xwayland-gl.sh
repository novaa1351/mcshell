#!/bin/sh
# Does an X client's OpenGL survive sway's XWayland on this GPU — and if not,
# which setting makes it?
#
# Found on VMware's virtual GPU (vmwgfx, SVGA3D): XWayland hands sway the
# game's GPU buffer, sway cannot import it, and sway answers with a protocol
# error that disconnects XWayland and every X client with it:
#
#     XWAYLAND: [destroyed object]: error 7: importing the supplied dmabufs failed
#
# Minecraft is an X client, so the session boots to a game that dies at its
# first frame. GNOME's XWayland on the same machine is fine.
#
# This runs one invisible sway per variant — the headless backend, rendering on
# the real GPU, so the import path is the session's — and an X OpenGL client
# inside it for a few seconds. Nothing appears on screen and the running
# desktop is not touched; it works from any terminal, in any session.
#
#     session/probes/xwayland-gl.sh          # needs mesa-utils
#
# The failure is not XWayland's alone. wlroots checks every client's dmabuf
# the same way (check_import_dmabuf: a GEM import and close on the render
# node, and vmwgfx refuses the close), so a native Wayland OpenGL client is
# run after the X one, and a fix has to keep both: gtk-frames.py, a GTK 4
# window, which is what the session's own apps are. Not Mesa's Wayland demos:
# they crash on sway whatever the GPU (measured, exit 139 on i915).
#
# Per variant: the OpenGL renderer the X client got (a hardware name, or
# llvmpipe for software), whether each client was still alive at the end and
# how many frames it drew, and whether sway logged the import failure. Logs
# stay in the directory printed last.

set -u

for p in sway Xwayland glxgears glxinfo python3; do
	command -v "$p" >/dev/null 2>&1 || { echo "missing: $p (glxgears and glxinfo are in mesa-utils)" >&2; exit 2; }
done

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

node=${1:-}
if [ -z "$node" ]; then
	for n in /dev/dri/renderD*; do node=$n; break; done
fi
[ -e "$node" ] || { echo "no render node in /dev/dri" >&2; exit 2; }
driver=$(sed -n 's/^DRIVER=//p' "/sys/class/drm/$(basename "$node")/device/uevent" 2>/dev/null)

out=$(mktemp -d "${TMPDIR:-/tmp}/xwayland-gl.XXXXXX")
# A wrapper rather than a flag: sway has no setting for XWayland's arguments,
# but wlroots runs whatever WLR_XWAYLAND names.
printf '#!/bin/sh\nexec %s -shm "$@"\n' "$(command -v Xwayland)" >"$out/Xwayland-shm"
chmod +x "$out/Xwayland-shm"

echo "GPU: $node ($driver)"
printf '%-18s %-34s %-9s %-7s %-9s %-7s %s\n' variant "X renderer" "X alive" frames "WL alive" frames "import failed"

verdict() {
	case $(cat "$1" 2>/dev/null) in
	124) echo yes ;;
	'') echo "no run" ;;
	*) echo "no ($(cat "$1"))" ;;
	esac
}

frames() {
	sed -n 's/^\([0-9]*\) frames in.*/\1/p' "$1" 2>/dev/null | head -1
}

run() {
	name=$1
	shift
	dir=$out/$name
	mkdir -p "$dir"
	# Short: a socket path past 108 bytes fails, and runtime dirs nest deep.
	rt=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/xg.XXXX")
	cat >"$dir/config" <<-EOF
	xwayland force
	exec sh -c 'glxinfo -B >"$dir/glxinfo" 2>&1; vblank_mode=0 timeout 6 glxgears >"$dir/gears" 2>&1; echo \$? >"$dir/rc"; GSK_RENDERER=gl timeout 6 python3 -I "$here/gtk-frames.py" >"$dir/wlgears" 2>&1; echo \$? >"$dir/wlrc"; swaymsg exit'
	EOF
	env -u WAYLAND_DISPLAY -u DISPLAY -u SWAYSOCK -u I3SOCK \
		XDG_RUNTIME_DIR="$rt" WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 \
		WLR_RENDER_DRM_DEVICE="$node" "$@" \
		timeout 30 sway -c "$dir/config" >"$dir/sway.log" 2>&1
	rm -rf "$rt"

	renderer=$(sed -n 's/^ *OpenGL renderer string: //p' "$dir/glxinfo" 2>/dev/null)
	# timeout's 124 means the client was still drawing when it was stopped.
	alive=$(verdict "$dir/rc")
	wlalive=$(verdict "$dir/wlrc")
	# Drawn frames, not just a live process: without them nothing was handed
	# to sway, and the import that fails was never attempted.
	frames=$(frames "$dir/gears")
	wlframes=$(frames "$dir/wlgears")
	if grep -q 'importing the supplied dmabufs failed' "$dir/sway.log"; then failed=yes; else failed=no; fi
	printf '%-18s %-34s %-9s %-7s %-9s %-7s %s\n' "$name" "$(printf %s "${renderer:-none}" | cut -c1-34)" \
		"$alive" "${frames:-0}" "$wlalive" "${wlframes:-0}" "$failed"
}

run default
run egl-no-modifiers WLR_EGL_NO_MODIFIERS=1
run xwayland-shm WLR_XWAYLAND="$out/Xwayland-shm"
run pixman WLR_RENDERER=pixman

echo "logs: $out"
