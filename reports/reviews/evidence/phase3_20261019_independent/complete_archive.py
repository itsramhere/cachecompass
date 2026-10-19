import hashlib
import json
from pathlib import Path
import shutil

base = Path(__file__).parent
owner = json.loads(Path('reports/evidence/phase3/source-final-002.json').read_text())
copied = []
for row in owner['files']:
    target = base/'original'/row['path']
    if target.is_file():
        continue
    source = Path(row['path'])
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != row['sha256']:
        raise ValueError('Unarchived file changed since submitted manifest: '+row['path'])
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
    copied.append(row)
with (base/'archive_completion.json').open('x',encoding='utf-8') as f:
    json.dump({'reason':'Initial scoped rg copy omitted hidden/ignored and unmodified ancillary files; each current byte hash verified against submitted manifest before copying.',
               'copied':copied},f,indent=2)
print(len(copied))
