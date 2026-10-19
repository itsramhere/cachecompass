"""Fail-closed raw validation and matched initial/schedule audits for Phase 5."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cache_scaleout.baselines import BASELINES,DIMENSIONS
from cache_scaleout.contracts import json_record
from cache_scaleout.dataset import create_dataset,StableOwnershipMap
from cache_scaleout.evidence import write_json
from cache_scaleout.phase5 import stability_windows
from cache_scaleout.telemetry import reconcile_offers
from phase5_audit import audit_extra
from phase5_independent_audit import provenance_audit
from phase5_review_raw import raw_checks


def read(p): return json.loads(p.read_text())
def rows(p): return [json.loads(l) for l in p.read_text().splitlines() if l]
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()



def probe_coverage(c,r):
    """One attempted bundle per round; absent unissued work is never charged.

    Complete bundles require their full operation sequence. UNKNOWN must have
    explicit failure provenance and a legal issued prefix, never an invented
    INFO/query merely to satisfy a fixed count.
    """
    rounds=r['observations'];timeout=int(c['timing']['observation_timeout_seconds']*1e9)
    groups={o['started_ns']+timeout:o for o in rounds}
    if len(groups)!=len(rounds) or set(r['cache_probes'])!=set(c['routing']['final_nodes']):return False
    for name,operations in [('database',r['db_probes']),*r['cache_probes'].items()]:
        by={deadline:[] for deadline in groups}
        for op in operations:
            deadline=op['absolute_deadline_ns'];round=groups.get(deadline)
            if round is None or not round['started_ns']<=op['issued_ns']<deadline or op['terminal_ns']>round['ended_ns']:return False
            by[deadline].append(op)
        for deadline,round in groups.items():
            issued=sorted(by[deadline],key=lambda o:o['issued_ns']);sample=round['samples'][name]
            raw=round['raw_database_sample'] if name=='database' else round['raw_cache_samples'][name]
            expected=['same_query_probe'] if name=='database' else ['ping','info']
            names=[op['operation'] for op in issued]
            if names!=expected[:len(names)] or len(names)>len(expected):return False
            if sample['state']=='unknown':
                if not raw or 'failed_at_ns' not in raw or 'error' not in raw:return False
                if len(issued)==len(expected) and issued[-1]['outcome']=='completed':return False
                if len(issued)>1 and issued[0]['outcome']!='completed':return False
            elif names!=expected or any(op['outcome']!='completed' for op in issued):return False
    return True


def validate(path):
    errors=[]; checks={};counts={};m={};capacity_ok=False
    def check(name,value):
        checks[name]=bool(value)
        if not value:errors.append(name)
    try:
        m=read(path/'manifest.json');c=read(path/'effective_config.json');r=read(path/'result.json');status=read(path/'status.json');seal=read(path/'checksums.json')
        check('artifact_seal',all((path/k).is_file() and digest(path/k)==v for k,v in seal.items()) and set(seal)=={p.name for p in path.iterdir() if p.is_file() and p.name!='checksums.json'})
        check('required_artifacts',all(k in seal for k in ('manifest.json','source.json','effective_config.json','events.jsonl','requests.jsonl','migrations.jsonl','offered_schedule.json','result.json','status.json','warm_stability.json')))
        source=read(path/'source.json');canonical=json.dumps(source['files'],sort_keys=True,separators=(',',':')).encode()
        check('source_identity',hashlib.sha256(canonical).hexdigest()==source['aggregate_sha256']==m['source_fingerprint'])
        doc=read(path/'offered_schedule.json');offers=doc['requests'];events=rows(path/'events.jsonl');req=rows(path/'requests.jsonl');mig=rows(path/'migrations.jsonl')
        arrivals=[e['detail'] for e in events if e['kind']=='arrival_scheduled']
        check('offer_arrival_identity',len(arrivals)==len(offers) and {o['request_id']:o for o in arrivals}=={o['request_id']:o for o in offers})
        check('fixed_horizon',r['measurement_ended_ns']>=doc['origin_ns']+int(c['timing']['measurement_horizon_seconds']*1e9))
        check('no_diagnostics',m['phase3_diagnostics_enabled'] is False and r['diagnostic_operations']==0)
        ds=create_dataset(seed=c['dataset']['seed'],key_count=c['dataset']['keys'],value_bytes=c['dataset']['value_bytes']);by=ds.by_key()
        ownership=StableOwnershipMap(mapping_seed=c['routing']['mapping_seed'],bucket_count=c['routing']['virtual_buckets'],old_nodes=tuple(c['routing']['old_nodes']),final_nodes=tuple(c['routing']['final_nodes']),destination=c['routing']['destination'])
        check('empty_physical_reset',len({v['server_run_id'] for v in m['initial_service_state'].values()})==3 and all(v['physical_key_count']==v['evicted_keys']==0 for v in m['initial_service_state'].values()))
        expected={n:[] for n in c['routing']['final_nodes']}
        for item in ds.items: expected[str(ownership.old_owner(ownership.bucket_for_key(item.key)))].append({'key':str(item.key),'payload_hex':item.payload.hex(),'ttl_ms':None})
        check('complete_initial_state',all(sorted(expected[n],key=lambda x:x['key'])==m['initial_logical_state'][n] for n in expected))
        check('warm_stability_raw',read(path/'warm_stability.json')['valid'] and all(q['hit'] and q['payload_ok'] for w in read(path/'warm_stability.json')['windows'] for q in w['requests']))
        check('actual_pool_bounds',not r['database_pool']['issuance_stopped'] and r['database_pool']['quarantined_operations']==0 and r['database_pool']['foreground']['observed_max_concurrency']<=c['resources']['foreground_db_connections'] and r['database_pool']['background']['observed_max_concurrency']<=c['resources']['background_db_connections'] and all(v['foreground_max']<=c['resources']['foreground_cache_connections_per_node'] and v['background_max']<=c['resources']['background_cache_connections_per_node'] for v in r['cache_pools'].values()))
        probes=r['db_probes']+[o for records in r['cache_probes'].values() for o in records]
        check('individual_probe_charges',len({o['operation_id'] for o in probes})==len(probes) and all(o['terminal_ns']>=o['issued_ns'] and o['issued_ns']<o['absolute_deadline_ns'] and o['outcome'] in ('completed','failed','timed_out','cancelled') for o in probes))
        check('common_noncatchup_probes',len(r['observations'])>=int(c['timing']['measurement_horizon_seconds']/c['timing']['observation_interval_seconds'])-2 and probe_coverage(c,r))
        if m['kind']=='mixed_pool':
            ops=r['operations'];check('mixed_offer_terminal_identity',{o['request_id'] for o in offers}=={o['request_id'] for o in ops} and len(offers)==len(ops))
            check('mixed_operation_offer_fields',all(any(all(op.get(k)==offer.get(k) for k in ('request_id','key','work_class','scheduled_arrival_ns')) for offer in offers) for op in ops))
            check('mixed_payload_and_chronology',all(o['payload_ok'] and o['scheduled_arrival_ns']<=o['submitted_ns']<=o['issued_ns']<=o['terminal_ns'] for o in ops))
            check('no_router_migration',not req and not mig)
            counts={'offered':len(offers),'db_attempts':len(ops)+len(r['db_probes'])}
        else:
            check('six_controls_only',m['policy'] in BASELINES)
            check('request_reconciliation',reconcile_offers(tuple(offers),req).complete)
            check('request_chronology',all(q['scheduled_arrival_ns']<=q['submitted_ns']<=q['completed_ns'] and (q['outcome']!='completed' or q['completed_ns']-q['scheduled_arrival_ns']<=q['timeout_seconds']*1e9) for q in req))
            check('payload_identity',len(r['payload_checks'])==len(req) and len({p['request_id'] for p in r['payload_checks']})==len(req) and all(p['actual'] is None or p['actual']==p['expected']==hashlib.sha256(by[next(q['key'] for q in req if q['request_id']==p['request_id'])].payload).hexdigest() for p in r['payload_checks']))
            fg=r['foreground_operations'];bg=r['migration_operations'];ops=fg+bg+probes
            check('global_unique_terminal_operations',len({o['operation_id'] for o in ops})==len(ops) and all(o.get('terminal_ns') is not None and o['terminal_ns']>=o['issued_ns'] and o['issued_ns']<o['absolute_deadline_ns'] and o['outcome'] in ('completed','failed','timed_out','cancelled') for o in ops))
            classes=Counter(o['work_class'] for o in ops)
            check('global_db_partition',sum(q['database_attempts'] for q in req)==classes['foreground_database'] and sum(o['work_class'] in ('foreground_database','discretionary_database_warmup','observation_database') for o in ops)==sum(classes[k] for k in ('foreground_database','discretionary_database_warmup','observation_database')))
            check('foreground_attempt_ownership',all(sum(o['request_id']==q['request_id'] and o['operation']=='database_read' for o in fg)==q['database_attempts'] and sum(o['request_id']==q['request_id'] and o['operation']=='cache_read' for o in fg)==q['cache_attempts'] and sum(o['request_id']==q['request_id'] and o['operation']=='cache_write' for o in fg)==q['cache_write_attempts'] for q in req))
            check('migration_attempt_links',len(mig)==len(bg) and len({(a['task_id'],a['attempt']) for a in mig})==len(mig) and {(a['task_id'],a['attempt'],a['outcome']) for a in mig}=={(o['task_id'],o['retry_ordinal'],o['outcome']) for o in bg})
            check('migration_parent_payload',all(o['parent_task_id'] is None or any(p['task_id']==o['parent_task_id'] and p['key']==o['key'] and p['outcome']=='completed' for p in bg) for o in bg))
            actions=r['actions'];admitted=[]
            check('action_event_identity',[e['detail'] for e in events if e['kind']=='policy_action']==actions)
            check('action_causality',all(a['action']['observation_as_of_ns']==a['observation']['observed_at_ns']<=a['action']['decided_at_ns'] and a['observation']['demand']['window']['end_ns']<=a['action']['observation_as_of_ns'] and a['action']['decided_at_ns']<r['deadline_ns'] for a in actions))
            for row in actions:
                a=row['action'];o=row['observation'];w=o['demand']['window'];actual=Counter(q['key'] for q in req if w['start_ns']<=q['submitted_ns']<w['end_ns'])
                represented={e['key']:e['request_count'] for e in o['demand']['entries']}
                check('causal_demand_'+str(a['decided_at_ns']),dict(actual)==represented)
                admitted.extend(a['admit_buckets'])
            check('unique_irreversible_admissions',len(set(admitted))==len(admitted))
            grant_ok=True
            for row in actions:
                a=row['action'];g=a['budget'];t=a['decided_at_ns'];charged=Counter()
                for op in bg:
                    if op.get('grant_generation_ns')==t:
                        cls=op['work_class'];prefix={'donor_read':'donor','discretionary_database_warmup':'background_db','destination_write':'destination_write'}[cls]
                        charged[prefix+'_operations']+=1
                        if cls!='discretionary_database_warmup':charged[prefix+'_bytes']+=op['reserved_bytes']
                        if not t<=op['issued_ns']<t+g['valid_for_ns']:grant_ok=False
                if any(charged[d]>g[d] for d in DIMENSIONS):grant_ok=False
            check('generation_interval_limits',grant_ok and all(any(a['action']['decided_at_ns']==op.get('grant_generation_ns') for a in actions) for op in bg))
            check('background_deadline',all(op['issued_ns']<r['deadline_ns'] for op in bg))
            check('bounded_cleanup',r['bounds']['remaining_fills']==r['bounds']['remaining_workers']==r['bounds']['remaining_buffered_bytes']==0 and r['bounds']['maximum_inflight']<=c['resources']['max_inflight_requests'] and r['bounds']['migration_workers']<=c['resources']['migration_workers'] and r['bounds']['maximum_buffered_bytes']<=c['resources']['max_buffered_payload_bytes'] and r['bounds']['maximum_queue_depth']<=c['resources']['max_pending_migration_tasks'])
            check('no_wire_byte_fabrication',all(o['actual_bytes'] is None for o in bg))
            if m['policy']=='immediate_cutover':
                check('immediate_no_discretionary',not bg and not r['pass_results'] and len(admitted)==len(ownership.affected_buckets) and len([a for a in actions if a['action']['admit_buckets']])==1)
            else:
                expectedkeys={i.key for i in ds.items if ownership.bucket_for_key(i.key) in ownership.affected_buckets}
                check('finite_pass_exact_registry',{p['key'] for p in r['pass_results']}==expectedkeys and len(r['pass_results'])==len(expectedkeys) and all(p['disposition'] in ('warmed','not_warmed') for p in r['pass_results']))
            if 'migration_before_cutover' in m['policy']:
                check('all_at_once_control',not admitted or len(admitted)==len(ownership.affected_buckets) and len([a for a in actions if a['action']['admit_buckets']])==1)
            windows,success=stability_windows(req,affected=ownership.affected_buckets,destination=c['routing']['destination'],final_ns=r['final_publication_ns'],final_epoch=r['final_epoch'],deadline=r['deadline_ns'],width=int(c['timing']['stability_subwindow_seconds']*1e9),required=c['timing']['stability_subwindows'],minimum=c['timing']['stability_min_requests'])
            check('raw_traffic_stability',windows==r['stability'] and success==r['success_ns'])
            check('legitimate_terminal_status',status['status']==r['status']==('completed' if success else 'policy_failure'))
            check('entire_handover_interval',success is None or r['handover_seconds']==(success-r['expansion_ns'])/1e9)
            extra,token_detail=audit_extra(path,m,c,r,req)
            for name,value in extra.items():check(name,value)
            for name,value in provenance_audit(m,c,r,req).items():check(name,value)
            counts={'token_detail':token_detail,'offered':len(offers),'operations':len(ops),'db_attempts':sum(classes[k] for k in ('foreground_database','discretionary_database_warmup','observation_database')),'classes':dict(classes),'status':status['status'],'handover_seconds':r['handover_seconds']}
        for name,value in raw_checks(m,c,r,offers,req,read(path/'warm_stability.json')).items():check(name,value)
        capacity=m.get('capacity_record');capacity_ok=False
        if m.get('schema_version',0)>=6 and m['kind']=='baseline' and capacity:
            from cache_scaleout.phase5 import capacity_signature
            capacity_ok=capacity['signature']==capacity_signature(c) and capacity['source']==m['source_fingerprint'] and capacity['total_attempt_rate']==c['policy']['safe_total_db_rate'] and capacity['observation_rate']==1/c['timing']['observation_interval_seconds'] and capacity['reserve_rate']==c['policy']['reserve_db_rate']
            splits=set()
            for case in capacity['cases']:
                case_path=path.parent/case['run_id'];cm=read(case_path/'manifest.json');cr=read(case_path/'result.json')
                splits.add((cm['mixed_foreground_rate'],cm['mixed_warmup_rate']))
                capacity_ok &= digest(case_path/'result.json')==case['result_sha256'] and cm['source_fingerprint']==m['source_fingerprint'] and validate(case_path)['valid'] and cr['eligible']
            capacity_ok &= splits=={(capacity['total_attempt_rate']-capacity['observation_rate']-2.,2.),(capacity['total_attempt_rate']-capacity['observation_rate']-4.,4.)}
    except Exception as e:errors.append('validation_exception:'+repr(e))
    return {'run_id':path.name,'valid':not errors,'review_eligible':not errors and m.get('schema_version',0)>=6 and (m['kind']=='mixed_pool' or capacity_ok),'checks':checks,'errors':errors,'counts':counts}


def matched(paths):
    errors=[];first=None;seen=set()
    for p in paths:
        m=read(p/'manifest.json');c=read(p/'effective_config.json');d=read(p/'offered_schedule.json');origin=d['origin_ns']
        identity={'common_config':c,'initial':m['initial_logical_state'],'schedule':[{**o,'scheduled_arrival_ns':o['scheduled_arrival_ns']-origin} for o in d['requests']],
            'resources':c['resources'],'retries':c['retries'],'timing':c['timing'],'ordering':c['policy']['ordering'],'source':m['source_fingerprint']}
        if first is None:first=identity
        if identity!=first:errors.append(p.name+':unmatched')
        ids={v['server_run_id'] for v in m['initial_service_state'].values()}
        if ids & seen:errors.append(p.name+':reused_physical_process')
        seen|=ids
    return {'valid':not errors,'errors':errors,'runs':[p.name for p in paths]}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runs',nargs='+',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--matched',action='store_true');a=p.parse_args()
    if a.output.exists():raise SystemExit('fresh output required')
    root=Path(__file__).resolve().parents[1];paths=[root/'runs'/i for i in a.runs];result={'runs':[validate(i) for i in paths]}
    if a.matched:result['matched']=matched(paths)
    result['valid']=all(v['valid'] for v in result['runs']) and result.get('matched',{}).get('valid',True)
    write_json(a.output,result);print(json.dumps({'valid':result['valid'],'runs':[(v['run_id'],v['valid'],v['errors']) for v in result['runs']]},indent=2));raise SystemExit(0 if result['valid'] else 1)
