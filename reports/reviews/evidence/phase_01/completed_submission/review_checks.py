"""Bounded Phase 1 review diagnostics; writes only new reviewer artifacts."""
from datetime import datetime, timezone
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
RESULT = OUT / 'checks.json'
if RESULT.exists():
    raise SystemExit('Reviewer evidence exists; refuse overwrite')
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'reports/tools/python'))
from cache_scaleout.evidence import source_fingerprint


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2)
        handle.write('\n')


def command(argv):
    started = datetime.now(timezone.utc).isoformat()
    tick = time.monotonic()
    completed = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=25,
                               env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    return {'command': argv, 'started_utc': started, 'elapsed_seconds': time.monotonic() - tick,
            'exit_code': completed.returncode, 'stdout': completed.stdout, 'stderr': completed.stderr}


def mocked_script(script, argv, urlopen):
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(sys, 'argv', [script, *argv]), patch('urllib.request.urlopen', urlopen), \
            redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            runpy.run_path(str(ROOT / script), run_name='__main__')
            exit_code, exception = 0, None
        except SystemExit as error:
            exit_code, exception = error.code, None
        except Exception as error:
            exit_code, exception = 1, {'type': type(error).__name__, 'message': str(error),
                                       'traceback': traceback.format_exc()}
    return {'script': script, 'arguments': argv, 'network': 'mocked; no network requests',
            'exit_code': exit_code, 'exception': exception,
            'stdout': stdout.getvalue(), 'stderr': stderr.getvalue()}


