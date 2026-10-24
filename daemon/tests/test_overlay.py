"""The overlay process, when there is nowhere for it to draw.

A test daemon has no display, so its overlay starts and dies at once — the
same as a session whose gtk4-layer-shell is missing. It is the boot screen
that asks for it first, every tick for up to ninety seconds.
"""

import time


def test_an_overlay_that_dies_at_once_is_not_started_again_every_tick(daemon):
    time.sleep(3)
    log = daemon.log_text()
    # Before the fix: about seven in three seconds, one per boot tick.
    assert log.count("overlay: up") == 1, log
    assert "boot: no overlay to draw the loading screen on" in log
