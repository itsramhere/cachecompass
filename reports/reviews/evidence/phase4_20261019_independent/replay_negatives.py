"""Fresh replay harness; original outputs/bytes are retained separately."""
import argparse, hashlib, json, os, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]; HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(); parser.add_argument('case',choices=('submission','expiry')); args=parser.parse_args()
archive=HERE/('original' if args.case=='submission' else 'confirmation_inputs')
manifest=json.loads((HERE/('submitted_identity.json' if args.case=='submission' else 'confirmation_archive_identity.json')).read_text())
for row in manifest['files']:
    if hashlib.sha256((archive/row['path']).read_bytes()).hexdigest()!=row['sha256']: raise RuntimeError('archive mismatch '+row['path'])
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(archive/'src'))
os.environ['P4_ANALYSIS_PATH']=str(archive/'analysis/phase4_analysis.py')
from tests import test_phase4_independent as t
import cache_scaleout.adapters as adapter
if Path(adapter.__file__).resolve()!=(archive/'src/cache_scaleout/adapters.py').resolve():
    raise RuntimeError('Replay imported the wrong adapter source')
if args.case=='submission':
    methods=['test_wrong_key','test_rewritten_scheduled_time','test_nonterminal','test_summary_is_recomputed','test_duplicate_offer','test_calibration_without_common_probes']
    suite=unittest.TestSuite([t.EvidenceNegatives(m) for m in methods]+[t.WorkloadTests(m) for m in ('test_zipf_parameter_changes_draws','test_requested_share_is_applied','test_failures_count_in_all_offer_denominator')])
    expected=(9,6,2)
else:
    suite=unittest.TestSuite([t.DatabaseExpiryRace('test_expired_acquisition_never_starts_or_quarantines_query')]); expected=(1,1,0)
result=unittest.TextTestRunner(verbosity=2).run(suite)
observed=(result.testsRun,len(result.failures),len(result.errors))
print(json.dumps({'fresh_replay':True,'case':args.case,'loaded_archive_source':manifest['aggregate_sha256'],'expected':expected,'observed':observed}))
raise SystemExit(0 if observed==expected else 1)
