from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from coincurve import PrivateKey, PublicKeyXOnly


@dataclass(frozen=True)
class Identity:
    _priv: PrivateKey

    @property
    def pubkey_bytes(self) -> bytes:
        # BIP-340 x-only: 32 bytes
        return self._priv.public_key_xonly.format()

    @property
    def pubkey_hex(self) -> str:
        return self.pubkey_bytes.hex()

    def sign_schnorr(self, message_32: bytes) -> bytes:
        assert len(message_32) == 32
        return self._priv.sign_schnorr(message_32)

    @staticmethod
    def verify_schnorr(message_32: bytes, sig: bytes, pubkey_xonly_32: bytes) -> bool:
        try:
            pk = PublicKeyXOnly(pubkey_xonly_32)
            return pk.verify(sig, message_32)
        except Exception:
            return False

    def ecdh_x(self, peer_pubkey_xonly_32: bytes) -> bytes:
        """NIP-44 ECDH: return the x-coordinate of priv * peer_pub as raw 32 bytes."""
        from coincurve import PublicKey
        full_compressed = b"\x02" + peer_pubkey_xonly_32
        peer = PublicKey(full_compressed)
        shared_point = peer.multiply(self._priv.secret)
        return shared_point.format(compressed=True)[1:]


def load_or_create(key_path: Path) -> Identity:
    key_path = Path(key_path)
    if key_path.exists():
        mode = stat.S_IMODE(key_path.stat().st_mode)
        if mode != 0o600:
            raise PermissionError(
                f"{key_path} has mode {oct(mode)}; expected 0o600. "
                f"Run: chmod 600 {key_path}"
            )
        st = key_path.stat()
        if st.st_uid != os.getuid():
            raise PermissionError(f"{key_path} is owned by uid {st.st_uid}, not current user")
        secret = key_path.read_bytes()
        return Identity(PrivateKey(secret))

    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    priv = PrivateKey()
    fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, priv.secret)
    finally:
        os.close(fd)
    return Identity(priv)
