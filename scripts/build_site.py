#!/usr/bin/env python3
"""Build a small static site from the digests: index.html, stats.html, feed.xml, digests.json.

Usage: build_site.py [OUT_DIR]      (default: site/)
Optional environment: GITHUB_REPOSITORY (owner/name) and SITE_URL (public base URL).
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from board import fetch_board, render_board_page
from digestlib import (
    ROOT, area_for, area_slug, entry_link, load_areas, load_contribution_labels, load_state, parse_date,
    parse_digest,
)
from fork_inventory import fetch as fetch_repo
from stats import digests_json, render_stats_page

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
[hidden]{display:none!important}
input[type=search]{font:inherit;width:100%;box-sizing:border-box;padding:.4rem .6rem;color:var(--fg);
background:transparent;border:1px solid var(--line);border-radius:.4rem;margin:.5rem 0}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;margin:.75rem 0}
.chip{font:inherit;font-size:.85rem;color:var(--fg);background:transparent;border:1px solid var(--line);
border-radius:999px;padding:.15rem .7rem;cursor:pointer}
.chip span{color:var(--muted)}
.chip[aria-pressed=true]{background:var(--link);border-color:var(--link);color:var(--bg)}
.chip[aria-pressed=true] span{color:var(--bg)}
"""


FILTER_JS = """
(function(){
  var fnav=document.getElementById('filters'); if(!fnav) return;
  var anav=document.getElementById('areas');
  var arts=document.querySelectorAll('article[data-topic]');
  var area='', topic='', query='';
  var box=document.getElementById('q');
  function press(nav, btn){
    nav.querySelectorAll('button').forEach(function(x){
      x.setAttribute('aria-pressed', x===btn?'true':'false');
    });
  }
  function apply(){
    arts.forEach(function(a){
      a.hidden=(area!==''&&a.getAttribute('data-area')!==area)||(topic!==''&&a.getAttribute('data-topic')!==topic)||
        (query!==''&&a.textContent.toLowerCase().indexOf(query)===-1);
    });
    fnav.querySelectorAll('button').forEach(function(b){
      var t=b.getAttribute('data-topic');
      b.hidden=(t!==''&&area!==''&&b.getAttribute('data-area')!==area);
    });
  }
  fnav.hidden=false;
  if(box){
    box.hidden=false;
    box.addEventListener('input',function(){ query=box.value.trim().toLowerCase(); apply(); });
  }
  fnav.addEventListener('click',function(e){
    var b=e.target.closest('button[data-topic]'); if(!b) return;
    topic=b.getAttribute('data-topic'); press(fnav,b); apply();
  });
  if(anav){
    anav.hidden=false;
    anav.addEventListener('click',function(e){
      var b=e.target.closest('button[data-area]'); if(!b) return;
      area=b.getAttribute('data-area'); topic=''; press(anav,b);
      press(fnav,fnav.querySelector('button[data-topic=""]')); apply();
    });
  }
})();
"""
MAX_CHIPS = 12


def _chip(attrs, label, count, pressed):
    return (
        f"<button class='chip' {attrs} aria-pressed='{pressed}'>"
        f"{escape(label)} <span>{count}</span></button>"
    )


