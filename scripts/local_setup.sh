#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -euo pipefail

# Usage: ./scripts/local_setup.sh [--dev]
#
# Options:
#   --dev    Create a development environment (install dev deps) and install
#            prek hooks.

DEV_MODE=false
while [ "$#" -gt 0 ]; do
	case "$1" in
		--dev)
			DEV_MODE=true
			shift
			;;
		-h|--help)
			echo "Set up a local environment for the r9cam repository using uv."
			echo "Usage: $0 [--dev]"
			echo ""
			echo "Arguments:"
			echo "  --dev    Create a development environment (install dev deps and install prek hooks)."
			exit 0
			;;
		*)
			shift
			;;
	esac
done

# Install uv if not already installed: the release archive for this platform, checked against the
# sha256 uv publishes with the release, so no downloaded script runs. The version follows the
# Dockerfile's uv 0.13 line; bump it and all five hashes together.
UV_VERSION=0.13.5
if ! command -v uv >/dev/null 2>&1; then
	case "$(uname -s)-$(uname -m)" in
		Linux-x86_64) UV_TARGET=x86_64-unknown-linux-gnu UV_SHA256=f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f ;;
		Linux-aarch64) UV_TARGET=aarch64-unknown-linux-gnu UV_SHA256=4bb69cf95ed13f23713bb7bc09f241896ea0c75b7c557e615a20604b82f9c403 ;;
		Linux-armv7l) UV_TARGET=armv7-unknown-linux-gnueabihf UV_SHA256=fe6b5b1d30b28b9dec45cfd8f60fec38941e18a8f9b1e64530dd197aba68dd07 ;;
		Darwin-x86_64) UV_TARGET=x86_64-apple-darwin UV_SHA256=b0f52b0e3945b4107d89024ea38e625683011fbfc05a0d98f9fa2d6dcee28c66 ;;
		Darwin-arm64) UV_TARGET=aarch64-apple-darwin UV_SHA256=743f85035a1996ecb350659e01cd9faea9709829be09b1b4b03c73eaf3c9cd73 ;;
		*)
			echo "Error: no uv download for $(uname -s) $(uname -m); install uv by hand: https://docs.astral.sh/uv/getting-started/installation/" >&2
			exit 1
			;;
	esac
	UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${UV_TARGET}.tar.gz"
	UV_TMP=$(mktemp -d)
	trap 'rm -rf "$UV_TMP"' EXIT
	echo "Installing uv ${UV_VERSION} into $HOME/.local/bin..."
	if command -v curl >/dev/null 2>&1; then
		curl -fsSL -o "$UV_TMP/uv.tar.gz" "$UV_URL"
	elif command -v wget >/dev/null 2>&1; then
		wget -qO "$UV_TMP/uv.tar.gz" "$UV_URL"
	else
		echo "Error: curl or wget required to install uv" >&2
		exit 1
	fi
	if command -v sha256sum >/dev/null 2>&1; then
		UV_ACTUAL=$(sha256sum "$UV_TMP/uv.tar.gz" | cut -d ' ' -f 1)
	else
		UV_ACTUAL=$(shasum -a 256 "$UV_TMP/uv.tar.gz" | cut -d ' ' -f 1)
	fi
	if [ "$UV_ACTUAL" != "$UV_SHA256" ]; then
		echo "Error: checksum mismatch for $UV_URL (expected $UV_SHA256, got $UV_ACTUAL)" >&2
		exit 1
	fi
	tar -xzf "$UV_TMP/uv.tar.gz" -C "$UV_TMP"
	mkdir -p "$HOME/.local/bin"
	install -m 755 "$UV_TMP/uv-${UV_TARGET}/uv" "$UV_TMP/uv-${UV_TARGET}/uvx" "$HOME/.local/bin/"

	# Ensure the freshly-installed uv is on PATH for this run
	export PATH="$HOME/.local/bin:$PATH"

	if ! command -v uv >/dev/null 2>&1; then
		echo "uv still not available after installation; please add $HOME/.local/bin to your PATH or install uv manually: https://astral.sh/uv" >&2
		exit 1
	fi
fi

# Create a virtual environment using the system Python and site packages
uv venv --system-site-packages --clear --no-managed-python --no-config

# Sync dependencies. In dev mode we keep dev dependencies, otherwise exclude them.
if [ "$DEV_MODE" = true ]; then
	echo "Syncing dependencies (including dev deps)"
	uv sync --frozen
else
	echo "Syncing dependencies (excluding dev deps)"
	uv sync --frozen --no-dev
fi

# Install prek hooks only in dev mode
if [ "$DEV_MODE" = true ]; then
	echo "Installing prek hooks ..."
	uv run prek install
	echo "Local setup complete. To run the application, use 'uv run fastapi dev app/main.py'"
else
	echo "Skipping prek install in non-dev mode"
	echo "Local setup complete. To run the application, use 'uv run fastapi run app/main.py --port 8018'"
fi
