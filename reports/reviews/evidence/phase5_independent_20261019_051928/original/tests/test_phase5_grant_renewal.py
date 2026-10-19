"""A timeout of an old interval must not expire the finite key pass."""
import time
import unittest
import test_phase5_baselines as helpers
from cache_scaleout.contracts import ControllerAction,TransferBudget


class GrantBoundaryRenewal(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,stage):
        d,m,caches,db,s=helpers.MigrationPolicyTests().system()
        now=time.monotonic_ns()
        def replace_grant():
            now=time.monotonic_ns()
            s.apply_action(ControllerAction(now,TransferBudget(10,20000,10,10,1_000_000_000,20000),(),('replacement',),0,now))
        replace_grant()
        reservation=await s.grants.reserve_destination(1088)
        calls=0
        async def acquire(dimensions,deadline_ns):
            nonlocal calls
            calls+=1
            if calls==1:
                replace_grant()
                raise TimeoutError('old grant expired during replacement')
        s.tokens.acquire=acquire
        if stage=='source':
            fresh,issued=await s._source_slot(reservation,1088,'donor',now+500_000_000)
            self.assertTrue(issued)
        else:
            fresh=await s._destination_slot(reservation,1088,now+500_000_000)
            self.assertIsNotNone(fresh)
        self.assertEqual(calls,2)
        self.assertEqual(fresh.generation,s.grants.last_decided_at_ns)

    async def test_source_old_timeout_renews_live_replacement(self):await self.exercise('source')
    async def test_destination_old_timeout_renews_live_replacement(self):await self.exercise('destination')
