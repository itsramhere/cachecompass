"""Independent Phase 5 counterexamples; names/aggregate flags are not proof."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'analysis')]
import test_phase5_baselines as owner
from cache_scaleout import phase5
from cache_scaleout.baselines import BaselineController,install_action
from cache_scaleout.contracts import (BucketState,ComponentPressure,ControllerAction,TransferBudget,PressureState,DataSource,CacheReadResult)
from cache_scaleout.issuance import notify_issued
from cache_scaleout.observations import BoundedDemandTracker,ResidencyTracker
from cache_scaleout.policy_observations import ObservationBuilder,PressureClassifier
from cache_scaleout.dataset import StableOwnershipMap,create_dataset
from phase5_validation import validate,matched


def builder_fixture():
    c=phase5.load_config(ROOT/'configs/phase5_pilot.yaml')
    d=create_dataset(seed=505,key_count=512,value_bytes=1024)
    o=StableOwnershipMap(mapping_seed=20261019,bucket_count=64,old_nodes=('old-1','old-2'),final_nodes=('old-1','old-2','new'),destination='new')
    registry=o.keys_by_bucket(d)
    t=BoundedDemandTracker(subwindow_ns=500_000_000,retained_subwindows=2,max_total_keys=512,max_keys_per_bucket=512,max_buckets=64,max_age_ns=1_500_000_000,origin_ns=10_000_000_000,reserve_open_subwindow=True)
    t.register({b:{i.key:i.object_bytes for i in v} for b,v in registry.items()})
    b=ObservationBuilder(c,origin=10_000_000_000,ownership=o,tracker=t,residency=ResidencyTracker(destination='new',registered_keys=tuple(i.key for i in d.items)),registry=registry)
    return c,b


def round_sample(now):
    return {'started_ns':now-50_000_000,'ended_ns':now-1,
        'raw_database_sample':{'probe_ms':10.,'foreground_waiting':0,'background_waiting':0,'real_classes':{}},
        'raw_cache_samples':{n:{'ping_ms':1.,'used_memory':1_000_000,'maxmemory':33_554_432,'evicted_keys':0,'waiting':0,'active':0,'real_classes':{}} for n in ('old-1','old-2','new')},
        'samples':{n:{'state':'safe','observed_at_ns':now-1,'reason':'complete'} for n in ('old-1','old-2','new','database')}}


def observation_from(b,now,ops=(),rounds=None):
    return b.build(now,foreground_operations=list(ops),terminal_requests=[],migration_operations=[],rounds=rounds or [round_sample(now)],probe_records=[])


class ObservationCounterexamples(unittest.TestCase):
    def test_missing_cache_resource_bundle_is_unknown(self):
        c,b=builder_fixture()
        result=PressureClassifier(c['policy_pressure']).classify('new',{'ping_ms':1.},observed_ns=1,real_rows=[],rate=0)
        self.assertEqual(result.state,PressureState.UNKNOWN)

    def test_foreground_db_latency_is_not_attributed_to_cache(self):
        c,b=builder_fixture();now=12_000_000_000
        row={'request_id':'db','work_class':'foreground_database','target_owner':'old-1','issued_ns':now-300_000_000,'terminal_ns':now-100_000_000,'outcome':'completed'}
        o=observation_from(b,now,[row])
        self.assertEqual(o.db_pressure.state,PressureState.UNSAFE)
        self.assertEqual(o.donor_pressure.state,PressureState.SAFE)

    def test_individual_component_timestamp_is_not_freshened_by_bundle(self):
        c,b=builder_fixture();now=12_000_000_000;r=round_sample(now)
        r['samples']['old-1']['observed_at_ns']=now-2_000_000_000
        o=observation_from(b,now,rounds=[r])
        self.assertEqual(o.donor_pressure.effective_state(as_of_ns=now,max_age_ns=o.max_signal_age_ns),PressureState.STALE)

    def test_inflight_operation_older_than_one_slot_still_exerts_pressure(self):
        c,b=builder_fixture();now=12_000_000_000
        row={'request_id':'hung','work_class':'foreground_database','target_owner':'old-1','issued_ns':now-1_000_000_000,'terminal_ns':None,'outcome':None}
        o=observation_from(b,now,[row])
        self.assertEqual(o.db_pressure.state,PressureState.UNSAFE)

    def test_missing_windows_cannot_reuse_old_estimator_history(self):
        c,b=builder_fixture()
        observation_from(b,12_000_000_000);observation_from(b,12_500_000_000)
        o=observation_from(b,15_000_000_000)
        self.assertEqual(o.foreground_db_observed_at_ns,0)


class ControllerCounterexamples(unittest.TestCase):
    def test_duplicate_window_cannot_claim_uninstalled_all_at_once_admissions(self):
        c=BaselineController('migration_before_cutover',owner.params(),expansion_ns=0)
        owner.step(c,owner.observation(states={1:BucketState.COPYING,2:BucketState.COPYING,3:BucketState.COPYING}))
        a=c.decide(owner.observation(),decided_at_ns=2_000_000_002)
        self.assertEqual(a.admit_buckets,())

    def test_expired_staged_action_cannot_publish_or_install_grant(self):
        d,m,caches,db,s=owner.MigrationPolicyTests().system()
        c=BaselineController('immediate_cutover',owner.params(),expansion_ns=0)
        o=owner.observation(states=dict(m.snapshot.states));a=c.decide(o,decided_at_ns=o.observed_at_ns)
        with self.assertRaises(ValueError):install_action(m,s,c,a)
        self.assertEqual(m.snapshot.epoch,0);self.assertIsNone(s.grants.action)


class GrantCounterexamples(unittest.IsolatedAsyncioTestCase):
    async def test_unissued_replacements_do_not_consume_retry_ordinals(self):
        d,m,caches,db,s=owner.MigrationPolicyTests().system()
        item=next(i for i in d.items if m.bucket_for_key(i.key) in m.affected_buckets)
        donor=caches[str(m.old_owner(m.bucket_for_key(item.key)))];donor.reports_issuance=True
        calls=[]
        def grant():
            n=time.monotonic_ns();s.apply_action(ControllerAction(n,TransferBudget(100,200000,100,100,1_000_000_000,200000),(),('test',),m.snapshot.epoch,n))
        async def read(key,*,source,deadline_ns):
            calls.append(key)
            if len(calls)<=2:grant()
            notify_issued()
            return CacheReadResult(source,item.cache_value(),time.monotonic_ns(),1)
        donor.read=read;grant()
        r=await s.migrate((item,),deadline_ns=time.monotonic_ns()+300_000_000,allow_db_fallback=False)
        self.assertEqual(r[0].disposition,'warmed')
        self.assertEqual(len(calls),3)
        self.assertEqual([o['retry_ordinal'] for o in s.operation_records],[1,1])
        self.assertEqual(r[0].attempts,2)

    async def test_old_unissued_refund_cannot_restore_zeroed_tokens(self):
        d,m,caches,db,s=owner.MigrationPolicyTests().system()
        item=next(i for i in d.items if m.bucket_for_key(i.key) in m.affected_buckets)
        donor=caches[str(m.old_owner(m.bucket_for_key(item.key)))];donor.reports_issuance=True
        def grant(zero=False):
            n=time.monotonic_ns();s.apply_action(ControllerAction(n,TransferBudget(0 if zero else 10,0 if zero else 20000,0,0 if zero else 10,1_000_000_000,0 if zero else 20000),(),('zero' if zero else 'start',),0,n))
        async def read(key,*,source,deadline_ns):
            grant(True);s.tokens.rates=dict.fromkeys(s.tokens.rates,0.);s.tokens.tokens=dict.fromkeys(s.tokens.tokens,0.)
            notify_issued()
        donor.read=read;grant()
        await s.migrate((item,),deadline_ns=time.monotonic_ns()+30_000_000,allow_db_fallback=False)
        self.assertEqual(sum(s.tokens.tokens.values()),0.)

    async def test_service_connection_failure_is_infrastructure_failure(self):
        c=phase5.load_config(ROOT/'configs/phase5_pilot.yaml')
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(phase5,'ROOT',Path(tmp)),patch.object(phase5,'_open_environment',AsyncMock(side_effect=ConnectionError('unavailable'))):
                with self.assertRaises(ConnectionError):await phase5.run(c,ROOT/'configs/phase5_pilot.yaml','connection-failure','immediate_cutover','A',seed=606,total_db_rate=16)
            self.assertEqual(json.loads((Path(tmp)/'runs/connection-failure/status.json').read_text())['status'],'infrastructure_failure')


class RawCounterexamples(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'run'
        shutil.copytree(ROOT/'runs/p5matrix_v1_20261019_smoke5',self.p)
    def tearDown(self):self.tmp.cleanup()
    def read(self,n):return json.loads((self.p/n).read_text())
    def write(self,n,v): (self.p/n).write_text(json.dumps(v))
    def reseal(self):self.write('checksums.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.p.iterdir() if p.is_file() and p.name!='checksums.json'})
    def test_unsafe_admission_in_resealed_action_log_is_rejected(self):
        r=self.read('result.json')
        a=next(a for a in r['actions'] if a['action']['admit_buckets'])
        a['observation']['db_pressure']['state']='unknown'
        self.write('result.json',r)
        events=[json.loads(l) for l in (self.p/'events.jsonl').read_text().splitlines()]
        for e in events:
            if e['kind']=='policy_action' and e['detail']['action']['decided_at_ns']==a['action']['decided_at_ns']:e['detail']=a
        (self.p/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events));self.reseal()
        self.assertFalse(validate(self.p)['valid'])

    def test_burst_and_parent_chronology_cannot_hide_in_long_integral(self):
        r=self.read('result.json');a=r['actions'][5];at=a['action']['decided_at_ns']+10_000_000
        selected=[op for op in r['migration_operations'] if op['work_class']=='donor_read'][:10]
        for op in selected:op.update(issued_ns=at,terminal_ns=at+1_000_000,absolute_deadline_ns=at+400_000_000,grant_generation_ns=a['action']['decided_at_ns'])
        self.write('result.json',r);self.reseal()
        self.assertFalse(validate(self.p)['valid'])

    def test_matched_comparison_checks_query_mix(self):
        q=Path(self.tmp.name)/'other';shutil.copytree(self.p,q)
        m=json.loads((q/'manifest.json').read_text())
        for v in m['initial_service_state'].values():v['server_run_id']+='different'
        (q/'manifest.json').write_text(json.dumps(m))
        c=json.loads((q/'effective_config.json').read_text());c['services']['database']['query_cpu_rounds']=1
        (q/'effective_config.json').write_text(json.dumps(c))
        self.assertFalse(matched([self.p,q])['valid'])

    def test_mixed_operations_match_key_and_schedule_not_just_boolean(self):
        shutil.rmtree(self.p);shutil.copytree(ROOT/'runs/p5mix12_v1_20261019',self.p)
        r=self.read('result.json');r['operations'][0]['key']='wrong-unregistered-key';self.write('result.json',r);self.reseal()
        self.assertFalse(validate(self.p)['valid'])

class HorizonCounterexamples(unittest.IsolatedAsyncioTestCase):
    async def test_sampler_cannot_start_another_round_after_horizon_without_close(self):
        from cache_scaleout.sampling import PressureSampler
        class Client:
            evicted_keys=0
            last_pressure_detail={}
            async def sample_pressure(self,*args,**kwargs):return ComponentPressure(PressureState.SAFE,time.monotonic_ns(),'test')
        sampler=PressureSampler(caches={'new':Client()},database=Client(),key='key',interval_seconds=.01,timeout_seconds=.01,on_round=AsyncMock(),maximum_rounds=100,stop_at_ns=time.monotonic_ns()+25_000_000)
        await sampler.start();await asyncio.sleep(.06)
        self.assertTrue(sampler._task.done())
        self.assertTrue(all(r['started_ns']<sampler.stop_at_ns for r in sampler.rounds))
        await sampler.close()
