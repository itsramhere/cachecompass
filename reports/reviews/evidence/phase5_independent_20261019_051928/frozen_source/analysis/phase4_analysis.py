"""Fail-closed raw Phase 4 validation and independent-run descriptive inference."""
from __future__ import annotations
import argparse, csv, hashlib, html, json, math, statistics, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.phase4 import _percentile, _window_summary
from cache_scaleout.dataset import create_dataset, StableOwnershipMap
from cache_scaleout.telemetry import reconcile_offers

def read(path): return json.loads(path.read_text(encoding='utf-8'))
def rows(path): return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(run):
    errors=[]; entry={'run_id':run.name,'valid':False,'errors':errors}
    try:
        m=read(run/'manifest.json'); cfg=read(run/'effective_config.json'); result=read(run/'result.json')
        entry.update(kind=m['kind'],condition=m.get('condition'),pair_id=m.get('pair_id'),manifest=m)
        doc=read(run/'offered_schedule.json'); schedule=doc['requests']; origin=doc['origin_ns']; req=rows(run/'requests.jsonl')
        offers={r['request_id']:r for r in schedule}
        if len(offers)!=len(schedule): errors.append('duplicate offered ID')
        if {r['request_id'] for r in req}!=set(offers) or len(req)!=len(offers): errors.append('terminal ID reconciliation')
        for r in req:
            if r.get('error','').split(':')[0] in {'RuntimeError','ValueError','BufferError'}: errors.append('driver/correctness failure; not DB capacity')
            if r['request_id'] not in offers or any(r.get(k)!=offers[r['request_id']][k] for k in ('key','scheduled_arrival_ns')): errors.append('schedule identity differs')
            if r.get('outcome') not in {'completed','failed','timed_out','cancelled','refused','unsubmitted'}: errors.append('terminal outcome missing')
            s,t,c=r['scheduled_arrival_ns'],r.get('submitted_ns'),r.get('completed_ns')
            if t is None or c is None or not s<=t<=c: errors.append('request chronology/non-submission')
            if r.get('issued_ns') is not None and not t<=r['issued_ns']<=c: errors.append('issuance chronology')
            if r['outcome']=='completed' and c-s>int(cfg['timing']['request_timeout_seconds']*1e9): errors.append('late successful response')
        calibration=m['kind']=='calibration'; duration=cfg['timing']['calibration_seconds' if calibration else 'expansion_seconds']; first=cfg['timing']['first_arrival_seconds']
        rate=m.get('rate',m.get('offered_rate')); end=origin+int((first+duration)*1e9); target=cfg['timing']['latency_target_ms']
        if len(schedule)!=int(rate*duration) or any(r['scheduled_arrival_ns']!=origin+int((first+i/rate)*1e9) for i,r in enumerate(schedule)): errors.append('offered rate/duration mismatch')
        computed={}
        if calibration:
            computed=_window_summary(req,origin,end,target); computed['issued']=sum(r.get('issued_ns') is not None for r in req)
            for key,value in computed.items():
                if result.get(key)!=value: errors.append('summary mismatch: '+key)
            computed.update(rate=rate,duration_seconds=duration)
            computed['time_bins']=[_window_summary(req,origin+int((first+i)*1e9),origin+int((first+min(i+4,duration))*1e9),target) for i in range(0,int(duration),4)]
        else:
            cut=origin+int(cfg['timing']['expansion_at_seconds']*1e9)
            for name,begin,finish in (('pre_event',origin,cut),('transition',cut,cut+2_000_000_000),('post_event',cut+2_000_000_000,end)):
                computed[name]=_window_summary(req,begin,finish,target)
                if computed[name]!=result.get(name): errors.append('summary mismatch: '+name)
            if not reconcile_offers(tuple(schedule),req).complete: errors.append('request leader reconciliation')
        if m.get('schema_version')!=2: errors.append('legacy measurement; corrected protocol not executed')
        events=rows(run/'events.jsonl') if (run/'events.jsonl').exists() else []
        arrivals=[e['detail'] for e in events if e['kind']=='arrival_scheduled']
        if len(arrivals)!=len(schedule) or {e['request_id']:e for e in arrivals}!=offers: errors.append('arrival event reconciliation')
        rounds=[e['detail'] for e in events if e['kind']=='observation']
        if not rounds or rounds[-1]['started_ns']<end-1_000_000_000: errors.append('fixed observation horizon missing')
        accounting=result.get('accounting',{}); probes=accounting.get('database_probes',[])
        if not probes: errors.append('missing DB probe operation records')
        if set(accounting.get('cache_probes',{}))!=set(cfg['routing']['final_nodes']): errors.append('missing cache probe records')
        all_probes=probes+sum(accounting.get('cache_probes',{}).values(),[])
        if len({p['operation_id'] for p in all_probes})!=len(all_probes): errors.append('duplicate probe IDs')
        for p in all_probes:
            if p['outcome'] not in {'completed','failed','timed_out','cancelled'} or not isinstance(p.get('terminal_ns'),int) or not p['issued_ns']<=p['terminal_ns']: errors.append('probe terminal chronology')
            if p['actual_bytes'] is not None: errors.append('unverified measured wire bytes')
        if any(accounting.get(k)!=0 for k in ('competing_application_db_reads','discretionary_db_warmup_reads','donor_copy_reads','diagnostic_forced_misses')): errors.append('undeclared background/diagnostic work')
        if probes and (min(p['issued_ns'] for p in probes)>origin+500_000_000 or max(p['issued_ns'] for p in probes)<end-1_000_000_000): errors.append('observation horizon incomplete')
        if rounds:
            for begin,end_round in ((r['started_ns'],r['ended_ns']) for r in rounds):
                bundle=[p for p in all_probes if begin<=p['issued_ns']<=end_round]
                if not any(p['source']=='database' for p in bundle): errors.append('probe round missing DB issue')
            if any(p['issued_ns']<origin or not any(r['started_ns']<=p['issued_ns']<=r['ended_ns'] for r in rounds) for p in all_probes): errors.append('probe outside recorded rounds')
        dataset=create_dataset(seed=cfg['dataset']['seed'],key_count=cfg['dataset']['keys'],value_bytes=cfg['dataset']['value_bytes'])
        expected={str(r.key):hashlib.sha256(r.payload).hexdigest() for r in dataset.items}
        rt=cfg['routing']; ownership=StableOwnershipMap(mapping_seed=rt['mapping_seed'],bucket_count=rt['virtual_buckets'],old_nodes=tuple(rt['old_nodes']),final_nodes=tuple(rt['final_nodes']),destination=rt['destination'])
        logical=m.get('initial_logical_state',{})
        if set(logical)!=set(rt['final_nodes']): errors.append('missing complete initial state')
        else:
            actual={r['key']:hashlib.sha256(bytes.fromhex(r['payload_hex'])).hexdigest() for population in logical.values() for r in population}
            if actual!=expected or sum(map(len,logical.values()))!=len(expected): errors.append('initial payload population')
            for node,population in logical.items():
                if any(str(ownership.old_owner(ownership.bucket_for_key(r['key'])))!=node or r['ttl_ms'] is not None for r in population): errors.append('initial owner/TTL mismatch')
            if logical[rt['destination']]: errors.append('destination prewarmed')
        services=m['initial_service_state']
        if len({v['server_run_id'] for v in services.values()})!=3 or any(v['physical_key_count'] or v['evicted_keys'] for v in services.values()): errors.append('initial physical reset')
        final=result.get('cache_final',result.get('cache_services',{}))
        if len(final)!=3 or any(v['evicted_keys'] or v['maxmemory']!=cfg['services']['cache']['maxmemory_bytes'] for v in final.values()): errors.append('cache limits/evictions')
        if calibration:
            for r in req:
                if r['outcome']=='completed' and r.get('payload_sha256')!=expected.get(r['key']): errors.append('returned DB payload mismatch')
            ops=[{'operation_id':r['request_id'],'issued_ns':r['issued_ns'],'terminal_ns':r['completed_ns'],'source':'database','operation':'database_read','outcome':r['outcome']} for r in req if r.get('issued_ns') is not None]
        else:
            ops=result['router']['operations']
            if len({o['operation_id'] for o in ops})!=len(ops): errors.append('duplicate operation IDs')
            if result['routing']!=ownership.summary(): errors.append('ownership map mismatch')
            tr=result.get('transition_record')
            if m['condition']=='immediate':
                if not tr or tr['affected_buckets']!=list(ownership.affected_buckets) or tr['path']!=['copying','eligible','new'] or tr['epoch']!=1 or tr['expected_epoch']!=0 or not cut<=tr['published_ns']<=cut+50_000_000: errors.append('cutover map/trigger mismatch')
            elif tr is not None: errors.append('control published cutover')
            payloads={p['request_id']:p for p in result.get('payload_checks',[])}
            if set(payloads)!=set(offers): errors.append('missing response payload checks')
            for r in req:
                if r['outcome']=='completed' and payloads.get(r['request_id'],{}).get('payload_sha256')!=expected.get(r['key']): errors.append('returned cache/DB payload mismatch')
                route=r['route']; bucket=ownership.bucket_for_key(r['key'])
                is_new=m['condition']=='immediate' and tr and r['submitted_ns']>=tr['published_ns'] and bucket in ownership.affected_buckets
                wanted=str(ownership.final_owner(bucket) if is_new else ownership.old_owner(bucket))
                if tr and r['submitted_ns']==tr['published_ns'] and route['epoch']==0: wanted=str(ownership.old_owner(bucket))
                if route['owner']!=wanted or route['bucket']!=bucket: errors.append('captured owner mismatch')
                own=[o for o in ops if o['request_id']==r['request_id']]
                if any(r[key]!=sum(o['operation']==op for o in own) for key,op in (('cache_attempts','cache_read'),('database_attempts','database_read'),('cache_write_attempts','cache_write'))): errors.append('operation request reconciliation')
            if any(o['request_id'] not in offers or o['outcome'] not in {'completed','failed','timed_out','cancelled'} or not o['issued_ns']<=o.get('terminal_ns',0) or o['issued_ns']>=o['absolute_deadline_ns'] for o in ops): errors.append('operation chronology/terminal')
            computed['cold_cache_misses']=sum(o['operation']=='cache_read' and o['outcome']=='completed' and 'payload_bytes' not in o for o in ops)
        warm=read(run/'warm_stability.json') if (run/'warm_stability.json').exists() else None
        if not warm: errors.append('missing warm latency stability evidence')
        else:
            w=cfg['warm_stability']; p95=[_percentile([r['latency_ms'] for r in win['requests']],.95) for win in warm['windows']]
            if len(p95)!=w['windows'] or max(p95)>w['maximum_p95_ms'] or max(p95)-min(p95)>w['maximum_p95_spread_ms'] or any(not r['hit'] or not r['payload_ok'] for win in warm['windows'] for r in win['requests']): errors.append('warm stability criterion')
        if 'container_resources' not in result or 'headroom' not in result: errors.append('missing measured component headroom')
        pool=result.get('db_pool',result.get('database_pool',{}))
        if pool.get('issuance_stopped') or pool.get('quarantined_operations'): errors.append('driver issuance stopped/quarantined')
        if (run/'checksums.json').exists():
            seals=read(run/'checksums.json'); files={p.name for p in run.iterdir() if p.is_file() and p.name!='checksums.json'}
            if set(seals)!=files or any(digest(run/name)!=value for name,value in seals.items()): errors.append('artifact checksum mismatch')
        else: errors.append('missing artifact checksums')
        source=read(run/'source.json'); canonical=json.dumps(source['files'],sort_keys=True,separators=(',',':')).encode()
        if hashlib.sha256(canonical).hexdigest()!=source['aggregate_sha256'] or source['aggregate_sha256']!=m['source_fingerprint']: errors.append('source identity mismatch')
        if read(run/'status.json')['status'] not in {'completed','policy_failure'}: errors.append('run not completed validly')
        lag=[(r['submitted_ns']-r['scheduled_arrival_ns'])/1e6 for r in req if r.get('submitted_ns') is not None]
        computed.update(dispatch_lag_p95_ms=_percentile(lag,.95),dispatch_lag_max_ms=max(lag,default=0),
            issued_foreground_db_attempts=sum(o['source']=='database' for o in ops),issued_observation_db_attempts=len(probes),
            db_issue_latency_p95_ms=_percentile([(r['issued_ns']-r['submitted_ns'])/1e6 for r in req if r.get('issued_ns') is not None],.95))
        if calibration: computed['capacity_eligible']=not errors and computed['issued']==len(schedule) and computed['completed']==len(schedule) and computed['all_offer_latency_violations']==0 and computed['successful_p95_ms']<target and computed['dispatch_lag_max_ms']<=50
        entry.update(computed=computed,source=source['aggregate_sha256'],headroom=result.get('headroom'),resources=result.get('container_resources'))
    except (OSError,KeyError,TypeError,ValueError,ZeroDivisionError) as error:
        errors.append('incomplete/malformed evidence: '+repr(error))
    entry['errors']=sorted(set(errors)); entry['valid']=not errors
    return entry

