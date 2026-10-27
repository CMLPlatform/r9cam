"""Tests for reading the credentials file that v0.6 installs left behind."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import pytest

from app.core import bootstrap
from app.pairing.services import credentials as pairing_credentials

if TYPE_CHECKING:
    from pathlib import Path

LEGACY_CREDENTIALS = {"relay_camera_id": "cam-old", "relay_private_key_pem": "old-pem", "local_api_key": "old-key"}


@pytest.fixture
def legacy_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Point HOME at tmp_path with only a v0.6 credentials file; return (new, legacy) paths."""
    monkeypatch.setenv("HOME", str(tmp_path))
    new = tmp_path / ".config" / "r9cam" / "relay_credentials.json"
    legacy = tmp_path / ".config" / "relab" / "relay_credentials.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps(LEGACY_CREDENTIALS))
    monkeypatch.setattr(pairing_credentials, "_CREDENTIALS_FILE", new)
    monkeypatch.setattr(bootstrap, "_CREDENTIALS_FILE", new)
    return new, legacy


def test_old_env_var_is_used_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """RELAB_CREDENTIALS_FILE still points at the file when R9CAM_CREDENTIALS_FILE is unset."""
    old = tmp_path / "relay.json"
    monkeypatch.delenv("R9CAM_CREDENTIALS_FILE", raising=False)
    monkeypatch.setenv("RELAB_CREDENTIALS_FILE", str(old))

    with caplog.at_level(logging.WARNING):
        assert pairing_credentials._get_credentials_file() == old
    assert "R9CAM_CREDENTIALS_FILE" in caplog.text


@pytest.mark.usefixtures("legacy_home")
def test_load_reads_the_old_default_file() -> None:
    """Without a file at the new default path, the v0.6 file is read."""
    assert pairing_credentials.load_relay_credentials() == LEGACY_CREDENTIALS


def test_save_moves_the_old_file_to_the_new_path(legacy_home: tuple[Path, Path]) -> None:
    """A save keeps the old fields, writes the new path and removes the old file with its key."""
    new, legacy = legacy_home

    pairing_credentials.save_relay_credentials("https://api.example", "cam-new", "device_assertion", "key-1", "new-pem")

    saved = json.loads(new.read_text())
    assert saved["local_api_key"] == "old-key"
    assert saved["relay_camera_id"] == "cam-new"
    assert not legacy.exists()


def test_persisting_the_local_key_keeps_the_old_pairing(legacy_home: tuple[Path, Path]) -> None:
    """The first write at startup carries the v0.6 relay credentials over."""
    new, legacy = legacy_home

    bootstrap._persist_local_api_key("new-key")

    assert json.loads(new.read_text()) == {**LEGACY_CREDENTIALS, "local_api_key": "new-key"}
    assert not legacy.exists()


def test_delete_removes_the_old_file_too(legacy_home: tuple[Path, Path]) -> None:
    """Unpairing must not leave the v0.6 file to be read again on the next start."""
    _, legacy = legacy_home

    pairing_credentials.delete_relay_credentials()

    assert not legacy.exists()
    assert pairing_credentials.load_relay_credentials() is None
