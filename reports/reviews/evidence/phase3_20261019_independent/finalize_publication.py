"""Refresh living reports after byte-preserving Git metadata verification."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).parent
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import utc_now, source_fingerprint
def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))
old = read(BASE/'source_complete.json')
new = read(BASE/'source_publication.json')
tests = read(BASE/'tests_publication.json')
pair = read(BASE/'publication_pair_validation.json')
failure = read(BASE/'expected_failure_publication.json')
assert new['aggregate_sha256'] == source_fingerprint()['aggregate_sha256']
assert tests['exit_code'] == 0 and 'Ran 90 tests' in tests['stderr']
assert tests['source']['aggregate_sha256'] == new['aggregate_sha256']
assert pair['valid'] and failure['exit_code'] == 0
failure_accounting = read(ROOT/'runs/phase3-publication-no-grant-20261019/failure_accounting.json')
assert failure_accounting['complete'] and failure_accounting['all_issued_terminal']
before = {row['path']:row['sha256'] for row in old['files']}
after = {row['path']:row['sha256'] for row in new['files']}
changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
assert changed == {'.gitattributes','README.md'}, changed
for name in ['phase3-publication-a-20261019','phase3-publication-b-20261019','phase3-publication-no-grant-20261019']:
    assert read(ROOT/'runs'/name/'manifest.json')['source_sha256'] == new['aggregate_sha256']
timestamp = utc_now()
duration = re.search(r'Ran 90 tests in ([0-9.]+)s',tests['stderr']).group(1)
replacements = {
    old['aggregate_sha256']:new['aggregate_sha256'],
    'source_complete.json':'source_publication.json',
    'complete_source_capture.json':'publication_source_capture.json',
    'tests_complete.json':'tests_publication.json',
    'complete_cycle.json':'publication_cycle.json',
    'complete_pair_validation.json':'publication_pair_validation.json',
    'expected_failure_complete.json':'expected_failure_publication.json',
    'run_failure_case_complete.py':'run_failure_case_publication.py',
    'command_index.json':'command_index_publication.json',
    'phase3-independent-verified-a-20261019':'phase3-publication-a-20261019',
    'phase3-independent-verified-b-20261019':'phase3-publication-b-20261019',
    'phase3-independent-no-grant-verified-20261019':'phase3-publication-no-grant-20261019',
    'phase3-independent-final-a-20261019':'phase3-independent-verified-a-20261019',
    'phase3-independent-final-b-20261019':'phase3-independent-verified-b-20261019',
    '77 canonical':'78 canonical','77 files':'78 files','13.295 s':duration+' s'}
if failure_accounting['issued_operations'] != 317:
    replacements['317'] = str(failure_accounting['issued_operations'])
paths = [ROOT/'reports/STATUS.md',ROOT/'reports/phase_03.md',ROOT/'reports/DECISIONS.md',
         ROOT/'reports/reviews/phase_03_independent_20261019.md']
paths += [ROOT/f'reports/issues/ISSUE-{n:04d}.md' for n in range(17,21)]
backup = BASE/'before_publication'
backup.mkdir(exist_ok=False)
for path in paths:
    text = path.read_text()
    (backup/path.name).write_text(text,encoding='utf-8')
    for old_text,new_text in replacements.items():
        text = text.replace(old_text,new_text)
    if path.name == 'STATUS.md':
        text = re.sub(r'Updated: .*',f'Updated: {timestamp}',text,count=1)
        text = text.replace('Complete the explicitly authorized Phase 3 commit/push.',
                            'Phase 3 publication is authorized; the commit/push result is reported in the final handoff.')
    if path.name == 'phase_03_independent_20261019.md':
        text += f'''

## Byte-preserving publication verification

Updated {timestamp}. Git staging exposed newline conversion that would invalidate forensic SHA256 checks after checkout. Added `.gitattributes` for canonical inputs and Phase 3 evidence; the copied original ignore file's seven `test_out` artifacts are force-included as historical evidence. Original whitespace and newline bytes are intentionally preserved, not reformatted to satisfy style checks. The only canonical input changes after the preceding checkpoint are Git attributes and README links; runtime/config/test bytes are identical. Nevertheless, the full 90-check live suite, fresh reset pair and controlled failure were rerun with the final **78-file** SHA256 `{new['aggregate_sha256']}`. The preceding checkpoint report is retained under `before_publication/`. Final records are `tests_publication.json`, `publication_cycle.json`, `publication_pair_validation.json`, `expected_failure_publication.json` and `source_publication.json`. No Phase 4 work occurred.

The fresh `replay_submitted_negatives.py` harness hash-verifies all 80 archived submitted inputs, imports that archived runtime (not current modules), and reproduces all ten original runtime counterexamples. It is explicitly a fresh replay rather than a claim to preserve the initial test-file bytes. `replay_submitted_negatives.json` records ten expected assertion failures with no harness errors; the checker exits zero only after verifying that expected result. The original failing records remain unchanged.
'''
    path.write_text(text,encoding='utf-8')
summary = read(BASE/'review_summary.json')
summary.update(completed_utc=timestamp,source_sha256=new['aggregate_sha256'],source_files=len(new['files']),
               runs=['phase3-publication-a-20261019','phase3-publication-b-20261019'],
               failure_accounting=failure_accounting,
               source_delta_from_checkpoint=sorted(changed))
with (BASE/'publication_summary.json').open('x',encoding='utf-8') as f:
    json.dump(summary,f,indent=2,sort_keys=True)
commands = []
for path in sorted(BASE.glob('*.json')):
    try:
        record = read(path)
    except (ValueError,UnicodeError):
        continue
    if isinstance(record,dict) and 'command' in record:
        commands.append({'record':path.name, **{k:record.get(k) for k in
            ('command','exit_code','started_utc','ended_utc','elapsed_seconds','retry_of')},
            'source_sha256':record.get('source',{}).get('aggregate_sha256')})
with (BASE/'command_index_publication.json').open('x',encoding='utf-8') as f:
    json.dump(commands,f,indent=2,sort_keys=True)
print(json.dumps(summary,sort_keys=True))
