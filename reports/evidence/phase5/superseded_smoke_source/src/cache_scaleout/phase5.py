"""Matched actual-client Phase 5 runs through the reviewed shared mechanisms."""
from __future__ import annotations
import argparse
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
import math
import os
from pathlib import Path
import time

import yaml
from .baselines import BaselineController, BaselineParameters, BASELINES, DIMENSIONS, install_action
from .contracts import (BucketAdvance, BucketState, EventKind, EventPhase, ResourceLimits, json_record)
from .evidence import ROOT, source_fingerprint, utc_now, write_json
from .issuance import issuing
from .load import sleep_until_ns
from .migration import BoundedMigrationScheduler
from .observations import BoundedDemandTracker, ResidencyTracker
from .phase4 import (_open_environment, _prepare_measurement, _close, _resource_snapshot,
    _git_state, _seal_run, _retry, _event, _percentile, _window_summary, select_workload, ReviewMetrics)
from .policy_observations import ObservationBuilder
from .router import CacheAsideRouter
from .sampling import PressureSampler
from .telemetry import reconcile_offers


class LiveMetrics(ReviewMetrics):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs); self.request_rows=[]
    async def emit_request(self,record,*,deadline_ns):
        if len(self.request_rows)>=self.queue.maxsize: raise BufferError('bounded request history full')
        self.request_rows.append(json_record(record))
        await super().emit_request(record,deadline_ns=deadline_ns)


def load_config(path):
    c=yaml.safe_load(path.read_text())
    dt=c['timing']['observation_interval_seconds']; p=c['policy']; t=c['timing']
    for n in ('measurement_horizon_seconds','task_lifetime_seconds','handover_deadline_seconds','observation_interval_seconds','observation_timeout_seconds','request_timeout_seconds','stability_subwindow_seconds'):
        if not isinstance(t[n],(float,int)) or not 0<t[n]<90: raise ValueError('invalid finite timing: '+n)
    if t['measurement_horizon_seconds']<t['expansion_at_seconds']+t['handover_deadline_seconds']+t['request_timeout_seconds']:
        raise ValueError('measurement horizon must include deadline and request allowance')
    if t['expansion_at_seconds']<max(p['safe_windows'],p['demand_windows'])*dt:
        raise ValueError('insufficient pre-event rounds')
    for name in ('signal_max_age_seconds','demand_max_age_seconds','residency_max_age_seconds','alpha','foreground_margin','old_lower_margin','cold_reserve_per_bucket'):
        if isinstance(p[name],bool) or not math.isfinite(p[name]) or p[name]<0: raise ValueError('invalid policy bound '+name)
    if p['alpha']<1: raise ValueError('alpha must be >=1')
    if p['ordering'] not in ('fifo_hash','demand','recency'): raise ValueError('unknown ordering')
    if p['safe_windows']<1 or p['demand_windows']<1: raise ValueError('positive window counts')
    if c['resources']['max_buffered_payload_bytes']<c['dataset']['value_bytes']: raise ValueError('object exceeds buffer')
    bound=c['dataset']['value_bytes']+1024
    for d in DIMENSIONS:
        if type(c['bursts'][d]) is not int or c['bursts'][d]<(bound if d.endswith('bytes') else 1): raise ValueError('impossible burst '+d)
    ResourceLimits(**c['resources'])
    for n in c['retries']: _retry(c,n)
    return c


def parameters(c, setting, total):
    s=c['settings'][setting]; p=c['policy']
    return BaselineParameters(int(c['timing']['observation_interval_seconds']*1e9),s['fixed_rates'],s['ceilings'],s['increments'],
        p['safe_windows'],p['unsafe_donor_multiplier'],total,p['reserve_db_rate'],int(p['fixed_origin_seconds']*1e9),
        int(s['fixed_interval_seconds']*1e9),s['fixed_count'],s['admission_cap'],c['retries']['foreground_database']['max_attempts'])


def stability_windows(requests, *, affected, destination, final_ns, final_epoch, deadline, width, required, minimum):
    windows=[]; streak=0; success=None
    if final_ns is None: return windows,success
    begin=final_ns
    while begin+width<=deadline:
        rows=[r for r in requests if r['submitted_ns'] is not None and begin<=r['submitted_ns']<begin+width and r['route']['bucket'] in affected]
        correct=all(r['route']['owner']==destination and r['route']['epoch']>=final_epoch for r in rows)
        if not correct: raise ValueError('wrong owner after final publication')
        valid=len(rows)>=minimum
        streak=streak+1 if valid else 0
        windows.append({'start_ns':begin,'end_ns':begin+width,'submitted_affected':len(rows),'completed_affected':sum(r['outcome']=='completed' for r in rows),
            'destination_share':1. if rows else None,'expected_share':1. if rows else None,'valid':valid,
            'reason':'actual_traffic_stable' if valid else 'traffic_stability_inconclusive'})
        if streak>=required and success is None: success=begin+width
        begin+=width
    return windows,success


