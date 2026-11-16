#!/usr/bin/env python3
"""Fail if any checked commit is not solely authored by an allowed identity.

Rules, applied to each commit in the range:
  * the author email must be in .github/allowed-authors.txt
  * the committer email must be an allowed email, or GitHub's own noreply address (which is
    the committer when a commit is made or merged in the web UI)
  * no "Co-authored-by:" line may name anyone outside the allowed list

Which commits are checked (first match wins):
  1. BASE_SHA..HEAD_SHA when both are set and BASE_SHA exists (push and pull request events)
  2. commits on HEAD_SHA that are not on origin/main (new branches)
  3. the whole history of HEAD_SHA (default HEAD)

Standard library only. Exit code 1 lists every offending commit.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED_FILE = ROOT / ".github" / "allowed-authors.txt"
GITHUB_NOREPLY = "noreply@github.com"       # committer of web-UI merges and edits
ZERO_SHA = "0" * 40
SEP = "\x1f"
END = "\x1e"


def load_allowed(path=ALLOWED_FILE):
    emails = set()
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            emails.add(line)
    return emails


def git(args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def rev_args(base, head, cwd=ROOT):
    """The `git log` revision arguments for the commits to check."""
    head = head or "HEAD"
    if base and base != ZERO_SHA and git(["cat-file", "-e", f"{base}^{{commit}}"], cwd).returncode == 0:
        return [f"{base}..{head}"]
    if git(["rev-parse", "--verify", "-q", "origin/main"], cwd).returncode == 0:
        return [head, "--not", "origin/main"]
    return [head]


def commits(revs, cwd=ROOT):
    fmt = SEP.join(["%H", "%an", "%ae", "%cn", "%ce", "%B"]) + END
    out = git(["log", f"--format={fmt}", *revs], cwd)
    if out.returncode != 0:
        raise SystemExit(f"git log failed: {out.stderr.strip()}")
    rows = []
    for chunk in out.stdout.split(END):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, an, ae, cn, ce, body = chunk.split(SEP, 5)
        rows.append({"sha": sha, "author": f"{an} <{ae}>", "ae": ae.lower(), "committer": f"{cn} <{ce}>",
                     "ce": ce.lower(), "body": body})
    return rows


def coauthor_emails(body):
    """Emails named in Co-authored-by trailers (case-insensitive)."""
    found = re.findall(r"^\s*co-authored-by:\s*(.*)$", body, re.I | re.M)
    emails = []
    for entry in found:
        m = re.search(r"<([^>]*)>", entry)
        emails.append((m.group(1) if m else entry).strip().lower())
    return emails


def problems(commit, allowed):
    out = []
    if commit["ae"] not in allowed:
        out.append(f"author {commit['author']} is not an allowed identity")
    if commit["ce"] not in allowed and commit["ce"] != GITHUB_NOREPLY:
        out.append(f"committer {commit['committer']} is not an allowed identity")
    for email in coauthor_emails(commit["body"]):
        if email not in allowed:
            out.append(f"Co-authored-by names {email or 'someone'}")
    return out


def check(revs, allowed, cwd=ROOT):
    """Return {sha: [problems]} for offending commits among `revs`."""
    bad = {}
    for c in commits(revs, cwd):
        found = problems(c, allowed)
        if found:
            bad[c["sha"]] = found
    return bad


def main():
    allowed = load_allowed()
    if not allowed:
        raise SystemExit(f"{ALLOWED_FILE} lists no allowed identities")
    revs = rev_args(os.getenv("BASE_SHA", ""), os.getenv("HEAD_SHA", ""))
    checked = len(commits(revs))
    bad = check(revs, allowed)
    lines = ["### Sole-author check", ""]
    lines.append(f"Checked {checked} commit(s) against {len(allowed)} allowed identity(ies).")
    if bad:
        lines += ["", "**Problems found:**"]
        for sha, found in bad.items():
            lines += [f"- `{sha[:7]}`: " + "; ".join(found)]
    else:
        lines += ["", "All commits are solely authored by an allowed identity."]
    report = "\n".join(lines) + "\n"
    print(report)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
