"""The "Contribute" board: open beginner-friendly issues from the repos the digest has featured.

Read-only. It lists issues with links and never comments on, claims or opens anything. Issue
titles are untrusted, so everything goes through glance.pick_opportunities (which cleans titles
and builds links from issue numbers) and is HTML-escaped on output. Standard library only.
"""
from __future__ import annotations

import sys
import urllib.parse
from html import escape

from digestlib import HEAD_ICON
from fork_inventory import fetch as fetch_json
from glance import pick_opportunities

DEFAULT_LABELS = ("good first issue", "help wanted")
MAX_REPOS = 40          # newest picks to look at (2 API calls each)
PER_REPO = 3            # issues kept per repo
MAX_FAILURES = 3        # stop early when GitHub keeps failing (rate limit, outage)


def fetch_board(entries, today, labels=DEFAULT_LABELS, max_repos=MAX_REPOS, per_repo=PER_REPO,
                max_age_days=180, get=fetch_json):
    """[{"repo", "date", "issues": [...]}] for the newest picks that have open issues.

    A failed lookup skips that repo; several failures in a row stop the whole run. Never raises."""
    board, failures = [], 0
    for e in entries[:max_repos]:
        groups, failed = [], False
        for label in labels:
            q = urllib.parse.urlencode(
                {"state": "open", "labels": label, "per_page": 20, "sort": "updated", "direction": "desc"}
            )
            try:
                data = get(f"/repos/{e['repo']}/issues?{q}")
            except Exception as err:  # noqa: BLE001 - the board is a nicety, never break the build
                print(f"issues lookup failed for {e['repo']}: {err}", file=sys.stderr)
                failed = True
                break
            groups.append((label, data if isinstance(data, list) else []))
        if failed:
            failures += 1
            if failures >= MAX_FAILURES:
                break
            continue
        failures = 0
        issues = pick_opportunities(groups, e["repo"], today, per_repo, max_age_days)
        if issues:
            board.append({"repo": e["repo"], "date": e["date"], "issues": issues})
    return board


def render_board_page(css, board, generated_label):
    """contribute.html. `board` comes from fetch_board; every value is escaped."""
    total = sum(len(b["issues"]) for b in board)
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Contribute</title>",
        HEAD_ICON,
        f"<style>{css}</style></head><body><main>",
        "<header class='hero'><h1>Contribute</h1>",
        "<p class='muted'>Open <code>good first issue</code> and <code>help wanted</code> issues in "
        "projects the pipeline has processed. Unassigned and recently active when this page was built "
        f"({escape(generated_label)}). Read the project's contributing guide first, and "
        "check an issue is still open before starting.</p>",
        "<nav class='links'><a href='index.html'>Back to the index</a></nav></header>",
    ]
    if not board:
        parts.append("<p>No open beginner-friendly issues found right now. Check back later.</p>")
    else:
        parts.append(f"<p class='muted'>{total} issues across {len(board)} repos.</p>")
    for b in board:
        repo = escape(b["repo"])
        items = "".join(
            f"<li><a href='{escape(o['url'])}'>{escape(o['title'])}</a> "
            f"<span class='muted'>({escape(o['label'])}, updated {escape(o['updated'])})</span></li>"
            for o in b["issues"]
        )
        parts.append(
            f"<article><h2><a href='https://github.com/{repo}'>{repo}</a></h2>"
            f"<div class='muted'>featured {escape(b['date'])}</div><ul>{items}</ul></article>"
        )
    parts.append("</main></body></html>")
    return "\n".join(parts)
