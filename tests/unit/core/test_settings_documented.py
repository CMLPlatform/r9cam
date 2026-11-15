"""Every operator-facing setting is named in .env.example or INSTALL.md."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.settings import Settings

ROOT = Path(__file__).resolve().parents[3]

# Settings left out of the docs on purpose, with the reason.
INTERNAL = {
    "camera_backend": "only picamera2 exists; the field is removed in a later release",
    "relay_auth_scheme": "only device_assertion exists; the field is removed in a later release",
    "templates_path": "packaged app assets, not an operator choice",
    "static_path": "packaged app assets, not an operator choice",
}


def _documented_text() -> str:
    return (ROOT / ".env.example").read_text() + (ROOT / "INSTALL.md").read_text()


@pytest.mark.parametrize("field", sorted(set(Settings.model_fields) - set(INTERNAL)))
def test_setting_is_documented(field: str) -> None:
    """The upper-cased env name appears in .env.example or INSTALL.md."""
    name = field.upper()
    assert re.search(rf"\b{name}\b", _documented_text()), f"{name} is not in .env.example or INSTALL.md"


def test_allowlist_names_real_fields() -> None:
    """A renamed or removed field must leave the allowlist too."""
    assert set(INTERNAL) <= set(Settings.model_fields)


def test_key_reader_prints_local_api_key(tmp_path: Path) -> None:
    """The justfile's key reader prints the key from the credentials file and nothing else."""
    creds = tmp_path / "creds.json"
    creds.write_text('{"local_api_key": "local_abc"}')
    just = shutil.which("just")
    if just is None:
        pytest.skip("just is not installed")
    reader = subprocess.run(  # noqa: S603
        [just, "--evaluate", "key_reader"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", reader],
        env={"R9CAM_CREDENTIALS_FILE": str(creds)},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out == "local_abc\n"
