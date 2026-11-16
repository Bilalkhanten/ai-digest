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
