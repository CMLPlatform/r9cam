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
# A mutant-name pattern (just mutation "app.delivery.queue*") limits the run and skips the baseline diff, which only means something on a full run.
mutation *ARGS:
    rm -rf .mutation
    mkdir -p .mutation/src reports/mutation
    cp -r app scripts tests typings pyproject.toml uv.lock .mutation/
    cp -r r9cam_models/src/r9cam_models .mutation/src/
    cd .mutation && uv run --project .. mutmut run --max-children "$(nproc)" {{ARGS}}
    cd .mutation && uv run --project .. mutmut results | grep -E ': (survived|no tests)$' | sed 's/^ *//; s/: .*//' | LC_ALL=C sort > ../reports/mutation/survivors.txt
    @echo "Survivors and untested: $(wc -l < reports/mutation/survivors.txt)"
    @if [ -z '{{ARGS}}' ]; then \
        echo "Survivor counts per function that differ from tests/mutation-baseline.txt (< baseline, > this run):"; \
        sed 's/ *#.*//; /^$/d; s/__mutmut_[0-9]*$//' tests/mutation-baseline.txt | uniq -c > .mutation/baseline-counts.txt; \
        sed 's/__mutmut_[0-9]*$//' reports/mutation/survivors.txt | uniq -c | diff .mutation/baseline-counts.txt -; \
    fi

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
