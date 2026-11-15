"""Relay credential validation helpers."""

from __future__ import annotations

import re

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

_SAFE_RELAY_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._~-]+$")
_MAX_RELAY_CAMERA_ID_LENGTH = 128
_MAX_RELAY_KEY_ID_LENGTH = 64
_RELAY_SIGNING_CURVE_NAME = "secp256r1"


def _validate_relay_identifier(value: str, *, field_name: str, max_length: int) -> None:
    """Validate relay identifiers before they are accepted as signing context."""
    if not value or len(value) > max_length or not _SAFE_RELAY_IDENTIFIER_PATTERN.fullmatch(value):
        msg = f"{field_name} must be 1-{max_length} URL-safe characters."
        raise ValueError(msg)


RelaySigningKey = ec.EllipticCurvePrivateKey | ed25519.Ed25519PrivateKey


def load_relay_signing_private_key(private_key_pem: str) -> RelaySigningKey:
    """Load and validate the relay device-assertion private key (EC P-256 or Ed25519)."""
    try:
        private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    except (TypeError, ValueError) as exc:
        msg = "relay_private_key_pem must contain a valid PEM private key."
        raise ValueError(msg) from exc
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        return private_key
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or private_key.curve.name != _RELAY_SIGNING_CURVE_NAME:
        msg = "relay_private_key_pem must be an EC P-256 or Ed25519 private key."
        raise ValueError(msg)
    return private_key


def relay_signing_algorithm(private_key: RelaySigningKey) -> str:
    """JOSE ``alg`` for a signing key: the stored key type decides, never a setting."""
    return "EdDSA" if isinstance(private_key, ed25519.Ed25519PrivateKey) else "ES256"


def validate_relay_credentials(
    *,
    relay_camera_id: str,
    relay_key_id: str,
    relay_private_key_pem: str,
) -> None:
    """Validate relay device-assertion credentials at process trust boundaries."""
    _validate_relay_identifier(
        relay_camera_id,
        field_name="relay_camera_id",
        max_length=_MAX_RELAY_CAMERA_ID_LENGTH,
    )
    _validate_relay_identifier(
        relay_key_id,
        field_name="relay_key_id",
        max_length=_MAX_RELAY_KEY_ID_LENGTH,
    )
    load_relay_signing_private_key(relay_private_key_pem)
