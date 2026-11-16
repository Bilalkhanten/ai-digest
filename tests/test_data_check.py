"""Tests for scripts/data_check.py: a healthy tree passes, and each corruption is caught."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import data_check as dc  # noqa: E402

TODAY = date(2026, 11, 20)


def entry(day, repo, stars=1000, topic="llm", fork=True):
    return {"date": day, "repo": repo, "stars": stars, "topic": topic,
            "fork_url": f"https://github.com/me/{repo.split('/')[1]}" if fork else None}


def digest(day, repo):
    return f"# {repo}\n\n> A project.\n\n- Date picked: {day} (topic: `llm`)\n- Stars: 1,000\n"


class Tree(unittest.TestCase):
    """Builds a small, healthy repository layout under a temp directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = [entry("2026-10-18", "a/one"), entry("2026-10-19", "b/two", fork=False)]
        self.write_all()

    def write_all(self):
        (self.root / "digest" / "weekly").mkdir(parents=True, exist_ok=True)
        (self.root / "forked.json").write_text(json.dumps(self.state))
        for stale in (self.root / "digest").glob("20*.md"):
            stale.unlink()                      # start each layout from a clean digest folder
        for e in self.state:
            (self.root / "digest" / f"{e['date']}.md").write_text(digest(e["date"], e["repo"]))
        newest = sorted(self.state, key=lambda x: x["date"], reverse=True)

        def rows(items):
            return "\n".join(f"| {e['date']} | [{e['repo']}](x) | 1 | llm |" for e in items)

        (self.root / "INDEX.md").write_text("# Index\n\n| Date | Repo |\n|---|---|\n" + rows(newest) + "\n")
        block = "| Date | Repo | Stars | Topic |\n|---|---|---|---|\n" + rows(newest[: dc.LATEST_COUNT])
        (self.root / "README.md").write_text(f"# R\n\n{dc.LATEST_START}\n{block}\n{dc.LATEST_END}\n")
        (self.root / "digest" / "weekly" / "2026-W47.md").write_text("# Week 2026-W47\n\nbody\n")
        (self.root / "config.json").write_text(json.dumps({
            "topics": ["llm", "rag", "kubernetes"], "areas": {"AI": ["llm", "rag"], "Platform": ["kubernetes"]}}))

    def problems(self):
        return dc.check(self.root, TODAY)

    def assertHas(self, fragment):
        found = self.problems()
        self.assertTrue(any(fragment in p for p in found), f"expected a problem containing {fragment!r}, got {found}")

    def set_state(self, state):
        self.state = state
        (self.root / "forked.json").write_text(json.dumps(state))


class HealthyTests(Tree):
    def test_a_healthy_tree_has_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_an_empty_repository_is_fine(self):
        self.state = []
        self.write_all()
        self.assertEqual(self.problems(), [])

    def test_missing_optional_files_are_fine(self):
        (self.root / "README.md").unlink()
        (self.root / "config.json").unlink()
        (self.root / "digest" / "weekly" / "2026-W47.md").unlink()
        self.assertEqual(self.problems(), [])

    def test_readme_without_the_block_is_fine(self):
        (self.root / "README.md").write_text("# no markers here\n")
        self.assertEqual(self.problems(), [])


class StateTests(Tree):
    def test_invalid_json(self):
        (self.root / "forked.json").write_text("{not json")
        self.assertHas("not valid JSON")

    def test_missing_file(self):
        (self.root / "forked.json").unlink()
        self.assertHas("forked.json is missing")

    def test_not_a_list(self):
        (self.root / "forked.json").write_text('{"a": 1}')
        self.assertHas("not a JSON list")

    def test_entry_not_an_object(self):
        self.set_state(["junk"])
        self.assertHas("is not an object")

    def test_bad_and_missing_dates(self):
        self.set_state([{**entry("2026-10-18", "a/one"), "date": "18/11/2026"}])
        self.assertHas("bad or missing date")

    def test_future_date(self):
        self.set_state([entry("2026-12-31", "a/one")])
        (self.root / "digest" / "2026-12-31.md").write_text(digest("2026-12-31", "a/one"))
        self.assertHas("in the future")

    def test_bad_repo_names(self):
        for bad in ("noslash", "a/b/c", "has space/x", "", None, 5):
            self.set_state([{**entry("2026-10-18", "a/one"), "repo": bad}])
            self.assertHas("bad repo")

    def test_bad_stars(self):
        for bad in (-1, "12", 1.5, True, None):
            self.set_state([{**entry("2026-10-18", "a/one"), "stars": bad}])
            self.assertHas("stars must be")

    def test_missing_topic(self):
        self.set_state([{**entry("2026-10-18", "a/one"), "topic": "  "}])
        self.assertHas("missing topic")

    def test_bad_fork_url(self):
        for bad in ("http://github.com/a/b", "https://evil.example/a/b", "https://github.com/a", 5):
            self.set_state([{**entry("2026-10-18", "a/one"), "fork_url": bad}])
            self.assertHas("bad fork_url")

    def test_duplicate_date_and_duplicate_repo(self):
        self.set_state([entry("2026-10-18", "a/one"), entry("2026-10-18", "c/three")])
        self.assertHas("duplicate date")
        self.set_state([entry("2026-10-18", "a/one"), entry("2026-10-19", "A/One")])
        self.assertHas("already picked")


