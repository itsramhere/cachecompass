"""Exclusive review records and byte-preserving submission archive."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))
from cache_scaleout.evidence import command, source_fingerprint, utc_now, write_json

HERE = Path(__file__).resolve().parent

def preserve():
    source = source_fingerprint()
    target = HERE / 'original'
    target.mkdir(exist_ok=False)
    for entry in source['files']:
        dest = target / entry['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / entry['path'], dest)
    for name in ('STATUS.md', 'DECISIONS.md', 'ISSUE_INDEX.md', 'phase_04.md'):
        shutil.copy2(ROOT / 'reports' / name, target / name)
    hashes = []
    for base in (ROOT / 'runs', ROOT / 'reports' / 'analysis', ROOT / 'reports' / 'evidence' / 'phase4'):
        for path in sorted(base.rglob('*')):
            if path.is_file():
                hashes.append({'path':path.relative_to(ROOT).as_posix(), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    write_json(HERE / 'submitted_identity.json', source)
    write_json(HERE / 'historical_hashes.json', hashes)
    print(source['aggregate_sha256'], len(hashes))

def record(name, argv):
    path = HERE / (name + '.json')
    if path.exists():
        raise RuntimeError('record exists')
    started = utc_now()
    result = command(argv, timeout=900)
    write_json(path, {'started_utc':started, 'ended_utc':utc_now(), 'source':source_fingerprint(), **result})
    print(json.dumps({'name':name, **{k:v for k,v in result.items() if k not in ('stdout','stderr')}}), flush=True)
    print(result.get('stdout','')[-4000:], result.get('stderr','')[-2000:], flush=True)
    return result['exit_code']

if __name__ == '__main__':
    if sys.argv[1] == 'preserve':
        preserve()
    else:
        raise SystemExit(record(sys.argv[1], sys.argv[2:]))
