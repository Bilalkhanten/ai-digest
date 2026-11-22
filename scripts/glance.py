"""Free, rule-based "At a glance" facts about a repo. No API keys, no LLM. Standard library only.

Everything here treats the README as untrusted text: output is plain text only (HTML, images
and link targets are stripped), so it is safe to write into a Markdown page.
"""
from __future__ import annotations

import re
from datetime import date

EXCERPT_LIMIT = 320
MAX_SECTIONS = 6

_FENCE = re.compile(r"^\s*(```|~~~)")
_INSTALL = re.compile(
    r"^(?:\$\s+)?((?:pip3?|uv pip|uv|npm|pnpm|yarn|cargo|go|docker|brew|npx|poetry|conda)\s+"
    r"(?:install|add|get|run|i)\b[^\n]*)$"
)
_SKIP_HEADINGS = {
    "table of contents", "contents", "toc", "license", "licence", "contributing", "contributors",
}
_BLOCK_STARTS = ("#", "|", "<", ">", "- ", "* ", "+ ", "---", "===")


def _strip_inline(text):
    """Reduce Markdown/HTML inline syntax to plain text."""
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)               # images
    text = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", " ", text)  # badge links
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)            # links -> their text
    text = re.sub(r"<[^>]+>", " ", text)                             # HTML tags
    text = re.sub(r"https?://\S+", " ", text)                        # bare URLs
    text = re.sub(r"[`*~]+", "", text)                               # emphasis / code marks
    text = re.sub(r"(?<![A-Za-z0-9])_+|_+(?![A-Za-z0-9])", "", text)    # _emphasis_, but keep SOME_VAR
    text = text.replace("@", "")                                     # never create mentions
    return re.sub(r"\s+", " ", text).strip()


def _outside_fences(text):
    """Yield (line, in_fence) for each line, tracking fenced code blocks."""
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            yield line, True
            continue
        yield line, in_fence


