"""Unit tests for the server launcher."""

from pathlib import Path
from typing import Any

import pytest

from app import serve
from app.core.settings import Settings
from tests.fakes import write_self_signed_cert


def _run_kwargs(monkeypatch: pytest.MonkeyPatch, app_settings: Settings) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(serve, "settings", app_settings)
    monkeypatch.setattr(serve.uvicorn, "run", lambda *_args, **kwargs: calls.append(kwargs))
    serve.main()
    return calls[0]


def test_plain_http_without_tls_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without TLS files uvicorn gets no certificate, as with the old ``fastapi run``."""
    kwargs = _run_kwargs(monkeypatch, Settings())
    assert kwargs["ssl_certfile"] is None
    assert kwargs["ssl_keyfile"] is None
    assert kwargs["forwarded_allow_ips"] == "127.0.0.1,::1"


def test_https_with_tls_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """With both TLS files uvicorn serves HTTPS with them."""
    cert, key = write_self_signed_cert(tmp_path)
    kwargs = _run_kwargs(monkeypatch, Settings(tls_cert_file=str(cert), tls_key_file=str(key)))
    assert kwargs["ssl_certfile"] == str(cert)
    assert kwargs["ssl_keyfile"] == str(key)
