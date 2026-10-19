"""Independent arithmetic, provenance and token replay for Phase 5 artifacts."""
from collections import Counter,deque
import math
from cache_scaleout.dataset import create_dataset

DIMS=('donor_operations','donor_bytes','background_db_operations','destination_write_operations','destination_write_bytes')
CLASS_DIMS={'donor_read':('donor_operations','donor_bytes'),'discretionary_database_warmup':('background_db_operations',),'destination_write':('destination_write_operations','destination_write_bytes')}


def token_audit(c,r,*,legacy=False):
    operations=r['migration_operations'];checks={}
    if legacy:
        # Legacy artifacts lack acquisition/refund records. This bounded burst
        # check is additional accounting only, never review gate evidence.
        valid=True
        for dim in DIMS:
            credit=0.;rate=0.;previous=r['expansion_ns']
            timeline=[(a['action']['decided_at_ns'],0,a['detail']['rates'][dim]) for a in r['actions']]
            timeline += [(o['issued_ns'],1,o['reserved_bytes'] if dim.endswith('bytes') else 1) for o in operations if dim in CLASS_DIMS[o['work_class']]]
            for at,kind,value in sorted(timeline,key=lambda e:(e[0],e[1])):
                credit=min(c['bursts'][dim],credit+max(0,at-previous)/1e9*rate);previous=at
                if kind==0:
                    rate=value
                    if not rate:credit=0.
                else:
                    credit-=value
                    if credit < -1e-5:valid=False
        return {'legacy_burst_accounting':valid}
    events=r.get('token_events',[]);rates=dict.fromkeys(DIMS,0.);credit=dict.fromkeys(DIMS,0.)
    previous=None;acquired={};returned=set();valid=bool(events)
    for index,event in enumerate(events):
        at=event['at_ns']
        if event['event_id']!=index or previous is not None and at<previous:valid=False
        if previous is not None:
            for dim in DIMS:credit[dim]=min(c['bursts'][dim],credit[dim]+max(0,at-previous)/1e9*rates[dim])
        previous=at;kind=event['kind']
        if kind=='init':
            if index!=0 or event['bursts']!=c['bursts'] or any(event['rates'].values()):valid=False
        elif kind=='rates':
            rates=event['rates']
            if set(rates)!=set(DIMS) or any(not math.isfinite(v) or v<0 for v in rates.values()):valid=False
            for dim,value in rates.items():
                if value==0:credit[dim]=0.
        elif kind=='acquire':
            acquired[index]=event
            for dim,amount in event['amounts'].items():
                if type(amount) is not int or amount<1 or amount>c['bursts'][dim]:valid=False
                credit[dim]-=amount
                if credit[dim]<-1e-4:valid=False
        elif kind in ('refund','forfeit'):
            origin=event.get('acquire_event_id')
            if origin not in acquired or origin in returned or event['amounts']!=acquired[origin]['amounts']:valid=False
            returned.add(origin)
            if kind=='refund':
                for dim,amount in event['amounts'].items():
                    if rates[dim]>0:credit[dim]=min(c['bursts'][dim],credit[dim]+amount)
        else:valid=False
    seen=set()
    for op in operations:
        ticket=op.get('token_event_id');event=acquired.get(ticket)
        amounts={dim:op['reserved_bytes'] if dim.endswith('bytes') else 1 for dim in CLASS_DIMS[op['work_class']]}
        if event is None or event['amounts']!=amounts or ticket in seen or ticket in returned or event['at_ns']>op['issued_ns']:valid=False
        seen.add(ticket)
    checks['independent_empty_start_burst_refund_replay']=valid
    checks['no_issued_token_refunds']=not (seen & returned)
    installed=[e for e in events if e['kind']=='rates']
    checks['token_rates_match_published_actions']=len(installed)==len(r['actions']) and all(e['rates']==a['detail']['rates'] and a['action']['decided_at_ns']<=e['at_ns']<=a['detail']['published_at_ns'] for e,a in zip(installed,r['actions']))
    checks['token_leases_fully_reconciled']=set(acquired)==seen|returned
    return checks


