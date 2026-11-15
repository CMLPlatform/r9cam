"""Tests for the relay credentials file."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.core import bootstrap
from app.pairing.services import credentials as pairing_credentials

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_delete_keeps_the_local_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unpairing drops the relay keys but keeps the LAN key, so direct clients keep access after a restart."""
    path = tmp_path / "relay_credentials.json"
    monkeypatch.setattr(pairing_credentials, "_CREDENTIALS_FILE", path)
    monkeypatch.setattr(bootstrap, "_CREDENTIALS_FILE", path)
    pairing_credentials.save_relay_credentials("https://api.example", "cam-1", "key-1", "pem")
    bootstrap._persist_local_api_key("lan-key")

    pairing_credentials.delete_relay_credentials()

    assert json.loads(path.read_text()) == {"local_api_key": "lan-key"}
