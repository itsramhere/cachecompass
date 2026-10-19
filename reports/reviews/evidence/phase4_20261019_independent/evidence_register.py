"""Append-only classification/replacement overlay; never rewrites original runs."""
import hashlib, importlib.util, json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[4]; HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import write_json,utc_now,source_fingerprint
spec=importlib.util.spec_from_file_location('analysis4',ROOT/'analysis/phase4_analysis.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
entries=[]
for run in sorted((ROOT/'runs').glob('p4*')):
    status=a.read(run/'status.json') if (run/'status.json').exists() else {'status':'missing'}
    manifest=a.read(run/'manifest.json') if (run/'manifest.json').exists() else {}
    name=run.name
    if name.startswith('p4final_'):
        check=a.validate(run); use='corrected_confirmation' if 'headroom' not in name else 'separate_headroom_diagnostic'
        scientific_status=status['status'] if check['valid'] else 'invalid_measurement'
        reason='raw validator verdict'; errors=check['errors']
    elif name.startswith('p4review_'):
        errors=[]; use='superseded_first_review_matrix'; scientific_status='invalid_measurement'
        reason='ISSUE-0025 changed issuance/observation timing; entire matrix replaced, including favorable runs'
        if 'pilot' in name or 'diagnostic' in name:
            use='diagnostic_only'; scientific_status=status['status']; reason='not in frozen confirmation matrix'
        if name.startswith('p4review_cal36_'):
            scientific_status='infrastructure_failure'; reason='DB adapter orphan/quarantine/issuance stop; original completed label superseded by this overlay'
    else:
        errors=[]; use='historical_submission_only'; scientific_status='invalid_measurement'
        reason='ISSUE-0023/0024: corrected accounting/workload/stability claims require fresh runs'
        if 'pilot' in name: reason+='; exploratory pilot, not confirmation'
    entries.append({'run_id':name,'original_status':status,'scientific_status':scientific_status,'use':use,'reason':reason,
        'retry_of':manifest.get('retry_of'),'source_fingerprint':manifest.get('source_fingerprint'),'errors':errors})
commands=[]
for path in sorted(HERE.glob('*.json')):
    value=a.read(path)
    if isinstance(value,dict) and 'command' in value and 'exit_code' in value:
        commands.append({'record':path.relative_to(ROOT).as_posix(),'command':value['command'],'exit_code':value['exit_code']})
write_json(HERE/'evidence_register_final.json',{'updated_utc':utc_now(),'runs':entries,'command_index':commands,
    'rule':'Overlay classifications do not mutate historical evidence. All original labels/bytes remain retained.'})
source=source_fingerprint(); target=HERE/'final_inputs'; target.mkdir(exist_ok=False)
for row in source['files']:
    data=(ROOT/row['path']).read_bytes(); dest=target/row['path']; dest.parent.mkdir(parents=True,exist_ok=True)
    # Archive bytes through copyfile; source/data editing is not performed here.
    import shutil
    shutil.copyfile(ROOT/row['path'],dest)
    if hashlib.sha256(dest.read_bytes()).hexdigest()!=row['sha256']: raise RuntimeError('final source archive mismatch')
write_json(HERE/'final_source_archive.json',source)
print(json.dumps({'source':source['aggregate_sha256'],'files':len(source['files']),'runs_classified':len(entries),'commands_indexed':len(commands)}))
