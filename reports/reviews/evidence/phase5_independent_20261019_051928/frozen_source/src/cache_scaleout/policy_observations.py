"""Causal, bounded Phase 5 estimators and hysteretic pressure classification."""
from collections import deque
import hashlib
import math

from .contracts import (BucketState, ComponentPressure, ControllerObservation, PressureState,
                        estimate_coverage)


class PressureClassifier:
    def __init__(self, config):
        self.config=config
        self.previous={}
        self.evictions={}

    def classify(self, name, sample, *, observed_ns, real_rows, rate, cache_raw=None, as_of_ns=None, max_age_ns=1_500_000_000):
        p=self.config
        now=observed_ns if as_of_ns is None else as_of_ns
        required=(('probe_ms','foreground_waiting','background_waiting') if name=='db' else
                  ('ping_ms','used_memory','maxmemory','evicted_keys','waiting','active'))
        valid=(sample is not None and all(k in sample and isinstance(sample[k],(int,float)) and
               not isinstance(sample[k],bool) and math.isfinite(sample[k]) and sample[k]>=0 for k in required)
               and (name=='db' or sample['maxmemory']>0))
        if not valid:
            state=PressureState.UNKNOWN; reason='missing_failed_or_invalid_probe_resource_bundle'
        else:
            probe=sample['probe_ms'] if name=='db' else sample['ping_ms']
            latencies=[((r['terminal_ns'] if r.get('terminal_ns') is not None else now)-r['issued_ns'])/1e6 for r in real_rows]
            outcomes=[r.get('outcome') for r in real_rows if r.get('terminal_ns') is not None]
            # Adapter timings include pre-issue connection/pool wait. Probe work
            # is excluded by the adapters; retain each real latency class.
            def classes(value):
                if isinstance(value,dict):
                    if all(k in value for k in ('latency_ms','outcome','observed_at_ns')):
                        if 0<=now-value['observed_at_ns']<=max_age_ns:
                            yield value
                    else:
                        for child in value.values():yield from classes(child)
            for row in classes(sample.get('real_classes',{})):
                latencies.append(row['latency_ms']);outcomes.append(row['outcome'])
            lower=p['db_probe_lower_ms'] if name=='db' else p['cache_probe_lower_ms']
            upper=p['db_probe_upper_ms'] if name=='db' else p['cache_probe_upper_ms']
            waiting=(sample['foreground_waiting']+sample['background_waiting'] if name=='db' else sample['waiting'])
            active=(sample.get('foreground_active',0)+sample.get('background_active',0) if name=='db' else sample['active'])
            active=max(active,sum(r.get('terminal_ns') is None for r in real_rows))
            fraction=sample['used_memory']/sample['maxmemory'] if name!='db' else 0
            evicted=sample.get('evicted_keys',0);increased=evicted>self.evictions.get(name,0)
            self.evictions[name]=evicted
            inflight_lower=p.get('db_inflight_lower' if name=='db' else 'cache_inflight_lower',1000000)
            inflight_upper=p.get('db_inflight_upper' if name=='db' else 'cache_inflight_upper',1000000)
            unsafe=(probe>upper or any(o!='completed' for o in outcomes) or
                    max(latencies,default=0)>p['real_upper_ms'] or waiting>p['queue_upper'] or active>inflight_upper or
                    fraction>p['memory_upper'] or increased or (name=='db' and rate>p['db_rate_upper']))
            safe=(probe<=lower and max(latencies,default=0)<=p['real_lower_ms'] and
                  waiting<=p['queue_lower'] and active<=inflight_lower and fraction<=p['memory_lower'] and
                  not increased and (name!='db' or rate<=p['db_rate_lower']))
            state=PressureState.UNSAFE if unsafe else PressureState.SAFE if safe else self.previous.get(name,PressureState.UNKNOWN)
            reason=f'probe={probe};real_count={len(latencies)};max_real_ms={max(latencies,default=0)};queue={waiting};active={active};memory={fraction};rate={rate};eviction_delta={increased}'
        self.previous[name]=state
        return ComponentPressure(state,observed_ns,reason)


