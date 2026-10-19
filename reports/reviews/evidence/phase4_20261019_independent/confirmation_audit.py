"""Independent issue-time, resource, causal and preservation calculations."""
import argparse, collections
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
ROOT=Path(__file__).resolve().parents[4]; HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import source_fingerprint, write_json, utc_now
from cache_scaleout.phase4 import _percentile
spec=importlib.util.spec_from_file_location('p4analysis',ROOT/'analysis/phase4_analysis.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
parser=argparse.ArgumentParser(); parser.add_argument('--prefix',default='p4review'); parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
if args.output.exists(): raise SystemExit('Audit output exists; choose a new path')

def audit():
    result=[]
    names=[f'{args.prefix}_cal{rate}_{rep}_20261019' for rep in range(1,4) for rate in (12,24,36)]
    names += [f'{args.prefix}_{c}_{rep}_20261019' for rep in range(1,4) for c in ('control','immediate')]
    names += [f'{args.prefix}_headroom144_20261019']
    for name in names:
        run=ROOT/'runs'/name; valid=a.validate(run)
        if not valid['valid']:
            result.append({'run_id':name,'errors':valid['errors']}); continue
        r=a.read(run/'result.json'); m=a.read(run/'manifest.json'); d=a.read(run/'offered_schedule.json'); req=a.rows(run/'requests.jsonl')
        origin=d['origin_ns']; cfg=a.read(run/'effective_config.json'); duration=cfg['timing']['calibration_seconds' if m['kind']=='calibration' else 'expansion_seconds']; end=origin+int((.5+duration)*1e9)
        probes=r['accounting']['database_probes']; events=a.rows(run/'events.jsonl'); rounds=[e['detail'] for e in events if e['kind']=='observation']
        ops=r.get('router',{}).get('operations',[])
        if m['kind']=='calibration':
            dbops=[{'issued_ns':x['issued_ns'],'terminal_ns':x['completed_ns'],'source':'database'} for x in req if x.get('issued_ns') is not None]
        else: dbops=[o for o in ops if o['source']=='database']
        timeline=sorted([(o['issued_ns'],1) for o in dbops]+[(o['terminal_ns'],-1) for o in dbops],key=lambda p:(p[0],-p[1]))
        active=maximum=0
        for _,delta in timeline: active+=delta; maximum=max(maximum,active)
        cpu={}
        for service,before in r['container_resources']['before'].items():
            after=r['container_resources']['after'][service]; elapsed=(after['observed_ns']-before['observed_ns'])/1e9
            stats={k:after['cpu_stat'][k]-v for k,v in before['cpu_stat'].items()}
            cpu[service]={'counter_interval_seconds':elapsed,'usage_core_fraction':stats['usage_usec']/1e6/elapsed,
                'cpu_stat_delta':stats,'nano_cpus':after.get('nano_cpus'),'memory_limit_bytes':after.get('memory_limit_bytes')}
        windows=[]
        for sec in range(int(duration+.5)+1):
            begin=origin+sec*1_000_000_000; finish=begin+1_000_000_000
            windows.append({'second':sec,'foreground_db_issued':sum(begin<=o['issued_ns']<finish for o in dbops),
                'observation_db_issued':sum(begin<=o['issued_ns']<finish for o in probes)})
        qpc={}
        lookup={x['request_id']:x for x in req}
        for w,begin,finish in (('pre',0,3),('transition',3,5),('post',5,8.5)):
            for source in ('database','old_cache','new_cache'):
                values=[p['service_ms_qpc'] for p in r.get('payload_checks',[]) if 'service_ms_qpc' in p and lookup[p['request_id']]['source']==source and origin+int(begin*1e9)<=lookup[p['request_id']]['scheduled_arrival_ns']<origin+int(finish*1e9)]
                if values: qpc[w+':'+source]={'count':len(values),'p50_ms':_percentile(values,.5),'p95_ms':_percentile(values,.95)}
        probe_latencies=[x['raw_database_sample'].get('probe_ms') for x in rounds if 'probe_ms' in x['raw_database_sample']]
        pool=r.get('db_pool',r.get('database_pool')); firstpool=rounds[0]['raw_database_sample'].get('pools',{})
        queue_deltas={k:pool['foreground'].get(k,0)-firstpool.get('foreground',{}).get(k,0) for k in ('requests_queued','requests_wait_ms')}
        cohort=valid['computed']; warm=a.read(run/'warm_stability.json')
        resources={'run_id':name,'computed':cohort,'container_cpu':cpu,'actual_issue_time_1s_bins':windows,
            'total_db_issued':len(dbops)+len(probes),'foreground_db_issued':len(dbops),'observation_db_issued':len(probes),
            'probe_outcomes':dict(collections.Counter(p['outcome'] for p in probes)),
            'probe_bundle_p95_ms':_percentile(probe_latencies,.95),'probe_bundle_max_ms':max(probe_latencies,default=None),
            'max_db_concurrency_conservative_tick_ties':maximum,'pool_queue_counter_delta_after_first_observation':queue_deltas,
            'qpc_service_by_window_returned_source':qpc,'warm_window_p95_ms':[w['p95_ms'] for w in warm['windows']],
            'headroom':r['headroom'],'database_pool':pool,'cache_final':r.get('cache_final',r.get('cache_services')),
            'cold_cache_misses':cohort.get('cold_cache_misses'),
            'transition_record':r.get('transition_record')}
        if m['kind']=='calibration':
            resources['terminal_outcomes_by_issuance']=dict(collections.Counter(x['outcome']+(' issued' if x.get('issued_ns') is not None else ' unissued') for x in req))
        else:
            resources['foreground_cache_read_ops_by_owner']=dict(collections.Counter(o['target_owner'] for o in ops if o['operation']=='cache_read'))
            resources['cold_cache_misses_by_owner']=dict(collections.Counter(o['target_owner'] for o in ops if o['operation']=='cache_read' and o['outcome']=='completed' and 'payload_bytes' not in o))
            cut=origin+3_000_000_000
            resources['transition_issued_work']={
                'foreground_db_issued':sum(cut<=o['issued_ns']<cut+2_000_000_000 for o in dbops),
                'observation_db_issued':sum(cut<=o['issued_ns']<cut+2_000_000_000 for o in probes),
                'new_cache_issued_reads':sum(o['operation']=='cache_read' and o['target_owner']=='new' and cut<=o['issued_ns']<cut+2_000_000_000 for o in ops),
                'new_cache_cold_misses':sum(o['operation']=='cache_read' and o['target_owner']=='new' and o['outcome']=='completed' and 'payload_bytes' not in o and cut<=o['issued_ns']<cut+2_000_000_000 for o in ops)}
        # Cohort counts differ from reads issued within a time boundary, deliberately reported separately.
        result.append(resources)
    historical=a.read(HERE/'historical_hashes.json')
    mismatches=[x['path'] for x in historical if not (ROOT/x['path']).is_file() or a.digest(ROOT/x['path'])!=x['sha256']]
    original=a.read(HERE/'submitted_identity.json')
    archive_mismatch=[x['path'] for x in original['files'] if a.digest(HERE/'original'/x['path'])!=x['sha256']]
    identity=source_fingerprint(); frozen=a.read(HERE/('final_confirmation_source.json' if args.prefix=='p4final' else 'confirmation_source.json'))
    output={'ended_utc':utc_now(),'runs':result,'historical_files_checked':len(historical),'historical_mismatches':mismatches,
        'archived_submitted_files_checked':len(original['files']),'archive_mismatches':archive_mismatch,
        'source_unchanged_since_freeze':identity['aggregate_sha256']==frozen['aggregate_sha256'], 'source':identity['aggregate_sha256']}
    write_json(args.output,output)
    print(json.dumps({k:v for k,v in output.items() if k!='runs'},indent=2))
    print(json.dumps([{'run_id':r['run_id'],'errors':r.get('errors'),'db':r.get('foreground_db_issued'),'probes':r.get('observation_db_issued')} for r in result],indent=2))
    return 1 if mismatches or archive_mismatch or any(r.get('errors') for r in result) or not output['source_unchanged_since_freeze'] else 0

if __name__=='__main__': raise SystemExit(audit())
