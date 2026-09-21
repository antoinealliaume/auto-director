from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerTokenRenewalTests(unittest.TestCase):
    def test_failed_proactive_renewal_retries_after_short_delay(self):
        source = (ROOT / "self_hosted_worker/http_worker.py").read_text(encoding="utf-8")
        start = source.index("def renew_loop():")
        end = source.index("\ndef heartbeat_payload", start)
        renew_loop = source[start:end]

        self.assertIn("while not STOP.wait(RENEW_SECONDS):", renew_loop)
        self.assertIn("while not renew_token():", renew_loop)
        self.assertIn("if STOP.wait(60):return", renew_loop)


if __name__ == "__main__":
    unittest.main()
