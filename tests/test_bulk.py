import asyncio
import pytest
from agent_wormhole.bulk import send_file, receive_file


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
