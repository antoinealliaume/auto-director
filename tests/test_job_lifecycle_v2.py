from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import unittest
from unittest.mock import patch

from app.job_lifecycle import (
    JOB_STATES,
    can_transition,
    claimable,
    deadline_exceeded,
    normalize_status,
    recoverable,
    retry_plan,
    worker_compatibility,
)
from app.structured_logging import log_event, reset_request_id, set_request_id


class JobLifecycleV2Tests(unittest.TestCase):
    def test_required_states_and_legacy_done_migration(self):
        self.assertEqual(JOB_STATES, {"queued", "claimed", "running", "completed", "failed", "cancelled"})
        self.assertEqual(normalize_status("done"), "completed")

    def test_transitions_are_explicit(self):
        self.assertTrue(can_transition("queued", "claimed"))
        self.assertTrue(can_transition("claimed", "running"))
        self.assertTrue(can_transition("running", "completed"))
        self.assertFalse(can_transition("completed", "running"))

    def test_double_claim_guard(self):
        self.assertTrue(claimable("queued"))
        self.assertFalse(claimable("claimed"))
        self.assertFalse(claimable("running"))

    def test_timeout_and_restart_recovery(self):
        now=datetime(2026,9,19,tzinfo=timezone.utc)
        self.assertTrue(deadline_exceeded(now-timedelta(seconds=61),60,now=now))
        self.assertTrue(recoverable("running",has_live_lease=False,age_seconds=60,timeout_seconds=60))
        self.assertFalse(recoverable("running",has_live_lease=True,age_seconds=600,timeout_seconds=60))

    def test_retry_backoff_is_bounded(self):
        now=datetime(2026,9,19,tzinfo=timezone.utc)
        first=retry_plan({},now=now)
        second=retry_plan(first["settings"],now=now)
        third=retry_plan(second["settings"],now=now)
        self.assertEqual((first["delaySeconds"],second["delaySeconds"]),(15,30))
        self.assertTrue(first["allowed"] and second["allowed"])
        self.assertFalse(third["allowed"])

    def test_worker_offline_or_incompatible(self):
        self.assertFalse(worker_compatibility(None,None)["compatible"])
        self.assertFalse(worker_compatibility("9.1",2)["compatible"])
        self.assertFalse(worker_compatibility("9.2",1)["compatible"])
        self.assertTrue(worker_compatibility("9.2",2)["compatible"])

    def test_cancellation_is_terminal(self):
        self.assertTrue(can_transition("running","cancelled"))
        self.assertFalse(can_transition("cancelled","running"))

    def test_worker_failure_cannot_resurrect_cancelled_job(self):
        source=(Path(__file__).resolve().parents[1]/"app"/"local_worker_api2.py").read_text(encoding="utf-8")
        fail_block=source.split("    async def fail(",1)[1].split("    app.add_api_route",1)[0]
        guard="where id=%s and status in ('claimed','running') returning id"
        self.assertEqual(fail_block.count(guard),2)
        self.assertIn("if not updated:raise HTTPException(409,'Job annulé ou déjà terminé')",fail_block)
        self.assertLess(fail_block.index("if not updated"),fail_block.index("if plan['allowed']:rq().zadd"))

    def test_claim_error_recovery_cannot_resurrect_cancelled_job(self):
        source=(Path(__file__).resolve().parents[1]/"app"/"local_worker_api2.py").read_text(encoding="utf-8")
        claim_block=source.split("    async def claim(",1)[1].split("    async def asset(",1)[0]
        self.assertEqual(claim_block.count("where id=%s and status='claimed'"),1)
        self.assertIn("delete from worker_leases where job_id=%s",claim_block)

    def test_pc_worker_claim_respects_retry_backoff(self):
        source=(Path(__file__).resolve().parents[1]/"app"/"local_worker_api2.py").read_text(encoding="utf-8")
        claim_block=source.split("    async def claim(",1)[1].split("    async def asset(",1)[0]
        self.assertIn("coalesce(settings->>'nextAttemptAt','') in ('','null')",claim_block)
        self.assertIn("(settings->>'nextAttemptAt')::timestamptz <= now()",claim_block)

    def test_cloud_recovery_cannot_resurrect_cancelled_job(self):
        source=(Path(__file__).resolve().parents[1]/"engine"/"config.py").read_text(encoding="utf-8")
        recovery_block=source.split("def recover_stale_jobs():",1)[1]
        guard="where id=%s and status in ('claimed','running') returning id"
        self.assertIn(guard,recovery_block)
        self.assertIn("if not changed:continue",recovery_block)
        self.assertLess(recovery_block.index("if not changed:continue"),recovery_block.index("queue.delete('autodirector:lock:'"))

    def test_manual_retry_is_serialized_before_runtime_cleanup(self):
        source=(Path(__file__).resolve().parents[1]/"app"/"main.py").read_text(encoding="utf-8")
        retry_block=source.split("def retry_job(",1)[1].split("@app.get(\"/api/jobs/{job_id}/events\")",1)[0]
        self.assertIn("select status,output_asset_ids from jobs where id=%s for update",retry_block)
        self.assertIn("where id=%s and status in ('failed','cancelled') returning id",retry_block)
        self.assertLess(retry_block.index("for update"),retry_block.index("queue.lrem"))
        self.assertLess(retry_block.index("delete from worker_leases"),retry_block.index("update jobs set status='queued'"))
        self.assertNotIn("_clear_runtime_job_state(jid)",retry_block)
        self.assertNotIn("_delete_job_outputs(jid)",retry_block)

    def test_structured_logs_correlate_request_and_job(self):
        token=set_request_id('request-123')
        try:
            with patch('app.structured_logging.logger.log') as emit:
                log_event('job.claimed',job_id='job-456')
            payload=json.loads(emit.call_args.args[1])
            self.assertEqual(payload['request_id'],'request-123')
            self.assertEqual(payload['job_id'],'job-456')
            self.assertEqual(emit.call_args.args[0],logging.INFO)
        finally:
            reset_request_id(token)


if __name__ == "__main__":
    unittest.main()
