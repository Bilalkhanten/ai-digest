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


LONG_README = "# Project\n" + "A useful description of the project. " * 30


class FakeGitHub:
    """Routes df.gh() calls to canned responses and records writes."""

    def __init__(self, items, readmes=None, releases=None):
        self.items = items
        self.readmes = readmes or {}
        self.releases = releases or {}
        self.calls = []

    def __call__(self, method, path, data=None, accept=None):
        self.calls.append((method, path))
        if path == "/user":
            return json.dumps({"login": "me", "id": 42})
        if path.startswith("/search/repositories"):
            return json.dumps({"items": self.items})
        if path.endswith("/readme"):
            return self.readmes.get(path.split("/repos/")[1].rsplit("/readme", 1)[0], LONG_README)
        if path.endswith("/releases/latest"):
            name = path.split("/repos/")[1].rsplit("/releases/latest", 1)[0]
            if name not in self.releases:
                raise df.ApiError("GET release -> HTTP 404")
            return json.dumps(self.releases[name])
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
        self.assertIn("fork_url=https://github.com/me/agent", outputs)
        self.assertIn("commit_email=42+me@users.noreply.github.com", outputs)
        self.assertIn("Digest for `acme/agent`", self.summary.read_text())

    def test_real_run_page_includes_release_and_readme_facts(self):
        fake = FakeGitHub(
            [make_repo("acme/agent", stars=900)],
            readmes={"acme/agent": "# Agent\n\nAcme Agent is a framework for building reliable tool using "
                     "agents with typed plans and good tracing support.\n\n## Quickstart\n\n```\n"
                     "pip install acme-agent\n```\n" + "More text here. " * 40},
            releases={"acme/agent": {"tag_name": "v3.1.0", "published_at": "2026-11-10T00:00:00Z"}},
        )
        with mock.patch.object(df, "gh", fake):
            df.main()
        page = next((self.root / "digest").glob("*.md")).read_text()
        self.assertIn("Latest release: v3.1.0 (2026-11-10)", page)
        self.assertIn("Install: `pip install acme-agent`", page)
        self.assertIn("README sections: Quickstart", page)
        self.assertIn("README excerpt: Acme Agent is a framework", page)

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

    def test_digest_only_day_writes_files_but_does_not_fork(self):
        fake = FakeGitHub([make_repo("acme/agent")])
        with mock.patch.object(df, "gh", fake), mock.patch.object(df, "FORK_EVERY_DAYS", 0):
            self.assertEqual(df.main(), 0)
        self.assertFalse(any(m == "POST" for m, _ in fake.calls))
        state = json.loads((self.root / "forked.json").read_text())
        self.assertIsNone(state[0]["fork_url"])
        self.assertIn("fork_url=\n", self.out.read_text())
        self.assertIn("digest only", self.summary.read_text())

    def test_stub_readme_everywhere_means_no_candidate_and_no_files(self):
        fake = FakeGitHub([make_repo("acme/agent")], readmes={"acme/agent": "# tiny"})
        with mock.patch.object(df, "gh", fake):
            self.assertEqual(df.main(), 0)
        self.assertFalse((self.root / "forked.json").exists())
        self.assertIn("No candidate", self.summary.read_text())

    def test_missing_token_without_dry_run_exits(self):
        with mock.patch.object(df, "gh", FakeGitHub([make_repo()])), mock.patch.object(df, "TOKEN", ""):
            with self.assertRaises(SystemExit):
                df.main()


class ExclusionTests(unittest.TestCase):
    def cfg(self, **overrides):
        return mock.patch.object(df, "CONFIG", {**df.DEFAULT_CONFIG, **overrides})

    def test_name_pattern_and_description_keyword(self):
        awesome = make_repo("a/awesome-llm")
        listy = {**make_repo("a/other"), "description": "A Curated List of things"}
        with self.cfg():
            self.assertTrue(df.is_excluded(awesome))
            self.assertTrue(df.is_excluded(listy))
            self.assertFalse(df.is_excluded(make_repo("a/agent")))

    def test_explicit_repo_and_owner_lists_are_case_insensitive(self):
        with self.cfg(exclude_repos=["Acme/Agent"], exclude_owners=["Spammer"]):
            self.assertTrue(df.is_excluded(make_repo("acme/agent")))
            self.assertTrue(df.is_excluded(make_repo("spammer/x")))
            self.assertFalse(df.is_excluded(make_repo("fine/x")))

    def test_empty_repo_is_excluded(self):
        with self.cfg():
            self.assertTrue(df.is_excluded({**make_repo(), "size": 0}))

    def test_excluded_repos_never_reach_the_candidate_pool(self):
        items = [make_repo("a/awesome-x"), make_repo("b/real")]
        with mock.patch.object(df, "gh", FakeGitHub(items)), \
                mock.patch.object(df, "CONFIG", {**df.DEFAULT_CONFIG}):
            _, pool = df.find_candidates(set(), "me")
        self.assertEqual([r["full_name"] for r in pool], ["b/real"])


