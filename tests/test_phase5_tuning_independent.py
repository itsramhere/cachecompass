import contextlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import phase5_matrix as matrix


class TuningSelection(unittest.TestCase):
    def run_grid(self,all_fail=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'configs').mkdir();(root/'configs/phase5_pilot.yaml').write_text((ROOT/'configs/phase5_pilot.yaml').read_text());(root/'reports/evidence/phase5').mkdir(parents=True)
            def cycle(name,args,record_path,**kwargs):
                if '--mixed-foreground' in args:
                    p=root/'runs'/name;p.mkdir(parents=True);(p/'result.json').write_text(json.dumps({'eligible':True}));return 0
                policy=args[args.index('--policy')+1];setting=args[args.index('--setting')+1]
                preference='A' if policy=='fixed_gradual_handover' else 'B'
                result={'status':'policy_failure' if all_fail else 'completed','summary':{'all_offer_latency_violations':10 if all_fail and setting=='A' else 0},'handover_seconds':None if all_fail else 1. if setting==preference else 2.}
                p=root/'runs'/name;p.mkdir(parents=True);(p/'result.json').write_text(json.dumps(result));return int(all_fail)
            with patch.object(matrix,'ROOT',root),patch.object(matrix,'cycle',cycle),patch.object(matrix,'validate',lambda p:{'valid':True,'errors':[],'counts':{},'run_id':p.name}),patch.object(matrix,'matched',lambda p:{'valid':True}),patch.object(sys,'argv',['phase5_matrix','--prefix','stub']),contextlib.redirect_stdout(io.StringIO()):
                matrix.main()
            return json.loads((root/'reports/evidence/phase5/stub/selections.json').read_text())
    def test_all_fixed_components_use_same_selected_profile(self):
        s=self.run_grid()
        self.assertEqual(s['fixed_gradual_handover']['selected_setting'],s['warmup_only_adaptation']['selected_setting'])
        self.assertEqual(s['fixed_gradual_handover']['selected_setting'],s['traffic_only_adaptation']['selected_setting'])
    def test_both_failure_profiles_use_declared_A_fallback(self):
        s=self.run_grid(all_fail=True)
        self.assertTrue(all(v['selected_setting']=='A' for v in s.values()))
