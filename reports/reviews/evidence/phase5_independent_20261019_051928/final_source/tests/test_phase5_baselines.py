import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cache_scaleout.baselines import *
from cache_scaleout.contracts import *
from cache_scaleout.dataset import StableOwnershipMap,create_dataset
from cache_scaleout.migration import BoundedMigrationScheduler
from cache_scaleout.observations import BoundedDemandTracker,ResidencyTracker
from cache_scaleout.phase5 import load_config,parameters,stability_windows
from cache_scaleout.policy_observations import PressureClassifier
from cache_scaleout.telemetry import InMemoryMetricsSink
from test_phase3_behavior import FakeCache,FakeDatabase,retry


def observation(end=2_000_000_000,states=None,epoch=0,pressure=PressureState.SAFE):
    now=end+1
    demand=DemandSnapshot(ObservationWindow(end-1_000_000_000,end,now,1_000_000_000),(),10,20,16,{})
    states=states or {1:BucketState.ELIGIBLE,2:BucketState.ELIGIBLE,3:BucketState.ELIGIBLE}
    return ControllerObservation(now,demand,1.,*[ComponentPressure(pressure,end,'test') for _ in range(3)],
        {b:CoverageEstimate(1,0,0,0,0,now,'new',demand.window.start_ns,end) for b in states},states,epoch,
        {b:2. for b in states},{b:0. for b in states},0.,end,1_000_000_000,'new',{b:0. for b in states},2.)


def params(**changes):
    rates={d:20. if not d.endswith('bytes') else 20000. for d in DIMENSIONS};rates['background_db_operations']=2.
    p=BaselineParameters(500_000_000,rates,rates,{d:v/2 for d,v in rates.items()},2,.5,20.,2.,0,500_000_000,1,2,2)
    return replace(p,**changes)


def step(c,o,now=None):
    a=c.decide(o,decided_at_ns=now or o.observed_at_ns);c.commit(a);return a


