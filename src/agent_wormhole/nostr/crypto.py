"""NIP-44 v2 encryption — https://github.com/nostr-protocol/nips/blob/master/44.md"""
from __future__ import annotations

import base64
import hmac
import os
from hashlib import sha256

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand

VERSION = 0x02


def conversation_key(my_priv: bytes, peer_pubkey_xonly: bytes) -> bytes:
    """HKDF-Extract over the ECDH shared x-coordinate."""
    from coincurve import PublicKey
    full_compressed = b"\x02" + peer_pubkey_xonly
    peer = PublicKey(full_compressed)
    shared_point = peer.multiply(my_priv)
    shared_x = shared_point.format(compressed=True)[1:]
    return hmac.new(b"nip44-v2", shared_x, sha256).digest()


def _derive_keys(ck: bytes, nonce: bytes) -> tuple[bytes, bytes, bytes]:
    """Return (chacha_key, chacha_nonce, hmac_key)."""
    hkdf = HKDFExpand(algorithm=SHA256(), length=76, info=nonce)
    okm = hkdf.derive(ck)
    return okm[:32], okm[32:44], okm[44:76]


def calc_padded_len(unpadded_len: int) -> int:
    """Per NIP-44 spec."""
    if unpadded_len <= 32:
        return 32
    next_power = 1 << (unpadded_len - 1).bit_length()
    chunk = next_power // 8 if next_power > 256 else 32
    return chunk * ((unpadded_len - 1) // chunk + 1)


def _pad(plaintext: bytes) -> bytes:
    n = len(plaintext)
    if n < 1 or n > 65535:
        raise ValueError("plaintext length must be 1..65535 bytes")
    padded_len = calc_padded_len(n)
    return n.to_bytes(2, "big") + plaintext + b"\x00" * (padded_len - n)


def _unpad(padded: bytes) -> bytes:
    n = int.from_bytes(padded[:2], "big")
    if n < 1 or n > len(padded) - 2:
        raise ValueError("invalid padded length prefix")
    return padded[2 : 2 + n]


def encrypt(plaintext: str, *, conversation_key: bytes, nonce: bytes | None = None) -> str:
    if nonce is None:
        nonce = os.urandom(32)
    if len(nonce) != 32:
        raise ValueError("nonce must be 32 bytes")
    chacha_key, chacha_nonce, hmac_key = _derive_keys(conversation_key, nonce)
    padded = _pad(plaintext.encode("utf-8"))
    cipher = Cipher(
        algorithms.ChaCha20(chacha_key, b"\x00" * 4 + chacha_nonce), mode=None
    ).encryptor()
    ct = cipher.update(padded) + cipher.finalize()
    mac = hmac.new(hmac_key, nonce + ct, sha256).digest()
    return base64.b64encode(bytes([VERSION]) + nonce + ct + mac).decode("ascii")


def decrypt(payload: str, *, conversation_key: bytes) -> str:
    raw = base64.b64decode(payload)
    if len(raw) < 1 + 32 + 32:
        raise ValueError("payload too short")
    if raw[0] != VERSION:
        raise ValueError(f"unsupported NIP-44 version: {raw[0]}")
    nonce = raw[1:33]
    mac = raw[-32:]
    ct = raw[33:-32]
    chacha_key, chacha_nonce, hmac_key = _derive_keys(conversation_key, nonce)
    expected_mac = hmac.new(hmac_key, nonce + ct, sha256).digest()
    if not hmac.compare_digest(mac, expected_mac):
        raise ValueError("MAC verification failed")
    cipher = Cipher(
        algorithms.ChaCha20(chacha_key, b"\x00" * 4 + chacha_nonce), mode=None
    ).decryptor()
    padded = cipher.update(ct) + cipher.finalize()
    return _unpad(padded).decode("utf-8")
