"""Bounded exact command capture for the full replacement (not the 180s recorder)."""
import sys,json
from pathlib import Path
ROOT=Path('/workspace/cachecompass');sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import command,write_json,utc_now,source_fingerprint
p=ROOT/'reports/reviews/evidence/phase5_independent_20261019_051928';out=p/'replacement_command.json'
if out.exists():raise RuntimeError('fresh command record required')
live=json.loads((p/'live_final.json').read_text());source=source_fingerprint()
assert live['source_before']==live['source_after']==source
assert live['commands'][2]['returncode']==0 and live['services_stopped']
print(live['commands'][2]['stderr'][-150:],flush=True)
start=utc_now();argv=['.venv/bin/python','-B','scripts/phase5_matrix.py','--prefix','p5ind_20261019_m2','--retry-prefix','p5ind_20261019_m1']
r=command(argv,timeout=2100);write_json(out,{'started_utc':start,'ended_utc':utc_now(),'retry_of':str(p/'continuation_command.json'),'source_before':source,'source_after':source_fingerprint(),**r});print(r.get('stdout',''));print(r.get('stderr',r.get('error','')));raise SystemExit(r['exit_code'] if r['exit_code'] is not None else 1)
