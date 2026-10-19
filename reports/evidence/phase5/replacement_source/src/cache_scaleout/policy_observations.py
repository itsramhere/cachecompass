"""Causal, bounded Phase 5 estimators and hysteretic pressure classification."""
from collections import deque
import hashlib

from .contracts import (BucketState, ComponentPressure, ControllerObservation, PressureState,
                        estimate_coverage)


class PressureClassifier:
    def __init__(self, config):
        self.config=config
        self.previous={}
        self.evictions={}

    def classify(self, name, sample, *, observed_ns, real_rows, rate, cache_raw=None):
        p=self.config
        if sample is None:
            state=PressureState.UNKNOWN; reason='missing_probe_bundle'
        else:
            probe=(sample.get('probe_ms') if name=='db' else sample.get('ping_ms'))
            real=[r for r in real_rows if r['terminal_ns'] is not None]
            latencies=[(r['terminal_ns']-r['issued_ns'])/1e6 for r in real]
            lower=p['db_probe_lower_ms'] if name=='db' else p['cache_probe_lower_ms']
            upper=p['db_probe_upper_ms'] if name=='db' else p['cache_probe_upper_ms']
            waiting=(sample.get('foreground_waiting',0)+sample.get('background_waiting',0) if name=='db' else sample.get('waiting',0))
            fraction=sample.get('used_memory',0)/max(1,sample.get('maxmemory',1)) if name!='db' else 0
            evicted=sample.get('evicted_keys',0)
            increased=evicted>self.evictions.get(name,0)
            self.evictions[name]=evicted
            if probe is None:
                state=PressureState.UNKNOWN; reason='failed_or_incomplete_probe'
            else:
                unsafe=(probe>upper or any(r['outcome']!='completed' for r in real) or
                        max(latencies,default=0)>p['real_upper_ms'] or waiting>p['queue_upper'] or
                        fraction>p['memory_upper'] or increased or (name=='db' and rate>p['db_rate_upper']))
                safe=(probe<=lower and max(latencies,default=0)<=p['real_lower_ms'] and
                      waiting<=p['queue_lower'] and fraction<=p['memory_lower'] and
                      not increased and (name!='db' or rate<=p['db_rate_lower']))
                state=PressureState.UNSAFE if unsafe else PressureState.SAFE if safe else self.previous.get(name,PressureState.UNKNOWN)
                reason=f'probe={probe};real_count={len(real)};max_real_ms={max(latencies,default=0)};queue={waiting};memory={fraction};rate={rate};eviction_delta={increased}'
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
            self.history.append((len(fg)/(dt/1e9),{b:v/(dt/1e9) for b,v in old.items()}))
            self.last_end=end
        enough=len(self.history)==self.k and end-self.origin>=width
        foreground=max((h[0] for h in self.history),default=0)+c['policy']['foreground_margin']
        oldlower={b:max(0,min((h[1][b] for h in self.history),default=0)-c['policy']['old_lower_margin']) if enough else 0 for b in old}
        # Closed-round samples only; no future or partial observation bundle.
        eligible=[r for r in rounds if r['ended_ns']<=now]
        latest=eligible[-1] if eligible else None
        at=latest['ended_ns'] if latest else 0
        real=[r for r in (*foreground_operations,*migration_operations) if end-dt<=r['issued_ns']<end]
        dbreal=[r for r in real if 'database' in r['work_class']]
        all_db=len([r for r in (*real,*probe_records) if end-dt<=r['issued_ns']<end and ('database' in r['work_class'])])/(dt/1e9)
        db=self.classifier.classify('db',latest['raw_database_sample'] if latest else None,observed_ns=at,real_rows=dbreal,rate=all_db)
        pressures={}
        for node in self.c['routing']['final_nodes']:
            pressures[node]=self.classifier.classify(node,latest['raw_cache_samples'][node] if latest else None,
                observed_ns=at,real_rows=[r for r in real if r['target_owner']==node],rate=0)
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
            1e9/dt+sum(r.get('terminal_ns') is None for r in probe_records)/(dt/1e9),validity)
        self.last_snapshot=obs
        return obs

    def order_key(self,item):
        mode=self.c['policy']['ordering']; bucket=self.ownership.bucket_for_key(item.key)
        entries={e.key:e for e in self.last_snapshot.demand.entries} if self.last_snapshot else {}
        e=entries.get(item.key)
        if mode=='demand': return (-(e.request_count/item.object_bytes if e else 0),-(e.last_seen_ns if e else 0),bucket,item.key)
        if mode=='recency': return (-(e.last_seen_ns if e else 0),bucket,item.key)
        return (hashlib.sha256(f'{self.c["routing"]["mapping_seed"]}:{item.key}'.encode()).hexdigest(),bucket,item.key)
