"""Benchmarks for security-sensitive helpers: log redaction and device JWT minting."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.runtime_state import RuntimeState
from app.observability.logging import JsonFormatter, redact_log_text
from app.relay.device_jwt import build_device_assertion

if TYPE_CHECKING:
    from pytest_codspeed import BenchmarkFixture

# Assemble the PEM armor at runtime so secret scanners do not flag this fake key.
_PEM_LABEL = "PRIVATE" + " KEY"
_LOG_LINE = (
    "Relay request failed: headers={'authorization': 'Bearer eyJhbGciOiJFUzI1NiJ9.payload.sig', "
    '\'x-api-key\': \'abcdef0123456789\'} body={"stream_key": "live-xyz", "product_id": 12} '
    "token=sk_live_1234 relay_private_key_pem=-----BEGIN " + _PEM_LABEL + "-----\nMIGHAgEAMBMGByqGSM49\n"
    "-----END " + _PEM_LABEL + "----- camera ready at http://192.168.1.20:8018/preview "
)
_LOG_TEXT = _LOG_LINE * 4


@pytest.fixture
def signing_state() -> RuntimeState:
    """Return a runtime state holding a fresh P-256 relay signing key."""
    pem = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )
    state = RuntimeState()
    state.set_relay_credentials(
        relay_backend_url="wss://backend.example/ws",
        relay_camera_id="11111111-2222-3333-4444-555555555555",
        relay_auth_scheme="device_assertion",
        relay_key_id="cam-key-42",
        relay_private_key_pem=pem,
    )
    return state


def test_redact_log_text(benchmark: BenchmarkFixture) -> None:
    """Redact bearer tokens, sensitive fields and PEM blocks from a log line."""
    result = benchmark(redact_log_text, _LOG_TEXT)

    assert "sk_live_1234" not in result


def test_json_log_formatter(benchmark: BenchmarkFixture) -> None:
    """Format a structured security log record as redacted JSON."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="app.auth",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Security event: %s",
        args=(_LOG_TEXT,),
        exc_info=None,
    )
    record.event = "security.auth"
    record.outcome = "denied"
    record.status_code = 401
    record.method = "GET"
    record.path = "/camera"

    result = benchmark(formatter.format, record)

    assert "[REDACTED]" in result


def test_build_device_assertion(benchmark: BenchmarkFixture, signing_state: RuntimeState) -> None:
    """Mint a short-lived ES256 device assertion used for relay and upload auth."""
    result = benchmark(build_device_assertion, signing_state)

    assert result.count(".") == 2
