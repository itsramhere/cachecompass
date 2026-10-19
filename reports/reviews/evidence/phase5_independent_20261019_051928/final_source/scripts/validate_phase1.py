"""Audit literature evidence and documented gate; not a semantic or performance proof."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cache_scaleout.evidence import source_fingerprint, utc_now, write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, default=ROOT / 'configs/literature_review.json')
parser.add_argument('--source-manifest', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--handoff', action='store_true')
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Validation output exists; choose a new path')
checks = []
def check(name, passed, detail=None):
    checks.append({'check':name, 'passed':bool(passed), **({'detail':detail} if detail else {})})
def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

try:
    config = json.loads(args.config.read_text(encoding='utf-8'))
    docs = {name:(ROOT / 'docs' / name).read_text(encoding='utf-8') for name in
            ['LITERATURE_MATRIX.md','BIBLIOGRAPHY.md','HYPOTHESES.md','CANDIDATE_CONTRIBUTION.md','LITERATURE_SEARCH.md']}
    bib = (ROOT / 'paper/references.bib').read_text(encoding='utf-8')
    check('unique_reference_ids', len({s['id'] for s in config['sources']})==len(config['sources']))
    check('five_mandatory_sources', {s['id'] for s in config['sources'] if s['required']}=={'R01','R02','R03','R04','R05'})
    for s in config['sources']:
        check(s['id']+':bibliography_identity', s['bib_key'] in bib and s['url'] in bib and s['id'] in docs['BIBLIOGRAPHY.md'])
        check(s['id']+':matrix_coverage', s['id'] in docs['LITERATURE_MATRIX.md'])
        if s['read_status'] != 'relevant_sections_read':
            check(s['id']+':explicit_unresolved', not s['required'] and not s['pdf_pages_read'] and s['issue']=='ISSUE-0004')
            continue
        directory = ROOT / s['evidence_dir']
        record = read(s['evidence_dir']+'/retrieval.json')
        manifest = read(str(Path(s['evidence_dir']).parent / 'manifest.json'))
        check(s['id']+':manifest_record', record in manifest['sources'] and record['status']=='retrieved_and_extracted' and record['url']==s['url'])
        for file, field in [('source.pdf','pdf_sha256'),('pages.json','pages_sha256'),('text.txt','text_sha256')]:
            check(s['id']+':'+file, sha(directory/file)==record[field])
        pages = read(s['evidence_dir']+'/pages.json')
        check(s['id']+':reading_coverage_in_bounds', bool(s['pdf_pages_read']) and bool(s['sections_read']) and
              all(1<=p<=len(pages) and pages[p-1]['text'].strip() for p in s['pdf_pages_read']))
    for run, cfg in [('phase1-fetch-001','literature_sources.json'),('phase1-fetch-002','literature_followups.json')]:
        directory = ROOT / 'reports/literature' / run
        manifest = read(str(directory.relative_to(ROOT) / 'manifest.json'))
        check(run+':config_hash', sha(ROOT/'configs'/cfg)==manifest['config_sha256'])
        check(run+':effective_config', read(str(directory.relative_to(ROOT)/'effective_config.json'))==read('configs/'+cfg))
        verification = read(str(directory.relative_to(ROOT)/'verification.json'))
        check(run+':verification', verification['passed'] and all(c['passed'] for c in verification['checks']))
    web = read('reports/literature/phase1-web-001/manifest.json')
    for record in web['checks']:
        check(record['id']+':retained_response_hash', sha(ROOT/'reports/literature/phase1-web-001'/record['response_file'])==record['sha256'])
    original = next(r for r in web['checks'] if r['id']=='adaptcache-publisher')
    check('adaptcache:failure_preserved', original['status']=='retrieval_failure' and original['http_status']==403)
    metadata = read('reports/literature/phase1-web-001/adaptcache-metadata.response')['message']
    check('adaptcache:verified_metadata_only', metadata['DOI']=='10.1145/2988336.2988343' and metadata['title']==['AdaptCache'] and
          metadata.get('subtitle')==['Adaptive Data Partitioning and Migration for Distributed Object Caches'] and
          [a['family'] for a in metadata['author']]==['Asad','Kemme'] and metadata['published']['date-parts'][0][0]==2016)
    guide = next(r for r in web['checks'] if r['id']=='guide-pinned')
    check('guide:pinned_before_cutoff', guide['commit']==config['engineering_sources'][0]['commit'] and
          guide['commit_date'][:10]<=config['search_cutoff'] and guide['commit'] in guide['url'])
    gate = config['gate']
    nearest = next(s for s in config['sources'] if s['id']==gate['nearest_verified_source'])
    check('gate:nearest_verified_direct', nearest['comparison_role']=='nearest_direct' and nearest['read_status']=='relevant_sections_read')
    check('gate:testable_difference_documented', gate['testable_differences']==['H1','H4'] and
          all(h in docs['HYPOTHESES.md'] for h in gate['testable_differences']) and 'incremental' in docs['CANDIDATE_CONTRIBUTION.md'])
    check('gate:refutation_and_adequate_simple_control', len(re.findall(r'^Refutation:',docs['HYPOTHESES.md'],re.M))==4 and
          'migration-before-cutover' in docs['HYPOTHESES.md'] and 'ample headroom' in docs['HYPOTHESES.md'])
    check('gate:overlap_disclosed', not gate['novelty_claim_supported'] and gate['study_mode']=='reproduction_inspired_characterization' and
          'G01' in docs['CANDIDATE_CONTRIBUTION.md'] and 'ISSUE-0004' in docs['CANDIDATE_CONTRIBUTION.md'])
    check('search:mechanism_queries_retained', (ROOT/'reports/evidence/phase1/search-reproduction-001.json').is_file())
    for name, text in docs.items():
        for link in re.findall(r'\]\(([^)]+)\)',text):
            if not re.match(r'https?://',link):
                check('link:'+name+':'+link, (ROOT/'docs'/link.split('#')[0]).is_file())
    prior = read('reports/source_state.json')
    protected = ['RESEARCH_IMPLEMENTATION_PLAN.md','AGENT_REPORTING_TEMPLATES.md']
    protected += [f['path'] for f in prior['files'] if f['path'].endswith('.md') and f['path'] not in
                  ['README.md','docs/SCOPE.md','docs/ENVIRONMENT_COMPATIBILITY.md']]
    for path in protected:
        expected = next(f['sha256'] for f in prior['files'] if f['path']==path)
        check('preserved:'+path, sha(ROOT/path)==expected)
    check('runtime_lock_preserved', sha(ROOT/'requirements.lock')==next(f['sha256'] for f in prior['files'] if f['path']=='requirements.lock'))
    captured = json.loads(args.source_manifest.read_text(encoding='utf-8'))
    # capture_source.py stores the source object directly.
    check('final_source_matches_manifest', source_fingerprint()==captured)
    check('isolated_tool_wheel_hash', sha(ROOT/'reports/tools/wheels/pypdf-6.1.1-py3-none-any.whl')==
          '7781f99493208a37a7d4275601d883e19af24e62a525c25844d22157c2e4cde7')
    if args.handoff:
        status = (ROOT/'reports/STATUS.md').read_text(encoding='utf-8')
        phase = (ROOT/'reports/phase_01.md').read_text(encoding='utf-8')
        check('handoff:complete_phase_record', 'Phase status: complete' in status and 'Status: complete' in phase and
              captured['aggregate_sha256'] in status and captured['aggregate_sha256'] in phase)
        check('handoff:access_limit_disclosed', 'ISSUE-0004' in status and 'ISSUE-0004' in phase)
except Exception as error:
    check('audit_exception', False, str(error))
passed = bool(checks) and all(c['passed'] for c in checks)
write_json(args.output, {'captured_utc':utc_now(), 'config':str(args.config), 'source_manifest':str(args.source_manifest),
           'passed':passed, 'checks':checks, 'boundary':'Artifact integrity, provenance and presence of manually assessed gate evidence only. Not independent semantic literature review, novelty proof, or performance validation.'})
print(json.dumps({'passed':passed, 'checks':len(checks), 'failed':[c for c in checks if not c['passed']], 'output':str(args.output)}))
raise SystemExit(0 if passed else 1)
