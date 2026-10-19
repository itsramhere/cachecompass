"""Retain exact commands, output and status without replacing prior records."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cache_scaleout.evidence import command, utc_now, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--retry-of', type=Path)
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Record already exists; choose a new path')
if args.retry_of and not args.retry_of.is_file():
    raise SystemExit('Retry record not found')
argv = args.command[1:] if args.command[:1] == ['--'] else args.command
if not argv:
    raise SystemExit('Command required after --')
started = utc_now()
result = command(argv, timeout=180)
write_json(args.output, {'started_utc':started, 'ended_utc':utc_now(), 'retry_of':str(args.retry_of) if args.retry_of else None, **result})
def emit(stream, value):
    data = (value + ('\n' if value and not value.endswith('\n') else '')).encode('utf-8', errors='replace')
    stream.buffer.write(data)
    stream.buffer.flush()

emit(sys.stdout, result.get('stdout', ''))
emit(sys.stderr, result.get('stderr', result.get('error','')))
raise SystemExit(result['exit_code'] if result['exit_code'] is not None else 1)
