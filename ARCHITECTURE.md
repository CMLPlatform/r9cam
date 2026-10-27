# Architecture

This document is for maintainers and agents changing the plugin internals. Operator setup lives in [INSTALL.md](INSTALL.md); contributor workflow lives in [CONTRIBUTING.md](CONTRIBUTING.md).

The plugin is a FastAPI app running on a Raspberry Pi. It captures images and video, serves local setup and preview surfaces, opens an outbound relay to R9lab, and uploads captures either to the R9lab backend or to S3-compatible storage.

## Request Flow

```text
R9lab backend / local browser
        |
        | outbound WebSocket relay or local HTTP
        v
FastAPI app (app/main.py, app/router.py)
        |
        v
Feature routers: camera / pairing / auth / observability / frontend
        |
        v
Feature services and shared infrastructure
        |
        v
AppRuntime-owned services, workers, and runtime state
```

Feature packages own their routers, schemas, dependencies, exceptions, and services. The camera package also owns the preview/stream pipeline under `app/camera/streaming/`. Cross-cutting packages at `app/` root own infrastructure: backend client, relay, delivery (image sinks and upload queue), observability, and workers.

## Runtime Container

`app/core/runtime.py::AppRuntime` is the process container. It owns:

- camera manager
- preview pipeline and media helpers
- relay service and relay state
- pairing service and pairing state
- upload queue worker
- thermal, preview-sleep, and thumbnail workers
- observability handle
- managed background task sets

Code that runs outside a request, such as pairing and relay startup, accesses the active runtime through `app/core/runtime_context.py`.

Architecture rewrites should keep this boundary explicit: `Settings` is static bootstrap input, `RuntimeState` is active mutable credential/auth state, and `AppRuntime` owns long-lived services, workers, and task lifecycles. A service should move into `AppRuntime` only when it is process-owned rather than request-local.

## Lifespan And Bootstrap

Startup is coordinated through `app/core/lifespan.py`, `app/core/bootstrap.py`, and `app/core/settings.py`:

1. Load env-backed `Settings`.
1. Build `AppRuntime` with a `RuntimeState` seeded from settings.
1. Apply persisted relay credentials from `~/.config/r9cam/relay_credentials.json` if static relay credentials are absent.
1. Ensure local and relay-local API keys exist where needed.
1. Register `AppRuntime` as the active runtime.
1. Start managed background workers, pairing, and relay tasks according to config.

Shutdown cancels managed tasks and closes camera, relay, and observability resources.

## Configuration And Runtime State

`Settings` is static operator configuration loaded from `.env`. `RuntimeState` stores values that are generated, persisted, or mutable at runtime, such as relay credentials, local API keys, and derived authorized key snapshots. `RelayRuntimeState` is separate and tracks relay connection/activity, not credentials.

Configuration precedence at startup is:

1. env-backed settings
1. persisted runtime credentials
1. generated local defaults

Transport policy is enforced at the settings/runtime boundary. Relay URLs use `wss://` outside `APP_ENV=development`. Remote S3, public URL templates, and OTLP endpoints use HTTPS unless they are loopback or development-only HTTP. Backend-returned media URLs are checked before they reach callers, so uploads do not come back as plain-HTTP links.

`APP_ENV=production` is the fail-closed default. Production rejects `DEBUG=true`, disables Pi-hosted Swagger/OpenAPI routes, blocks HTTP TRACE, and serves only `.css`, `.ico`, `.js`, and `.png`.

## External Connections

Outbound connections are fixed at startup and kept narrow:

- pairing API, relay WebSocket, and upload callbacks go to R9lab
- relay local dispatch is allowlisted first, then gets the relay-local API key
- MediaMTX stays on localhost
- S3 uses HTTPS remotely
- observability collectors are optional

Any path used at request time is either encoded or checked against an allowlist first.

## Cryptography

Relay device assertions are short-lived ES256 JWTs signed with the Pi's P-256 key. We validate that key when settings load, credentials are saved, and runtime state is applied, so bad key types fail early.

Relay private keys, relay key IDs, camera IDs, and local API keys live in `~/.config/r9cam/relay_credentials.json`. The file is written atomically with `0600` permissions. Pairing creates a fresh key pair; unpairing deletes the file.

Session tokens, API keys, pairing fingerprints, JWT IDs, and capture IDs come from Python's `secrets` CSPRNG. API-key comparisons use `hmac.compare_digest`.

