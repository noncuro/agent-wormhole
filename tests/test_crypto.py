import pytest
from agent_wormhole.crypto import (
    Handshake,
    SessionKeys,
    encrypt,
    decrypt,
    MAX_MESSAGE_SIZE,
)


def test_handshake_matching_passwords():
    """Both sides derive the same session keys when passwords match."""
    host = Handshake.host(b"9471-alpha-bravo-charlie")
    peer = Handshake.peer(b"9471-alpha-bravo-charlie")

    msg_host = host.start()
    msg_peer = peer.start()

    keys_host = host.finish(msg_peer)
    keys_peer = peer.finish(msg_host)

    # Host's send key == peer's receive key and vice versa
    assert keys_host.send_key == keys_peer.recv_key
    assert keys_host.recv_key == keys_peer.send_key


def test_handshake_mismatched_passwords():
    """Mismatched passwords cause key derivation to produce incompatible keys.

    Note: spake2 library may raise on finish() or may silently produce
    different keys depending on version. Either way, encryption/decryption
    will fail. We test that the resulting keys cannot communicate.
    """
    host = Handshake.host(b"9471-alpha-bravo-charlie")
    peer = Handshake.peer(b"9471-wrong-wrong-wrong")

    msg_host = host.start()
    msg_peer = peer.start()

    try:
        keys_host = host.finish(msg_peer)
        keys_peer = peer.finish(msg_host)
    except Exception:
        # SPAKE2 may raise on mismatched passwords — that's fine
        return

    # If it didn't raise, the keys should be incompatible
    ciphertext = encrypt(keys_host, b"test", sending=True)
    with pytest.raises(Exception):
        decrypt(keys_peer, ciphertext, receiving=True)


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt returns original plaintext."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    keys_peer = peer.finish(msg_h)

    plaintext = b"hello world"
    ciphertext = encrypt(keys_host, plaintext, sending=True)
    result = decrypt(keys_peer, ciphertext, receiving=True)
    assert result == plaintext


def test_encrypt_decrypt_reverse_direction():
    """Peer sends to host using the reverse key pair."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    keys_peer = peer.finish(msg_h)

    plaintext = b"reply from peer"
    ciphertext = encrypt(keys_peer, plaintext, sending=True)
    result = decrypt(keys_host, ciphertext, receiving=True)
    assert result == plaintext


def test_nonce_increments():
    """Each encryption uses a new nonce; same plaintext produces different ciphertext."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    keys_peer = peer.finish(msg_h)

    ct1 = encrypt(keys_host, b"same", sending=True)
    ct2 = encrypt(keys_host, b"same", sending=True)
    assert ct1 != ct2


def test_decrypt_wrong_order_fails():
    """Decrypting out of nonce order fails."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    keys_peer = peer.finish(msg_h)

    ct1 = encrypt(keys_host, b"first", sending=True)
    ct2 = encrypt(keys_host, b"second", sending=True)

    # Skip ct1, try to decrypt ct2 first — should fail
    with pytest.raises(Exception):
        decrypt(keys_peer, ct2, receiving=True)


def test_max_message_size_enforced():
    """Messages over MAX_MESSAGE_SIZE are rejected."""
    host = Handshake.host(b"test-password")
    peer = Handshake.peer(b"test-password")
    msg_h = host.start()
    msg_p = peer.start()
    keys_host = host.finish(msg_p)
    _ = peer.finish(msg_h)

    too_large = b"x" * (MAX_MESSAGE_SIZE + 1)
    with pytest.raises(ValueError, match="exceeds maximum"):
        encrypt(keys_host, too_large, sending=True)
