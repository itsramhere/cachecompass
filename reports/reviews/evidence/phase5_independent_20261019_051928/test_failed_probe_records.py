"""A failed observation is not an omitted offer or an impossible successful bundle."""
import hashlib,json,shutil,sys,tempfile,unittest
from pathlib import Path
ROOT=Path('/workspace/cachecompass');sys.path[:0]=[str(ROOT/'src'),str(ROOT/'analysis')]
from phase5_validation import validate
class FailedProbeRecords(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name in ('p5ind_20261019_m3_tune1A','p5ind_20261019_m3_mixed8_2','p5ind_20261019_m3_mixed6_4'):shutil.copytree(ROOT/'runs'/name,self.root/name)
        self.path=self.root/'p5ind_20261019_m3_tune1A'
    def tearDown(self):self.tmp.cleanup()
    def alter(self,component,failed):
        p=self.path/'result.json';r=json.loads(p.read_text());round=r['observations'][-1]
        if component=='new':
            r['cache_probes']['new'].pop()
            if failed:
                r['cache_probes']['new'][-1]['outcome']='timed_out';round['raw_cache_samples']['new']={'failed_at_ns':round['ended_ns'],'error':'TimeoutError'}
        else:
            r['db_probes'].pop()
            if failed:round['raw_database_sample']={'failed_at_ns':round['ended_ns'],'error':'TimeoutError'}
        if failed:round['samples'][component].update(state='unknown',reason='probe_failed:TimeoutError')
        p.write_text(json.dumps(r));events=[json.loads(s) for s in (self.path/'events.jsonl').read_text().splitlines()]
        for event in reversed(events):
            if event['kind']=='observation':event['detail']=round;break
        (self.path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        seal={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.path.iterdir() if p.is_file() and p.name!='checksums.json'};(self.path/'checksums.json').write_text(json.dumps(seal))
        return validate(self.path)
    def test_actual_failed_ping_has_no_info_and_remains_valid_measurement(self):
        r=self.alter('new',True);self.assertTrue(r['valid'],r['errors'])
    def test_unissued_db_probe_has_unknown_bundle_and_remains_valid_measurement(self):
        r=self.alter('database',True);self.assertTrue(r['valid'],r['errors'])
    def test_missing_info_from_successful_bundle_still_rejects(self):
        r=self.alter('new',False);self.assertFalse(r['valid'])
if __name__=='__main__':unittest.main(verbosity=2)