class DigestTests(Tree):
    def test_missing_digest_page(self):
        (self.root / "digest" / "2026-10-18.md").unlink()
        self.assertHas("digest/2026-10-18.md is missing")

    def test_heading_mismatch(self):
        (self.root / "digest" / "2026-10-18.md").write_text(digest("2026-10-18", "x/other"))
        self.assertHas("expected a/one")

    def test_missing_heading(self):
        (self.root / "digest" / "2026-10-18.md").write_text("no heading\n")
        self.assertHas("heading is missing")

    def test_date_picked_mismatch(self):
        (self.root / "digest" / "2026-10-18.md").write_text(digest("2026-10-01", "a/one"))
        self.assertHas("'Date picked' line does not match")

    def test_orphan_digest_page(self):
        (self.root / "digest" / "2026-10-01.md").write_text(digest("2026-10-01", "z/orphan"))
        self.assertHas("has no entry in forked.json")

    def test_non_date_markdown_files_are_ignored(self):
        (self.root / "digest" / "notes.md").write_text("scratch")
        self.assertEqual(self.problems(), [])


class IndexAndReadmeTests(Tree):
    def test_index_row_count_and_missing_repo(self):
        (self.root / "INDEX.md").write_text("| 2026-10-18 | a/one |\n")
        found = self.problems()
        self.assertTrue(any("1 rows but forked.json has 2" in p for p in found))
        self.assertTrue(any("does not mention b/two" in p for p in found))

    def test_missing_index(self):
        (self.root / "INDEX.md").unlink()
        self.assertHas("INDEX.md is missing")

    def test_old_index_format_is_accepted(self):
        old = "| Date | Repo | Stars | Topic | Notes |\n|---|---|---|---|---|\n"
        old += "\n".join(f"| {e['date']} | [{e['repo']}](u) | 1 | llm | [digest](d) |" for e in self.state) + "\n"
        (self.root / "INDEX.md").write_text(old)
        self.assertEqual(self.problems(), [])

    def test_stale_readme_block(self):
        (self.root / "README.md").write_text(f"{dc.LATEST_START}\n| 2026-10-01 | [old/repo](x) | 1 | llm |\n{dc.LATEST_END}\n")
        self.assertHas("README latest-picks block is out of date")

    def test_readme_block_only_needs_the_newest_seven(self):
        self.state = [entry(f"2026-10-{d:02d}", f"o/r{d}") for d in range(1, 11)]
        self.write_all()
        self.assertEqual(self.problems(), [])


class WeeklyAndConfigTests(Tree):
    def test_bad_weekly_names_and_headings(self):
        w = self.root / "digest" / "weekly"
        (w / "week-47.md").write_text("# Week x\n")
        (w / "2026-W99.md").write_text("# Week 2026-W99\n")
        (w / "2026-W46.md").write_text("# Something else\n")
        found = self.problems()
        self.assertTrue(any("week-47.md: name is not" in p for p in found))
        self.assertTrue(any("2026-W99.md: not a real ISO week" in p for p in found))
        self.assertTrue(any("2026-W46.md: first line should be" in p for p in found))

    def test_config_duplicates_and_uncovered_topics(self):
        (self.root / "config.json").write_text(json.dumps({
            "topics": ["llm", "llm", "rag", "orphan"], "areas": {"AI": ["llm"], "Other": ["llm", "ghost"]}}))
        found = " | ".join(self.problems())
        self.assertIn("duplicate topics", found)
        self.assertIn("more than one area", found)
        self.assertIn("without an area: orphan, rag", found)
        self.assertIn("not in the rotation: ghost", found)

    def test_invalid_config_json(self):
        (self.root / "config.json").write_text("{nope")
        self.assertHas("config.json is not valid JSON")


class OutputTests(Tree):
    def test_main_exit_codes_and_report(self):
        self.assertEqual(dc.main([str(self.root)]), 0)
        (self.root / "digest" / "2026-10-18.md").unlink()
        self.assertEqual(dc.main([str(self.root)]), 1)

    def test_every_problem_is_reported_not_just_the_first(self):
        (self.root / "digest" / "2026-10-18.md").unlink()
        (self.root / "INDEX.md").unlink()
        self.assertGreaterEqual(len(self.problems()), 2)


if __name__ == "__main__":
    unittest.main()
