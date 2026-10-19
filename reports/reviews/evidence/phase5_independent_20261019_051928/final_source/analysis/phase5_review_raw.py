"""Independent schema-6 checks of raw evidence (no controller invocation)."""
import hashlib, math
from collections import Counter
from cache_scaleout.phase5 import capacity_signature
from cache_scaleout.phase4 import _percentile,select_workload
from cache_scaleout.dataset import create_dataset,StableOwnershipMap


def raw_checks(m,c,r,offers,requests,warm):
    if m.get('schema_version',0)<6:return {}
    checks={};origin=r['measurement_origin_ns'];horizon=origin+int(c['timing']['measurement_horizon_seconds']*1e9)
    checks['exact_common_horizon']=r['horizon_ns']==horizon
    checks['no_new_observations_after_horizon']=all(origin<=o['started_ns']<horizon and o['started_ns']<=o['ended_ns'] for o in r['observations'])
    resources=r['resources'];expected={'database':(1000000000,536870912),'cache-new':(500000000,134217728),'cache-old-1':(500000000,134217728),'cache-old-2':(500000000,134217728)}
    checks['actual_physical_limits']=all(set(resources[s])==set(expected) and all((v['nano_cpus'],v['memory_limit_bytes'])==expected[k] and '@sha256:' in v['image'] for k,v in resources[s].items()) for s in ('before','after'))
    checks['stable_images_and_limits']=all(all(resources['before'][k][f]==resources['after'][k][f] for f in ('nano_cpus','memory_limit_bytes','image')) for k in expected)
    p95=[_percentile([q['latency_ms'] for q in w['requests']],.95) for w in warm['windows']]
    checks['warm_stability_numeric_replay']=len(p95)==c['warm_stability']['windows'] and all(v<=c['warm_stability']['maximum_p95_ms'] for v in p95) and max(p95)-min(p95)<=c['warm_stability']['maximum_p95_spread_ms'] and all(w['p95_ms']==v for w,v in zip(warm['windows'],p95))
    ds=create_dataset(seed=c['dataset']['seed'],key_count=c['dataset']['keys'],value_bytes=c['dataset']['value_bytes']);by=ds.by_key()
    if m['kind']=='mixed_pool':
        expected_offers=[]
        for cls,rate in [('foreground_database',m['mixed_foreground_rate']),('discretionary_database_warmup',m['mixed_warmup_rate'])]:
            expected_offers += [{'request_id':f'{cls}-{i:04d}','key':str(ds.items[i%len(ds.items)].key),'work_class':cls,'scheduled_arrival_ns':origin+int((.5+i/rate)*1e9)} for i in range(int(rate*8))]
        expected_offers.sort(key=lambda o:(o['scheduled_arrival_ns'],o['request_id']))
        checks['mixed_exact_offered_schedule']=offers==expected_offers
        checks['mixed_raw_payload_hashes']=all(o['payload_sha256']==o['expected_sha256']==hashlib.sha256(by[o['key']].payload).hexdigest() for o in r['operations'])
        summaries={}
        for cls in ('foreground_database','discretionary_database_warmup'):
            rows=[o for o in r['operations'] if o['work_class']==cls]
            summaries[cls]={'offered':len(rows),'issued':sum(o['issued_ns'] is not None for o in rows),'completed':sum(o['outcome']=='completed' for o in rows),
                'p95_ms':_percentile([(o['terminal_ns']-o['scheduled_arrival_ns'])/1e6 for o in rows],.95),
                'max_dispatch_ms':max((o['submitted_ns']-o['scheduled_arrival_ns'])/1e6 for o in rows),'payloads_ok':all(o['payload_ok'] for o in rows)}
        eligible=all(s['offered']==s['issued']==s['completed'] and s['payloads_ok'] and s['p95_ms']<=100 and s['max_dispatch_ms']<=50 for s in summaries.values())
        checks['mixed_numeric_eligibility_replay']=summaries==r['mixed_summaries'] and eligible==r['eligible'] and r['nominal_total_attempt_rate']==m['mixed_foreground_rate']+m['mixed_warmup_rate']+1/c['timing']['observation_interval_seconds']
        return checks
    rt=c['routing'];mapping=StableOwnershipMap(mapping_seed=rt['mapping_seed'],bucket_count=rt['virtual_buckets'],old_nodes=tuple(rt['old_nodes']),final_nodes=tuple(rt['final_nodes']),destination=rt['destination'])
    affected=[i for b,items in mapping.keys_by_bucket(ds).items() if b in mapping.affected_buckets for i in items]
    # Generator's affected list is ordered by affected bucket, not dictionary traversal.
    grouped=mapping.keys_by_bucket(ds);affected=[i for b in mapping.affected_buckets for i in grouped[b]]
    count=int(c['workload']['offered_rate']*(c['timing']['measurement_horizon_seconds']-.5))
    selected=select_workload(affected,[i for i in ds.items if mapping.bucket_for_key(i.key) not in mapping.affected_buckets],count,c['workload']['affected_share'],c['workload']['zipf_exponent'],c['dataset']['seed'])
    expected_offers=[{'request_id':f'app-{i:05d}','key':str(item.key),'scheduled_arrival_ns':origin+int((.5+i/c['workload']['offered_rate'])*1e9)} for i,item in enumerate(selected)]
    checks['baseline_exact_offered_schedule']=offers==expected_offers
    checks['common_deadline_and_task_interval']=r['expansion_ns']==origin+int(c['timing']['expansion_at_seconds']*1e9) and r['deadline_ns']==r['expansion_ns']+int(c['timing']['handover_deadline_seconds']*1e9)
    checks['published_action_validity']=all(a['action']['decided_at_ns']<=a['detail']['published_at_ns']<a['action']['decided_at_ns']+a['action']['budget']['valid_for_ns'] for a in r['actions'])
    if m['policy']!='immediate_cutover' and c['policy']['ordering']=='fifo_hash' and c['resources']['migration_workers']==1:
        ordered=sorted(affected,key=lambda item:(hashlib.sha256(f'{rt["mapping_seed"]}:{item.key}'.encode()).hexdigest(),mapping.bucket_for_key(item.key),item.key))
        checks['causal_fifo_hash_pass_order']=[p['key'] for p in r['pass_results']]==[i.key for i in ordered]
    fg=r['foreground_operations'];req={q['request_id']:q for q in requests}
    retries={'cache_read':'foreground_cache','database_read':'foreground_database','cache_write':'foreground_fill_write'}
    checks['foreground_retry_timeouts']=all(1<=o['retry_ordinal']<=c['retries'][retries[o['operation']]]['max_attempts'] and o['absolute_deadline_ns']<=req[o['request_id']]['scheduled_arrival_ns']+int(c['timing']['request_timeout_seconds']*1e9) for o in fg)
    checks.update(pressure_replay(c,r))
    return checks


