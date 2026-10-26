# The base image is OSS-Fuzz's Python builder. It ships Python 3.11, so build.sh
# uses uv to build the Python 3.13 environment r9cam needs.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9
# Same uv image as the app Dockerfile, so one pin covers both.
COPY --from=ghcr.io/astral-sh/uv:0.13-python3.13-trixie-slim@sha256:40215b626e22e4ff65839863624c4b885b8829b1a66ce895b7be20eca7fabe6d /usr/local/bin/uv /usr/local/bin/uv
COPY . $SRC/r9cam
WORKDIR $SRC/r9cam
COPY .clusterfuzzlite/build.sh $SRC/
