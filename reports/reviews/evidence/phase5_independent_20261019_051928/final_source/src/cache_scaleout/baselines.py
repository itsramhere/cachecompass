"""Phase 5 controls. No joint controller; decisions install transactionally."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math
import time

from .contracts import (BucketAdvance, BucketState, ControllerAction, ControllerObservation,
                        PressureState, TransferBudget)
from .policies import (TrafficControl, WarmupControl, incremental_foreground_db_rate,
                       policy_catalog, remaining_db_allowance, admit_in_order)

DIMENSIONS = ('donor_operations', 'donor_bytes', 'background_db_operations',
              'destination_write_operations', 'destination_write_bytes')
BASELINES = tuple(name for name in policy_catalog() if name != 'joint_control')


@dataclass(frozen=True)
class BaselineParameters:
    interval_ns: int
    fixed_rates: dict[str, float]
    ceilings: dict[str, float]
    increments: dict[str, float]
    safe_windows: int
    unsafe_donor_multiplier: float
    safe_total_db_rate: float
    reserve_db_rate: float
    fixed_origin_ns: int
    fixed_interval_ns: int
    fixed_count: int
    admission_cap: int
    max_foreground_attempts: int

    def __post_init__(self):
        for name in ('interval_ns','safe_windows','fixed_interval_ns','max_foreground_attempts'):
            if type(getattr(self,name)) is not int or getattr(self,name) < 1:
                raise ValueError('positive integer '+name+' required')
        for name in ('fixed_origin_ns','fixed_count','admission_cap'):
            if type(getattr(self,name)) is not int or getattr(self,name) < 0:
                raise ValueError('nonnegative integer '+name+' required')
        for rates in (self.fixed_rates,self.ceilings,self.increments):
            if set(rates) != set(DIMENSIONS) or any(isinstance(v,bool) or not math.isfinite(v) or v<0 for v in rates.values()):
                raise ValueError('five finite nonnegative rate dimensions required')
        if any(self.fixed_rates[d]>self.ceilings[d] for d in DIMENSIONS):
            raise ValueError('fixed rate exceeds ceiling')
        if not math.isfinite(self.unsafe_donor_multiplier) or not 0<=self.unsafe_donor_multiplier<1:
            raise ValueError('invalid multiplicative decrease')
        if any(isinstance(v,bool) or not math.isfinite(v) or v<0 for v in (self.safe_total_db_rate,self.reserve_db_rate)):
            raise ValueError('finite DB bounds required')


class BaselineController:
    """decide stages private state; commit only after the shared action installs."""
    def __init__(self, policy_name, parameters, *, expansion_ns):
        if policy_name not in BASELINES:
            raise ValueError('Phase 5 supports six controls; joint_control is Phase 6')
        self.policy_name=policy_name
        self.definition=policy_catalog()[policy_name]
        self.p=parameters
        self.expansion_ns=expansion_ns
        self.rates=dict.fromkeys(DIMENSIONS,0.)
        self.safe=dict.fromkeys(('db','donor','destination'),0)
        self.last_window=-1
        self.last_fixed_tick=-1
        self.pending={}
        self.last_detail={}
        self._proposal=None

    def decide(self, observation: ControllerObservation, *, decided_at_ns):
        if decided_at_ns < observation.observed_at_ns:
            raise ValueError('decision precedes causal observation')
        candidate=copy.copy(self)
        candidate.rates=dict(self.rates); candidate.safe=dict(self.safe); candidate.pending=dict(self.pending)
        candidate._proposal=None
        action=candidate._decide(observation,decided_at_ns)
        self._proposal=(action,candidate,observation)
        return action

    def commit(self, action):
        if self._proposal is None or action != self._proposal[0]:
            raise ValueError('action is not the staged decision')
        candidate=self._proposal[1]
        self.__dict__.update(candidate.__dict__)
        self._proposal=None

    def _decide(self,o,now):
        p=self.p; end=o.demand.window.end_ns
        fresh=end>self.last_window
        states={name:pressure.effective_state(as_of_ns=now,max_age_ns=o.max_signal_age_ns)
                for name,pressure in (('db',o.db_pressure),('donor',o.donor_pressure),('destination',o.destination_pressure))}
        estimates_fresh=(o.foreground_db_known and now-end<=o.demand.window.max_age_ns and
                         now-o.foreground_db_observed_at_ns<=o.max_signal_age_ns)
        # A reserve retires only when its entire cutover lies before a fresh window.
        if estimates_fresh:
            self.pending={b:v for b,v in self.pending.items() if o.demand.window.start_ns<v[1]}
        pending=max(o.pending_admission_db_rate_upper,sum(v[0] for v in self.pending.values()))
        reasons=[]; rejected=[]
        if not fresh:
            reasons.append('duplicate_window_no_grant')
            if self.definition.warmup_control is WarmupControl.ADAPTIVE and (not estimates_fresh or any(v is not PressureState.SAFE for v in states.values())):
                self.rates=dict.fromkeys(DIMENSIONS,0.)
                self.safe=dict.fromkeys(self.safe,0)
                reasons=['duplicate_window_revoke_unsafe']
        else:
            self.last_window=end
            for name,state in states.items():
                safe=state is PressureState.SAFE and (estimates_fresh or name!='db')
                self.safe[name]=self.safe[name]+1 if safe else 0
            if self.definition.warmup_control is WarmupControl.FIXED:
                self.rates=dict(p.fixed_rates)
                reasons.append('fixed_rates_ignore_soft_pressure')
            elif self.definition.warmup_control is WarmupControl.ADAPTIVE:
                for dim in DIMENSIONS:
                    name=('donor' if dim.startswith('donor') else 'db' if dim.startswith('background') else 'destination')
                    state=states[name]
                    if state is PressureState.SAFE and (name!='db' or estimates_fresh):
                        if self.safe[name]>=p.safe_windows:
                            self.rates[dim]=min(p.ceilings[dim],self.rates[dim]+p.increments[dim])
                    elif name=='donor' and state is PressureState.UNSAFE:
                        self.rates[dim]*=p.unsafe_donor_multiplier
                    else:
                        self.rates[dim]=0.
                if states['destination'] is not PressureState.SAFE:
                    self.rates=dict.fromkeys(DIMENSIONS,0.)
                self.rates['background_db_operations']=min(self.rates['background_db_operations'],
                    remaining_db_allowance(p.safe_total_db_rate,p.reserve_db_rate,o.foreground_db_rate_upper,0,
                        pending_admission_db_rate_upper=pending,observation_db_rate_upper=o.observation_db_rate_upper))
                reasons.append('adaptive_fresh_window_update')
        admissible=[]; costs={}; allowance=None
        traffic=self.definition.traffic_control
        ordered=sorted(o.bucket_states)
        if traffic is TrafficControl.IMMEDIATE:
            admissible=[b for b in ordered if o.bucket_states[b] is not BucketState.NEW]
            self.rates=dict.fromkeys(DIMENSIONS,0.)
            reasons.append('immediate_zero_discretionary_work')
        elif traffic is TrafficControl.AFTER_MIGRATION:
            if all(s in (BucketState.ELIGIBLE,BucketState.NEW) for s in o.bucket_states.values()):
                admissible=[b for b in ordered if o.bucket_states[b] is BucketState.ELIGIBLE]
                reasons.append('entire_finite_pass_terminal_cutover_all')
            else:
                reasons.append('waiting_entire_finite_pass')
        elif traffic is TrafficControl.FIXED_GRADUAL:
            relative=now-self.expansion_ns-p.fixed_origin_ns
            slot=relative//p.fixed_interval_ns if relative>=0 else -1
            if slot>self.last_fixed_tick:
                self.last_fixed_tick=slot  # Missed opportunities disappear; one cap per actual tick.
                for b in ordered:
                    if o.bucket_states[b] is BucketState.NEW: continue
                    if len(admissible)>=p.fixed_count: break
                    if o.bucket_states[b] is not BucketState.ELIGIBLE:
                        reasons.append('fixed_schedule_waiting_for_eligibility'); break
                    admissible.append(b)
                reasons.append('fixed_tick_no_catchup_no_leapfrog')
            else:
                reasons.append('waiting_fixed_tick')
        elif traffic is TrafficControl.ADAPTIVE:
            if fresh and o.admissions_safe_at(now) and min(self.safe.values())>=p.safe_windows:
                allowance=remaining_db_allowance(p.safe_total_db_rate,p.reserve_db_rate,o.foreground_db_rate_upper,
                    self.rates['background_db_operations'],pending_admission_db_rate_upper=pending,
                    observation_db_rate_upper=o.observation_db_rate_upper)
                costs={b:incremental_foreground_db_rate(o.candidate_request_rate_upper[b],
                    (o.bucket_coverage[b].warmed_request_coverage if now<o.coverage_valid_until_ns.get(b,o.observed_at_ns+1) else 0.),o.uncertain_miss_reserve_rate[b],
                    max_foreground_attempts=p.max_foreground_attempts,old_owner_db_rate_lower=o.old_owner_db_rate_lower[b])
                    for b in ordered if o.bucket_states[b] is BucketState.ELIGIBLE}
                admissible=list(admit_in_order(tuple(costs.items()),allowance=allowance,max_admissions=p.admission_cap))
                rejected=[{'bucket':b,'cost':c,'reason':'allowance_or_cap'} for b,c in costs.items() if b not in admissible]
                reasons.append('adaptive_admission_charges_pending_and_fixed_warming')
                for b in admissible: self.pending[b]=(costs[b],now)
            else:
                reasons.append('admission_paused_stale_unknown_unsafe_or_hysteresis')
        if not fresh:admissible=[]
        if not admissible: reasons.append('no_admission')
        grant_rates=self.rates if fresh else dict.fromkeys(DIMENSIONS,0.)
        grants={d:math.floor(v*p.interval_ns/1e9) for d,v in grant_rates.items()}
        budget=TransferBudget(**grants,valid_for_ns=p.interval_ns)
        self.last_detail={'pressure':{k:v.value for k,v in states.items()},'safe_counters':dict(self.safe),
            'rates':dict(self.rates),'fresh_window':fresh,'window_start_ns':o.demand.window.start_ns,'window_end_ns':end,
            'pending_before':pending,'pending_after':{b:list(v) for b,v in self.pending.items()},
            'foreground_upper':o.foreground_db_rate_upper,'probe_upper':o.observation_db_rate_upper,
            'planned_warmup_upper':self.rates['background_db_operations'],'allowance':allowance,
            'candidate_costs':costs,'expired_coverage_buckets':[b for b in ordered if now>=o.coverage_valid_until_ns.get(b,o.observed_at_ns+1)],'rejected':rejected,'conservative_overlap':'pending held across straddling windows; unknown old-owner credit is zero'}
        return ControllerAction(now,budget,tuple(admissible),tuple(reasons),o.routing_epoch,o.observed_at_ns)


def install_action(ownership, scheduler, controller, action, *, clock=None):
    """Validate complete next map and grant before changing either; no awaits."""
    installed_at=(clock or time.monotonic_ns)()
    if not action.decided_at_ns<=installed_at<action.decided_at_ns+action.budget.valid_for_ns:
        raise ValueError('action is future-dated or expired before installation')
    if action.expected_routing_epoch!=ownership.snapshot.epoch:
        raise ValueError('stale action epoch; nothing installed')
    if controller._proposal is None or controller._proposal[0]!=action:
        raise ValueError('unstaged action')
    if action.decided_at_ns<=scheduler.grants.last_decided_at_ns:
        raise ValueError('duplicate grant generation')
    observation=controller._proposal[2]
    if action.admit_buckets and controller.definition.traffic_control is TrafficControl.ADAPTIVE:
        if not observation.admissions_safe_at(installed_at):raise ValueError('admission observation expired before installation')
        if any(observation.bucket_coverage[b].warmed_request_coverage>0 and installed_at>=observation.coverage_valid_until_ns.get(b,observation.observed_at_ns+1) for b in action.admit_buckets):raise ValueError('coverage expired before installation')
    if 'duplicate_window_no_grant' in action.reason_codes:
        controller.commit(action)
        return ownership.snapshot.epoch
    advances=[]
    for b in action.admit_buckets:
        state=ownership.state(b)
        path=((BucketState.COPYING,BucketState.ELIGIBLE,BucketState.NEW) if state is BucketState.OLD
              else (BucketState.NEW,))
        advances.append(BucketAdvance(b,state,path))
    preview=copy.copy(ownership)
    preview.publish(tuple(advances),expected_epoch=action.expected_routing_epoch)
    scheduler.apply_action(action)
    scheduler.tokens.set_rates(controller._proposal[1].rates)
    epoch=ownership.publish(tuple(advances),expected_epoch=action.expected_routing_epoch)
    publication_ns=(clock or time.monotonic_ns)()
    controller._proposal[1].last_detail['published_at_ns']=publication_ns
    for bucket in action.admit_buckets:
        if bucket in controller._proposal[1].pending:
            cost,_=controller._proposal[1].pending[bucket]
            controller._proposal[1].pending[bucket]=(cost,publication_ns)
    controller._proposal[1].last_detail['pending_after']={b:list(v) for b,v in controller._proposal[1].pending.items()}
    controller.commit(action)
    return epoch
