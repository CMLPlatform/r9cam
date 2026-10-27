set dotenv-load := true

default:
    @just --list

install:
    uv sync --all-groups

dev:
    uv run fastapi dev

test:
    uv run pytest --cov=app --cov=r9cam_models --cov-report=term-missing

test-unit:
    uv run pytest tests/unit

test-integration:
    uv run pytest tests/integration

test-slowest:
    uv run pytest --durations=20 -q

bench:
    uv run pytest tests/benchmarks --codspeed

# Mutation-test the relay seam and the upload queue. Survivors land in reports/mutation/.
mutation:
    rm -rf .mutation
    mkdir -p .mutation/src reports/mutation
    cp -r app scripts tests typings pyproject.toml uv.lock .mutation/
    cp -r r9cam_models/src/r9cam_models .mutation/src/
    cd .mutation && uv run --project .. mutmut run --max-children "$(nproc)"
    cd .mutation && uv run --project .. mutmut results | grep -E ': (survived|no tests)$' | sed 's/^ *//; s/: .*//' | LC_ALL=C sort > ../reports/mutation/survivors.txt
    @echo "Survivors and untested: $(wc -l < reports/mutation/survivors.txt)"
    @echo "Survivor counts per function that differ from tests/mutation-baseline.txt (< baseline, > this run):"
    @sed 's/ *#.*//; /^$/d; s/__mutmut_[0-9]*$//' tests/mutation-baseline.txt | uniq -c > .mutation/baseline-counts.txt
    @sed 's/__mutmut_[0-9]*$//' reports/mutation/survivors.txt | uniq -c | diff .mutation/baseline-counts.txt -

typecheck:
    uv run ty check .

lint:
    uv run ruff check --no-fix .
    just typecheck

format:
    uv run ruff check --fix .
    uv run ruff format .

openapi:
    uv run python -m scripts.export_openapi

openapi-check:
    uv run python -m scripts.export_openapi --check

prek:
    uv run prek run --all-files

check:
    just lint
    just test

audit:
    uv audit --preview-features audit --locked --no-dev

build:
    uv build

clean:
    rm -rf dist/ .venv/ .pytest_cache/ __pycache__/ .mutation/ reports/

# Print the local direct-connection API key from the local key endpoint.
show-key:
    @python3 -c 'import sys; from urllib.request import urlopen; sys.stdout.write(urlopen("http://127.0.0.1:8018/local-key", timeout=2).read().decode("utf-8", "replace").strip() + "\n")'

# Branch release/vX.Y.Z off origin/main and make the bump commit: the version files,
# uv.lock, CHANGELOG.md and the release dates. No tag: the Release workflow tags the
# merged commit.
release-prep:
    #!/usr/bin/env bash
    set -euo pipefail
    [[ -z "$(git status --porcelain)" ]] || { echo "the working tree has changes; commit or stash them first" >&2; exit 1; }
    git fetch --quiet origin main --tags
    git switch --quiet --detach origin/main
    previous="$(uv version --short)"
    # commitizen exits 3 when there are no commits since the last tag and 21 when none of them bump the version.
    code=0
    next="$(uv run cz bump --get-next)" || code=$?
    if [[ $code -eq 3 || $code -eq 21 ]]; then
        git switch --quiet -
        echo "No commits since v$previous that call for a release; nothing to do."
        exit 0
    fi
    [[ $code -eq 0 ]] || { git switch --quiet -; exit "$code"; }
    git switch --quiet --create "release/v$next"
    uv run cz bump --yes --version-files-only
    today="$(date +%F)"
    sed -i -E "s/^date-released: .*/date-released: $today/" CITATION.cff
    sed -i -E "s/(\"datePublished\": )\"[^\"]*\"/\1\"$today\"/" codemeta.json
    git add pyproject.toml app/__version__.py openapi.r9cam.json CITATION.cff codemeta.json CHANGELOG.md uv.lock
    git commit --quiet --signoff -m "bump: version $previous → $next"
    git log --oneline -1
    echo "Next:"
    echo "  1. git push -u origin release/v$next and open a pull request."
    echo "  2. After it merges, run the Release workflow on main: gh workflow run release.yml --ref main"
