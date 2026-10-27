# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Entries up to
0.6.2 were generated from commit messages.

## [Unreleased]

### Changed

- Release tags are signed: `just release-publish` signs the tag with the maintainer's key
  and pushes it before drafting the release, instead of GitHub creating an unsigned tag.
- The image and the install no longer pull in the deploy-only parts of `fastapi[standard]`
  (the FastAPI Cloud CLI, `email-validator`, `httpx2`, `pydantic-extra-types` and their
  dependencies). The app asks for what it uses: `fastapi-cli`, `uvicorn[standard]`, `jinja2`
  and `python-multipart`. The runtime image is about 15 MB smaller.

### Fixed

- A 2xx upload reply that is not JSON or lacks `image_id` or `image_url` now counts as
  delivered, with a warning in the log. Before, the Pi retried the upload and the backend
  stored the capture twice.
- A 2xx upload reply with a valid `image_id` but a bad or missing `image_url` now keeps the
  backend's id. Before, the Pi fell back to its own capture id and lost the backend's.
- A capture whose requeue after pairing was cut off by a crash is no longer lost when the
  camera restarts and drains its queue before the next pairing. The queue now finishes the
  requeue instead of deleting the image. A full disk while finishing one such capture no
  longer stops the rest of the requeue or the queue drain.
- A camera start that is cancelled (for example by a request timeout) no longer leaves the
  camera claimed until the app restarts. The close now waits for the start, or for opening
  the camera, to finish, because picamera2 cannot release a camera that is still starting.
- A capture that runs out of upload attempts while a new capture is being queued is no longer
  lost. The queue check could delete its metadata between the two file moves into `dead/`.
  A dead-letter move cut off by a crash or shutdown is now finished on the next pass.

## [0.7.1] - 2026-10-27

### Added

