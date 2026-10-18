"""Bounded independent review checks; writes only new reviewer evidence."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
REPORT = OUT / 'diagnostics.json'
if REPORT.exists() or (OUT / 'validator.json').exists():
    raise SystemExit('Reviewer evidence exists; refuse overwrite')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def command(argv: list[str], env=None) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    tick = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True,
                                text=True, timeout=15)
        return {'command': argv, 'started_utc': started,
                'elapsed_seconds': time.monotonic() - tick,
                'exit_code': result.returncode, 'stdout': result.stdout,
                'stderr': result.stderr}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'command': argv, 'started_utc': started,
                'elapsed_seconds': time.monotonic() - tick,
                'exit_code': None, 'error': str(error)}


source = read(ROOT / 'reports/source_state.json')
run = ROOT / 'runs/phase0-health-001'
before = {p.name: digest(p) for p in run.iterdir() if p.is_file()}
manifest = read(run / 'manifest.json')
run_source = read(run / 'source.json')
results = read(run / 'results.json')
config = read(ROOT / 'configs/environment.json')
events = [json.loads(line) for line in (run / 'events.jsonl').read_text().splitlines()]
canonical = json.dumps(source['files'], sort_keys=True, separators=(',', ':')).encode()
source_mismatches = [entry['path'] for entry in source['files']
                     if not (ROOT / entry['path']).is_file()
                     or digest(ROOT / entry['path']) != entry['sha256']]
checksum_mismatches = [name for name, value in read(run / 'checksums.json').items()
                      if not (run / name).is_file() or digest(run / name) != value]

checks = {
    'source_files_checked': len(source['files']),
    'source_mismatches': source_mismatches,
    'source_aggregate_matches': hashlib.sha256(canonical).hexdigest() == source['aggregate_sha256'],
    'execution_source_matches': source == run_source and manifest['source_sha256'] == source['aggregate_sha256'],
    'run_checksum_mismatches': checksum_mismatches,
    'config_hash_matches': manifest['config_sha256'] == digest(ROOT / 'configs/environment.json'),
    'effective_config_matches': config == read(run / 'effective_config.json'),
    'event_count': len(events),
    'result_count': len(results['checks']),
    'events_match_results': [{k: v for k, v in event.items() if k != 'utc'} for event in events] == results['checks'],
    'events_within_run': all(manifest['started_utc'] <= event['utc'] <= manifest['ended_utc'] for event in events),
    'payload_hashes_match': all(c['payload_sha256'] == hashlib.sha256(
        (f"phase0-{c['component']}".encode() if c['component'].startswith('cache-')
         else b'phase0-authoritative-value')).hexdigest() for c in results['checks']),
    'required_phase1_artifacts': {name: (ROOT / name).is_file() for name in
        ['docs/LITERATURE_MATRIX.md', 'docs/HYPOTHESES.md', 'reports/phase_01.md']},
    'paper_files': [p.relative_to(ROOT).as_posix() for p in (ROOT / 'paper').rglob('*') if p.is_file()],
    'source_sha256': source['aggregate_sha256'],
}
validator = command([sys.executable, '-B', 'scripts/validate_phase0.py',
                     '--run', 'runs/phase0-health-001',
                     '--output', 'reports/reviews/evidence/phase_01/validator.json'])
# Only the retained inline import check is executed, never the bootstrap installer.
ps = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
legacy = command([ps, '-NoProfile', '-Command',
    '& .\\.venv\\Scripts\\python.exe -B -c \'import redis.asyncio, psycopg, psycopg_pool, yaml; print("Runtime imports OK")\'; exit $LASTEXITCODE'])
fixed = command([sys.executable, '-B', 'scripts/check_runtime.py'])
review_env = dict(os.environ)
review_env['PYTHONPATH'] = str(ROOT / 'src')
duplicate = command([sys.executable, '-B', '-m', 'cache_scaleout', 'health',
                     '--config', 'configs/environment.json',
                     '--run-id', 'phase0-health-001'], env=review_env)
after = {p.name: digest(p) for p in run.iterdir() if p.is_file()}
checks['retained_run_unchanged'] = before == after
checks['source_unchanged_after_diagnostics'] = all(
    digest(ROOT / entry['path']) == entry['sha256'] for entry in source['files'])
output = {'captured_utc': datetime.now(timezone.utc).isoformat(),
          'boundary': 'No services started/stopped; no performance load; original run and implementation preserved.',
          'checks': checks, 'validator': validator, 'legacy_quoting_reproduction': legacy,
          'fixed_runtime_check': fixed, 'duplicate_run_reproduction': duplicate}
with REPORT.open('x', encoding='utf-8') as handle:
    json.dump(output, handle, indent=2)
    handle.write('\n')
print(json.dumps({'evidence': str(REPORT), 'checks': checks,
                  'validator_exit': validator['exit_code'], 'legacy_exit': legacy['exit_code'],
                  'fixed_exit': fixed['exit_code'], 'duplicate_exit': duplicate['exit_code']}))
