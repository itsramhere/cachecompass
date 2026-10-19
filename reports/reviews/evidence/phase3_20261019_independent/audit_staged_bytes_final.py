ï»¿"""Compare actual index blob bytes with final source and archived evidence."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).parent
source = json.loads((BASE/'source_publication.json').read_text())
original = json.loads((ROOT/'reports/evidence/phase3/source-final-002.json').read_text())
expected = {row['path']:row['sha256'] for row in source['files']}
for row in original['files']:
    name = (BASE/'original'/row['path']).relative_to(ROOT).as_posix()
    expected[name] = row['sha256']
staged = subprocess.run(['git','diff','--cached','--name-only','-z'],cwd=ROOT,check=True,capture_output=True).stdout.decode().split('\0')
for name in staged:
    if (name.startswith('runs/phase3-') or name.startswith('reports/evidence/phase3/')
            or name.startswith('reports/reviews/evidence/phase3_20261019_independent/')):
        path = ROOT/name
        if path.is_file():
            expected[name] = hashlib.sha256(path.read_bytes()).hexdigest()
names = sorted(expected)
data = subprocess.run(['git','cat-file','--batch'],cwd=ROOT,input=''.join(':'+name+'\n' for name in names).encode(),
                      check=True,capture_output=True).stdout
cursor = 0
mismatches = []
for name in names:
    header_end = data.index(b'\n',cursor)
    header = data[cursor:header_end].decode().split()
    if header[-1] == 'missing':
        mismatches.append(name)
        cursor = header_end+1
        continue
    size = int(header[-1])
    payload = data[header_end+1:header_end+1+size]
    if hashlib.sha256(payload).hexdigest() != expected[name]:
        mismatches.append(name)
    cursor = header_end+size+2
record = {'checked_index_blobs':len(names),'mismatches':mismatches,'all_bytes_preserved':not mismatches,
          'final_source_sha256':source['aggregate_sha256']}
with (BASE/'staged_byte_audit_final.json').open('x',encoding='utf-8') as f:
    json.dump(record,f,indent=2,sort_keys=True)
print(json.dumps(record))
raise SystemExit(1 if mismatches else 0)

