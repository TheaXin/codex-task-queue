import subprocess
import unittest
from unittest.mock import patch
from adapter import Adapter, PreflightError, InvalidTarget

THREAD = "11111111-1111-4111-8111-111111111111"
JOB = "22222222-2222-4222-8222-222222222222"


class AdapterTests(unittest.TestCase):
    def test_lookup_failure_is_preflight(self):
        a = Adapter()
        with patch.object(a, "threads", side_effect=OSError()), patch("adapter.subprocess.run") as run:
            with self.assertRaises(PreflightError):
                a.submit(THREAD, "test", JOB)
            run.assert_not_called()

    def test_invalid_target_never_starts_cli(self):
        a = Adapter()
        with patch.object(a, "threads", return_value=[]), patch("adapter.subprocess.run") as run:
            with self.assertRaises(InvalidTarget):
                a.submit(THREAD, "test", JOB)
            run.assert_not_called()

    def test_daemon_failure_is_preflight(self):
        a = Adapter()
        with patch.object(a, "threads", return_value=[{"id": THREAD}]), patch(
            "adapter.subprocess.run", side_effect=subprocess.TimeoutExpired("daemon", 60)
        ):
            with self.assertRaises(PreflightError):
                a.submit(THREAD, "test", JOB)

    def test_queue_timeout_is_ambiguous(self):
        a = Adapter()
        with patch.object(a, "threads", return_value=[{"id": THREAD}]), patch(
            "adapter.subprocess.run", side_effect=[subprocess.CompletedProcess([], 0),
                                                   subprocess.TimeoutExpired("queue", 60)]
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                a.submit(THREAD, "test", JOB)

    def test_receipt_on_later_page_is_found(self):
        a = Adapter()
        receipt = {"id": "turn", "status": "completed", "items": [
            {"type": "userMessage", "content": [{"type": "text", "text": f"[队列任务 {JOB}]\nhello"}]}
        ]}
        with patch.object(a, "rpc", side_effect=[
            {"data": [{"items": []}], "nextCursor": "next"},
            {"data": [receipt], "nextCursor": None}
        ]) as rpc:
            self.assertEqual(a.result(THREAD, JOB), "completed")
            self.assertEqual(rpc.call_args.args[1]["cursor"], "next")
            self.assertEqual(rpc.call_args.args[1]["itemsView"], "full")

    def test_unknown_quota_does_not_allow_dispatch(self):
        a = Adapter()
        with patch.object(a, "rpc", return_value={"ordinaryUsageAllowed": True}):
            self.assertFalse(a.quota()["allowed"])

    def test_weekly_exhaustion_blocks(self):
        a = Adapter()
        with patch.object(a, "rpc", return_value={"ordinaryUsageAllowed": True, "rateLimits": {
            "primary": {"usedPercent": 1}, "secondary": {"usedPercent": 100, "resetsAt": 123}
        }}):
            self.assertEqual(a.quota()["retry_at"], 123)
            self.assertFalse(a.quota()["allowed"])


if __name__ == "__main__":
    unittest.main()