class ObservationBuilder:
    def __init__(self, config, *, origin, ownership, tracker, residency, registry):
        self.c=config; self.origin=origin; self.ownership=ownership; self.tracker=tracker
        self.residency=residency; self.registry=registry
        self.classifier=PressureClassifier(config['policy_pressure'])
        self.k=config['policy']['safe_windows']; self.dt=int(config['timing']['observation_interval_seconds']*1e9)
        self.last_end=-1; self.history=deque(maxlen=self.k)
        self.last_snapshot=None

    def build(self, now, *, foreground_operations, terminal_requests, migration_operations, rounds, probe_records):
        c=self.c; dt=self.dt
        end=self.origin+((now-self.origin)//dt)*dt
        # Preserve m closed windows while separately bounding the open subwindow.
        width=c['policy']['demand_windows']*dt
        demand=self.tracker.snapshot(start_ns=end-width,end_ns=end,observed_at_ns=now)
        fg=[r for r in foreground_operations if end-dt<=r['issued_ns']<end and r['work_class']=='foreground_database']
        requests={r['request_id']:r for r in terminal_requests}
        old={b:0 for b in self.ownership.affected_buckets}
        for op in fg:
            req=requests.get(op['request_id'])
            if req and req['route']['state']!='new' and req['route']['bucket'] in old:
                old[req['route']['bucket']]+=1
        if end>self.last_end:
            if self.last_end!=-1 and end-self.last_end!=dt:self.history.clear()
            self.history.append((len(fg)/(dt/1e9),{b:v/(dt/1e9) for b,v in old.items()}))
            self.last_end=end
        enough=len(self.history)==self.k and end-self.origin>=width
        foreground=max((h[0] for h in self.history),default=0)+c['policy']['foreground_margin']
        oldlower={b:max(0,min((h[1][b] for h in self.history),default=0)-c['policy']['old_lower_margin']) if enough else 0 for b in old}
        # Closed-round samples only; no future or partial observation bundle.
        eligible=[r for r in rounds if r['ended_ns']<=now]
        latest=eligible[-1] if eligible else None
        at=latest['ended_ns'] if latest else 0
        real=[r for r in (*foreground_operations,*migration_operations) if r['issued_ns']<=now and
              (r.get('terminal_ns') is None or end-dt<=r['terminal_ns']<=now)]
        dbreal=[r for r in real if 'database' in r['work_class']]
        all_db=len([r for r in (*foreground_operations,*migration_operations,*probe_records) if end-dt<=r['issued_ns']<end and ('database' in r['work_class'])])/(dt/1e9)
        db_at=latest.get('samples',{}).get('database',{}).get('observed_at_ns',0) if latest else 0
        db=self.classifier.classify('db',latest['raw_database_sample'] if latest else None,observed_ns=db_at,real_rows=dbreal,rate=all_db,as_of_ns=now,max_age_ns=int(c['policy']['signal_max_age_seconds']*1e9))
        pressures={}
        for node in self.c['routing']['final_nodes']:
            pressures[node]=self.classifier.classify(node,latest['raw_cache_samples'][node] if latest else None,
                observed_ns=latest.get('samples',{}).get(node,{}).get('observed_at_ns',0) if latest else 0,
                real_rows=[r for r in real if r['target_owner']==node and r['work_class'] in ('foreground_cache','donor_read','destination_write')],
                rate=0,as_of_ns=now,max_age_ns=int(c['policy']['signal_max_age_seconds']*1e9))
        donor_nodes=self.c['routing']['old_nodes']
        # Aggregate conservatively, preserving the oldest component timestamp.
        donor_state=(PressureState.UNSAFE if any(pressures[n].state is PressureState.UNSAFE for n in donor_nodes)
                     else PressureState.SAFE if all(pressures[n].state is PressureState.SAFE for n in donor_nodes) else PressureState.UNKNOWN)
        donor=ComponentPressure(donor_state,min(pressures[n].observed_at_ns for n in donor_nodes),';'.join(pressures[n].reason for n in donor_nodes))
        dest=self.c['routing']['destination']
        coverage={b:estimate_coverage(demand,self.residency.snapshot(),bucket=b,as_of_ns=now,
                    max_residency_age_ns=int(c['policy']['residency_max_age_seconds']*1e9),
                    registered_keys=tuple(i.key for i in self.registry[b]),destination=dest) for b in old}
        validity={}
        evidence=self.residency.snapshot()
        for b in old:
            bounds=[]
            for item in self.registry[b]:
                e=evidence.get(item.key)
                if e and e.is_warm(as_of_ns=now,max_observation_age_ns=int(c['policy']['residency_max_age_seconds']*1e9)):
                    bounds.append(min(e.valid_until_ns if e.valid_until_ns is not None else 2**63-1,
                                      e.observed_at_ns+int(c['policy']['residency_max_age_seconds']*1e9)))
            validity[b]=min(bounds,default=now)
        rates={b:c['policy']['alpha']*(sum(e.request_count for e in demand.entries if e.bucket==b)+demand.overflow_request_count_by_bucket.get(b,0))/(width/1e9) for b in old}
        # Unknown estimator is encoded by an expired foreground timestamp.
        fg_at=end if enough else 0
        obs=ControllerObservation(now,demand,foreground,db,donor,pressures[dest],coverage,
            dict(self.ownership.snapshot.states),self.ownership.snapshot.epoch,rates,
            {b:c['policy']['cold_reserve_per_bucket'] for b in old},0.,fg_at,
            int(c['policy']['signal_max_age_seconds']*1e9),dest,oldlower,
            1e9/dt+sum(r.get('terminal_ns') is None for r in probe_records)/(dt/1e9),validity,enough)
        self.last_snapshot=obs
        return obs

    def order_key(self,item):
        mode=self.c['policy']['ordering']; bucket=self.ownership.bucket_for_key(item.key)
        entries={e.key:e for e in self.last_snapshot.demand.entries} if self.last_snapshot else {}
        e=entries.get(item.key)
        if mode=='demand': return (-(e.request_count/item.object_bytes if e else 0),-(e.last_seen_ns if e else 0),bucket,item.key)
        if mode=='recency': return (-(e.last_seen_ns if e else 0),bucket,item.key)
        return (hashlib.sha256(f'{self.c["routing"]["mapping_seed"]}:{item.key}'.encode()).hexdigest(),bucket,item.key)
