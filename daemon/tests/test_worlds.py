"""The world picker: what is in saves/, and the choice the launcher reads."""

import pytest


@pytest.fixture
def saves(daemon):
    saves = daemon.home / ".local/share/PrismLauncher/instances/MCShell/minecraft/saves"
    for name in ("Island", "Skyblock", "Tutorial World"):
        (saves / name).mkdir(parents=True)
        (saves / name / "level.dat").write_bytes(b"")
    return saves


def names(worlds):
    return sorted(w["name"] for w in worlds["worlds"])


def test_the_worlds_and_the_default_choice(client, saves):
    worlds = client.ask({"t": "worlds_query"}, "worlds")
    assert names(worlds) == ["Island", "Skyblock", "Tutorial World"]
    assert worlds["chosen"] == "Tutorial World"


def test_choosing_writes_the_file_the_launcher_reads(daemon, client, saves):
    worlds = client.ask({"t": "world_choose", "name": "Skyblock"}, "worlds")
    assert worlds["chosen"] == "Skyblock"
    assert (daemon.home / ".config/mcshell/world").read_text().strip() == "Skyblock"


@pytest.mark.parametrize("name", ["Nowhere", "../Island", ""])
def test_a_world_that_is_not_there_is_refused(daemon, client, saves, name):
    assert client.ask({"t": "world_choose", "name": name}, "error")["message"]
    assert not (daemon.home / ".config/mcshell/world").exists()
