# Governance

r9cam is a small research software project. This page says who decides what and who can change the repository.

## Maintainer

The project has one maintainer, the author listed in [CITATION.cff](CITATION.cff). The maintainer reviews and merges pull requests, triages issues, cuts releases of the plugin app and of `r9cam_models`, and handles security reports as described in [SECURITY.md](SECURITY.md).

## Decisions

The maintainer makes the final call on features, design, releases and what goes on the [roadmap](ROADMAP.md). Larger design choices are written down as architecture decision records in [docs/adr/](docs/adr/), so the reasoning stays visible.

Anyone can propose a change by opening an issue or a pull request. Proposals are discussed in the open on that issue or pull request. Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](.github/CODE_OF_CONDUCT.md).

## Access

- Only the maintainer has write and admin access to the repository, its release workflows and the PyPI trusted publisher for `r9cam_models`.
- Renovate opens dependency pull requests, and the release workflow pushes the version bump commit and tag.
- All other changes reach `main` through pull requests that pass CI.
- Repository secrets are limited to what CI and the release workflows need.

## Changes to This Document

If the project gains more maintainers, this page will be updated to say how they are added, how decisions are made among them and how access is granted and removed. The maintainer changes this page through a normal pull request.
