# Recipes of this repo. `copier update` never touches this file.

install:
    uv sync --all-groups --no-group fuzz

dev:
    APP_ENV=development uv run fastapi dev

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

build:
    uv build

clean:
    rm -rf dist/ .venv/ .pytest_cache/ __pycache__/ .mutation/ reports/

# Python that prints local_api_key from the credentials file ($R9CAM_CREDENTIALS_FILE, else ~/.config/r9cam).
# The /local-key route needs the key itself, so the key is read from the file instead.
key_reader := "import json, os, pathlib; p = pathlib.Path(os.getenv('R9CAM_CREDENTIALS_FILE') or pathlib.Path.home() / '.config/r9cam/relay_credentials.json'); print(json.loads(p.read_text()).get('local_api_key', ''))"

# Print the local direct-connection API key from inside the Compose app container.
show-key:
    docker compose exec app python -c "{{ key_reader }}"

# Print the key for a direct Python run (no container).
show-key-direct:
    python3 -c "{{ key_reader }}"

# Releases, as in r9lab:
#
#   just release-prep 0.7.0      branch release/v0.7.0 from origin/main, set every version
#                                file and turn CHANGELOG.md's Unreleased into [0.7.0]
#   (write the section, commit, open a PR and merge it)
#   just release-publish 0.7.0   sign and push the v0.7.0 tag
#
# The tag starts release.yml, which drafts the GitHub release from that CHANGELOG section,
# uploads the wheel, the sdist and its SBOM, pushes the image, then publishes the release.

# Branch release/vX.Y.Z, set every version file and cut CHANGELOG's Unreleased section.
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
    # The Markdown formatter may lowercase link labels, so match [unreleased] in either case.
    sed -i -E "s#^\[[Uu]nreleased\]: (.*)/compare/v[0-9.]+\.\.\.HEAD\$#[unreleased]: \1/compare/v$version...HEAD\n[$version]: \1/compare/$previous...v$version#" CHANGELOG.md
    grep -q "^\[$version\]: " CHANGELOG.md || { echo "CHANGELOG.md has no [unreleased] compare link to move" >&2; exit 1; }
    git status --short
    echo "Commits since $previous, to write the [$version] section from:"
    git log --format='  %s' "$previous..origin/main"
    echo "Write the [$version] section of CHANGELOG.md, then commit and open a PR."

# Sign and push the tag for a merged version, from an up-to-date main. release.yml does the rest.
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
    .github/scripts/tag-release.sh "$version"
    echo "Tag v$version is pushed: release.yml drafts the release, uploads its assets and publishes it."

# Run at the end of `just check`: the openapi schema and the coverage gate.
local-check:
    just openapi-check
    just test

# Collect the translatable strings of app/ (templates and N_() calls) into app/locale/messages.pot.
i18n-extract:
    uv run pybabel extract -F babel.cfg -k N_ --no-location --no-wrap --sort-output --project r9cam --copyright-holder "Simon van Lierde" -o app/locale/messages.pot app
    perl -0pi -e 's/\n+\z/\n/' app/locale/messages.pot

# Re-extract, then merge the new strings into each language's .po. Translate the empty entries, then `just i18n-compile`.
i18n-update: i18n-extract
    uv run pybabel update -i app/locale/messages.pot -d app/locale --no-fuzzy-matching --ignore-pot-creation-date --ignore-obsolete --no-wrap
    # pybabel update puts back the header lines extract leaves out, and a trailing blank line.
    perl -0pi -e 's/\n+\z/\n/; s/^"Report-Msgid-Bugs-To: .*\n//m; s/Project-Id-Version:  /Project-Id-Version: /' app/locale/*/LC_MESSAGES/messages.po

# Compile each .po to the .mo the app reads. The .mo files are committed.
i18n-compile:
    uv run pybabel compile -d app/locale --statistics
