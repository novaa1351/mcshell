"""The hotbar's nine slots: what is assigned, cleared, and kept on disk."""


def slot(taskbar, i):
    return taskbar["slots"][i - 1]


def assigned(i, app):
    return lambda m: slot(m, i)["app"] == app


def test_nine_empty_slots_to_begin_with(client):
    taskbar = client.ask({"t": "taskbar_query"}, "taskbar")
    assert len(taskbar["slots"]) == 9
    assert all(s["app"] is None for s in taskbar["slots"])


def test_assign_names_the_app_and_it_is_not_running(client):
    taskbar = client.ask({"t": "slot_assign", "slot": 1, "app": "test-editor.desktop"},
                         "taskbar", where=assigned(1, "test-editor.desktop"))
    s = slot(taskbar, 1)
    assert s["name"] == "Test Editor"
    assert (s["running"], s["windows"], s["transient"]) == (False, 0, False)


def test_clear(client):
    client.ask({"t": "slot_assign", "slot": 2, "app": "test-editor.desktop"},
               "taskbar", where=assigned(2, "test-editor.desktop"))
    client.ask({"t": "slot_clear", "slot": 2}, "taskbar", where=assigned(2, None))


def test_assignments_survive_a_restart(make_daemon):
    first = make_daemon().start()
    first.connect().ask({"t": "slot_assign", "slot": 5, "app": "test-browser.desktop"},
                        "taskbar", where=assigned(5, "test-browser.desktop"))
    first.stop()

    second = make_daemon().start()
    taskbar = second.connect().ask({"t": "taskbar_query"}, "taskbar")
    assert slot(taskbar, 5)["app"] == "test-browser.desktop"


def test_a_slot_out_of_range_is_refused(client):
    for bad in (0, 10):
        error = client.ask({"t": "slot_assign", "slot": bad, "app": "test-editor.desktop"},
                           "error")
        assert error["message"]


def test_arrange_replaces_the_whole_bar(client):
    client.ask({"t": "slot_assign", "slot": 1, "app": "test-editor.desktop"},
               "taskbar", where=assigned(1, "test-editor.desktop"))
    taskbar = client.ask(
        {"t": "slots_arrange", "slots": {"4": "test-editor.desktop",
                                         "6": "test-browser.desktop"}},
        "taskbar", where=assigned(4, "test-editor.desktop"))
    apps = {s["i"]: s["app"] for s in taskbar["slots"] if s["app"]}
    assert apps == {4: "test-editor.desktop", 6: "test-browser.desktop"}
