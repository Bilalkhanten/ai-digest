#!/usr/bin/env python3
"""Check that the fork token still works and warn before it expires.

Standard library only. Environment variables:
  GH_TOKEN    the classic PAT used for forking (FORK_PAT)
  WARN_DAYS   fail when the token expires within this many days (default 14)

Exit code 0 = healthy, 1 = problem (details printed, and written to the job summary).
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
WARN_DAYS = int(os.getenv("WARN_DAYS", "14"))
# Anything beyond this is more access than the tool needs.
EXPECTED_SCOPES = {"public_repo"}


def fetch_user(token):
    """Return (status, headers) for GET /user."""
    req = urllib.request.Request(
        f"{API}/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-repo-digest-health",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers


def parse_expiry(value):
    """Parse GitHub's 'YYYY-MM-DD HH:MM:SS UTC' expiry header. None if absent/unparseable."""
    if not value:
        return None
    try:
        return datetime.strptime(value.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def evaluate(status, headers, now=None):
    """Return (problems, notes) as lists of strings."""
    now = now or datetime.now(timezone.utc)
    problems, notes = [], []
    if status != 200:
        problems.append(f"Token rejected by GitHub (HTTP {status}). It may be expired or revoked.")
        return problems, notes

    scopes = {s.strip() for s in (headers.get("X-OAuth-Scopes") or "").split(",") if s.strip()}
    extra = scopes - EXPECTED_SCOPES
    if "public_repo" not in scopes:
        problems.append(f"Token is missing the public_repo scope (has: {sorted(scopes) or 'none'}).")
    if extra:
        problems.append(
            f"Token has broader scopes than needed: {sorted(extra)}. Regenerate with public_repo only."
        )

    expiry = parse_expiry(headers.get("github-authentication-token-expiration"))
    if expiry is None:
        notes.append("Token has no expiry date (or GitHub did not report one). Consider setting one.")
    else:
        days_left = (expiry - now).days
        notes.append(f"Token expires {expiry:%Y-%m-%d} ({days_left} days left).")
        if days_left < 0:
            problems.append("Token has expired.")
        elif days_left <= WARN_DAYS:
            problems.append(
                f"Token expires in {days_left} days ({expiry:%Y-%m-%d}). "
                "Regenerate it and update the FORK_PAT secret."
            )

    remaining = headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        notes.append(f"API rate limit remaining: {remaining}.")
    return problems, notes


def main():
    token = os.getenv("GH_TOKEN", "")
    if not token:
        print("GH_TOKEN is not set (is the FORK_PAT secret missing?).", file=sys.stderr)
        return 1
    status, headers = fetch_user(token)
    problems, notes = evaluate(status, headers)

    lines = ["### Token health", ""]
    lines += [f"- OK: {n}" for n in notes]
    lines += [f"- PROBLEM: {p}" for p in problems]
    if not problems:
        lines.append("- All checks passed.")
    report = "\n".join(lines) + "\n"
    print(report)

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
