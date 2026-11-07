import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import server


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in (("DATA", Path(self.temp.name)), ("adapter", Mock())):
            patched = patch.object(server, name, value)
            patched.start()
            self.addCleanup(patched.stop)
        server.next_quota_check = 0
        server.initialize()
        server.adapter.quota.return_value = {"allowed": True, "reason": "可用"}
        server.adapter.submit.return_value = "turn1"

    def seed(self, key, thread="a"):
        with server.db() as c:
            c.execute(
                "insert into jobs(id,thread_id,prompt,due,status,detail,turn_id) values(?,?,?,0,'queued','',null)",
                (key, thread, key),
            )

    def status(self, key):
        with server.db() as c:
            return c.execute("select status from jobs where id=?", (key,)).fetchone()[0]

    def test_quota_wait_and_return(self):
        self.seed("one")
        server.adapter.quota.return_value["allowed"] = False
        server.dispatch()
        server.adapter.submit.assert_not_called()
        server.next_quota_check = 0
        server.initialize()
        server.adapter.quota.return_value["allowed"] = True
        server.dispatch()
        server.adapter.result.return_value = "completed"
        server.dispatch()
        self.assertEqual(self.status("one"), "delivered")
        server.adapter.submit.assert_called_once_with("a", "one", "one")

    def test_ambiguous_receipt_blocks_same_target_only(self):
        self.seed("one")
        self.seed("two")
        self.seed("three", "b")
        server.adapter.submit.side_effect = TimeoutError()
        server.dispatch()
        self.assertEqual(self.status("one"), "review")
        server.adapter.result.return_value = "unknown"
        server.adapter.submit.side_effect = None
        server.dispatch()
        self.assertEqual(self.status("two"), "queued")
        self.assertEqual(self.status("three"), "running")

    def test_quota_during_execution_continues_with_new_marker(self):
        self.seed("one")
        server.dispatch()
        server.adapter.result.return_value = "quota"
        server.adapter.quota.return_value["allowed"] = False
        server.dispatch()
        self.assertEqual(self.status("one"), "waiting_quota")
        server.next_quota_check = 0
        server.adapter.quota.return_value["allowed"] = True
        server.dispatch()
        call = server.adapter.submit.call_args
        self.assertNotEqual(call.args[2], "one")
        self.assertIn("只完成尚未完成的部分", call.args[1])
        self.assertEqual(server.adapter.submit.call_count, 2)

    def test_ambiguous_delivery_reconciles_without_resend(self):
        self.seed("one")
        server.adapter.submit.side_effect = TimeoutError()
        server.dispatch()
        server.initialize()
        server.adapter.result.return_value = "completed"
        server.dispatch()
        self.assertEqual(self.status("one"), "delivered")
        server.adapter.submit.assert_called_once()

    def test_preflight_preserves_due_and_order(self):
        self.seed("one")
        self.seed("two")
        self.seed("three", "b")
        server.adapter.submit.side_effect = server.PreflightError("offline")
        server.dispatch()
        with server.db() as c:
            row = c.execute("select due,retry_at from jobs where id='one'").fetchone()
        self.assertEqual(row["due"], 0)
        self.assertGreater(row["retry_at"], 0)
        server.adapter.submit.side_effect = None
        server.dispatch()
        self.assertEqual(self.status("two"), "queued")
        self.assertEqual(self.status("three"), "running")

    def test_recovery_precedes_new_earlier_due_job(self):
        self.seed("interrupted")
        self.seed("new")
        server.update_job("interrupted", status="waiting_quota", due=1)
        server.dispatch()
        self.assertEqual(self.status("interrupted"), "running")
        self.assertEqual(self.status("new"), "queued")

    def test_missing_target_requires_review(self):
        self.seed("one")
        server.adapter.submit.side_effect = server.InvalidTarget("missing")
        server.dispatch()
        self.assertEqual(self.status("one"), "review")
        with server.db() as c:
            self.assertIsNone(c.execute("select turn_id from jobs").fetchone()[0])

    def test_crash_after_claim(self):
        self.seed("one")
        with server.db() as c:
            c.execute("update jobs set status='sending'")
        server.initialize()
        server.dispatch()
        server.adapter.submit.assert_not_called()
        self.assertEqual(self.status("one"), "review")


if __name__ == "__main__":
    unittest.main()
