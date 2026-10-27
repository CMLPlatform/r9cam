# Installation And Setup Guide

This guide is for operators installing and running the RPI Camera Plugin on a Raspberry Pi.

## Requirements

### Hardware

- Raspberry Pi 5 or Raspberry Pi 4
- Raspberry Pi Camera Module 3 or v2
- MicroSD card, 8 GB or larger
- Power supply
- Ethernet or WiFi network
- Camera mount

### Software

- Raspberry Pi OS 64-bit
- Python 3.13+
- Docker Compose for the recommended runtime
- Network access to the R9lab backend for paired mode

## Prepare The Pi

1. Install Raspberry Pi OS using the [official Raspberry Pi guide](https://www.raspberrypi.com/documentation/computers/getting-started.html#installing-the-operating-system).

1. Connect the camera module using the [camera module guide](https://www.raspberrypi.com/documentation/accessories/camera.html#connect-the-camera).

1. Confirm the camera is visible:

   ```sh
   rpicam-hello
   ```

1. Clone the plugin:

   ```sh
   git clone https://github.com/CMLPlatform/r9cam.git r9cam
   cd r9cam
   cp .env.example .env
   ```

## Paired R9lab Mode

Paired mode connects the Pi to R9lab through an outbound WebSocket relay. The Pi does not need a public IP address or inbound port forwarding.

Set the pairing backend URL in `.env`:

```sh
PAIRING_BACKEND_URL=https://api.r9lab.io
```

Start the plugin with Docker Compose:

```sh
./scripts/generate_compose_override.py > compose.override.yml
docker compose pull
docker compose up -d
```

`docker compose pull` fetches the signed arm64 image `ghcr.io/cmlplatform/r9cam` that each release publishes, so the Pi does not build it. The tag is `latest` unless `R9CAM_VERSION` in `.env` pins a version such as `0.7.0`. `latest` is mutable: it moves with each release. To check what the Pi actually pulled, verify the digest of the pulled image, not the tag. Run this on the Pi:

```sh
docker image inspect --format '{{index .RepoDigests 0}}' ghcr.io/cmlplatform/r9cam:0.7.0
```

Then run this anywhere with the GitHub CLI, with the `ghcr.io/cmlplatform/r9cam@sha256:...` value it printed:

```sh
gh attestation verify oci://ghcr.io/cmlplatform/r9cam@sha256:<digest> --repo CMLPlatform/r9cam
```

To upgrade, run `git pull` (for `compose.yml` and the other config files), then `docker compose pull` and `docker compose up -d`.

Review `compose.override.yml` before startup. It should contain only current camera device nodes such as `/dev/media*`, `/dev/video*`, `/dev/v4l-subdev*`, and `/dev/dma_heap`. Regenerate it after kernel, camera, or hardware changes; do not use `privileged: true`.

View logs:

```sh
docker compose logs -f app
```

### Pair The Camera

When pairing mode is active, read the code from either surface:

- browser UI: `http://your-pi-ip:8018/setup`
- logs: the `PAIRING READY` banner

Treat `/setup` and pairing logs as local/operator-only during pairing. The code is a short-lived bootstrap credential; anyone who can reach either surface during its 10-minute window can try to claim the camera.

The setup page polls `GET /pairing/state` so it can reload when pairing or unpairing completes. That endpoint is intentionally public and returns only low-detail state (`status` and `relay_enabled`); it does not expose the pairing code, relay credentials, local API key, backend URLs, or camera IDs.

Enter the code in the native R9lab app under Cameras > Add Camera. The Pi receives relay credentials, saves them to `~/.config/r9cam/relay_credentials.json`, and connects to the backend.

To rotate the code without deleting relay credentials, use **Generate a new pairing code** on `/setup`.
To rotate relay credentials, unpair the camera and pair it again. Unpairing clears the stored relay key first, and the next pairing creates a fresh key pair.

Docker Compose stores runtime credentials in a named volume mounted at `/home/r9cam/.config/r9cam`, so paired credentials survive container restarts.

The relay signing key is stored in `relay_credentials.json` with `0o600` permissions. Against SD-card theft, use full-disk encryption (LUKS); to keep the key off disk entirely, skip pairing and inject `RELAY_PRIVATE_KEY_PEM` (with `RELAY_CAMERA_ID`, `RELAY_KEY_ID`, `RELAY_AUTH_SCHEME`) via env.

The HTTPS-served R9lab web frontend cannot auto-probe the Pi's plain-HTTP local API because browsers block mixed content. Use the native app for pairing and direct-mode setup.

## Upgrading From 0.6

Upgrade the R9lab backend first. This release needs a backend that serves the `/v1/plugins/r9cam` routes and accepts the `r9cam-relay` token audience. The hosted `api.r9lab.io` does; a self-hosted R9lab v0.5.0 or older does not. Against an older backend the relay handshake is refused: the relay keeps retrying with backoff and logs the refused status, but never connects. Pis on 0.6 keep working with a current backend until 2027-01-31, so upgrade them before then.

Paired cameras keep their pairing in these cases:

- **Docker Compose, upgraded in place** (`git pull` in the existing checkout): the `relay_credentials` volume keeps its name and is now mounted at `/home/r9cam/.config/r9cam`.
- **Without Docker:** the app still reads `~/.config/relab/relay_credentials.json` while `~/.config/r9cam/relay_credentials.json` does not exist. The next write moves it to the new path and deletes the old file. `RELAB_CREDENTIALS_FILE` still works when `R9CAM_CREDENTIALS_FILE` is unset, with a warning to rename it.
- **Standalone installs:** set `R9CAM_IMAGE=r9cam` in `.env`, then run `docker compose build` and `docker compose up -d`. Do not run `docker compose pull`: it fetches the paired image, which has no S3 support, and the S3 sink stops working.

A fresh clone into an `r9cam/` directory is a new Compose project, so it starts with new, empty volumes: no credentials and no upload queue. Bring the old project down first with `docker compose -p relab-rpi-cam-plugin down`, then pair again, or copy the `relay_credentials` and `app_data` volumes from the old project to the new one.

Renamed in this release:

| What                         | 0.6                         | Now                                                                                                            |
| ---------------------------- | --------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Credentials file override    | `RELAB_CREDENTIALS_FILE`    | `R9CAM_CREDENTIALS_FILE`                                                                                       |
| mDNS service type            | `_relab-rpi-cam._tcp`       | `_r9cam._tcp` (an existing avahi service file keeps working, since clients reach the Pi at `<hostname>.local`) |
| OpenTelemetry `service.name` | `relab-rpi-cam-plugin`      | `r9cam`                                                                                                        |
| `service` in `/healthz`      | `relab-rpi-cam`             | `r9cam`                                                                                                        |
| Session cookie               | `relab_session`             | `r9cam_session` (signed-in browsers sign in once more)                                                         |
| Compose image name           | `relab-rpi-cam-plugin`      | `ghcr.io/cmlplatform/r9cam`, pulled instead of built                                                           |
| OpenAPI file                 | `openapi.rpi-cam.json`      | `openapi.r9cam.json`                                                                                           |
| Prometheus metrics           | `rpi_cam_*`                 | `r9cam_*`, for example `r9cam_cpu_percent`                                                                     |
| Alloy `job` label            | `rpi-cam-plugin`            | `r9cam`                                                                                                        |
| Default Alloy `instance`     | `rpi-cam-plugin`            | `r9cam` (when `OBSERVABILITY_INSTANCE` is unset)                                                               |
| S3 object key prefix         | `rpi-cam/`                  | `r9cam/` (objects already stored stay under `rpi-cam/`)                                                        |
| Example S3 bucket            | `rpi-cam`                   | `r9cam` (an existing `S3_BUCKET` in `.env` is kept)                                                            |
| Container user and home      | `rpicam`, `/home/rpicam`    | `r9cam`, `/home/r9cam` (same uid 1000)                                                                         |
| Default pairing backend      | `https://api.cml-relab.org` | `https://api.r9lab.io`                                                                                         |

## Standalone Mode

Standalone mode stores captures in an S3-compatible bucket instead of the R9lab backend. The bundled standalone profile starts a local RustFS sidecar. The release image is paired mode only, so standalone builds its own image on the Pi under the local name `r9cam`.

Set these values in `.env`:

```sh
APP_BUILD_TARGET=runtime-standalone
R9CAM_IMAGE=r9cam
COMPOSE_PROFILES=standalone
APP_ENV=development

IMAGE_SINK=s3
S3_ENDPOINT_URL=http://127.0.0.1:9000
S3_BUCKET=r9cam
S3_ACCESS_KEY_ID=rustfsadmin
S3_SECRET_ACCESS_KEY=change-me-to-a-strong-password
RUSTFS_SECRET_KEY=change-me-to-a-strong-password
```

Start the stack:

```sh
docker compose build
docker compose up -d
```

Runtime surfaces:

- Camera API: `http://<pi-lan-ip>:8018`
- Setup UI: `http://<pi-lan-ip>:8018/setup`
- RustFS console: `http://127.0.0.1:9001`
- Captures: `http://127.0.0.1:9000/r9cam/`

RustFS is loopback-only by default. To expose it on the operator LAN, set `RUSTFS_API_BIND` and `RUSTFS_CONSOLE_BIND` to the Pi's LAN IP, then restrict ports `9000` and `9001` to trusted clients.

For an external S3-compatible service such as Backblaze B2, Cloudflare R2, Wasabi, or AWS S3, set `S3_ENDPOINT_URL`, credentials, and `S3_PUBLIC_URL_TEMPLATE`. Remote production S3 endpoints and remote public URL templates require HTTPS. Keep `APP_ENV=development` for local HTTP storage only.

Treat captures as sensitive device data. Current captures are always `.jpg` / `image/jpeg`, are bounded before upload or queueing, and are checked again before retry or serving. Failed uploads can stay in the local retry queue or dead-letter directory until the queue limits prune them. `S3_PUBLIC_URL_TEMPLATE` makes images as public as the bucket or proxy behind it, so use private or authenticated storage when needed.

If you rotate S3 or RustFS credentials, update the storage service first, then refresh `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, and `RUSTFS_SECRET_KEY` if needed.

Set `COMPOSE_PROFILES=` to skip the RustFS sidecar when using a managed bucket.

## Local Direct Mode

Local direct mode is enabled by default. On first boot, the plugin generates and persists a local API key. Local clients call the Pi API with:

```sh
X-API-Key: <local-api-key>
```

Paired R9lab apps can fetch the key through the relay and switch to LAN/Ethernet direct access for lower preview latency. Custom clients can use the key without pairing.

Retrieve the key from an SSH session:

```sh
just show-key
```

Or read it directly from the credentials file:

```sh
python3 -c "import json,pathlib; print(json.loads((pathlib.Path.home()/'.config/r9cam/relay_credentials.json').read_text()).get('local_api_key',''))"
```

Disable direct local API access with:

```sh
LOCAL_MODE_ENABLED=false
```

To rotate the local API key, stop the app, remove `local_api_key` from `~/.config/r9cam/relay_credentials.json` or delete the credentials file when you re-pair, then start the app again. Custom clients using the old key will need the new one.

Transport security:

- The local API is plain **HTTP** by design — the API key and setup data cross the LAN unencrypted, so keep port `8018` on a trusted network. Outbound traffic (backend, `wss://` relay, S3, OTLP) is always TLS.
- For TLS, front the API with a reverse proxy and set `BASE_URL=https://<host>` (enables HSTS, silences the plaintext-LAN startup warning).

Network notes:

- Keep app port `8018` reachable only on trusted operator networks.
- MediaMTX RTSP `8554` and HLS `8888` bind to `127.0.0.1`; preview traffic goes through the app.
- Ethernet link-local addressing (`169.254.x.x`) works when no DHCP server is present.
- USB gadget mode applies to Raspberry Pi Zero 2W and some Raspberry Pi 4 revisions, not Raspberry Pi 5.
- mDNS is optional. Install `avahi-daemon` and advertise `_r9cam._tcp` on port 8018 to reach the Pi at `<hostname>.local`.

## Direct Python Run

For a non-Docker run on the Pi:

```sh
./scripts/local_setup.sh
uv run fastapi run app/main.py --host 0.0.0.0 --port 8018 --forwarded-allow-ips 127.0.0.1,::1
```

## Verify The Service

Once running, check:

- setup and status: `http://your-pi-ip:8018/setup`
- API reference: <https://docs.r9lab.io/api/rpi-cam/>
- HLS preview: `http://your-pi-ip:8018/preview/hls/cam-preview/index.m3u8`

For headless operation, read pairing status from:

- Docker Compose: `docker compose logs app`
- systemd/journald, if you run it under your own unit: `journalctl -u <your-unit> -f`
- direct shell run: the `PAIRING READY` terminal banner

## Observability

Structured JSON logs are always written. Docker logs are bounded by Compose config, and rotating file logs are written to the mounted `app_logs` volume.

Log inventory:

- app file logs: UTC JSON in `app_logs`, rotated daily
- Docker logs: redacted console output
- optional shipped logs: Alloy tails `app_logs` and pushes to the configured collector
- security events: auth results, rate-limit denials, relay validation failures, and unhandled errors

Logs include request IDs where available and leave out credentials, tokens, pairing codes, private keys, request bodies, and response bodies.

To ship logs to a Loki-compatible collector, add:

```sh
COMPOSE_PROFILES=observability-ship
OBSERVABILITY_INSTANCE=pi-01
LOKI_PUSH_URL=https://your-observability-host/loki/api/v1/push
```

Use an authenticated collector with explicit log retention. Structured file logs
redact runtime secrets and omit local-only pairing banners, but collectors
remain operator-visible infrastructure.

To ship metrics, configure a remote-write endpoint and an API key for Alloy's
local scrape:

```sh
PROMETHEUS_REMOTE_WRITE_URL=https://your-observability-host/api/v1/write
PROMETHEUS_SCRAPE_API_KEY=change-me
AUTHORIZED_API_KEYS='["change-me"]'
```

The scrape key is sent only to the local plugin `/metrics` endpoint. Use scoped
collector credentials for remote-write when supported.

Tracing is opt-in:

```sh
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=https://your-observability-host:4318/v1/traces
```

Remote production OTLP endpoints require HTTPS. Plaintext HTTP is accepted only
for loopback collectors or when `APP_ENV=development`.
If you rotate `PROMETHEUS_SCRAPE_API_KEY`, `AUTHORIZED_API_KEYS`,
Loki/Prometheus tokens, or OTLP collector credentials, update the collector
first, then refresh `.env` and restart the stack.

Local Loki/Grafana and OTLP collectors are not bundled with this plugin.

Profiles can be combined:

```sh
COMPOSE_PROFILES=standalone,observability-ship
```

## Troubleshooting

### Camera Not Detected

```sh
rpicam-hello --list-cameras
```

Check the CSI cable orientation, camera seating, and camera module compatibility.

### API Does Not Start

- Check port 8018 availability: `sudo netstat -tlnp | grep :8018`
- Check logs: `docker compose logs app`
- For direct runs, start with `uv run fastapi run app/main.py --host 0.0.0.0 --port 8018 --forwarded-allow-ips 127.0.0.1,::1`

### Relay Does Not Connect

- Confirm `PAIRING_BACKEND_URL` points at the backend API origin.
- Confirm the Pi has outbound internet access.
- Confirm `~/.config/r9cam/relay_credentials.json` exists after pairing.
- Check logs: `docker compose logs app`
- `refusing to connect`: pairing returned a relay host that differs from the hostname in `PAIRING_BACKEND_URL`. The device only authenticates to the backend it paired with, so point `PAIRING_BACKEND_URL` at the host the backend actually serves the relay from. A different port on the same host is fine. Pairing stops instead of retrying and shows this message on the setup page; if the mismatch is in already-stored credentials, the relay stays off at boot with `Persisted relay credentials rejected` in the log and the device re-pairs.
- If the backend sits behind Cloudflare, add a WAF bypass for `/v1/plugins/r9cam/pairing/*`, `/v1/plugins/r9cam/device/*`, and `/v1/plugins/r9cam/ws/connect`.

### Pairing Code Not Showing

- Confirm `PAIRING_BACKEND_URL` is set in `.env`.
- Remove `~/.config/r9cam/relay_credentials.json` if pairing should restart.
- Check `/setup` and the `PAIRING MODE` / `PAIRING READY` log lines.
- In Docker, avoid `http://localhost:8011` for host services from inside the container. Use `http://host.docker.internal:8011`, the host LAN IP, or the real HTTPS API URL.

### Poor Image Quality

- Clean the camera lens gently.
- Improve lighting at the capture location.
- Check the camera module connection.
