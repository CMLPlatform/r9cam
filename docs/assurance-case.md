# Assurance case for r9cam

This section argues why the plugin meets its security requirements. The requirements are: only the paired R9lab backend and local operators with a key or session can drive the camera; device credentials never leave the Pi in clear; and a malformed or hostile input cannot reach code outside the routes meant for it. Each claim names the code or workflow that backs it. Reporting and scope live in [SECURITY.md](../SECURITY.md).

## Threat model

The Pi sits on a lab or home network and keeps one outbound connection to R9lab. We defend against:

- a network attacker who can read or change traffic between the Pi and R9lab or S3;
- a compromised or buggy backend that sends relay commands outside what the device should do;
- a host on the local network that calls the REST API without a key, or replays a browser session;
- a hostile web page that tries a cross-site write through the operator's browser;
- a malicious dependency, action or contributor change that reaches a release.

We do not defend against physical access to the Pi, root on the host, or an operator who exposes the API to the internet against [INSTALL.md](../INSTALL.md). User and tenant authorization belongs to R9lab, not to this device (see [Auth Boundaries](../ARCHITECTURE.md#auth-boundaries)).

## Trust boundaries

| Boundary                           | What crosses it                                  | Controls                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ---------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Device to platform WebSocket relay | Commands from the backend, responses from the Pi | `wss://` required outside development and the relay host pinned to the pairing host (`app/core/settings.py`); ES256 device assertion with a random `jti` (`app/relay/device_jwt.py`); envelope schema, 64 KiB frame limit, header cap and method/path allowlist (`r9cam_models/src/r9cam_models/device_seam.py`); queue depth and command concurrency limits (`app/relay/service.py`)                                                                         |
| Local REST API                     | Requests from the LAN and the operator UI        | `X-API-Key` checked with constant-time compare, or a server-side session cookie that is `HttpOnly` and `SameSite=Lax`; `Origin`/`Referer` check on cookie writes (`app/auth/dependencies.py`, `app/auth/router.py`); `/local-key` limited to local-network clients (`app/pairing/routers/local_key.py`); optional HTTPS when `TLS_CERT_FILE` and `TLS_KEY_FILE` are set, checked at startup with no fallback to HTTP (`app/core/settings.py`, `app/serve.py`) |
| MediaMTX and ffmpeg sidecars       | Preview frames, the YouTube egress command       | RTSP, HLS and the control API bound to `127.0.0.1`, RTMP, WebRTC and SRT off (`mediamtx.yml`); YouTube keys validated before they reach the `runOnReady` command (`app/camera/schemas.py`, `app/camera/streaming/mediamtx_client.py`); containers run read-only with all capabilities dropped (`compose.yml`)                                                                                                                                                 |
| S3 and upload sink                 | Capture bytes and metadata leaving the Pi        | HTTPS for remote S3, public URL templates and backend media URLs (`app/delivery/factory.py`, `app/backend/client.py`); size and pixel caps before upload or queueing (`app/camera/services/manager.py`, `app/delivery/queue.py`)                                                                                                                                                                                                                              |
| Pairing and the stored private key | Pairing code, relay credentials                  | Code and fingerprint from `secrets` (`app/pairing/services/service.py`); P-256 key checked when it is loaded or saved (`app/relay/credentials.py`); credentials written atomically with mode `0600` (`app/utils/files.py`, `app/pairing/services/credentials.py`)                                                                                                                                                                                             |
| Release and CI supply chain        | Code, dependencies, built artifacts              | Pull requests need one approving review plus the `Secret Scan` and `Dependency Audit` checks (`.github/workflows/security.yml`, [GOVERNANCE.md](../GOVERNANCE.md#access)); actions and base images pinned by digest; release assets get build provenance and SBOM attestations (`.github/workflows/release.yml`); `r9cam_models` publishes through a PyPI trusted publisher (`.github/workflows/models-publish.yml`)                                             |

## Secure design principles

- **Fail-safe defaults.** `APP_ENV=production` is the default. It refuses `DEBUG=true`, turns off the OpenAPI routes, blocks `TRACE` and serves only an allowlist of static file types (`app/core/settings.py`, `app/main.py`, `app/core/middleware.py`).
- **Least privilege.** The relay reaches only allowlisted routes, the image runs as a non-root user (`Dockerfile`), and Compose drops all capabilities and sets `no-new-privileges` (`compose.yml`). Workflows start from `contents: read`.
- **Complete mediation.** Protected routers share one `verify_request` dependency (`app/auth/dependencies.py`), and relay commands go through the same FastAPI auth after the allowlist, with the relay-local key (`app/relay/service.py`).
- **Economy of mechanism.** The Pi opens one outbound connection and needs no port open to the internet. One allowlist in `r9cam_models` serves both the backend and the plugin.
- **Open design.** Security rests on keys, not on secret code: the source, relay protocol and allowlist are public.

## Countering common weaknesses

- **Injection and path traversal.** Relay paths are unquoted repeatedly and `..` segments rejected before the allowlist check, and only trace headers pass the header filter (`r9cam_models/src/r9cam_models/device_seam.py`).
- **Input validation.** Pydantic schemas bound camera controls, upload metadata and stream keys at the edge (`app/camera/schemas.py`, `r9cam_models/`).
- **Brute force and abuse.** Login failures and sensitive actions are rate-limited per API key, session or client IP, in a sliding window (`app/core/middleware.py`).
- **Weak randomness and secret leaks.** Keys, tokens, codes and capture IDs come from `secrets`; logs redact secret fields, bearer tokens and PEM keys (`app/observability/logging.py`); responses send `Cache-Control: no-store` (`app/core/headers.py`).
- **Untested edge cases.** Atheris fuzzes raw relay frames through ClusterFuzzLite on every pull request that touches the app, the models or the dependencies (`fuzz/relay_frames.py`, `.github/workflows/cflite-pr.yml`). Mutation testing of the relay boundary and upload queue runs with `just mutation` against `tests/mutation-baseline.txt`. CI runs ruff with `select = ["ALL"]`, ty, and pytest with an 80% coverage floor (`.github/workflows/ci.yml`, `pyproject.toml`).
- **Vulnerable dependencies and leaked secrets.** `uv audit` and gitleaks gate merges (`.github/workflows/security.yml`), Trivy scans the image (`.github/workflows/container.yml`), CodeQL and Scorecard run on GitHub (`.github/workflows/scorecard.yml`), and Renovate keeps pins current (`.github/renovate.json`).