## Sensitive Data

Credentials such as relay keys, API keys, session tokens, pairing fingerprints, and S3 secrets stay out of URLs and query strings. API keys and assertions stay in headers or protected response bodies. Logout clears the browser session and drops cached state.

Responses use `Cache-Control: no-store`, static assets come from an explicit extension allowlist, and `/local-key` is only exposed explicitly.

Logs redact known secret fields, bearer tokens, and private keys before emission. Local pairing banners stay out of JSON logs. Captured images, queue entries, and preview thumbnails are bounded and validated before upload, retry, or serving.

## Auth Boundaries

The plugin has two request-auth modes:

- `X-API-Key` for local direct clients, relay-dispatched local calls, and scriptable integrations
- browser session cookie for the local operator UI

Protected feature routers are included with the shared `verify_request` dependency. Unsafe cookie-authenticated writes require same-origin browser proof through `Origin` or `Referer`; explicit API-key writes do not use that browser CSRF path.

Browser sessions are server-side, in-memory tokens for the local operator UI. Login replaces any existing cookie, sessions expire after 30 minutes of inactivity or 12 hours from creation, and logout or restart clears them.

The plugin does not manage local user accounts, admin roles, MFA, account-disable workflows, or federated identity sessions. Those controls live in the R9lab platform/backend identity boundary. This device plugin only checks local API keys and its own short-lived operator UI sessions.

Local login attempts are rate-limited at the auth boundary. Request schemas own edge validation for camera controls, focus mode consistency, stream keys, upload metadata, and other bounded user-controlled payloads before work reaches services.

The setup page is intentionally public during pairing so headless operators can read the pairing code. Because that code is short-lived, `/setup` and pairing logs should be treated as operator-only during pairing.

Authorization is route based and local to the device. The R9lab backend handles per-user and tenant authorization before sending relay commands; the plugin just keeps the device side narrow:

- public setup/status routes are `/`, `/setup`, `/pairing/state`, and local-network preview media
- protected routes include camera controls, captures, preview, streaming, telemetry, metrics, `local-key`, `local-access`, unpair, and pairing-code rotation
- relay-dispatched routes must match the allowlist in `r9cam_models`

Sensitive details stay behind those boundaries. Public setup visitors see bootstrap state only, while authenticated operators can see topology and direct-access details. `/system/local-access` and `/local-key` expose the local API key after normal auth, and `/local-key` also requires a local-network client.

## Pairing

When relay credentials are absent and `PAIRING_BACKEND_URL` is set, `app/pairing/services/service.py` enters pairing mode:

1. generate a short pairing code and device fingerprint
1. register with the pairing backend
1. display the code on `/setup` and in the `PAIRING READY` log banner
1. poll until the backend claims the code
1. validate returned relay transport
1. persist credentials through `app/pairing/services/credentials.py`
1. start relay operation

Pairing rotation replaces the active code without deleting existing relay credentials.

## Relay

`app/relay/service.py` keeps one outbound WebSocket connection to the paired backend. The backend is a privileged command source for the device. The Pi-side relay limits blast radius with:

- explicit method/path allowlists
- relative path rejection
- filtered inbound headers
- local relay API-key injection before dispatch to FastAPI
- structural command envelope validation plus bounded frame size, queue depth, and command concurrency
- exponential reconnect

New relay-reachable routes should be intentionally added to the allowlist and covered by tests.

The relay allowlist is part of the private backend-to-plugin protocol. It belongs in the shared contract package (`r9cam_models`) with the relay envelopes, not duplicated in plugin runtime code. Breaking relay protocol changes are allowed when they simplify the seam, but they require a shared package version bump and coordinated backend/plugin updates.

## Camera, Preview, And Capture

`app/camera/services/manager.py` coordinates camera operations behind a lock. All hardware access goes through `CameraBackend` in `app/camera/services/backend.py`; production uses `Picamera2Backend` and tests use fakes. No code outside `picamera2_backend.py` touches the raw hardware handle.

`CameraBackend` covers the core every camera needs: `is_open` reports hardware readiness and `capture_preview_frame` taps the lores buffer without acquiring the capture lock. `StreamingCameraBackend` adds `start_lores_encoder` / `stop_lores_encoder`, which attach and detach the H264 encoder. The preview pipeline narrows to `StreamingCameraBackend` and raises `StreamingNotSupportedError` for a backend without those hooks. Workers and routers call only these protocol methods.

