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

    def test_glance_facts_are_shown_and_escaped(self):
        html = (self.out / "index.html").read_text()
        self.assertIn("<code>pip install acme-agent</code>", html)
        self.assertIn("Latest release: v1.2.3 (2026-11-01)", html)
        self.assertIn("Builds &lt;agents&gt; &amp; more.", html)

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


class SummaryHtmlTests(unittest.TestCase):
    def test_plain_text_summary_becomes_a_paragraph(self):
        self.assertEqual(bs.summary_html("just text"), "<p>just text</p>")
        self.assertEqual(bs.summary_html(""), "")


if __name__ == "__main__":
    unittest.main()
