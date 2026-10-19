"""Capture PostgreSQL relation/statio evidence for the configured Phase 4 mix."""
import argparse, asyncio, json, os, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cache_scaleout.phase4 import load_phase4_config, _open_environment, _close
from cache_scaleout.evidence import ROOT, source_fingerprint, write_json, utc_now

parser=argparse.ArgumentParser()
parser.add_argument('--run-id',required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--config',type=Path,default=ROOT/'configs/phase4_review.yaml')
args=parser.parse_args()
if args.output.exists(): raise SystemExit('Probe output exists; choose a new path')

async def main():
    config=load_phase4_config(args.config); run_id=args.run_id
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
        # A query-local plan avoids treating asynchronously refreshed cumulative
        # pg_statio counters (which also include preparation) as this query's IO.
        async with database.background_pool.connection() as conn:
            plan=(await (await conn.execute(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT d.payload, d.version, d.absolute_expiry_ns "
                "FROM phase3_dataset AS d CROSS JOIN LATERAL "
                "(SELECT sum(length(md5(g::text || d.key))) AS work "
                " FROM generate_series(1, GREATEST(%s, 1)) AS g) AS cpu "
                "WHERE d.key = %s AND cpu.work >= 0",
                (database.query_cpu_rounds,str(dataset.items[0].key)))).fetchone())[0]
        write_json(args.output,{'started_utc':utc_now(),'run_id':run_id,'source':source_fingerprint(),'effective_config':config,
            'before':before,'after':after,'cumulative_stat_caution':'asynchronous; includes preparation; not attributed solely to 96 lookups',
            'same_query_explain_analyze_buffers':plan,'diagnostic_foreground_reads':96,'diagnostic_explain_queries':1,
            'query_cpu_rounds':config['services']['database']['query_cpu_rounds'],'pool':database.pool_summary(),'cache_services':services})
    finally:
        if caches is not None: await _close(caches,database)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
asyncio.run(main())