Preview publishes to a local MediaMTX sidecar over RTSP; browsers consume the stream via LL-HLS. Worker-owned hibernation (`PreviewSleeper`) stops the encoder after relay idleness and restarts it on the next HLS request. The `ThermalGovernor` drops the encoder bitrate when the SoC runs hot. The thumbnail worker keeps the setup UI preview current while preview is active.

Remote (relay-proxied) preview deliberately stays on LL-HLS; the rationale and the WebRTC/WHEP migration conditions are recorded in [ADR 0001](docs/adr/0001-preview-streaming-hls-over-relay.md).

Capture requests produce image bytes and bounded metadata, then pass them to the configured `ImageSink`.

## Image Sinks And Upload Queue

`app/delivery/base.py::ImageSink` abstracts capture persistence:

- backend sink uploads to the paired R9lab backend
- S3 sink uploads to an S3-compatible bucket

`IMAGE_SINK=auto` infers the sink from config. Explicit sink configuration fails loudly when required fields are missing. The upload queue is sink-agnostic: failed synchronous uploads are persisted to disk, retried with exponential backoff, and dead-lettered after exhaustion. Queue capacity and dead-letter retention settings are the single retention policy for failed local captures.

Capture IDs and filenames are generated internally. Current captures are `.jpg` / `image/jpeg`, bounded by `MAX_CAPTURE_PIXELS` and `MAX_CAPTURE_FILE_BYTES` before upload or queueing. Persisted queue and thumbnail files are validated before retry or serving. See [Sensitive Data](#sensitive-data) for retention and privacy boundaries.

## Observability

Structured logging is always enabled. Optional components are configured by env:

- Loki-compatible log shipping through the `observability-ship` Compose profile
- OTLP tracing through `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT`
- local telemetry collection exposed through protected system routes

The log inventory, retention defaults, and access expectations are documented in `INSTALL.md`.

Tracing setup lives in `app/observability/tracing.py`; logging and request-id context live in `app/observability/logging.py` and `app/core/middleware.py`.

## Shared Contract Package

`r9cam_models` contains the backend-to-plugin device DTOs. It validates pairing bootstrap payloads, local access bootstrap data, upload acknowledgements, relay command wire shape, and the shared relay command allowlist. Backend and plugin runtime code enforce that shared policy; frontend code consumes backend OpenAPI rather than importing device DTOs directly.

## Assurance Case

This section argues why the plugin meets its security requirements. The requirements are: only the paired R9lab backend and local operators with a key or session can drive the camera; device credentials never leave the Pi in clear; and a malformed or hostile input cannot reach code outside the routes meant for it. Each claim names the code or workflow that backs it. Reporting and scope live in [SECURITY.md](SECURITY.md).

### Threat model

The Pi sits on a lab or home network and keeps one outbound connection to R9lab. We defend against:

- a network attacker who can read or change traffic between the Pi and R9lab or S3;
- a compromised or buggy backend that sends relay commands outside what the device should do;
- a host on the local network that calls the REST API without a key, or replays a browser session;
- a hostile web page that tries a cross-site write through the operator's browser;
- a malicious dependency, action or contributor change that reaches a release.

We do not defend against physical access to the Pi, root on the host, or an operator who exposes the API to the internet against [INSTALL.md](INSTALL.md). User and tenant authorization belongs to R9lab, not to this device (see [Auth Boundaries](#auth-boundaries)).

### Trust boundaries

| Boundary                           | What crosses it                                  | Controls                                                                                                                                                                                                                                                                                                                                                                                                          |
| ---------------------------------- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Device to platform WebSocket relay | Commands from the backend, responses from the Pi | `wss://` required outside development and the relay host pinned to the pairing host (`app/core/settings.py`); ES256 device assertion with a random `jti` (`app/relay/device_jwt.py`); envelope schema, 64 KiB frame limit, header cap and method/path allowlist (`r9cam_models/src/r9cam_models/device_seam.py`); queue depth and command concurrency limits (`app/relay/service.py`)                             |
| Local REST API                     | Requests from the LAN and the operator UI        | `X-API-Key` checked with constant-time compare, or a server-side session cookie that is `HttpOnly` and `SameSite=Lax`; `Origin`/`Referer` check on cookie writes (`app/auth/dependencies.py`, `app/auth/router.py`); `/local-key` limited to local-network clients (`app/pairing/routers/local_key.py`)                                                                                                           |
| MediaMTX and ffmpeg sidecars       | Preview frames, the YouTube egress command       | RTSP, HLS and the control API bound to `127.0.0.1`, RTMP, WebRTC and SRT off (`mediamtx.yml`); YouTube keys validated before they reach the `runOnReady` command (`app/camera/schemas.py`, `app/camera/streaming/mediamtx_client.py`); containers run read-only with all capabilities dropped (`compose.yml`)                                                                                                     |
| S3 and upload sink                 | Capture bytes and metadata leaving the Pi        | HTTPS for remote S3, public URL templates and backend media URLs (`app/delivery/factory.py`, `app/backend/client.py`); size and pixel caps before upload or queueing (`app/camera/services/manager.py`, `app/delivery/queue.py`)                                                                                                                                                                                  |
| Pairing and the stored private key | Pairing code, relay credentials                  | Code and fingerprint from `secrets` (`app/pairing/services/service.py`); P-256 key checked when it is loaded or saved (`app/relay/credentials.py`); credentials written atomically with mode `0600` (`app/utils/files.py`, `app/pairing/services/credentials.py`)                                                                                                                                                 |
| Release and CI supply chain        | Code, dependencies, built artifacts              | Pull requests need one approving review plus the `Secret Scan` and `Dependency Audit` checks (`.github/workflows/security.yml`, [GOVERNANCE.md](GOVERNANCE.md#access)); actions and base images pinned by digest; release assets get build provenance and SBOM attestations (`.github/workflows/release.yml`); `r9cam_models` publishes through a PyPI trusted publisher (`.github/workflows/models-publish.yml`) |

### Secure design principles

- **Fail-safe defaults.** `APP_ENV=production` is the default. It refuses `DEBUG=true`, turns off the OpenAPI routes, blocks `TRACE` and serves only an allowlist of static file types (`app/core/settings.py`, `app/main.py`, `app/core/middleware.py`).
- **Least privilege.** The relay reaches only allowlisted routes, the image runs as a non-root user (`Dockerfile`), and Compose drops all capabilities and sets `no-new-privileges` (`compose.yml`). Workflows start from `contents: read`.
- **Complete mediation.** Protected routers share one `verify_request` dependency (`app/auth/dependencies.py`), and relay commands go through the same FastAPI auth after the allowlist, with the relay-local key (`app/relay/service.py`).
- **Economy of mechanism.** The Pi opens one outbound connection and needs no port open to the internet. One allowlist in `r9cam_models` serves both the backend and the plugin.
- **Open design.** Security rests on keys, not on secret code: the source, relay protocol and allowlist are public.

### Countering common weaknesses

- **Injection and path traversal.** Relay paths are unquoted repeatedly and `..` segments rejected before the allowlist check, and only trace headers pass the header filter (`r9cam_models/src/r9cam_models/device_seam.py`).
- **Input validation.** Pydantic schemas bound camera controls, upload metadata and stream keys at the edge (`app/camera/schemas.py`, `r9cam_models/`).
- **Brute force and abuse.** Login failures and sensitive actions are rate-limited per API key, session or client IP, in a sliding window (`app/core/middleware.py`).
- **Weak randomness and secret leaks.** Keys, tokens, codes and capture IDs come from `secrets`; logs redact secret fields, bearer tokens and PEM keys (`app/observability/logging.py`); responses send `Cache-Control: no-store` (`app/core/headers.py`).
- **Untested edge cases.** Atheris fuzzes raw relay frames through ClusterFuzzLite on every pull request that touches the app, the models or the dependencies (`fuzz/relay_frames.py`, `.github/workflows/cflite-pr.yml`). Mutation testing of the relay boundary and upload queue runs with `just mutation` against `tests/mutation-baseline.txt`. CI runs ruff with `select = ["ALL"]`, ty, and pytest with an 80% coverage floor (`.github/workflows/ci.yml`, `pyproject.toml`).
- **Vulnerable dependencies and leaked secrets.** `uv audit` and gitleaks gate merges (`.github/workflows/security.yml`), Trivy scans the image (`.github/workflows/container.yml`), CodeQL and Scorecard run on GitHub (`.github/workflows/scorecard.yml`), and Renovate keeps pins current (`.github/renovate.json`).
