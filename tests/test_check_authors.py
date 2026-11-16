"""Tests for scripts/check_authors.py, run against real throwaway git repositories."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_authors as ca  # noqa: E402

ME = "24990758+Bilalkhanten@users.noreply.github.com"
ALLOWED = {ME.lower()}   # the real loader lowercases, like the commit emails


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.git("init", "-q", "-b", "main")
        self.n = 0

    def git(self, *args, env=None):
        full_env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, **(env or {})}
        return subprocess.run(["git", *args], cwd=self.dir, env=full_env, capture_output=True, text=True, check=True)

    def commit(self, message="work", author=ME, committer=None, author_name="Bilalkhanten"):
        self.n += 1
        (self.dir / f"f{self.n}.txt").write_text(str(self.n))
        self.git("add", "-A")
        committer = committer or author
        env = {"GIT_AUTHOR_NAME": author_name, "GIT_AUTHOR_EMAIL": author,
               "GIT_COMMITTER_NAME": "C", "GIT_COMMITTER_EMAIL": committer}
        self.git("commit", "-q", "-m", message, env=env)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def bad(self, *revs):
        return ca.check(list(revs) or ["HEAD"], ALLOWED, self.dir)


class RuleTests(RepoCase):
    def test_clean_history_passes(self):
        self.commit()
        self.commit("second")
        self.assertEqual(self.bad(), {})

    def test_other_author_is_flagged(self):
        self.commit()
        sha = self.commit(author="someone@example.com", committer=ME)
        found = self.bad()
        self.assertEqual(list(found), [sha])
        self.assertIn("author", found[sha][0])

    def test_bot_author_is_flagged(self):
        sha = self.commit(author="49699333+dependabot[bot]@users.noreply.github.com", author_name="dependabot[bot]")
        self.assertIn(sha, self.bad())

    def test_other_committer_is_flagged_but_github_web_ui_committer_is_fine(self):
        sha = self.commit(author=ME, committer="intruder@example.com")
        self.assertIn("committer", self.bad()[sha][0])
        self.assertEqual(self.bad("HEAD", "--not", sha), {})          # nothing newer than that commit
        ok = self.commit(author=ME, committer="noreply@github.com")
        self.assertNotIn(ok, self.bad())

    def test_coauthor_trailer_for_someone_else_is_flagged(self):
        sha = self.commit("feat\n\nCo-Authored-By: Some Bot <noreply@example.com>")
        self.assertIn("Co-authored-by", self.bad()[sha][0])

    def test_trailer_check_is_case_insensitive_and_catches_bare_names(self):
        a = self.commit("x\n\nco-authored-by: Someone <a@b.c>")
        b = self.commit("y\n\nCO-AUTHORED-BY: Just A Name")
        found = self.bad()
        self.assertIn(a, found)
        self.assertIn(b, found)

    def test_coauthor_that_is_you_is_allowed(self):
        self.commit(f"ok\n\nCo-authored-by: Bilal <{ME}>")
        self.assertEqual(self.bad(), {})

    def test_email_comparison_ignores_case(self):
        self.commit(author=ME.upper())
        self.assertEqual(self.bad(), {})

    def test_every_problem_in_one_commit_is_reported(self):
        sha = self.commit("z\n\nCo-authored-by: X <x@y.z>", author="a@b.c", committer="d@e.f")
        self.assertEqual(len(self.bad()[sha]), 3)


class RangeTests(RepoCase):
    def test_only_the_range_is_checked(self):
        self.commit(author="old@example.com", committer=ME)                # offending, but older
        base = self.commit()
        new = self.commit("new")
        self.assertEqual(ca.check(ca.rev_args(base, new, self.dir), ALLOWED, self.dir), {})
        everything = ca.check(ca.rev_args("", new, self.dir), ALLOWED, self.dir)
        self.assertEqual(len(everything), 1)

    def test_range_catches_a_new_offender(self):
        base = self.commit()
        bad = self.commit(author="x@y.z", committer=ME)
        self.assertEqual(list(ca.check(ca.rev_args(base, bad, self.dir), ALLOWED, self.dir)), [bad])

    def test_missing_or_zero_base_falls_back_safely(self):
        head = self.commit()
        self.assertEqual(ca.rev_args(ca.ZERO_SHA, head, self.dir), [head])
        self.assertEqual(ca.rev_args("f" * 40, head, self.dir), [head])

    def test_new_branch_is_compared_with_origin_main_when_it_exists(self):
        self.commit()
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        revs = ca.rev_args("", "HEAD", self.dir)
        self.assertEqual(revs, ["HEAD", "--not", "origin/main"])
        self.commit(author="x@y.z", committer=ME)
        self.assertEqual(len(ca.check(revs, ALLOWED, self.dir)), 1)


class AllowedFileTests(unittest.TestCase):
    def test_comments_blanks_and_case_are_handled(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "allowed.txt"
            p.write_text("# comment\n\nA@B.C   # trailing\n  d@e.f \n")
            self.assertEqual(ca.load_allowed(p), {"a@b.c", "d@e.f"})

    def test_shipped_file_contains_exactly_the_owner_identity(self):
        self.assertEqual(ca.load_allowed(), {ME.lower()})


if __name__ == "__main__":
    unittest.main()
