"""Independently rehash historical files and submitted source; never overwrite."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).parent
label = sys.argv[1]
output = BASE / (label+'.json')
if output.exists():
    raise SystemExit('Audit exists')
historical = json.loads((BASE/'historical_before.json').read_text(encoding='utf-8-sig'))
changes = []
for row in historical:
    path = ROOT / row['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest().lower() != row['sha256'].lower():
        changes.append(row['path'])
submitted = json.loads((ROOT/'reports/evidence/phase3/source-final-002.json').read_text())
if 'files' not in submitted:
    submitted = submitted['source']
original_changes = []
for row in submitted['files']:
    path = BASE/'original'/row['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        original_changes.append(row['path'])
result = {'historical_files':len(historical),'historical_changes':changes,
          'submitted_files':len(submitted['files']),'submitted_sha256':submitted['aggregate_sha256'],
          'submitted_archive_mismatches':original_changes,'preserved':not changes and not original_changes}
with output.open('x',encoding='utf-8') as f:
    json.dump(result,f,indent=2,sort_keys=True)
print(json.dumps(result))
raise SystemExit(0 if result['preserved'] else 1)