def chips_html(entries, areas=None):
    """Area and topic buttons. Hidden until JavaScript runs, so no dead buttons without it.

    Topics are capped per area (most common first); the area bar only appears if there is
    more than one area."""
    areas = areas or load_areas()
    counts = Counter(e["topic"] for e in entries)
    area_of = {t: area_for(t, areas) for t in counts}
    per_area = Counter()
    for e in entries:
        per_area[area_of[e["topic"]]] += 1
    chosen = []
    for name in per_area:
        in_area = [(t, n) for t, n in counts.items() if area_of[t] == name]
        chosen += sorted(in_area, key=lambda kv: (-kv[1], kv[0]))[:MAX_CHIPS]
    chosen.sort(key=lambda kv: (-kv[1], kv[0]))

    topic_buttons = [_chip("data-topic='' data-area=''", "All", len(entries), "true")]
    topic_buttons += [
        _chip(f"data-topic='{escape(t)}' data-area='{escape(area_of[t])}'", t, n, "false") for t, n in chosen
    ]
    search = "<input id='q' type='search' placeholder='Search picks' aria-label='Search picks' hidden>"
    topic_nav = "<nav id='filters' class='chips' aria-label='Filter by topic' hidden>"
    topic_nav += "".join(topic_buttons) + "</nav>"
    if len(per_area) < 2:
        return search + topic_nav
    area_buttons = [_chip("data-area=''", "All areas", len(entries), "true")]
    area_buttons += [
        _chip(f"data-area='{escape(name)}'", name, n, "false")
        for name, n in sorted(per_area.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    area_nav = "<nav id='areas' class='chips' aria-label='Filter by area' hidden>"
    area_nav += "".join(area_buttons) + "</nav>"
    return search + area_nav + topic_nav


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
    if info["whatsnew"]:
        parts.append(f"<p class='muted'>What's new: {escape(info['whatsnew'])}</p>")
    extras = []
    if info["install"]:
        extras.append(f"Install: <code>{escape(info['install'])}</code>")
    if info["release"]:
        extras.append(f"Latest release: {escape(info['release'])}")
    if info["advisories"]:
        extras.append(f"Security advisories: {escape(info['advisories'])}")
    if extras:
        parts.append("<p class='muted'>" + " &middot; ".join(extras) + "</p>")
    if info.get("opportunities"):
        items = "".join(
            f"<li><a href='{escape(o['url'])}'>{escape(o['title'])}</a> "
            f"<span class='muted'>({escape(o['label'])}, updated {escape(o['updated'])})</span></li>"
            for o in info["opportunities"]
        )
        guide = (
            f" <a href='{escape(info['contributing'])}'>Contributing guide</a>"
            if info.get("contributing") else ""
        )
        parts.append(f"<p class='muted'>Ways to contribute:{guide}</p><ul>{items}</ul>")
    return "".join(parts)


def default_site_url():
    if os.getenv("SITE_URL"):
        return os.environ["SITE_URL"].rstrip("/") + "/"
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def render_index(entries, weekly_files, site_url, repo_slug, areas=None, feeds=None, show_contribute=False):
    areas = areas or load_areas()
    feeds = feeds or [("All", "feed.xml")]
    alternates = "".join(
        f"<link rel='alternate' type='application/rss+xml' title='Repo digest: {escape(label)}' "
        f"href='{escape(file)}'>"
        for label, file in feeds
    )
    feed_links = " &middot; ".join(f"<a href='{escape(file)}'>{escape(label)}</a>" for label, file in feeds)
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>Repo digest</title>",
        alternates,
        f"<style>{CSS}</style></head><body><main>",
        "<h1>Repo digest</h1>",
        "<p class='muted'>One popular, recently active open-source repo per day "
        "(AI, DevOps, Kubernetes, SRE and more). "
        f"RSS: {feed_links} &middot; <a href='stats.html'>Stats</a> &middot; "
        + ("<a href='contribute.html'>Contribute</a> &middot; " if show_contribute else "")
        + "<a href='digests.json'>Open data</a></p>",
    ]
    if weekly_files and repo_slug:
        links = " &middot; ".join(
            f"<a href='https://github.com/{escape(repo_slug)}/blob/main/digest/weekly/{escape(f)}'>"
            f"{escape(Path(f).stem)}</a>"
            for f in weekly_files[:8]
        )
        parts.append(f"<p class='muted'>Weekly roll-ups: {links}</p>")
    if entries:
        parts.append(chips_html(entries, areas))
    for e in entries:
        info = info_for(e)
        fork = f" &middot; <a href='{escape(e['fork_url'])}'>fork</a>" if e.get("fork_url") else ""
        lang = f" &middot; {escape(info['language'])}" if info["language"] != "n/a" else ""
        parts.append(
            f"<article data-topic='{escape(e['topic'])}' data-area='{escape(area_for(e['topic'], areas))}'>"
            f"<h2><a href='https://github.com/{escape(e['repo'])}'>{escape(e['repo'])}</a></h2>"
            f"<div class='muted'>{escape(e['date'])} &middot; {e['stars']:,} stars &middot; "
            f"{escape(e['topic'])}{lang}{fork}</div>"
            f"<p>{escape(info['description'])}</p>{glance_html(info)}{summary_html(info['summary'])}</article>"
        )
    parts.append(f"</main><script>{FILTER_JS}</script></body></html>")
    return "\n".join(parts)


def render_feed(entries, site_url, now, title="Repo digest"):
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
        f"<title>{xml_escape(title)}</title>"
        f"<link>{xml_escape(site_url or 'https://github.com')}</link>"
        "<description>One popular, recently active open-source repo per day.</description>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        + "".join(items)
        + "</channel></rss>"
    )


def fetch_stars(entries, limit=100):
    """Current star counts for the newest picks. A failed lookup just leaves that repo out."""
    out, failures = {}, 0
    for e in entries[:limit]:
        try:
            repo = fetch_repo(f"/repos/{e['repo']}")
        except Exception as err:  # noqa: BLE001 - stats are a nicety, never break the build
            failures += 1
            print(f"stars lookup failed for {e['repo']}: {err}", file=sys.stderr)
            if failures >= 3:
                break
            continue
        if repo:
            out[e["repo"]] = repo.get("stargazers_count")
    return out


WEEKLY_NAME = re.compile(r"^(\d{4})-W(\d{2})$")
WEEKLY_ROW = re.compile(r"^\| (\d{4}-\d{2}-\d{2}) \| \[([^\]]+)\]\([^)]*\) \| ([\d,]+) \| ([^|]*?) \|", re.M)
MAX_WEEKLY_ITEMS = 12


def parse_weekly(text):
    """Pull the intro line, the repo rows and the themes paragraph out of a weekly page."""
    intro = re.search(r"^(\d+ repos? featured, [^\n]+)$", text, re.M)
    themes = re.search(r"^## Themes\s*\n+(.+?)(?:\n\s*\n|\Z)", text, re.M | re.S)
    return {
        "intro": intro.group(1) if intro else "",
        "themes": themes.group(1).strip() if themes else "",
        "repos": [(r, int(s.replace(",", "")), t.strip()) for _, r, s, t in WEEKLY_ROW.findall(text)],
    }


