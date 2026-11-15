# Assurance case for r9cam

Why r9cam meets its security requirements. [SECURITY.md](../SECURITY.md)
says how to report a vulnerability and what is in scope.

<!-- Keep the whole document near 1,000 words. One line per claim, each with a link to
     its evidence: a file, a test, a workflow or a decision record in docs/adr/.
     Link SECURITY.md and the architecture docs instead of restating them. Mark any
     claim nobody has checked "not verified". -->

## Threat model

<!-- Who would attack this, what they want, and what they can reach: users, contributors,
     dependencies, the CI and release path. Name what the project protects. -->

- Assets: TODO, e.g. the published releases and the users' data.
- Attackers: TODO, e.g. a malicious input, a compromised dependency, a hostile pull request.

## Trust boundaries

<!-- Every place where data or code crosses from less trusted to more trusted. One row each. -->

| Boundary | What crosses | How it is treated |
| --- | --- | --- |
| Pull request from a fork to CI | Untrusted code | TODO: runs without secrets, see `.github/workflows/` |
| Dependency registry to build | Third-party packages | TODO: pinned in lockfiles |
| TODO: user input to the program | TODO | TODO |

## Secure design principles

<!-- One line per principle, pointing at the row in "Weaknesses countered" that shows it. -->

- Least privilege: each workflow job gets only the token permissions it needs (W1).
- Fail-safe defaults: TODO (W3).
- Complete mediation: TODO, or "not verified".
- Economy of mechanism: TODO.

## Weaknesses countered

<!-- The common weaknesses that apply here (OWASP Top 10, CWE Top 25) and how each is
     countered. The evidence link is what a reader can open and check. -->

| Id | Threat | Counter | Evidence |
| --- | --- | --- | --- |
| W1 | A workflow token with more rights than it needs | `permissions:` set per job | `.github/workflows/` |
| W2 | A dependency with a known vulnerability | Lockfiles, a weekly advisory scan | `.github/workflows/advisories.yml` |
| W3 | TODO: e.g. injection through user input | TODO | TODO, or "not verified" |

## Residual risk

<!-- What is not countered, or not checked, and why that is accepted. Be honest: a
     short true list beats a long reassuring one. -->

- TODO
