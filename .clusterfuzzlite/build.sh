#!/bin/bash -eu
# compile_python_fuzzer runs pyinstaller from PATH, so putting the 3.13 venv
# first makes it bundle that interpreter and the locked dependencies.
export UV_PROJECT_ENVIRONMENT="$SRC/venv"
export UV_PYTHON_INSTALL_DIR="$SRC/uv-python"
uv sync --locked --no-dev --group fuzz --python 3.13
export PATH="$SRC/venv/bin:$PATH"

# The app mounts its static files and loads its templates at import time.
compile_python_fuzzer fuzz/relay_frames.py \
    --add-data app/static:app/static \
    --add-data app/templates:app/templates
