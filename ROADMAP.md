# Roadmap

This is a short view of what is planned for r9cam over the next year, to October 2027. It is a plan, not a promise, and it changes as needs change. Released work is in [CHANGELOG.md](CHANGELOG.md). Ideas and bugs are tracked as GitHub issues. [GOVERNANCE.md](GOVERNANCE.md) says who decides what goes here.

## Planned

- Test metadata parsing against a dict recorded from a real camera ([#53](https://github.com/CMLPlatform/r9cam/issues/53)).
- Record provenance with every capture: plugin version and git commit, camera serial, tuning-file hash, and the lens position, colour gains and scaler crop used. An optional raw (DNG) capture and a colour-reference shot per session follow.
- Run hardware-in-the-loop tests on a self-hosted Raspberry Pi, on a schedule or by manual dispatch on `main` only, never from pull requests. They publish capture latency, upload p95 and SoC temperature.
- Build a teardown station kit once a second site joins: motion and lighting control behind their own seams, a relay command that captures a sequence of views, a bill of materials, print files and an assembly guide.
- Keep the contract with the R9lab platform stable: changes to `r9cam_models` stay backward compatible, and the package is released in step with the plugin.

## Not planned

- Local user accounts, roles or login federation. Identity stays with the R9lab platform; the plugin only checks local API keys.
- WebRTC preview, until the conditions in [ADR 0001](docs/adr/0001-preview-streaming-hls-over-relay.md) hold.
- Boards other than Raspberry Pi 5 and 4, and cameras other than Camera Module 3 and v2.
