#!/usr/bin/env python3
"""Fail (exit 1) when the daily digest has stopped appearing.

Scheduled GitHub workflows are sometimes delayed or skipped, and a silent gap is easy to
miss. This checks the newest entry in forked.json against today's date (UTC).

Environment: OVERDUE_DAYS (default 2) = alert when the newest digest is at least this old.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from digestlib import load_state, parse_date


def evaluate(state, today, overdue_days=2):
    """Return (ok, message). `today` is a date."""
    if not state:
        return True, "No digests yet; nothing to check."
    last = max(parse_date(e["date"]) for e in state)
    gap = (today - last).days
    if gap >= overdue_days:
        return False, (
            f"The newest digest is from {last} ({gap} days ago). The daily run may be failing or "
            "GitHub skipped the schedule. Check the Actions tab."
        )
    return True, f"Newest digest is from {last} ({gap} days ago). On schedule."


def main():
    overdue = int(os.getenv("OVERDUE_DAYS", "2"))
    ok, message = evaluate(load_state(), datetime.now(timezone.utc).date(), overdue)
    print(message)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Watchdog\n\n{message}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