def pressure_replay(c,r):
    previous={};evictions={};valid=True;timestamp=True;charges=True
    p=c['policy_pressure'];dt=c['timing']['observation_interval_seconds'];width=int(dt*1e9)
    allops=r['foreground_operations']+r['migration_operations'];probes=r['db_probes'];max_age=int(c['policy']['signal_max_age_seconds']*1e9)
    for action in r['actions']:
        o=action['observation'];now=o['observed_at_ns'];end=o['demand']['window']['end_ns']
        rounds=[q for q in r['observations'] if q['ended_ns']<=now];latest=rounds[-1] if rounds else None
        real=[op for op in allops if op['issued_ns']<=now and (op['terminal_ns']>now or op['terminal_ns']>=end-width)]
        states={};times={}
        for name in ['db',*c['routing']['final_nodes']]:
            sample=(latest['raw_database_sample'] if name=='db' else latest['raw_cache_samples'][name]) if latest else None
            times[name]=latest['samples']['database' if name=='db' else name]['observed_at_ns'] if latest else 0
            required=('probe_ms','foreground_waiting','background_waiting') if name=='db' else ('ping_ms','used_memory','maxmemory','evicted_keys','waiting','active')
            good=sample is not None and all(isinstance(sample.get(k),(int,float)) and not isinstance(sample[k],bool) and math.isfinite(sample[k]) and sample[k]>=0 for k in required) and (name=='db' or sample['maxmemory']>0)
            if not good:state='unknown'
            else:
                rows=[op for op in real if ('database' in op['work_class'] if name=='db' else op['target_owner']==name and op['work_class'] in ('foreground_cache','donor_read','destination_write'))]
                latency=[(min(now,op['terminal_ns'])-op['issued_ns'])/1e6 for op in rows]
                failure=any(op['terminal_ns']<=now and op['outcome']!='completed' for op in rows)
                stack=[sample.get('real_classes',{})]
                while stack:
                    row=stack.pop()
                    if not isinstance(row,dict):continue
                    if 'latency_ms' in row:
                        if 0<=now-row['observed_at_ns']<=max_age:latency.append(row['latency_ms']);failure |= row['outcome']!='completed'
                    else:stack.extend(row.values())
                probe=sample['probe_ms' if name=='db' else 'ping_ms'];queue=sample['foreground_waiting']+sample['background_waiting'] if name=='db' else sample['waiting']
                active=sample.get('foreground_active',0)+sample.get('background_active',0) if name=='db' else sample['active'];active=max(active,sum(op['terminal_ns']>now for op in rows))
                fraction=0 if name=='db' else sample['used_memory']/sample['maxmemory'];evicted=sample.get('evicted_keys',0);increase=evicted>evictions.get(name,0);evictions[name]=evicted
                rate=sum(end-width<=op['issued_ns']<end and 'database' in op['work_class'] for op in allops+probes)/dt if name=='db' else 0
                prefix='db' if name=='db' else 'cache';maximum=max(latency,default=0)
                unsafe=probe>p[prefix+'_probe_upper_ms'] or failure or maximum>p['real_upper_ms'] or queue>p['queue_upper'] or active>p.get(prefix+'_inflight_upper',1000000) or fraction>p['memory_upper'] or increase or name=='db' and rate>p['db_rate_upper']
                safe=probe<=p[prefix+'_probe_lower_ms'] and maximum<=p['real_lower_ms'] and queue<=p['queue_lower'] and active<=p.get(prefix+'_inflight_lower',1000000) and fraction<=p['memory_lower'] and not increase and (name!='db' or rate<=p['db_rate_lower'])
                state='unsafe' if unsafe else 'safe' if safe else previous.get(name,'unknown')
            states[name]=state;previous[name]=state
        donors=[states[n] for n in c['routing']['old_nodes']];donor='unsafe' if 'unsafe' in donors else 'safe' if all(s=='safe' for s in donors) else 'unknown'
        valid &= (o['db_pressure']['state'],o['donor_pressure']['state'],o['destination_pressure']['state'])==(states['db'],donor,states[c['routing']['destination']])
        timestamp &= (o['db_pressure']['observed_at_ns'],o['donor_pressure']['observed_at_ns'],o['destination_pressure']['observed_at_ns'])==(times['db'],min(times[n] for n in c['routing']['old_nodes']),times[c['routing']['destination']])
        expected=1/dt+sum(op['issued_ns']<=now<op['terminal_ns'] for op in probes)/dt
        charges &= o['observation_db_rate_upper']==expected
    return {'independent_raw_pressure_hysteresis':valid,'independent_component_sample_freshness':timestamp,'independent_single_observation_allowance':charges}
