import ast
import os
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
WORKER_SOURCE = ROOT / "self_hosted_worker/http_worker.py"


def load_bounded_env_int():
    source = WORKER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_bounded_env_int"
    )
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"os": os}
    exec(compile(module, str(WORKER_SOURCE), "exec"), namespace)
    return namespace["_bounded_env_int"]


class WorkerTokenRenewalTests(unittest.TestCase):
    def test_failed_proactive_renewal_retries_after_short_delay(self):
        source = WORKER_SOURCE.read_text(encoding="utf-8")
        start = source.index("def renew_loop():")
        end = source.index("\ndef heartbeat_payload", start)
        renew_loop = source[start:end]

        self.assertIn("while not STOP.wait(RENEW_SECONDS):", renew_loop)
        self.assertIn("while not renew_token():", renew_loop)
        self.assertIn("if STOP.wait(60):return", renew_loop)

    def test_invalid_worker_intervals_fall_back_to_defaults(self):
        bounded = load_bounded_env_int()
        with patch.dict(os.environ, {
            "WORKER_POLL_SECONDS": "broken",
            "WORKER_RENEW_SECONDS": "",
        }):
            self.assertEqual(bounded("WORKER_POLL_SECONDS", 4, 2, 15), 4)
            self.assertEqual(bounded("WORKER_RENEW_SECONDS", 10800, 1800, 6 * 3600), 10800)

    def test_worker_intervals_keep_existing_bounds(self):
        bounded = load_bounded_env_int()
        with patch.dict(os.environ, {
            "WORKER_POLL_SECONDS": "0",
            "WORKER_RENEW_SECONDS": "999999",
        }):
            self.assertEqual(bounded("WORKER_POLL_SECONDS", 4, 2, 15), 2)
            self.assertEqual(bounded("WORKER_RENEW_SECONDS", 10800, 1800, 6 * 3600), 6 * 3600)

        source = WORKER_SOURCE.read_text(encoding="utf-8")
        self.assertIn("POLL_SECONDS=_bounded_env_int('WORKER_POLL_SECONDS',4,2,15)", source)
        self.assertIn("RENEW_SECONDS=_bounded_env_int('WORKER_RENEW_SECONDS',10800,1800,6*3600)", source)


if __name__ == "__main__":
    unittest.main()
