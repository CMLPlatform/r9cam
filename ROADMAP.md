# Roadmap

This is a short view of what is planned for r9cam. It is a plan, not a promise, and it changes as needs change. Released work is in [CHANGELOG.md](CHANGELOG.md). Ideas and bugs are tracked as GitHub issues. [GOVERNANCE.md](GOVERNANCE.md) says who decides what goes here.

## Now

- Release the rename from `relab` to `r9cam` as the next minor version. This covers the plugin, the `r9cam_models` package, the config directory and the relay token audience. Existing Pis must be paired again, as [INSTALL.md](INSTALL.md) explains.
- Ship the fixes merged since v0.6.2, such as pairing polls that use POST with a JSON body and refreshed locks past dependency advisories.
- Finish the project hygiene files: security policy, code of conduct, governance and this roadmap.

## Next

- Keep the CodSpeed benchmarks and the container smoke test green on every pull request, and add benchmarks when a change touches an uncovered hot path.
- Keep dependency, Action and image pins current, and fix findings within the windows set in [CONTRIBUTING.md](CONTRIBUTING.md#security-maintenance).

## Later

- Keep the `r9cam_models` contract stable for the R9lab backend, and version any breaking change to it on its own release line.
- Test camera behavior on more Raspberry Pi models and camera modules.
