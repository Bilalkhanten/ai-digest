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
            name = {"ci": "ci", "daily-fork": "daily pipeline run", "weekly-rollup": "weekly roll-up",
                    "watchdog": "watchdog", "data-check": "data check", "token-health": "token health", "fork-inventory": "fork inventory", "copilot-ci": "copilot ci", "copilot-publish": "copilot publish",
                    "scorecard": "scorecard", "codeql": "codeql"}[wf.stem]
            self.assertIn(name, text, f"{wf.name} is not described in ARCHITECTURE.md")


class ReadmeLinksTests(unittest.TestCase):
    def test_relative_links_point_at_real_files(self):
        text = (ROOT / "README.md").read_text()
        for target in re.findall(r"\]\(((?!https?://|#)[^)\s]+)\)", text):
            self.assertTrue((ROOT / target).exists(), f"README links to missing {target}")


class PublishWorkflowTests(unittest.TestCase):
    def test_publish_workflow_attests_what_it_publishes(self):
        text = (ROOT / ".github" / "workflows" / "copilot-publish.yml").read_text()
        self.assertEqual(text.count("uses: actions/attest@"), 2)      # tarball and image
        for use in re.findall(r"uses: (\S+)", text):
            self.assertRegex(use, r"@[0-9a-f]{40}$", f"{use} is not pinned to a commit SHA")
        self.assertIn("id-token: write", text)
        self.assertIn("attestations: write", text)
        # attestations are only created for real releases, never for dry runs
        for block in text.split("- name: Attest")[1:]:
            self.assertIn("if: github.ref_type == 'tag'", block.split("uses:")[0])
        # the tarball that is published is the one that was packed and attested
        self.assertIn('npm publish "$TARBALL"', text)


class BadgeTests(unittest.TestCase):
    def test_images_only_come_from_github_or_shields(self):
        text = (ROOT / "README.md").read_text()
        for url in re.findall(r"!\[[^\]]*\]\((https?://[^)\s]+)\)", text):
            self.assertRegex(url, r"^https://(github\.com|img\.shields\.io|api\.securityscorecards\.dev)/", f"unexpected image host: {url}")

    def test_local_images_used_by_the_readme_exist(self):
        text = (ROOT / "README.md").read_text()
        sources = re.findall(r'<img[^>]+src="([^"]+)"', text)
        self.assertIn("docs/banner.svg", sources)
        for src in sources:
            if not src.startswith("http"):
                self.assertTrue((ROOT / src).exists(), f"README uses missing image {src}")

    def test_the_static_license_badge_matches_the_real_license(self):
        text = (ROOT / "README.md").read_text()
        if "copilot_license-MIT" in text:
            self.assertTrue((ROOT / "copilot" / "LICENSE").read_text().startswith("MIT License"))


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


class RepoHealthFilesTests(unittest.TestCase):
    def test_community_files_exist_and_say_what_they_should(self):
        security = (ROOT / "SECURITY.md").read_text()
        self.assertIn("Report a vulnerability", security)
        self.assertIn("read-only", security.lower())
        contributing = (ROOT / "CONTRIBUTING.md").read_text()
        self.assertIn("sole-author", contributing)      # explains why outside PRs fail CI
        self.assertIn("allowed-authors.txt", contributing)

    def test_codeowners_names_an_allowed_author(self):
        owners = (ROOT / ".github" / "CODEOWNERS").read_text()
        allowed = {ln.strip().lower() for ln in (ROOT / ".github" / "allowed-authors.txt").read_text().splitlines()
                   if ln.strip() and not ln.startswith("#")}
        handle = next(ln.split()[1] for ln in owners.splitlines() if ln.startswith("*"))
        self.assertTrue(handle.startswith("@"))
        self.assertTrue(any(handle.lstrip("@").lower() in a for a in allowed), handle)

    def test_issue_templates_are_present_and_look_like_forms(self):
        for name in ("bug_report.yml", "feature_request.yml"):
            text = (ROOT / ".github" / "ISSUE_TEMPLATE" / name).read_text()
            self.assertIn("name:", text)
            self.assertIn("body:", text)
        self.assertIn("security/advisories/new", (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text())

    def test_scorecard_workflow_has_no_run_steps_and_pins_every_action(self):
        text = (ROOT / ".github" / "workflows" / "scorecard.yml").read_text()
        self.assertNotIn("\n        run:", text)            # Scorecard requires this when publishing
        for use in re.findall(r"uses: (\S+)", text):
            self.assertRegex(use, r"@[0-9a-f]{40}$", f"{use} is not pinned to a commit SHA")


if __name__ == "__main__":
    unittest.main()
