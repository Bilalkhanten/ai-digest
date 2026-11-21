"""Cheap checks on the documentation. The diagrams are rendered by GitHub, not here."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = ("flowchart", "graph", "sequenceDiagram", "stateDiagram", "classDiagram")


def mermaid_blocks(path):
    return re.findall(r"```mermaid\n(.*?)```", path.read_text(), re.S)


class MermaidTests(unittest.TestCase):
    FILES = [ROOT / "docs" / "ARCHITECTURE.md"]

    def test_each_file_has_at_least_one_diagram(self):
        for f in self.FILES:
            self.assertTrue(mermaid_blocks(f), f"{f.name} has no mermaid block")

    def test_diagrams_start_with_a_known_type_and_have_balanced_brackets(self):
        for f in self.FILES:
            for block in mermaid_blocks(f):
                self.assertTrue(block.lstrip().startswith(DIAGRAMS), f"{f.name}: unknown diagram type")
                for open_, close in ("[]", "()", "{}"):
                    self.assertEqual(block.count(open_), block.count(close), f"{f.name}: unbalanced {open_}{close}")
                self.assertEqual(block.count('"') % 2, 0, f"{f.name}: odd number of quotes")

    def test_subgraphs_are_closed(self):
        for f in self.FILES:
            for block in mermaid_blocks(f):
                self.assertEqual(len(re.findall(r"^\s*subgraph\b", block, re.M)),
                                 len(re.findall(r"^\s*end\s*$", block, re.M)))

    def test_every_workflow_file_is_documented(self):
        text = (ROOT / "docs" / "ARCHITECTURE.md").read_text().lower()
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            name = {"ci": "ci", "daily-fork": "daily repo fork", "weekly-rollup": "weekly roll-up",
                    "watchdog": "watchdog", "data-check": "data check", "token-health": "token health", "fork-inventory": "fork inventory", "copilot-ci": "copilot ci", "copilot-publish": "copilot publish"}[wf.stem]
            self.assertIn(name, text, f"{wf.name} is not described in ARCHITECTURE.md")


class ReadmeLinksTests(unittest.TestCase):
    def test_relative_links_point_at_real_files(self):
        text = (ROOT / "README.md").read_text()
        for target in re.findall(r"\]\(((?!https?://|#)[^)\s]+)\)", text):
            self.assertTrue((ROOT / target).exists(), f"README links to missing {target}")


class BadgeTests(unittest.TestCase):
    def test_every_workflow_badge_points_at_a_real_workflow_file(self):
        text = (ROOT / "README.md").read_text()
        badges = re.findall(r"actions/workflows/([\w.-]+\.yml)/badge\.svg", text)
        self.assertTrue(badges, "README has no workflow badges")
        for name in badges:
            self.assertTrue((ROOT / ".github" / "workflows" / name).exists(), f"badge for missing workflow {name}")

    def test_every_workflow_has_a_badge(self):
        text = (ROOT / "README.md").read_text()
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            self.assertIn(f"workflows/{wf.name}/badge.svg", text, f"{wf.name} has no badge in the README")


if __name__ == "__main__":
    unittest.main()
