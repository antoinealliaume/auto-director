import unittest
from unittest.mock import patch

import engine.config as cfg


class Result:
    def __init__(self, rows): self.rows=rows
    def fetchall(self): return self.rows


class FakeConnection:
    def __init__(self, queued): self.queued=queued
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def execute(self, sql, params=None):
        if "status='running'" in sql and 'select id' in sql:
            return Result([])
        if "status='queued'" in sql and 'select id' in sql:
            return Result([(x,) for x in self.queued])
        return Result([])


class FakeQueue:
    def __init__(self): self.deleted=[];self.pushed=[]
    def delete(self,key): self.deleted.append(key);return 1
    def lpos(self,key,value): return None
    def lpush(self,key,value): self.pushed.append((key,value));return 1


class QueueRecoveryTests(unittest.TestCase):
    def test_queued_job_clears_stale_lock_before_requeue(self):
        q=FakeQueue();jid='job-123'
        with patch.object(cfg,'queue',q), patch.object(cfg,'db',lambda:FakeConnection([jid])):
            cfg.recover_stale_jobs()
        self.assertIn('autodirector:lock:'+jid,q.deleted)
        self.assertIn(('auto_director:jobs',jid),q.pushed)


if __name__=='__main__':
    unittest.main()
