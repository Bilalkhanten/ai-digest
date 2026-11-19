"""Offline tests for scripts/digestlib.py."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import digestlib as dl  # noqa: E402

PAGE = """# acme/agent

> An agent framework.

- Date picked: 2026-11-16 (topic: `llm`)
- Link: https://github.com/acme/agent
- Stars: 1,234
- Language: Python
- License: MIT

## Summary

- Does a thing
- For people
- Notable
"""


OPPORTUNITIES = '## Contribution opportunities\n\n- [Fix typo](https://github.com/acme/agent/issues/7) (good first issue, updated 3 days ago)\n- [Add retry](https://github.com/acme/agent/issues/9) (help wanted, updated 2 months ago)\n\nContributing guide: https://github.com/acme/agent/blob/main/CONTRIBUTING.md\n\n'


class ParseDigestTests(unittest.TestCase):
    def test_extracts_fields_and_summary(self):
        info = dl.parse_digest(PAGE)
        self.assertEqual(info["description"], "An agent framework.")
        self.assertEqual(info["language"], "Python")
        self.assertEqual(info["license"], "MIT")
        self.assertIn("- Does a thing", info["summary"])

    def test_contribution_opportunities_are_parsed_and_stay_out_of_the_summary(self):
        page = PAGE.replace("## Summary", OPPORTUNITIES + "## Summary")
        info = dl.parse_digest(page)
        self.assertEqual(
            info["opportunities"][0],
            {"title": "Fix typo", "url": "https://github.com/acme/agent/issues/7",
             "label": "good first issue", "updated": "3 days ago"},
        )
        self.assertEqual([o["label"] for o in info["opportunities"]], ["good first issue", "help wanted"])
        self.assertEqual(info["contributing"], "https://github.com/acme/agent/blob/main/CONTRIBUTING.md")
        self.assertNotIn("issues/7", info["summary"])

    def test_opportunity_lines_with_non_github_links_are_ignored(self):
        info = dl.parse_digest("- [x](https://evil.example/a) (help wanted, updated 1 day ago)\n"
                               "Contributing guide: https://evil.example/c\n")
        self.assertEqual((info["opportunities"], info["contributing"]), ([], ""))

    def test_page_without_summary_or_fields_uses_defaults(self):
        info = dl.parse_digest("")
        self.assertEqual((info["language"], info["summary"]), ("n/a", ""))
        self.assertEqual((info["opportunities"], info["contributing"]), ([], ""))


class EntryLinkTests(unittest.TestCase):
    def test_prefers_fork_then_original(self):
        self.assertEqual(dl.entry_link({"repo": "a/b", "fork_url": "F"}), "F")
        self.assertEqual(dl.entry_link({"repo": "a/b", "fork_url": None}), "https://github.com/a/b")
        self.assertEqual(dl.entry_link({"repo": "a/b"}), "https://github.com/a/b")


class AreaTests(unittest.TestCase):
    CFG = Path(__file__).resolve().parent.parent / "config.json"

    def test_built_in_defaults_match_the_shipped_config(self):
        import json
        self.assertEqual(dl.DEFAULT_AREAS, json.loads(self.CFG.read_text())["areas"])

    def test_every_rotation_topic_has_exactly_one_area(self):
        import json
        cfg = json.loads(self.CFG.read_text())
        listed = [t for topics in cfg["areas"].values() for t in topics]
        self.assertEqual(sorted(listed), sorted(cfg["topics"]))
        self.assertEqual(len(listed), len(set(listed)))

    def test_area_for_and_slug(self):
        areas = dl.DEFAULT_AREAS
        self.assertEqual(dl.area_for("llm", areas), "AI")
        self.assertEqual(dl.area_for("kubernetes", areas), "Platform")
        self.assertEqual(dl.area_for("something-new", areas), "Other")
        self.assertEqual(dl.area_slug("Platform"), "platform")
        self.assertEqual(dl.area_slug("Cloud & Infra!"), "cloud-infra")
        self.assertEqual(dl.area_slug("!!!"), "other")

    def test_load_areas_falls_back_when_missing_or_invalid(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(dl.load_areas(Path(d) / "nope.json"), dl.DEFAULT_AREAS)
            bad = Path(d) / "bad.json"
            bad.write_text("{not json")
            self.assertEqual(dl.load_areas(bad), dl.DEFAULT_AREAS)
            custom = Path(d) / "c.json"
            custom.write_text('{"areas": {"X": ["a"]}}')
            self.assertEqual(dl.load_areas(custom), {"X": ["a"]})


class AskClaudeTests(unittest.TestCase):
    def test_no_key_means_no_network_call(self):
        with mock.patch.object(dl.urllib.request, "urlopen") as op:
            self.assertEqual(dl.ask_claude("hi", "", "m"), "")
        op.assert_not_called()

    def test_failures_return_empty_string_instead_of_raising(self):
        with mock.patch.object(dl.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertEqual(dl.ask_claude("hi", "key", "m"), "")


if __name__ == "__main__":
    unittest.main()
