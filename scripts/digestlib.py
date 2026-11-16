"""Shared helpers for the digest scripts. Standard library only."""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_state(path=None):
    """Return the list of digest entries from forked.json ([] if missing)."""
    path = Path(path) if path else ROOT / "forked.json"
    return json.loads(path.read_text()) if path.exists() else []


def entry_link(entry):
    """Link for a digest entry: the fork if one was made, else the original repo."""
    return entry.get("fork_url") or f"https://github.com/{entry['repo']}"


def parse_date(value):
    return date.fromisoformat(value)


def parse_digest(text):
    """Pull the fields we need back out of a rendered digest page."""
    info = {"description": "", "language": "n/a", "license": "n/a", "summary": ""}
    m = re.search(r"^> (.+)$", text, re.M)
    if m:
        info["description"] = m.group(1).strip()
    for key, label in (("language", "Language"), ("license", "License")):
        m = re.search(rf"^- {label}: (.+)$", text, re.M)
        if m:
            info[key] = m.group(1).strip()
    m = re.search(r"^## Summary\s*\n(.*)\Z", text, re.M | re.S)
    if m:
        info["summary"] = m.group(1).strip()
    return info


def ask_claude(prompt, key, model, max_tokens=400):
    """One-shot Claude call. Returns "" on any failure; the summary is optional."""
    if not key:
        return ""
    body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    except Exception as e:  # noqa: BLE001 - optional feature must never break a run
        import sys

        print(f"Claude call skipped: {e}", file=sys.stderr)
        return ""