def pair_check(c,i):
    errors=[]
    for key in ('config_sha256','initial_logical_state'):
        if c['manifest'][key]!=i['manifest'][key]: errors.append('paired '+key+' differs')
    if c['source']!=i['source']: errors.append('paired source differs')
    if {s['server_run_id'] for s in c['manifest']['initial_service_state'].values()} & {s['server_run_id'] for s in i['manifest']['initial_service_state'].values()}: errors.append('paired caches reused')
    schedules=[]
    for e in (c,i):
        d=read(ROOT/'runs'/e['run_id']/'offered_schedule.json')
        schedules.append([(r['request_id'],r['key'],r['scheduled_arrival_ns']-d['origin_ns']) for r in d['requests']])
    if schedules[0]!=schedules[1]: errors.append('paired relative schedule differs')
    return errors

def run_uncertainty(values):
    if not values: return None
    n=len(values); mean=statistics.mean(values); result={'independent_runs':n,'mean':mean,'minimum':min(values),'maximum':max(values)}
    if n==3:
        half=4.3026527299*statistics.stdev(values)/math.sqrt(n)
        result.update(normal_model_t95_interval=[mean-half,mean+half],caution='n=3; normal run-effects assumption unverified; exploratory interval, no equivalence claim')
    return result

def select_capacity(curve):
    return max((r['offered_rate'] for r in curve if r['eligible']),default=None)

