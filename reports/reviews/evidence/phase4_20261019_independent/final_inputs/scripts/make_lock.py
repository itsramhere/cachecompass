"""Create a hash-locked requirements file from downloaded wheels, without installing them."""
import hashlib
from email.parser import BytesParser
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
lines = ['# CPython 3.12 / Windows amd64; wheel-only hashes. Regenerate deliberately, never during bootstrap.']
for wheel in sorted((root / '.wheelhouse').glob('*.whl')):
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))
        metadata = BytesParser().parsebytes(archive.read(metadata_path))
    lines.append(f"{metadata['Name']}=={metadata['Version']} --hash=sha256:{hashlib.sha256(wheel.read_bytes()).hexdigest()}")
if len(lines) == 1:
    raise SystemExit('No wheels downloaded; refusing empty lock')
with (root / 'requirements.lock').open('x', encoding='utf-8', newline='\n') as stream:
    stream.write('\n'.join(lines) + '\n')
print(f'Locked {len(lines) - 1} wheels')

