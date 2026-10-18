"""Seal and independently rehash the Phase 1 evidence package (reports only)."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from cache_scaleout.evidence import utc_now, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['seal','verify'])
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--manifest', type=Path, default=ROOT/'reports/phase1-evidence-checksums.json')
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Evidence output exists; choose a new path')
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
if args.action == 'seal':
    paths = list((ROOT/'reports/literature').rglob('*'))
    paths += list((ROOT/'reports/evidence/phase1').rglob('*'))
    paths += [ROOT/'reports'/name for name in ['STATUS.md','phase_01.md','DECISIONS.md','ISSUE_INDEX.md',
        'issues/ISSUE-0004.md','source_state_phase1.json','verification-phase1.json','verification-phase1-handoff.json',
        'tools/wheels/pypdf-6.1.1-py3-none-any.whl']]
    paths = sorted({p for p in paths if p.is_file() and '__pycache__' not in p.parts})
    files = [{'path':p.relative_to(ROOT).as_posix(), 'sha256':sha(p)} for p in paths]
    canonical = json.dumps(files,sort_keys=True,separators=(',',':')).encode()
    value = {'captured_utc':utc_now(), 'files':files, 'aggregate_sha256':hashlib.sha256(canonical).hexdigest(),
        'boundary':'Retained Phase 1 reports, PDFs/text, raw responses, command/search evidence and extraction wheel; source/config hashes are separate. Seal record itself is outside its file list.'}
    write_json(args.output,value)
    print(json.dumps({'files':len(files),'aggregate_sha256':value['aggregate_sha256']}))
else:
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    checks = [{'path':f['path'],'passed':sha(ROOT/f['path'])==f['sha256']} for f in manifest['files']]
    canonical = json.dumps(manifest['files'],sort_keys=True,separators=(',',':')).encode()
    valid = all(c['passed'] for c in checks) and hashlib.sha256(canonical).hexdigest()==manifest['aggregate_sha256']
    write_json(args.output, {'captured_utc':utc_now(), 'manifest_sha256':sha(args.manifest),'passed':valid,
        'files':len(checks),'checks':checks,'aggregate_sha256':manifest['aggregate_sha256']})
    print(json.dumps({'passed':valid,'files':len(checks),'aggregate_sha256':manifest['aggregate_sha256']}))
    raise SystemExit(0 if valid else 1)
