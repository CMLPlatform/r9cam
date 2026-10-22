"""Benchmark for the redacting JSON log formatter every log record passes through."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.observability.logging import JsonFormatter

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
