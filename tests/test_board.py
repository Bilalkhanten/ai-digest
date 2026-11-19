"""Offline tests for scripts/board.py (the Contribute board). GitHub is never contacted."""
import sys
import unittest
import urllib.parse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import board as bd  # noqa: E402

TODAY = date(2026, 11, 19)
CSS = "body{}"


def issue(number, title="Fix it", updated="2026-11-10T00:00:00Z", **extra):
    return {"number": number, "title": title, "state": "open", "updated_at": updated, "assignees": [], **extra}


def entries(*names):
    return [{"date": f"2026-11-{19 - i:02d}", "repo": n, "stars": 1, "topic": "llm", "fork_url": None}
            for i, n in enumerate(names)]


class FakeGet:
    """Maps (repo, label) -> list of issues, an Exception, or a non-list."""

    def __init__(self, data):
        self.data, self.calls = data, []

    def __call__(self, path):
        self.calls.append(path)
        repo = path.split("/repos/")[1].split("/issues?")[0]
        label = urllib.parse.parse_qs(path.split("?", 1)[1])["labels"][0]
        result = self.data.get((repo, label), [])
        if isinstance(result, Exception):
            raise result
        return result


class FetchBoardTests(unittest.TestCase):
    def test_collects_issues_per_repo_and_skips_repos_with_none(self):
        get = FakeGet({("a/one", "good first issue"): [issue(1)], ("a/one", "help wanted"): [issue(2)]})
        got = bd.fetch_board(entries("a/one", "b/two"), TODAY, get=get)
        self.assertEqual([b["repo"] for b in got], ["a/one"])
        self.assertEqual([i["url"][-1] for i in got[0]["issues"]], ["1", "2"])
        self.assertEqual(got[0]["date"], "2026-11-19")

    def test_limits_repos_and_issues_per_repo(self):
        many = {("a/one", "good first issue"): [issue(n) for n in range(1, 10)]}
        get = FakeGet(many)
        got = bd.fetch_board(entries("a/one", "b/two", "c/three"), TODAY, max_repos=2, per_repo=2, get=get)
        self.assertEqual(len(got[0]["issues"]), 2)
        self.assertFalse([c for c in get.calls if "c/three" in c])

    def test_assigned_stale_and_pull_request_items_are_excluded(self):
        get = FakeGet({("a/one", "good first issue"): [
            issue(1, assignees=[{"login": "x"}]), issue(2, updated="2024-01-01T00:00:00Z"),
            issue(3, pull_request={"url": "u"}), issue(4)]})
        got = bd.fetch_board(entries("a/one"), TODAY, get=get)
        self.assertEqual([i["url"][-1] for i in got[0]["issues"]], ["4"])

    def test_one_failure_skips_that_repo_only(self):
        get = FakeGet({("a/one", "good first issue"): OSError("boom"), ("b/two", "good first issue"): [issue(5)]})
        got = bd.fetch_board(entries("a/one", "b/two"), TODAY, get=get)
        self.assertEqual([b["repo"] for b in got], ["b/two"])

    def test_repeated_failures_stop_early_and_nothing_raises(self):
        boom = OSError("rate limited")
        names = [f"o/r{i}" for i in range(10)]
        get = FakeGet({(n, "good first issue"): boom for n in names})
        self.assertEqual(bd.fetch_board(entries(*names), TODAY, get=get), [])
        self.assertEqual(len(get.calls), bd.MAX_FAILURES)

    def test_a_success_resets_the_failure_count(self):
        boom = OSError("x")
        data = {("o/a", "good first issue"): boom, ("o/b", "good first issue"): boom,
                ("o/c", "good first issue"): [issue(1)],
                ("o/d", "good first issue"): boom, ("o/e", "good first issue"): boom,
                ("o/f", "good first issue"): [issue(2)]}
        got = bd.fetch_board(entries("o/a", "o/b", "o/c", "o/d", "o/e", "o/f"), TODAY, get=FakeGet(data))
        self.assertEqual([b["repo"] for b in got], ["o/c", "o/f"])

    def test_a_missing_repo_or_junk_response_is_just_empty(self):
        class Gone(FakeGet):
            def __call__(self, path):
                return None
        self.assertEqual(bd.fetch_board(entries("a/one"), TODAY, get=Gone({})), [])

    def test_labels_are_url_encoded_in_the_request(self):
        get = FakeGet({})
        bd.fetch_board(entries("a/one"), TODAY, labels=["good first issue"], get=get)
        self.assertIn("labels=good+first+issue", get.calls[0])


class RenderTests(unittest.TestCase):
    def test_page_lists_repos_issues_and_counts(self):
        board = [{"repo": "a/one", "date": "2026-11-19", "issues": [
            {"title": "Fix typo", "url": "https://github.com/a/one/issues/1", "label": "help wanted",
             "updated": "3 days ago"}]}]
        html = bd.render_board_page(CSS, board, "2026-11-19 07:00 UTC")
        self.assertIn("<a href='https://github.com/a/one'>a/one</a>", html)
        self.assertIn("<a href='https://github.com/a/one/issues/1'>Fix typo</a>", html)
        self.assertIn("1 issues across 1 repos", html)
        self.assertIn("index.html", html)

    def test_empty_board_has_a_friendly_message(self):
        self.assertIn("No open beginner-friendly issues", bd.render_board_page(CSS, [], "now"))

    def test_everything_is_escaped(self):
        board = [{"repo": "a/<b>", "date": "<d>", "issues": [
            {"title": "<script>alert(1)</script>", "url": "https://github.com/a/x/issues/1' onclick='x",
             "label": "<i>", "updated": "<u>"}]}]
        html = bd.render_board_page(CSS, board, "<g>")
        for raw in ("<script>alert(1)", "<b>", "<i>", "<u>", "<d>", "<g>", "' onclick='"):
            self.assertNotIn(raw, html)


if __name__ == "__main__":
    unittest.main()
