import os
import stat
import pytest
from pathlib import Path
from agent_wormhole.fs import (
    init_channel_dir,
    cleanup_channel,
    safe_save_file,
    safe_save_text,
    get_outbox_path,
    sanitize_filename,
)


@pytest.fixture
def tmp_base(tmp_path):
    """Use tmp_path as the base directory instead of /tmp/agent-wormhole."""
    return tmp_path


def test_init_channel_dir_creates_structure(tmp_base):
    channel_dir = init_channel_dir("1234-alpha-bravo-charlie", role="host", base=tmp_base)
    assert channel_dir.exists()
    assert (channel_dir / "files").exists()
    assert (channel_dir / "messages").exists()
    # Check permissions
    mode = stat.S_IMODE(channel_dir.stat().st_mode)
    assert mode == 0o700


def test_init_channel_dir_clears_stale_outbox(tmp_base):
    channel_dir = tmp_base / "1234-alpha-bravo-charlie"
    channel_dir.mkdir(parents=True)
    outbox = channel_dir / "outbox-host"
    outbox.write_text("stale data")
    init_channel_dir("1234-alpha-bravo-charlie", role="host", base=tmp_base)
    assert not outbox.exists()


def test_cleanup_channel_removes_all(tmp_base):
    channel_dir = init_channel_dir("1234-alpha-bravo-charlie", role="host", base=tmp_base)
    (channel_dir / "files" / "test.txt").write_text("data")
    (channel_dir / "messages" / "msg.txt").write_text("hello")
    cleanup_channel("1234-alpha-bravo-charlie", base=tmp_base)
    assert not channel_dir.exists()


def test_safe_save_file(tmp_base):
    channel_dir = init_channel_dir("1234-alpha-bravo-charlie", role="host", base=tmp_base)
    path = safe_save_file("1234-alpha-bravo-charlie", "test.txt", b"content", base=tmp_base)
    assert path.exists()
    assert path.read_bytes() == b"content"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_safe_save_file_rejects_traversal(tmp_base):
    init_channel_dir("1234-alpha-bravo-charlie", role="host", base=tmp_base)
    with pytest.raises(ValueError, match="Invalid filename"):
        safe_save_file("1234-alpha-bravo-charlie", "../etc/passwd", b"hack", base=tmp_base)
    with pytest.raises(ValueError, match="Invalid filename"):
        safe_save_file("1234-alpha-bravo-charlie", "/etc/passwd", b"hack", base=tmp_base)
    with pytest.raises(ValueError, match="Invalid filename"):
        safe_save_file("1234-alpha-bravo-charlie", "foo/bar.txt", b"hack", base=tmp_base)


def test_safe_save_text(tmp_base):
    channel_dir = init_channel_dir("1234-alpha-bravo-charlie", role="host", base=tmp_base)
    path = safe_save_text("1234-alpha-bravo-charlie", "long text here", base=tmp_base)
    assert path.exists()
    assert path.read_text() == "long text here"


def test_sanitize_filename():
    assert sanitize_filename("hello.txt") == "hello.txt"
    assert sanitize_filename("path/to/file.txt") is None
    assert sanitize_filename("../escape.txt") is None
    assert sanitize_filename("/absolute.txt") is None
    assert sanitize_filename("..") is None
    assert sanitize_filename(".") is None
    assert sanitize_filename("") is None


def test_get_outbox_path(tmp_base):
    init_channel_dir("1234-alpha-bravo-charlie", role="host", base=tmp_base)
    path = get_outbox_path("1234-alpha-bravo-charlie", role="host", base=tmp_base)
    assert path == tmp_base / "1234-alpha-bravo-charlie" / "outbox-host"
