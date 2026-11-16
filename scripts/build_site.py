#!/usr/bin/env python3
"""Build a small static site (index.html + RSS feed.xml) from the digests.

Usage: build_site.py [OUT_DIR]      (default: site/)
Optional environment: GITHUB_REPOSITORY (owner/name) and SITE_URL (public base URL).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from digestlib import ROOT, entry_link, load_state, parse_date, parse_digest

DIGEST_DIR = ROOT / "digest"
WEEKLY_DIR = DIGEST_DIR / "weekly"
MAX_PAGE_ENTRIES = 100
MAX_FEED_ENTRIES = 30

CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--link:#0969da}
@media (prefers-color-scheme:dark)
{:root{--bg:#0d1117;--fg:#e6edf3;--muted:#9198a1;--line:#3d444d;--link:#4493f8}}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0}
main{max-width:46rem;margin:0 auto;padding:1.5rem 1rem}
a{color:var(--link)} h1{margin:0 0 .25rem} .muted{color:var(--muted);font-size:.9rem}
article{border-top:1px solid var(--line);padding:1rem 0} h2{font-size:1.1rem;margin:0}
ul{margin:.4rem 0 0 1.2rem;padding:0}
"""


def info_for(entry):
    page = DIGEST_DIR / f"{entry['date']}.md"
    return parse_digest(page.read_text(encoding="utf-8")) if page.exists() else parse_digest("")


def summary_html(summary):
    """Render the 3-bullet summary safely: bullets become <li>, everything is escaped."""
    items = [ln.lstrip("-* ").strip() for ln in summary.splitlines() if ln.strip().startswith(("-", "*"))]
    if items:
        return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"
    return f"<p>{escape(summary)}</p>" if summary else ""


def glance_html(info):
    """The free 'At a glance' facts, all HTML-escaped."""
    parts = []
    if info["excerpt"]:
        parts.append(f"<p class='muted'>{escape(info['excerpt'])}</p>")
    extras = []
    if info["install"]:
        extras.append(f"Install: <code>{escape(info['install'])}</code>")
    if info["release"]:
        extras.append(f"Latest release: {escape(info['release'])}")
    if extras:
        parts.append("<p class='muted'>" + " &middot; ".join(extras) + "</p>")
    return "".join(parts)


def default_site_url():
    if os.getenv("SITE_URL"):
        return os.environ["SITE_URL"].rstrip("/") + "/"
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def render_index(entries, weekly_files, site_url, repo_slug):
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>AI repo digest</title>",
        "<link rel='alternate' type='application/rss+xml' title='AI repo digest' href='feed.xml'>",
        f"<style>{CSS}</style></head><body><main>",
        "<h1>AI repo digest</h1>",
        "<p class='muted'>One popular, recently active AI repo per day. "
        "<a href='feed.xml'>RSS feed</a></p>",
    ]
    if weekly_files and repo_slug:
        links = " &middot; ".join(
            f"<a href='https://github.com/{escape(repo_slug)}/blob/main/digest/weekly/{escape(f)}'>"
            f"{escape(Path(f).stem)}</a>"
            for f in weekly_files[:8]
        )
        parts.append(f"<p class='muted'>Weekly roll-ups: {links}</p>")
    for e in entries:
        info = info_for(e)
        fork = f" &middot; <a href='{escape(e['fork_url'])}'>fork</a>" if e.get("fork_url") else ""
        parts.append(
            f"<article><h2><a href='https://github.com/{escape(e['repo'])}'>{escape(e['repo'])}</a></h2>"
            f"<div class='muted'>{escape(e['date'])} &middot; {e['stars']:,} stars &middot; "
            f"{escape(e['topic'])} &middot; {escape(info['language'])}{fork}</div>"
            f"<p>{escape(info['description'])}</p>{glance_html(info)}{summary_html(info['summary'])}</article>"
        )
    parts.append("</main></body></html>")
    return "\n".join(parts)


def render_feed(entries, site_url, now):
    items = []
    for e in entries:
        info = info_for(e)
        day = parse_date(e["date"])
        published = datetime(day.year, day.month, day.day, 7, tzinfo=timezone.utc)
        body = info["description"]
        for extra in (info["excerpt"], info["summary"]):
            if extra:
                body += "\n\n" + extra
        items.append(
            "<item>"
            f"<title>{xml_escape(e['repo'])}</title>"
            f"<link>{xml_escape(entry_link({'repo': e['repo']}))}</link>"
            f"<guid isPermaLink='false'>{xml_escape(site_url or 'digest')}#{xml_escape(e['date'])}</guid>"
            f"<pubDate>{format_datetime(published)}</pubDate>"
            f"<description>{xml_escape(body)}</description>"
            "</item>"
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>"
        "<title>AI repo digest</title>"
        f"<link>{xml_escape(site_url or 'https://github.com')}</link>"
        "<description>One popular, recently active AI repo per day.</description>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        + "".join(items)
        + "</channel></rss>"
    )


def build(out_dir, state=None, now=None):
    state = load_state() if state is None else state
    now = now or datetime.now(timezone.utc)
    entries = sorted(state, key=lambda e: e["date"], reverse=True)
    weekly = sorted((p.name for p in WEEKLY_DIR.glob("*.md")), reverse=True) if WEEKLY_DIR.exists() else []
    site_url = default_site_url()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(
        render_index(entries[:MAX_PAGE_ENTRIES], weekly, site_url, os.getenv("GITHUB_REPOSITORY", "")),
        encoding="utf-8",
    )
    (out / "feed.xml").write_text(render_feed(entries[:MAX_FEED_ENTRIES], site_url, now), encoding="utf-8")
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    out = build(argv[0] if argv else ROOT / "site")
    print(f"built {out}/index.html and {out}/feed.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
