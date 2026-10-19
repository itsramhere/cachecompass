"""Non-overwriting independent review evidence runner."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'src'))
from cache_scaleout.evidence import source_fingerprint, utc_now

parser = argparse.ArgumentParser()
parser.add_argument('label')
parser.add_argument('--retry-of')
parser.add_argument('argv', nargs=argparse.REMAINDER)
args = parser.parse_args()
directory = Path(__file__).parent
target = directory / (args.label + '.json')
if target.exists():
    raise SystemExit('Evidence already exists')
argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
before = source_fingerprint()
started = utc_now()
start = time.monotonic()
if argv:
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=240)
    record = dict(command=argv, exit_code=result.returncode,
                  stdout=result.stdout.decode('utf-8', errors='replace'),
                  stderr=result.stderr.decode('utf-8', errors='replace'))
else:
    record = dict(exit_code=0)
record.update(started_utc=started, ended_utc=utc_now(), elapsed_seconds=time.monotonic()-start,
              retry_of=args.retry_of, source=before)
with target.open('x', encoding='utf-8') as output:
    json.dump(record, output, indent=2, sort_keys=True)
print(json.dumps({k:v for k,v in record.items() if k != 'source'}, ensure_ascii=True))
raise SystemExit(record['exit_code'])
