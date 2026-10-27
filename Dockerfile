# Prep stage: fetch the Raspberry Pi archive keyring once (shared by later stages).
# The remote .deb is checksum-pinned; only the extracted keyring file is copied forward.
# See raspberrypi/rpi-image-gen#171 for why we fetch the .deb directly.
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS rpi-keyring
ADD --checksum=sha256:2e727149d7acb8cc7f604e66d0049161039c8aa1eaf1175e54f9e69d963d60e4 \
    https://archive.raspberrypi.com/debian/pool/main/r/raspberrypi-archive-keyring/raspberrypi-archive-keyring_2025.1+rpt1_all.deb /tmp/keyring.deb
RUN dpkg -i /tmp/keyring.deb

# Build stage: compile the virtual environment (no S3 dependencies by default).
FROM ghcr.io/astral-sh/uv:0.13-python3.13-trixie-slim@sha256:331fbb158258608b9391e802305a9a2c9e42d689435c1d98706647122a122ab0 AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# Configure Raspberry Pi repository (keyring from prep stage)
COPY --from=rpi-keyring /usr/share/keyrings/raspberrypi-archive-keyring.gpg /usr/share/keyrings/
RUN printf "Types: deb\nURIs: https://archive.raspberrypi.com/debian/\nSuites: trixie\nComponents: main\nSigned-By: /usr/share/keyrings/raspberrypi-archive-keyring.gpg\n" \
    > /etc/apt/sources.list.d/raspi.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends python3-picamera2 && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies (cached layer — copy lockfile first for layer-cache efficiency).
COPY .python-version pyproject.toml uv.lock README.md LICENSE ./
COPY r9cam_models/ r9cam_models/
# The venv is built on Debian's python3.13 (pulled in by python3-picamera2), not
# the image's /usr/local one: the runtime stage ships only Debian's interpreter.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --system-site-packages --python /usr/bin/python3.13 && \
    uv sync --locked --no-install-project --no-editable --no-dev

# Install project
COPY app/ app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --no-dev

# Standalone builder: add the [s3] group (aioboto3) on top of the paired venv.
# S3CompatibleSink guards its import with try/except so paired-mode images run
# fine without it; this stage is only referenced by the runtime-standalone target.
FROM builder AS builder-standalone
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable --no-dev --group s3

# Runtime stage: minimal paired-mode image (no S3 dependencies).
# Plain Debian, not python:3.13-slim: python3-picamera2 already installs Debian's
# python3.13, which the venv is built on, so a second interpreter in /usr/local
# would be 33 MiB of dead weight.
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS runtime

# The source label links a pushed GHCR package to this repository.
LABEL org.opencontainers.image.source="https://github.com/CMLPlatform/r9cam" \
      org.opencontainers.image.title="r9cam" \
      org.opencontainers.image.description="Raspberry Pi Camera plugin for R9lab platform" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

WORKDIR /app

# Configure Raspberry Pi repository and install runtime dependencies.
# apt cache mounts keep package lists in the build cache (not in the image
# layer), so there is no need for a separate ``rm -rf /var/lib/apt/lists/*``.
# ca-certificates comes first: debian-slim lacks it, and both the Pi archive
# and the app's own HTTPS calls need it.
#
# python3-av -> libavdevice -> libsdl2 -> libgbm1 drags in Mesa's GPU drivers:
# mesa-libgallium, LLVM and Z3, about 190 MiB. Only GL, GBM and VA-API driver
# modules link them, and those are loaded on demand for a display or a GPU,
# which this headless image never uses. So they are removed with
# --force-depends, and the check after it proves ffmpeg and av still load.
# This leaves apt's dependency state broken: add packages before this step.
COPY --from=rpi-keyring /usr/share/keyrings/raspberrypi-archive-keyring.gpg /usr/share/keyrings/
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    printf "Types: deb\nURIs: https://archive.raspberrypi.com/debian/\nSuites: trixie\nComponents: main\nSigned-By: /usr/share/keyrings/raspberrypi-archive-keyring.gpg\n" \
    > /etc/apt/sources.list.d/raspi.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg python3-picamera2 util-linux && \
    dpkg-query -W -f '${db:Status-Abbrev} ${Package}\n' mesa-libgallium 'libllvm*' 'libz3-*' | \
    awk '$1 == "ii" {print $2}' | xargs -r dpkg --remove --force-depends && \
    ffmpeg -hide_banner -version >/dev/null && \
    python3 -c "import av, picamera2" && \
    useradd --create-home --uid 1000 --gid video r9cam

# LANG matches what python:3.13-slim set, for the app and its ffmpeg subprocesses.
ENV LANG=C.UTF-8 \
    PYTHONPATH="/app:/usr/lib/python3/dist-packages" \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --link --chown=1000:44 --from=builder /app/.venv .venv
COPY --link --chown=1000:44 --from=builder /app/app app

RUN mkdir -p /app/data/images /app/logs /home/r9cam/.config/r9cam && \
    chown -R 1000:44 /app/data /app/logs /home/r9cam/.config

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8018/')" || exit 1

EXPOSE 8018

USER 1000:44

CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8018", "--forwarded-allow-ips", "127.0.0.1,::1"]

# Standalone runtime: identical to the paired runtime but with S3 dependencies.
# Only the venv differs; all other layers are inherited from the runtime stage.
FROM runtime AS runtime-standalone
COPY --link --chown=1000:44 --from=builder-standalone /app/.venv .venv
