"""Retain exact adapter exceptions from a fresh constrained-load diagnostic."""
import argparse, asyncio, json, sys, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]; sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.adapters import PostgresDatabaseAdapter
from cache_scaleout.phase4 import load_phase4_config, run_calibration
from cache_scaleout.evidence import write_json
HERE=Path(__file__).resolve().parent
errors=[]
parser=argparse.ArgumentParser(); parser.add_argument('--rate',type=float,default=36); parser.add_argument('--suffix',default='')
args=parser.parse_args()
original=PostgresDatabaseAdapter._read
async def tracked(self,*args,**kwargs):
    try:
        return await original(self,*args,**kwargs)
    except BaseException as error:
        if len(errors)<30 or not isinstance(error,RuntimeError):
            errors.append({'error':repr(error),'traceback':traceback.format_exc(),'stopped':self._stopped,
                'quarantined':len(self._quarantined),'discarded_connections':self.discarded_connections})
        raise
PostgresDatabaseAdapter._read=tracked
if sys.platform=='win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
try:
    code=asyncio.run(run_calibration(load_phase4_config(ROOT/'configs/phase4_review.yaml'),ROOT/'configs/phase4_review.yaml','p4review_cleanup_diagnostic'+args.suffix+'_20261019',args.rate))
finally:
    write_json(HERE/('cleanup_diagnostic_errors'+args.suffix+'.json'),errors)
raise SystemExit(code)
