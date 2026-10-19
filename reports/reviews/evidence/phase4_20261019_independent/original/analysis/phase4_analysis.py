"""Validate retained Phase 4 raw data and regenerate tables and SVG figures."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def rows(path): return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
def validate(run: Path):
    manifest=json.loads((run/'manifest.json').read_text()); result=json.loads((run/'result.json').read_text())
    schedule=json.loads((run/'offered_schedule.json').read_text())['requests']
    if manifest['kind']=='calibration':
        request_rows=rows(run/'requests.jsonl'); offered={x['request_id'] for x in schedule}; terminal={x['request_id'] for x in request_rows}
    else:
        request_rows=rows(run/'requests.jsonl'); offered={x['request_id'] for x in schedule}; terminal={x['request_id'] for x in request_rows}
    errors=[]
    if offered != terminal: errors.append('offered terminal IDs differ')
    if len(request_rows) != len(terminal): errors.append('duplicate terminal records')
    for row in request_rows:
        if row.get('submitted_ns') is None: errors.append('unexpected unsubmitted request')
        if row.get('completed_ns') is None: errors.append('missing completion timestamp')
        if row['completed_ns'] < row['scheduled_arrival_ns']: errors.append('completion precedes scheduled arrival')
    return {'run_id':run.name,'kind':manifest['kind'],'condition':manifest.get('condition'),'valid':not errors,'errors':sorted(set(errors)), 'result':result}
def svg(points, path, title):
    width,height=720,360; margin=55
    max_x=max(x for x,y,label in points) or 1; max_y=max(y for x,y,label in points) or 1
    dots=''.join(f'<circle cx="{margin+x/max_x*(width-2*margin):.1f}" cy="{height-margin-y/max_y*(height-2*margin):.1f}" r="5"><title>{label}</title></circle>' for x,y,label in points)
    labels=''.join(f'<text x="{margin+x/max_x*(width-2*margin):.1f}" y="{height-18}" font-size="11">{x:g}</text>' for x,y,label in points)
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"><rect width="100%" height="100%" fill="white"/><text x="20" y="25" font-size="16">{title}</text><line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="black"/><line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="black"/>{dots}{labels}</svg>',encoding='utf-8')
def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--runs',nargs='+',required=True); parser.add_argument('--output',required=True); args=parser.parse_args()
    output=ROOT/args.output; output.mkdir(parents=True,exist_ok=False)
    data=[validate(ROOT/'runs'/run) for run in args.runs]
    (output/'validation.json').write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    calibration=[entry for entry in data if entry['kind']=='calibration']; expansion=[entry for entry in data if entry['kind']=='immediate_cutover']
    cal_rows=[]
    for entry in calibration:
        result=entry['result']; cal_rows.append({'run_id':entry['run_id'],'rate':result['rate'],'p95_ms':result['successful_p95_ms'],'violations':result['all_offer_latency_violations'],'issued':result['issued']})
    (output/'calibration.csv').write_text('run_id,rate,p95_ms,violations,issued\n'+''.join(f"{r['run_id']},{r['rate']},{r['p95_ms']},{r['violations']},{r['issued']}\n" for r in cal_rows),encoding='utf-8')
    if cal_rows: svg([(r['rate'],r['p95_ms'] or 0,r['run_id']) for r in cal_rows],output/'calibration_p95.svg','PostgreSQL actual-query p95 vs offered rate')
    by_rate={}
    for row in cal_rows: by_rate.setdefault(row['rate'],[]).append(row)
    curve=[]
    for rate, entries in sorted(by_rate.items()):
        p95=[entry['p95_ms'] for entry in entries if entry['p95_ms'] is not None]
        curve.append({'offered_rate':rate,'independent_runs':len(entries),'p95_ms_mean':sum(p95)/len(p95),
                      'p95_ms_min':min(p95),'p95_ms_max':max(p95),'all_offer_violations':sum(entry['violations'] for entry in entries),
                      'offered':int(rate*4)*len(entries),'all_offers_submitted_and_issued':all(entry['issued']==int(rate*4) for entry in entries)})
    exp_rows=[]
    for entry in expansion:
        for window in ('pre_event','transition','post_event'):
            value=entry['result'][window]; exp_rows.append({'run_id':entry['run_id'],'condition':entry['condition'],'window':window,**value})
    fields=['run_id','condition','window','offered','submitted','completed','successful_p95_ms','all_offer_latency_violations','database_attempts','new_cache_reads','old_cache_reads']
    (output/'expansion.csv').write_text(','.join(fields)+'\n'+''.join(','.join(str(r.get(f,'')) for f in fields)+'\n' for r in exp_rows),encoding='utf-8')
    points=[(index,row.get('database_attempts',0),f"{row['condition']} {row['window']}") for index,row in enumerate(exp_rows,1)]
    if points: svg(points,output/'expansion_db_attempts.svg','Foreground DB attempts by fixed window')
    paired=[]
    for number in ('1','2','3'):
        control=next((r for r in exp_rows if r['run_id']==f'p4exp_confirm_control_{number}' and r['window']=='transition'),None)
        immediate=next((r for r in exp_rows if r['run_id']==f'p4exp_confirm_immediate_{number}' and r['window']=='transition'),None)
        if control and immediate: paired.append({'pair':number,'control_p95_ms':control['successful_p95_ms'],'immediate_p95_ms':immediate['successful_p95_ms'],
            'p95_delta_ms':immediate['successful_p95_ms']-control['successful_p95_ms'],'immediate_db_attempts':immediate['database_attempts'],
            'control_db_attempts':control['database_attempts'],'immediate_all_offer_violations':immediate['all_offer_latency_violations']})
    record={'schema_version':1,'calibration_curve':curve,'selected_c_safe_rps':24,
            'selection_rule':'highest confirmed rate with all three runs submitted/issued, p95 below 100 ms, and zero all-offer violations; 36 rps failed this rule in two of three runs',
            'applicability':'512x1KiB immutable dataset; indexed lookup plus 20,000 SQL CPU rounds; PostgreSQL 1 CPU/512MiB container; four foreground connections; local Windows client and 100ms provisional target',
            'paired_transition_results':paired}
    (output/'calibration_record.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    summary={'valid_runs':sum(x['valid'] for x in data),'invalid_runs':[x['run_id'] for x in data if not x['valid']],'calibration_rows':cal_rows,'expansion_rows':exp_rows,'paired_transition_results':paired}
    (output/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',encoding='utf-8')
if __name__=='__main__': main()