before = source_fingerprint()
manifest = read(ROOT / 'reports/source_state_phase1.json')
seal = read(ROOT / 'reports/phase1-evidence-checksums.json')
checks = {
    'captured_utc': datetime.now(timezone.utc).isoformat(),
    'source_file_count': len(manifest['files']),
    'source_sha256': manifest['aggregate_sha256'],
    'source_matches_capture': before == manifest,
    'evidence_seal_files': len(seal['files']),
    'evidence_seal_mismatches': [f['path'] for f in seal['files']
                               if not (ROOT / f['path']).is_file() or sha(ROOT / f['path']) != f['sha256']],
    'evidence_seal_aggregate_valid': hashlib.sha256(json.dumps(
        seal['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest() == seal['aggregate_sha256'],
}
checks['phase1_validator'] = command([sys.executable, '-B', 'scripts/validate_phase1.py',
    '--config', 'configs/literature_review.json', '--source-manifest', 'reports/source_state_phase1.json',
    '--output', str(OUT / 'validator_recorded.json'), '--handoff'])
checks['seal_validator'] = command([sys.executable, '-B', 'reports/evidence/phase1/seal_evidence.py',
    'verify', '--manifest', 'reports/phase1-evidence-checksums.json', '--output', str(OUT / 'seal_recorded.json')])
checks['phase0_validation_from_prior_attempt'] = read(OUT / 'phase0_validator.json')

# The isolated HTTPError reproductions exercise the submitted scripts unchanged.
fake_body = b'Reviewer mock access-denied response: preserve this diagnostic body.'
mock_config = OUT / 'mock_sources.json'
if not mock_config.exists():
    save(mock_config, {'sources': [{'id': 'MOCK403', 'url': 'https://review.invalid/paper.pdf'}]})


def always_forbidden(request, **kwargs):
    raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden',
                                 {'Content-Type': 'text/plain'}, io.BytesIO(fake_body))


failed_pdf = mocked_script('scripts/literature_sources.py',
    ['fetch', '--config', str(mock_config), '--output', str(OUT / 'mock_pdf_failure_recorded')], always_forbidden)
pdf_record_path = OUT / 'mock_pdf_failure_recorded/MOCK403/retrieval.json'
pdf_record = read(pdf_record_path) if pdf_record_path.is_file() else None
failed_pdf.update({'retrieval': pdf_record,
                  'manifest_preserved': (OUT / 'mock_pdf_failure_recorded/manifest.json').is_file(),
                  'retained_files': [p.name for p in (OUT / 'mock_pdf_failure_recorded/MOCK403').iterdir()],
                  'http_status_field_preserved': pdf_record is not None and pdf_record.get('http_status') == 403,
                  'response_body_preserved': any(p.is_file() and p.read_bytes() == fake_body
                      for p in (OUT / 'mock_pdf_failure_recorded/MOCK403').iterdir())})
checks['mock_pdf_http_failure'] = failed_pdf


class MockResponse(io.BytesIO):
    status = 200

    def __init__(self, data, url):
        super().__init__(data)
        self.url = url


def fail_pinned_guide(request, **kwargs):
    url = request.full_url
    if 'raw.githubusercontent.com' in url:
        raise urllib.error.HTTPError(url, 503, 'Service Unavailable', {}, io.BytesIO(fake_body))
    if 'commits?' in url:
        value = [{'sha': 'a' * 40, 'commit': {'committer': {'date': '2026-07-21T00:00:00Z'}}}]
    elif 'crossref.org' in url:
        value = {'message': {'title': ['AdaptCache']}}
    else:
        value = {'mock': 'prior request succeeded'}
    return MockResponse(json.dumps(value).encode(), url)


failed_guide = mocked_script('scripts/literature_web_checks.py',
    ['--output', str(OUT / 'mock_guide_failure')], fail_pinned_guide)
failed_guide.update({'manifest_preserved': (OUT / 'mock_guide_failure/manifest.json').is_file(),
                     'retained_files': [p.name for p in (OUT / 'mock_guide_failure').iterdir()],
                     'raw_error_body_preserved': any(p.is_file() and p.read_bytes() == fake_body
                         for p in (OUT / 'mock_guide_failure').iterdir())})
checks['mock_pinned_guide_failure'] = failed_guide

# One live publisher reproduction and bounded alternate/provenance diagnostics.
urls = [
    ('adaptcache_publisher', 'https://dl.acm.org/doi/10.1145/2988336.2988343'),
    ('adaptcache_metadata', 'https://api.crossref.org/works/10.1145/2988336.2988343'),
    ('guide_commit', 'https://api.github.com/repos/babushkai/system-design-patterns/commits/a6e583a999cbe9f8b82e688365a58bdd2f4d5687'),
    ('guide_pinned', 'https://raw.githubusercontent.com/babushkai/system-design-patterns/a6e583a999cbe9f8b82e688365a58bdd2f4d5687/04-caching/04-cache-stampede.md'),
]
checks['live_http'] = []
for name, url in urls:
    record = {'name': name, 'url': url, 'started_utc': datetime.now(timezone.utc).isoformat()}
    tick = time.monotonic()
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'paper2-literature-review/1.0'})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = response.read(1024 * 1024)
            record.update({'status': 'retrieved', 'http_status': response.status, 'resolved_url': response.url})
    except urllib.error.HTTPError as error:
        data = error.read(1024 * 1024)
        record.update({'status': 'retrieval_failure', 'http_status': error.code, 'error': str(error)})
    except Exception as error:
        data = str(error).encode()
        record.update({'status': 'retrieval_failure', 'error': str(error)})
    target = OUT / (name + '.response')
    with target.open('xb') as handle:
        handle.write(data)
    record.update({'response_file': target.name, 'sha256': sha(target),
                   'elapsed_seconds': time.monotonic() - tick})
    if name == 'guide_pinned' and record['status'] == 'retrieved':
        record['matches_retained_guide'] = sha(target) == sha(ROOT / 'reports/literature/phase1-web-001/guide.md')
    if name == 'guide_commit' and record['status'] == 'retrieved':
        metadata = json.loads(data)
        record['verified_commit'] = metadata['sha']
        record['committer_date'] = metadata['commit']['committer']['date']
    if name == 'adaptcache_metadata' and record['status'] == 'retrieved':
        metadata = json.loads(data)['message']
        record['title'] = metadata.get('title')
        record['subtitle'] = metadata.get('subtitle')
    checks['live_http'].append(record)
    print(json.dumps(record), flush=True)

checks['source_unchanged'] = before == source_fingerprint()
checks['sealed_originals_unchanged'] = all(sha(ROOT / f['path']) == f['sha256'] for f in seal['files'])
save(RESULT, checks)
print(json.dumps({'evidence': str(RESULT), 'source_matches': checks['source_matches_capture'],
                  'source_unchanged': checks['source_unchanged'],
                  'sealed_originals_unchanged': checks['sealed_originals_unchanged'],
                  'phase1_validator_exit': checks['phase1_validator']['exit_code']}))
