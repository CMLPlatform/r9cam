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


# NOTE: the RELAB_CREDENTIALS_FILE and ~/.config/relab fallbacks below exist so v0.6
# installs keep their pairing. Remove them once no v0.6 Pis remain: the backend stops
# accepting their relay token audience on 2027-01-31.


def _get_credentials_file() -> Path:
    """Return the path to the relay credentials file.

    Respects ``R9CAM_CREDENTIALS_FILE`` if set, then the old ``RELAB_CREDENTIALS_FILE``;
    otherwise falls back to ``~/.config/r9cam/relay_credentials.json`` (XDG-style).
    """
    if env_path := os.getenv("R9CAM_CREDENTIALS_FILE"):
        return Path(env_path)
    if env_path := os.getenv("RELAB_CREDENTIALS_FILE"):
        logger.warning("RELAB_CREDENTIALS_FILE is deprecated; rename it to R9CAM_CREDENTIALS_FILE")
        return Path(env_path)
    return Path.home() / ".config" / "r9cam" / "relay_credentials.json"


_CREDENTIALS_FILE = _get_credentials_file()


def _legacy_credentials_file() -> Path | None:
    """Return the v0.6 default file, which applies only while the new default path is in use."""
    home = Path.home()
    if home / ".config" / "r9cam" / "relay_credentials.json" != _CREDENTIALS_FILE:
        return None
    return home / ".config" / "relab" / "relay_credentials.json"


def _file_to_read() -> Path:
    """Return the file to read: the v0.6 file until the new one exists, else the new one."""
    legacy = _legacy_credentials_file()
    if legacy is not None and not _CREDENTIALS_FILE.exists() and legacy.exists():
        return legacy
    return _CREDENTIALS_FILE


def merge_into_credentials_file(fields: dict[str, object]) -> None:
    """Merge ``fields`` into the credentials file and write it atomically.

    Other fields are kept. When the content came from the v0.6 file, that file is
    removed once the new one is written, so its private key does not linger.
    """
    source = _file_to_read()
    existing: dict[str, object] = {}
    if source.exists():
        with suppress(json.JSONDecodeError, OSError):
            loaded = json.loads(source.read_text())
            if isinstance(loaded, dict):
                existing = loaded
    existing.update(fields)
    write_json_atomic(_CREDENTIALS_FILE, existing)
    if source != _CREDENTIALS_FILE:
        try:
            source.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to delete old credentials file %s: %s", source, exc)


def save_relay_credentials(
    relay_backend_url: str,
    camera_id: str,
    relay_auth_scheme: str,
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
            "relay_auth_scheme": relay_auth_scheme,
            "relay_key_id": key_id,
            "relay_private_key_pem": private_key_pem,
        }
    )
    logger.info("Relay credentials saved to %s", _CREDENTIALS_FILE)


def load_relay_credentials() -> dict[str, str | bool] | None:
    """Load relay credentials from the JSON file, if it exists."""
    path = _file_to_read()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read %s", path)
        return None


def delete_relay_credentials() -> None:
    """Remove the relay fields from disk, and the v0.6 file, but keep ``local_api_key``.

    LAN clients hold the local key, so unpairing must not rotate it on the next start.
    """
    creds = load_relay_credentials()
    kept: dict[str, object] = (
        {k: v for k, v in creds.items() if not k.startswith("relay_")} if isinstance(creds, dict) else {}
    )
    for path in (_CREDENTIALS_FILE, _legacy_credentials_file()):
        if path is None:
            continue
        try:
            path.unlink(missing_ok=True)
            logger.info("Relay credentials deleted from %s", path)
        except OSError as exc:
            logger.warning("Failed to delete relay credentials file: %s", exc)
    if kept:
        try:
            write_json_atomic(_CREDENTIALS_FILE, kept)
        except OSError as exc:
            logger.warning("Failed to keep the local API key in %s: %s", _CREDENTIALS_FILE, exc)
