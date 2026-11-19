"""Offline tests for scripts/stats.py."""
import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import stats as st  # noqa: E402

D = date.fromisoformat
TODAY = date(2026, 11, 16)   # a Monday


class StreakTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(st.streaks([], TODAY), (0, 0))

    def test_current_and_longest(self):
        days = [D("2026-11-01"), D("2026-11-02"), D("2026-11-03"), D("2026-11-04"), D("2026-11-15"), D("2026-11-16")]
        self.assertEqual(st.streaks(days, TODAY), (2, 4))

    def test_yesterday_keeps_the_streak_alive_but_two_days_ago_ends_it(self):
        self.assertEqual(st.streaks([D("2026-11-14"), D("2026-11-15")], TODAY)[0], 2)
        self.assertEqual(st.streaks([D("2026-11-13"), D("2026-11-14")], TODAY)[0], 0)

    def test_duplicates_are_ignored_and_a_single_day_counts(self):
        self.assertEqual(st.streaks([D("2026-11-16"), D("2026-11-16")], TODAY), (1, 1))


class CountTests(unittest.TestCase):
    def test_weekly_counts_cover_twelve_weeks_oldest_first(self):
        days = [D("2026-11-16"), D("2026-11-17"), D("2026-11-09"), D("2026-01-01")]
        weeks = st.weekly_counts(days, TODAY)
        self.assertEqual(len(weeks), 12)
        self.assertEqual(weeks[-1], ("Nov 16", 2))
        self.assertEqual(weeks[-2], ("Nov 09", 1))
        self.assertEqual(sum(c for _, c in weeks), 3)      # Jan 1 is outside the window

    def test_top_counts_sorts_drops_blanks_and_limits(self):
        got = st.top_counts(["Go", "Python", "Python", "n/a", "", "Rust", "Go"], limit=2)
        self.assertEqual(got, [("Go", 2), ("Python", 2)])


class StarDeltaTests(unittest.TestCase):
    ENTRIES = [
        {"repo": "a/up", "date": "2026-11-01", "stars": 1000},
        {"repo": "b/down", "date": "2026-11-02", "stars": 500},
        {"repo": "c/unknown", "date": "2026-11-03", "stars": 100},
    ]

    def test_sorted_by_gain_with_unknowns_last(self):
        rows = st.star_deltas(self.ENTRIES, {"a/up": 1500, "b/down": 480})
        self.assertEqual([r["repo"] for r in rows], ["a/up", "b/down", "c/unknown"])
        self.assertEqual((rows[0]["delta"], round(rows[0]["pct"])), (500, 50))
        self.assertEqual(rows[1]["delta"], -20)
        self.assertIsNone(rows[2]["delta"])


class ChartTests(unittest.TestCase):
    def test_bar_chart_is_well_formed_and_escapes_labels(self):
        svg = st.bar_chart_svg([("<script>x</script>", 3), ("Python", 1)], "Picks <by> topic")
        self.assertNotIn("<script>", svg)
        ET.fromstring(svg)                                  # valid XML
        self.assertIn("&lt;script&gt;", svg)

    def test_long_labels_are_shortened(self):
        self.assertIn("…", st.bar_chart_svg([("x" * 60, 1)], "t"))

    def test_empty_charts_show_a_message(self):
        self.assertIn("No data", st.bar_chart_svg([], "t"))
        self.assertIn("No data", st.column_chart_svg([], "t"))

    def test_column_chart_is_well_formed(self):
        ET.fromstring(st.column_chart_svg([("Nov 02", 0), ("Nov 09", 4), ("Nov 16", 7)], "weekly"))


class PageAndJsonTests(unittest.TestCase):
    ENTRIES = [
        {"date": "2026-11-16", "repo": "acme/agent", "stars": 1000, "topic": "llm", "fork_url": "https://github.com/me/agent"},
        {"date": "2026-11-15", "repo": "evil/<b>x", "stars": 50, "topic": "rag", "fork_url": None},
    ]
    INFOS = [
        {"language": "Python", "license": "MIT", "description": "d", "reason": "1,000 stars",
         "release": "v1 (2026-11-01)", "whatsnew": "Faster", "advisories": "1 published (highest: high)"},
        {"language": "n/a", "license": "n/a", "description": "", "reason": "", "release": "",
         "whatsnew": "", "advisories": ""},
    ]

    def page(self, stars_now):
        return st.render_stats_page("", self.ENTRIES, self.INFOS, stars_now, TODAY, "2026-11-16 12:00 UTC")

    def test_page_has_tiles_charts_and_table(self):
        html = self.page({"acme/agent": 1250})
        for expected in ("Current streak", "2 d", "<svg", "Where are they now?", "1,250", "+250 (+25%)", "digests.json"):
            self.assertIn(expected, html)

    def test_unknown_stars_show_na_and_untrusted_names_are_escaped(self):
        html = self.page({})
        self.assertIn("n/a", html)
        self.assertNotIn("evil/<b>x", html)
        self.assertIn("evil/&lt;b&gt;x", html)

    def test_page_has_a_by_area_chart(self):
        html = st.render_stats_page("", self.ENTRIES, self.INFOS, {}, TODAY, "x", areas={"AI": ["llm"], "Plat": ["rag"]})
        self.assertIn("By area", html)
        self.assertIn("Picks by area", html)

    def test_json_has_area_and_the_new_fields(self):
        data = st.digests_json(self.ENTRIES, self.INFOS, "t", areas={"AI": ["llm"]})
        first = data["entries"][0]
        self.assertEqual((first["area"], first["whats_new"]), ("AI", "Faster"))
        self.assertEqual(first["security_advisories"], "1 published (highest: high)")
        self.assertEqual(data["entries"][1]["area"], "Other")

    def test_json_carries_contribution_opportunities(self):
        infos = [dict(self.INFOS[0], opportunities=[{"title": "T", "url": "https://github.com/a/b/issues/1",
                                                     "label": "help wanted", "updated": "1 days ago"}],
                      contributing="https://github.com/a/b/blob/main/CONTRIBUTING.md"), self.INFOS[1]]
        data = st.digests_json(self.ENTRIES, infos, "t")
        self.assertEqual(data["entries"][0]["contribution_opportunities"][0]["title"], "T")
        self.assertEqual(data["entries"][0]["contributing_guide"], "https://github.com/a/b/blob/main/CONTRIBUTING.md")
        self.assertEqual(data["entries"][1]["contribution_opportunities"], [])
        self.assertEqual(data["entries"][1]["contributing_guide"], "")

    def test_json_records(self):
        data = st.digests_json(self.ENTRIES, self.INFOS, "2026-11-16T12:00:00+00:00")
        self.assertEqual(data["count"], 2)
        first = data["entries"][0]
        self.assertEqual((first["repo"], first["stars_at_pick"], first["why_picked"]), ("acme/agent", 1000, "1,000 stars"))
        self.assertEqual(first["url"], "https://github.com/acme/agent")
        self.assertIsNone(data["entries"][1]["fork_url"])


if __name__ == "__main__":
    unittest.main()
