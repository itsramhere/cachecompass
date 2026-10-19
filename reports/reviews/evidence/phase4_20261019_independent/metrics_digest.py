"""Compact raw-derived values for the review narrative; no request pooling inference."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[4]; HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import write_json
audit=json.loads((HERE/'raw_final_audit.json').read_text()); runs=audit['runs']
probes=[]
for r in runs:
    if 'control_' not in r['run_id'] and 'immediate_' not in r['run_id']: continue
    directory=ROOT/'runs'/r['run_id']; result=json.loads((directory/'result.json').read_text()); doc=json.loads((directory/'offered_schedule.json').read_text())
    origin=doc['origin_ns']; group=result['accounting']['cache_probes']
    probes.append({'run_id':r['run_id'],'transition_cache_probe_commands':{n:sum(origin+3_000_000_000<=x['issued_ns']<origin+5_000_000_000 for x in rows) for n,rows in group.items()},
        'transition_db_probe_attempts':r['transition_issued_work']['observation_db_issued'],'whole_run_db_probe_attempts':r['observation_db_issued']})
cuts=[{'run_id':r['run_id'],'publication_lateness_ms':(r['transition_record']['published_ns']-r['transition_record']['requested_ns'])/1e6} for r in runs if r['transition_record']]
data={'paired_observation_overhead':probes,'cutovers':cuts,'warm_p95_range_ms':[min(v for r in runs for v in r['warm_window_p95_ms']),max(v for r in runs for v in r['warm_window_p95_ms'])],
    'maximum_metric_emit_ms':max(r['headroom']['maximum_metric_emit_ms'] for r in runs),
    'calibration':[{'run_id':r['run_id'],'cpu_core_fraction':r['container_cpu']['database']['usage_core_fraction'],
        'throttled_seconds':r['container_cpu']['database']['cpu_stat_delta']['throttled_usec']/1e6,
        'dispatch_max_ms':r['computed']['dispatch_lag_max_ms'],'pool_queue':r['pool_queue_counter_delta_after_first_observation']} for r in runs if 'cal' in r['run_id']],
    'headroom_profile':next(r for r in runs if 'headroom144' in r['run_id'])}
write_json(HERE/'final_metrics_digest.json',data)
print(json.dumps({k:v for k,v in data.items() if k!='headroom_profile'},indent=2))
