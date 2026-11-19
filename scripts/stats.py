"""Stats and open-data helpers for the website. Pure functions; standard library only.

Charts are plain inline SVG (no JavaScript, no libraries). Every label that comes from a
repo is HTML-escaped.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from html import escape

from digestlib import area_for, entry_link, load_areas

STATS_CSS = """
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));gap:.75rem}
.tile{border:1px solid var(--line);border-radius:8px;padding:.6rem .8rem}
.num{font-size:1.5rem;font-weight:600}
.bar{fill:var(--link)} .lbl{fill:var(--fg);font-size:12px} .val{fill:var(--muted);font-size:11px}
table{border-collapse:collapse;width:100%;font-size:.9rem}
td,th{border-top:1px solid var(--line);padding:.35rem .4rem;text-align:left}
th{color:var(--muted);font-weight:500}
"""


def streaks(days, today):
    """(current, longest) runs of consecutive calendar days that each have a digest.

    The current streak is still alive if the newest digest is from today or yesterday."""
    ordered = sorted(set(days))
    if not ordered:
        return 0, 0
    longest = run = 1
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)
    current = 0
    if (today - ordered[-1]).days <= 1:
        current = 1
        i = len(ordered) - 1
        while i > 0 and (ordered[i] - ordered[i - 1]).days == 1:
            current += 1
            i -= 1
    return current, longest


def weekly_counts(days, today, weeks=12):
    """[(label, count)] for the last `weeks` Monday-start weeks, oldest first."""
    monday = today - timedelta(days=today.weekday())
    out = []
    for back in range(weeks - 1, -1, -1):
        start = monday - timedelta(weeks=back)
        end = start + timedelta(days=6)
        out.append((start.strftime("%b %d"), sum(1 for d in days if start <= d <= end)))
    return out


def top_counts(values, limit=10):
    """[(value, count)] most common first, ties alphabetical; blanks and 'n/a' dropped."""
    counts = Counter(v for v in values if v and v != "n/a")
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def star_deltas(entries, stars_now):
    """Rows for the 'where are they now' table, biggest gain first; unknowns last."""
    rows = []
    for e in entries:
        now = stars_now.get(e["repo"])
        delta = None if now is None else now - e["stars"]
        pct = None if delta is None or e["stars"] <= 0 else delta / e["stars"] * 100
        rows.append({"repo": e["repo"], "date": e["date"], "then": e["stars"], "now": now,
                     "delta": delta, "pct": pct})
    rows.sort(key=lambda r: (r["delta"] is None, -(r["delta"] or 0), r["repo"]))
    return rows


def bar_chart_svg(items, title, width=560, label_width=170):
    """Horizontal bar chart. items: [(label, value)]."""
    if not items:
        return "<p class='muted'>No data yet.</p>"
    row_h, pad = 24, 6
    height = len(items) * row_h + pad * 2
    top = max(v for _, v in items) or 1
    bar_room = width - label_width - 50
    rows = []
    for i, (label, value) in enumerate(items):
        y = pad + i * row_h
        w = max(2, round(bar_room * value / top))
        short = label if len(label) <= 24 else label[:23] + "…"
        rows.append(
            f"<text class='lbl' x='{label_width - 8}' y='{y + 16}' text-anchor='end'>{escape(short)}</text>"
            f"<rect class='bar' x='{label_width}' y='{y + 3}' width='{w}' height='{row_h - 8}' rx='3'/>"
            f"<text class='val' x='{label_width + w + 6}' y='{y + 16}'>{value}</text>"
        )
    return (
        f"<svg role='img' aria-label='{escape(title)}' viewBox='0 0 {width} {height}' width='100%' "
        f"style='max-width:{width}px'><title>{escape(title)}</title>{''.join(rows)}</svg>"
    )


def column_chart_svg(items, title, width=560, height=140):
    """Vertical bars for a time series. items: [(label, value)]."""
    if not items:
        return "<p class='muted'>No data yet.</p>"
    top = max(v for _, v in items) or 1
    left, bottom = 8, 28
    slot = (width - left * 2) / len(items)
    chart_h = height - bottom - 16
    parts = []
    for i, (label, value) in enumerate(items):
        h = round(chart_h * value / top) if value else 0
        x = left + i * slot
        y = 16 + chart_h - h
        parts.append(
            f"<rect class='bar' x='{x + 3:.1f}' y='{y}' width='{max(slot - 6, 2):.1f}' "
            f"height='{max(h, 1)}' rx='2'/>"
            f"<text class='val' x='{x + slot / 2:.1f}' y='{y - 3}' text-anchor='middle'>{value}</text>"
            f"<text class='lbl' x='{x + slot / 2:.1f}' y='{height - 10}' text-anchor='middle' "
            f"font-size='9'>{escape(label)}</text>"
        )
    return (
        f"<svg role='img' aria-label='{escape(title)}' viewBox='0 0 {width} {height}' width='100%' "
        f"style='max-width:{width}px'><title>{escape(title)}</title>{''.join(parts)}</svg>"
    )


def format_delta(row):
    if row["delta"] is None:
        return "n/a"
    sign = "+" if row["delta"] > 0 else ""
    pct = f" ({sign}{row['pct']:.0f}%)" if row["pct"] is not None else ""
    return f"{sign}{row['delta']:,}{pct}"


def render_stats_page(css, entries, infos, stars_now, today, generated_label, areas=None):
    """Full stats.html. `infos` lines up with `entries` (parsed digest pages)."""
    from datetime import date as _date

    days = [_date.fromisoformat(e["date"]) for e in entries]
    current, longest = streaks(days, today)
    forks = sum(1 for e in entries if e.get("fork_url"))
    areas = areas or load_areas()
    by_area = top_counts([area_for(e["topic"], areas) for e in entries])
    topics = top_counts([e["topic"] for e in entries])
    langs = top_counts([i["language"] for i in infos])
    rows = star_deltas(entries, stars_now)[:15]
    tiles = [
        ("Picks", len(entries)), ("Forks made", forks),
        ("Current streak", f"{current} d"), ("Longest streak", f"{longest} d"),
        ("Topics", len({e["topic"] for e in entries})),
        ("Languages", len({i["language"] for i in infos if i["language"] != "n/a"})),
    ]
    tile_html = "".join(
        f"<div class='tile'><div class='num'>{escape(str(v))}</div>"
        f"<div class='muted'>{escape(k)}</div></div>"
        for k, v in tiles
    )
    table = "".join(
        f"<tr><td><a href='{escape(entry_link({'repo': r['repo']}))}'>{escape(r['repo'])}</a></td>"
        f"<td>{escape(r['date'])}</td><td>{r['then']:,}</td>"
        f"<td>{'n/a' if r['now'] is None else format(r['now'], ',')}</td>"
        f"<td>{escape(format_delta(r))}</td></tr>"
        for r in rows
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Repo digest: stats</title>"
        f"<style>{css}{STATS_CSS}</style></head><body><main>"
        "<h1>Stats</h1><p class='muted'><a href='index.html'>Back to the digest</a> &middot; "
        f"<a href='digests.json'>digests.json</a> (open data) &middot; built {escape(generated_label)}</p>"
        f"<div class='tiles'>{tile_html}</div>"
        "<h2 style='margin-top:1.5rem'>Picks per week (last 12 weeks)</h2>"
        f"{column_chart_svg(weekly_counts(days, today), 'Picks per week')}"
        "<h2 style='margin-top:1.5rem'>By area</h2>" f"{bar_chart_svg(by_area, 'Picks by area')}"
        "<h2 style='margin-top:1.5rem'>By topic</h2>" f"{bar_chart_svg(topics, 'Picks by topic')}"
        "<h2 style='margin-top:1.5rem'>By language</h2>" f"{bar_chart_svg(langs, 'Picks by language')}"
        "<h2 style='margin-top:1.5rem'>Where are they now?</h2>"
        "<p class='muted'>Stars when picked versus stars at the time the site was last built.</p>"
        "<table><tr><th>Repo</th><th>Picked</th><th>Stars then</th><th>Stars now</th><th>Change</th></tr>"
        f"{table}</table></main></body></html>"
    )


def digests_json(entries, infos, generated, areas=None):
    """Open-data record for each pick, newest first."""
    areas = areas or load_areas()
    records = []
    for e, i in zip(entries, infos, strict=True):
        records.append({
            "date": e["date"],
            "repo": e["repo"],
            "url": f"https://github.com/{e['repo']}",
            "fork_url": e.get("fork_url"),
            "stars_at_pick": e["stars"],
            "topic": e["topic"],
            "area": area_for(e["topic"], areas),
            "language": i["language"],
            "license": i["license"],
            "description": i["description"],
            "why_picked": i["reason"],
            "latest_release": i["release"],
            "whats_new": i["whatsnew"],
            "security_advisories": i["advisories"],
            "contribution_opportunities": i.get("opportunities", []),
            "contributing_guide": i.get("contributing", ""),
        })
    return {"generated": generated, "count": len(records), "entries": records}
