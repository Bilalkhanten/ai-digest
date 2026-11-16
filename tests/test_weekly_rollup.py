"""Offline tests for scripts/weekly_rollup.py."""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import weekly_rollup as wr  # noqa: E402

STATE = [
    {"date": "2026-11-09", "repo": "a/old", "stars": 5, "topic": "rag", "fork_url": None},   # previous week
    {"date": "2026-11-16", "repo": "b/one", "stars": 1500, "topic": "llm", "fork_url": "https://github.com/me/one"},
    {"date": "2026-11-17", "repo": "c/two", "stars": 800, "topic": "llm", "fork_url": None},
    {"date": "2026-11-18", "repo": "d/three", "stars": 300, "topic": "mcp", "fork_url": None},
]
PAGE = "# x\n\n> desc\n\n- Language: {lang}\n- License: MIT\n"


class WeekTests(unittest.TestCase):
    def test_week_key_is_iso(self):
        self.assertEqual(wr.week_key(date(2026, 11, 16)), "2026-W47")
        self.assertEqual(wr.week_key(date(2026, 1, 1)), "2026-W01")

    def test_only_entries_in_the_same_iso_week(self):
        got = wr.week_entries(STATE, date(2026, 11, 18))
        self.assertEqual([e["repo"] for e in got], ["b/one", "c/two", "d/three"])


class GainersTests(unittest.TestCase):
    DAY = date(2026, 11, 18)

    def test_only_picks_that_gained_and_biggest_gain_first(self):
        # a/old (picked Nov 9) is within 30 days: 5 -> 9999. c/two fell and d/three is unchanged.
        stars_now = {"a/old": 9999, "b/one": 2500, "c/two": 700, "d/three": 300}
        rows = wr.gainers_rows(STATE, self.DAY, stars_now)
        self.assertEqual([r["repo"] for r in rows], ["a/old", "b/one"])

    def test_old_picks_fall_outside_the_window(self):
        old_state = STATE + [{"date": "2026-09-01", "repo": "e/ancient", "stars": 10, "topic": "x", "fork_url": None}]
        rows = wr.gainers_rows(old_state, self.DAY, {"e/ancient": 5000, "b/one": 1600})
        self.assertEqual([r["repo"] for r in rows], ["b/one"])

    def test_limit_and_ordering(self):
        state = [{"date": "2026-11-10", "repo": f"o/r{i}", "stars": 100, "topic": "t", "fork_url": None} for i in range(8)]
        now = {f"o/r{i}": 100 + i * 10 for i in range(8)}
        rows = wr.gainers_rows(state, self.DAY, now, limit=3)
        self.assertEqual([r["repo"] for r in rows], ["o/r7", "o/r6", "o/r5"])

    def test_unknown_star_counts_are_skipped(self):
        self.assertEqual(wr.gainers_rows(STATE, self.DAY, {}), [])

    def test_section_renders_only_when_there_are_gainers(self):
        entries = wr.week_entries(STATE, date(2026, 11, 16))
        infos = [{"language": "x", "description": "", "license": "", "summary": ""}] * 3
        rows = wr.gainers_rows(STATE, self.DAY, {"b/one": 1800})
        text = wr.render_weekly("2026-W47", entries, infos, gainers=rows)
        self.assertIn("## Biggest gainers (picks from the last 30 days)", text)
        self.assertIn("| [b/one](https://github.com/b/one) | 2026-11-16 | 1,500 | 1,800 | +300 (+20%) |", text)
        self.assertNotIn("Biggest gainers", wr.render_weekly("2026-W47", entries, infos))


class RenderTests(unittest.TestCase):
    def test_counts_and_links(self):
        entries = wr.week_entries(STATE, date(2026, 11, 16))
        infos = [{"language": "Python", "description": "d", "license": "n/a", "summary": ""}] * 2 + [
            {"language": "Go", "description": "d", "license": "n/a", "summary": ""}]
        text = wr.render_weekly("2026-W47", entries, infos, "Agents everywhere.")
        self.assertIn("# Week 2026-W47", text)
        self.assertIn("3 repos featured, 2026-11-16 to 2026-11-18", text)
        self.assertIn("(https://github.com/me/one)", text)       # fork link used
        self.assertIn("(https://github.com/c/two)", text)        # original used when no fork
        self.assertIn("- llm: 2", text)
        self.assertIn("- Python: 2", text)
        self.assertIn("## Themes", text)

    def test_no_themes_section_without_text(self):
        entries = wr.week_entries(STATE, date(2026, 11, 16))
        infos = [{"language": "x", "description": "", "license": "", "summary": ""}] * 3
        self.assertNotIn("## Themes", wr.render_weekly("2026-W47", entries, infos))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "digest").mkdir()
        for e in STATE:
            (root / "digest" / f"{e['date']}.md").write_text(PAGE.format(lang="Python"))
        self.patches = [
            mock.patch.object(wr, "ROOT", root),
            mock.patch.object(wr, "DIGEST_DIR", root / "digest"),
            mock.patch.object(wr, "WEEKLY_DIR", root / "digest" / "weekly"),
            mock.patch.object(wr, "ANTHROPIC_KEY", ""),
        ]
        for p in self.patches:
            p.start()
        self.root = root

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_writes_page_then_skips_when_it_exists(self):
        path = wr.run(date(2026, 11, 18), state=STATE)
        self.assertEqual(path.name, "2026-W47.md")
        self.assertIn("Python", path.read_text())
        self.assertIsNone(wr.run(date(2026, 11, 18), state=STATE))        # idempotent
        self.assertIsNotNone(wr.run(date(2026, 11, 18), force=True, state=STATE))

    def test_empty_week_writes_nothing(self):
        self.assertIsNone(wr.run(date(2026, 12, 20), state=STATE))
        self.assertFalse((self.root / "digest" / "weekly").exists())

    def test_missing_digest_page_does_not_break_the_rollup(self):
        (self.root / "digest" / "2026-11-17.md").unlink()
        self.assertIsNotNone(wr.run(date(2026, 11, 18), state=STATE))


if __name__ == "__main__":
    unittest.main()
