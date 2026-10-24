"""Statistics: the machine, and the kill button's limits."""

import subprocess
import time


def test_general_and_disks_have_rows(client):
    for tab in ("general", "disks"):
        stats = client.ask({"t": "stats_query", "tab": tab}, "stats")
        assert stats["rows"] and all({"label", "value"} <= r.keys() for r in stats["rows"])


def test_an_unknown_tab_is_refused(client):
    assert "no_such" in client.ask({"t": "stats_query", "tab": "no_such"}, "error")["message"]


def test_the_live_tab_streams_while_watched(client):
    client.send({"t": "stats_watch", "on": True, "sort": "cpu", "desc": True, "limit": 5})
    procs = client.until("processes", timeout=5)
    assert 0 < len(procs["procs"]) <= 5
    client.until("processes", timeout=5)


def test_kill_sends_sigterm(client):
    victim = subprocess.Popen(["sleep", "60"])
    try:
        assert client.ask({"t": "process_kill", "pid": victim.pid}, "ok")
        assert victim.wait(timeout=5) == -15
    finally:
        victim.kill()


def test_kill_refuses_init_and_the_daemon_itself(daemon, client):
    for pid in (1, daemon.proc.pid):
        assert "cannot be killed" in client.ask({"t": "process_kill", "pid": pid},
                                                "error")["message"]
    time.sleep(0.2)
    assert daemon.proc.poll() is None


def test_kill_of_a_process_that_is_gone(client):
    gone = subprocess.Popen(["true"])
    gone.wait()
    assert "no process" in client.ask({"t": "process_kill", "pid": gone.pid},
                                      "error")["message"]
