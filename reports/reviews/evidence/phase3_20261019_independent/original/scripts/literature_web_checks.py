"""Capture bounded primary-source follow-up responses; never overwrite evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cache_scaleout.evidence import utc_now, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Evidence directory exists; choose a new ID')
args.output.mkdir(parents=True)
checks = [
    ('adaptcache-publisher', 'https://dl.acm.org/doi/10.1145/2988336.2988343'),
    ('adaptcache-metadata', 'https://api.crossref.org/works/10.1145/2988336.2988343'),
    ('guide-commit', 'https://api.github.com/repos/babushkai/system-design-patterns/commits?path=04-caching/04-cache-stampede.md&per_page=1'),
]
records = []
for name, url in checks:
    tick = time.monotonic()
    record = {'id': name, 'url': url, 'started_utc': utc_now()}
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'paper2-literature-review/1.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(4 * 1024 * 1024)
            record.update(status='retrieved', http_status=response.status, resolved_url=response.url)
    except urllib.error.HTTPError as error:
        data = error.read(4 * 1024 * 1024)
        record.update(status='retrieval_failure', http_status=error.code, error=str(error))
    except Exception as error:
        data = str(error).encode()
        record.update(status='retrieval_failure', error=str(error))
    target = args.output / (name + '.response')
    target.write_bytes(data)
    record.update(response_file=target.name, sha256=hashlib.sha256(data).hexdigest(), ended_utc=utc_now(), elapsed_seconds=time.monotonic()-tick)
    records.append(record)
    if name == 'guide-commit' and record['status'] == 'retrieved':
        try:
            commits = json.loads(data)
            if commits:
                sha = commits[0]['sha']
                raw_url = f'https://raw.githubusercontent.com/babushkai/system-design-patterns/{sha}/04-caching/04-cache-stampede.md'
                pinned_tick = time.monotonic()
                raw_record = {
                    'id': 'guide-pinned',
                    'url': raw_url,
                    'commit': sha,
                    'commit_date': commits[0]['commit']['committer']['date'],
                    'started_utc': utc_now()
                }
                try:
                    req = urllib.request.Request(raw_url, headers={'User-Agent': 'paper2-literature-review/1.0'})
                    with urllib.request.urlopen(req, timeout=30) as response:
                        raw = response.read(4 * 1024 * 1024)
                        raw_record.update(status='retrieved', http_status=response.status, resolved_url=response.url)
                except urllib.error.HTTPError as error:
                    raw = error.read(4 * 1024 * 1024)
                    raw_record.update(status='retrieval_failure', http_status=error.code, error=str(error))
                except Exception as error:
                    raw = str(error).encode()
                    raw_record.update(status='retrieval_failure', error=str(error))
                
                (args.output / 'guide.md').write_bytes(raw)
                raw_record.update(
                    response_file='guide.md',
                    sha256=hashlib.sha256(raw).hexdigest(),
                    ended_utc=utc_now(),
                    elapsed_seconds=time.monotonic() - pinned_tick
                )
                records.append(raw_record)
        except Exception as error:
            record['status'] = 'metadata_parsing_failure'
            record['error'] = f'Parsing failed: {str(error)}'
write_json(args.output / 'manifest.json', {'captured_utc':utc_now(), 'checks':records})
print(json.dumps(records, indent=2))
raise SystemExit(0 if all(r['status']=='retrieved' for r in records) else 1)