class PolicyTests(unittest.TestCase):
    def test_all_six_and_forbidden_joint(self):
        self.assertEqual(len(BASELINES),6)
        with self.assertRaises(ValueError): BaselineController('joint_control',params(),expansion_ns=0)
        for name in BASELINES:
            c=BaselineController(name,params(),expansion_ns=0)
            a=step(c,observation())
            if name=='immediate_cutover': self.assertEqual(sum(asdict(a.budget).values())-a.budget.valid_for_ns,0)
            if c.definition.warmup_control is WarmupControl.FIXED: self.assertEqual(c.rates,c.p.fixed_rates)

    def test_deterministic_decisions_no_state_before_commit(self):
        for name in BASELINES:
            a=BaselineController(name,params(),expansion_ns=0);b=BaselineController(name,params(),expansion_ns=0)
            x=a.decide(observation(),decided_at_ns=2_000_000_001);y=b.decide(observation(),decided_at_ns=2_000_000_001)
            self.assertEqual(x,y);self.assertEqual(a.last_window,-1)

    def test_fixed_tick_blocked_no_catchup_no_leapfrog(self):
        c=BaselineController('fixed_gradual_handover',params(),expansion_ns=0)
        o=observation(states={1:BucketState.COPYING,2:BucketState.ELIGIBLE})
        self.assertEqual(step(c,o).admit_buckets,())
        self.assertEqual(step(c,replace(o,bucket_states={1:BucketState.ELIGIBLE,2:BucketState.ELIGIBLE})).admit_buckets,())
        self.assertEqual(step(c,observation(9_000_000_000)).admit_buckets,(1,))

    def test_all_at_once_waits_entire_pass_even_unknown(self):
        for name in ('migration_before_cutover','adaptive_budget_migration_before_cutover'):
            c=BaselineController(name,params(),expansion_ns=0)
            self.assertEqual(step(c,observation(states={1:BucketState.ELIGIBLE,2:BucketState.COPYING})).admit_buckets,())
            self.assertEqual(step(c,observation(3_000_000_000,pressure=PressureState.UNKNOWN)).admit_buckets,(1,2,3))

    def test_fresh_windows_ramp_reset_and_no_duplicate_grant(self):
        c=BaselineController('warmup_only_adaptation',params(),expansion_ns=0)
        step(c,observation());self.assertEqual(c.rates['donor_operations'],0)
        step(c,observation(3_000_000_000));self.assertEqual(c.rates['donor_operations'],10)
        duplicate=step(c,observation(3_000_000_000));self.assertEqual(duplicate.budget.donor_operations,0)
        self.assertEqual(c.rates['donor_operations'],10)
        o=observation(4_000_000_000)
        step(c,replace(o,donor_pressure=ComponentPressure(PressureState.UNSAFE,4_000_000_000,'pressure')))
        self.assertEqual(c.rates['donor_operations'],5)
        step(c,observation(5_000_000_000,pressure=PressureState.UNKNOWN));self.assertEqual(sum(c.rates.values()),0)
        self.assertEqual(min(c.safe.values()),0)

    def test_stale_at_decision_zeroes_adaptive_work(self):
        for state in (PressureState.SAFE,PressureState.UNKNOWN,PressureState.STALE,PressureState.UNSAFE):
            c=BaselineController('warmup_only_adaptation',params(),expansion_ns=0)
            step(c,observation());step(c,observation(3_000_000_000))
            a=step(c,observation(4_000_000_000,pressure=state),now=8_000_000_000)
            self.assertEqual(a.budget.donor_operations,0)

    def test_fixed_rates_ignore_pressure_traffic_only_does_not_adapt_rates(self):
        for name in ('fixed_gradual_handover','migration_before_cutover','traffic_only_adaptation'):
            c=BaselineController(name,params(),expansion_ns=0)
            a=step(c,observation(pressure=PressureState.UNSAFE))
            self.assertEqual(c.rates,c.p.fixed_rates)
            if name=='traffic_only_adaptation':self.assertEqual(a.admit_buckets,())

    def test_pending_reserve_held_until_window_start_after_cutover(self):
        p=params(safe_total_db_rate=9.,max_foreground_attempts=1)
        c=BaselineController('traffic_only_adaptation',p,expansion_ns=0)
        step(c,observation());a=step(c,observation(2_500_000_000));self.assertEqual(a.admit_buckets,(1,))
        self.assertEqual(c.pending[1][0],2.)
        b=step(c,observation(3_000_000_000,states={1:BucketState.NEW,2:BucketState.ELIGIBLE,3:BucketState.ELIGIBLE}))
        self.assertEqual(b.admit_buckets,())
        step(c,observation(4_000_000_000,states={1:BucketState.NEW,2:BucketState.ELIGIBLE,3:BucketState.ELIGIBLE}))
        self.assertNotIn(1,c.pending)

    def test_retry_aware_positive_difference_and_zero_cap(self):
        self.assertEqual(incremental_foreground_db_rate(5,.2,1,max_foreground_attempts=2,old_owner_db_rate_lower=3),7)
        self.assertEqual(incremental_foreground_db_rate(1,1,0,max_foreground_attempts=2,old_owner_db_rate_lower=3),0)
        c=BaselineController('traffic_only_adaptation',params(admission_cap=0),expansion_ns=0)
        step(c,observation());self.assertFalse(step(c,observation(3_000_000_000)).admit_buckets)

    def test_decision_rejects_future(self):
        c=BaselineController('immediate_cutover',params(),expansion_ns=0)
        with self.assertRaises(ValueError):c.decide(observation(),decided_at_ns=1)

    def test_open_subwindow_does_not_evict_closed_evidence(self):
        t=BoundedDemandTracker(subwindow_ns=10,retained_subwindows=2,max_total_keys=2,max_keys_per_bucket=2,max_buckets=1,max_age_ns=20,reserve_open_subwindow=True)
        t.register({0:{'a':1}})
        for at in (1,11,21):t.observe('a',0,1,at_ns=at)
        self.assertEqual(t.snapshot(start_ns=0,end_ns=20,observed_at_ns=21).entries[0].request_count,2)
        self.assertEqual(len(t._slots),3)

    def test_stability_inconclusive_and_wrong_routing(self):
        kw=dict(affected=(1,),destination='new',final_ns=10,final_epoch=2,deadline=50,width=10,required=2,minimum=1)
        self.assertIsNone(stability_windows([],**kw)[1])
        rows=[{'submitted_ns':t,'route':{'bucket':1,'owner':'new','epoch':2},'outcome':'timed_out'} for t in (11,21)]
        self.assertEqual(stability_windows(rows,**kw)[1],30)
        rows[0]['route']['owner']='old'
        with self.assertRaises(ValueError):stability_windows(rows,**kw)

    def test_pressure_hysteresis_and_unknown(self):
        cfg=load_config(Path(__file__).resolve().parents[1]/'configs/phase5_pilot.yaml')
        p=PressureClassifier(cfg['policy_pressure'])
        self.assertEqual(p.classify('db',None,observed_ns=1,real_rows=[],rate=0).state,PressureState.UNKNOWN)
        self.assertEqual(p.classify('db',{'probe_ms':50,'foreground_waiting':0,'background_waiting':0},observed_ns=2,real_rows=[],rate=0).state,PressureState.SAFE)
        self.assertEqual(p.classify('db',{'probe_ms':120,'foreground_waiting':0,'background_waiting':0},observed_ns=3,real_rows=[],rate=0).state,PressureState.SAFE)
        self.assertEqual(p.classify('db',{'probe_ms':180,'foreground_waiting':0,'background_waiting':0},observed_ns=4,real_rows=[],rate=0).state,PressureState.UNSAFE)
        self.assertEqual(p.classify('db',{'probe_ms':120,'foreground_waiting':0,'background_waiting':0},observed_ns=5,real_rows=[],rate=0).state,PressureState.UNSAFE)


