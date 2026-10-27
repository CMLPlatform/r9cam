"""Print one version's CHANGELOG.md section, for the GitHub release notes.

The section is cut out on its own, so the link definitions it uses, which sit at the
bottom of the file, are appended. Without them GitHub shows `[#45]` as literal text.

Usage: python scripts/release_notes.py <version> < CHANGELOG.md
"""

import re
import sys


def release_notes(changelog: str, version: str) -> str:
    """Return the body of the `## [version]` section plus the link definitions it uses."""
    section = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", changelog, re.MULTILINE | re.DOTALL)
    if section is None:
        return ""
    body = section.group(1)
    # Reference definitions at the file's end, e.g. "[#45]: https://..." (mdformat lowercases labels).
    definitions = {label.lower(): url for label, url in re.findall(r"^\[([^\]]+)\]: (\S+)$", changelog, re.MULTILINE)}
    used = dict.fromkeys(label for label in re.findall(r"\[([^\]]+)\]", body) if label.lower() in definitions)
    links = "".join(f"[{label}]: {definitions[label.lower()]}\n" for label in used)
    # The oldest section runs to the end of the file and so holds every definition: keep only the used ones.
    body = re.sub(r"^\[[^\]]+\]: \S+\n?", "", body, flags=re.MULTILINE).strip()
    return f"{body}\n\n{links}" if links else f"{body}\n"


def main() -> int:
    """Print the notes for argv[1], or fail when CHANGELOG.md has no such section."""
    notes = release_notes(sys.stdin.read(), sys.argv[1])
    if not notes.strip():
        sys.stderr.write(f"CHANGELOG.md has no [{sys.argv[1]}] section\n")
        return 1
    sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
