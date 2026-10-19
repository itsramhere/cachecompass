"""Execute the predeclared finite grid, select a common profile, then fresh smoke."""
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
    write_json(out/'registration.json',{'utc':utc_now(),'source':source_fingerprint(),'protocol':'docs/PHASE5_INDEPENDENT_PROTOCOL.md','maximum_runs':23,'retry_prefix':a.retry_prefix,'total_db_attempt_rate':16,'tuning_seed':505,'smoke_seed':606})
    tuning={};records=[];capacity=None
    def one(short,policy,setting,seed,stage,boundary=None,mixed=None):
        name=f'{a.prefix}_{short}'
        args=['--policy',policy,'--setting',setting,'--seed',str(seed),'--stage',stage,'--total-db-rate','16']
        if mixed is not None:args+=['--mixed-foreground',str(mixed[0]),'--mixed-warmup',str(mixed[1])]
        elif capacity is not None:args+=['--capacity-record',str(out/'capacity.json')]
        if boundary:args+=['--boundary',boundary]
        code=cycle(name,args,out/(short+'_command.json'),retry_of=(f'{a.retry_prefix}_{short}' if a.retry_prefix and (ROOT/'runs'/f'{a.retry_prefix}_{short}').exists() else None))
        v=validate(ROOT/'runs'/name);write_json(out/(short+'_validation.json'),v)
        records.append(v);write_json(out/'progress.json',records)
        print(name,code,v['valid'],v['errors'],v['counts'],flush=True)
        if not v['valid'] or not v.get('review_eligible',True):raise RuntimeError('invalid measurement; matrix stops for diagnosis: '+name)
        return name,json.loads((ROOT/'runs'/name/'result.json').read_text())
    mixed_cases=[]
    from cache_scaleout.phase5 import load_config,capacity_signature
    for short,split in [('mixed12_2',(12.,2.)),('mixed10_4',(10.,4.))]:
        name,r=one(short,'immediate_cutover','A',505,'mixed',mixed=split)
        if not r['eligible']:raise RuntimeError('mixed operating setting failed: '+name)
        mixed_cases.append({'run_id':name,'result_sha256':__import__('hashlib').sha256((ROOT/'runs'/name/'result.json').read_bytes()).hexdigest()})
    capacity={'total_attempt_rate':16.,'observation_rate':2.,'reserve_rate':2.,'cases':mixed_cases,
        'source':source_fingerprint()['aggregate_sha256'],'signature':capacity_signature(load_config(ROOT/'configs/phase5_pilot.yaml')),
        'interpretation':'conditional short mixed-pool setting; neither saturation nor universal safety'}
    write_json(out/'capacity.json',capacity)
    aggregate={s:[0,0,0.] for s in ('A','B')}
    for index,policy in enumerate(BASELINES):
        options=[]
        for setting in ('A','B'):
            name,r=one(f'tune{index}{setting}',policy,setting,505,'tuning')
            score=(r['status']!='completed',r['summary']['all_offer_latency_violations'],r['handover_seconds'] if r['handover_seconds'] is not None else float('inf'),setting)
            options.append((score,setting,name))
            if policy!='immediate_cutover':
                aggregate[setting][0]+=int(r['status']!='completed')
                aggregate[setting][1]+=r['summary']['all_offer_latency_violations']
                aggregate[setting][2]+=r['handover_seconds'] if r['handover_seconds'] is not None else 8.
        selected=min(options)
        tuning[policy]={'selected_setting':selected[1],'options':[{'score':list(s),'setting':t,'run_id':n} for s,t,n in options]}
    selected_common='A' if all(v[0]==len(BASELINES)-1 for v in aggregate.values()) else min(aggregate,key=lambda s:(*aggregate[s],s))
    for value in tuning.values():
        value['individual_preference']=value['selected_setting'];value['selected_setting']=selected_common
        value['common_aggregate_scores']=aggregate
    write_json(out/'selections.json',tuning)  # durable before fresh comparison
    smoke=[]
    for index,policy in enumerate(BASELINES):
        name,r=one(f'smoke{index}',policy,tuning[policy]['selected_setting'],606,'smoke')
        smoke.append(ROOT/'runs'/name)
    pairing=matched(smoke);write_json(out/'matched_smoke.json',pairing)
    if not pairing['valid']:raise RuntimeError(pairing)
    one('boundary_zero','migration_before_cutover','A',606,'boundary','zero')
    one('boundary_deadline','fixed_gradual_handover','A',606,'boundary','deadline')
    one('boundary_nonprogress','traffic_only_adaptation','A',606,'boundary','nonprogress')
    write_json(out/'complete.json',{'records':records,'matched':pairing,'source':source_fingerprint(),'utc':utc_now()})

if __name__=='__main__':main()