def weekly_items(weekly_dir, repo_slug, site_url):
    """Feed items for the weekly pages, newest week first."""
    items = []
    for path in sorted(Path(weekly_dir).glob("*.md"), reverse=True)[:MAX_WEEKLY_ITEMS]:
        m = WEEKLY_NAME.match(path.stem)
        if not m:
            continue
        try:
            sunday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 7)
        except ValueError:
            continue
        info = parse_weekly(path.read_text(encoding="utf-8"))
        lines = [info["intro"]] if info["intro"] else []
        if info["themes"]:
            lines.append(info["themes"])
        lines += [f"{r} ({s:,} stars, {t})" for r, s, t in info["repos"]]
        link = site_url
        if repo_slug:
            link = f"https://github.com/{repo_slug}/blob/main/digest/weekly/{path.name}"
        items.append({
            "title": f"Week {path.stem}",
            "link": link or "https://github.com",
            "guid": f"{site_url or 'digest'}#weekly-{path.stem}",
            "published": datetime(sunday.year, sunday.month, sunday.day, 18, 23, tzinfo=timezone.utc),
            "description": "\n".join(lines),
        })
    return items


def render_weekly_feed(items, site_url, now):
    body = "".join(
        "<item>"
        f"<title>{xml_escape(i['title'])}</title>"
        f"<link>{xml_escape(i['link'])}</link>"
        f"<guid isPermaLink='false'>{xml_escape(i['guid'])}</guid>"
        f"<pubDate>{format_datetime(i['published'])}</pubDate>"
        f"<description>{xml_escape(i['description'])}</description>"
        "</item>"
        for i in items
    )
    return (
        "<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>"
        "<title>Repo digest: weekly roll-ups</title>"
        f"<link>{xml_escape(site_url or 'https://github.com')}</link>"
        "<description>One summary per week of the repos featured in the digest.</description>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>{body}</channel></rss>"
    )


def build(out_dir, state=None, now=None, stars_now=None, areas=None, board=None):
    state = load_state() if state is None else state
    now = now or datetime.now(timezone.utc)
    entries = sorted(state, key=lambda e: e["date"], reverse=True)
    weekly = sorted((p.name for p in WEEKLY_DIR.glob("*.md")), reverse=True) if WEEKLY_DIR.exists() else []
    site_url = default_site_url()
    areas = areas or load_areas()
    present = sorted({area_for(e["topic"], areas) for e in entries})
    feeds = [("All", "feed.xml")]
    if len(present) > 1:
        feeds += [(name, f"feed-{area_slug(name)}.xml") for name in present]
    slug = os.getenv("GITHUB_REPOSITORY", "")
    weekly_feed_items = weekly_items(WEEKLY_DIR, slug, site_url) if weekly else []
    if weekly_feed_items:
        feeds.append(("Weekly", "feed-weekly.xml"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(
        render_index(
            entries[:MAX_PAGE_ENTRIES], weekly, site_url, os.getenv("GITHUB_REPOSITORY", ""), areas, feeds,
            show_contribute=board is not None,
        ),
        encoding="utf-8",
    )
    (out / "feed.xml").write_text(render_feed(entries[:MAX_FEED_ENTRIES], site_url, now), encoding="utf-8")
    for name, file in feeds[1:]:
        if file == "feed-weekly.xml":
            continue
        mine = [e for e in entries if area_for(e["topic"], areas) == name][:MAX_FEED_ENTRIES]
        (out / file).write_text(render_feed(mine, site_url, now, f"Repo digest: {name}"), encoding="utf-8")
    if weekly_feed_items:
        weekly_xml = render_weekly_feed(weekly_feed_items, site_url, now)
        (out / "feed-weekly.xml").write_text(weekly_xml, encoding="utf-8")
    if board is not None:
        (out / "contribute.html").write_text(
            render_board_page(CSS, board, now.strftime("%Y-%m-%d %H:%M UTC")), encoding="utf-8"
        )
    infos = [info_for(e) for e in entries]
    (out / "stats.html").write_text(
        render_stats_page(
            CSS, entries, infos, stars_now or {}, now.date(), now.strftime("%Y-%m-%d %H:%M UTC"), areas
        ),
        encoding="utf-8",
    )
    (out / "digests.json").write_text(
        json.dumps(digests_json(entries, infos, now.isoformat(timespec="seconds"), areas), indent=2) + "\n",
        encoding="utf-8",
    )
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    state = load_state()
    newest = sorted(state, key=lambda e: e["date"], reverse=True)
    stars_now = fetch_stars(newest)
    board = fetch_board(newest, datetime.now(timezone.utc).date(), load_contribution_labels())
    out = build(argv[0] if argv else ROOT / "site", state=state, stars_now=stars_now, board=board)
    print(f"built {out}: index.html, stats.html, contribute.html, feed.xml, digests.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
