# Roadmap

This is a short view of what is planned for r9cam. It is a plan, not a promise, and it changes as needs change. Released work is in [CHANGELOG.md](CHANGELOG.md). Ideas and bugs are tracked as GitHub issues. [GOVERNANCE.md](GOVERNANCE.md) says who decides what goes here.

- Release the rename from `relab` to `r9cam` as the next minor version. This covers the plugin, the `r9cam_models` package, the config directory and the relay token audience. Existing Pis must be paired again, as [INSTALL.md](INSTALL.md) explains.
- Ship the fixes merged since v0.6.2, such as pairing polls that use POST with a JSON body and refreshed locks past dependency advisories.
- Test metadata parsing against a dict recorded from a real camera ([#53](https://github.com/CMLPlatform/r9cam/issues/53)).
