import asyncio
import pytest
from agent_wormhole.bulk import is_wormhole_code, receive_file, send_file, send_text


@pytest.mark.parametrize(
    "code,expected",
    [
        ("7-foo-bar", True),
        ("12-guitarist-revenge", True),
        ("4-foo-bar-baz", True),
        ("0-a-b", True),
        ("foo-bar", False),       # no leading number
        ("7-foo", False),         # only one word segment
        ("7", False),
        ("connect to 7-foo-bar", False),  # embedded, not exact
        ("-0", False),
        ("", False),
    ],
)
def test_is_wormhole_code(code, expected):
    assert is_wormhole_code(code) is expected


@pytest.mark.asyncio
async def test_send_text_argv_and_stdin(monkeypatch):
    captured = {}

    class FakeStdin:
        def __init__(self):
            self.data = b""

        def write(self, b):
            self.data += b

        async def drain(self):
            pass

        def close(self):
            captured["stdin_closed"] = True

    class FakeStdout:
        def __init__(self, lines):
            self._lines = list(lines)

        async def readline(self):
            return self._lines.pop(0) if self._lines else b""

    class FakeProc:
        returncode = 0

        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout([b"Wormhole code is: 7-foo-bar\n"])

        async def wait(self):
            return 0

    proc = FakeProc()

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    codes = []

    async def on_code(code):
        codes.append(code)

    await send_text('{"hello":"world"}', on_code=on_code)

    assert captured["args"] == ("wormhole", "send", "--text", "-")
    assert proc.stdin.data == b'{"hello":"world"}'
    assert captured["stdin_closed"] is True
    assert codes == ["7-foo-bar"]


@pytest.mark.asyncio
async def test_send_text_cancel_terminates_subprocess(monkeypatch):
    class FakeStdin:
        def write(self, _b):
            pass

        async def drain(self):
            pass

        def close(self):
            pass

    class FakeStdout:
        async def readline(self):
            await asyncio.Event().wait()

    class FakeProc:
        returncode = None

        def __init__(self):
            self.stdin = FakeStdin()
            self.stdout = FakeStdout()
            self.terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    proc = FakeProc()

    async def fake_exec(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    async def on_code(_code):
        pass

    task = asyncio.create_task(send_text("payload", on_code=on_code))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert proc.terminated is True


@pytest.mark.asyncio
async def test_receive_file_inserts_option_terminator(tmp_path, monkeypatch):
    captured = {}
    received = tmp_path / "received.txt"

    class FakeProc:
        returncode = 0

        async def communicate(self):
            received.write_text("ok")
            return b"", b""

    async def fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    saved = await receive_file(code="4-foo-bar", dest_dir=tmp_path, accept=True)

    assert saved == received
    assert captured["args"] == ("wormhole", "receive", "--accept-file", "--", "4-foo-bar")
    assert captured["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_receive_file_rejects_option_like_code(tmp_path, monkeypatch):
    async def fake_exec(*args, **kwargs):
        raise AssertionError("subprocess should not be started for invalid codes")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    with pytest.raises(ValueError, match="invalid wormhole code"):
        await receive_file(code="-0", dest_dir=tmp_path, accept=True)


@pytest.mark.asyncio
@pytest.mark.network
async def test_file_roundtrip(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello-world" * 100)
    dst_dir = tmp_path / "inbox"
    dst_dir.mkdir()

    code_holder: dict[str, str] = {}

    async def on_code(code: str) -> None:
        code_holder["c"] = code
        await receive_file(code=code, dest_dir=dst_dir, accept=True)

    await send_file(path=src, on_code=on_code)

    received = dst_dir / "src.bin"
    assert received.exists()
    assert received.read_bytes() == src.read_bytes()
