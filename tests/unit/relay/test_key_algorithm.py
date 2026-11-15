"""Device-key algorithm agility: ES256 and EdDSA keys, from pairing to a signed token."""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from jwt.algorithms import ECAlgorithm, OKPAlgorithm
from pydantic import ValidationError

from app.core.runtime import AppRuntime, set_active_runtime
from app.core.settings import settings
from app.pairing.services import credentials as pairing_credentials
from app.pairing.services import service as pairing_mod
from app.relay.credentials import load_relay_signing_private_key, relay_signing_algorithm
from app.relay.device_jwt import DEVICE_ASSERTION_AUDIENCE, build_device_assertion
from r9cam_models import DevicePublicKeyJWK

if TYPE_CHECKING:
    from pathlib import Path

_KEY_ID = "cam-key-agility"
_CASES = [("ES256", "EC", "P-256"), ("EdDSA", "OKP", "Ed25519")]


def _generate(monkeypatch: pytest.MonkeyPatch, algorithm: str) -> pairing_mod.RelaySigningKey:
    monkeypatch.setattr(settings, "device_key_algorithm", algorithm)
    return pairing_mod._generate_private_key()


@pytest.mark.parametrize(("algorithm", "kty", "crv"), _CASES)
def test_pairing_key_and_jwk_follow_the_setting(
    monkeypatch: pytest.MonkeyPatch, algorithm: str, kty: str, crv: str
) -> None:
    """The setting picks the key type; the JWK validates as the matching model shape."""
    key = _generate(monkeypatch, algorithm)
    assert relay_signing_algorithm(key) == algorithm
    assert isinstance(key, ed25519.Ed25519PrivateKey if algorithm == "EdDSA" else ec.EllipticCurvePrivateKey)
    jwk = pairing_mod._public_jwk(key, _KEY_ID)
    assert (jwk["kty"], jwk["crv"]) == (kty, crv)
    assert ("y" in jwk) == (kty == "EC")
    assert DevicePublicKeyJWK.model_validate(jwk).kid == _KEY_ID


def test_es256_jwk_is_unchanged_from_before_agility(monkeypatch: pytest.MonkeyPatch) -> None:
    """Older backends forbid unknown JWK members, so the default JWK carries no ``alg``."""
    jwk = pairing_mod._public_jwk(_generate(monkeypatch, "ES256"), _KEY_ID)
    assert set(jwk) == {"kty", "crv", "x", "y", "kid"}


@pytest.mark.parametrize("algorithm", ["ES256", "EdDSA"])
def test_token_round_trip_verifies_against_the_registered_jwk(monkeypatch: pytest.MonkeyPatch, algorithm: str) -> None:
    """The token names the stored key's algorithm and verifies with the JWK sent at pairing."""
    key = _generate(monkeypatch, algorithm)
    jwk = pairing_mod._public_jwk(key, _KEY_ID)
    monkeypatch.setattr(settings, "device_key_algorithm", "ES256" if algorithm == "EdDSA" else "EdDSA")
    runtime = AppRuntime()
    runtime.runtime_state.set_relay_credentials(
        relay_backend_url="wss://backend.example/ws",
        relay_camera_id="cam-1",
        relay_key_id=_KEY_ID,
        relay_private_key_pem=pairing_mod._private_key_pem(key),
    )
    set_active_runtime(runtime)
    try:
        token = build_device_assertion()
    finally:
        set_active_runtime(None)
    assert jwt.get_unverified_header(token)["alg"] == algorithm
    public = (OKPAlgorithm if algorithm == "EdDSA" else ECAlgorithm).from_jwk(json.dumps(jwk))
    claims = jwt.decode(token, cast("Any", public), algorithms=[algorithm], audience=DEVICE_ASSERTION_AUDIENCE)
    assert claims["iss"] == "camera:cam-1"


def test_credentials_file_without_algorithm_still_loads_as_es256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file saved before agility holds only a P-256 PEM and keeps signing ES256."""
    path = tmp_path / "relay_credentials.json"
    monkeypatch.setattr(pairing_credentials, "_CREDENTIALS_FILE", path)
    monkeypatch.setattr(settings, "device_key_algorithm", "EdDSA")  # must not matter
    pem = pairing_mod._private_key_pem(ec.generate_private_key(ec.SECP256R1()))
    pairing_credentials.save_relay_credentials("wss://backend.example/ws", "cam-1", _KEY_ID, pem)
    creds = pairing_credentials.load_relay_credentials()
    assert creds is not None
    assert "algorithm" not in json.dumps(creds)
    assert relay_signing_algorithm(load_relay_signing_private_key(str(creds["relay_private_key_pem"]))) == "ES256"


def test_other_curves_still_rejected() -> None:
    """Agility adds Ed25519 only; P-384 stays out."""
    pem = pairing_mod._private_key_pem(ec.generate_private_key(ec.SECP384R1()))
    with pytest.raises(ValueError, match="P-256 or Ed25519"):
        load_relay_signing_private_key(pem)


_X43 = base64.urlsafe_b64encode(bytes(32)).rstrip(b"=").decode()


@pytest.mark.parametrize(
    "jwk",
    [
        {"kty": "OKP", "crv": "Ed25519", "x": _X43},
        {"kty": "OKP", "crv": "Ed25519", "x": _X43, "alg": "EdDSA", "kid": "k"},
        {"kty": "EC", "crv": "P-256", "x": _X43, "y": _X43},
        {"kty": "EC", "crv": "P-256", "x": _X43, "y": _X43, "alg": "ES256"},
    ],
)
def test_models_accept_both_jwk_shapes(jwk: dict[str, str]) -> None:
    """Both the EC P-256 and the OKP Ed25519 shapes validate."""
    assert DevicePublicKeyJWK.model_validate(jwk)


@pytest.mark.parametrize(
    "jwk",
    [
        {"kty": "OKP", "crv": "P-256", "x": _X43},
        {"kty": "EC", "crv": "Ed25519", "x": _X43, "y": _X43},
        {"kty": "OKP", "crv": "Ed25519", "x": _X43, "y": _X43},  # OKP has no y
        {"kty": "EC", "crv": "P-256", "x": _X43},  # EC needs y
        {"kty": "OKP", "crv": "Ed25519", "x": _X43, "alg": "ES256"},
        {"kty": "EC", "crv": "P-256", "x": _X43, "y": _X43, "alg": "EdDSA"},
        {"kty": "OKP", "crv": "Ed25519", "x": "short"},
        {"kty": "RSA", "crv": "P-256", "x": _X43, "y": _X43},
        {"kty": "OKP", "crv": "Ed448", "x": _X43},
    ],
)
def test_models_reject_malformed_jwks(jwk: dict[str, str]) -> None:
    """Mismatched kty/crv/alg, a missing or extra y, and bad coordinates fail."""
    with pytest.raises(ValidationError):
        DevicePublicKeyJWK.model_validate(jwk)
