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
    FAVICON_SVG, HEAD_ICON, PROJECT_NAME, ROOT, area_for, area_slug, entry_link, load_areas,
    load_contribution_labels, load_state, parse_date, parse_digest,
)
from fork_inventory import fetch as fetch_repo
from stats import digests_json, render_stats_page

DIGEST_DIR = ROOT / "digest"
WEEKLY_DIR = DIGEST_DIR / "weekly"
MAX_PAGE_ENTRIES = 100
MAX_FEED_ENTRIES = 30
SOCIAL_IMAGE = ROOT / "assets" / "social-preview.jpg"
NEW_DAYS = 1                     # picks this many days old (or newer) get a "new" badge

CSS = """
:root{--bg:#f6f8fa;--card:#fff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--link:#0969da;
--accent:#2da44e;
--shadow:0 1px 2px rgba(31,35,40,.06),0 4px 14px rgba(31,35,40,.05);--hero1:#0b1320;--hero2:#14304f;
--hero3:#1d5a8a}
@media (prefers-color-scheme:dark)
{:root{--bg:#0d1117;--card:#151b23;--fg:#e6edf3;--muted:#9198a1;--line:#30363d;--link:#58a6ff;
--accent:#3fb950;
--shadow:0 1px 2px rgba(0,0,0,.5)}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,
sans-serif;margin:0}
main{max-width:52rem;margin:0 auto;padding:0 1rem 2.5rem}
a{color:var(--link);text-underline-offset:2px}
:focus-visible{outline:2px solid var(--link);outline-offset:2px}
.muted{color:var(--muted);font-size:.9rem}
.hero{position:relative;overflow:hidden;margin:0 -1rem 1.25rem;padding:2rem 1.4rem 1.3rem 1.6rem;
color:#fff;
border-radius:0 0 18px 18px;background:linear-gradient(135deg,var(--hero1),var(--hero2) 55%,
var(--hero3))}
.hero::before{content:"";position:absolute;left:0;top:0;bottom:0;width:6px;
background:linear-gradient(#3fb950,#58a6ff)}
.hero::after{content:"";position:absolute;right:-60px;top:-80px;width:260px;height:260px;
border-radius:50%;
background:rgba(88,166,255,.10)}
.hero h1{position:relative;margin:0 0 .3rem;font-size:2.1rem;letter-spacing:-.02em;line-height:1.15;
color:#fff}
.hero .muted{position:relative;margin:0 0 .9rem;color:#b8d4f0;font-size:1rem}
.links{position:relative;display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;font-size:.85rem;
color:#b8d4f0}
.links a{color:#fff;text-decoration:none;background:rgba(255,255,255,.13);padding:.2rem .7rem;
border-radius:999px}
.links a:hover{background:rgba(255,255,255,.25)}
.links .sep{width:1px;height:1.1rem;background:rgba(255,255,255,.3);margin:0 .3rem}
h2{font-size:1.1rem;margin:0}
article{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1rem 1.2rem;
margin:.9rem 0;
box-shadow:var(--shadow);transition:border-color .15s,box-shadow .15s}
article:hover{border-color:var(--link);box-shadow:0 4px 18px rgba(9,105,218,.13)}
article h2{font-size:1.2rem;line-height:1.3}
article h2 a{color:var(--fg);text-decoration:none}
article h2 a:hover{color:var(--link)}
article .muted{font-size:.85rem}
article p{margin:.55rem 0}
article p.muted{line-height:1.5}
ul{margin:.5rem 0 0;padding:0;list-style:none}
li{margin:.3rem 0;padding:.35rem .7rem;border-left:3px solid var(--accent);
border-radius:0 8px 8px 0;
background:rgba(46,164,79,.08)}
code{font:.85em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:rgba(127,127,127,
.16);
padding:.1rem .35rem;border-radius:6px;word-break:break-word}
[hidden]{display:none!important}
input[type=search]{font:inherit;width:100%;padding:.65rem .95rem;color:var(--fg);
background:var(--card);
border:1px solid var(--line);border-radius:12px;margin:.5rem 0;box-shadow:var(--shadow)}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;margin:.6rem 0}
.chip{font:inherit;font-size:.85rem;color:var(--fg);background:var(--card);
border:1px solid var(--line);
border-radius:999px;padding:.2rem .8rem;cursor:pointer;transition:border-color .12s,transform .12s}
.chip:hover{border-color:var(--link);transform:translateY(-1px)}
.chip span{color:var(--muted)}
.chip[aria-pressed=true]{background:linear-gradient(135deg,#2da44e,#1d6fd8);
border-color:transparent;color:#fff}
.chip[aria-pressed=true] span{color:rgba(255,255,255,.8)}
.badge{display:inline-block;margin-left:.5rem;padding:0 .5rem;border-radius:999px;font-size:.7rem;
font-weight:600;letter-spacing:.03em;text-transform:uppercase;vertical-align:middle;color:#fff;
background:linear-gradient(135deg,#2da44e,#1d6fd8)}
.copy{font:inherit;font-size:.75rem;margin-left:.4rem;padding:.05rem .55rem;color:var(--fg);
background:var(--card);border:1px solid var(--line);border-radius:999px;cursor:pointer}
.copy:hover{border-color:var(--link)}
footer{margin-top:2rem;padding-top:1rem;border-top:1px solid var(--line);text-align:center}
@media (max-width:600px){.hero{padding:1.4rem 1rem 1.1rem 1.3rem}.hero h1{font-size:1.6rem}article{
padding:.9rem}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
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

# Adds a "Copy" button after each install command. Runs only where the clipboard API exists.
COPY_JS = """
(function(){
  if(!navigator.clipboard) return;
  document.querySelectorAll('article code').forEach(function(c){
    var prev=c.previousSibling;
    if(!prev||!/Install: *$/.test(prev.textContent||'')) return;
    var b=document.createElement('button'); b.type='button'; b.className='copy'; b.textContent='Copy';
    b.setAttribute('aria-label','Copy install command');
    b.addEventListener('click',function(){
      navigator.clipboard.writeText(c.textContent).then(function(){
        b.textContent='Copied'; setTimeout(function(){b.textContent='Copy';},1500);
      },function(){b.textContent='Failed';});
    });
    c.after(b);
  });
})();
"""


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


def social_meta(site_url, with_image):
    """Description and Open Graph / Twitter tags so links to the site preview well."""
    title = escape(PROJECT_NAME)
    desc = escape("Open-source projects scored on momentum: AI, DevOps, Kubernetes, SRE and more.")
    tags = [
        f"<meta name='description' content='{desc}'>",
        f"<meta property='og:title' content='{title}'>",
        f"<meta property='og:description' content='{desc}'>",
        "<meta property='og:type' content='website'>",
    ]
    if site_url:
        tags.append(f"<meta property='og:url' content='{escape(site_url)}'>")
        if with_image:
            tags.append(f"<meta property='og:image' content='{escape(site_url)}social-preview.jpg'>")
    tags.append(
        "<meta name='twitter:card' content='summary_large_image'>" if site_url and with_image
        else "<meta name='twitter:card' content='summary'>"
    )
    return "".join(tags)


def render_index(entries, weekly_files, site_url, repo_slug, areas=None, feeds=None, show_contribute=False,
                 today=None, social_image=False):
    areas = areas or load_areas()
    feeds = feeds or [("All", "feed.xml")]
    alternates = "".join(
        f"<link rel='alternate' type='application/rss+xml' title='{escape(PROJECT_NAME)}: {escape(label)}' "
        f"href='{escape(file)}'>"
        for label, file in feeds
    )
    feed_links = "".join(f"<a href='{escape(file)}'>{escape(label)}</a>" for label, file in feeds)
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{escape(PROJECT_NAME)}</title>",
        HEAD_ICON,
        social_meta(site_url, social_image),
        alternates,
        f"<style>{CSS}</style></head><body><main>",
        "<header class='hero'>",
        f"<h1>{escape(PROJECT_NAME)}</h1>",
        "<p class='muted'>Open-source projects scored on momentum "
        "(AI, DevOps, Kubernetes, SRE and more).</p>",
        f"<nav class='links' aria-label='Site links'><span>RSS</span>{feed_links}<span class='sep'></span>"
        "<a href='stats.html'>Stats</a>"
        + ("<a href='contribute.html'>Contribute</a>" if show_contribute else "")
        + "<a href='digests.json'>Open data</a></nav>",
        "</header>",
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
        age = (today - parse_date(e["date"])).days if today else None
        fresh = " <span class='badge'>new</span>" if age is not None and 0 <= age <= NEW_DAYS else ""
        parts.append(
            f"<article data-topic='{escape(e['topic'])}' data-area='{escape(area_for(e['topic'], areas))}'>"
            f"<h2><a href='https://github.com/{escape(e['repo'])}'>{escape(e['repo'])}</a>{fresh}</h2>"
            f"<div class='muted'>{escape(e['date'])} &middot; {e['stars']:,} stars &middot; "
            f"{escape(e['topic'])}{lang}{fork}</div>"
            f"<p>{escape(info['description'])}</p>{glance_html(info)}{summary_html(info['summary'])}</article>"
        )
    source = (
        f" &middot; <a href='https://github.com/{escape(repo_slug)}'>Source</a>" if repo_slug else ""
    )
    parts.append(
        "<footer class='muted'>Static site generated by a scheduled pipeline &middot; "
        f"<a href='digests.json'>open data</a>{source}</footer>"
    )
    parts.append(f"</main><script>{FILTER_JS}{COPY_JS}</script></body></html>")
    return "\n".join(parts)


def render_feed(entries, site_url, now, title=PROJECT_NAME):
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
        "<description>Open-source projects scored on momentum, "
        "across AI, DevOps, Kubernetes, SRE and more.</description>"
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
        f"<title>{xml_escape(PROJECT_NAME)}: weekly roll-ups</title>"
        f"<link>{xml_escape(site_url or 'https://github.com')}</link>"
        "<description>One summary per week of the projects the pipeline processed.</description>"
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
            show_contribute=board is not None, today=now.date(), social_image=SOCIAL_IMAGE.exists(),
        ),
        encoding="utf-8",
    )
    (out / "favicon.svg").write_text(FAVICON_SVG, encoding="utf-8")
    if SOCIAL_IMAGE.exists():
        (out / SOCIAL_IMAGE.name).write_bytes(SOCIAL_IMAGE.read_bytes())
    (out / "feed.xml").write_text(render_feed(entries[:MAX_FEED_ENTRIES], site_url, now), encoding="utf-8")
    for name, file in feeds[1:]:
        if file == "feed-weekly.xml":
            continue
        mine = [e for e in entries if area_for(e["topic"], areas) == name][:MAX_FEED_ENTRIES]
        (out / file).write_text(render_feed(mine, site_url, now, f"{PROJECT_NAME}: {name}"), encoding="utf-8")
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
