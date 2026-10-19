import collections, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import write_json

output=[]
for run in sorted((ROOT/'runs').glob('p4*')):
    entry={'run_id':run.name,'files':[p.name for p in run.iterdir()]}
    for name in ('status','manifest'):
        if (run/(name+'.json')).exists():
            entry[name]=json.loads((run/(name+'.json')).read_text())
    if (run/'requests.jsonl').exists() and (run/'offered_schedule.json').exists():
        rows=[json.loads(line) for line in (run/'requests.jsonl').read_text().splitlines()]
        schedule=json.loads((run/'offered_schedule.json').read_text())
        offers=schedule['requests']; lookup={r['request_id']:r for r in offers}
        entry['raw']={'offered':len(offers),'terminal':len(rows),
            'outcomes':dict(collections.Counter(r['outcome'] for r in rows)),
            'offered_identity_exact':len(rows)==len(offers)==len({r['request_id'] for r in rows}) and all(
                all(r[k]==lookup[r['request_id']][k] for k in ('key','scheduled_arrival_ns')) for r in rows),
            'max_dispatch_lag_ms':max((r['submitted_ns']-r['scheduled_arrival_ns'])/1e6 for r in rows),
            'db_attempts':sum(r.get('database_attempts',r.get('issued_ns') is not None) for r in rows)}
        if (run/'result.json').exists():
            result=json.loads((run/'result.json').read_text())
            ops=result.get('router',{}).get('operations',[])
            entry['raw']['operation_classes']=dict(collections.Counter((r['work_class']+':'+r['operation']) for r in ops))
            entry['raw']['observations']=len(result.get('observations',[]))
            entry['raw']['probe_operation_records_present']='accounting' in result
    output.append(entry)
write_json(Path(__file__).with_name('submitted_raw_audit.json'),output)
print(json.dumps([{k:r[k] for k in ('run_id','raw') if k in r} for r in output],indent=2))
