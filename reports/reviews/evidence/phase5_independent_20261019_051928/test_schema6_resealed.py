"""Adversarial replay of corrected actual-client records; historical bytes untouched."""
import hashlib,json,shutil,sys,tempfile,unittest
from pathlib import Path
ROOT=Path('/workspace/cachecompass');sys.path[:0]=[str(ROOT/'src'),str(ROOT/'analysis')]
from phase5_validation import validate
BASE='p5ind_20261019_m1_tune1A'

class CorrectedRawNegatives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        for short in ('mixed12_2','mixed10_4'):
            name='p5ind_20261019_m1_'+short;shutil.copytree(ROOT/'runs'/name,cls.root/name)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.path=self.root/self._testMethodName;shutil.copytree(ROOT/'runs'/BASE,self.path)
    def mutate(self,fn,filename='result.json',sync_actions=False):
        path=self.path/filename;data=json.loads(path.read_text());fn(data);path.write_text(json.dumps(data))
        if sync_actions:
            events=[json.loads(line) for line in (self.path/'events.jsonl').read_text().splitlines()];actions=iter(data['actions'])
            for event in events:
                if event['kind']=='policy_action':event['detail']=next(actions)
            (self.path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
        seal={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.path.iterdir() if p.is_file() and p.name!='checksums.json'}
        (self.path/'checksums.json').write_text(json.dumps(seal))
    def rejects(self,check):
        result=validate(self.path);self.assertIn(check,result['errors'],result);self.assertFalse(result['review_eligible'])
    def test_untampered_is_valid_and_eligible(self):
        result=validate(self.path);self.assertTrue(result['valid'],result);self.assertTrue(result['review_eligible'],result)
    def test_forged_pressure_even_with_synced_action_events(self):
        self.mutate(lambda r:r['actions'][-1]['observation']['db_pressure'].update(state='unsafe'),sync_actions=True);self.rejects('independent_raw_pressure_hysteresis')
    def test_freshened_component_timestamp(self):
        self.mutate(lambda r:r['actions'][-1]['observation']['db_pressure'].update(observed_at_ns=r['actions'][-1]['observation']['observed_at_ns']),sync_actions=True);self.rejects('independent_component_sample_freshness')
    def test_omitted_observation_charge(self):
        self.mutate(lambda r:r['actions'][0]['observation'].update(observation_db_rate_upper=0.),sync_actions=True);self.rejects('independent_single_observation_allowance')
    def test_changed_token_rates_cannot_hide_behind_correct_action(self):
        self.mutate(lambda r:next(e for e in r['token_events'] if e['kind']=='rates')['rates'].update(donor_operations=6400.));self.rejects('token_rates_match_published_actions')
    def test_acquire_before_tokens_exist(self):
        self.mutate(lambda r:next(e for e in r['token_events'] if e['kind']=='acquire').update(at_ns=r['expansion_ns']));self.rejects('independent_empty_start_burst_refund_replay')
    def test_issued_tokens_cannot_refund(self):
        def change(r):
            original=next(e for e in r['token_events'] if e['event_id']==r['migration_operations'][0]['token_event_id'])
            r['token_events'].append({'event_id':len(r['token_events']),'at_ns':r['token_events'][-1]['at_ns'],'kind':'refund','amounts':original['amounts'],'acquire_event_id':original['event_id']})
        self.mutate(change);self.rejects('no_issued_token_refunds')
    def test_unreconciled_token_lease(self):
        self.mutate(lambda r:r['token_events'].append({'event_id':len(r['token_events']),'at_ns':r['token_events'][-1]['at_ns'],'kind':'acquire','amounts':{'donor_operations':1}}));self.rejects('token_leases_fully_reconciled')
    def test_wrong_actual_source_payload(self):
        self.mutate(lambda r:r['migration_operations'][0].update(payload_sha256='0'*64));self.rejects('actual_migration_payload_provenance')
    def test_write_cannot_precede_its_source(self):
        def change(r):
            write=next(o for o in r['migration_operations'] if o['work_class']=='destination_write')
            parent=next(o for o in r['migration_operations'] if o['task_id']==write['parent_task_id']);parent['terminal_ns']=write['issued_ns']+1
        self.mutate(change);self.rejects('source_write_chronology')
    def test_forged_coverage(self):
        def change(r):
            coverage=next(iter(r['actions'][-1]['observation']['bucket_coverage'].values()));coverage['confirmed_warm_keys']+=1
        self.mutate(change,sync_actions=True);self.rejects('independent_residency_coverage_provenance')
    def test_observation_after_horizon(self):
        self.mutate(lambda r:r['observations'][-1].update(started_ns=r['horizon_ns']));self.rejects('no_new_observations_after_horizon')
    def test_changed_query_cannot_use_existing_capacity(self):
        self.mutate(lambda c:c['services']['database'].update(query_cpu_rounds=1),'effective_config.json');self.assertFalse(validate(self.path)['review_eligible'])
    def test_foreground_donor_shortcut(self):
        self.mutate(lambda r:r['foreground_operations'][0].update(target_owner='new'));self.rejects('foreground_source_owner_identity')
    def test_false_terminal_attempt_count(self):
        self.mutate(lambda r:r['pass_results'][0].update(attempts=100));self.rejects('per_key_terminal_accounting')
    def test_forged_foreground_upper_bound(self):
        self.mutate(lambda r:r['actions'][-1]['observation'].update(foreground_db_rate_upper=0.),sync_actions=True);self.rejects('independent_foreground_and_candidate_estimates')

if __name__=='__main__':unittest.main(verbosity=2)
