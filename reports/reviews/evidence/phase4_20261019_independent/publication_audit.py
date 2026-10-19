"""Verify publication-only delta, byte preservation and final evidence links."""
import hashlib, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]; HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import source_fingerprint,write_json,utc_now
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
frozen=read(HERE/'final_confirmation_source.json'); current=source_fingerprint()
old={x['path']:x['sha256'] for x in frozen['files']}; new={x['path']:x['sha256'] for x in current['files']}
changed=sorted(k for k in old.keys()&new.keys() if old[k]!=new[k]); added=sorted(new.keys()-old.keys()); removed=sorted(old.keys()-new.keys())
archives=[x['path'] for x in frozen['files'] if digest(HERE/'final_inputs'/x['path'])!=x['sha256']]
historical=read(HERE/'historical_hashes.json'); history_bad=[x['path'] for x in historical if digest(ROOT/x['path'])!=x['sha256']]
link_errors=[]
docs=['README.md','reports/STATUS.md','reports/phase_04.md','reports/HANDOFF_PHASE4.md','reports/reviews/phase_04_independent_20261019_0354.md']
for relative in docs:
    p=ROOT/relative
    for link in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
        if link.startswith(('http:','https:','#')): continue
        target=link.split('#')[0].strip('<>')
        if not (p.parent/target).exists(): link_errors.append(relative+':'+link)
validation=read(ROOT/'reports/analysis/phase4_independent_final_20261019/validation.json')
run_bad=[e['run_id'] for e in validation if not e['valid'] or e['source']!=frozen['aggregate_sha256']]
test=read(HERE/'final_full_live_suite.json')
test_ok=test['exit_code']==0 and 'Ran 107 tests' in test['stderr'] and 'skipped=' not in test['stderr'] and test['source']['aggregate_sha256']==frozen['aggregate_sha256']
invalid=read(HERE/'invalid_analysis_exit.json'); invalid_summary=read(HERE/'invalid_analysis_check/summary.json')
invalid_ok=invalid['exit_code']==1 and invalid_summary['selected_c_safe_foreground_rps'] is None and len(invalid_summary['invalid_runs'])==1
git_args=['git','-c','core.whitespace=cr-at-eol','diff','--check']
from cache_scaleout.evidence import command
whitespace=command(git_args)
result={'updated_utc':utc_now(),'executed_source':frozen['aggregate_sha256'],'publication_source':current['aggregate_sha256'],
    'changed_inputs_since_execution':changed,'added_inputs':added,'removed_inputs':removed,
    'publication_only_delta_verified':changed==['.gitattributes','README.md'] and not added and not removed,
    'final_archived_files_checked':len(old),'archive_mismatches':archives,'historical_files_checked':len(historical),'historical_mismatches':history_bad,
    'broken_handoff_links':link_errors,'invalid_final_runs':run_bad,'frozen_107_live_checks_verified':test_ok,
    'invalid_analysis_rejected_with_null_capacity':invalid_ok,'whitespace_check':whitespace,
    'all_disposable_services_removed_evidence':['final_live_shutdown.json','p4final_headroom144_20261019.json','final_buffer_command.json']}
write_json(HERE/'publication_source.json',current)
write_json(HERE/'publication_verification.json',result)
commands=[]
for path in sorted(HERE.glob('*.json')):
    value=read(path)
    if isinstance(value,dict) and 'command' in value and 'exit_code' in value:
        commands.append({'record':path.name,'command':value['command'],'exit_code':value['exit_code']})
write_json(HERE/'command_index_publication.json',commands)
print(json.dumps(result,indent=2))
raise SystemExit(not result['publication_only_delta_verified'] or bool(archives or history_bad or link_errors or run_bad) or not test_ok or not invalid_ok or whitespace['exit_code']!=0)
