"""Offline tests for scripts/build_site.py."""
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_site as bs  # noqa: E402

_REAL = {"digest": bs.DIGEST_DIR, "weekly": bs.WEEKLY_DIR}
_GUARD = {}


def setUpModule():
    """Point the site builder at an empty digest folder for EVERY test in this file.

    Without this, a test whose fixture date equals a real digest's date silently reads that real
    page. That is exactly what broke the daily run's test gate the day a real digest for the
    fixture date appeared. Direct assignment (not mock) so mock.patch.stopall() cannot undo it."""
    _GUARD["tmp"] = tempfile.TemporaryDirectory()
    digest = Path(_GUARD["tmp"].name) / "digest"
    (digest / "weekly").mkdir(parents=True)
    bs.DIGEST_DIR, bs.WEEKLY_DIR = digest, digest / "weekly"


def tearDownModule():
    bs.DIGEST_DIR, bs.WEEKLY_DIR = _REAL["digest"], _REAL["weekly"]
    _GUARD["tmp"].cleanup()


OPPORTUNITIES = '## Contribution opportunities\n\n- [Fix typo](https://github.com/acme/agent/issues/7) (good first issue, updated 3 days ago)\n- [Add retry](https://github.com/acme/agent/issues/9) (help wanted, updated 2 months ago)\n\nContributing guide: https://github.com/acme/agent/blob/main/CONTRIBUTING.md\n\n'


class IsolationGuardTests(unittest.TestCase):
    def test_tests_never_read_the_real_digest_folder(self):
        self.assertNotEqual(bs.DIGEST_DIR, _REAL["digest"])
        self.assertNotEqual(bs.WEEKLY_DIR, _REAL["weekly"])
        self.assertEqual(list(bs.DIGEST_DIR.glob("*.md")), [])

    def test_a_fixture_date_matching_a_real_digest_cannot_leak_in(self):
        # Regression: on 2026-11-18 a real digest with this date existed and changed the output.
        entry = [{"date": "2026-11-18", "repo": "a/b", "stars": 1, "topic": "sre", "fork_url": None}]
        html = bs.render_index(entry, [], "", "")
        self.assertNotIn("vllm", html)
        self.assertNotIn("Python", html)

STATE = [
    {"date": "2026-11-16", "repo": "acme/agent", "stars": 1234, "topic": "llm", "fork_url": "https://github.com/me/agent"},
    {"date": "2026-11-17", "repo": "evil/x", "stars": 5, "topic": "rag", "fork_url": None},
]
GOOD = (
    "# acme/agent\n\n> An agent framework.\n\n- Language: Python\n- Latest release: v1.2.3 (2026-11-01)\n\n"
    "## At a glance\n\nREADME excerpt: Builds <agents> & more.\n\nInstall: `pip install acme-agent`\n\n"
    "## Summary\n\n- One\n- Two\n"
)
EVIL = "# evil/x\n\n> <script>alert(1)</script> & more\n\n- Language: <b>Rust</b>\n\n## Summary\n\n- <img src=x onerror=alert(1)>\n"


class BuildSiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        digest = self.root / "digest"
        (digest / "weekly").mkdir(parents=True)
        (digest / "2026-11-16.md").write_text(GOOD)
        (digest / "2026-11-17.md").write_text(EVIL)
        (digest / "weekly" / "2026-W47.md").write_text("# Week")
        self.patches = [
            mock.patch.object(bs, "DIGEST_DIR", digest),
            mock.patch.object(bs, "WEEKLY_DIR", digest / "weekly"),
            mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": "Me/ai-digest"}, clear=False),
        ]
        for p in self.patches:
            p.start()
        self.out = bs.build(self.root / "site", state=STATE, now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_index_lists_newest_first_with_links(self):
        html = (self.out / "index.html").read_text()
        self.assertLess(html.index("evil/x"), html.index("acme/agent"))
        self.assertIn("https://github.com/acme/agent", html)
        self.assertIn("<li>One</li>", html)
        self.assertIn("2026-W47", html)            # weekly link
        self.assertIn("1,234 stars", html)

    def test_whatsnew_and_advisories_are_shown_and_escaped(self):
        digest = self.root / "digest" / "2026-11-16.md"
        digest.write_text(GOOD + "\nWhat's new: <b>Faster</b> startup\n- Security advisories: 2 published (highest: high)\n")
        html = bs.render_index(STATE[:1], [], "", "")
        self.assertIn("What's new: &lt;b&gt;Faster&lt;/b&gt; startup", html)
        self.assertNotIn("<b>Faster</b>", html)

    def test_glance_facts_are_shown_and_escaped(self):
        html = (self.out / "index.html").read_text()
        self.assertIn("<code>pip install acme-agent</code>", html)
        self.assertIn("Latest release: v1.2.3 (2026-11-01)", html)
        self.assertIn("Builds &lt;agents&gt; &amp; more.", html)

    def test_contribution_opportunities_are_listed_with_safe_links(self):
        digest = self.root / "digest" / "2026-11-16.md"
        digest.write_text(GOOD.replace("## Summary", OPPORTUNITIES + "## Summary"))
        html = bs.render_index(STATE[:1], [], "", "")
        self.assertIn("<a href='https://github.com/acme/agent/issues/7'>Fix typo</a>", html)
        self.assertIn("(good first issue, updated 3 days ago)", html)
        self.assertIn("<a href='https://github.com/acme/agent/blob/main/CONTRIBUTING.md'>Contributing guide</a>", html)

    def test_contribute_page_and_link_only_when_a_board_is_given(self):
        self.assertFalse((self.out / "contribute.html").exists())
        self.assertNotIn("contribute.html", (self.out / "index.html").read_text())
        board = [{"repo": "acme/agent", "date": "2026-11-16", "issues": [
            {"title": "Fix typo", "url": "https://github.com/acme/agent/issues/7", "label": "help wanted",
             "updated": "3 days ago"}]}]
        out = bs.build(self.root / "site3", state=STATE, board=board,
                       now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc))
        self.assertIn("Fix typo", (out / "contribute.html").read_text())
        self.assertIn("<a href='contribute.html'>Contribute</a>", (out / "index.html").read_text())
        empty = bs.build(self.root / "site4", state=STATE, board=[],
                         now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc))
        self.assertIn("No open beginner-friendly issues", (empty / "contribute.html").read_text())

    def test_search_box_is_hidden_until_javascript_runs_and_wired_up(self):
        html = (self.out / "index.html").read_text()
        self.assertIn("<input id='q' type='search' placeholder='Search picks' aria-label='Search picks' hidden>", html)
        self.assertIn("getElementById('q')", html)
        self.assertLess(html.index("id='q'"), html.index("id='filters'"))
        self.assertNotIn("id='q'", bs.render_index([], [], "", ""))

    def test_pages_without_opportunities_show_no_such_block(self):
        self.assertNotIn("Ways to contribute", (self.out / "index.html").read_text())

    def test_untrusted_repo_text_is_escaped(self):
        html = (self.out / "index.html").read_text()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("<b>Rust</b>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_feed_is_valid_xml_with_expected_items(self):
        root = ET.fromstring((self.out / "feed.xml").read_text())
        items = root.findall("./channel/item")
        self.assertEqual([i.findtext("title") for i in items], ["evil/x", "acme/agent"])
        self.assertTrue(items[0].findtext("pubDate").endswith("+0000"))
        self.assertIn("An agent framework.", items[1].findtext("description"))
        self.assertEqual(root.findtext("./channel/link"), "https://me.github.io/ai-digest/")


class StatsAndDataTests(unittest.TestCase):
    def setUp(self):
        BuildSiteTests.setUp(self)

    tearDown = BuildSiteTests.tearDown

    def test_stats_page_and_open_data_are_written(self):
        out = bs.build(self.root / "site2", state=STATE, now=datetime(2026, 11, 17, 12, tzinfo=timezone.utc),
                       stars_now={"acme/agent": 2000})
        html = (out / "stats.html").read_text()
        self.assertIn("2,000", html)
        self.assertIn("Where are they now?", html)
        data = json.loads((out / "digests.json").read_text())
        self.assertEqual([e["repo"] for e in data["entries"]], ["evil/x", "acme/agent"])
        self.assertEqual(data["entries"][1]["latest_release"], "v1.2.3 (2026-11-01)")

    def test_index_links_to_stats_and_data(self):
        html = (self.out / "index.html").read_text()
        self.assertIn("stats.html", html)
        self.assertIn("digests.json", html)

    def test_fetch_stars_tolerates_failures_and_stops_after_three(self):
        calls = []

        def boom(path):
            calls.append(path)
            raise OSError("offline")

        with mock.patch.object(bs, "fetch_repo", boom):
            got = bs.fetch_stars([{"repo": f"o/r{i}"} for i in range(10)])
        self.assertEqual(got, {})
        self.assertEqual(len(calls), 3)

    def test_fetch_stars_collects_counts_and_skips_missing_repos(self):
        def fake(path):
            return None if path.endswith("gone") else {"stargazers_count": 42}

        with mock.patch.object(bs, "fetch_repo", fake):
            self.assertEqual(bs.fetch_stars([{"repo": "o/ok"}, {"repo": "o/gone"}]), {"o/ok": 42})


class TopicFilterTests(unittest.TestCase):
    ENTRIES = [
        {"date": "2026-11-18", "repo": "a/k1", "stars": 1, "topic": "kubernetes", "fork_url": None},
        {"date": "2026-11-17", "repo": "b/k2", "stars": 1, "topic": "kubernetes", "fork_url": None},
        {"date": "2026-11-16", "repo": "c/l1", "stars": 1, "topic": "llm", "fork_url": None},
        {"date": "2026-11-15", "repo": "d/x", "stars": 1, "topic": "<b>bad</b>", "fork_url": None},
    ]

    def html(self, entries=None):
        return bs.render_index(entries or self.ENTRIES, [], "", "")

    def test_chips_show_counts_most_common_first_and_start_hidden(self):
        html = self.html()
        self.assertIn("<nav id='filters' class='chips' aria-label='Filter by topic' hidden>", html)
        self.assertIn("data-topic=''", html)
        self.assertLess(html.index("data-topic='kubernetes'"), html.index("data-topic='llm'"))
        self.assertIn("kubernetes <span>2</span>", html)
        self.assertIn("All <span>4</span>", html)

    def test_every_article_carries_its_topic(self):
        html = self.html()
        self.assertEqual(html.count("<article data-topic="), 4)
        self.assertIn("<article data-topic='kubernetes' data-area='Platform'>", html)

    def test_topics_are_escaped_in_attributes_and_labels(self):
        html = self.html()
        self.assertNotIn("<b>bad</b>", html)
        self.assertIn("&lt;b&gt;bad&lt;/b&gt;", html)

    def test_script_is_inline_and_scoped_to_the_filter_nav(self):
        html = self.html()
        self.assertIn("getElementById('filters')", html)
        self.assertNotIn("http://", html.split("<script>")[1])         # no external scripts
        self.assertEqual(html.count("<script"), 1)

    def test_chip_count_is_capped(self):
        many = [{"date": "2026-11-18", "repo": f"o/r{i}", "stars": 1, "topic": f"t{i:02d}", "fork_url": None}
                for i in range(30)]
        self.assertEqual(self.html(many).count("<button"), bs.MAX_CHIPS + 1)   # +1 for "All"

    def test_empty_site_has_no_filter_bar(self):
        self.assertNotIn("id='filters'", bs.render_index([], [], "", ""))


class AreaTests(unittest.TestCase):
    ENTRIES = TopicFilterTests.ENTRIES

    def test_area_bar_shows_each_area_with_counts_and_starts_hidden(self):
        html = bs.render_index(self.ENTRIES, [], "", "")
        self.assertIn("<nav id='areas' class='chips' aria-label='Filter by area' hidden>", html)
        self.assertIn("All areas <span>4</span>", html)
        self.assertIn("Platform <span>2</span>", html)
        self.assertIn("AI <span>1</span>", html)
        self.assertLess(html.index("id='areas'"), html.index("id='filters'"))

    def test_topic_chips_know_their_area(self):
        html = bs.render_index(self.ENTRIES, [], "", "")
        self.assertIn("data-topic='kubernetes' data-area='Platform'", html)
        self.assertIn("data-topic='llm' data-area='AI'", html)

    def test_no_area_bar_when_everything_is_one_area(self):
        only_ai = [{"date": "2026-11-18", "repo": "a/b", "stars": 1, "topic": "llm", "fork_url": None},
                   {"date": "2026-11-17", "repo": "c/d", "stars": 1, "topic": "rag", "fork_url": None}]
        self.assertNotIn("id='areas'", bs.render_index(only_ai, [], "", ""))

    def test_custom_areas_are_respected_and_escaped(self):
        html = bs.render_index(self.ENTRIES[:1], [], "", "", areas={"<i>X</i>": ["kubernetes"]})
        self.assertIn("data-area='&lt;i&gt;X&lt;/i&gt;'", html)
        self.assertNotIn("<i>X</i>", html)

    def test_feed_links_are_listed_when_given(self):
        html = bs.render_index(self.ENTRIES, [], "", "", feeds=[("All", "feed.xml"), ("AI", "feed-ai.xml")])
        self.assertIn("href='feed-ai.xml'", html)
        self.assertIn("RSS: <a href='feed.xml'>All</a> &middot; <a href='feed-ai.xml'>AI</a>", html)
        self.assertEqual(html.count("rel='alternate'"), 2)


class PerAreaFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for p in (mock.patch.object(bs, "DIGEST_DIR", self.root / "digest"),
                  mock.patch.object(bs, "WEEKLY_DIR", self.root / "digest" / "weekly")):
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(self.tmp.cleanup)

    def build(self, entries):
        return bs.build(self.root / "site", state=entries, now=datetime(2026, 11, 20, tzinfo=timezone.utc))

    def entries(self):
        return TopicFilterTests.ENTRIES[:3]    # kubernetes x2 (Platform), llm (AI)

    def test_one_feed_per_area_plus_the_combined_feed(self):
        out = self.build(self.entries())
        self.assertEqual(sorted(p.name for p in out.glob("feed*.xml")), ["feed-ai.xml", "feed-platform.xml", "feed.xml"])

    def test_each_area_feed_only_contains_its_own_picks(self):
        out = self.build(self.entries())
        titles = lambda f: [i.findtext("title") for i in ET.fromstring((out / f).read_text()).findall("./channel/item")]  # noqa: E731
        self.assertEqual(sorted(titles("feed-platform.xml")), ["a/k1", "b/k2"])
        self.assertEqual(titles("feed-ai.xml"), ["c/l1"])
        self.assertEqual(len(titles("feed.xml")), 3)
        self.assertEqual(ET.fromstring((out / "feed-ai.xml").read_text()).findtext("./channel/title"), "OSS Signal Pipeline: AI")

    def test_single_area_site_writes_only_the_combined_feed(self):
        only_ai = [e for e in self.entries() if e["topic"] == "llm"]
        out = self.build(only_ai)
        self.assertEqual([p.name for p in out.glob("feed*.xml")], ["feed.xml"])

    def test_area_is_in_the_open_data(self):
        out = self.build(self.entries())
        data = json.loads((out / "digests.json").read_text())
        self.assertEqual({e["repo"]: e["area"] for e in data["entries"]},
                         {"a/k1": "Platform", "b/k2": "Platform", "c/l1": "AI"})

    def test_stats_page_has_an_area_chart(self):
        out = self.build(self.entries())
        self.assertIn("By area", (out / "stats.html").read_text())


WEEKLY_PAGE = """# Week 2026-W47

2 repos featured, 2026-11-16 to 2026-11-17.

## Themes

Agents everywhere & <script>alert(1)</script> tooling.

## Repos

| Date | Repo | Stars | Topic | Language |
|---|---|---|---|---|
| 2026-11-16 | [acme/agent](https://github.com/me/agent) | 1,500 | llm | Python |
| 2026-11-17 | [evil/<b>x](https://github.com/evil/x) | 800 | sre | Go |

## By topic

- llm: 1
"""


class WeeklyFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.weekly = self.root / "digest" / "weekly"
        self.weekly.mkdir(parents=True)
        self.now = datetime(2026, 11, 22, 19, tzinfo=timezone.utc)
        for p in (mock.patch.object(bs, "DIGEST_DIR", self.root / "digest"),
                  mock.patch.object(bs, "WEEKLY_DIR", self.weekly)):
            p.start()
        self.addCleanup(mock.patch.stopall)

    def items(self, slug="Me/ai-digest"):
        return bs.weekly_items(self.weekly, slug, "https://me.github.io/ai-digest/")

    def test_parse_weekly(self):
        info = bs.parse_weekly(WEEKLY_PAGE)
        self.assertEqual(info["intro"], "2 repos featured, 2026-11-16 to 2026-11-17.")
        self.assertTrue(info["themes"].startswith("Agents everywhere"))
        self.assertEqual(info["repos"][0], ("acme/agent", 1500, "llm"))
        self.assertEqual(len(info["repos"]), 2)

    def test_parse_weekly_without_themes_or_rows(self):
        info = bs.parse_weekly("# Week 2026-W01\n\nnothing\n")
        self.assertEqual((info["intro"], info["themes"], info["repos"]), ("", "", []))

    def test_item_fields_and_sunday_publish_date(self):
        (self.weekly / "2026-W47.md").write_text(WEEKLY_PAGE)
        (item,) = self.items()
        self.assertEqual(item["title"], "Week 2026-W47")
        self.assertEqual(item["link"], "https://github.com/Me/ai-digest/blob/main/digest/weekly/2026-W47.md")
        self.assertEqual(item["published"], datetime(2026, 11, 22, 18, 23, tzinfo=timezone.utc))   # that week's Sunday
        self.assertIn("acme/agent (1,500 stars, llm)", item["description"])

    def test_newest_week_first_and_junk_files_are_skipped(self):
        for name in ("2026-W45.md", "2026-W47.md", "2026-W46.md", "notes.md", "2026-W99.md"):
            (self.weekly / name).write_text(WEEKLY_PAGE)
        self.assertEqual([i["title"] for i in self.items()], ["Week 2026-W47", "Week 2026-W46", "Week 2026-W45"])

    def test_item_count_is_capped(self):
        for w in range(1, 30):
            (self.weekly / f"2026-W{w:02d}.md").write_text(WEEKLY_PAGE)
        self.assertEqual(len(self.items()), bs.MAX_WEEKLY_ITEMS)

    def test_without_a_repo_slug_it_links_to_the_site(self):
        (self.weekly / "2026-W47.md").write_text(WEEKLY_PAGE)
        self.assertEqual(self.items(slug="")[0]["link"], "https://me.github.io/ai-digest/")

    def test_feed_is_valid_xml_and_escapes_untrusted_text(self):
        (self.weekly / "2026-W47.md").write_text(WEEKLY_PAGE)
        xml = bs.render_weekly_feed(self.items(), "https://me.github.io/ai-digest/", self.now)
        root = ET.fromstring(xml)
        self.assertEqual(root.findtext("./channel/title"), "OSS Signal Pipeline: weekly roll-ups")
        description = root.findtext("./channel/item/description")
        self.assertIn("<script>alert(1)</script>", description)     # preserved as TEXT after XML unescaping
        self.assertNotIn("<script>", xml)                              # but never as markup in the XML itself
        self.assertTrue(root.findtext("./channel/item/pubDate").endswith("+0000"))

    def test_build_writes_the_weekly_feed_and_lists_it(self):
        (self.weekly / "2026-W47.md").write_text(WEEKLY_PAGE)
        out = bs.build(self.root / "site", state=TopicFilterTests.ENTRIES[:2], now=self.now)
        self.assertTrue((out / "feed-weekly.xml").exists())
        html = (out / "index.html").read_text()
        self.assertIn("<a href='feed-weekly.xml'>Weekly</a>", html)
        self.assertIn("title='OSS Signal Pipeline: Weekly'", html)

    def test_no_weekly_pages_means_no_weekly_feed(self):
        out = bs.build(self.root / "site", state=TopicFilterTests.ENTRIES[:2], now=self.now)
        self.assertFalse((out / "feed-weekly.xml").exists())
        self.assertNotIn("feed-weekly.xml", (out / "index.html").read_text())

    def test_an_unreadable_weekly_page_does_not_break_the_site_build(self):
        (self.weekly / "2026-W47.md").write_text("garbage with no structure at all")
        out = bs.build(self.root / "site", state=TopicFilterTests.ENTRIES[:2], now=self.now)
        ET.fromstring((out / "feed-weekly.xml").read_text())


class LanguageDisplayTests(unittest.TestCase):
    def test_unknown_language_is_not_shown_as_na(self):
        entry = [{"date": "2026-11-18", "repo": "a/b", "stars": 1, "topic": "sre", "fork_url": None}]
        html = bs.render_index(entry, [], "", "")
        self.assertNotIn("n/a", html)
        self.assertIn("1 stars &middot; sre</div>", html)


class SummaryHtmlTests(unittest.TestCase):
    def test_plain_text_summary_becomes_a_paragraph(self):
        self.assertEqual(bs.summary_html("just text"), "<p>just text</p>")
        self.assertEqual(bs.summary_html(""), "")


if __name__ == "__main__":
    unittest.main()
