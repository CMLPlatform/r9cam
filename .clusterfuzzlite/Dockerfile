# The base image is OSS-Fuzz's Python builder. It ships Python 3.11, so build.sh
# uses uv to build the Python 3.13 environment r9cam needs.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9
# Matches the app Dockerfile's uv image. The two pins are bumped separately by Renovate.
COPY --from=ghcr.io/astral-sh/uv:0.13-python3.13-trixie-slim@sha256:803d2b80b6913e562837d69f037f39bfea80f51ef3f0dd0d8fdffbd95688fd6d /usr/local/bin/uv /usr/local/bin/uv
COPY . $SRC/r9cam
WORKDIR $SRC/r9cam
COPY .clusterfuzzlite/build.sh $SRC/
