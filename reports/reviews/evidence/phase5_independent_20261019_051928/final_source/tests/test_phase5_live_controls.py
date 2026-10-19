"""Actual-client functional control cases with donor misses, not comparisons."""
import asyncio
from dataclasses import asdict,replace
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import test_phase5_baselines as fixture
from cache_scaleout.adapters import RedisCacheAdapter,PostgresDatabaseAdapter,PressureLimits
from cache_scaleout.baselines import BaselineController,BaselineParameters,BASELINES,DIMENSIONS,install_action
from cache_scaleout.contracts import BucketAdvance,BucketState,DataSource,ResourceLimits,RetryPolicy,json_record
from cache_scaleout.dataset import create_dataset,StableOwnershipMap
from cache_scaleout.migration import BoundedMigrationScheduler
from cache_scaleout.observations import ResidencyTracker,BoundedDemandTracker
from cache_scaleout.router import CacheAsideRouter
from cache_scaleout.telemetry import InMemoryMetricsSink


@unittest.skipUnless(os.environ.get('PAPER2_INTEGRATION')=='1','requires disposable live Redis/PostgreSQL')
class ActualControlExecution(unittest.IsolatedAsyncioTestCase):
    async def exercise(self,policy):
        namespace='p5-live-'+uuid.uuid4().hex
        ownership=StableOwnershipMap(mapping_seed=2026,bucket_count=16,old_nodes=('old-1','old-2'),final_nodes=('old-1','old-2','new'),destination='new')
        dataset=create_dataset(seed=777,key_count=32,value_bytes=64)
        items=tuple(i for i in dataset.items if ownership.bucket_for_key(i.key) in ownership.affected_buckets)
        self.assertGreater(len(items),1)
        caches={n:RedisCacheAdapter(node_id=n,host='127.0.0.1',port=port,namespace=namespace,max_connections=8,socket_timeout_seconds=1,pressure_limits=PressureLimits(1000),is_destination=n=='new') for n,port in zip(ownership.final_nodes,(16379,16380,16381))}
        background={n:RedisCacheAdapter(node_id=n,host='127.0.0.1',port=port,namespace=namespace,max_connections=1,socket_timeout_seconds=1,pressure_limits=PressureLimits(1000),is_destination=n=='new') for n,port in zip(ownership.final_nodes,(16379,16380,16381))}
        database=PostgresDatabaseAdapter(connection_kwargs={'host':'127.0.0.1','port':15432,'dbname':'paper2_research','user':'paper2_research','password':os.environ.get('PAPER2_DB_PASSWORD','paper2-disposable-local-only'),'connect_timeout':2},foreground_max_size=4,background_max_size=1,pool_timeout_seconds=2,statement_timeout_ms=1500,pressure_latency_upper_ms=1000,query_cpu_rounds=20000)
        task=None
        try:
            await database.open();await database.prepare_dataset(dataset.items,deadline_ns=time.monotonic_ns()+5_000_000_000)
            first=items[0];await caches[str(ownership.old_owner(ownership.bucket_for_key(first.key)))].write(first.key,first.cache_value(),deadline_ns=time.monotonic_ns()+1_000_000_000)
            sink=InMemoryMetricsSink(capacity=12000)
            residency=ResidencyTracker(destination='new',registered_keys=tuple(i.key for i in items))
            tracker=BoundedDemandTracker(subwindow_ns=1_000_000_000,retained_subwindows=4,max_total_keys=64,max_keys_per_bucket=64,max_buckets=16,max_age_ns=5_000_000_000)
            grouped=ownership.keys_by_bucket(dataset);tracker.register({b:{i.key:i.object_bytes for i in values} for b,values in grouped.items()})
            retry=RetryPolicy(2,.5,(.01,))
            scheduler=BoundedMigrationScheduler(run_id=namespace,ownership=ownership,donor_caches=background,destination_cache=background['new'],database=database,metrics=sink,residency=residency,worker_limit=1,queue_limit=64,max_buffered_payload_bytes=2048,donor_retry=retry,db_retry=retry,write_retry=retry,attempt_timeout_seconds=.5,rates=dict.fromkeys(DIMENSIONS,0.),bursts={d:2176 if d.endswith('bytes') else 2 for d in DIMENSIONS})
            router=CacheAsideRouter(run_id=namespace,ownership=ownership,caches=caches,database=database,demand_tracker=tracker,metrics=sink,limits=ResourceLimits(4,1,8,1,1,128,64,128,12000,2048),cache_retry=RetryPolicy(1,.5,()),db_retry=RetryPolicy(1,1.,()),fill_write_retry=RetryPolicy(1,.5,()),cleanup_timeout_seconds=1,residency=residency)
            rates={d:108800. if d.endswith('bytes') else 100. for d in DIMENSIONS};rates['background_db_operations']=10.
            p=BaselineParameters(100_000_000,rates,rates,rates,1,.5,16.,2.,0,100_000_000,10,10,1)
            expansion=time.monotonic_ns();controller=BaselineController(policy,p,expansion_ns=expansion)
            results=[];remaining={b:sum(ownership.bucket_for_key(i.key)==b for i in items) for b in ownership.affected_buckets}
            if policy!='immediate_cutover':ownership.publish(tuple(BucketAdvance(b,BucketState.OLD,(BucketState.COPYING,)) for b in ownership.affected_buckets),expected_epoch=0)
            def terminal(r):results.append(asdict(r));remaining[r.bucket]-=1
            actions=[]
            for tick in range(40):
                now=time.monotonic_ns()
                eligible=[b for b,v in remaining.items() if v==0 and ownership.state(b) is BucketState.COPYING]
                if 'migration_before_cutover' in policy and any(remaining.values()):eligible=[]
                if eligible:ownership.publish(tuple(BucketAdvance(b,BucketState.COPYING,(BucketState.ELIGIBLE,)) for b in eligible),expected_epoch=ownership.snapshot.epoch)
                obs=fixture.observation(end=now-1,states=dict(ownership.snapshot.states),epoch=ownership.snapshot.epoch)
                obs=replace(obs,candidate_request_rate_upper={b:0. for b in remaining},observation_db_rate_upper=0.)
                action=controller.decide(obs,decided_at_ns=time.monotonic_ns());install_action(ownership,scheduler,controller,action);actions.append(json_record(action))
                if task is None and policy!='immediate_cutover':task=asyncio.create_task(scheduler.migrate(items,deadline_ns=expansion+3_500_000_000,allow_db_fallback=True,on_result=terminal))
                if task is not None and task.done():await task
                if all(s is BucketState.NEW for s in ownership.snapshot.states.values()):break
                await asyncio.sleep(.1)
            self.assertTrue(all(s is BucketState.NEW for s in ownership.snapshot.states.values()))
            if task is not None:await task
            for index,item in enumerate(items):
                response=await router.read(request_id=f'request-{index}',key=item.key,scheduled_arrival_ns=time.monotonic_ns(),timeout_seconds=1.,object_bytes=item.object_bytes)
                self.assertIsNotNone(response.value);self.assertEqual(response.value.payload,item.payload)
                self.assertEqual(response.record.route.owner,'new')
            await router.finalize_requests()
            if policy=='immediate_cutover':self.assertFalse(scheduler.operation_records)
            else:
                self.assertTrue(all(r['disposition']=='warmed' for r in results))
                self.assertEqual(sum(o['work_class']=='discretionary_database_warmup' for o in scheduler.operation_records),len(items)-1)
                self.assertEqual(sum(o['work_class']=='donor_read' for o in scheduler.operation_records),len(items))
                self.assertEqual(sum(o['work_class']=='destination_write' for o in scheduler.operation_records),len(items))
            output=os.environ.get('PAPER2_PHASE5_LIVE_EVIDENCE_DIR')
            if output:
                destination=Path(output)/f'{policy}.json';destination.parent.mkdir(parents=True,exist_ok=True)
                if destination.exists():raise RuntimeError('fresh live test evidence path required')
                destination.write_text(json.dumps({'policy':policy,'functional_scope':'actual-client partial donor availability; no comparison/pressure/stability inference','actions':actions,'requests':[json_record(r) for r in sink.requests],'foreground_operations':router.ledger.records,'migration_operations':scheduler.operation_records,'pass_results':results,'tokens':scheduler.tokens.events,'pools':database.pool_summary()},indent=2)+'\n')
        finally:
            if task is not None and not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
            for client in (*caches.values(),*background.values()):await client.close()
            await database.close()


def case(policy):
    async def run(self):await self.exercise(policy)
    return run
for name in BASELINES:setattr(ActualControlExecution,'test_'+name,case(name))
