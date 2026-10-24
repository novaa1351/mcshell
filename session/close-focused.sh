#!/bin/sh
# Close the focused window. Refuse if it is the backdrop.
#
# Bound to Alt+F4 and $mod+Shift+q. Sway bindings are global — they fire
# whatever is focused, and the compositor sees the key before the application
# does — so a plain `bindsym Alt+F4 kill` would also close Minecraft, and
# Minecraft is the desktop. Hence a script rather than a binding.
#
# Plain swaymsg, no daemon: closing a window has to work when mcshelld is dead,
# for the same reason raise-mc.sh does.
#
# `kill` is sway's polite close request, not a signal — an editor with unsaved
# work still gets to argue about it.

set -u

# Exits 0 when the focused window is the backdrop. The two identities are the
# ones layout.conf pins, and for the same reason: the client runs under
# XWayland today, and may not always.
swaymsg -t get_tree 2>/dev/null | python3 -c '
import json, re, sys


def focused(node):
    if node.get("focused"):
        return node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        hit = focused(child)
        if hit:
            return hit
    return None


try:
    node = focused(json.load(sys.stdin))
except Exception:
    sys.exit(0)  # no tree to read is not a window worth closing

if node is None:
    sys.exit(0)

props = node.get("window_properties") or {}
backdrop = re.match(r"^[Mm]inecraft", node.get("app_id") or "") or re.match(
    r"^Minecraft", props.get("class") or ""
)
sys.exit(0 if backdrop else 1)
' && exit 0

swaymsg kill >/dev/null 2>&1 || true
