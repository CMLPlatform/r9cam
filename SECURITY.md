# Security Policy

## Supported Versions

Security fixes go into the latest release of the plugin app and the latest release of `r9cam_models`. Older releases do not get backported fixes, so upgrade to the latest release to pick them up.

## Report a vulnerability

Please do not open a public issue or pull request for a security problem: anyone can read those before there is a fix. Report it privately through GitHub's "Report a vulnerability" form:

<https://github.com/CMLPlatform/r9cam/security/advisories/new>

Please include:

- What the problem is and where: the affected version, and the endpoint, file or setting.
- How to reproduce it, or a proof of concept.
- The impact you expect, for example on the Pi, its camera or the paired R9lab platform.

We acknowledge a report within 5 business days, then tell you whether we can reproduce it and when we expect a fix. This matches the [R9lab platform policy](https://github.com/CMLPlatform/r9lab/blob/main/.github/SECURITY.md).

## Fixes and disclosure

A fix ships in a new release. When the release is out, we publish the GitHub security advisory for it, with a CVE where one applies, and credit you unless you would rather not be named. The release notes link the advisory.

## Scope

In scope:

- The plugin app: its HTTP API, setup UI, local-access and pairing flows, and API-key and session auth.
- The outbound WebSocket relay, the upload queue and the S3 sink.
- The camera, preview and streaming paths, including the MediaMTX and ffmpeg configuration the plugin ships.
- The `r9cam_models` package and this repository's own CI and release workflows.
- The `Dockerfile` and `compose.yml` defaults.

Out of scope:

- A vulnerability in a dependency, such as FastAPI, MediaMTX, ffmpeg or Raspberry Pi OS. Report it upstream; a pin or setting this repository should change is in scope.
- A weakness in the R9lab platform itself. Report it as the [platform policy](https://github.com/CMLPlatform/r9lab/blob/main/.github/SECURITY.md) says.
- A deployment that exposes the plugin to the internet without the access controls [INSTALL.md](INSTALL.md) describes, or physical access to the Pi.
