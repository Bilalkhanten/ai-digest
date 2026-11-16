"""Offline tests for scripts/daily_fork.py. GitHub and Anthropic are never contacted."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import daily_fork as df  # noqa: E402


def make_repo(name="acme/agent", stars=500, owner=None):
    owner = owner or name.split("/")[0]
    return {
        "full_name": name,
        "owner": {"login": owner},
        "html_url": f"https://github.com/{name}",
        "description": "An agent framework.",
        "stargazers_count": stars,
        "language": "Python",
        "license": {"spdx_id": "MIT"},
        "pushed_at": "2026-11-16T10:00:00Z",
        "topics": ["llm", "agents"],
    }


class FakeGitHub:
    """Routes df.gh() calls to canned responses and records writes."""

    def __init__(self, items):
        self.items = items
        self.calls = []

    def __call__(self, method, path, data=None, accept=None):
        self.calls.append((method, path))
        if path == "/user":
            return json.dumps({"login": "me", "id": 42})
        if path.startswith("/search/repositories"):
            return json.dumps({"items": self.items})
        if path.endswith("/readme"):
            return "# readme"
        if method == "POST" and path.endswith("/forks"):
            name = path.split("/repos/")[1].rsplit("/forks", 1)[0]
            return json.dumps({"html_url": f"https://github.com/me/{name.split('/')[1]}"})
        raise AssertionError(f"unexpected call {method} {path}")


class FindCandidateTests(unittest.TestCase):
    def test_skips_already_forked_and_own_repos(self):
        items = [make_repo("a/one"), make_repo("me/mine"), make_repo("b/two")]
        with mock.patch.object(df, "gh", FakeGitHub(items)):
            topic, repo = df.find_candidate({"a/one"}, "Me")
        self.assertEqual(repo["full_name"], "b/two")
        self.assertIn(topic, df.TOPICS)

    def test_returns_none_when_nothing_qualifies(self):
        with mock.patch.object(df, "gh", FakeGitHub([make_repo("a/one")])):
            topic, repo = df.find_candidate({"a/one"}, "me")
        self.assertIsNone(topic)
        self.assertIsNone(repo)

    def test_search_query_uses_configured_thresholds(self):
        fake = FakeGitHub([make_repo()])
        with mock.patch.object(df, "gh", fake), mock.patch.object(df, "MIN_STARS", 123):
            df.find_candidate(set(), "me")
        self.assertIn("stars%3A%3E%3D123", fake.calls[0][1])


class RenderTests(unittest.TestCase):
    def test_digest_has_core_fields_and_optional_summary(self):
        page = df.render_digest("2026-11-16", "llm", make_repo(stars=1234), "- a\n- b\n- c")
        for expected in ("# acme/agent", "Stars: 1,234", "License: MIT", "## Summary"):
            self.assertIn(expected, page)
        self.assertNotIn("## Summary", df.render_digest("2026-11-16", "llm", make_repo(), ""))

    def test_index_is_newest_first(self):
        state = [
            {"date": "2026-11-15", "repo": "a/old", "stars": 1, "topic": "rag", "fork_url": "u1"},
            {"date": "2026-11-16", "repo": "b/new", "stars": 2, "topic": "llm", "fork_url": "u2"},
        ]
        index = df.render_index(state)
        self.assertLess(index.index("b/new"), index.index("a/old"))


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            mock.patch.object(df, "STATE_FILE", root / "forked.json"),
            mock.patch.object(df, "DIGEST_DIR", root / "digest"),
            mock.patch.object(df, "INDEX_FILE", root / "INDEX.md"),
            mock.patch.object(df, "TOKEN", "tok"),
            mock.patch.object(df, "DRY_RUN", False),
            mock.patch.object(df, "ANTHROPIC_KEY", ""),
        ]
        for p in self.patches:
            p.start()
        self.root = root
        self.out = root / "gh_output"
        self.summary = root / "gh_summary"
        self.env = mock.patch.dict(
            os.environ,
            {"GITHUB_OUTPUT": str(self.out), "GITHUB_STEP_SUMMARY": str(self.summary)},
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_real_run_forks_writes_files_and_sets_noreply_identity(self):
        fake = FakeGitHub([make_repo("acme/agent", stars=900)])
        with mock.patch.object(df, "gh", fake):
            self.assertEqual(df.main(), 0)

        self.assertIn(("POST", "/repos/acme/agent/forks"), fake.calls)
        state = json.loads((self.root / "forked.json").read_text())
        self.assertEqual([e["repo"] for e in state], ["acme/agent"])
        self.assertEqual(len(list((self.root / "digest").glob("*.md"))), 1)
        self.assertIn("acme/agent", (self.root / "INDEX.md").read_text())

        outputs = self.out.read_text()
        self.assertIn("picked=acme/agent", outputs)
        self.assertIn("commit_email=42+me@users.noreply.github.com", outputs)
        self.assertIn("Forked `acme/agent`", self.summary.read_text())

    def test_second_run_same_day_is_a_noop(self):
        fake = FakeGitHub([make_repo("acme/agent")])
        with mock.patch.object(df, "gh", fake):
            df.main()
            fake.calls.clear()
            self.assertEqual(df.main(), 0)
        self.assertEqual(fake.calls, [])

    def test_dry_run_writes_and_forks_nothing(self):
        fake = FakeGitHub([make_repo("acme/agent")])
        with mock.patch.object(df, "gh", fake), mock.patch.object(df, "DRY_RUN", True):
            self.assertEqual(df.main(), 0)
        self.assertNotIn(("POST", "/repos/acme/agent/forks"), fake.calls)
        self.assertFalse((self.root / "forked.json").exists())
        self.assertFalse((self.root / "digest").exists())
        self.assertFalse(self.out.exists())

    def test_failed_fork_leaves_no_files(self):
        def failing(method, path, data=None, accept=None):
            if method == "POST":
                raise df.ApiError("boom")
            return FakeGitHub([make_repo()])(method, path, data, accept)

        with mock.patch.object(df, "gh", failing):
            with self.assertRaises(df.ApiError):
                df.main()
        self.assertFalse((self.root / "forked.json").exists())
        self.assertFalse((self.root / "digest").exists())

    def test_missing_token_without_dry_run_exits(self):
        with mock.patch.object(df, "gh", FakeGitHub([make_repo()])), mock.patch.object(df, "TOKEN", ""):
            with self.assertRaises(SystemExit):
                df.main()


def http_error(code, headers=None):
    return urllib.error.HTTPError("u", code, "err", headers or {}, io.BytesIO(b"{}"))


class RetryTests(unittest.TestCase):
    def test_retries_transient_errors_then_succeeds(self):
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b"fine"
        with mock.patch.object(df.urllib.request, "urlopen", side_effect=[http_error(502), ok]) as op, \
                mock.patch.object(df.time, "sleep") as sleep:
            self.assertEqual(df.gh("GET", "/x"), "fine")
        self.assertEqual(op.call_count, 2)
        sleep.assert_called_once()

    def test_does_not_retry_client_errors(self):
        with mock.patch.object(df.urllib.request, "urlopen", side_effect=http_error(404)) as op, \
                mock.patch.object(df.time, "sleep") as sleep:
            with self.assertRaises(df.ApiError):
                df.gh("GET", "/x")
        self.assertEqual(op.call_count, 1)
        sleep.assert_not_called()

    def test_gives_up_after_max_attempts(self):
        errors = [http_error(503) for _ in range(df.MAX_ATTEMPTS)]
        with mock.patch.object(df.urllib.request, "urlopen", side_effect=errors) as op, \
                mock.patch.object(df.time, "sleep"):
            with self.assertRaises(df.ApiError):
                df.gh("GET", "/x")
        self.assertEqual(op.call_count, df.MAX_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