def control_audit(m,c,r,requests):
    checks={};parameters=c['settings'][m['setting']];policy=m['policy'];adaptive_warm=policy in ('warmup_only_adaptation','adaptive_budget_migration_before_cutover')
    rates=dict.fromkeys(DIMS,0.);safe=dict.fromkeys(('db','donor','destination'),0);last_window=-1
    pending={};history=deque(maxlen=c['policy']['safe_windows']);last_fg_end=None;old_history=deque(maxlen=c['policy']['safe_windows'])
    valid_rates=True;valid_grants=True;valid_admissions=True;valid_estimates=True;valid_pending=True
    dt=c['timing']['observation_interval_seconds'];width=c['policy']['demand_windows']*dt
    previous_fixed=-1;fg=[o for o in r['foreground_operations'] if o['work_class']=='foreground_database'];by_request={q['request_id']:q for q in requests}
    for row in r['actions']:
        a=row['action'];o=row['observation'];detail=row['detail'];now=a['decided_at_ns'];window=o['demand']['window'];end=window['end_ns'];fresh=end>last_window
        states={name:('stale' if now-pressure['observed_at_ns']>o['max_signal_age_ns'] else pressure['state']) for name,pressure in (('db',o['db_pressure']),('donor',o['donor_pressure']),('destination',o['destination_pressure']))}
        known=o.get('foreground_db_known',o['foreground_db_observed_at_ns']>0)
        fresh_estimates=known and now-end<=window['max_age_ns'] and now-o['foreground_db_observed_at_ns']<=o['max_signal_age_ns']
        if fresh:
            if last_fg_end is not None and end-last_fg_end!=int(dt*1e9):history.clear();old_history.clear()
            history.append(sum(end-int(dt*1e9)<=op['issued_ns']<end for op in fg)/dt);last_fg_end=end
            counts={b:0. for b in o['old_owner_db_rate_lower']}
            for op in fg:
                q=by_request[op['request_id']];bucket=str(q['route']['bucket'])
                if end-int(dt*1e9)<=op['issued_ns']<end and q['route']['state']!='new' and bucket in counts:counts[bucket]+=1/dt
            old_history.append(counts)
            enough=len(history)==c['policy']['safe_windows'] and end-r['measurement_origin_ns']>=int(width*1e9)
            if m.get('schema_version',0)>=6 and known!=enough:valid_estimates=False
            for b,value in o['old_owner_db_rate_lower'].items():
                expected_lower=max(0,min(h[b] for h in old_history)-c['policy']['old_lower_margin']) if enough else 0.
                if abs(value-expected_lower)>1e-7:valid_estimates=False
            expected_fg=max(history)+c['policy']['foreground_margin']
            if abs(expected_fg-o['foreground_db_rate_upper'])>1e-7:valid_estimates=False
            if fresh_estimates:pending={b:value for b,value in pending.items() if window['start_ns']<value[1]}
            for name,state in states.items():safe[name]=safe[name]+1 if state=='safe' and (name!='db' or fresh_estimates) else 0
            if policy=='immediate_cutover':rates=dict.fromkeys(DIMS,0.)
            elif not adaptive_warm:rates=dict(parameters['fixed_rates'])
            else:
                for dim in DIMS:
                    name='donor' if dim.startswith('donor') else 'db' if dim.startswith('background') else 'destination'
                    if states[name]=='safe' and (name!='db' or fresh_estimates):
                        if safe[name]>=c['policy']['safe_windows']:rates[dim]=min(parameters['ceilings'][dim],rates[dim]+parameters['increments'][dim])
                    elif name=='donor' and states[name]=='unsafe':rates[dim]*=c['policy']['unsafe_donor_multiplier']
                    else:rates[dim]=0.
                if states['destination']!='safe':rates=dict.fromkeys(DIMS,0.)
                bound=max(0,c['policy']['safe_total_db_rate']-c['policy']['reserve_db_rate']-o['foreground_db_rate_upper']-max(o['pending_admission_db_rate_upper'],sum(v[0] for v in pending.values()))-o['observation_db_rate_upper'])
                rates['background_db_operations']=min(rates['background_db_operations'],bound)
        last_window=max(last_window,end)
        if fresh and any(abs(rates[d]-detail['rates'][d])>1e-6 for d in DIMS):valid_rates=False
        if fresh and any(a['budget'][d]!=math.floor(rates[d]*dt) for d in DIMS):valid_grants=False
        if not fresh and (a['admit_buckets'] or any(a['budget'][d] for d in DIMS)):valid_grants=False
        observed_pending=max(o['pending_admission_db_rate_upper'],sum(v[0] for v in pending.values()))
        if abs(detail['pending_before']-observed_pending)>1e-6:valid_pending=False
        ordered=sorted(int(b) for b in o['bucket_states']);states_b={int(b):v for b,v in o['bucket_states'].items()};expected=[]
        if fresh and policy=='immediate_cutover':expected=[b for b in ordered if states_b[b]!='new']
        elif fresh and 'migration_before_cutover' in policy:
            if all(v in ('eligible','new') for v in states_b.values()):expected=[b for b in ordered if states_b[b]=='eligible']
        elif fresh and policy in ('fixed_gradual_handover','warmup_only_adaptation'):
            slot=math.floor((now-r['expansion_ns']-c['policy']['fixed_origin_seconds']*1e9)/(parameters['fixed_interval_seconds']*1e9))
            if slot>=0 and slot>previous_fixed:
                previous_fixed=slot
                for b in ordered:
                    if states_b[b]=='new':continue
                    if states_b[b]!='eligible' or len(expected)>=parameters['fixed_count']:break
                    expected.append(b)
        elif fresh and policy=='traffic_only_adaptation' and fresh_estimates and all(v=='safe' for v in states.values()) and min(safe.values())>=c['policy']['safe_windows']:
            remaining=max(0,c['policy']['safe_total_db_rate']-c['policy']['reserve_db_rate']-o['foreground_db_rate_upper']-observed_pending-rates['background_db_operations']-o['observation_db_rate_upper'])
            for b in ordered:
                if states_b[b]!='eligible':continue
                coverage=o['bucket_coverage'][str(b)];denominator=coverage['observed_requests']+coverage['unknown_requests']
                fraction=coverage['confirmed_warm_requests']/denominator if denominator else 0.
                if now>=o.get('coverage_valid_until_ns',{}).get(str(b),o['observed_at_ns']+1):fraction=0.
                observed=sum(window['start_ns']<=q['submitted_ns']<end and q['route']['bucket']==b for q in requests)
                rate=c['policy']['alpha']*observed/width
                if abs(rate-o['candidate_request_rate_upper'][str(b)])>1e-7:valid_estimates=False
                cost=max(0,c['retries']['foreground_database']['max_attempts']*(rate*(1-fraction)+o['uncertain_miss_reserve_rate'][str(b)])-o['old_owner_db_rate_lower'][str(b)])
                if cost<=remaining and len(expected)<parameters['admission_cap']:
                    expected.append(b);remaining-=cost
                    pending[b]=(cost,detail.get('published_at_ns',a['decided_at_ns']))
        if a['admit_buckets']!=expected:valid_admissions=False
    checks.update(independent_control_rates=valid_rates,independent_interval_grants=valid_grants,
        independent_admissions_pressure_allowance_and_schedule=valid_admissions,independent_foreground_and_candidate_estimates=valid_estimates,independent_pending_reserve_replay=valid_pending)
    return checks


