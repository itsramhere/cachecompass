"""Complete replacement matrix after the reproduced DB deadline race fix."""
import os, sys
from review_driver import ROOT,HERE,record
from cache_scaleout.evidence import source_fingerprint,write_json,utc_now
PY=str(ROOT/'.venv/Scripts/python.exe'); os.environ['PYTHONPATH']=str(ROOT/'src'); os.environ['PAPER2_INTEGRATION']='1'
write_json(HERE/'final_confirmation_source.json',source_fingerprint())
failures=[]
def run(name,argv):
    if record(name,argv)!=0: failures.append(name)
run('final_live_start',['powershell.exe','-NoProfile','-File','scripts/start.ps1'])
try:
    run('final_full_live_suite',[PY,'-B','-m','unittest','discover','-s','tests','-p','test_*.py','-v'])
finally:
    run('final_live_shutdown',['powershell.exe','-NoProfile','-File','scripts/shutdown.ps1'])
for rep,rates in enumerate(((12,24,36),(36,12,24),(24,36,12)),1):
    for rate in rates:
        name=f'p4final_cal{rate}_{rep}_20261019'
        run(name,['powershell.exe','-NoProfile','-File','scripts/phase4_run.ps1','-Mode','calibrate','-RunId',name,'-Rate',str(rate),
            '-Config','configs/phase4_review.yaml','-RetryOf',f'p4review_cal{rate}_{rep}_20261019'])
    for condition in (('control','immediate') if rep%2 else ('immediate','control')):
        name=f'p4final_{condition}_{rep}_20261019'
        run(name,['powershell.exe','-NoProfile','-File','scripts/phase4_run.ps1','-Mode','immediate','-RunId',name,'-Rate','36',
            '-Condition',condition,'-Config','configs/phase4_review.yaml','-PairId',f'final-pair-{rep}','-RetryOf',f'p4review_{condition}_{rep}_20261019'])
name='p4final_headroom144_20261019'
run(name,['powershell.exe','-NoProfile','-File','scripts/phase4_run.ps1','-Mode','immediate','-RunId',name,'-Rate','144',
    '-Condition','control','-Config','configs/phase4_review.yaml','-RetryOf','p4review_headroom144_20261019'])
write_json(HERE/'final_matrix_completion.json',{'ended_utc':utc_now(),'failed_commands':failures,'source':source_fingerprint()})
print({'failed_commands':failures},flush=True)
raise SystemExit(bool(failures))
