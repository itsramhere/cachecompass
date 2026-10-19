import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cache_scaleout.evidence import source_fingerprint, write_json

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Source evidence exists; choose a new output')
value = source_fingerprint()
write_json(args.output, value)
print(value['aggregate_sha256'])

