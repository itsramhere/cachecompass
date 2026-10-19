import json
r=json.load(open('runs/p5ind_20261019_m1_tune4A/result.json'));c=json.load(open('runs/p5ind_20261019_m1_tune4A/effective_config.json'))
rates=dict.fromkeys(c['bursts'],0.);credit=rates.copy();previous=None;acquired={};returned=set();bad=[]
for index,e in enumerate(r['token_events']):
 at=e['at_ns'];kind=e['kind']
 if previous is not None:
  for dim in rates:credit[dim]=min(c['bursts'][dim],credit[dim]+max(0,at-previous)/1e9*rates[dim])
 previous=at
 if kind=='rates':
  rates=e['rates'];
  for d,v in rates.items():
   if v==0:credit[d]=0.
 elif kind=='acquire':
  acquired[index]=e
  for d,a in e['amounts'].items():
   credit[d]-=a
   if credit[d]<-1e-4:bad.append({'event':index,'at':at,'dim':d,'deficit':credit[d],'rates':rates.copy(),'previous':r['token_events'][index-1]})
 elif kind in ('refund','forfeit'):
  origin=e.get('acquire_event_id')
  if origin not in acquired or origin in returned or e['amounts']!=acquired[origin]['amounts']:bad.append({'bad_return':e})
  returned.add(origin)
  if kind=='refund':
   for d,a in e['amounts'].items():
    if rates[d]>0:credit[d]=min(c['bursts'][d],credit[d]+a)
print(json.dumps({'violations':bad[:15],'n':len(bad)},indent=2))
