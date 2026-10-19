"""Label-verified disposable reset/run/shutdown with exact immutable records."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cache_scaleout.evidence import source_fingerprint,utc_now,write_json


def docker_environment():
    env=dict(os.environ)
    for line in (ROOT/'infra/images.env').read_text().splitlines():
        if line and not line.startswith('#'):
            k,v=line.split('=',1);env[k]=v
    env.setdefault('PAPER2_DB_PASSWORD','paper2-disposable-local-only')
    env.update(PAPER2_DOCKER='docker',PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1')
    return env


def service_command(args,env):
    r=subprocess.run(['docker',*args],cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
    return {'argv':['docker',*args],'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}


def verify_disposable(env):
    r=service_command(['ps','-aq','--filter','label=com.docker.compose.project=paper2-research'],env)
    if r['returncode']: raise RuntimeError(r)
    for identity in r['stdout'].split():
        info=service_command(['inspect',identity,'--format','{"labels":{{json .Config.Labels}},"Mounts":{{json .Mounts}}}'],env)
        data=json.loads(info['stdout']);labels=data['labels']
        if labels.get('org.paper2.purpose')!='disposable-research': raise RuntimeError('unrecognized project container; reset refused')
        if data['Mounts'] and any(m['Type']=='bind' for m in data['Mounts']): raise RuntimeError('unexpected shared bind mount; reset refused')


def cycle(run_id,arguments,record_path,*,retry_of=None,tests=False):
    if record_path.exists() or (ROOT/'runs'/run_id).exists(): raise ValueError('fresh run/record required')
    env=docker_environment(); commands=[];start=utc_now();code=None;source_before=source_fingerprint()
    compose=['compose','-f','infra/compose.yaml','--project-name','paper2-research']
    verify_disposable(env)
    try:
        for args in ([*compose,'down','--volumes','--remove-orphans'],[*compose,'up','-d','--wait','--wait-timeout','50']):
            row=service_command(args,env);commands.append(row)
            if row['returncode']: raise RuntimeError(row)
        argv=([sys.executable,'-B','-m','unittest','discover','-s','tests','-p','test_*.py','-v'] if tests else [sys.executable,'-B','-m','cache_scaleout.phase5','--run-id',run_id,*arguments])
        if tests: env['PAPER2_INTEGRATION']='1'
        begin=time.monotonic()
        if retry_of: env['PAPER2_RETRY_OF']=retry_of
        child=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
        commands.append({'argv':argv,'returncode':child.returncode,'stdout':child.stdout,'stderr':child.stderr,'elapsed_seconds':time.monotonic()-begin})
        code=child.returncode
    finally:
        verify_disposable(env)
        commands.append(service_command([*compose,'down','--volumes','--remove-orphans'],env))
        stopped=service_command(['ps','-q','--filter','label=com.docker.compose.project=paper2-research'],env)
        commands.append(stopped)
        write_json(record_path,{'started_utc':start,'ended_utc':utc_now(),'source_before':source_before,'source_after':source_fingerprint(),
            'run_id':run_id,'retry_of':retry_of,'commands':commands,'services_stopped':stopped['returncode']==0 and not stopped['stdout'].strip()})
    return code

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-id',required=True);p.add_argument('--record',required=True,type=Path);p.add_argument('--retry-of');p.add_argument('--tests',action='store_true');p.add_argument('args',nargs=argparse.REMAINDER)
    a=p.parse_args();raise SystemExit(cycle(a.run_id,a.args[1:] if a.args[:1]==['--'] else a.args,a.record,retry_of=a.retry_of,tests=a.tests))
