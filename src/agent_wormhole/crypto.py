from __future__ import annotations

from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from spake2 import SPAKE2_A, SPAKE2_B


MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB


@dataclass
class SessionKeys:
    """Direction-separated encryption keys with nonce counters."""

    send_key: bytes
    recv_key: bytes
    _send_nonce: int = field(default=0, repr=False)
    _recv_nonce: int = field(default=0, repr=False)

    def next_send_nonce(self) -> bytes:
        nonce = self._send_nonce.to_bytes(12, "big")
        self._send_nonce += 1
        return nonce

    def next_recv_nonce(self) -> bytes:
        nonce = self._recv_nonce.to_bytes(12, "big")
        self._recv_nonce += 1
        return nonce


class Handshake:
    """SPAKE2 handshake wrapper."""

    def __init__(self, spake_instance, is_host: bool):
        self._spake = spake_instance
        self._is_host = is_host

    @classmethod
    def host(cls, password: bytes) -> Handshake:
        return cls(SPAKE2_A(password), is_host=True)

    @classmethod
    def peer(cls, password: bytes) -> Handshake:
        return cls(SPAKE2_B(password), is_host=False)

    def start(self) -> bytes:
        return self._spake.start()

    def finish(self, other_msg: bytes) -> SessionKeys:
        shared_secret = self._spake.finish(other_msg)
        host_to_peer = _derive_key(shared_secret, b"host-to-peer")
        peer_to_host = _derive_key(shared_secret, b"peer-to-host")
        if self._is_host:
            return SessionKeys(send_key=host_to_peer, recv_key=peer_to_host)
        else:
            return SessionKeys(send_key=peer_to_host, recv_key=host_to_peer)


def _derive_key(secret: bytes, info: bytes) -> bytes:
    return HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=info,
    ).derive(secret)


def encrypt(keys: SessionKeys, plaintext: bytes, *, sending: bool) -> bytes:
    if len(plaintext) > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message size {len(plaintext)} exceeds maximum {MAX_MESSAGE_SIZE}")
    if sending:
        nonce = keys.next_send_nonce()
        key = keys.send_key
    else:
        nonce = keys.next_recv_nonce()
        key = keys.recv_key
    return AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt(keys: SessionKeys, ciphertext: bytes, *, receiving: bool) -> bytes:
    if receiving:
        nonce = keys.next_recv_nonce()
        key = keys.recv_key
    else:
        nonce = keys.next_send_nonce()
        key = keys.send_key
    return AESGCM(key).decrypt(nonce, ciphertext, None)
