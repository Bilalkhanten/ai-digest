"""Offline tests for scripts/daily_fork.py. GitHub and Anthropic are never contacted."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import daily_fork as df  # noqa: E402

_REAL_README = df.README_FILE
_GUARD = {}


def setUpModule():
    """Point README_FILE at a throwaway file so no test can modify the real README."""
    _GUARD["tmp"] = tempfile.TemporaryDirectory()
    df.README_FILE = Path(_GUARD["tmp"].name) / "README.md"


def tearDownModule():
    df.README_FILE = _REAL_README
    _GUARD["tmp"].cleanup()


def make_repo(name="acme/agent", stars=500, owner=None, created_at=None, pushed_at="2026-11-16T10:00:00Z"):
    owner = owner or name.split("/")[0]
    repo = {
        "full_name": name,
        "owner": {"login": owner},
        "html_url": f"https://github.com/{name}",
        "description": "An agent framework.",
        "stargazers_count": stars,
        "language": "Python",
        "license": {"spdx_id": "MIT"},
        "pushed_at": pushed_at,
        "topics": ["llm", "agents"],
    }
    if created_at:
        repo["created_at"] = created_at
    return repo


LONG_README = "# Project\n" + "A useful description of the project. " * 30


class FakeGitHub:
    """Routes df.gh() calls to canned responses and records writes."""

    def __init__(self, items, readmes=None, releases=None, readme_errors=None, advisories=None,
                 issues=None, profiles=None):
        self.items = items
        self.issues = issues or {}        # repo -> {label: [issue, ...]} (a string value = API error)
        self.profiles = profiles or {}    # repo -> community profile
        self.advisories = advisories or {}
        self.readmes = readmes or {}
        self.readme_errors = readme_errors or {}
        self.releases = releases or {}
        self.calls = []

    def __call__(self, method, path, data=None, accept=None):
        self.calls.append((method, path))
        if path == "/user":
            return json.dumps({"login": "me", "id": 42})
        if path.startswith("/search/repositories"):
            return json.dumps({"items": self.items})
        if "/issues?" in path:
            name = path.split("/repos/")[1].split("/issues?")[0]
            label = urllib.parse.parse_qs(path.split("?", 1)[1])["labels"][0]
            found = self.issues.get(name, {}).get(label, [])
            if isinstance(found, str):
                raise df.ApiError(found)
            return json.dumps(found)
        if path.endswith("/community/profile"):
            name = path.split("/repos/")[1].rsplit("/community/profile", 1)[0]
            if name not in self.profiles:
                raise df.ApiError("GET profile -> HTTP 404")
            return json.dumps(self.profiles[name])
        if path.endswith("/readme"):
            name = path.split("/repos/")[1].rsplit("/readme", 1)[0]
            if name in self.readme_errors:
                raise df.ApiError(self.readme_errors[name])
            return self.readmes.get(path.split("/repos/")[1].rsplit("/readme", 1)[0], LONG_README)
        if "/security-advisories" in path:
            name = path.split("/repos/")[1].split("/security-advisories")[0]
            if name not in self.advisories:
                raise df.ApiError("GET advisories -> HTTP 404")
            return json.dumps(self.advisories[name])
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
            mock.patch.object(df, "README_FILE", root / "README.md"),
            mock.patch.object(df, "TOKEN", "tok"),
            mock.patch.object(df, "DRY_RUN", False),
            mock.patch.object(df, "ANTHROPIC_KEY", ""),
        ]
        for p in self.patches:
            p.start()
        self.root = root
        (root / "README.md").write_text(f"# T\n\n{df.LATEST_START}\n{df.LATEST_END}\n")
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

    def test_real_run_page_has_whatsnew_and_advisories(self):
        fake = FakeGitHub(
            [make_repo("acme/agent", stars=900)],
            releases={"acme/agent": {"tag_name": "v3", "published_at": "2026-11-10T00:00:00Z",
                                     "body": "## What's Changed\n* Faster startup by @dev in #12\n* Fix crash on exit by @x in #13\n"}},
            advisories={"acme/agent": [{"severity": "critical", "published_at": "2026-09-09T00:00:00Z"}]},
        )
        with mock.patch.object(df, "gh", fake):
            df.main()
        page = next((self.root / "digest").glob("*.md")).read_text()
        self.assertIn("What's new: Faster startup; Fix crash on exit", page)
        self.assertIn("- Security advisories: 1 published (highest: critical, latest 2026-09-09)", page)

    def _issue(self, number, title, days_old=3, **extra):
        stamp = (datetime.now(timezone.utc) - timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {"number": number, "title": title, "state": "open", "updated_at": stamp, "assignees": [], **extra}

    def test_page_lists_contribution_opportunities_and_the_guide(self):
        fake = FakeGitHub(
            [make_repo("acme/agent", stars=900)],
            issues={"acme/agent": {
                "good first issue": [self._issue(7, "Fix typo in [docs]"), self._issue(8, "Assigned", assignees=[{"login": "x"}])],
                "help wanted": [self._issue(9, "Add retry"), self._issue(7, "Fix typo in [docs]")],
            }},
            profiles={"acme/agent": {"files": {"contributing": {
                "html_url": "https://github.com/acme/agent/blob/main/CONTRIBUTING.md"}}}},
        )
        with mock.patch.object(df, "gh", fake):
            df.main()
        page = next((self.root / "digest").glob("*.md")).read_text()
        self.assertIn("## Contribution opportunities", page)
        self.assertIn("- [Fix typo in docs](https://github.com/acme/agent/issues/7) (good first issue, updated 3 days ago)", page)
        self.assertIn("- [Add retry](https://github.com/acme/agent/issues/9) (help wanted, updated 3 days ago)", page)
        self.assertNotIn("issues/8", page)
        self.assertEqual(page.count("issues/7"), 1)
        self.assertIn("Contributing guide: https://github.com/acme/agent/blob/main/CONTRIBUTING.md", page)

    def test_no_issues_means_no_section_and_no_profile_lookup(self):
        fake = FakeGitHub([make_repo("acme/agent")])
        with mock.patch.object(df, "gh", fake):
            df.main()
        page = next((self.root / "digest").glob("*.md")).read_text()
        self.assertNotIn("Contribution opportunities", page)
        self.assertFalse([c for c in fake.calls if "community/profile" in c[1]])

    def test_issue_api_errors_leave_the_section_out_without_failing(self):
        fake = FakeGitHub(
            [make_repo("acme/agent")],
            issues={"acme/agent": {"good first issue": "GET issues -> HTTP 403", "help wanted": "HTTP 500"}},
        )
        with mock.patch.object(df, "gh", fake):
            self.assertEqual(df.main(), 0)
        page = next((self.root / "digest").glob("*.md")).read_text()
        self.assertNotIn("Contribution opportunities", page)

    def test_opportunities_can_be_switched_off(self):
        fake = FakeGitHub([make_repo("acme/agent")],
                          issues={"acme/agent": {"good first issue": [self._issue(1, "Something")]}})
        with mock.patch.object(df, "gh", fake), mock.patch.object(df, "CONFIG", {**df.CONFIG, "max_opportunities": 0}):
            df.main()
        self.assertFalse([c for c in fake.calls if "/issues?" in c[1]])
        self.assertNotIn("Contribution opportunities", next((self.root / "digest").glob("*.md")).read_text())

    def test_missing_advisories_and_releases_just_leave_the_lines_out(self):
        with mock.patch.object(df, "gh", FakeGitHub([make_repo("acme/agent")])):
            df.main()
        page = next((self.root / "digest").glob("*.md")).read_text()
        self.assertNotIn("Security advisories", page)
        self.assertNotIn("What's new", page)

    def test_real_run_refreshes_the_readme_block(self):
        with mock.patch.object(df, "gh", FakeGitHub([make_repo("acme/agent", stars=900)])):
            df.main()
        self.assertIn("[acme/agent](https://github.com/acme/agent) | 900 |", (self.root / "README.md").read_text())

    def test_dry_run_leaves_the_readme_alone(self):
        before = (self.root / "README.md").read_text()
        with mock.patch.object(df, "gh", FakeGitHub([make_repo("acme/agent")])), mock.patch.object(df, "DRY_RUN", True):
            df.main()
        self.assertEqual((self.root / "README.md").read_text(), before)

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
        self.assertIn("- Why picked: 900 stars", page)

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

    def test_language_allow_and_block_lists(self):
        py, go, none = make_repo("a/py"), {**make_repo("a/go"), "language": "Go"}, {**make_repo("a/n"), "language": None}
        with self.cfg(include_languages=["python"]):          # case-insensitive allowlist
            self.assertFalse(df.is_excluded(py))
            self.assertTrue(df.is_excluded(go))
            self.assertTrue(df.is_excluded(none))              # unknown language can't match an allowlist
        with self.cfg(exclude_languages=["GO"]):
            self.assertTrue(df.is_excluded(go))
            self.assertFalse(df.is_excluded(py))
            self.assertFalse(df.is_excluded(none))
        with self.cfg():                                       # defaults: anything goes
            self.assertFalse(df.is_excluded(go))

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

    def test_missing_readme_404_is_skipped(self):
        pool = [make_repo("a/none"), make_repo("b/good")]
        fake = FakeGitHub([], readme_errors={"a/none": "GET /repos/a/none/readme -> HTTP 404: Not Found"})
        with mock.patch.object(df, "gh", fake):
            repo, _ = df.choose_repo(pool)
        self.assertEqual(repo["full_name"], "b/good")

    def test_unverifiable_readme_is_accepted_not_penalised(self):
        for message in ("GET x -> HTTP 403: rate limit", "GET x -> HTTP 502: bad gateway", "GET x -> network error: down"):
            pool = [make_repo("a/flaky"), make_repo("b/other")]
            with mock.patch.object(df, "gh", FakeGitHub([], readme_errors={"a/flaky": message})):
                repo, readme = df.choose_repo(pool)
            self.assertEqual((repo["full_name"], readme), ("a/flaky", ""))

    def test_a_day_is_not_lost_when_every_readme_lookup_fails(self):
        pool = [make_repo(f"o/r{i}") for i in range(3)]
        errors = {f"o/r{i}": "HTTP 500" for i in range(3)}
        with mock.patch.object(df, "gh", FakeGitHub([], readme_errors=errors)):
            repo, _ = df.choose_repo(pool)
        self.assertIsNotNone(repo)

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


class ReadmeBlockTests(unittest.TestCase):
    STATE = [{"date": f"2026-11-{d:02d}", "repo": f"o/r{d}", "stars": d * 1000, "topic": "llm"} for d in range(1, 10)]

    def test_block_lists_the_newest_seven_first(self):
        block = df.render_latest_block(self.STATE)
        rows = [ln for ln in block.splitlines() if ln.startswith("| 2026")]
        self.assertEqual(len(rows), 7)
        self.assertTrue(rows[0].startswith("| 2026-11-09"))
        self.assertIn("[o/r9](https://github.com/o/r9) | 9,000 |", rows[0])

    def test_replace_block_keeps_surrounding_text(self):
        text = f"before\n{df.LATEST_START}\nold\n{df.LATEST_END}\nafter\n"
        got = df.replace_block(text, "NEW")
        self.assertEqual(got, f"before\n{df.LATEST_START}\nNEW\n{df.LATEST_END}\nafter\n")

    def test_missing_or_reversed_markers_change_nothing(self):
        self.assertEqual(df.replace_block("no markers", "NEW"), "no markers")
        reversed_ = f"{df.LATEST_END}\n{df.LATEST_START}\n"
        self.assertEqual(df.replace_block(reversed_, "NEW"), reversed_)

    def test_update_readme_is_idempotent_and_reports_changes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "README.md"
            path.write_text(f"{df.LATEST_START}\n{df.LATEST_END}\n")
            with mock.patch.object(df, "README_FILE", path):
                self.assertTrue(df.update_readme(self.STATE))
                self.assertFalse(df.update_readme(self.STATE))
                self.assertIn("o/r9", path.read_text())
            with mock.patch.object(df, "README_FILE", Path(d) / "missing.md"):
                self.assertFalse(df.update_readme(self.STATE))


class TopicSearchResilienceTests(unittest.TestCase):
    class Flaky(FakeGitHub):
        def __init__(self, items, fail_first):
            super().__init__(items)
            self.fail_first, self.searches = fail_first, 0

        def __call__(self, method, path, data=None, accept=None):
            if path.startswith("/search/repositories"):
                self.searches += 1
                if self.searches <= self.fail_first:
                    raise df.ApiError("GET /search -> HTTP 403: rate limited")
            return super().__call__(method, path, data, accept)

    def test_a_failing_topic_falls_through_to_the_next(self):
        fake = self.Flaky([make_repo("a/ok")], fail_first=2)
        with mock.patch.object(df, "gh", fake):
            topic, pool = df.find_candidates(set(), "me")
        self.assertEqual([r["full_name"] for r in pool], ["a/ok"])
        self.assertEqual(fake.searches, 3)

    def test_every_search_failing_raises_so_the_alert_fires(self):
        fake = self.Flaky([make_repo("a/ok")], fail_first=10_000)
        with mock.patch.object(df, "gh", fake), self.assertRaises(df.ApiError):
            df.find_candidates(set(), "me")

    def test_all_topics_empty_is_not_an_error(self):
        with mock.patch.object(df, "gh", FakeGitHub([])):
            self.assertEqual(df.find_candidates(set(), "me"), (None, []))


class TopicListTests(unittest.TestCase):
    CFG = df.load_config(Path(__file__).resolve().parent.parent / "config.json")
    AI = {"llm", "ai-agents", "rag", "mcp"}
    PLATFORM = {"kubernetes", "devops", "docker", "sre", "monitoring", "observability", "terraform"}

    def test_topics_are_unique_and_cover_ai_and_platform_areas(self):
        topics = self.CFG["topics"]
        self.assertEqual(len(topics), len(set(topics)))
        self.assertTrue(self.AI <= set(topics))
        self.assertTrue(self.PLATFORM <= set(topics))

    def test_shipped_config_and_built_in_defaults_agree(self):
        self.assertEqual(self.CFG["topics"], df.DEFAULT_CONFIG["topics"])

    def test_areas_alternate_instead_of_running_in_long_blocks(self):
        flags = [t in self.AI or t in {"machine-learning", "generative-ai", "deep-learning", "nlp",
                                       "computer-vision", "langchain", "robotics", "data-science", "diffusion"}
                 for t in self.CFG["topics"]]
        longest = run = 1
        for prev, cur in zip(flags, flags[1:], strict=False):
            run = run + 1 if cur == prev else 1
            longest = max(longest, run)
        self.assertLessEqual(longest, 4)


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


TODAY = date(2026, 11, 16)


class MomentumTests(unittest.TestCase):
    def test_signals(self):
        repo = make_repo(stars=3000, created_at="2026-08-18T00:00:00Z", pushed_at="2026-11-13T00:00:00Z")
        m = df.momentum(repo, TODAY)
        self.assertEqual((m["stars"], m["pushed_days"]), (3000, 3))
        self.assertAlmostEqual(m["velocity"], 3000 / 90, places=1)

    def test_young_repos_use_a_30_day_floor_and_missing_dates_are_safe(self):
        self.assertAlmostEqual(df.momentum(make_repo(stars=300, created_at="2026-11-15T00:00:00Z"), TODAY)["velocity"], 10.0)
        bare = {"stargazers_count": 10}
        m = df.momentum(bare, TODAY)
        self.assertEqual((m["velocity"], m["pushed_days"]), (0.0, None))

    def test_growing_and_fresh_beats_stale_at_equal_stars(self):
        hot = make_repo(stars=1000, created_at="2026-09-16T00:00:00Z", pushed_at="2026-11-16T00:00:00Z")
        cold = make_repo(stars=1000, created_at="2019-01-01T00:00:00Z", pushed_at="2026-10-20T00:00:00Z")
        self.assertGreater(df.base_score(hot, TODAY), df.base_score(cold, TODAY))

    def test_more_stars_score_higher(self):
        a, b = make_repo(stars=200), make_repo(stars=20000)
        self.assertGreater(df.base_score(b, TODAY), df.base_score(a, TODAY))


class OwnerCooldownTests(unittest.TestCase):
    STATE = [{"date": "2026-11-10", "repo": "Acme/old"}, {"date": "2026-09-01", "repo": "Longago/x"}]

    def test_recent_owners_respects_the_window_and_case(self):
        self.assertEqual(df.recent_owners(self.STATE, TODAY, 21), {"acme"})
        self.assertEqual(df.recent_owners(self.STATE, TODAY, 90), {"acme", "longago"})

    def test_cooldown_owner_is_skipped_when_alternatives_exist(self):
        items = [make_repo("acme/one", stars=9000), make_repo("other/two", stars=200)]
        with mock.patch.object(df, "gh", FakeGitHub(items)):
            _, pool = df.find_candidates(set(), "me", {"acme"})
        self.assertEqual([r["full_name"] for r in pool], ["other/two"])

    def test_cooldown_is_ignored_when_it_would_leave_nothing(self):
        with mock.patch.object(df, "gh", FakeGitHub([make_repo("acme/one")])):
            _, pool = df.find_candidates(set(), "me", {"acme"})
        self.assertEqual([r["full_name"] for r in pool], ["acme/one"])


class ReleasePreferenceTests(unittest.TestCase):
    def setUp(self):
        df._RELEASES.clear()

    def test_recent_release_moves_up_and_order_inside_groups_is_kept(self):
        pool = [make_repo(f"o/r{i}") for i in range(4)]
        releases = {
            "o/r2": {"tag_name": "v1", "published_at": "2026-11-10T00:00:00Z"},   # 6 days: recent
            "o/r3": {"tag_name": "v0", "published_at": "2025-01-01T00:00:00Z"},   # old
        }
        with mock.patch.object(df, "gh", FakeGitHub([], releases=releases)):
            ordered = df.prefer_recent_release(pool, TODAY)
        self.assertEqual([r["full_name"] for r in ordered], ["o/r2", "o/r0", "o/r1", "o/r3"])

    def test_only_the_top_n_are_checked(self):
        pool = [make_repo(f"o/r{i}") for i in range(10)]
        fake = FakeGitHub([])
        with mock.patch.object(df, "gh", fake), mock.patch.dict(df.CONFIG, {"release_check_top": 3}):
            ordered = df.prefer_recent_release(pool, TODAY)
        self.assertEqual(len([c for c in fake.calls if "releases" in c[1]]), 3)
        self.assertEqual(len(ordered), 10)

    def test_release_is_looked_up_once_per_repo(self):
        fake = FakeGitHub([], releases={"o/a": {"tag_name": "v1", "published_at": "2026-11-15T00:00:00Z"}})
        with mock.patch.object(df, "gh", fake):
            df.release_for(make_repo("o/a"))
            df.release_for(make_repo("o/a"))
        self.assertEqual(len(fake.calls), 1)


class ReasonTests(unittest.TestCase):
    def test_full_reason(self):
        repo = make_repo(stars=1772, created_at="2026-08-18T00:00:00Z", pushed_at="2026-11-16T05:00:00Z")
        rel = {"tag_name": "v1", "published_at": "2026-11-12T00:00:00Z"}
        self.assertEqual(
            df.reason_text(repo, TODAY, rel),
            "1,772 stars, ~19.7 stars/day since creation, pushed today, release 4 days ago",
        )

    def test_minimal_reason_and_singular_day(self):
        bare = {"stargazers_count": 500}
        self.assertEqual(df.reason_text(bare, TODAY, None), "500 stars")
        repo = make_repo(stars=500, pushed_at="2026-11-15T00:00:00Z")
        self.assertEqual(df.reason_text(repo, TODAY, None), "500 stars, pushed 1 day ago")

    def test_reason_appears_on_the_page_and_parses_back(self):
        import digestlib
        page = df.render_digest("2026-11-16", "llm", make_repo(), "", {"reason": "500 stars, pushed today"})
        self.assertIn("- Why picked: 500 stars, pushed today", page)
        self.assertEqual(digestlib.parse_digest(page)["reason"], "500 stars, pushed today")


class WhatsNewAndAdvisoryTests(unittest.TestCase):
    ADVISORIES = [
        {"ghsa_id": "GHSA-1", "severity": "high", "published_at": "2026-10-02T00:00:00Z"},
        {"ghsa_id": "GHSA-2", "severity": "low", "published_at": "2026-01-05T00:00:00Z"},
    ]

    def test_lines_are_rendered_and_parse_back(self):
        import digestlib
        extras = {"whatsnew": "Faster startup; fixes a crash", "advisories": "2 published (highest: high, latest 2026-10-02)"}
        page = df.render_digest("2026-11-16", "llm", make_repo(), "", extras)
        self.assertIn("What's new: Faster startup; fixes a crash", page)
        self.assertIn("- Security advisories: 2 published (highest: high, latest 2026-10-02)", page)
        info = digestlib.parse_digest(page)
        self.assertEqual(info["whatsnew"], "Faster startup; fixes a crash")
        self.assertTrue(info["advisories"].startswith("2 published"))

    def test_fetch_advisories_returns_a_list_or_none(self):
        fake = FakeGitHub([], advisories={"o/a": self.ADVISORIES})
        with mock.patch.object(df, "gh", fake):
            self.assertEqual(len(df.fetch_advisories(make_repo("o/a"))), 2)
            self.assertIsNone(df.fetch_advisories(make_repo("o/none")))

    def test_non_list_json_is_ignored(self):
        with mock.patch.object(df, "gh", lambda *a, **k: json.dumps({"message": "Not Found"})):
            self.assertIsNone(df.fetch_advisories(make_repo("o/x")))


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
