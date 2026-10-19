import hashlib, shutil, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]; HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import source_fingerprint, write_json
source=source_fingerprint()
target=HERE/'confirmation_inputs'; target.mkdir(exist_ok=False)
for row in source['files']:
    dest=target/row['path']; dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/row['path'],dest)
    if hashlib.sha256(dest.read_bytes()).hexdigest()!=row['sha256']: raise RuntimeError('archive mismatch')
write_json(HERE/'confirmation_archive_identity.json',source)
print(source['aggregate_sha256'])