def readme_excerpt(text, limit=EXCERPT_LIMIT):
    """First real prose paragraph of a README, cleaned and shortened. '' if none."""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line, in_fence in _outside_fences(text):
        if in_fence:
            continue
        stripped = line.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = []
            continue
        if stripped.startswith(_BLOCK_STARTS) or re.match(r"\d+\.\s", stripped):
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(current)

    for lines in paragraphs:
        cleaned = _strip_inline(" ".join(lines))
        if len(cleaned) >= 60 and len(re.findall(r"[A-Za-z]{3,}", cleaned)) >= 8:
            if len(cleaned) > limit:
                cleaned = cleaned[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "..."
            return cleaned
    return ""


def readme_sections(text, maximum=MAX_SECTIONS):
    """Names of the README's second- and third-level headings (deduplicated, in order)."""
    seen, out = set(), []
    for line, in_fence in _outside_fences(text):
        if in_fence:
            continue
        m = re.match(r"^(#{2,3})\s+(.+?)\s*#*\s*$", line)
        if not m:
            continue
        name = _strip_inline(m.group(2))
        name = re.sub(r"[^\w\s&/+.'-]", "", name).strip()
        key = name.lower()
        if not name or key in seen or key in _SKIP_HEADINGS:
            continue
        seen.add(key)
        out.append(name[:50])
        if len(out) == maximum:
            break
    return out


def install_hint(text):
    """First install/run command found inside a fenced code block. '' if none."""
    for line, in_fence in _outside_fences(text):
        if not in_fence or _FENCE.match(line):
            continue
        m = _INSTALL.match(line.strip())
        if m and "`" not in m.group(1) and "<" not in m.group(1):
            command = re.sub(r"\s+#.*$", "", m.group(1))   # "brew install x   # macOS" -> "brew install x"
            return re.sub(r"\s{2,}", " ", command).strip()[:100]
    return ""


def age_text(created_at, today):
    """'20 months ago' / '2.3 years ago' from an ISO timestamp. '' if unparseable."""
    try:
        created = date.fromisoformat(created_at[:10])
    except (TypeError, ValueError):
        return ""
    days = (today - created).days
    if days < 0:
        return ""
    if days < 60:
        return f"{days} days ago"
    if days < 730:
        return f"{days // 30} months ago"
    return f"{days / 365:.1f} years ago"


def release_text(release):
    """'v1.2.3 (2026-11-01)' from a GitHub release object. '' if absent."""
    if not release:
        return ""
    tag = re.sub(r"[^\w.+-]", "", str(release.get("tag_name") or ""))[:40]
    published = (release.get("published_at") or "")[:10]
    if not tag:
        return ""
    return f"{tag} ({published})" if published else tag


_SEVERITY_ORDER = ["critical", "high", "medium", "low"]
_NOISE = ("full changelog", "new contributors", "what's changed", "whats changed")


def release_notes(release, limit=260, max_items=3):
    """The first few meaningful lines of the latest release notes, as plain text. '' if none."""
    body = (release or {}).get("body") or ""
    items = []
    for line, in_fence in _outside_fences(body):
        if in_fence:
            continue
        s = line.strip()
        if not s or s.startswith(("#", "|", ">", "---", "===")) or s.lower().strip("*_ ").startswith(_NOISE):
            continue
        s = re.sub(r"^(?:[-*+]|\d+\.)\s+", "", s)
        s = re.sub(r"\s+by\s+@\S+.*$", "", s)        # "... by @user in #123"
        s = re.sub(r"\s+in\s+#\d+.*$", "", s)
        cleaned = _strip_inline(s)
        if len(cleaned) >= 8:
            items.append(cleaned)
        if len(items) == max_items:
            break
    text = "; ".join(items)
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "..."
    return text


def advisory_text(advisories):
    """'3 published (highest: high, latest 2026-10-02)' from a list of advisories. '' if none."""
    if not isinstance(advisories, list) or not advisories:
        return ""
    severities = {str(a.get("severity") or "").lower() for a in advisories if isinstance(a, dict)}
    highest = next((s for s in _SEVERITY_ORDER if s in severities), "")
    dates = sorted((a.get("published_at") or "")[:10] for a in advisories if isinstance(a, dict))
    latest = next((d for d in reversed(dates) if d), "")
    parts = [f"{len(advisories)} published"]
    bits = [f"highest: {highest}" if highest else "", f"latest {latest}" if latest else ""]
    detail = ", ".join(b for b in bits if b)
    return f"{parts[0]} ({detail})" if detail else parts[0]


def clean_title(title, limit=90):
    """An issue title reduced to safe plain text (it is untrusted and goes inside a Markdown link)."""
    text = _strip_inline(str(title or ""))
    text = re.sub(r"[\[\]()<>|]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "..."
    return text


def _issue_age_days(issue, today):
    try:
        return (today - date.fromisoformat(str(issue.get("updated_at") or "")[:10])).days
    except ValueError:
        return None


def pick_opportunities(issues_by_label, repo_name, today, maximum=3, max_age_days=180):
    """Up to `maximum` open, unassigned, recently active issues a newcomer could take.

    `issues_by_label` is [(label, [issue, ...]), ...] in priority order; each list is newest first.
    Pull requests, locked, assigned and stale issues are dropped, and an issue listed under two
    labels is kept once (under the first). The link is built from the issue number, never
    taken from the response. Returns [{"title", "url", "label", "updated"}].
    """
    out, seen = [], set()
    for label, issues in issues_by_label:
        for issue in issues if isinstance(issues, list) else []:
            if not isinstance(issue, dict) or "pull_request" in issue or issue.get("locked"):
                continue
            number = issue.get("number")
            if not isinstance(number, int) or isinstance(number, bool) or number in seen:
                continue
            if issue.get("state", "open") != "open" or issue.get("assignees") or issue.get("assignee"):
                continue
            age = _issue_age_days(issue, today)
            if age is None or age < 0 or age > max_age_days:
                continue
            title = clean_title(issue.get("title"))
            if not title:
                continue
            seen.add(number)
            out.append({
                "title": title,
                "url": f"https://github.com/{repo_name}/issues/{number}",
                "label": clean_title(label, 30),
                "updated": age_text(str(issue.get("updated_at"))[:10], today),
            })
            if len(out) == maximum:
                return out
    return out


def contributing_url(profile, repo_name):
    """The repo's CONTRIBUTING file link from a community-profile response. '' if absent or odd."""
    files = (profile or {}).get("files") if isinstance(profile, dict) else None
    contributing = files.get("contributing") if isinstance(files, dict) else None
    url = contributing.get("html_url") if isinstance(contributing, dict) else ""
    if isinstance(url, str) and url.startswith(f"https://github.com/{repo_name}/") and " " not in url:
        return url
    return ""


def build_extras(repo, readme, today, release=None, advisories=None):
    """Collect everything render_digest needs for the 'At a glance' section."""
    return {
        "excerpt": readme_excerpt(readme),
        "sections": readme_sections(readme),
        "install": install_hint(readme),
        "release": release_text(release),
        "whatsnew": release_notes(release),
        "advisories": advisory_text(advisories),
        "age": age_text(repo.get("created_at"), today),
    }
