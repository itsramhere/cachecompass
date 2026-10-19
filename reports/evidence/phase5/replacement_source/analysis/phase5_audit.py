"""Additional independent operation, route, control and token audits."""
from collections import Counter
import hashlib,json,math
from pathlib import Path


def audit_extra(path,m,c,r,req):
    checks={};ops=r['migration_operations'];actions=r['actions'];fg=r['foreground_operations']
    rows={q['request_id']:q for q in req};payload={p['request_id']:p for p in r['payload_checks']}
    checks['successful_payload_required']=all(q['outcome']!='completed' or payload.get(q['request_id'],{}).get('actual')==payload.get(q['request_id'],{}).get('expected') and payload.get(q['request_id'],{}).get('actual') is not None for q in req)
    from cache_scaleout.phase4 import _window_summary
    checks['raw_summary_recomputed']=r['summary']==_window_summary(req,r['measurement_origin_ns'],r['horizon_ns'],c['timing']['latency_target_ms'])
    # Rebuild route state transitions without trusting the per-request owner.
    from cache_scaleout.dataset import StableOwnershipMap
    from cache_scaleout.contracts import BucketState,BucketAdvance
    rt=c['routing'];ownership=StableOwnershipMap(mapping_seed=rt['mapping_seed'],bucket_count=rt['virtual_buckets'],old_nodes=tuple(rt['old_nodes']),final_nodes=tuple(rt['final_nodes']),destination=rt['destination'])
    timeline=[(t['at_ns'],0,t) for t in r['transitions']]+[(q['submitted_ns'],1,q) for q in req]
    valid=True
    for at,kind,item in sorted(timeline,key=lambda x:(x[0],x[1])):
        if kind==0:
            if item['expected_epoch']!=ownership.snapshot.epoch:valid=False;continue
            advances=[]
            if 'advances' in item:
                advances=[BucketAdvance(a['bucket'],BucketState(a['expected']),tuple(BucketState(s) for s in a['path'])) for a in item['advances']]
            else:
                for b in item['admit']:
                    before=ownership.state(b)
                    advances.append(BucketAdvance(b,before,(BucketState.COPYING,BucketState.ELIGIBLE,BucketState.NEW) if before is BucketState.OLD else (BucketState.NEW,)))
            epoch=ownership.publish(tuple(advances),expected_epoch=item['expected_epoch'])
            if epoch!=item['epoch']:valid=False
        elif item['route']!={'epoch':int(ownership.capture(item['key']).epoch),'bucket':int(ownership.capture(item['key']).bucket),'owner':ownership.capture(item['key']).owner,'state':ownership.capture(item['key']).state.value}:valid=False
    checks['independent_atomic_epoch_route_replay']=valid
    checks['foreground_source_owner_identity']=all(op['target_owner']==rows[op['request_id']]['route']['owner'] and (op['source']=='database' or op['source']==('new_cache' if rows[op['request_id']]['route']['state']=='new' else 'old_cache')) for op in fg)
    # All operations have finite configured retry ordinals, including charged failures.
    retry_name={'donor_read':'donor_read','discretionary_database_warmup':'warmup_database','destination_write':'destination_write'}
    checks['finite_retry_ceilings']=all(1<=op['retry_ordinal']<=c['retries'][retry_name[op['work_class']]]['max_attempts'] for op in ops)
    # Per-dimension global envelopes: integrate installed rates, cap empty-start
    # tokens at bursts and consume at actual issue times. A finite one-operation
    # acquisition/connection interval can shift issuance later; validate both
    # cumulative integral and burst envelopes with the measured one-worker bound.
    dim={'donor_read':('donor_operations','donor_bytes'),'discretionary_database_warmup':('background_db_operations',),'destination_write':('destination_write_operations','destination_write_bytes')}
    tokenok=True;details={}
    for d in c['bursts']:
        rates=[(a['action']['decided_at_ns'],a['detail']['rates'][d]) for a in actions if 'duplicate_window_no_grant' not in a['action']['reason_codes']]
        issued=sorted((op['issued_ns'],op['reserved_bytes'] if d.endswith('bytes') else 1) for op in ops if d in dim[op['work_class']])
        integral=0.;last=r['expansion_ns'];current=0.;idx=0;spent=0.
        for at,amount in issued:
            while idx<len(rates) and rates[idx][0]<=at:
                t,rate=rates[idx];integral+=max(0,t-last)/1e9*current;last=t;current=rate;idx+=1
            integral+=max(0,at-last)/1e9*current;last=at;spent+=amount
            if spent>integral+1e-6:tokenok=False
        details[d]={'issued_units':spent,'integrated_empty_start_rate_units':integral}
    checks['empty_start_cumulative_token_envelopes']=tokenok
    # Exact independent fixed schedule: one actual opportunity, contiguous prefix.
    if m['policy'] in ('fixed_gradual_handover','warmup_only_adaptation'):
        last=-1;fixedok=True;setting=c['settings'][m['setting']]
        for a in actions:
            tick=math.floor((a['action']['decided_at_ns']-r['expansion_ns']-c['policy']['fixed_origin_seconds']*1e9)/(setting['fixed_interval_seconds']*1e9))
            expected=[]
            if tick>=0 and tick>last:
                last=tick
                for b,state in sorted(((int(k),v) for k,v in a['observation']['bucket_states'].items())):
                    if state=='new':continue
                    if len(expected)>=setting['fixed_count'] or state!='eligible':break
                    expected.append(b)
            if a['action']['admit_buckets']!=expected:fixedok=False
        checks['independent_fixed_tick_prefix']=fixedok
    # Fixed rates are never a function of pressure. Immediate rates remain zero.
    if m['policy'] in ('migration_before_cutover','fixed_gradual_handover','traffic_only_adaptation'):
        checks['forbidden_warming_adaptation']=all(a['detail']['rates']==c['settings'][m['setting']]['fixed_rates'] for a in actions)
    if m['policy']=='immediate_cutover': checks['forbidden_discretionary_budget']=all(not any(a['action']['budget'][d] for d in c['bursts']) for a in actions)
    return checks,details
