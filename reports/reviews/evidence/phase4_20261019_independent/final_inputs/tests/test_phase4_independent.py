"""Counterexamples to permissive Phase 4 evidence and workload selection."""
import importlib.util
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
ANALYSIS=Path(os.environ.get('P4_ANALYSIS_PATH', ROOT/'analysis/phase4_analysis.py'))
spec=importlib.util.spec_from_file_location('phase4_review_analysis', ANALYSIS)
analysis=importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class EvidenceNegatives(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run=Path(self.tmp.name)/'sample'
        shutil.copytree(ROOT/'runs/p4cal_confirm_r24_1', self.run)

    def mutate(self, change):
        path=self.run/'requests.jsonl'
        rows=[json.loads(s) for s in path.read_text().splitlines()]
        change(rows)
        path.write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def assertRejected(self, reason):
        result=analysis.validate(self.run)
        self.assertFalse(result['valid'])
        self.assertTrue(any(reason in s for s in result['errors']),result['errors'])

    def test_wrong_key(self):
        self.mutate(lambda rows:rows[0].update(key='wrong'))
        self.assertRejected('schedule identity')

    def test_rewritten_scheduled_time(self):
        self.mutate(lambda rows:rows[0].update(scheduled_arrival_ns=rows[0]['scheduled_arrival_ns']-1))
        self.assertRejected('schedule identity')

    def test_nonterminal(self):
        self.mutate(lambda rows:rows[0].update(outcome='running'))
        self.assertRejected('terminal outcome')

    def test_summary_is_recomputed(self):
        path=self.run/'result.json'; value=json.loads(path.read_text())
        value['successful_p95_ms']=0
        path.write_text(json.dumps(value))
        self.assertRejected('summary mismatch')

    def test_duplicate_offer(self):
        path=self.run/'offered_schedule.json'; value=json.loads(path.read_text())
        value['requests'].append(value['requests'][0]); path.write_text(json.dumps(value))
        self.assertRejected('duplicate offered')

    def test_calibration_without_common_probes(self):
        self.assertRejected('missing DB probe')

    def test_driver_failure_is_not_database_capacity(self):
        self.mutate(lambda rows:rows[-1].update(outcome='failed',error='RuntimeError:DB issuance stopped'))
        self.assertRejected('not DB capacity')


class WorkloadTests(unittest.TestCase):
    def test_capacity_not_hardcoded(self):
        self.assertIsNone(analysis.select_capacity([]))
        self.assertEqual(analysis.select_capacity([{'offered_rate':12,'eligible':True},{'offered_rate':24,'eligible':False}]),12)

    def test_run_level_uncertainty(self):
        value=analysis.run_uncertainty([1,2,3])
        self.assertEqual(value['independent_runs'],3)
        self.assertEqual(value['mean'],2)
        self.assertLess(value['normal_model_t95_interval'][0],0)

    def test_zipf_parameter_changes_draws(self):
        from cache_scaleout.phase4 import _zipf_keys
        self.assertNotEqual(_zipf_keys(list(range(20)),100,404,.1),_zipf_keys(list(range(20)),100,404,3.0))

    def test_requested_share_is_applied(self):
        from cache_scaleout.phase4 import select_workload
        for share in (.2,.65,1.0):
            rows=select_workload(['a'],['b'],101,share,1.15,404)
            self.assertEqual(rows.count('a'),round(101*share))

    def test_failures_count_in_all_offer_denominator(self):
        from cache_scaleout.phase4 import _window_summary
        result=_window_summary([
            {'scheduled_arrival_ns':1,'submitted_ns':1,'completed_ns':20,'outcome':'completed'},
            {'scheduled_arrival_ns':2,'submitted_ns':2,'completed_ns':20,'outcome':'timed_out'}],0,30,100)
        self.assertEqual(result['all_offer_latency_violations'],1)
        self.assertEqual(result['all_offer_violation_fraction'],.5)


class CorrectedRawNegatives(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run=Path(self.tmp.name)/'corrected'
        shutil.copytree(ROOT/'runs/p4review_pilot_immediate_20261019',self.run)
        self.assertTrue(analysis.validate(self.run)['valid'])

    def change(self,callback,reason):
        path=self.run/'result.json'; value=json.loads(path.read_text()); callback(value); path.write_text(json.dumps(value))
        result=analysis.validate(self.run)
        self.assertFalse(result['valid'])
        self.assertTrue(any(reason in e for e in result['errors']),result['errors'])

    def test_missing_probe_terminal(self):
        self.change(lambda r:r['accounting']['database_probes'][0].update(terminal_ns=None),'probe terminal')

    def test_wrong_cutover_map(self):
        self.change(lambda r:r['transition_record'].update(affected_buckets=[]),'cutover map')

    def test_foreground_operation_omitted(self):
        self.change(lambda r:r['router']['operations'].pop(),'operation request')

    def test_wrong_payload(self):
        self.change(lambda r:r['payload_checks'][0].update(payload_sha256='bad'),'payload mismatch')


class DatabaseExpiryRace(unittest.IsolatedAsyncioTestCase):
    async def test_expired_acquisition_never_starts_or_quarantines_query(self):
        from cache_scaleout.adapters import PostgresDatabaseAdapter
        from cache_scaleout.issuance import issuing
        class Connection:
            @asynccontextmanager
            async def transaction(self):
                yield
            async def execute(self,*args):
                await asyncio.Event().wait()
        class Pool:
            def __init__(self): self.returned=0
            async def getconn(self,**kwargs): return Connection()
            async def putconn(self,connection): self.returned+=1
        db=PostgresDatabaseAdapter(connection_kwargs={},foreground_max_size=1,background_max_size=1,
            pool_timeout_seconds=1,statement_timeout_ms=1000,pressure_latency_upper_ms=1000)
        pool=Pool(); db.foreground_pool=pool
        issued=[]
        try:
            # The acquisition succeeds just as the absolute deadline expires.
            with patch('cache_scaleout.adapters._remaining_seconds',side_effect=[1.,1.,TimeoutError('expired after acquisition')]):
                with issuing(lambda:issued.append(True)):
                    with self.assertRaises(TimeoutError):
                        await db.read_foreground('key',deadline_ns=10**18)
            self.assertFalse(db._stopped,'a known idle connection must not quarantine an unissued query')
            self.assertEqual(issued,[])
            self.assertEqual(pool.returned,1)
            self.assertEqual(db._foreground_limit.active,0)
        finally:
            pending=[t for _,_,t in db._quarantined]
            for task in pending: task.cancel()
            await asyncio.gather(*pending,return_exceptions=True)


if __name__=='__main__': unittest.main()
