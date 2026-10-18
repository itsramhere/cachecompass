"""Finish review evidence after isolated failure-path diagnostics."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
import time
import traceback
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from cache_scaleout.evidence import source_fingerprint

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2)
        handle.write('\n')

record = {'captured_utc': datetime.now(timezone.utc).isoformat()}
source = read(ROOT / 'reports/source_state_phase1.json')
seal = read(ROOT / 'reports/phase1-evidence-checksums.json')
record['source'] = {'matches': source == source_fingerprint(), 'files': len(source['files']),
                    'sha256': source['aggregate_sha256']}
record['evidence_seal'] = {'files': len(seal['files']),
    'mismatches': [f['path'] for f in seal['files'] if sha(ROOT / f['path']) != f['sha256']],
    'aggregate_valid': hashlib.sha256(json.dumps(seal['files'], sort_keys=True,
        separators=(',', ':')).encode()).hexdigest() == seal['aggregate_sha256']}
record['audits'] = {}
for name in ('validator_recorded.json', 'seal_recorded.json', 'phase0_validator.json'):
    audit = read(OUT / name)
    record['audits'][name] = {'passed': audit['passed'], 'checks': len(audit['checks']),
                              'captured_utc': audit['captured_utc']}
record['pdf_failure_reproduction'] = read(OUT / 'mock_debug.json')
record['pdf_failure_artifacts'] = {
    'manifest_present': (OUT / 'mock_pdf_failure_debug/manifest.json').exists(),
    'retrieval_record_present': (OUT / 'mock_pdf_failure_debug/MOCK403/retrieval.json').exists(),
    'per_source_files': [p.name for p in (OUT / 'mock_pdf_failure_debug/MOCK403').iterdir()]}

class Response(io.BytesIO):
    status = 200
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

def fail_raw(request, **kwargs):
    url = request.full_url
    if 'raw.githubusercontent.com' in url:
        raise urllib.error.HTTPError(url, 503, 'Service Unavailable', {}, io.BytesIO(b'review mock failure body'))
    value = ([{'sha': 'a' * 40, 'commit': {'committer': {'date': '2026-07-21T00:00:00Z'}}}]
             if 'commits?' in url else {'mock': 'prior HTTP response successful'})
    return Response(json.dumps(value).encode(), url)

argv = ['scripts/literature_web_checks.py', '--output', str(OUT / 'mock_guide_failure_recorded')]
stdout, stderr = io.StringIO(), io.StringIO()
with patch.object(sys, 'argv', argv), patch('urllib.request.urlopen', fail_raw), \
        redirect_stdout(stdout), redirect_stderr(stderr):
    try:
        runpy.run_path(str(ROOT / 'scripts/literature_web_checks.py'), run_name='__main__')
        code, error = 0, None
    except SystemExit as exc:
        code, error = exc.code, None
    except Exception:
        code, error = 1, traceback.format_exc()
record['guide_failure_reproduction'] = {'command': argv, 'network': 'mocked', 'exit_code': code,
    'error': error, 'stdout': stdout.getvalue(), 'stderr': stderr.getvalue(),
    'manifest_present': (OUT / 'mock_guide_failure_recorded/manifest.json').exists(),
    'retained_files': [p.name for p in (OUT / 'mock_guide_failure_recorded').iterdir()]}

record['live_publisher_reproduction'] = {
    'url': 'https://dl.acm.org/doi/10.1145/2988336.2988343',
    'started_utc': '2026-10-09T18:25:30.170581+00:00', 'http_status': 403,
    'error': 'HTTP Error 403: Forbidden', 'response_file': 'adaptcache_publisher.response',
    'sha256': sha(OUT / 'adaptcache_publisher.response'),
    'record_boundary': 'Transcribed from retained tool output; original response preserved.'}
metadata = read(OUT / 'adaptcache_metadata.response')['message']
record['live_adaptcache_metadata'] = {'http_status': 200, 'title': metadata['title'],
    'subtitle': metadata['subtitle'], 'DOI': metadata['DOI'],
    'response_sha256': sha(OUT / 'adaptcache_metadata.response')}
record['review_probe_failures'] = [
    {'attempt': 1, 'observation': 'Reviewer expected a failed-PDF record; file absent, then FileNotFoundError.',
     'diagnosis': 'Separate mock_debug.py isolates submitted retriever AttributeError; original directories preserved.'},
    {'attempt': 2, 'observation': 'Reviewer truncated a large GitHub commit JSON at its 1 MiB response limit, then JSONDecodeError.',
     'diagnosis': 'Reviewer-only response-size handling error. Truncated response preserved; use bounded commit-list metadata. No implementation finding based on this failure.'}]

record['live_guide_checks'] = []
queries = [
    ('guide_commit_metadata', 'https://api.github.com/repos/babushkai/system-design-patterns/commits?sha=a6e583a999cbe9f8b82e688365a58bdd2f4d5687&per_page=1'),
    ('guide_pinned_verified', 'https://raw.githubusercontent.com/babushkai/system-design-patterns/a6e583a999cbe9f8b82e688365a58bdd2f4d5687/04-caching/04-cache-stampede.md')]
for name, url in queries:
    entry = {'url': url, 'started_utc': datetime.now(timezone.utc).isoformat()}
    tick = time.monotonic()
    try:
        with urllib.request.urlopen(urllib.request.Request(url,
                headers={'User-Agent': 'paper2-literature-review/1.0'}), timeout=12) as response:
            data = response.read(1024 * 1024)
            entry.update({'status': 'retrieved', 'http_status': response.status})
        if name == 'guide_commit_metadata':
            commit = json.loads(data)[0]
            entry['commit'] = commit['sha']
            entry['committer_date'] = commit['commit']['committer']['date']
        else:
            entry['matches_retained'] = hashlib.sha256(data).hexdigest() == sha(ROOT / 'reports/literature/phase1-web-001/guide.md')
    except urllib.error.HTTPError as exc:
        data = exc.read(1024 * 1024)
        entry.update({'status': 'retrieval_failure', 'http_status': exc.code, 'error': str(exc)})
    except Exception as exc:
        data = str(exc).encode()
        entry.update({'status': 'retrieval_failure', 'error': str(exc)})
    with (OUT / (name + '.response')).open('xb') as handle:
        handle.write(data)
    entry.update({'response_file': name + '.response', 'sha256': sha(OUT / (name + '.response')),
                  'elapsed_seconds': time.monotonic() - tick})
    record['live_guide_checks'].append(entry)

record['source_unchanged_after_diagnostics'] = source == source_fingerprint()
record['sealed_evidence_unchanged_after_diagnostics'] = all(sha(ROOT / f['path']) == f['sha256'] for f in seal['files'])
save(OUT / 'checks.json', record)
print(json.dumps(record, indent=2))
