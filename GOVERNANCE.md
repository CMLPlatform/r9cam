# Governance

r9cam is a small research software project. This page says who decides what and who can change the repository.

## Maintainer

The project has one maintainer, named in [CONTRIBUTING.md](CONTRIBUTING.md#who-maintains-this) together with the person who takes over if they cannot continue. The maintainer reviews and merges pull requests, triages issues, cuts releases of the plugin app and of `r9cam_models`, and handles security reports as described in [SECURITY.md](SECURITY.md).

## Decisions

The maintainer makes the final call on features, design, releases and what goes on the [roadmap](ROADMAP.md). Larger design choices are written down as architecture decision records in [docs/adr/](docs/adr/), so the reasoning stays visible.

Anyone can propose a change by opening an issue or a pull request. Proposals are discussed in the open on that issue or pull request. Contributions follow [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](.github/CODE_OF_CONDUCT.md).

## Access

- Seven GitHub accounts have admin access to the repository: @simonvanlierde, @FDonati, @bfdb, @TomerFishman, @robyistrate, @mrvisscher and @SoniaMCunha. Nobody has write access without admin.
- Who may publish `r9cam_models` on PyPI: PLACEHOLDER, the maintainer lists the PyPI owners here. The API gives no view of them.
- The release workflows publish the plugin app and, through a PyPI trusted publisher, `r9cam_models`. The version bump reaches `main` through a pull request like any other change. Publishing the GitHub release creates the tag, and the release workflow then uploads the distributions.
- Changes to `main` go through pull requests that need one approving review and the `Secret Scan` and `Dependency Audit` checks, on an up-to-date branch. Admins and the Renovate app may merge without the review. Only admins may skip the checks, which sit in a ruleset of their own. Force-pushes and deletion are blocked.
- Renovate opens the dependency pull requests.

## Changes to This Document

The maintainer changes this page through a normal pull request. If the project gains more maintainers, the page will say how they are added and how decisions are made among them.