class ChooseRepoTests(unittest.TestCase):
    def test_skips_stub_readmes_and_takes_the_next_candidate(self):
        pool = [make_repo("a/stub"), make_repo("b/good")]
        fake = FakeGitHub([], readmes={"a/stub": "# tiny"})
        with mock.patch.object(df, "gh", fake):
            repo, readme = df.choose_repo(pool)
        self.assertEqual(repo["full_name"], "b/good")
        self.assertGreaterEqual(len(readme), 500)

    def test_returns_none_when_all_readmes_are_stubs(self):
        pool = [make_repo("a/stub")]
        with mock.patch.object(df, "gh", FakeGitHub([], readmes={"a/stub": ""})):
            self.assertEqual(df.choose_repo(pool), (None, ""))

    def test_weighted_order_returns_every_repo_exactly_once(self):
        pool = [make_repo(f"o/r{i}", stars=100 * (i + 1)) for i in range(6)]
        ordered = df.weighted_order(pool)
        self.assertEqual(sorted(r["full_name"] for r in ordered), sorted(r["full_name"] for r in pool))

    def test_weighted_order_prefers_popular_repos(self):
        pool = [make_repo("o/small", stars=100), make_repo("o/big", stars=1_000_000)]
        wins = sum(df.weighted_order(pool)[0]["full_name"] == "o/big" for _ in range(300))
        self.assertGreater(wins, 200)


class ForkCadenceTests(unittest.TestCase):
    def state(self, *pairs):
        return [{"date": d, "repo": f"o/r{i}", "stars": 1, "topic": "llm", "fork_url": u}
                for i, (d, u) in enumerate(pairs)]

    def test_daily_default_forks_every_day(self):
        with mock.patch.object(df, "FORK_EVERY_DAYS", 1):
            self.assertTrue(df.should_fork(self.state(("2026-11-15", "u")), "2026-11-16"))

    def test_weekly_cadence_waits_for_the_gap(self):
        with mock.patch.object(df, "FORK_EVERY_DAYS", 7):
            st = self.state(("2026-11-10", "u"))
            self.assertFalse(df.should_fork(st, "2026-11-16"))
            self.assertTrue(df.should_fork(st, "2026-11-17"))

    def test_digest_only_days_do_not_reset_the_clock(self):
        with mock.patch.object(df, "FORK_EVERY_DAYS", 7):
            st = self.state(("2026-11-10", "u"), ("2026-11-14", None))
            self.assertTrue(df.should_fork(st, "2026-11-17"))

    def test_zero_means_never_and_first_run_always_forks(self):
        with mock.patch.object(df, "FORK_EVERY_DAYS", 0):
            self.assertFalse(df.should_fork([], "2026-11-16"))
        with mock.patch.object(df, "FORK_EVERY_DAYS", 7):
            self.assertTrue(df.should_fork([], "2026-11-16"))

    def test_index_links_original_when_there_is_no_fork(self):
        st = self.state(("2026-11-16", None))
        index = df.render_index(st)
        self.assertIn("(https://github.com/o/r0)", index)
        self.assertIn("| no |", index)


class AtAGlanceTests(unittest.TestCase):
    EXTRAS = {
        "excerpt": "A framework for building agents.", "sections": ["Quickstart", "Usage"],
        "install": "pip install acme-agent", "release": "v1.2.3 (2026-11-01)", "age": "20 months ago",
    }

    def repo(self):
        return {**make_repo(), "created_at": "2025-03-01T00:00:00Z", "forks_count": 1234, "open_issues_count": 56}

    def test_section_and_facts_are_rendered(self):
        page = df.render_digest("2026-11-16", "llm", self.repo(), "", self.EXTRAS)
        for expected in (
            "## At a glance", "README excerpt: A framework for building agents.",
            "Install: `pip install acme-agent`", "README sections: Quickstart, Usage",
            "- Created: 2025-03-01 (20 months ago)", "- Forks: 1,234 | Open issues: 56",
            "- Latest release: v1.2.3 (2026-11-01)",
        ):
            self.assertIn(expected, page)

    def test_no_extras_renders_exactly_like_before(self):
        page = df.render_digest("2026-11-16", "llm", make_repo(), "")
        self.assertNotIn("At a glance", page)
        self.assertNotIn("Created:", page)

    def test_glance_comes_before_the_claude_summary(self):
        page = df.render_digest("2026-11-16", "llm", self.repo(), "- a\n- b", self.EXTRAS)
        self.assertLess(page.index("## At a glance"), page.index("## Summary"))

    def test_page_round_trips_through_the_parser(self):
        import digestlib
        info = digestlib.parse_digest(df.render_digest("2026-11-16", "llm", self.repo(), "- a", self.EXTRAS))
        self.assertEqual(info["excerpt"], "A framework for building agents.")
        self.assertEqual(info["install"], "pip install acme-agent")
        self.assertEqual(info["release"], "v1.2.3 (2026-11-01)")
        self.assertEqual(info["language"], "Python")
        self.assertEqual(info["summary"], "- a")

    def test_release_lookup_failure_is_not_fatal(self):
        with mock.patch.object(df, "gh", FakeGitHub([])):
            self.assertIsNone(df.fetch_release(make_repo("a/none")))
        fake = FakeGitHub([], releases={"a/rel": {"tag_name": "v2", "published_at": "2026-01-02T00:00:00Z"}})
        with mock.patch.object(df, "gh", fake):
            self.assertEqual(df.fetch_release(make_repo("a/rel"))["tag_name"], "v2")


class ConfigTests(unittest.TestCase):
    def test_missing_file_uses_defaults_and_file_overrides_keys(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            self.assertEqual(df.load_config(path)["min_stars"], df.DEFAULT_CONFIG["min_stars"])
            path.write_text('{"min_stars": 7}')
            cfg = df.load_config(path)
            self.assertEqual(cfg["min_stars"], 7)
            self.assertEqual(cfg["topics"], df.DEFAULT_CONFIG["topics"])

    def test_invalid_json_exits_with_a_clear_message(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text("{nope")
            with self.assertRaises(SystemExit):
                df.load_config(path)

    def test_shipped_config_is_valid_and_complete(self):
        cfg = df.load_config(Path(__file__).resolve().parent.parent / "config.json")
        self.assertEqual(set(cfg), set(df.DEFAULT_CONFIG))


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
