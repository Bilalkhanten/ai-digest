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


class ParseDigestTests(unittest.TestCase):
    def test_extracts_fields_and_summary(self):
        info = dl.parse_digest(PAGE)
        self.assertEqual(info["description"], "An agent framework.")
        self.assertEqual(info["language"], "Python")
        self.assertEqual(info["license"], "MIT")
        self.assertIn("- Does a thing", info["summary"])

    def test_page_without_summary_or_fields_uses_defaults(self):
        info = dl.parse_digest("")
        self.assertEqual((info["language"], info["summary"]), ("n/a", ""))


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
