"""Optional Ed25519 signatures for evidence bundles (`pip install taskwitness[sign]`).

The SHA-256 digests inside a bundle detect edits, but anyone can recompute them.
A signature additionally binds the bundle to a key, so a lab can show a result
came from its own rig and was not altered afterwards.

What a signature does NOT prove: that the verdict is right, that the sensors
were honest, or that the key belongs to who you think. Distribute public keys
out of band and pin the one you trust with `trusted_public_key`.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

from taskwitness.core import TaskWitnessError, canonical_json, verify_bundle_integrity

SIGNATURE_SCHEMA = "taskwitness.signature/v0"


class SigningError(TaskWitnessError):
    """Raised for signing setup problems or malformed signature documents."""


def _crypto():
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError:  # pragma: no cover - exercised only without the extra
        raise SigningError("signing needs the 'cryptography' package: pip install 'taskwitness[sign]'") from None
    return InvalidSignature, serialization, Ed25519PrivateKey, Ed25519PublicKey


def _raw_public(public_key) -> bytes:
    _, serialization, _, _ = _crypto()
    return public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(raw_public: bytes) -> str:
    return hashlib.sha256(raw_public).hexdigest()[:16]


def generate_keypair(directory: str | Path, name: str = "taskwitness") -> tuple[Path, Path]:
    """Write `<name>.key` (private, mode 0600) and `<name>.pub` (public) PEM files."""
    _, serialization, Ed25519PrivateKey, _ = _crypto()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    private_path, public_path = directory / f"{name}.key", directory / f"{name}.pub"
    if private_path.exists():
        raise SigningError(f"{private_path} already exists; refusing to overwrite a key")
    key = Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    private_path.touch(mode=0o600)
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    return private_path, public_path


def _load_private(pem: bytes):
    _, serialization, Ed25519PrivateKey, _ = _crypto()
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError) as exc:
        raise SigningError(f"cannot read private key: {exc}") from None
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningError("private key is not an Ed25519 key")
    return key


def load_public(pem: bytes):
    _, serialization, _, Ed25519PublicKey = _crypto()
    try:
        key = serialization.load_pem_public_key(pem)
    except (ValueError, TypeError) as exc:
        raise SigningError(f"cannot read public key: {exc}") from None
    if not isinstance(key, Ed25519PublicKey):
        raise SigningError("public key is not an Ed25519 key")
    return key


def sign_bundle(bundle: dict[str, Any], private_pem: bytes) -> dict[str, Any]:
    if not verify_bundle_integrity(bundle):
        raise SigningError("refusing to sign a bundle whose integrity digests do not match")
    key = _load_private(private_pem)
    raw_public = _raw_public(key.public_key())
    return {
        "schema": SIGNATURE_SCHEMA,
        "algorithm": "ed25519",
        "episode_id": bundle["episode_id"],
        "bundle_sha256": bundle["integrity"]["bundle_sha256"],
        "evidence_sha256": bundle["integrity"]["evidence_sha256"],
        "key_id": key_id(raw_public),
        "public_key": base64.b64encode(raw_public).decode("ascii"),
        "signature": base64.b64encode(key.sign(canonical_json(bundle))).decode("ascii"),
    }


def verify_signature(bundle: dict[str, Any], signature: dict[str, Any], trusted_public_pem: bytes | None = None) -> dict[str, Any]:
    """Return {"ok": bool, "key_id": ..., "reason": ...}. Never raises on a bad signature."""
    InvalidSignature, _, _, Ed25519PublicKey = _crypto()
    if not isinstance(signature, dict) or signature.get("schema") != SIGNATURE_SCHEMA or signature.get("algorithm") != "ed25519":
        raise SigningError(f"not a {SIGNATURE_SCHEMA} ed25519 document")
    try:
        raw_public = base64.b64decode(signature["public_key"], validate=True)
        sig = base64.b64decode(signature["signature"], validate=True)
        public = Ed25519PublicKey.from_public_bytes(raw_public)
    except (KeyError, ValueError) as exc:
        raise SigningError(f"malformed signature document: {exc}") from None
    kid = key_id(raw_public)
    if not verify_bundle_integrity(bundle):
        return {"ok": False, "key_id": kid, "reason": "bundle digests do not match its content"}
    if signature.get("bundle_sha256") != bundle["integrity"]["bundle_sha256"]:
        return {"ok": False, "key_id": kid, "reason": "signature is for a different bundle"}
    if trusted_public_pem is not None and _raw_public(load_public(trusted_public_pem)) != raw_public:
        return {"ok": False, "key_id": kid, "reason": "signed with a key other than the trusted one"}
    try:
        public.verify(sig, canonical_json(bundle))
    except InvalidSignature:
        return {"ok": False, "key_id": kid, "reason": "signature does not verify"}
    trust = "trusted key" if trusted_public_pem is not None else "embedded key (not pinned; pass a trusted public key)"
    return {"ok": True, "key_id": kid, "reason": f"valid signature by {trust}"}
