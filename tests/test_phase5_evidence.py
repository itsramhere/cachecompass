"""Negative evidence tests recompute checks even after a forged artifact seal."""
import hashlib,json,shutil,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'analysis'))
from phase5_validation import validate


class Phase5EvidenceNegatives(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'run'
        shutil.copytree(ROOT/'runs/p5matrix_v1_20261019_smoke1',self.path)
    def tearDown(self):self.tmp.cleanup()
    def mutate_result(self,fn):
        p=self.path/'result.json';r=json.loads(p.read_text());fn(r);p.write_text(json.dumps(r))
        seal={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.path.iterdir() if p.is_file() and p.name!='checksums.json'}
        (self.path/'checksums.json').write_text(json.dumps(seal))
    def test_retained_raw_fixture_cannot_prove_bursts_without_token_leases(self):
        result=validate(self.path)
        self.assertFalse(result['valid'])
        self.assertFalse(result['review_eligible'])
        self.assertIn('legacy_burst_accounting',result['errors'])
    def test_missing_successful_payload_cannot_hide_behind_resealed_evidence(self):
        self.mutate_result(lambda r:r['payload_checks'][0].update(actual=None))
        self.assertIn('successful_payload_required',validate(self.path)['errors'])
    def test_fabricated_summary_is_recomputed(self):
        self.mutate_result(lambda r:r['summary'].update(completed=999))
        self.assertIn('raw_summary_recomputed',validate(self.path)['errors'])
    def test_early_token_issue_is_rejected(self):
        self.mutate_result(lambda r:r['migration_operations'][0].update(issued_ns=r['actions'][0]['action']['decided_at_ns']+1))
        self.assertIn('empty_start_cumulative_token_envelopes',validate(self.path)['errors'])
    def test_corrupt_expected_epoch_fails_route_replay(self):
        self.mutate_result(lambda r:r['transitions'][0].update(expected_epoch=999))
        self.assertFalse(validate(self.path)['valid'])
