"""The app catalog, from the .desktop files in tests/fixtures/share."""

import time


def ids(catalog):
    return [item["id"] for item in catalog["items"]]


def test_every_visible_app_and_not_the_hidden_one(client):
    catalog = client.ask({"t": "catalog_query", "text": ""}, "catalog")
    assert ids(catalog) == ["test-browser.desktop", "test-editor.desktop"]


def test_categories_map_to_tabs(client):
    catalog = client.ask({"t": "catalog_query", "text": ""}, "catalog")
    tabs = {item["id"]: item["tab"] for item in catalog["items"]}
    assert tabs == {"test-browser.desktop": "Browsing",
                    "test-editor.desktop": "Productivity"}


def test_search_text(client):
    assert ids(client.ask({"t": "catalog_query", "text": "brow"}, "catalog")) == [
        "test-browser.desktop"]
    assert ids(client.ask({"t": "catalog_query", "text": "EDIT"}, "catalog")) == [
        "test-editor.desktop"]
    assert ids(client.ask({"t": "catalog_query", "text": "zzz"}, "catalog")) == []


def test_tab_filter(client):
    catalog = client.ask({"t": "catalog_query", "text": "", "tab": "Browsing"}, "catalog")
    assert ids(catalog) == ["test-browser.desktop"]


def test_an_app_installed_while_running_appears_without_a_restart(daemon, client):
    # The push is the client's last search answered again, so there has to
    # have been one; the mod asks whenever the screen opens.
    client.ask({"t": "catalog_query", "text": ""}, "catalog")
    apps = daemon.home / ".local/share/applications"
    apps.mkdir(parents=True, exist_ok=True)
    # Written elsewhere and renamed in, the way a package manager does it, so
    # the daemon never reads half a file.
    tmp = apps / "test-new.desktop.part"
    tmp.write_text("[Desktop Entry]\nType=Application\nName=Test New\n"
                   "Exec=true\nCategories=Game;\n")
    tmp.rename(apps / "test-new.desktop")
    started = time.monotonic()
    pushed = client.until("catalog", timeout=10,
                          where=lambda m: "test-new.desktop" in ids(m))
    assert "test-new.desktop" in ids(pushed)
    assert time.monotonic() - started < 10