class MigrationPolicyTests(unittest.IsolatedAsyncioTestCase):
    def system(self):
        d=create_dataset(seed=7,key_count=48,value_bytes=64)
        m=StableOwnershipMap(mapping_seed=2026,bucket_count=16,old_nodes=('old-1','old-2'),final_nodes=('old-1','old-2','new'),destination='new')
        caches={n:FakeCache(n) for n in m.final_nodes}; db=FakeDatabase({i.key:i.cache_value() for i in d.items})
        s=BoundedMigrationScheduler(run_id='test',ownership=m,donor_caches=caches,destination_cache=caches['new'],database=db,metrics=InMemoryMetricsSink(),
            residency=ResidencyTracker(destination='new',registered_keys=tuple(i.key for i in d.items)),worker_limit=1,queue_limit=8,max_buffered_payload_bytes=128,donor_retry=retry(2),db_retry=retry(2),write_retry=retry(2),attempt_timeout_seconds=.2)
        return d,m,caches,db,s

    async def test_stale_action_installs_neither_map_nor_grant(self):
        d,m,caches,db,s=self.system(); c=BaselineController('immediate_cutover',params(),expansion_ns=0)
        states=dict(m.snapshot.states);o=observation(states=states)
        a=c.decide(o,decided_at_ns=o.observed_at_ns)
        m.publish((BucketAdvance(m.affected_buckets[0],BucketState.OLD,(BucketState.COPYING,)),),expected_epoch=0)
        with self.assertRaises(ValueError): install_action(m,s,c,a,clock=lambda:a.decided_at_ns)
        self.assertEqual(s.grants.last_decided_at_ns,-1);self.assertEqual(c.last_window,-1)

    async def test_atomic_immediate_installs_zero_grants(self):
        d,m,caches,db,s=self.system();c=BaselineController('immediate_cutover',params(),expansion_ns=0)
        o=observation(states=dict(m.snapshot.states));a=c.decide(o,decided_at_ns=o.observed_at_ns)
        install_action(m,s,c,a,clock=lambda:a.decided_at_ns)
        self.assertTrue(all(v is BucketState.NEW for v in m.snapshot.states.values()));self.assertEqual(m.snapshot.epoch,1)
        self.assertEqual(s.grants.remaining_donor_operations,0)

    async def test_missing_donor_disabled_fallback_and_zero_budget_are_finite(self):
        d,m,caches,db,s=self.system();item=next(i for i in d.items if m.bucket_for_key(i.key) in m.affected_buckets)
        now=time.monotonic_ns();s.apply_action(ControllerAction(now,TransferBudget(2,4096,0,2,100_000_000,4096),(),('test',),0,now))
        results=await s.migrate((item,),deadline_ns=now+60_000_000,allow_db_fallback=False)
        self.assertEqual(results[0].disposition,'not_warmed');self.assertEqual(db.warmup_calls,0)
        d,m,caches,db,s=self.system()
        now=time.monotonic_ns();s.apply_action(ControllerAction(now,TransferBudget(0,0,0,0,100_000_000,0),(),('zero',),0,now))
        r=await s.migrate((item,),deadline_ns=now+20_000_000)
        self.assertEqual(r[0].attempts,0);self.assertEqual(s._buffered_bytes,0)

    async def test_retry_and_fallback_explicit_no_refund_and_order_callback(self):
        d,m,caches,db,s=self.system();items=tuple(i for i in d.items if m.bucket_for_key(i.key) in m.affected_buckets)[:2]
        caches[str(m.old_owner(m.bucket_for_key(items[0].key)))].read_failures=[ConnectionError('transient')]
        now=time.monotonic_ns();s.apply_action(ControllerAction(now,TransferBudget(10,20000,10,10,1_000_000_000,20000),(),('test',),0,now))
        order=[]
        results=await s.migrate(items,deadline_ns=now+500_000_000,order_key=lambda i:str(i.key),on_result=lambda r:order.append(r.key))
        self.assertTrue(all(r.disposition=='warmed' for r in results));self.assertEqual(db.warmup_calls,2)
        self.assertEqual(s.grants.charged['donor_operations'],3);self.assertEqual(s.grants.charged['background_db_operations'],2)
        self.assertEqual(len(order),2)

