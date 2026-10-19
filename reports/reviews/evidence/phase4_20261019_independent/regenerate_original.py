"""Reproduce historical figures honestly without certifying their validity."""
import importlib.util
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[4]; HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import command, write_json
names=[f'p4cal_confirm_r{rate}_{rep}' for rate in (12,24,36) for rep in (1,2,3)]
names += [f'p4exp_confirm_{condition}_{rep}' for rep in (1,2,3) for condition in ('control','immediate')]
dest=HERE/'original_regeneration'
argv=[sys.executable,'-B',str(HERE/'original/analysis/phase4_analysis.py'),'--runs',*[str(ROOT/'runs'/n) for n in names],'--output',str(dest)]
r=command(argv,timeout=60)
compared=[]
if r['exit_code']==0:
    for p in sorted(dest.iterdir()):
        old=ROOT/'reports/analysis/phase4_confirmation_final'/p.name
        compared.append({'file':p.name,'original_exists':old.exists(),'byte_identical':old.exists() and old.read_bytes()==p.read_bytes()})
write_json(HERE/'original_regeneration_check.json',{'command':r,'comparisons':compared,
    'meaning':'Numerical/plot regeneration check only. Original validity and hard-coded capacity are not certified.'})
print(json.dumps(compared,indent=2))
raise SystemExit(r['exit_code'])
