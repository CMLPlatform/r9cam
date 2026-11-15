"""On-disk relay credentials file I/O.

Extracted from ``service.py`` so ``app.core.bootstrap`` can import the
credentials loader without pulling in the pairing orchestration module
(which in turn needs bootstrap helpers) — breaking the previous
startup-time import cycle.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import suppress
from pathlib import Path

from app.utils.files import write_json_atomic

logger = logging.getLogger(__name__)


def _get_credentials_file() -> Path:
    """Return ``R9CAM_CREDENTIALS_FILE``, else ``~/.config/r9cam/relay_credentials.json``."""
    if env_path := os.getenv("R9CAM_CREDENTIALS_FILE"):
        return Path(env_path)
    return Path.home() / ".config" / "r9cam" / "relay_credentials.json"


_CREDENTIALS_FILE = _get_credentials_file()


def merge_into_credentials_file(fields: dict[str, object]) -> None:
    """Merge ``fields`` into the credentials file and write it atomically; other fields are kept."""
    existing: dict[str, object] = {}
    if _CREDENTIALS_FILE.exists():
        with suppress(json.JSONDecodeError, OSError):
            loaded = json.loads(_CREDENTIALS_FILE.read_text())
            if isinstance(loaded, dict):
                existing = loaded
    existing.update(fields)
    write_json_atomic(_CREDENTIALS_FILE, existing)


def save_relay_credentials(
    relay_backend_url: str,
    camera_id: str,
    key_id: str,
    private_key_pem: str,
) -> None:
    """Persist relay credentials atomically to the JSON credentials file.

    Merges into any existing content, preserving ``local_api_key`` and other fields.
    """
    merge_into_credentials_file(
        {
            "relay_backend_url": relay_backend_url,
            "relay_camera_id": camera_id,
            "relay_key_id": key_id,
            "relay_private_key_pem": private_key_pem,
        }
    )
    logger.info("Relay credentials saved to %s", _CREDENTIALS_FILE)


def load_relay_credentials() -> dict[str, str | bool] | None:
    """Load relay credentials from the JSON file, if it exists."""
    if not _CREDENTIALS_FILE.exists():
        return None
    try:
        return json.loads(_CREDENTIALS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read %s", _CREDENTIALS_FILE)
        return None


def delete_relay_credentials() -> None:
    """Remove the relay fields from disk but keep ``local_api_key``.

    LAN clients hold the local key, so unpairing must not rotate it on the next start.
    """
    creds = load_relay_credentials()
    kept: dict[str, object] = (
        {k: v for k, v in creds.items() if not k.startswith("relay_")} if isinstance(creds, dict) else {}
    )
    try:
        _CREDENTIALS_FILE.unlink(missing_ok=True)
        logger.info("Relay credentials deleted from %s", _CREDENTIALS_FILE)
    except OSError as exc:
        logger.warning("Failed to delete relay credentials file: %s", exc)
    if kept:
        try:
            write_json_atomic(_CREDENTIALS_FILE, kept)
        except OSError as exc:
            logger.warning("Failed to keep the local API key in %s: %s", _CREDENTIALS_FILE, exc)
