import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch

import server


class HttpTests(unittest.TestCase):
    def context(self, manager):
        value = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        return value

    def setUp(self):
        tmp = self.context(tempfile.TemporaryDirectory())
        self.context(patch.object(server, "DATA", Path(tmp)))
        self.context(patch.object(server, "threads", []))
        self.target = "11111111-1111-4111-8111-111111111111"
        self.job = "22222222-2222-4222-8222-222222222222"
        adapter = self.context(patch.object(server, "adapter", Mock()))
        adapter.threads.return_value = [{"id": self.target}]
        server.initialize()
        http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.addCleanup(http.server_close)
        self.port = http.server_port
        worker = threading.Thread(target=http.serve_forever)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(http.shutdown)
        self.origin = f"http://127.0.0.1:{self.port}"

    def request(self, path, data=None, **headers):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            body = None if data is None else json.dumps(data)
            headers = {"Origin": self.origin, "Content-Type": "application/json", **headers}
            connection.request("GET" if data is None else "POST", path, body, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def payload(self, **overrides):
        return dict(id=self.job, thread_id=self.target, prompt="test", due=0) | overrides

    def test_idempotency_and_cancellation(self):
        self.assertEqual(self.request("/api/state")[0], 200)
        for _ in range(2):
            self.assertEqual(self.request("/api/jobs", self.payload())[0], 200)
        self.assertEqual(self.request("/api/jobs", self.payload(prompt="different"))[0], 400)
        self.assertEqual(self.request("/api/cancel", {"id": self.job})[0], 200)
        jobs = self.request("/api/state")[1]["jobs"]
        self.assertEqual([(j["id"], j["status"]) for j in jobs], [(self.job, "cancelled")])

    def test_draft_stays_out_of_dispatch_until_explicitly_queued(self):
        for prompt in ("rough idea", "edited idea"):
            self.assertEqual(self.request("/api/drafts", {"id": self.job, "prompt": prompt})[0], 200)
        server.initialize()
        server.dispatch()
        server.adapter.quota.assert_not_called()
        server.adapter.submit.assert_not_called()
        status, data = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual([(job["status"], job["prompt"], job["thread_id"])
                          for job in data["jobs"]], [("draft", "edited idea", "")])
        for _ in range(2):
            self.assertEqual(self.request("/api/jobs", self.payload(prompt="edited idea"))[0], 200)
        self.assertEqual(self.request("/api/drafts", {"id": self.job, "prompt": "stale edit"})[0], 400)
        self.assertEqual([job["status"] for job in self.request("/api/state")[1]["jobs"]], ["queued"])

    def test_rejects_invalid_date_and_cross_origin(self):
        self.request("/api/state")
        for value in (True, -1, 10**15, 1.5, "123"):
            self.assertEqual(self.request("/api/jobs", self.payload(due=value))[0], 400)
        self.assertEqual(self.request("/api/jobs", self.payload(), Origin="http://example.invalid")[0], 403)
        self.assertEqual(self.request("/api/state", Host="example.invalid")[0], 403)
        self.assertEqual(self.request("/api/state")[1]["jobs"], [])
