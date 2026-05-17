import asyncio
import pytest
from agent_wormhole.bulk import send_file, receive_file


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