def provenance_audit(m,c,r,requests):
    checks={};new=m.get('schema_version',0)>=6;ops=r['migration_operations']
    checks.update(token_audit(c,r,legacy=not new));checks.update(control_audit(m,c,r,requests))
    checks['source_write_chronology']=all(op['parent_task_id'] is None or any(p['task_id']==op['parent_task_id'] and p['outcome']=='completed' and p['terminal_ns']<=op['issued_ns'] for p in ops) for op in ops)
    if not new:return checks
    dataset=create_dataset(seed=c['dataset']['seed'],key_count=c['dataset']['keys'],value_bytes=c['dataset']['value_bytes']);by=dataset.by_key()
    expected={k:__import__('hashlib').sha256(v.payload).hexdigest() for k,v in by.items()}
    checks['actual_migration_payload_provenance']=all(op['outcome']!='completed' or op.get('payload_sha256') is None and op['work_class']=='donor_read' or op.get('payload_sha256')==expected.get(op['key']) for op in ops)
    checks['actual_write_payload_parent_match']=all(op['work_class']!='destination_write' or any(parent['task_id']==op['parent_task_id'] and parent.get('payload_sha256')==op.get('payload_sha256') for parent in ops) for op in ops)
    checks['actual_attempt_timeout_fields']=all(op['absolute_deadline_ns']<=r['expansion_ns']+int(min(c['timing']['task_lifetime_seconds'],c['timing']['handover_deadline_seconds'])*1e9) and op['timeout_seconds']==c['retries'][{'donor_read':'donor_read','discretionary_database_warmup':'warmup_database','destination_write':'destination_write'}[op['work_class']]]['attempt_timeout_seconds'] for op in ops)
    writes=[o for o in ops if o['work_class']=='destination_write' and o['outcome']=='completed']
    coverage_ok=True;eligibility_ok=True
    registry={b:[] for b in range(c['routing']['virtual_buckets'])}
    from cache_scaleout.dataset import StableOwnershipMap
    mapping=StableOwnershipMap(mapping_seed=c['routing']['mapping_seed'],bucket_count=c['routing']['virtual_buckets'],old_nodes=tuple(c['routing']['old_nodes']),final_nodes=tuple(c['routing']['final_nodes']),destination=c['routing']['destination'])
    for item in dataset.items:registry[mapping.bucket_for_key(item.key)].append(item.key)
    for row in r['actions']:
        o=row['observation'];at=o['observed_at_ns'];w=o['demand']['window']
        evidence={}
        history=[(op.get('residency_confirmed_ns',2**63),0,op) for op in writes]
        history += [(op['residency_invalidated_ns'],1,op) for op in r['foreground_operations'] if op.get('residency_invalidated_ns') is not None]
        history += [(sample['residency_reset_ns'],2,sample) for sample in r['observations'] if sample.get('residency_reset_ns') is not None]
        for time,kind,event in sorted(history,key=lambda e:(e[0],e[1])):
            if time>at:break
            if kind==0:evidence[event['key']]=event
            elif kind==1:evidence.pop(next(q['key'] for q in requests if q['request_id']==event['request_id']),None)
            else:evidence.clear()
        warm={key for key,op in evidence.items() if at-op['residency_confirmed_ns']<=c['policy']['residency_max_age_seconds']*1e9 and (op.get('residency_valid_until_ns') is None or at<op['residency_valid_until_ns'])}
        # An observed destination miss removes positive evidence, even if a
        # normal foreground fill later repopulates it without a new receipt.
        for b,coverage in o['bucket_coverage'].items():
            b=int(b);represented=[q for q in requests if q['route']['bucket']==b and w['start_ns']<=q['submitted_ns']<w['end_ns']]
            if coverage['known_keys']!=len(registry[b]) or coverage['confirmed_warm_keys']!=sum(k in warm for k in registry[b]) or coverage['confirmed_warm_requests']!=sum(q['key'] in warm for q in represented):coverage_ok=False
        for b in row['action']['admit_buckets']:
            if m['policy']!='immediate_cutover' and any(p['terminal_ns']>row['action']['decided_at_ns'] for p in r['pass_results'] if p['bucket']==b):eligibility_ok=False
    checks['independent_residency_coverage_provenance']=coverage_ok
    checks['finite_pass_terminal_before_eligibility_admission']=eligibility_ok
    checks['per_key_terminal_accounting']=all(p['attempts']==sum(op['key']==p['key'] for op in ops) for p in r['pass_results'])
    return checks
