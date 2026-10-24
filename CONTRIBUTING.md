# Contributing

## How it fits together

Two programs talk over a unix socket, one JSON object per line:

- **`mod/`** is a Fabric mod for Minecraft 1.21.1. It draws what the daemon
  tells it to and reports clicks and keys. It makes no decisions.
- **`daemon/`** (`mcshelld`, Python) does everything else: Sway, the app
  catalog, audio, network, files, power.

If you find yourself writing logic in the mod, it belongs in the daemon.

Every message is in `docs/protocol.md` and `daemon/mcshelld/protocol.py`.
Change both in the same commit.

Each feature has a doc in `docs/design/` that explains why it works the way
it does. Read it before changing that feature. A lot of the rules look
arbitrary until you see what went wrong without them.

The UI uses Minecraft's own screens and textures. New features should look like
something vanilla could have shipped, not like a web page inside the game.

## Setup

Follow the install steps in `README.md`, then add the test tools:

```bash
cd daemon && uv pip install -e '.[test]'
```

## Running it

**Never test by logging out of your desktop.** Run Sway nested in a window:

```bash
session/start-nested.sh
```

It starts the daemon inside the nested session. For a daemon change, restart
it with `session/restart-daemon.sh`, or Ctrl+Alt+D inside the nested session.

**Drive the daemon without Minecraft** using `mcsh`:

```bash
daemon/tools/mcsh ping
daemon/tools/mcsh '{"t":"catalog_query","text":"fire"}'
daemon/tools/mcsh sh git status
daemon/tools/mcsh settings
```

Get a feature working through `mcsh` before writing any Java.

**The mod** has a dev client for fast iteration:

```bash
mod/gradlew -p mod runClient
```

The dev client and the Prism instance are separate installs. Use
`session/prism/install-mod.sh` to put a new build into the Prism instance,
and test session features there, in the real session.

## Tests and lint

These are the checks CI runs:

```bash
daemon/.venv/bin/python -m pytest -q daemon/tests
uvx ruff@0.17.1 check . daemon/tools/mcsh mod/tools/mcsrc
uvx --from shellcheck-py==0.11.0.1 shellcheck -S warning session/*.sh session/*/*.sh bin/mcshell
mod/gradlew -p mod build
```

The tests start a real daemon per test in a private home directory, with no
Sway and no D-Bus, and talk to it over its socket. They do not touch your
session. See `daemon/tests/conftest.py`.

## Changes

- Small commits, one change each.
- If a change makes a rule in a design doc untrue, update the doc in the same
  commit.
- If code starts depending on a new program, add it to `session/check.py` in
  the same commit.
- For bugs: build something that measures the problem before fixing it, and
  say whether a fix was tested or only should work.

## Bug reports

Include the output of `mcshell check`, and if the session is running,
`mcshell diagnose`.
