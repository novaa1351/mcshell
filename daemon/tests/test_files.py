"""The Advancements file tree: one directory at a time."""

import os

import pytest


def ask(client, path, offset=0, limit=20):
    return client.ask({"t": "dir_query", "path": str(path), "offset": offset,
                       "limit": limit}, "dir")


@pytest.fixture
def tree(daemon):
    root = daemon.home / "tree"
    for d in ("b_dir", "A_dir"):
        (root / d).mkdir(parents=True)
    for f in ("z.md", "a.pdf", "c.py", ".hidden", ".also-hidden"):
        (root / f).write_text("x")
    return root


def test_directories_first_then_files_each_alphabetical(client, tree):
    listing = ask(client, tree)
    assert [(e["name"], e["kind"]) for e in listing["entries"]] == [
        ("A_dir", "dir"), ("b_dir", "dir"),
        ("a.pdf", "pdf"), ("c.py", "code"), ("z.md", "text")]
    assert (listing["total"], listing["error"]) == (5, "")


def test_dotfiles_are_counted_not_shown(client, tree):
    assert ask(client, tree)["hidden"] == 2


def test_empty_path_is_home(daemon, client):
    assert ask(client, "")["path"] == str(daemon.home)


def test_pages(client, daemon):
    many = daemon.home / "many"
    many.mkdir()
    for i in range(25):
        (many / f"f{i:02}.txt").write_text("")
    first = ask(client, many)
    assert (len(first["entries"]), first["total"]) == (20, 25)
    rest = ask(client, many, offset=20)
    assert [e["name"] for e in rest["entries"]] == [f"f{i:02}.txt" for i in range(20, 25)]
    # Past the end is empty, and not clamped back into range.
    past = ask(client, many, offset=40)
    assert (past["entries"], past["offset"]) == ([], 40)


def test_not_a_directory(client, tree):
    assert ask(client, tree / "z.md")["error"] == "not a directory"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads anything")
def test_permission_denied(client, tree):
    locked = tree / "A_dir"
    locked.chmod(0)
    try:
        listing = ask(client, locked)
        assert (listing["entries"], listing["error"]) == ([], "permission denied")
    finally:
        locked.chmod(0o755)


def test_a_symlinked_directory_reports_where_it_went(client, tree):
    (tree / "link").symlink_to(tree / "b_dir")
    assert ask(client, tree / "link")["path"] == str(tree / "b_dir")
