import os
import stat
import pytest
from agent_wormhole.fs import (
    init_peer_dir,
    outbox_path,
    inbox_files_dir,
    sanitize_filename,
    safe_save_file,
)


def test_init_peer_dir_creates_structure(tmp_path):
    pdir = init_peer_dir("alice", base=tmp_path)
    assert pdir.exists()
    assert (pdir / "files").exists()
    mode = stat.S_IMODE(pdir.stat().st_mode)
    assert mode == 0o700


@pytest.mark.parametrize("peer", ["../alice", "/tmp/alice", "..", "alice/keys"])
def test_init_peer_dir_rejects_path_like_peer_names(tmp_path, peer):
    with pytest.raises(ValueError):
        init_peer_dir(peer, base=tmp_path)


def test_outbox_path_is_under_peer_dir(tmp_path):
    init_peer_dir("alice", base=tmp_path)
    assert outbox_path("alice", base=tmp_path) == tmp_path / "alice" / "outbox"


def test_inbox_files_dir(tmp_path):
    init_peer_dir("alice", base=tmp_path)
    assert inbox_files_dir("alice", base=tmp_path) == tmp_path / "alice" / "files"


def test_sanitize_filename_rejects_traversal():
    assert sanitize_filename("../etc/passwd") is None
    assert sanitize_filename("/abs/path") is None
    assert sanitize_filename("..") is None
    assert sanitize_filename("") is None
    assert sanitize_filename("normal.txt") == "normal.txt"


def test_safe_save_file_rejects_bad_name(tmp_path):
    init_peer_dir("alice", base=tmp_path)
    with pytest.raises(ValueError):
        safe_save_file("alice", "../evil", b"x", base=tmp_path)


def test_safe_save_file_writes_with_0600(tmp_path):
    init_peer_dir("alice", base=tmp_path)
    path = safe_save_file("alice", "report.pdf", b"data", base=tmp_path)
    assert path.read_bytes() == b"data"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
