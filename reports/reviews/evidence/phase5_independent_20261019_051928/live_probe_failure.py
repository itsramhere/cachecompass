"""Actual observation failure diagnostic, separate from every comparison."""
import asyncio,json,sys,time
from pathlib import Path
ROOT=Path('/workspace/cachecompass');E=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts'),str(ROOT/'analysis')]
from cache_scaleout.evidence import write_json,source_fingerprint,utc_now
from cache_scaleout.phase5 import load_config
from cache_scaleout.phase4 import _open_environment,_close
from phase5_cycle import docker_environment,verify_disposable,service_command
from phase5_validation import probe_coverage
async def diagnostic():
    c=load_config(ROOT/'configs/phase5_pilot.yaml');c['timing']['observation_timeout_seconds']=.02
    caches=database=None
    try:
        dataset,ownership,caches,database,services,initial=await _open_environment(c,'p5ind-probe-failure',require_empty=True)
        observers={n:client._phase4_observer for n,client in caches.items()}
        # Establish healthy actual clients first, retaining this outside the
        # failed-round accounting scope rather than erasing its operations.
        deadline=time.monotonic_ns()+1_000_000_000
        warm=await asyncio.gather(*(o.sample_pressure(deadline_ns=deadline) for o in observers.values()),database.sample_pressure(dataset.items[0].key,deadline_ns=deadline))
        warm_records={'db':list(database.probe_records),'cache':{n:list(o.probe_records) for n,o in observers.items()}}
        offsets={n:len(o.probe_records) for n,o in observers.items()};db_offset=len(database.probe_records)
        # This explicit disposable-only admin command creates a real PING
        # timeout; no comparison receives this diagnostic privilege.
        admin_start=time.monotonic_ns();ack=await caches['new']._client.execute_command('CLIENT','PAUSE',120);admin_end=time.monotonic_ns()
        async with database._background_limit:
            start=time.monotonic_ns();deadline=start+20_000_000
            results=await asyncio.gather(*(o.sample_pressure(deadline_ns=deadline) for o in observers.values()),database.sample_pressure(dataset.items[0].key,deadline_ns=deadline))
        ended=time.monotonic_ns()
        row={'started_ns':start,'ended_ns':ended,'raw_cache_samples':{n:dict(o.last_pressure_detail) for n,o in observers.items()},'raw_database_sample':dict(database.last_pressure_detail),
            'samples':{n:{'state':v.state.value,'reason':v.reason,'observed_at_ns':v.observed_at_ns} for n,v in zip((*observers,'database'),results)}}
        raw={'observations':[row],'db_probes':database.probe_records[db_offset:],'cache_probes':{n:o.probe_records[offsets[n]:] for n,o in observers.items()}}
        assert row['samples']['new']['state']==row['samples']['database']['state']=='unknown'
        assert not raw['db_probes'] and [o['operation'] for o in raw['cache_probes']['new']]==['ping']
        assert raw['cache_probes']['new'][0]['outcome']=='timed_out'
        assert probe_coverage(c,raw)
        return {'valid':True,'functional_only':True,'admin':{'operation':'CLIENT PAUSE','milliseconds':120,'work_class':'functional_diagnostic_cache','issued_ns':admin_start,'terminal_ns':admin_end,'ack':str(ack)},'healthy_precheck':[v.state.value for v in warm],'precheck_operations':warm_records,'failed_round':raw,'config':c}
    finally:
        if caches is not None:await _close(caches,database)
def main():
    assert (ROOT/'reports/evidence/phase5/p5ind_20261019_m3/complete.json').exists()
    out=E/'live_probe_failure.json'
    if out.exists():raise RuntimeError('fresh output required')
    env=docker_environment();verify_disposable(env);compose=['compose','-f','infra/compose.yaml','--project-name','paper2-research'];commands=[];result={};before=source_fingerprint();start=utc_now()
    try:
        for args in ([*compose,'down','--volumes','--remove-orphans'],[*compose,'up','-d','--wait','--wait-timeout','50']):
            r=service_command(args,env);commands.append(r);assert r['returncode']==0,r
        result=asyncio.run(diagnostic());print('actual cache issued timeout + DB unissued wait: valid UNKNOWN bundles')
    finally:
        verify_disposable(env);commands.append(service_command([*compose,'down','--volumes','--remove-orphans'],env));stopped=service_command(['ps','-q','--filter','label=com.docker.compose.project=paper2-research'],env);commands.append(stopped)
        write_json(out,{'started_utc':start,'ended_utc':utc_now(),'source_before':before,'source_after':source_fingerprint(),'commands':commands,'services_stopped':stopped['returncode']==0 and not stopped['stdout'].strip(),'result':result})
if __name__=='__main__':main()
