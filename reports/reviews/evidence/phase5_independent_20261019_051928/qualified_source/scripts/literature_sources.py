"""Retain primary PDFs and extract page-indexed text, or verify a retained retrieval."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'reports/tools/python'))
from cache_scaleout.evidence import utc_now, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['fetch', 'verify'])
parser.add_argument('--config', type=Path, default=ROOT / 'configs/literature_sources.json')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--retry-of')
args = parser.parse_args()
config = json.loads(args.config.read_text(encoding='utf-8'))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

if args.action == 'fetch':
    from pypdf import PdfReader
    if args.output.exists():
        raise SystemExit('Retrieval ID already exists; choose a new directory')
    if args.retry_of and not Path(args.retry_of).is_file():
        raise SystemExit('Retry parent manifest not found')
    args.output.mkdir(parents=True)
    write_json(args.output / 'effective_config.json', config)
    def retrieve(source):
        destination = args.output / source['id']
        destination.mkdir()
        started, tick = utc_now(), time.monotonic()
        record = {**source, 'started_utc': started, 'status': 'retrieval_failure'}
        try:
            request = urllib.request.Request(source['url'], headers={'User-Agent':'paper2-literature-review/1.0'})
            with urllib.request.urlopen(request, timeout=35) as response:
                data = response.read(25 * 1024 * 1024)
                record.update({'http_status': response.status, 'resolved_url': response.url,
                               'content_type': response.headers.get('Content-Type')})
            if not data.startswith(b'%PDF'):
                (destination / 'response.bin').write_bytes(data)
                raise ValueError('Response is not a PDF; original response retained')
            pdf = destination / 'source.pdf'
            pdf.write_bytes(data)
            reader = PdfReader(pdf)
            pages = [{'pdf_page': i+1, 'text': page.extract_text() or ''} for i, page in enumerate(reader.pages)]
            write_json(destination / 'pages.json', pages)
            (destination / 'text.txt').write_text('\n\n'.join(f"=== PDF PAGE {p['pdf_page']} ===\n{p['text']}" for p in pages), encoding='utf-8')
            record.update({'status':'retrieved_and_extracted','pages':len(pages), 'pdf_sha256':digest(pdf),
                           'pages_sha256':digest(destination / 'pages.json'), 'text_sha256':digest(destination / 'text.txt')})
        except Exception as error:
            error_info = {'type': type(error).__name__, 'message': str(error)}
            if hasattr(error, 'code'):
                record['http_status'] = error.code
            if hasattr(error, 'read'):
                try:
                    body = error.read(4096)
                    if body:
                        error_info['body'] = body.decode('utf-8', 'replace')
                except Exception:
                    pass
            record['error'] = error_info
        record.update({'ended_utc':utc_now(), 'elapsed_seconds':time.monotonic()-tick})
        write_json(destination / 'retrieval.json', record)
        return record
    with ThreadPoolExecutor(max_workers=4) as executor:
        sources = list(executor.map(retrieve, config['sources']))
    manifest = {'captured_utc':utc_now(), 'config_sha256':digest(args.config), 'retry_of':args.retry_of,
                'sources':sources, 'boundary':'Extraction is not proof of manual relevant-section reading.'}
    write_json(args.output / 'manifest.json', manifest)
    print(json.dumps([{k:r.get(k) for k in ('id','status','pages','error')} for r in sources], indent=2))
    raise SystemExit(0 if all(r['status']=='retrieved_and_extracted' for r in sources) else 1)

manifest = json.loads((args.output / 'manifest.json').read_text())
checks = [
    {'check':'retrieval_config_hash', 'passed':digest(args.config)==manifest['config_sha256']},
    {'check':'effective_config', 'passed':json.loads((args.output / 'effective_config.json').read_text())==config},
    {'check':'source_ids', 'passed':[s['id'] for s in config['sources']]==[s['id'] for s in manifest['sources']]}
]
if manifest.get('retry_of'):
    checks.append({'check':'retry_parent_retained', 'passed':Path(manifest['retry_of']).is_file()})
for source in manifest['sources']:
    directory = args.output / source['id']
    checks.append({'source':source['id'], 'check':'retrieved', 'passed':source['status']=='retrieved_and_extracted'})
    if source['status'] == 'retrieved_and_extracted':
        for name, field in [('source.pdf','pdf_sha256'),('pages.json','pages_sha256'),('text.txt','text_sha256')]:
            checks.append({'source':source['id'], 'check':name, 'passed':digest(directory / name)==source[field]})
        pages = json.loads((directory / 'pages.json').read_text())
        checks.append({'source':source['id'],'check':'indexed_nonempty_pages',
                       'passed':len(pages)==source['pages'] and all(p['pdf_page']==i+1 and p['text'].strip() for i,p in enumerate(pages))})
passed = all(check['passed'] for check in checks)
verification = args.output / 'verification.json'
if verification.exists():
    raise SystemExit('Verification already exists; preserve it')
write_json(verification, {'captured_utc':utc_now(), 'passed':passed, 'checks':checks})
print(json.dumps({'passed':passed,'checks':len(checks),'verification':str(verification)}))
raise SystemExit(0 if passed else 1)
