"""Expected policy-failure correctness run; no calibration or rate tuning."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'src'))
import yaml
from cache_scaleout.phase3 import load_phase3_config, run_phase3

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
config = load_phase3_config(ROOT/'configs/phase3_smoke.yaml')
config['purpose'] = 'Phase 3 expected no-background-grant policy failure; independent accounting check'
config['migration_grant']['donor_operations'] = 0
config['migration_grant']['background_db_operations'] = 0
config_path = Path(__file__).parent/'no_background_grant_final.yaml'
with config_path.open('x',encoding='utf-8') as f:
    yaml.safe_dump(config,f,sort_keys=False)
def service(script):
    subprocess.run(['powershell.exe','-NoProfile','-File','scripts/'+script+'.ps1'],cwd=ROOT,check=True)
try:
    service('shutdown')
    service('start')
    result = asyncio.run(run_phase3(config,config_path,'phase3-independent-no-grant-final-20261019','phase3-independent-no-grant-20261019'))
finally:
    service('shutdown')
accounting = json.loads((ROOT/'runs/phase3-independent-no-grant-final-20261019/failure_accounting.json').read_text())
manifest = json.loads((ROOT/'runs/phase3-independent-no-grant-final-20261019/manifest.json').read_text())
assert result == 1 and manifest['status'] == 'policy_failure', manifest
assert accounting['complete'] and accounting['all_issued_terminal'], accounting
assert accounting['offered'] == accounting['terminal'] == 10, accounting
assert accounting['issued_operations'] == accounting['issued_events'], accounting
print(json.dumps({'expected_policy_failure_verified':True,'accounting':accounting}))

