"""Offline tests for scripts/fork_inventory.py. No network: fetch is injected."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fork_inventory as fi  # noqa: E402

TODAY = date(2026, 11, 16)


def entry(day, repo, forked=True):
    return {"date": day, "repo": repo, "stars": 1, "topic": "llm",
            "fork_url": f"https://github.com/me/{repo.split('/')[1]}" if forked else None}


class InspectTests(unittest.TestCase):
    def test_flags_archived_deleted_and_old(self):
        def get(path):
            return {"/repos/a/arch": {"archived": True, "stargazers_count": 9},
                    "/repos/b/live": {"archived": False, "stargazers_count": 50},
                    "/repos/c/gone": None,
                    "/repos/d/old": {"archived": False, "stargazers_count": 5}}[path]

        r = fi.inspect_fork(entry("2026-11-01", "a/arch"), TODAY, get)
        self.assertEqual(r["reasons"], ["original archived"])
        self.assertEqual(fi.inspect_fork(entry("2026-11-01", "b/live"), TODAY, get)["reasons"], [])
        gone = fi.inspect_fork(entry("2026-11-01", "c/gone"), TODAY, get)
        self.assertEqual((gone["reasons"], gone["stars_now"]), (["original deleted"], None))
        old = fi.inspect_fork(entry("2026-01-01", "d/old"), TODAY, get)
        self.assertEqual(old["reasons"], [f"older than {fi.PRUNE_AFTER_DAYS} days"])

    def test_fork_slug(self):
        self.assertEqual(fi.fork_slug("https://github.com/me/agent"), "me/agent")


class RenderTests(unittest.TestCase):
    def test_report_lists_candidates_and_never_calls_anything_but_get(self):
        calls = []

        def get(path):
            calls.append(path)
            return {"archived": path.endswith("arch"), "stargazers_count": 3}

        state = [entry("2026-11-10", "a/arch"), entry("2026-11-11", "b/live"), entry("2026-11-12", "c/none", forked=False)]
        report = fi.render(state, TODAY, get)
        self.assertIn("2 forks made by this tool (1 digest-only days)", report)
        self.assertIn("Candidates to review (1)", report)
        self.assertIn("https://github.com/me/arch/settings", report)
        self.assertEqual(sorted(calls), ["/repos/a/arch", "/repos/b/live"])  # digest-only day is not fetched
        self.assertIn("Nothing is deleted automatically", report)

    def test_no_candidates_message(self):
        report = fi.render([entry("2026-11-10", "b/live")], TODAY, lambda p: {"archived": False, "stargazers_count": 1})
        self.assertIn("None.", report)

    def test_caps_the_number_of_rows(self):
        state = [entry(f"2026-{m:02d}-{d:02d}", f"o/r{m}{d}") for m in range(1, 5) for d in range(1, 29)]
        report = fi.render(state, TODAY, lambda p: {"archived": False, "stargazers_count": 1})
        self.assertIn(f"Showing the newest {fi.MAX_ROWS}", report)


if __name__ == "__main__":
    unittest.main()
