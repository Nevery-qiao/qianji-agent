"""Only synthetic read/write fixtures and temporary journals."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from test_continuation_visibility_debt import VisibilityBackend
from qianji_agent.codec import digest
from qianji_agent.engine import Engine


class LastReadDrift(VisibilityBackend):
    def read(self, route, params):
        if route == "asset/info" and self.writes:
            target = next(a for a in self.data["assets"] if str(a["id"]) == str(params["did"]))
            target["currency"] = "USD"
        return super().read(route, params)


class FinalObservationTests(unittest.TestCase):
    def test_latest_info_evidence_must_reach_watch_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = LastReadDrift()
            backend.data["assets"][0]["status"] = 2
            engine = Engine(backend, "123", Path(tmp) / "journal")
            result = engine.execute("restore", {
                "action": "account_restore", "object_id": "10",
                "expected_version": digest(backend.data["assets"][0])})
            self.assertEqual(backend.data["assets"][0]["currency"], "USD")
            self.assertEqual(result["state"], "pending_verification", result)
            self.assertTrue(engine.journal.active_halts())


if __name__ == "__main__":
    unittest.main(verbosity=2)
