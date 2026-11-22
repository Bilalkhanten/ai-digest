"""Shared helpers for the digest scripts. Standard library only."""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_NAME = "OSS Signal Pipeline"

# Favicon (an inline SVG written to favicon.svg by the site builder) and the browser theme colour.
FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><defs>"
    "<linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='#2da44e'/>"
    "<stop offset='1' stop-color='#1d6fd8'/></linearGradient></defs>"
    "<rect width='64' height='64' rx='14' fill='url(#g)'/><g fill='#fff'>"
    "<rect x='13' y='38' width='9' height='14' rx='2'/><rect x='27' y='28' width='9' height='24' rx='2'/>"
    "<rect x='41' y='14' width='9' height='38' rx='2'/></g></svg>"
)
HEAD_ICON = (
    "<link rel='icon' type='image/svg+xml' href='favicon.svg'>"
    "<meta name='theme-color' content='#0b1320'>"
)
ROOT = Path(__file__).resolve().parent.parent

# Topic areas used by the website filters and per-area feeds (overridable in config.json).
DEFAULT_AREAS = {
    "AI": [
        "llm", "ai-agents", "rag", "machine-learning", "generative-ai", "deep-learning", "mcp",
        "nlp", "computer-vision", "langchain", "robotics", "data-science", "diffusion",
    ],
    "Platform": [
        "kubernetes", "devops", "docker", "sre", "monitoring", "observability", "prometheus",
        "grafana", "opentelemetry", "terraform", "infrastructure-as-code", "gitops", "helm",
        "cloud-native", "platform-engineering", "ci-cd", "ansible", "service-mesh",
        "incident-response", "logging", "ebpf", "containers", "argocd",
    ],
}


def load_areas(path=None):
    """{area name: [topics]} from config.json, falling back to the built-in defaults."""
    path = Path(path) if path else ROOT / "config.json"
    try:
        areas = json.loads(path.read_text()).get("areas")
    except (OSError, ValueError):
        areas = None
    return areas if isinstance(areas, dict) and areas else DEFAULT_AREAS


def load_contribution_labels(path=None):
    """Issue labels to look for, from config.json (default: good first issue, help wanted)."""
    path = Path(path) if path else ROOT / "config.json"
    try:
        labels = json.loads(path.read_text()).get("contribution_labels")
    except (OSError, ValueError):
        labels = None
    ok = isinstance(labels, list) and labels and all(isinstance(x, str) and x.strip() for x in labels)
    return list(labels) if ok else ["good first issue", "help wanted"]


def area_for(topic, areas):
    """The area a topic belongs to, or "Other"."""
    for name, topics in areas.items():
        if topic in topics:
            return name
    return "Other"


def area_slug(name):
    """File-name-safe version of an area name, e.g. "Platform" -> "platform"."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "other"


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
    info: dict[str, Any] = {
        "description": "", "language": "n/a", "license": "n/a", "summary": "",
        "excerpt": "", "install": "", "release": "", "reason": "",
        "whatsnew": "", "advisories": "", "opportunities": [], "contributing": "",
    }
    m = re.search(r"^> (.+)$", text, re.M)
    if m:
        info["description"] = m.group(1).strip()
    for key, label in (("language", "Language"), ("license", "License")):
        m = re.search(rf"^- {label}: (.+)$", text, re.M)
        if m:
            info[key] = m.group(1).strip()
    for key, pattern in (
        ("excerpt", r"^README excerpt: (.+)$"),
        ("install", r"^Install: `(.+)`$"),
        ("release", r"^- Latest release: (.+)$"),
        ("reason", r"^- Why picked: (.+)$"),
        ("whatsnew", r"^What's new: (.+)$"),
        ("advisories", r"^- Security advisories: (.+)$"),
    ):
        m = re.search(pattern, text, re.M)
        if m:
            info[key] = m.group(1).strip()
    for m in re.finditer(
        r"^- \[([^\]]+)\]\((https://github\.com/[^)\s]+)\) \(([^,()]+), updated ([^)]+)\)$", text, re.M
    ):
        info["opportunities"].append(
            {"title": m.group(1), "url": m.group(2), "label": m.group(3), "updated": m.group(4)}
        )
    m = re.search(r"^Contributing guide: (https://github\.com/\S+)$", text, re.M)
    if m:
        info["contributing"] = m.group(1)
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
