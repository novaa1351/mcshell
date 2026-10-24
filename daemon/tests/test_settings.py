"""The settings hub, through the page that needs no hardware: Accessibility.

Sound, Video and Network answer from pactl, brightnessctl and nmcli, which
the test daemon does not have; those pages are tested only for coming back
empty rather than broken.
"""

CLOCK = "general.clock..show"


def rows(schema):
    return {item["key"]: item for item in schema["items"]}


def test_the_general_page(client):
    schema = client.ask({"t": "settings_query", "page": "general"}, "settings_schema")
    clock = rows(schema)[CLOCK]
    assert (clock["type"], clock["value"]) == ("bool", True)


def test_a_change_is_pushed_to_the_page_and_the_hud(client):
    client.send({"t": "setting_set", "key": CLOCK, "value": False})
    schema = client.until("settings_schema", where=lambda m: CLOCK in rows(m))
    assert rows(schema)[CLOCK]["value"] is False
    assert client.until("hud", where=lambda m: m["clock"] is False)


def test_a_change_survives_a_restart(make_daemon):
    first = make_daemon().start()
    c = first.connect()
    c.send({"t": "setting_set", "key": CLOCK, "value": False})
    c.until("settings_schema", where=lambda m: CLOCK in rows(m))
    first.stop()

    second = make_daemon().start()
    schema = second.connect().ask({"t": "settings_query", "page": "general"},
                                  "settings_schema")
    assert rows(schema)[CLOCK]["value"] is False


def test_an_unknown_key_is_refused(client):
    assert client.ask({"t": "setting_set", "key": "general.no.such", "value": 1},
                      "error")["message"]


def test_pages_without_their_tools_come_back_empty_not_broken(client):
    for page in ("audio", "network"):
        schema = client.ask({"t": "settings_query", "page": page}, "settings_schema",
                            where=lambda m, page=page: m.get("page") == page)
        assert isinstance(schema["items"], list)
