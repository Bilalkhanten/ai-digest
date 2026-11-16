"""Offline tests for scripts/watchdog.py."""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import watchdog as wd  # noqa: E402

STATE = [{"date": "2026-11-14"}, {"date": "2026-11-16"}]


class EvaluateTests(unittest.TestCase):
    def test_on_schedule(self):
        ok, msg = wd.evaluate(STATE, date(2026, 11, 16))
        self.assertTrue(ok)
        self.assertIn("On schedule", msg)

    def test_one_day_old_is_still_fine(self):
        self.assertTrue(wd.evaluate(STATE, date(2026, 11, 17))[0])

    def test_two_days_old_is_overdue(self):
        ok, msg = wd.evaluate(STATE, date(2026, 11, 18))
        self.assertFalse(ok)
        self.assertIn("2026-11-16", msg)

    def test_threshold_is_configurable(self):
        self.assertTrue(wd.evaluate(STATE, date(2026, 11, 18), overdue_days=5)[0])
        self.assertFalse(wd.evaluate(STATE, date(2026, 11, 17), overdue_days=1)[0])

    def test_empty_state_is_not_an_error(self):
        self.assertTrue(wd.evaluate([], date(2026, 11, 16))[0])

    def test_uses_the_newest_entry_regardless_of_order(self):
        self.assertTrue(wd.evaluate([{"date": "2026-11-16"}, {"date": "2026-01-01"}], date(2026, 11, 16))[0])


if __name__ == "__main__":
    unittest.main()
