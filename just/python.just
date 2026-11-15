# Install the venv, writing uv.lock if it is missing or stale. CI uses --locked.
py-sync:
    uv sync

# What CI runs: lint, format check, types, tests, dependency audit and licenses.
py-check:
    uv run --locked ruff check
    uv run --locked ruff format --check
    uv run --locked ty check
    uv run --locked pytest
    uv audit --locked --preview-features audit-command
    d=$(mktemp -d) && trap 'rm -rf "$d"' EXIT && uv export --locked --no-default-groups --no-hashes --no-annotate --no-header --no-emit-project --no-emit-workspace -q -o "$d/requirements.txt" && { test ! -s "$d/requirements.txt" || uv run --locked --with licensecheck==2026.0.8 licensecheck --license AGPL -r "$d/requirements.txt" --zero; }

# Fix what ruff can fix, then format.
py-fmt:
    uv run ruff check --fix
    uv run ruff format

# Tests with a coverage summary.
py-cov:
    uv run pytest --cov --cov-report=term-missing

# Tests only; extra arguments reach pytest (`just py-test -k name`).
py-test *args:
    uv run pytest {{ args }}
