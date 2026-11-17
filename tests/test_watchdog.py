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


class CatchUpTests(unittest.TestCase):
    def test_missing_today(self):
        self.assertTrue(wd.missing_today([{"date": "2026-11-15"}], date(2026, 11, 16)))
        self.assertFalse(wd.missing_today([{"date": "2026-11-16"}], date(2026, 11, 16)))
        self.assertTrue(wd.missing_today([], date(2026, 11, 16)))

    def run_main(self, state, force="0", today=date(2026, 11, 16)):
        import os
        import tempfile
        from datetime import datetime, timezone
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            env = {"GITHUB_OUTPUT": str(out), "FORCE_CATCH_UP": force}
            fake_now = mock.MagicMock()
            fake_now.now.return_value = datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc)
            with mock.patch.dict(os.environ, env), mock.patch.object(wd, "load_state", return_value=state), \
                    mock.patch.object(wd, "datetime", fake_now):
                code = wd.main()
            return code, out.read_text()

    def test_output_is_false_when_todays_digest_exists(self):
        code, out = self.run_main([{"date": "2026-11-16"}])
        self.assertEqual((code, out), (0, "missing_today=false\n"))

    def test_output_is_true_when_it_is_missing_even_though_not_yet_overdue(self):
        code, out = self.run_main([{"date": "2026-11-15"}])
        self.assertEqual(code, 0)                         # only one day old: no alert yet...
        self.assertEqual(out, "missing_today=true\n")     # ...but the repair step should still run

    def test_overdue_fails_and_also_asks_for_a_repair(self):
        code, out = self.run_main([{"date": "2026-11-10"}])
        self.assertEqual((code, out), (1, "missing_today=true\n"))

    def test_force_catch_up_overrides_a_present_digest(self):
        code, out = self.run_main([{"date": "2026-11-16"}], force="1")
        self.assertEqual((code, out), (0, "missing_today=true\n"))

    def test_no_output_file_is_fine(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_OUTPUT", None)
            wd.set_output("x", "y")          # must not raise


if __name__ == "__main__":
    unittest.main()
