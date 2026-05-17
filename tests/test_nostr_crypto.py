import json
from pathlib import Path
import pytest
from agent_wormhole.nostr.crypto import (
    conversation_key,
    encrypt,
    decrypt,
    calc_padded_len,
)


VECTORS = json.loads((Path(__file__).parent / "nip44_vectors.json").read_text())["v2"]


def _pub_from_sec(sec_hex: str) -> bytes:
    from coincurve import PrivateKey
    return PrivateKey(bytes.fromhex(sec_hex)).public_key_xonly.format()


@pytest.mark.parametrize("v", VECTORS["valid"]["get_conversation_key"])
def test_conversation_key_matches_vector(v):
    ck = conversation_key(bytes.fromhex(v["sec1"]), bytes.fromhex(v["pub2"]))
    assert ck.hex() == v["conversation_key"]


@pytest.mark.parametrize("v", VECTORS["valid"]["encrypt_decrypt"])
def test_encrypt_matches_vector(v):
    ck = conversation_key(bytes.fromhex(v["sec1"]), _pub_from_sec(v["sec2"]))
    assert ck.hex() == v["conversation_key"]
    nonce = bytes.fromhex(v["nonce"])
    payload = encrypt(v["plaintext"], conversation_key=ck, nonce=nonce)
    assert payload == v["payload"]


@pytest.mark.parametrize("v", VECTORS["valid"]["encrypt_decrypt"])
def test_decrypt_matches_vector(v):
    ck = bytes.fromhex(v["conversation_key"])
    plaintext = decrypt(v["payload"], conversation_key=ck)
    assert plaintext == v["plaintext"]


@pytest.mark.parametrize("v", VECTORS["valid"]["calc_padded_len"])
def test_calc_padded_len_matches_vectors(v):
    unpadded, padded = v
    assert calc_padded_len(unpadded) == padded


def test_roundtrip_random_plaintext():
    import os
    ck = os.urandom(32)
    pt = "hello world " * 100
    payload = encrypt(pt, conversation_key=ck)
    assert decrypt(payload, conversation_key=ck) == pt


def test_decrypt_rejects_tampered_mac():
    import base64, os
    ck = os.urandom(32)
    payload = encrypt("hi", conversation_key=ck)
    raw = bytearray(base64.b64decode(payload))
    raw[-1] ^= 0x01  # flip a MAC bit
    bad = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(ValueError):
        decrypt(bad, conversation_key=ck)
