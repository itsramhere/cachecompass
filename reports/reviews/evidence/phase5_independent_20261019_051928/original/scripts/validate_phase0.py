"""Validate retained Phase 0 health evidence, not later experiment accounting."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cache_scaleout.evidence import utc_now, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Validation evidence already exists; choose a new output')
checks = []
try:
    manifest = json.loads((args.run / 'manifest.json').read_text())
    checksums = json.loads((args.run / 'checksums.json').read_text())
    results = json.loads((args.run / 'results.json').read_text())
    source = json.loads((args.run / 'source.json').read_text())
    for name in ('manifest.json', 'results.json', 'source.json', 'effective_config.json', 'events.jsonl'):
        checks.append({'check': f'checksum:{name}', 'passed':
                       checksums.get(name) == hashlib.sha256((args.run / name).read_bytes()).hexdigest()})
    canonical = json.dumps(source['files'], sort_keys=True, separators=(',', ':')).encode()
    checks.append({'check': 'source_fingerprint', 'passed': source['aggregate_sha256'] ==
                   hashlib.sha256(canonical).hexdigest() == manifest['source_sha256']})
    checks.append({'check': 'identity', 'passed': manifest['run_id'] == args.run.name and
                   manifest['kind'] == 'phase0_service_health'})
    checks.append({'check': 'real_service_health', 'passed': manifest['status'] == 'completed' and
                   manifest['exit_code'] == 0 and results['error'] is None and len(results['checks']) == 4 and
                   all(c['status'] == 'verified' and c['cleanup_verified'] for c in results['checks'])})
    caches = [c for c in results['checks'] if c['component'].startswith('cache-')]
    checks.append({'check': 'three_independent_caches', 'passed': len(caches) == 3 and
                   len({c['server_run_id'] for c in caches}) == 3})
    if manifest.get('retry_of'):
        parent = args.run.parent / manifest['retry_of'] / 'manifest.json'
        checks.append({'check': 'retained_retry_parent', 'passed': parent.is_file()})
except Exception as error:
    checks.append({'check': 'artifact_read', 'passed': False, 'error': str(error)})
passed = all(c['passed'] for c in checks)
write_json(args.output, {'captured_utc': utc_now(), 'run': str(args.run), 'passed': passed,
                        'checks': checks, 'boundary': 'Phase 0 integrity and health only; no offered request accounting yet.'})
print(json.dumps({'passed': passed, 'checks': len(checks), 'output': str(args.output)}))
raise SystemExit(0 if passed else 1)

