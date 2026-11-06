# The base image is OSS-Fuzz's Python builder. It ships Python 3.11, so build.sh
# uses uv to build the Python 3.13 environment r9cam needs.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9
# Matches the app Dockerfile's uv image. The two pins are bumped separately by Renovate.
COPY --from=ghcr.io/astral-sh/uv:0.13-python3.13-trixie-slim@sha256:6ff812e34a0e14b4b8bc9ddf25e77b3e16bac6e0c4d9b67641f40366fa382d4c /usr/local/bin/uv /usr/local/bin/uv
COPY . $SRC/r9cam
WORKDIR $SRC/r9cam
COPY .clusterfuzzlite/build.sh $SRC/
