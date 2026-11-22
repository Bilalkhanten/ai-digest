# Security policy

## Reporting a vulnerability

Please report security problems privately rather than in a public issue. On GitHub, open the
**Security** tab and choose **Report a vulnerability** (private vulnerability reporting). If that
option is not available, open an issue that says only that you have a security concern, with no
details, and the maintainer will arrange a private channel.

You can expect an acknowledgement within a few days. This is a personal project, so fixes are
best-effort, but credible reports are taken seriously.

## What is in scope

- The scripts and workflows in this repository (`scripts/`, `.github/workflows/`).
- The incident copilot in `copilot/` and its published npm package and container image
  (`@bilalkhanten/incident-copilot`, `ghcr.io/bilalkhanten/incident-copilot`).

Of particular interest: anything that lets the copilot change cluster state (it is designed to be
read-only), leaks a credential, or injects content into a generated page, feed or query.

## Supported versions

Only the latest release of the incident copilot and the current `main` branch are supported.

## How the project reduces risk

- Workflows start with no permissions, and each job asks for the minimum.
- Third-party actions are pinned to commit SHAs.
- The fork token is a classic token limited to `public_repo`, and its expiry is monitored.
- All third-party text (README excerpts, issue titles, release notes) is treated as untrusted and
  sanitised or escaped before it is written to a page.
- The copilot can run only `kubectl get pods|events -n <name> -o json`, validates names before they
  reach a query, and redacts secrets from its output.
- CI includes a sole-author check, type checking, a coverage floor, and a real-cluster end-to-end test.
