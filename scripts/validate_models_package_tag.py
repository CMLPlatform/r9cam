"""Validate a models package tag against the package version."""

import argparse
import sys
import tomllib
from pathlib import Path

PREFIX = "r9cam-models-v"
PYPROJECT = Path("r9cam_models/pyproject.toml")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag_name", help="The tag name that triggered publishing.")
    return parser.parse_args()


def main() -> int:
    """Validate that the tag suffix matches the package version."""
    args = parse_args()
    tag_name = args.tag_name
    if not tag_name.startswith(PREFIX):
        sys.stderr.write(f"Unexpected tag name: {tag_name}\n")
        return 1

    package_version = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    tag_version = tag_name.removeprefix(PREFIX)
    if tag_version != package_version:
        sys.stderr.write(
            f"Tag version {tag_version} does not match r9cam_models version {package_version}\n",
        )
        return 1

    sys.stdout.write(f"Validated {tag_name} against r9cam_models {package_version}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