class ExpiryRegression(unittest.IsolatedAsyncioTestCase):
    async def test_redis_millisecond_uncertainty_is_charged_with_high_resolution_python(self):
        from unittest.mock import patch,AsyncMock
        from types import SimpleNamespace
        from cache_scaleout.adapters import RedisCacheAdapter,PressureLimits
        c=RedisCacheAdapter(node_id='new',host='127.0.0.1',port=16381,namespace='test',max_connections=1,socket_timeout_seconds=1,pressure_limits=PressureLimits(100))
        c._client.set=AsyncMock(return_value=True)
        async def fake_run(deadline,operation,kind): return await operation
        c._run=fake_run
        with patch('cache_scaleout.adapters.time.monotonic_ns',return_value=2_000_000_000),patch('cache_scaleout.adapters.time.time_ns',return_value=1_000_000_000_000),patch('cache_scaleout.adapters.time.get_clock_info',return_value=SimpleNamespace(resolution=1e-9)):
            receipt=await c.write('key',CacheValue(b'value',3_000_000_000),deadline_ns=4_000_000_000)
        self.assertLessEqual(c._client.set.call_args.kwargs['pxat'],1_000_999)
        self.assertLess(receipt.valid_until_ns,2_999_000_000)
        await c.close()


class CoverageDecisionExpiry(unittest.TestCase):
    def test_positive_coverage_expires_between_collection_and_decision(self):
        c=BaselineController('traffic_only_adaptation',params(safe_windows=1,safe_total_db_rate=7.,max_foreground_attempts=1),expansion_ns=0)
        o=observation()
        coverage={b:replace(v,observed_requests=0,confirmed_warm_requests=0) for b,v in o.bucket_coverage.items()}
        # A zero-cost fully warmed request window is replaced with one hot key.
        demand=replace(o.demand,entries=tuple(KeyDemand(str(b),b,10,64,o.demand.window.start_ns) for b in o.bucket_states))
        coverage={b:CoverageEstimate(1,1,10,10,0,o.observed_at_ns,'new',demand.window.start_ns,demand.window.end_ns) for b in o.bucket_states}
        o=replace(o,demand=demand,bucket_coverage=coverage,coverage_valid_until_ns={b:o.observed_at_ns+10 for b in o.bucket_states})
        a=c.decide(o,decided_at_ns=o.observed_at_ns+11)
        self.assertEqual(a.admit_buckets,())

    def test_duplicate_unsafe_observation_revokes_without_ramping(self):
        c=BaselineController('warmup_only_adaptation',params(safe_windows=1),expansion_ns=0)
        step(c,observation());self.assertGreater(c.rates['donor_operations'],0)
        a=step(c,observation(pressure=PressureState.UNKNOWN))
        self.assertIn('duplicate_window_revoke_unsafe',a.reason_codes)
        self.assertEqual(sum(c.rates.values()),0)
