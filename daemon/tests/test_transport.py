"""The wire itself: one JSON object per line, and a bad one costs only itself."""


def test_ping(client):
    assert client.ask({"t": "ping"}, "pong") == {"t": "pong"}


def test_malformed_json_is_an_error_and_the_connection_survives(client):
    error = client.ask("this is not json", "error")
    assert "malformed JSON" in error["message"]
    assert client.ask({"t": "ping"}, "pong")


def test_unknown_type_is_named_in_the_error(client):
    error = client.ask({"t": "no_such_message"}, "error")
    assert "no_such_message" in error["message"]
    assert client.ask({"t": "ping"}, "pong")


def test_hello_is_answered_with_the_state_to_draw(client):
    client.ask({"t": "hello", "proto": 1, "mc": "1.21.1"}, "ok")
    # What the mod needs before it can draw anything, unasked.
    taskbar = client.until("taskbar")
    assert [s["i"] for s in taskbar["slots"]] == list(range(1, 10))
    hud = client.until("hud")
    assert {"clock", "time", "date"} <= hud.keys()


def test_a_change_reaches_every_client(daemon):
    a, b = daemon.connect(), daemon.connect()
    a.send({"t": "slot_assign", "slot": 3, "app": "test-editor.desktop"})
    pushed = b.until("taskbar", where=lambda m: m["slots"][2]["app"] is not None)
    assert pushed["slots"][2]["app"] == "test-editor.desktop"


def test_a_client_that_disconnects_mid_line_does_not_stop_the_daemon(daemon):
    gone = daemon.connect()
    gone.file.write(b'{"t":"pi')
    gone.file.flush()
    gone.close()
    assert daemon.connect().ask({"t": "ping"}, "pong")


def test_sigterm_stops_it_cleanly_and_removes_the_socket(daemon):
    assert daemon.stop() == 0
    assert not daemon.socket.exists()
