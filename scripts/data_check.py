#!/usr/bin/env python3
"""Validate the repository's own data files. Exit 1 and list every problem found.

Checks (all structural, so a template change never makes it fail):
  * forked.json is a JSON list of well-formed entries (date, repo, stars, topic, fork_url),
    with no duplicate dates or repos and no dates in the future
  * every entry has a digest page digest/<date>.md whose heading and "Date picked" line match,
    and every digest page belongs to an entry
  * INDEX.md has one row per entry and mentions every repo
  * the README "latest picks" block lists the newest entries
  * weekly pages are named YYYY-Www.md and start with "# Week YYYY-Www"
  * config.json topics are unique and every topic belongs to exactly one area

Standard library only. Usage: data_check.py [ROOT]
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
LATEST_START, LATEST_END = "<!-- LATEST-PICKS:START -->", "<!-- LATEST-PICKS:END -->"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FORK_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DIGEST_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
WEEKLY_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")
LATEST_COUNT = 7


def _parse_day(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def check_state(state, today):
    """Problems in the list of entries itself. Returns (problems, usable entries)."""
    problems, usable = [], []
    if not isinstance(state, list):
        return ["forked.json is not a JSON list"], []
    seen_dates, seen_repos = {}, {}
    for i, e in enumerate(state):
        where = f"forked.json entry {i}"
        if not isinstance(e, dict):
            problems.append(f"{where} is not an object")
            continue
        ok = True
        day = _parse_day(e.get("date"))
        if day is None:
            problems.append(f"{where}: bad or missing date {e.get('date')!r}")
            ok = False
        elif day > today:
            problems.append(f"{where}: date {e['date']} is in the future")
        if not isinstance(e.get("repo"), str) or not REPO_RE.match(e["repo"]):
            problems.append(f"{where}: bad repo {e.get('repo')!r}")
            ok = False
        if not isinstance(e.get("stars"), int) or isinstance(e.get("stars"), bool) or e["stars"] < 0:
            problems.append(f"{where}: stars must be a non-negative integer, got {e.get('stars')!r}")
        if not isinstance(e.get("topic"), str) or not e["topic"].strip():
            problems.append(f"{where}: missing topic")
        fork = e.get("fork_url")
        if fork is not None and (not isinstance(fork, str) or not FORK_RE.match(fork)):
            problems.append(f"{where}: bad fork_url {fork!r}")
        if not ok:
            continue
        if e["date"] in seen_dates:
            problems.append(f"{where}: duplicate date {e['date']} (also entry {seen_dates[e['date']]})")
        if e["repo"].lower() in seen_repos:
            first = seen_repos[e["repo"].lower()]
            problems.append(f"{where}: repo {e['repo']} was already picked (entry {first})")
        seen_dates.setdefault(e["date"], i)
        seen_repos.setdefault(e["repo"].lower(), i)
        usable.append(e)
    return problems, usable


def check_digests(root, entries):
    problems = []
    digest_dir = root / "digest"
    expected = set()
    for e in entries:
        name = f"{e['date']}.md"
        expected.add(name)
        path = digest_dir / name
        if not path.exists():
            problems.append(f"digest/{name} is missing (entry for {e['repo']})")
            continue
        text = path.read_text(encoding="utf-8")
        heading = re.match(r"# (\S+)", text)
        if not heading or heading.group(1) != e["repo"]:
            problems.append(f"digest/{name}: heading is {heading.group(1) if heading else 'missing'}, "
                            f"expected {e['repo']}")
        m = re.search(r"^- Date picked: (\d{4}-\d{2}-\d{2})", text, re.M)
        if not m or m.group(1) != e["date"]:
            problems.append(f"digest/{name}: 'Date picked' line does not match {e['date']}")
    if digest_dir.exists():
        for p in sorted(digest_dir.glob("*.md")):
            if DIGEST_RE.match(p.name) and p.name not in expected:
                problems.append(f"digest/{p.name} has no entry in forked.json")
    return problems


def check_index(root, entries):
    path = root / "INDEX.md"
    if not path.exists():
        return ["INDEX.md is missing"] if entries else []
    text = path.read_text(encoding="utf-8")
    rows = re.findall(r"^\| \d{4}-\d{2}-\d{2} \|", text, re.M)
    problems = []
    if len(rows) != len(entries):
        problems.append(f"INDEX.md has {len(rows)} rows but forked.json has {len(entries)} entries")
    for e in entries:
        if e["repo"] not in text:
            problems.append(f"INDEX.md does not mention {e['repo']}")
    return problems


def check_readme(root, entries):
    path = root / "README.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    a, b = text.find(LATEST_START), text.find(LATEST_END)
    if a == -1 or b == -1 or b < a:
        return []                      # the block is optional
    block = text[a + len(LATEST_START): b]
    shown = re.findall(r"^\| (\d{4}-\d{2}-\d{2}) \| \[([^\]]+)\]", block, re.M)
    newest = sorted(entries, key=lambda e: e["date"], reverse=True)[:LATEST_COUNT]
    want = [(e["date"], e["repo"]) for e in newest]
    if shown != want:
        return [f"README latest-picks block is out of date: shows {len(shown)} rows, expected {len(want)} "
                f"(newest {want[0][0] if want else 'none'})"]
    return []


def check_weekly(root):
    problems = []
    weekly = root / "digest" / "weekly"
    if not weekly.exists():
        return problems
    for p in sorted(weekly.glob("*.md")):
        m = WEEKLY_RE.match(p.name)
        if not m:
            problems.append(f"digest/weekly/{p.name}: name is not YYYY-Www.md")
            continue
        try:
            date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            problems.append(f"digest/weekly/{p.name}: not a real ISO week")
            continue
        first = p.read_text(encoding="utf-8").splitlines()[:1]
        if first != [f"# Week {p.stem}"]:
            problems.append(f"digest/weekly/{p.name}: first line should be '# Week {p.stem}'")
    return problems


def check_config(root):
    path = root / "config.json"
    if not path.exists():
        return []
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"config.json is not valid JSON: {e}"]
    problems = []
    topics = cfg.get("topics", [])
    if len(topics) != len(set(topics)):
        problems.append("config.json: duplicate topics")
    areas = cfg.get("areas")
    if isinstance(areas, dict):
        listed = [t for ts in areas.values() for t in ts]
        if len(listed) != len(set(listed)):
            problems.append("config.json: a topic is listed in more than one area")
        missing = sorted(set(topics) - set(listed))
        if missing:
            problems.append(f"config.json: topics without an area: {', '.join(missing)}")
        extra = sorted(set(listed) - set(topics))
        if extra:
            problems.append(f"config.json: area topics that are not in the rotation: {', '.join(extra)}")
    return problems


def check(root, today=None):
    """All problems found under `root` (empty list = healthy)."""
    root = Path(root)
    today = today or datetime.now(timezone.utc).date()
    state_path = root / "forked.json"
    if not state_path.exists():
        return ["forked.json is missing"]
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"forked.json is not valid JSON: {e}"]
    problems, entries = check_state(state, today)
    problems += check_digests(root, entries)
    problems += check_index(root, entries)
    problems += check_readme(root, entries)
    problems += check_weekly(root)
    problems += check_config(root)
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = Path(argv[0]) if argv else DEFAULT_ROOT
    problems = check(root)
    lines = ["### Data check", ""]
    if problems:
        lines.append(f"**{len(problems)} problem(s) found:**")
        lines += [f"- {p}" for p in problems]
    else:
        lines.append("All data files are consistent.")
    report = "\n".join(lines) + "\n"
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
