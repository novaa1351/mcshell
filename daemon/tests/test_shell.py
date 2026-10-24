"""The command bar: a line in, streamed output and an exit code out."""


def run(client, text, timeout=15.0):
    """Every message of one run, from command_start to command_end."""
    client.send({"t": "command_submit", "text": text})
    start = client.until("command_start", where=lambda m: m["text"] == text)
    cmd = start["cmd"]
    out = {"stdout": [], "stderr": []}
    other = []
    while True:
        msg = client.recv(timeout)
        if msg.get("cmd") != cmd:
            continue
        if msg["t"] == "output":
            out[msg["stream"]] += msg["lines"]
        elif msg["t"] == "command_end":
            return start, out, msg, other
        else:
            other.append(msg)


def test_output_and_exit_code(client):
    start, out, end, _ = run(client, "echo hello")
    assert out["stdout"] == ["hello"]
    assert (end["code"], end["note"]) == (0, "")


def test_stderr_and_a_failing_code(client):
    _, out, end, _ = run(client, "echo oops >&2; exit 3")
    assert out["stderr"] == ["oops"]
    assert end["code"] == 3


def test_it_starts_at_home(daemon, client):
    start, out, _, _ = run(client, "pwd")
    assert start["cwd"] == str(daemon.home)
    assert out["stdout"] == [str(daemon.home)]


def test_cd_is_kept_between_commands(client, daemon):
    (daemon.home / "sub").mkdir()
    run(client, "cd sub")
    _, out, _, _ = run(client, "pwd")
    assert out["stdout"] == [str(daemon.home / "sub")]
    run(client, "cd -")
    _, out, _, _ = run(client, "pwd")
    assert out["stdout"] == [str(daemon.home)]


def test_ansi_escapes_are_stripped(client):
    _, out, _, _ = run(client, r"printf '\033[31mred\033[0m\n'")
    assert out["stdout"] == ["red"]


def test_stdin_is_empty_rather_than_waited_on(client):
    _, out, end, _ = run(client, "cat; echo done", timeout=10)
    assert (out["stdout"], end["code"]) == (["done"], 0)


def test_clear_clears_the_chat(client):
    _, _, end, other = run(client, "clear")
    assert [m["t"] for m in other] == ["chat_clear"]
    assert end["code"] == 0


def test_one_command_at_a_time(client):
    client.send({"t": "command_submit", "text": "sleep 2"})
    client.until("command_start")
    assert client.ask({"t": "command_submit", "text": "echo second"}, "error")["message"]
    assert client.until("command_end", timeout=10)["code"] == 0
