"""Independent, offline regression probes; implementation files are read only."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
import traceback
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'reports/tools/python'))
from cache_scaleout.evidence import source_fingerprint
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, obj):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(obj, handle, indent=2)
        handle.write('\n')

def invoke(script, args, opener=None):
    stdout, stderr = io.StringIO(), io.StringIO()
    argv = [str(ROOT / script), *map(str, args)]
    with patch.object(sys, 'argv', argv), redirect_stdout(stdout), redirect_stderr(stderr):
        def run():
            try:
                runpy.run_path(argv[0], run_name='__main__')
                return 0, None
            except SystemExit as error:
                return error.code, None
            except Exception:
                return 1, traceback.format_exc()
        if opener:
            with patch('urllib.request.urlopen', opener):
                code, error = run()
        else:
            code, error = run()
    return {'argv': argv, 'exit_code': code, 'exception': error,
            'stdout': stdout.getvalue(), 'stderr': stderr.getvalue()}

class Response(io.BytesIO):
    status = 200
    headers = {'Content-Type': 'application/pdf'}
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

# A single text-bearing synthetic PDF avoids extracting the literature corpus.
writer = PdfWriter()
page = writer.add_blank_page(width=200, height=200)
font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                         NameObject('/Subtype'): NameObject('/Type1'),
                         NameObject('/BaseFont'): NameObject('/Helvetica')})
page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
    DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
stream = DecodedStreamObject()
stream.set_data(b'BT /F1 12 Tf 10 100 Td (Reviewer synthetic text) Tj ET')
page[NameObject('/Contents')] = writer._add_object(stream)
buffer = io.BytesIO()
writer.write(buffer)
pdf = buffer.getvalue()

source_before = source_fingerprint()
seal = read(ROOT / 'reports/phase1-evidence-checksums.json')
prior_evidence = ROOT / 'reports/reviews/evidence/phase_01/completed_submission'
prior_hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in prior_evidence.rglob('*') if p.is_file()}
result = {'captured_utc': datetime.now(timezone.utc).isoformat(),
          'network': 'All retrieval probes mocked; no live HTTP requests.',
          'source_before': source_before}
cfg = OUT / 'mock_sources.json'
save(cfg, {'sources': [{'id': 'FAIL', 'url': 'https://review.invalid/fail'},
                      {'id': 'OK', 'url': 'https://review.invalid/ok'}]})

def mixed(request, **kwargs):
    if request.full_url.endswith('/fail'):
        raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden', {},
                                     io.BytesIO(b'reviewer 403 failure body'))
    return Response(pdf, request.full_url)

failed = OUT / 'pdf_mixed'
result['pdf_mixed'] = invoke('scripts/literature_sources.py',
    ['fetch', '--config', cfg, '--output', failed], mixed)
manifest = read(failed / 'manifest.json')
failed_record, ok_record = manifest['sources']
result['pdf_mixed']['assertions'] = {
    'exit_one_without_exception': result['pdf_mixed']['exit_code'] == 1 and result['pdf_mixed']['exception'] is None,
    'all_sources_accounted': len(manifest['sources']) == 2,
    'failure_record_retained': read(failed / 'FAIL/retrieval.json') == failed_record,
    'failure_status_type_body': failed_record['status'] == 'retrieval_failure' and
        failed_record['http_status'] == 403 and failed_record['error']['type'] == 'HTTPError' and
        failed_record['error']['body'] == 'reviewer 403 failure body',
    'success_record_retained': read(failed / 'OK/retrieval.json') == ok_record and
        ok_record['status'] == 'retrieved_and_extracted',
    'timings_present': all(r['ended_utc'] and r['elapsed_seconds'] >= 0 for r in manifest['sources'])}
failed_hashes = {str(p): sha(p) for p in failed.rglob('*') if p.is_file()}
retry = OUT / 'pdf_retry'
result['pdf_retry'] = invoke('scripts/literature_sources.py',
    ['fetch', '--config', cfg, '--output', retry, '--retry-of', failed / 'manifest.json'],
    lambda request, **kwargs: Response(pdf, request.full_url))
result['pdf_retry_verify'] = invoke('scripts/literature_sources.py',
    ['verify', '--config', cfg, '--output', retry])
result['pdf_retry']['assertions'] = {
    'exit_zero': result['pdf_retry']['exit_code'] == 0 and result['pdf_retry']['exception'] is None,
    'parent_link': read(retry / 'manifest.json')['retry_of'] == str(failed / 'manifest.json'),
    'parent_preserved': all(sha(Path(p)) == value for p, value in failed_hashes.items()),
    'retry_verification_passed': read(retry / 'verification.json')['passed']}

def web_opener(mode):
    def opener(request, **kwargs):
        url = request.full_url
        if 'raw.githubusercontent.com' in url:
            if mode == '503':
                raise urllib.error.HTTPError(url, 503, 'Service Unavailable', {}, io.BytesIO(b'reviewer 503 body'))
            return Response(b'# Reviewer mock pinned guide\n', url)
        if 'commits?' in url:
            data = (b'not JSON' if mode == 'invalid_metadata' else json.dumps([
                {'sha': 'a' * 40, 'commit': {'committer': {'date': '2026-07-21T00:00:00Z'}}}]).encode())
        else:
            data = b'{"reviewer_mock": true}'
        return Response(data, url)
    return opener

for mode in ('503', 'success', 'invalid_metadata'):
    target = OUT / ('web_' + mode)
    record = invoke('scripts/literature_web_checks.py', ['--output', target], web_opener(mode))
    record['manifest_present'] = (target / 'manifest.json').is_file()
    record['retained_files'] = sorted(p.name for p in target.iterdir())
    if record['manifest_present']:
        records = read(target / 'manifest.json')['checks']
        pinned = records[-1]
        record['assertions'] = {
            'exit_matches_outcome': record['exit_code'] == (1 if mode == '503' else 0) and record['exception'] is None,
            'four_requests_accounted': len(records) == 4,
            'all_response_hashes_match': all(sha(target / r['response_file']) == r['sha256'] for r in records),
            'pinned_status_correct': pinned['status'] == ('retrieval_failure' if mode == '503' else 'retrieved'),
            'pinned_commit_and_timing': pinned['commit'] == 'a' * 40 and pinned['elapsed_seconds'] >= 0,
            'failure_body_and_status': mode != '503' or (pinned['http_status'] == 503 and
                (target / pinned['response_file']).read_bytes() == b'reviewer 503 body')}
    result['web_' + mode] = record

result['phase1_audit'] = invoke('scripts/validate_phase1.py',
    ['--config', ROOT / 'configs/literature_review.json', '--source-manifest', ROOT / 'reports/source_state_phase1.json',
     '--output', OUT / 'validator.json', '--handoff'])
audit = read(OUT / 'validator.json')
result['phase1_audit'].update(checks=len(audit['checks']), passed=audit['passed'],
                             failed=[c for c in audit['checks'] if not c['passed']])
old = read(ROOT / 'reports/source_state_phase1.json')
old_files = {r['path']: r['sha256'] for r in old['files']}
result['changed_since_original_capture'] = [r['path'] for r in source_before['files']
                                          if old_files.get(r['path']) != r['sha256']]
metadata = read(ROOT / 'reports/literature/phase1-web-001/adaptcache-metadata.response')['message']
full_title = metadata['title'][0] + ': ' + metadata['subtitle'][0]
registry = read(ROOT / 'configs/literature_review.json')
result['citation_assertions'] = {
    'registry_full_title': next(s for s in registry['sources'] if s['id'] == 'R13')['title'] == full_title,
    'bibliography_full_title': full_title in (ROOT / 'docs/BIBLIOGRAPHY.md').read_text(encoding='utf-8'),
    'bibtex_full_title': full_title in (ROOT / 'paper/references.bib').read_text(encoding='utf-8'),
    'validator_subtitle_check_passed': next(c for c in audit['checks'] if c['check'] == 'adaptcache:verified_metadata_only')['passed']}
result['preservation'] = {
    'source_unchanged_by_review': source_fingerprint() == source_before,
    'sealed_evidence_count': len(seal['files']),
    'sealed_evidence_mismatches': [r['path'] for r in seal['files'] if sha(ROOT / r['path']) != r['sha256']],
    'seal_aggregate_valid': hashlib.sha256(json.dumps(seal['files'], sort_keys=True,
        separators=(',', ':')).encode()).hexdigest() == seal['aggregate_sha256'],
    'previous_reviewer_evidence_unchanged': all(sha(ROOT / p) == value for p, value in prior_hashes.items())}
save(OUT / 'checks.json', result)
print(json.dumps({k: v for k, v in result.items() if k not in ('source_before',)}, indent=2))
