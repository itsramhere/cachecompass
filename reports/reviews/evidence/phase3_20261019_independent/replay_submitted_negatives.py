"""Replay ten runtime negatives using hash-verified archived submitted modules.

This is a fresh replay harness, not a claim to be the original test-file bytes.
"""
import ast
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).parent
archive = BASE/'original'
submitted = json.loads((ROOT/'reports/evidence/phase3/source-final-002.json').read_text())
for row in submitted['files']:
    assert hashlib.sha256((archive/row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
sys.path.insert(0,str(archive))
sys.path.insert(0,str(archive/'src'))
from tests import test_phase3_behavior as fixtures
from cache_scaleout.contracts import CacheValue, ControllerAction, TransferBudget, OperationOutcome
from cache_scaleout.migration import GrantEnforcer
from cache_scaleout.telemetry import reconcile_offers
from cache_scaleout import router
assert Path(router.__file__).resolve().is_relative_to(archive.resolve())
FakeCache, FakeDatabase = fixtures.FakeCache, fixtures.FakeDatabase
ownership_and_item, retry = fixtures.ownership_and_item, fixtures.retry
selected = {
    'IndependentRouterTests': {'setup_router','test_cache_cancellation_finishes_issued_ledger',
        'test_creator_deadline_bounds_fill_with_later_follower','test_refusal_still_records_submitted_demand',
        'test_write_retry_backoff_failure_keeps_valid_database_value'},
    'IndependentMigrationTests': {'setup_scheduler','test_worker_fault_propagates_and_does_not_hang_queue',
        'test_caller_cancellation_drains_workers_and_charges_attempt',
        'test_replaced_reservation_cannot_refund_new_grant','test_expired_grant_cannot_issue_destination'},
    'IndependentAccountingTests': {'test_reconciliation_rejects_wrong_key_and_schedule',
                                 'test_reconciliation_rejects_nonterminal_outcome'}}
tree = ast.parse((ROOT/'tests/test_phase3_independent.py').read_text())
classes = []
for node in tree.body:
    if isinstance(node,ast.ClassDef) and node.name in selected:
        node.body = [method for method in node.body if getattr(method,'name','') in selected[node.name]]
        for method in node.body:
            if getattr(method,'name','') == 'test_expired_grant_cannot_issue_destination':
                method.body = ast.parse('''
grants = GrantEnforcer()
now = time.monotonic_ns()
grants.apply_action(ControllerAction(now, TransferBudget(1,128,1,1,1_000_000,128), (), ('a',),0,now))
reservation = await grants.reserve_destination(64)
while time.monotonic_ns() <= now+5_000_000:
    await asyncio.sleep(.001)
with self.assertRaises((TimeoutError,RuntimeError)):
    await grants.issue_destination(reservation)
''').body
        classes.append(node)
replay = ast.fix_missing_locations(ast.Module(body=classes,type_ignores=[]))
exec(compile(replay,str(__file__),'exec'))
print(json.dumps({'archived_runtime':str(router.__file__),'verified_source_files':len(submitted['files']),
                  'submitted_source_sha256':submitted['aggregate_sha256']}))
suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
result = unittest.TextTestRunner(verbosity=2).run(suite)
assert result.testsRun == 10 and len(result.failures) == 10 and not result.errors
print(json.dumps({'ten_submitted_runtime_failures_reproduced':True}))
