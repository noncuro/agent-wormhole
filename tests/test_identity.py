import os
import stat
import pytest
from agent_wormhole.identity import Identity, load_or_create


def test_load_or_create_generates_new_key(tmp_path):
    key_path = tmp_path / "identity.key"
    ident = load_or_create(key_path)
    assert key_path.exists()
    assert len(ident.pubkey_hex) == 64  # x-only pubkey, 32 bytes hex
    mode = stat.S_IMODE(key_path.stat().st_mode)
    assert mode == 0o600


def test_load_or_create_loads_existing(tmp_path):
    key_path = tmp_path / "identity.key"
    a = load_or_create(key_path)
    b = load_or_create(key_path)
    assert a.pubkey_hex == b.pubkey_hex


def test_load_refuses_bad_perms(tmp_path):
    key_path = tmp_path / "identity.key"
    load_or_create(key_path)
    os.chmod(key_path, 0o644)
    with pytest.raises(PermissionError):
        load_or_create(key_path)


def test_sign_and_verify_roundtrip(tmp_path):
    ident = load_or_create(tmp_path / "identity.key")
    digest = b"\x01" * 32
    sig = ident.sign_schnorr(digest)
    assert ident.verify_schnorr(digest, sig, ident.pubkey_bytes)
    assert not ident.verify_schnorr(digest, sig, b"\x02" * 32)


def test_ecdh_shared_secret_is_symmetric(tmp_path):
    a = load_or_create(tmp_path / "a.key")
    b = load_or_create(tmp_path / "b.key")
    s_ab = a.ecdh_x(b.pubkey_bytes)
    s_ba = b.ecdh_x(a.pubkey_bytes)
    assert s_ab == s_ba
    assert len(s_ab) == 32
