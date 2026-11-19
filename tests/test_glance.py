"""Offline tests for scripts/glance.py (the free, rule-based "At a glance" facts)."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import glance as gl  # noqa: E402

README = """<p align="center"><img src="logo.png"></p>

# Acme Agent

[![CI](https://x/badge.svg)](https://x) [![PyPI](https://y/b.svg)](https://y)

Acme Agent is a **framework** for building reliable, tool-using agents with typed plans, retries and
[great tracing](https://example.com/docs). Contact @someone for help.

## Table of Contents

- [Install](#install)

## Quickstart

```bash
$ pip install acme-agent
```

## Usage <a name="usage"></a>

### Configuration

```python
## not a heading
import acme
```

## Usage

## License
MIT
"""


class ExcerptTests(unittest.TestCase):
    def test_skips_badges_html_and_headings_and_cleans_links(self):
        ex = gl.readme_excerpt(README)
        self.assertTrue(ex.startswith("Acme Agent is a framework for building reliable"))
        self.assertIn("great tracing", ex)
        for bad in ("http", "<", "**", "@", "[", "badge"):
            self.assertNotIn(bad, ex)

    def test_truncates_on_a_word_boundary(self):
        long = "word " * 200
        ex = gl.readme_excerpt(long, limit=100)
        self.assertTrue(ex.endswith("..."))
        self.assertLessEqual(len(ex), 104)

    def test_returns_empty_when_there_is_no_real_prose(self):
        self.assertEqual(gl.readme_excerpt("# T\n\n![x](y.png)\n\n- a\n- b\n"), "")
        self.assertEqual(gl.readme_excerpt(""), "")

    def test_code_blocks_are_never_used_as_the_excerpt(self):
        text = "# T\n\n```\nthis is a long line of code like text that has many many words in it okay\n```\n"
        self.assertEqual(gl.readme_excerpt(text), "")


class SectionsTests(unittest.TestCase):
    def test_lists_h2_h3_dedupes_skips_noise_and_ignores_code(self):
        self.assertEqual(gl.readme_sections(README), ["Quickstart", "Usage", "Configuration"])

    def test_keeps_apostrophes(self):
        self.assertEqual(gl.readme_sections("## What's New\n"), ["What's New"])

    def test_limit(self):
        text = "\n".join(f"## Section {i}" for i in range(20))
        self.assertEqual(len(gl.readme_sections(text)), gl.MAX_SECTIONS)


class InstallTests(unittest.TestCase):
    def test_finds_first_command_in_a_code_block_and_strips_prompt(self):
        self.assertEqual(gl.install_hint(README), "pip install acme-agent")

    def test_ignores_commands_outside_code_blocks_and_unsafe_ones(self):
        self.assertEqual(gl.install_hint("pip install outside-a-block\n"), "")
        self.assertEqual(gl.install_hint("```\nnpm install `evil`\n```\n"), "")
        self.assertEqual(gl.install_hint("```\ndocker run <image>\n```\n"), "")

    def test_other_tools(self):
        self.assertEqual(gl.install_hint("```sh\nnpm install foo\n```"), "npm install foo")
        self.assertEqual(gl.install_hint("```\ncargo install bar\n```"), "cargo install bar")
        self.assertEqual(gl.install_hint("```\ndocker run -p 80:80 img\n```"), "docker run -p 80:80 img")


class CleanupRegressionTests(unittest.TestCase):
    """Bugs seen on the first real digest page."""

    def test_underscores_in_identifiers_survive_but_emphasis_underscores_go(self):
        self.assertEqual(gl._strip_inline("set SMOLVM_MOUNT_DAX and my_var_name"), "set SMOLVM_MOUNT_DAX and my_var_name")
        self.assertEqual(gl._strip_inline("this is _emphasised_ and __bold__ text"), "this is emphasised and bold text")
        self.assertEqual(gl._strip_inline("_leading and trailing_"), "leading and trailing")

    def test_release_notes_keep_env_var_names(self):
        notes = gl.release_notes({"body": "* docs: SMOLVM_MOUNT_DAX does nothing on arm64"})
        self.assertEqual(notes, "docs: SMOLVM_MOUNT_DAX does nothing on arm64")

    def test_install_hint_drops_trailing_comments_and_extra_spaces(self):
        block = "```\nbrew install smol-machines/tap/smolvm                  # macOS (Homebrew)\n```"
        self.assertEqual(gl.install_hint(block), "brew install smol-machines/tap/smolvm")
        self.assertEqual(gl.install_hint("```\npip   install   foo\n```"), "pip install foo")

    def test_hash_inside_a_command_argument_is_kept(self):
        self.assertEqual(gl.install_hint("```\ngo install example.com/x@v1#frag\n```"), "go install example.com/x@v1#frag")


class AgeAndReleaseTests(unittest.TestCase):
    TODAY = date(2026, 11, 16)

    def test_age_text(self):
        self.assertEqual(gl.age_text("2026-11-10T00:00:00Z", self.TODAY), "6 days ago")
        self.assertEqual(gl.age_text("2025-03-01T00:00:00Z", self.TODAY), "20 months ago")
        self.assertEqual(gl.age_text("2022-11-16T00:00:00Z", self.TODAY), "4.0 years ago")

    def test_age_text_bad_input(self):
        self.assertEqual(gl.age_text(None, self.TODAY), "")
        self.assertEqual(gl.age_text("garbage", self.TODAY), "")
        self.assertEqual(gl.age_text("2030-01-01T00:00:00Z", self.TODAY), "")

    def test_release_text(self):
        self.assertEqual(gl.release_text({"tag_name": "v1.2.3", "published_at": "2026-11-01T10:00:00Z"}), "v1.2.3 (2026-11-01)")
        self.assertEqual(gl.release_text({"tag_name": "v9"}), "v9")
        self.assertEqual(gl.release_text(None), "")
        self.assertEqual(gl.release_text({"tag_name": ""}), "")

    def test_release_tag_is_sanitised(self):
        self.assertEqual(gl.release_text({"tag_name": "v1 <script>"}), "v1script")


class ReleaseNotesTests(unittest.TestCase):
    def test_takes_the_first_meaningful_lines_and_drops_authors_and_noise(self):
        body = ("## What's Changed\n* Faster startup by @alice in https://github.com/o/r/pull/1\n"
                "* Fix a crash on exit in #2\n- Add `--json` output flag\n* fourth item is ignored\n\n"
                "## New Contributors\n* @bob made their first contribution\n**Full Changelog**: https://x\n")
        text = gl.release_notes({"body": body})
        self.assertEqual(text, "Faster startup; Fix a crash on exit; Add --json output flag")
        for bad in ("@", "http", "#2", "Full Changelog"):
            self.assertNotIn(bad, text)

    def test_empty_missing_and_code_only_bodies(self):
        self.assertEqual(gl.release_notes(None), "")
        self.assertEqual(gl.release_notes({"body": None}), "")
        self.assertEqual(gl.release_notes({"body": "```\nthis is code and is ignored entirely\n```"}), "")

    def test_long_notes_are_truncated(self):
        text = gl.release_notes({"body": "* " + "word " * 100}, limit=50)
        self.assertTrue(text.endswith("..."))
        self.assertLessEqual(len(text), 54)

    def test_html_is_stripped(self):
        self.assertEqual(gl.release_notes({"body": "* <img src=x onerror=alert(1)> Better caching layer"}), "Better caching layer")


class AdvisoryTextTests(unittest.TestCase):
    def test_summary_with_highest_severity_and_latest_date(self):
        adv = [{"severity": "medium", "published_at": "2026-03-01T00:00:00Z"},
               {"severity": "critical", "published_at": "2026-08-09T00:00:00Z"},
               {"severity": "low", "published_at": "2025-12-31T00:00:00Z"}]
        self.assertEqual(gl.advisory_text(adv), "3 published (highest: critical, latest 2026-08-09)")

    def test_empty_none_and_malformed_input(self):
        self.assertEqual(gl.advisory_text([]), "")
        self.assertEqual(gl.advisory_text(None), "")
        self.assertEqual(gl.advisory_text({"message": "x"}), "")
        self.assertEqual(gl.advisory_text([{}]), "1 published")
        self.assertEqual(gl.advisory_text(["junk"]), "1 published")


class BuildExtrasTests(unittest.TestCase):
    def test_collects_everything(self):
        extras = gl.build_extras({"created_at": "2025-03-01T00:00:00Z"}, README, date(2026, 11, 16),
                                 {"tag_name": "v1", "published_at": "2026-11-01T00:00:00Z"})
        self.assertEqual(extras["install"], "pip install acme-agent")
        self.assertEqual(extras["release"], "v1 (2026-11-01)")
        self.assertEqual(extras["age"], "20 months ago")
        self.assertIn("Quickstart", extras["sections"])
        self.assertTrue(extras["excerpt"])
        self.assertEqual(extras["whatsnew"], "")
        self.assertEqual(extras["advisories"], "")


if __name__ == "__main__":
    unittest.main()


class OpportunityTests(unittest.TestCase):
    TODAY = date(2026, 11, 19)

    def issue(self, number, title="Fix it", updated="2026-11-10T00:00:00Z", **extra):
        return {"number": number, "title": title, "state": "open", "updated_at": updated, "assignees": [], **extra}

    def pick(self, groups, **kw):
        return gl.pick_opportunities(groups, "a/b", self.TODAY, **kw)

    def test_builds_links_from_numbers_and_orders_by_label_then_recency(self):
        got = self.pick([("good first issue", [self.issue(2), self.issue(1)]), ("help wanted", [self.issue(3)])])
        self.assertEqual([o["url"] for o in got], [f"https://github.com/a/b/issues/{n}" for n in (2, 1, 3)])
        self.assertEqual(got[0]["label"], "good first issue")
        self.assertEqual(got[0]["updated"], "9 days ago")

    def test_drops_prs_locked_assigned_stale_and_duplicates(self):
        groups = [("x", [
            self.issue(1, pull_request={"url": "u"}), self.issue(2, locked=True),
            self.issue(3, assignees=[{"login": "z"}]), self.issue(4, assignee={"login": "z"}),
            self.issue(5, updated="2025-01-01T00:00:00Z"), self.issue(6, state="closed"),
            self.issue(7), self.issue(7),
        ])]
        self.assertEqual([o["url"][-1] for o in self.pick(groups)], ["7"])

    def test_respects_the_maximum_and_survives_junk(self):
        groups = [("x", [self.issue(n) for n in range(1, 9)] + [None, "str", {"number": "9"}, {"number": True}])]
        self.assertEqual(len(self.pick(groups, maximum=3)), 3)
        self.assertEqual(self.pick([("x", None), ("y", "boom"), ("z", [{}])]), [])
        self.assertEqual(self.pick([("x", [self.issue(1, updated="nonsense")])]), [])

    def test_titles_are_untrusted_and_made_safe(self):
        got = self.pick([("x", [self.issue(1, title="Hi @bob [click](http://evil) <b>bold</b> | `code`")])])
        title = got[0]["title"]
        for bad in ("@", "[", "]", "(", ")", "<", ">", "|", "http"):
            self.assertNotIn(bad, title)
        self.assertEqual(self.pick([("x", [self.issue(1, title="   ")])]), [])
        self.assertLessEqual(len(gl.clean_title("word " * 100)), 93)

    def test_contributing_url_accepts_only_the_repos_own_github_links(self):
        ok = {"files": {"contributing": {"html_url": "https://github.com/a/b/blob/main/CONTRIBUTING.md"}}}
        self.assertEqual(gl.contributing_url(ok, "a/b"), "https://github.com/a/b/blob/main/CONTRIBUTING.md")
        for bad in (None, {}, {"files": None}, {"files": {"contributing": None}},
                    {"files": {"contributing": {"html_url": "https://evil.example/a/b/x"}}},
                    {"files": {"contributing": {"html_url": "https://github.com/other/repo/x"}}},
                    {"files": {"contributing": {"html_url": "javascript:alert(1)"}}}):
            self.assertEqual(gl.contributing_url(bad, "a/b"), "")
