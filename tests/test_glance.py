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
