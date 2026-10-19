"""Capture PostgreSQL relation/statio evidence for the configured Phase 4 mix."""
import asyncio, json, os, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cache_scaleout.phase4 import load_phase4_config, _open_environment, _close
from cache_scaleout.evidence import ROOT, write_json, utc_now

async def main():
    config=load_phase4_config(ROOT/'configs/phase4_calibration.yaml'); run_id='p4buffer_probe'
    dataset=ownership=caches=database=None
    try:
        dataset,ownership,caches,database,services,initial=await _open_environment(config,run_id,require_empty=True)
        async def stats():
            async with database.background_pool.connection() as conn:
                row=await (await conn.execute("SELECT pg_relation_size('phase3_dataset'), coalesce(s.heap_blks_read,0), coalesce(s.heap_blks_hit,0) FROM pg_statio_user_tables s WHERE relname='phase3_dataset'")).fetchone()
                return {'relation_bytes':int(row[0]),'heap_blks_read':int(row[1]),'heap_blks_hit':int(row[2])}
        before=await stats(); deadline=time.monotonic_ns()+20_000_000_000
        for item in dataset.items[:96]: await database.read_foreground(item.key,deadline_ns=deadline)
        after=await stats()
        write_json(ROOT/'reports/evidence/phase4/buffer_probe.json',{'started_utc':utc_now(),'before':before,'after':after,'query_cpu_rounds':config['services']['database']['query_cpu_rounds'],'pool':database.pool_summary(),'cache_services':services})
    finally:
        if caches is not None: await _close(caches,database)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
asyncio.run(main())
