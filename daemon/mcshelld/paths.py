"""Where the shell's own files are, as opposed to where its state is.

State has always been under the XDG directories. Code was found as a sibling
of this file — `parents[2]` is the checkout — which is right in a checkout and
wrong the moment a package puts the daemon in one directory and `session/` in
another. `$MCSHELL_ROOT` is the same variable `start-session.sh` exports for
sway's bindings; the daemon's unit sets it, and without it nothing changes.
"""

import os
from pathlib import Path


def root() -> Path:
    """The tree that holds `session/`: `$MCSHELL_ROOT`, else this checkout."""
    configured = os.environ.get("MCSHELL_ROOT")
    return Path(configured) if configured else Path(__file__).resolve().parents[2]


SESSION = root() / "session"

#: sudo's and the Wi-Fi page's password prompt, a real window. Under the root
#: rather than beside this file, which is a different directory once the
#: daemon is installed as a Python package.
ASKPASS = root() / "daemon" / "tools" / "mcshell-askpass"
