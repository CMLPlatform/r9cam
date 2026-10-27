set dotenv-load := true

default:
    @just --list

install:
    uv sync --all-groups --no-group fuzz

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
# A mutant-name pattern (just mutation "app.delivery.queue*") limits the run and skips the baseline diff, which only means something on a full run.
# A pattern run also keeps .mutation/, so mutants of unchanged files stay cached. `just clean` empties it.
mutation *ARGS:
    @if [ -z '{{ARGS}}' ]; then rm -rf .mutation; fi
    mkdir -p .mutation/src reports/mutation
    # -p keeps mtimes, so mutmut regenerates mutants only for changed files.
    cp -rp app scripts tests typings pyproject.toml uv.lock .mutation/
    cp -rp r9cam_models/src/r9cam_models .mutation/src/
    cd .mutation && uv run --project .. mutmut run --max-children "$(nproc)" {{ARGS}}
    cd .mutation && uv run --project .. mutmut results | grep -E ': (survived|no tests)$' | sed 's/^ *//; s/: .*//' | grep -E "^($(printf '%s' '{{ARGS}}' | sed 's/\*/.*/g; s/ /|/g; s/^$/./'))" | LC_ALL=C sort > ../reports/mutation/survivors.txt
    @echo "Survivors and untested: $(wc -l < reports/mutation/survivors.txt)"
    @if [ -z '{{ARGS}}' ]; then \
        echo "Survivor counts per function that differ from tests/mutation-baseline.txt (< baseline, > this run):"; \
        sed 's/ *#.*//; /^$/d; s/__mutmut_[0-9]*$//' tests/mutation-baseline.txt | uniq -c > .mutation/baseline-counts.txt; \
        sed 's/__mutmut_[0-9]*$//' reports/mutation/survivors.txt | uniq -c | diff .mutation/baseline-counts.txt -; \
    fi

# Fuzz the relay trust boundary. Flags go to libFuzzer, for example `just fuzz -runs=20000 -seed=1`.
fuzz *flags="-max_total_time=60":
    mkdir -p reports/fuzz
    uv run --group fuzz python fuzz/relay_frames.py -artifact_prefix=reports/fuzz/ {{flags}}

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

# Releases, as in r9lab:
#
#   just release-prep 0.7.0      branch release/v0.7.0 from origin/main, set every version
#                                file and turn CHANGELOG.md's Unreleased into [0.7.0]
#   (write the section, commit, open a PR and merge it)
#   just release-publish 0.7.0   sign and push the v0.7.0 tag, then draft the GitHub
#                                release from that CHANGELOG section
#
# Publishing the draft on GitHub starts release.yml, which uploads the wheel, the sdist
# and the SBOM.
release-prep version:
    #!/usr/bin/env bash
    set -euo pipefail
    version={{ quote(version) }}
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "expected a version like 0.7.0, got '$version'" >&2; exit 2; }
    [[ -z "$(git status --porcelain)" ]] || { echo "the working tree has changes; commit or stash them first" >&2; exit 1; }
    git fetch --quiet origin main --tags
    git switch --create "release/v$version" origin/main
    previous="$(git describe --tags --abbrev=0 --match 'v*' origin/main)"
    today="$(date +%F)"
    uv run cz bump --files-only --yes "$version"
    uv lock --quiet
    sed -i -E "s/^date-released: .*/date-released: $today/" CITATION.cff
    sed -i -E "s/(\"datePublished\": )\"[^\"]*\"/\1\"$today\"/" codemeta.json
    # Keep a Changelog: what accumulated under Unreleased becomes this version, under a
    # fresh, empty Unreleased, and the compare links move along.
    sed -i "0,/^## \[Unreleased\]$/s//## [Unreleased]\n\n## [$version] - $today/" CHANGELOG.md
    # mdformat lowercases and sorts the link labels, so match [unreleased] in either case.
    sed -i -E "s#^\[[Uu]nreleased\]: (.*)/compare/v[0-9.]+\.\.\.HEAD\$#[unreleased]: \1/compare/v$version...HEAD\n[$version]: \1/compare/$previous...v$version#" CHANGELOG.md
    grep -q "^\[$version\]: " CHANGELOG.md || { echo "CHANGELOG.md has no [unreleased] compare link to move" >&2; exit 1; }
    git status --short
    echo "Commits since $previous, to write the [$version] section from:"
    git log --format='  %s' "$previous..origin/main"
    echo "Write the [$version] section of CHANGELOG.md, then commit and open a PR."

# Sign and push the tag for a merged version, then draft its GitHub release from its
# CHANGELOG section.
release-publish version:
    #!/usr/bin/env bash
    set -euo pipefail
    version={{ quote(version) }}
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "expected a version like 0.7.0, got '$version'" >&2; exit 2; }
    git fetch --quiet origin main
    main_version="$(git show origin/main:pyproject.toml | python3 -c 'import sys, tomllib; print(tomllib.load(sys.stdin.buffer)["project"]["version"])')"
    [[ "$main_version" == "$version" ]] || {
        echo "origin/main is at $main_version, not $version: merge the release PR first" >&2
        exit 1
    }
    tag="v$version"
    ! git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null || { echo "tag $tag already exists locally" >&2; exit 1; }
    # ls-remote exits 2 when the tag is missing, 0 when it exists, anything else on an error.
    found=0
    git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null || found=$?
    [[ "$found" != 0 ]] || { echo "tag $tag already exists on origin" >&2; exit 1; }
    [[ "$found" == 2 ]] || { echo "could not list origin's tags" >&2; exit 1; }
    notes="$(git show origin/main:CHANGELOG.md | python3 scripts/release_notes.py "$version")"
    # Tag with your own key so GitHub shows it verified; a tag gh creates is unsigned.
    git tag --sign "$tag" --message "$tag" "$(git rev-parse origin/main)"
    git push origin "refs/tags/$tag"
    gh release create "$tag" --draft --verify-tag --title "$tag" --notes "$notes"
    echo "Review the draft, then publish it: that starts release.yml."