async def run(c,config_path,run_id,policy,setting,*,seed,total_db_rate=None,boundary=None,mixed_foreground=None,stage='smoke'):
    if not run_id or Path(run_id).name!=run_id: raise ValueError('safe fresh run ID required')
    c=json.loads(json.dumps(c)); c['dataset']['seed']=seed
    if mixed_foreground is None and (total_db_rate is None or total_db_rate<=0): raise ValueError('validated mixed-pool total required')
    if boundary=='zero':
        for group in ('fixed_rates','ceilings','increments'):
            c['settings'][setting][group]=dict.fromkeys(DIMENSIONS,0.)
        c['policy']['allow_db_fallback']=False
    if boundary=='deadline':
        c['timing']['handover_deadline_seconds']=.8
    c['policy']['safe_total_db_rate']=total_db_rate
    directory=ROOT/'runs'/run_id
    metrics=LiveMetrics(directory,capacity=c['resources']['max_pending_metric_records']); await metrics.start()
    caches=database=sampler=None; tasks=[]; actions=[]; pass_results=[]; transitions=[]; payload=[]
    initial_ns=time.monotonic_ns(); origin=None; pass_task=None
    try:
        dataset,ownership,caches,database,services,initial=await _open_environment(c,run_id,require_empty=True)
        warm=await _prepare_measurement(c,dataset,ownership,caches,database)
        write_json(directory/'warm_stability.json',warm)
        write_json(directory/'effective_config.json',c); write_json(directory/'source.json',source_fingerprint())
        write_json(directory/'manifest.json',{'schema_version':5,'run_id':run_id,'kind':'mixed_pool' if mixed_foreground else 'baseline',
            'policy':policy,'setting':setting,'stage':stage,'boundary':boundary,'seed':seed,'started_utc':utc_now(),
            'git':_git_state(),'source_fingerprint':source_fingerprint()['aggregate_sha256'],
            'config_path':str(config_path),'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(),
            'initial_service_state':services,'initial_logical_state':initial,'phase3_diagnostics_enabled':False,
            'retry_of':os.environ.get('PAPER2_RETRY_OF')})
        resources_before=await _resource_snapshot()
        origin=time.monotonic_ns(); timing=c['timing']; dt=int(timing['observation_interval_seconds']*1e9)
        expansion=origin+int(timing['expansion_at_seconds']*1e9)
        deadline=expansion+int(timing['handover_deadline_seconds']*1e9)
        horizon=origin+int(timing['measurement_horizon_seconds']*1e9)
        grouped=ownership.keys_by_bucket(dataset); by_key=dataset.by_key()
        affected=[i for b in ownership.affected_buckets for i in grouped[b]]
        if not affected: raise ValueError('no affected dataset keys')
        tracker=BoundedDemandTracker(subwindow_ns=dt,retained_subwindows=c['policy']['demand_windows'],max_total_keys=len(dataset.items),
            max_keys_per_bucket=len(dataset.items),max_buckets=ownership.bucket_count,max_age_ns=int(c['policy']['demand_max_age_seconds']*1e9),origin_ns=origin,reserve_open_subwindow=True)
        tracker.register({b:{i.key:i.object_bytes for i in items} for b,items in grouped.items()})
        residency=ResidencyTracker(destination=c['routing']['destination'],registered_keys=tuple(i.key for i in affected))
        router=CacheAsideRouter(run_id=run_id,ownership=ownership,caches=caches,database=database,demand_tracker=tracker,metrics=metrics,
            limits=ResourceLimits(**c['resources']),cache_retry=_retry(c,'foreground_cache'),db_retry=_retry(c,'foreground_database'),
            fill_write_retry=_retry(c,'foreground_fill_write'),cleanup_timeout_seconds=timing['cleanup_timeout_seconds'],residency=residency)
        scheduler=BoundedMigrationScheduler(run_id=run_id,ownership=ownership,donor_caches={n:caches[n]._phase4_observer for n in c['routing']['old_nodes']},
            destination_cache=caches[c['routing']['destination']]._phase4_observer,database=database,metrics=metrics,residency=residency,
            worker_limit=c['resources']['migration_workers'],queue_limit=c['resources']['max_pending_migration_tasks'],max_buffered_payload_bytes=c['resources']['max_buffered_payload_bytes'],
            donor_retry=_retry(c,'donor_read'),db_retry=_retry(c,'warmup_database'),write_retry=_retry(c,'destination_write'),attempt_timeout_seconds=1.,
            rates=dict.fromkeys(DIMENSIONS,0.),bursts=c['bursts'],max_operation_records=c['resources']['max_pending_metric_records'])
        builder=ObservationBuilder(c,origin=origin,ownership=ownership,tracker=tracker,residency=residency,registry=grouped)
        async def event(kind,reason,detail):
            e=_event(run_id,origin,EventPhase.HANDOVER,int(ownership.snapshot.epoch),kind,reason,detail)
            await metrics.emit_event(e,deadline_ns=time.monotonic_ns()+1_000_000_000)
        async def observe(row): await event(EventKind.OBSERVATION,'common_pressure_round',row)
        sampler=PressureSampler(caches={n:v._phase4_observer for n,v in caches.items()},database=database,key=dataset.items[0].key,
            interval_seconds=timing['observation_interval_seconds'],timeout_seconds=timing['observation_timeout_seconds'],on_round=observe,residency=residency,maximum_rounds=64)
        await sampler.start()
        cpu_start=time.process_time()
        mixed_ops=[]
        if mixed_foreground is not None:
            # Independently scheduled ACTUAL foreground and warm-up queries share
            # the one-CPU DB and distinct 4/1 pools with the same probes.
            schedule=[]
            for cls,rate in [('foreground_database',mixed_foreground),('discretionary_database_warmup',2)]:
                for i in range(int(rate*8)):
                    schedule.append({'request_id':f'{cls}-{i:04d}','key':str(dataset.items[i%len(dataset.items)].key),
                        'work_class':cls,'scheduled_arrival_ns':origin+int((.5+i/rate)*1e9)})
            schedule.sort(key=lambda r:(r['scheduled_arrival_ns'],r['request_id']))
            write_json(directory/'offered_schedule.json',{'origin_ns':origin,'requests':schedule})
            async def query(offer):
                await sleep_until_ns(offer['scheduled_arrival_ns']); await event(EventKind.ARRIVAL_SCHEDULED,'mixed_offer',offer)
                row={**offer,'submitted_ns':time.monotonic_ns(),'issued_ns':None,'terminal_ns':None,'outcome':'failed','payload_ok':False}
                def issue(): row['issued_ns']=time.monotonic_ns()
                try:
                    with issuing(issue):
                        value=await (database.read_foreground(offer['key'],deadline_ns=offer['scheduled_arrival_ns']+1_000_000_000) if offer['work_class']=='foreground_database'
                            else database.read_for_warmup(offer['key'],deadline_ns=offer['scheduled_arrival_ns']+1_000_000_000))
                    row.update(outcome='completed',payload_ok=value.payload==by_key[offer['key']].payload)
                except TimeoutError: row['outcome']='timed_out'
                finally:
                    row['terminal_ns']=time.monotonic_ns(); mixed_ops.append(row)
            tasks=[asyncio.create_task(query(o)) for o in schedule]
            await sleep_until_ns(horizon); await asyncio.gather(*tasks)
            await sampler.close()
            summaries={}
            for cls in ('foreground_database','discretionary_database_warmup'):
                rows=[r for r in mixed_ops if r['work_class']==cls]
                summaries[cls]={'offered':len(rows),'issued':sum(r['issued_ns'] is not None for r in rows),
                    'completed':sum(r['outcome']=='completed' for r in rows),'p95_ms':_percentile([(r['terminal_ns']-r['scheduled_arrival_ns'])/1e6 for r in rows],.95),
                    'max_dispatch_ms':max((r['submitted_ns']-r['scheduled_arrival_ns'])/1e6 for r in rows), 'payloads_ok':all(r['payload_ok'] for r in rows)}
            eligible=all(s['offered']==s['issued']==s['completed'] and s['payloads_ok'] and s['p95_ms']<=100 and s['max_dispatch_ms']<=50 for s in summaries.values())
            result={'mixed_summaries':summaries,'eligible':eligible,'nominal_total_attempt_rate':mixed_foreground+4,'operations':mixed_ops}
        else:
            count=int(c['workload']['offered_rate']*(timing['measurement_horizon_seconds']-.5))
            selected=select_workload(affected,[i for i in dataset.items if ownership.bucket_for_key(i.key) not in ownership.affected_buckets],count,c['workload']['affected_share'],c['workload']['zipf_exponent'],seed)
            schedule=[{'request_id':f'app-{i:05d}','key':str(item.key),'scheduled_arrival_ns':origin+int((.5+i/c['workload']['offered_rate'])*1e9)} for i,item in enumerate(selected)]
            write_json(directory/'offered_schedule.json',{'origin_ns':origin,'requests':schedule})
            async def one(o):
                await sleep_until_ns(o['scheduled_arrival_ns']); await event(EventKind.ARRIVAL_SCHEDULED,'open_loop_offer',o)
                item=by_key[o['key']]
                response=await router.read(request_id=o['request_id'],key=item.key,scheduled_arrival_ns=o['scheduled_arrival_ns'],timeout_seconds=timing['request_timeout_seconds'],object_bytes=item.object_bytes)
                payload.append({'request_id':o['request_id'],'actual':hashlib.sha256(response.value.payload).hexdigest() if response.value else None,'expected':hashlib.sha256(item.payload).hexdigest()})
            tasks=[asyncio.create_task(one(o)) for o in schedule]
            controller=BaselineController(policy,parameters(c,setting,total_db_rate),expansion_ns=expansion)
            remaining={b:len(grouped[b]) for b in ownership.affected_buckets}
            terminal_by_bucket={b:[] for b in remaining}
            pass_task=None; final_ns=None; final_epoch=None
            def terminal(result):
                pass_results.append(asdict(result)); remaining[result.bucket]-=1; terminal_by_bucket[result.bucket].append(result.key)
            async def transition(advances,why):
                expected=ownership.snapshot.epoch; epoch=ownership.publish(tuple(advances),expected_epoch=expected)
                row={'at_ns':time.monotonic_ns(),'expected_epoch':expected,'epoch':epoch,'advances':[json_record(a) for a in advances],'reason':why}
                transitions.append(row); await event(EventKind.BUCKET_TRANSITION,why,row)
            next_tick=expansion
            await sleep_until_ns(next_tick)
            if policy!='immediate_cutover':
                await transition([BucketAdvance(b,BucketState.OLD,(BucketState.COPYING,)) for b in ownership.affected_buckets],'finite_pass_start')
            while time.monotonic_ns()<deadline:
                now=time.monotonic_ns()
                if policy!='immediate_cutover':
                    done=[b for b in remaining if remaining[b]==0 and ownership.state(b) is BucketState.COPYING]
                    if 'migration_before_cutover' in policy and any(remaining.values()): done=[]
                    if done: await transition([BucketAdvance(b,BucketState.COPYING,(BucketState.ELIGIBLE,)) for b in done],'bucket_pass_terminal_not_residency')
                now=time.monotonic_ns()
                o=builder.build(now,foreground_operations=router.ledger.records,terminal_requests=metrics.request_rows,
                    migration_operations=scheduler.operation_records,rounds=sampler.rounds,probe_records=database.probe_records)
                a=controller.decide(o,decided_at_ns=time.monotonic_ns()); before=ownership.snapshot.epoch
                # The grant and published map install without any interleaving.
                install_action(ownership,scheduler,controller,a)
                row={'action':json_record(a),'observation':json_record(o),'detail':controller.last_detail,'installed_epoch':ownership.snapshot.epoch}
                actions.append(row); await event(EventKind.POLICY_ACTION,';'.join(a.reason_codes),row)
                if before!=ownership.snapshot.epoch:
                    transitions.append({'at_ns':a.decided_at_ns,'expected_epoch':before,'epoch':ownership.snapshot.epoch,
                        'admit':list(a.admit_buckets),'reason':';'.join(a.reason_codes)})
                if pass_task is None and policy!='immediate_cutover':
                    pass_task=asyncio.create_task(scheduler.migrate(tuple(affected),deadline_ns=min(deadline,expansion+int(timing['task_lifetime_seconds']*1e9)),
                        allow_db_fallback=c['policy']['allow_db_fallback'],order_key=builder.order_key,on_result=terminal))
                if pass_task is not None and pass_task.done(): await pass_task
                if final_ns is None and all(s is BucketState.NEW for s in ownership.snapshot.states.values()):
                    final_ns=time.monotonic_ns(); final_epoch=ownership.snapshot.epoch
                next_tick+=dt
                if next_tick<time.monotonic_ns(): next_tick=origin+((time.monotonic_ns()-origin)//dt+1)*dt
                await sleep_until_ns(min(next_tick,deadline))
            if pass_task is not None: await pass_task
            # Expired actions cannot authorize work beyond the common deadline.
            await sleep_until_ns(horizon); await asyncio.gather(*tasks); await router.finalize_requests(); await sampler.close()
            windows,success=stability_windows(metrics.request_rows,affected=ownership.affected_buckets,destination=c['routing']['destination'],
                final_ns=final_ns,final_epoch=final_epoch,deadline=deadline,width=int(timing['stability_subwindow_seconds']*1e9),required=timing['stability_subwindows'],minimum=timing['stability_min_requests'])
            result={'status':'completed' if success else 'policy_failure','terminal_reason':'actual_traffic_stable' if success else 'handover_timeout',
                'expansion_ns':expansion,'deadline_ns':deadline,'final_publication_ns':final_ns,'final_epoch':final_epoch,
                'success_ns':success,'handover_seconds':(success-expansion)/1e9 if success else None,'stability':windows,
                'summary':_window_summary(metrics.request_rows,origin,horizon,timing['latency_target_ms']),
                'actions':actions,'transitions':transitions,'pass_results':pass_results,'migration_operations':scheduler.operation_records,
                'grant_summary':scheduler.grants.summary(),'foreground_operations':router.ledger.records,'payload_checks':payload,
                'bounds':{'maximum_inflight':router.maximum_inflight,'maximum_coalesced_keys':router.maximum_coalesced_keys,'remaining_fills':router.coalesced_key_count,
                    'migration_workers':scheduler.maximum_workers,'remaining_workers':scheduler._active_workers,'maximum_buffered_bytes':scheduler.maximum_buffered_bytes,'remaining_buffered_bytes':scheduler._buffered_bytes,'maximum_queue_depth':scheduler.maximum_queue_depth}}
        await metrics.close(deadline_ns=time.monotonic_ns()+5_000_000_000)
        result.update(measurement_origin_ns=origin,measurement_ended_ns=time.monotonic_ns(),horizon_ns=horizon,
            preparation_seconds=(origin-initial_ns)/1e9,process_cpu_seconds=time.process_time()-cpu_start,
            observations=sampler.rounds,db_probes=database.probe_records,cache_probes={n:client._phase4_observer.probe_records for n,client in caches.items()},
            database_pool=database.pool_summary(),cache_pools={n:{'foreground_max':v._limit.maximum,'background_max':v._phase4_observer._limit.maximum} for n,v in caches.items()},
            resources={'before':resources_before,'after':await _resource_snapshot()},diagnostic_operations=0)
        if database.pool_summary()['issuance_stopped'] or database.pool_summary()['quarantined_operations']: raise RuntimeError('DB cleanup/issuance failure')
        write_json(directory/'result.json',result)
        status=result.get('status','completed')
        write_json(directory/'status.json',{'status':status,'ended_utc':utc_now()}); _seal_run(directory)
        return 0 if status=='completed' else 1
    except BaseException as error:
        if pass_task is not None and not pass_task.done(): pass_task.cancel()
        if pass_task is not None: await asyncio.gather(pass_task,return_exceptions=True)
        for task in tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        try: await metrics.close(deadline_ns=time.monotonic_ns()+1_000_000_000)
        except Exception: pass
        write_json(directory/'status.json',{'status':'invalid_measurement','error':repr(error),'ended_utc':utc_now()})
        raise
    finally:
        if sampler is not None: await sampler.close()
        if caches is not None: await _close(caches,database)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=ROOT/'configs/phase5_pilot.yaml');p.add_argument('--run-id',required=True)
    p.add_argument('--policy',choices=BASELINES,default='immediate_cutover');p.add_argument('--setting',choices=('A','B'),default='A')
    p.add_argument('--seed',type=int,default=606);p.add_argument('--total-db-rate',type=float);p.add_argument('--mixed-foreground',type=float)
    p.add_argument('--boundary',choices=('zero','deadline'));p.add_argument('--stage',default='smoke')
    a=p.parse_args();return asyncio.run(run(load_config(a.config),a.config,a.run_id,a.policy,a.setting,seed=a.seed,total_db_rate=a.total_db_rate,boundary=a.boundary,mixed_foreground=a.mixed_foreground,stage=a.stage))

if __name__=='__main__': raise SystemExit(main())