def write_csv(path,records):
    if not records: return
    with path.open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)

def svg(points,path,title):
    maxx=max(p[0] for p in points) or 1; maxy=max(p[1] for p in points) or 1
    dots=''.join(f'<circle cx="{65+x/maxx*580:.1f}" cy="{300-y/maxy*240:.1f}" r="4"><title>{html.escape(label)}</title></circle>' for x,y,label in points)
    ticks=''.join(f'<text x="10" y="{300-i*60}">{i*maxy/4:.1f}</text>' for i in range(5))
    labels=''.join(f'<text x="{65+x/maxx*580:.1f}" y="325">{x:g}</text>' for x in sorted({p[0] for p in points}))
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="740" height="390"><rect width="100%" height="100%" fill="white"/><text x="15" y="22">{html.escape(title)}</text><text x="15" y="43">Successful scheduled-arrival p95 (ms)</text><path d="M65 55V300H675" fill="none" stroke="black"/>{dots}{ticks}{labels}<text x="150" y="360">Offered requests/second; points are independent runs</text></svg>',encoding='utf-8')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--runs',nargs='+',required=True); p.add_argument('--output',required=True); args=p.parse_args()
    out=ROOT/args.output; out.mkdir(parents=True,exist_ok=False)
    data=[validate(ROOT/'runs'/name) for name in args.runs]; good=[e for e in data if e['valid']]
    cal=[e for e in good if e['kind']=='calibration']; exp=[e for e in good if e['kind']=='immediate_cutover']; curve=[]
    for rate in sorted({e['computed']['rate'] for e in cal}):
        group=[e for e in cal if e['computed']['rate']==rate]
        curve.append({'offered_rate':rate,'independent_runs':len(group),'p95_ms':run_uncertainty([e['computed']['successful_p95_ms'] for e in group]),'all_offer_violations_by_run':[e['computed']['all_offer_latency_violations'] for e in group],'eligible':len(group)>=3 and len({(e['source'],e['manifest']['config_sha256']) for e in group})==1 and all(e['computed']['capacity_eligible'] for e in group)})
    safe=select_capacity(curve); paired=[]
    for pair in sorted({e['pair_id'] for e in exp if e['pair_id']}):
        c=[e for e in exp if e['pair_id']==pair and e['condition']=='control']; i=[e for e in exp if e['pair_id']==pair and e['condition']=='immediate']
        if len(c)!=1 or len(i)!=1: continue
        errors=pair_check(c[0],i[0]); a=c[0]['computed']['transition']; b=i[0]['computed']['transition']
        paired.append({'pair_id':pair,'valid':not errors,'errors':errors,'control':c[0]['run_id'],'immediate':i[0]['run_id'],'p95_delta_ms':b['successful_p95_ms']-a['successful_p95_ms'],'db_attempt_delta':b['database_attempts']-a['database_attempts'],'control_p95_ms':a['successful_p95_ms'],'immediate_p95_ms':b['successful_p95_ms'],'control_violations':a['all_offer_latency_violations'],'immediate_violations':b['all_offer_latency_violations']})
    summary={'selected_c_safe_foreground_rps':safe,'selection_rule':'3+ valid independent runs; every offer issued/completed, zero violations, p95 below configured target, max dispatch lag <=50ms; common probe overhead; duration-limited empirical boundary','calibration_curve':curve,'pairs':paired,'paired_p95_delta_uncertainty':run_uncertainty([p['p95_delta_ms'] for p in paired if p['valid']]),'invalid_runs':[e['run_id'] for e in data if not e['valid']],'valid_runs':len(good),'replication_unit':'independent physically recreated run; requests are descriptive within-run observations','source_identities':sorted({e['source'] for e in good})}
    for name,value in (('validation.json',data),('summary.json',summary)):
        (out/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    write_csv(out/'calibration.csv',[{'run_id':e['run_id'],'rate':e['computed']['rate'],'p95_ms':e['computed']['successful_p95_ms'],'violations':e['computed']['all_offer_latency_violations'],'issued':e['computed']['issued'],'probes':e['computed']['issued_observation_db_attempts'],'dispatch_p95_ms':e['computed']['dispatch_lag_p95_ms'],'dispatch_max_ms':e['computed']['dispatch_lag_max_ms']} for e in cal])
    write_csv(out/'expansion.csv',[{'run_id':e['run_id'],'condition':e['condition'],'window':w,**e['computed'][w]} for e in exp for w in ('pre_event','transition','post_event')])
    if cal: svg([(e['computed']['rate'],e['computed']['successful_p95_ms'],e['run_id']) for e in cal],out/'calibration_p95.svg','Actual PostgreSQL query with common probes')
    if exp: svg([(e['manifest']['offered_rate'],e['computed']['transition']['successful_p95_ms'],e['run_id']) for e in exp],out/'expansion_p95.svg','Matched immediate/control transition')
    print(json.dumps(summary,indent=2))
    return 1 if summary['invalid_runs'] or any(not p['valid'] for p in paired) else 0

if __name__=='__main__': raise SystemExit(main())
