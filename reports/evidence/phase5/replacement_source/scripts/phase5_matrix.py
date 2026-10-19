"""Execute the predeclared finite grid, select per policy, then fresh smoke."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'analysis'),str(ROOT/'scripts')]
from cache_scaleout.baselines import BASELINES
from cache_scaleout.evidence import source_fingerprint,write_json,utc_now
from phase5_cycle import cycle
from phase5_validation import validate,matched


def main():
    p=argparse.ArgumentParser();p.add_argument('--prefix',required=True);p.add_argument('--retry-prefix');a=p.parse_args()
    out=ROOT/'reports/evidence/phase5'/a.prefix
    out.mkdir(exist_ok=False)
    write_json(out/'registration.json',{'utc':utc_now(),'source':source_fingerprint(),'protocol':'docs/PHASE5_PILOT_PROTOCOL.md','maximum_runs':20,'retry_prefix':a.retry_prefix,'total_db_attempt_rate':16,'tuning_seed':505,'smoke_seed':606})
    tuning={};records=[]
    def one(short,policy,setting,seed,stage,boundary=None):
        name=f'{a.prefix}_{short}'
        args=['--policy',policy,'--setting',setting,'--seed',str(seed),'--stage',stage,'--total-db-rate','16']
        if boundary:args+=['--boundary',boundary]
        code=cycle(name,args,out/(short+'_command.json'),retry_of=(f'{a.retry_prefix}_{short}' if a.retry_prefix else None))
        v=validate(ROOT/'runs'/name);write_json(out/(short+'_validation.json'),v)
        records.append(v);write_json(out/'progress.json',records)
        print(name,code,v['valid'],v['errors'],v['counts'],flush=True)
        if not v['valid']:raise RuntimeError('invalid measurement; matrix stops for diagnosis: '+name)
        return name,json.loads((ROOT/'runs'/name/'result.json').read_text())
    for index,policy in enumerate(BASELINES):
        options=[]
        for setting in ('A','B'):
            name,r=one(f'tune{index}{setting}',policy,setting,505,'tuning')
            score=(r['status']!='completed',r['summary']['all_offer_latency_violations'],r['handover_seconds'] if r['handover_seconds'] is not None else float('inf'),setting)
            options.append((score,setting,name))
        selected=min(options)
        tuning[policy]={'selected_setting':selected[1],'options':[{'score':list(s),'setting':t,'run_id':n} for s,t,n in options]}
    write_json(out/'selections.json',tuning)  # durable before fresh comparison
    smoke=[]
    for index,policy in enumerate(BASELINES):
        name,r=one(f'smoke{index}',policy,tuning[policy]['selected_setting'],606,'smoke')
        smoke.append(ROOT/'runs'/name)
    pairing=matched(smoke);write_json(out/'matched_smoke.json',pairing)
    if not pairing['valid']:raise RuntimeError(pairing)
    one('boundary_zero','migration_before_cutover','A',606,'boundary','zero')
    one('boundary_deadline','fixed_gradual_handover','A',606,'boundary','deadline')
    write_json(out/'complete.json',{'records':records,'matched':pairing,'source':source_fingerprint(),'utc':utc_now()})

if __name__=='__main__':main()
