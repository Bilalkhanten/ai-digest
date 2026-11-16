"""Offline tests for scripts/health_check.py."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import health_check as hc  # noqa: E402

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def headers(scopes="public_repo", expiry="2027-02-14 00:00:00 UTC", remaining="4999"):
    h = {"X-OAuth-Scopes": scopes, "X-RateLimit-Remaining": remaining}
    if expiry:
        h["github-authentication-token-expiration"] = expiry
    return h


class EvaluateTests(unittest.TestCase):
    def test_healthy_token(self):
        problems, notes = hc.evaluate(200, headers(), now=NOW)
        self.assertEqual(problems, [])
        self.assertTrue(any("days left" in n for n in notes))

    def test_rejected_token(self):
        problems, _ = hc.evaluate(401, {}, now=NOW)
        self.assertEqual(len(problems), 1)
        self.assertIn("401", problems[0])

    def test_expiring_soon_is_a_problem(self):
        problems, _ = hc.evaluate(200, headers(expiry="2026-11-25 00:00:00 UTC"), now=NOW)
        self.assertTrue(any("expires in" in p for p in problems))

    def test_already_expired(self):
        problems, _ = hc.evaluate(200, headers(expiry="2026-11-01 00:00:00 UTC"), now=NOW)
        self.assertTrue(any("expired" in p for p in problems))

    def test_broader_scopes_are_flagged(self):
        problems, _ = hc.evaluate(200, headers(scopes="public_repo, workflow"), now=NOW)
        self.assertTrue(any("broader scopes" in p for p in problems))

    def test_missing_public_repo_scope(self):
        problems, _ = hc.evaluate(200, headers(scopes="read:user"), now=NOW)
        self.assertTrue(any("missing the public_repo" in p for p in problems))

    def test_no_expiry_header_is_only_a_note(self):
        problems, notes = hc.evaluate(200, headers(expiry=None), now=NOW)
        self.assertEqual(problems, [])
        self.assertTrue(any("no expiry" in n.lower() for n in notes))

    def test_parse_expiry(self):
        self.assertEqual(hc.parse_expiry("2027-02-14 00:00:00 UTC").year, 2027)
        self.assertIsNone(hc.parse_expiry("garbage"))
        self.assertIsNone(hc.parse_expiry(None))


if __name__ == "__main__":
    unittest.main()
