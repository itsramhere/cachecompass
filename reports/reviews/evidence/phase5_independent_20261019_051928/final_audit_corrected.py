"""Independent final gate: raw rerun, protocol selection, byte/retry and preservation checks."""
import hashlib,json,sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path('/workspace/cachecompass');E=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'analysis')]
from cache_scaleout.evidence import source_fingerprint,write_json,utc_now
from cache_scaleout.dataset import create_dataset
from phase5_validation import validate,matched
PREFIX='p5ind_20261019_m3'

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def extra_operations(c,r):
    dataset=create_dataset(seed=c['dataset']['seed'],key_count=c['dataset']['keys'],value_bytes=c['dataset']['value_bytes']);by=dataset.by_key()
    migration=r.get('migration_operations',[])
    bound=all(op['reserved_bytes']==by[op['key']].object_bytes+1024 for op in migration)
    sizes=all(op.get('payload_bytes') is None or op['payload_bytes']==len(by[op['key']].payload) for op in migration)
    groups=defaultdict(list)
    for op in migration:groups[op['task_id']].append(op['retry_ordinal'])
    retry=all(values==list(range(1,len(values)+1)) for values in groups.values())
    charged=Counter()
    for op in migration:
        p={'donor_read':'donor','discretionary_database_warmup':'background_db','destination_write':'destination_write'}[op['work_class']]
        charged[p+'_operations']+=1
        if p!='background_db':charged[p+'_bytes']+=op['reserved_bytes']
    summary=all(r.get('grant_summary',{}).get('charged',{}).get(k,0)==v for k,v in {k:charged[k] for k in c['bursts']}.items())
    return {'exact_registry_encoded_reservations':bound,'actual_payload_sizes':sizes,'issued_stage_ordinals_no_gaps':retry,'grant_summary_actual_issue_reconciliation':summary}

def main():
    matrix=ROOT/'reports/evidence/phase5'/PREFIX;complete=read(matrix/'complete.json')
    source=read(E/'qualified_source.json');checks={};current=source_fingerprint();measured_files={r['path']:r['sha256'] for r in source['files']};current_files={r['path']:r['sha256'] for r in current['files']};publication_delta=[p for p in measured_files.keys()|current_files.keys() if measured_files.get(p)!=current_files.get(p)];checks['unchanged_runtime_and_experimental_inputs']=not (set(publication_delta)-{'analysis/phase5_validation.py'})
    rows=[];extras={};totals=Counter();smoke=[];all_disposed=True
    for item in complete['records']:
        path=ROOT/'runs'/item['run_id'];v=validate(path);m=read(path/'manifest.json');r=read(path/'result.json');c=read(path/'effective_config.json')
        rows.append(v);checks[path.name+'_qualified']=v['valid'] and v['review_eligible'] and (m['kind']!='mixed_pool' or r['eligible'])
        checks[path.name+'_source']=m['source_fingerprint']==source['aggregate_sha256']
        short=path.name[len(PREFIX)+1:];record=read(matrix/(short+'_command.json'))
        all_disposed &= record['services_stopped'] and record['source_before']==record['source_after']==source
        totals['offered']+=v['counts']['offered'];totals['database_attempts']+=v['counts']['db_attempts'];totals['db_probes']+=len(r['db_probes']);totals['cache_probes']+=sum(map(len,r['cache_probes'].values()))
        if m['kind']=='baseline':
            x=extra_operations(c,r);extras[path.name]=x
            checks[path.name+'_extra']=all(x.values())
        if m['stage']=='smoke':smoke.append(path)
    checks['all_cycles_disposed']=all_disposed
    pairing=matched(smoke);checks['complete_six_control_pairing']=pairing['valid'] and len(smoke)==6
    selections=read(matrix/'selections.json');aggregate={s:[0,0,0.] for s in ('A','B')}
    for policy,selection in sorted(selections.items(),key=lambda item:item[1]['options'][0]['run_id']):
        for option in selection['options']:
            r=read(ROOT/'runs'/option['run_id']/'result.json');s=option['setting']
            if policy!='immediate_cutover':
                aggregate[s][0]+=int(r['status']!='completed');aggregate[s][1]+=r['summary']['all_offer_latency_violations'];aggregate[s][2]+=r['handover_seconds'] if r['handover_seconds'] is not None else 8.
    selected='A' if all(a[0]==5 for a in aggregate.values()) else min(aggregate,key=lambda s:(*aggregate[s],s))
    checks['shared_preregistered_selection']=len(selections)==6 and all(s['selected_setting']==selected and s['common_aggregate_scores']==aggregate for s in selections.values())
    checks['finite_protocol_count']=len(rows)==24
    preserved=read(E/'preserved_before.json');allowed={'reports/STATUS.md','reports/DECISIONS.md','reports/ISSUE_INDEX.md','reports/phase_05.md','reports/HANDOFF_PHASE5.md','reports/issues/ISSUE-0027.md','reports/issues/ISSUE-0028.md'}
    changes=[p for p,h in preserved.items() if not (ROOT/p).exists() or sha(ROOT/p)!=h]
    unexpected=[p for p in changes if p not in allowed];checks['historical_preservation']=not unexpected
    supplemental=read(E/'superseded_review_hashes.json');lost=[p for p,h in supplemental.items() if not (ROOT/p).exists() or sha(ROOT/p)!=h];checks['superseded_review_preservation']=not lost
    submitted=read(E/'submitted_source.json');checks['submitted_archive_exact']=all(sha(E/'original'/r['path'])==r['sha256'] for r in submitted['files'])
    checks['qualified_archive_exact']=all(sha(E/'qualified_source'/r['path'])==r['sha256'] for r in source['files'])
    record={'utc':utc_now(),'valid':all(checks.values()),'checks':checks,'runs':rows,'extra_checks':extras,'matched':pairing,'totals':dict(totals),'selected_profile':selected,'aggregate_scores':aggregate,'source':source['aggregate_sha256'],
        'preservation':{'pre_review_files':len(preserved),'unchanged':len(preserved)-len(changes),'intentional_living_changes':changes,'unexpected_changes':unexpected,'superseded_review_files':len(supplemental),'superseded_changes':lost},'publication_source':current['aggregate_sha256'],'publication_delta':publication_delta,'audit_script_sha256':sha(Path(__file__))}
    out=E/'final_raw_preservation_audit_corrected.json'
    if out.exists():raise RuntimeError('fresh output required')
    write_json(out,record);print(json.dumps({k:record[k] for k in ('valid','totals','selected_profile','preservation')},indent=2));raise SystemExit(0 if record['valid'] else 1)
if __name__=='__main__':main()
