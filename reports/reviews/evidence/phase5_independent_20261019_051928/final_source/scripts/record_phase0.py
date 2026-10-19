"""Execute a named Phase 0 check and retain its exact command, outputs and exit code."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cache_scaleout.evidence import ROOT, command, utc_now, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--step', choices=['bootstrap', 'start', 'doctor', 'health', 'shutdown', 'fingerprint', 'validate'], required=True)
parser.add_argument('--record', type=Path, required=True)
parser.add_argument('--run-id', default='phase0-health-001')
parser.add_argument('--retry-of')
parser.add_argument('--output')
args = parser.parse_args()
if args.record.exists():
    raise SystemExit('Command record exists; choose a new path')
if args.step == 'validate':
    if not args.output:
        parser.error('validate requires --output')
    invocation = [sys.executable, 'scripts/validate_phase0.py', '--run', f'runs/{args.run_id}', '--output', args.output]
else:
    invocation = ['powershell.exe', '-NoProfile', '-File', f'scripts/{args.step}.ps1']
    if args.step == 'health':
        invocation += ['-RunId', args.run_id]
        if args.retry_of:
            invocation += ['-RetryOf', args.retry_of]
    elif args.output:
        invocation += ['-Output', args.output]
started = utc_now()
result = command(invocation, timeout=180)
result.update({'step': args.step, 'started_utc': started, 'ended_utc': utc_now()})
write_json(args.record, result)
print(result.get('stdout', ''))
print(result.get('stderr', ''), file=sys.stderr)
print(f"Recorded {args.step}: exit_code={result.get('exit_code')}; {args.record}")
raise SystemExit(result['exit_code'] if result.get('exit_code') is not None else 1)