- Each capture's metadata records how it was made: the lens position, white-balance gains
  and sensor crop, the plugin version and the commit the release image was built from, and
  the SHA-256 of the libcamera tuning file. R9lab stores them with the image. ([#100])

### Changed

- Needs r9cam-models 0.6.1, which adds the provenance fields and the stricter paired poll
  response. ([#106])
- The container image is about 220 MiB smaller unpacked (amd64 build: 750 to 529 MiB of files,
  797 to 556 MB as Docker reports it; the arm64 0.7.0 image was 778 MiB of files). It drops
  Mesa's GPU drivers with LLVM and Z3, which the libav libraries pull in but a headless image
  never loads, and it runs on Debian's Python 3.13 (3.13.5) instead of a second interpreter
  from the python:3.13-slim base. ([#103])

### Fixed

- Relayed commands no longer fail with 401 when the relay credentials come from environment
  variables. The key the relay uses to call this camera's own API was never created or
  authorized on that path, only when credentials were read from the credentials file. ([#96])
- A relayed command whose reply the relay cannot encode (for example an oversized
  `Content-Type`) now gets a 500 reply at once. Before, the backend waited out its 30 second
  command timeout. ([#97])
- The release image gets its SBOM and build provenance attestations again. The 0.7.0 image
  was published without them, because the SBOM step looked for an amd64 image. ([#95])
- The citation metadata lists "research data" instead of "computer vision", which r9cam does
  not do.
- A queued upload whose metadata file is valid JSON of the wrong shape, such as a list or a
  `null` attempt count, is now skipped instead of stopping every queued upload and every new
  capture. A timestamp without a timezone is read as UTC. ([#102])
- A capture left in the upload queue without its metadata file, after a crash or power cut
  during queueing, is now removed after a minute. It used to count against the queue's size
  limit forever. A requeue that a crash interrupted is finished on the next start. ([#102])
- Unpairing keeps the local API key. Before, it deleted the key with the relay credentials,
  so the next start made a new one and LAN clients lost access. ([#101])
- When the camera fails to configure, for example on a memory error, or its start is cancelled
  by a request timeout, it is released, so the next capture or stream opens it again. Before,
  the camera stayed half set up until a restart. ([#101])
- The preview thumbnail keeps refreshing after an error. Before, one failed refresh stopped
  the refresh loop until a restart, so the camera card showed an old image. ([#101])
- The relay waits before it reconnects when the backend accepts the connection and then drops
  it at once. Before, it reconnected in a tight loop. The wait grows up to 60 seconds and
  resets after a connection that stays up for 60 seconds. ([#101])
- A capture the backend accepted is no longer uploaded again when the backend's reply has an
  `image_url` the camera cannot use, such as plain HTTP in production. The camera logs a
  warning and returns the capture without a URL. Before, it queued the capture for retry and
  the backend stored it twice. ([#101])

## [0.7.0] - 2026-10-27

**Upgrading:**

- Upgrade the R9lab backend first. This release needs one that serves the `/v1/plugins/r9cam`
  routes and accepts the `r9cam-relay` token audience: the hosted `api.r9lab.io` does, a
  self-hosted R9lab v0.5.0 or older does not. Pis on 0.6 keep working with a current backend
  until 2027-01-31, so upgrade them before then.
- Docker Compose now pulls the release image: run `git pull` first, then `docker compose pull`
  and `docker compose up -d`. Standalone installs: set `R9CAM_IMAGE=r9cam` in `.env` and run
  `docker compose build` instead of `pull`.
- Paired cameras stay paired when Docker Compose is upgraded in place and on installs without
  Docker. A fresh clone into an `r9cam/` directory starts with empty volumes. See "Upgrading
  From 0.6" in [INSTALL.md](INSTALL.md) for both cases.
- With S3 storage, new captures go under the `r9cam/` key prefix. Objects already stored stay
  under `rpi-cam/`; nothing moves them. Dashboards and alerts that filter
  on `job="rpi-cam-plugin"` or `rpi_cam_*` metrics must switch to `job="r9cam"` and `r9cam_*`.

### Added

- Each release publishes a signed linux/arm64 image to `ghcr.io/cmlplatform/r9cam`, tagged
  with the version, `X.Y` and `latest`, so the Pi pulls it instead of building it. Its build
  provenance and SBOM are attested: `gh attestation verify oci://ghcr.io/cmlplatform/r9cam@<digest> --repo CMLPlatform/r9cam` checks them. `R9CAM_VERSION` in `.env` pins a release; the default is `latest`. ([#87])

### Changed

- **Breaking:** the plugin is now r9cam, and its shared models package is `r9cam-models`
  (was `relab-rpi-cam-models`). Renamed with it: the `R9CAM_CREDENTIALS_FILE` variable, the
  `~/.config/r9cam` credentials directory, the `_r9cam._tcp` mDNS service type, the `r9cam`
  OpenTelemetry `service.name`, `/healthz` service, the `r9cam_session` cookie,
  `openapi.r9cam.json` and the device token audience `r9cam-relay`. INSTALL.md has the full
  table. ([#45], [#48])
- **Breaking:** the last `rpi-cam` names follow the rename: Prometheus metrics are `r9cam_*`
  (was `rpi_cam_*`), the Alloy `job` label and default `instance` are `r9cam` (was
  `rpi-cam-plugin`), the default S3 key prefix is `r9cam/` (was `rpi-cam/`), the example bucket
  is `r9cam`, and the container user is `r9cam`. ([#86])
- **Breaking:** the Pi calls only the `/v1/plugins/r9cam` routes and the default pairing
  backend is `https://api.r9lab.io`. ([#79])
- Pairing polls with POST and a JSON body, as the current backend expects. ([#46])
- EXIF capture details (exposure, offset time, temperature) are written to the Exif block, and
  `Software` names the r9cam version.

### Fixed

- The upload queue stays under its byte cap when captures arrive at the same time. ([#61])
- Captures that ran out of upload retries, for example while the Pi was unpaired, are queued
  again after a successful pairing. Any that no longer fit under the queue's limits stay in
  `data/queue/dead/`. ([#85])
- `local_setup.sh` installs uv from a release archive it checks against its checksum. ([#68])
- Installs without Docker keep their pairing across the rename, and `RELAB_CREDENTIALS_FILE`
  still works with a warning. ([#79])
- The wheel and sdist include the AGPL license text. ([#90])
- The relay keeps retrying when the backend refuses its handshake (401, 403, 404, 429 and
  the like), with the usual backoff and a warning that names the status, instead of stopping
  until the next restart. On a 401 or 403 the warning says the camera may need re-pairing. ([#84])

### Security

- Dependencies locked past advisories in aiohttp, pillow, urllib3, pyjwt, multidict,
  opentelemetry and certifi. ([#42], [#58], [#63])
- Releases carry the wheel, the sdist and a CycloneDX SBOM (`r9cam.cdx.json`), each with a
  build provenance attestation.

## [0.6.2] - 2026-09-07

### Fix

- **pairing**: pin the relay host to the paired backend (#31)
- **docker**: install util-linux security update

## [0.6.1] - 2026-08-13

### Fix

- **docker**: pin the runtime image back to Python 3.13
- **docker**: drop pip from the runtime image
- device seam validation and licensing update (#24)

## [0.6.0] - 2026-07-20

### Feat

- **models**: add a shared relay command timeout constant so the backend can align its per-command wait with the Pi's own deadline

### Refactor

- **relay**: dispatch relayed commands in-process via `ASGITransport`, removing the loopback TCP hop and its dependence on `base_url` being reachable
- Standardize the project name to Relab

## [0.5.0] - 2026-07-09

### Feat

- **observability**: add unauthenticated local-network liveness probe

## [0.4.0] - 2026-07-01

### Feat

- Harden authentication and sessions: enforced lifetimes, ASVS-aligned cookies, same-origin checks for cookie writes, and structured auth, CSRF, and session logging
- Harden browser security: per-request CSP nonces, restricted CORS and private-network access, blocked HTTP TRACE, and limited static file types
- Enforce HTTPS transport for S3 and OTLP endpoints
- Validate relay credentials at startup and boundaries, allowlist backend commands, bound inputs, and rate-limit sensitive actions
- Require auth for pairing, preview, and metrics endpoints, and fail closed for production loopback pairing
- Reject `DEBUG=true` in production and reveal the local API key on demand instead of embedding it in HTML
- Add a security CI workflow, pin container images by digest, and default listeners to loopback
- Add a pairing-state polling endpoint and a client-safe exception handler

### Fix

- Block backslash open-redirects, redact bearer tokens in auth headers, return 403 instead of 500 for non-ASCII API keys, and reject oversized preview thumbnails
- Prevent startup crashes from malformed credential files, and harden capture validation and cleanup
- Fix worker reliability: thermal-throttle desync, preview-sleeper loop death, and preview recovery on fatal HLS errors
- Serialize capture timestamps as UTC-aware and relay binary frames correctly, warn on plain-HTTP base URLs in production, and map dma_heap nodes individually in Compose

### Refactor

- Reorganize into a feature-first layout: image sinks and upload into `delivery`, streaming into `camera/streaming`, metrics into `observability`

## [0.3.0] - 2026-04-21

The v0.1 to v0.3 history was squashed into one commit (c6e67bc) on 2026-04-15, so the v0.1.1
and v0.2.0 tags point at commits that are not on main. The v0.3.0 tag was added afterwards, on
3b32e04, the first commit on main at version 0.3.0.

### Feat

- Add a new local setup and pairing flow, including secure pairing, local connection mode, automatic API key generation, mDNS discovery, pairing status feedback, and improved direct-connection guidance
- Add local camera preview support, including low-resolution snapshots, preview thumbnails, and homepage display of the latest captured image
- Improve the local web UI with better setup flow, responsiveness, theming, and overall usability
- Expand camera and streaming support with updated routes, documentation, HLS activity tracking, and capture-and-store helpers
- Improve runtime reliability with better task lifecycle management, websocket and relay error handling, atomic JPEG encoding, and unpair cleanup
- Add MediaMTX and Docker networking configuration for local API and HLS access
- Add release verification for published package installation

### Refactor

- Reorganize the app into a clearer feature-first structure, modernize the plugin runtime, and simplify related settings and tests

## [0.2.0] - 2025-11-26

### Feat

- Add Dockerized setup for easier deployment
- Add Cloudflare Tunnel support for easy publishing

### Fix

- Add main platform API to default allowed CORS domains
- Improve local setup script
- Ensure the virtual environment is compatible with system Python packages

## [0.1.1] - 2025-08-20

### Fix

- **build**: bumped version to resolve a dependency issue on PyPI, as dependencies were only included after the initial publication.

## [0.1.0] - 2025-08-20

### Feat

- **frontend**: improve frontend access to API
- **logging**: add custom logging setup with file and console output
- **auth**: allow direct broswer-based access via cookies
- **build**: Move to src layout for packaging
- **pre-commit**: Add pre-commit-update hook
- **cicd**: Install commitizen and delete dependabot.yaml

### Fix

- **build**: Only build models package, main plugin app back to root
- **deps**: Custom Renovate config

### Refactor

- **tasks**: improve repeat_task function to handle coroutine tasks and logging

[#100]: https://github.com/CMLPlatform/r9cam/pull/100
[#101]: https://github.com/CMLPlatform/r9cam/pull/101
[#102]: https://github.com/CMLPlatform/r9cam/pull/102
[#103]: https://github.com/CMLPlatform/r9cam/pull/103
[#106]: https://github.com/CMLPlatform/r9cam/pull/106
[#42]: https://github.com/CMLPlatform/r9cam/pull/42
[#45]: https://github.com/CMLPlatform/r9cam/pull/45
[#46]: https://github.com/CMLPlatform/r9cam/pull/46
[#48]: https://github.com/CMLPlatform/r9cam/pull/48
[#58]: https://github.com/CMLPlatform/r9cam/pull/58
[#61]: https://github.com/CMLPlatform/r9cam/pull/61
[#63]: https://github.com/CMLPlatform/r9cam/pull/63
[#68]: https://github.com/CMLPlatform/r9cam/pull/68
[#79]: https://github.com/CMLPlatform/r9cam/pull/79
[#84]: https://github.com/CMLPlatform/r9cam/pull/84
[#85]: https://github.com/CMLPlatform/r9cam/pull/85
[#86]: https://github.com/CMLPlatform/r9cam/pull/86
[#87]: https://github.com/CMLPlatform/r9cam/pull/87
[#90]: https://github.com/CMLPlatform/r9cam/pull/90
[#96]: https://github.com/CMLPlatform/r9cam/pull/96
[#97]: https://github.com/CMLPlatform/r9cam/pull/97
[0.1.0]: https://github.com/CMLPlatform/r9cam/commits/v0.1.1
[0.1.1]: https://github.com/CMLPlatform/r9cam/releases/tag/v0.1.1
[0.2.0]: https://github.com/CMLPlatform/r9cam/compare/v0.1.1...v0.2.0
[0.3.0]: https://github.com/CMLPlatform/r9cam/compare/v0.2.0...v0.3.0
[0.4.0]: https://github.com/CMLPlatform/r9cam/compare/v0.3.0...v0.4.0
[0.5.0]: https://github.com/CMLPlatform/r9cam/compare/v0.4.0...v0.5.0
[0.6.0]: https://github.com/CMLPlatform/r9cam/compare/v0.5.0...v0.6.0
[0.6.1]: https://github.com/CMLPlatform/r9cam/compare/v0.6.0...v0.6.1
[0.6.2]: https://github.com/CMLPlatform/r9cam/compare/v0.6.1...v0.6.2
[0.7.0]: https://github.com/CMLPlatform/r9cam/compare/v0.6.2...v0.7.0
[0.7.1]: https://github.com/CMLPlatform/r9cam/compare/v0.7.0...v0.7.1
[unreleased]: https://github.com/CMLPlatform/r9cam/compare/v0.7.1...HEAD
