"""Regenerate corrected reports twice and verify CSV/SVG values and preservation."""
import csv, hashlib, json, os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
from review_driver import ROOT,HERE,record
from cache_scaleout.evidence import write_json
PY=str(ROOT/'.venv/Scripts/python.exe'); os.environ['PYTHONPATH']=str(ROOT/'src')
names=[f'p4final_cal{rate}_{rep}_20261019' for rate in (12,24,36) for rep in (1,2,3)]
names += [f'p4final_{c}_{rep}_20261019' for rep in (1,2,3) for c in ('control','immediate')]
names += ['p4final_headroom144_20261019']
base=ROOT/'reports/analysis/phase4_independent_final_20261019'
copy=HERE/'regenerated_final'
for name,out in (('final_analysis',base),('final_analysis_reproduction',copy)):
    record(name,[PY,'-B','analysis/phase4_analysis.py','--runs',*names,'--output',str(out)])
different=[p.name for p in base.iterdir() if p.read_bytes()!=(copy/p.name).read_bytes()]
validation=json.loads((base/'validation.json').read_text()); look={e['run_id']:e for e in validation}
table_errors=[]
with (base/'calibration.csv').open(newline='') as f:
    for row in csv.DictReader(f):
        e=look[row['run_id']]['computed']
        if float(row['p95_ms'])!=e['successful_p95_ms'] or int(row['issued'])!=e['issued'] or int(row['probes'])!=e['issued_observation_db_attempts']: table_errors.append(row['run_id'])
with (base/'expansion.csv').open(newline='') as f:
    for row in csv.DictReader(f):
        e=look[row['run_id']]['computed'][row['window']]
        for k in ('offered','completed','database_attempts','all_offer_latency_violations'):
            if int(row[k])!=e[k]: table_errors.append(row['run_id']+':'+k)
        if float(row['successful_p95_ms'])!=e['successful_p95_ms']: table_errors.append(row['run_id']+':p95')
svg_errors=[]
for file,kind in (('calibration_p95.svg','calibration'),('expansion_p95.svg','immediate_cutover')):
    points=[(e['computed']['rate'],e['computed']['successful_p95_ms'],e['run_id']) if kind=='calibration' else (e['manifest']['offered_rate'],e['computed']['transition']['successful_p95_ms'],e['run_id']) for e in validation if e['valid'] and e['kind']==kind]
    tree=ET.parse(base/file); circles=tree.findall('.//{http://www.w3.org/2000/svg}circle'); maxx=max(p[0] for p in points); maxy=max(p[1] for p in points)
    if len(circles)!=len(points): svg_errors.append(file+':count')
    for circle,(x,y,label) in zip(circles,points):
        if circle.attrib['cx']!=f'{65+x/maxx*580:.1f}' or circle.attrib['cy']!=f'{300-y/maxy*240:.1f}' or circle[0].text!=label: svg_errors.append(label)
result={'byte_different_regenerations':different,'table_errors':table_errors,'svg_errors':svg_errors,
    'analysis_files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in base.iterdir()},
    'invalid_runs':[e['run_id'] for e in validation if not e['valid']]}
write_json(HERE/'final_regeneration_verification.json',result)
print(json.dumps(result,indent=2))
raise SystemExit(bool(different or table_errors or svg_errors or result['invalid_runs']))
