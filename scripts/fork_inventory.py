#!/usr/bin/env python3
"""Report on the forks this tool has made. Read-only: it never deletes anything.

Usage: fork_inventory.py [REPORT.md]     (default: print to stdout)
Optional environment: GH_TOKEN (raises the API rate limit), PRUNE_AFTER_DAYS (default 180).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

from digestlib import load_state, parse_date

API = "https://api.github.com"
MAX_ROWS = 100
PRUNE_AFTER_DAYS = int(os.getenv("PRUNE_AFTER_DAYS", "180"))


def fetch(path):
    """GET a public repo. Returns the JSON dict, or None when it no longer exists (404)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-repo-digest-inventory",
    }
    if os.getenv("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{API}{path}", headers=headers), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fork_slug(url):
    return url.removeprefix("https://github.com/").strip("/")


def inspect_fork(entry, today, get=fetch):
    fork = fork_slug(entry["fork_url"])
    original = get(f"/repos/{entry['repo']}")
    age = (today - parse_date(entry["date"])).days
    reasons = []
    if original is None:
        reasons.append("original deleted")
    elif original.get("archived"):
        reasons.append("original archived")
    if age >= PRUNE_AFTER_DAYS:
        reasons.append(f"older than {PRUNE_AFTER_DAYS} days")
    return {
        "date": entry["date"],
        "fork": fork,
        "original": entry["repo"],
        "stars_now": original.get("stargazers_count") if original else None,
        "age": age,
        "reasons": reasons,
    }


def render(entries, today, get=fetch):
    forks = sorted((e for e in entries if e.get("fork_url")), key=lambda e: e["date"], reverse=True)
    rows = [inspect_fork(e, today, get) for e in forks[:MAX_ROWS]]
    flagged = [r for r in rows if r["reasons"]]
    out = [
        "## Monthly fork inventory",
        "",
        f"{len(forks)} forks made by this tool ({len(entries) - len(forks)} digest-only days). "
        f"Showing the newest {len(rows)}. Nothing is deleted automatically.",
        "",
        f"### Candidates to review ({len(flagged)})",
        "",
    ]
    if flagged:
        out += ["| Fork | Why | Delete |", "|---|---|---|"]
        out += [
            f"| [{r['fork']}](https://github.com/{r['fork']}) | {', '.join(r['reasons'])} | "
            f"[settings](https://github.com/{r['fork']}/settings) |"
            for r in flagged
        ]
    else:
        out.append("None.")
    out += ["", "### All inspected forks", ""]
    out += ["| Date | Fork | Original | Stars now | Age (days) |", "|---|---|---|---|---|"]
    out += [
        f"| {r['date']} | [{r['fork']}](https://github.com/{r['fork']}) | {r['original']} | "
        f"{r['stars_now'] if r['stars_now'] is not None else 'gone'} | {r['age']} |"
        for r in rows
    ]
    out += ["", "To delete a fork: open its settings page, scroll to Danger Zone,"]
    out[-1] += " choose Delete this repository."
    return "\n".join(out) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    report = render(load_state(), datetime.now(timezone.utc).date())
    if argv:
        with open(argv[0], "w", encoding="utf-8") as f:
            f.write(report)
        print(f"wrote {argv[0]}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
