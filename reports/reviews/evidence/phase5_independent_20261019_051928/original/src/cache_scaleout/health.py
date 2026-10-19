"""Actual client checks using bounded operations and disposable isolated data."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import traceback
import uuid

import psycopg
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from .evidence import ROOT, source_fingerprint, utc_now, write_json


async def cache_health(config: dict, index: int, events: list) -> dict:
    settings = config['cache']
    key = f'paper2:health:{uuid.uuid4().hex}'
    payload = f'phase0-cache-{index}'.encode()
    start = time.monotonic()
    async with Redis(host=settings['host'], port=settings['ports'][index],
                     max_connections=settings['max_connections'],
                     socket_connect_timeout=settings['socket_timeout_seconds'],
                     socket_timeout=settings['socket_timeout_seconds']) as client:
        assert await client.ping() is True, 'Redis PING failed'
        server = await client.info('server')
        memory = await client.info('memory')
        assert memory['maxmemory'] == settings['maxmemory_bytes'], 'Unexpected maxmemory'
        assert memory['maxmemory_policy'] == settings['eviction_policy'], 'Unexpected eviction policy'
        inserted = False
        try:
            inserted = bool(await client.set(key, payload, nx=True, ex=30))
            assert inserted, 'Disposable health key collision'
            actual = await client.get(key)
            assert actual == payload, 'Redis payload mismatch'
            assert 0 < await client.ttl(key) <= 30, 'Redis expiry not bounded'
        finally:
            if inserted:
                assert await client.delete(key) == 1, 'Disposable key cleanup failed'
        assert await client.get(key) is None, 'Redis cleanup readback failed'
        record = {'component': f'cache-{index}', 'port': settings['ports'][index], 'status': 'verified',
                  'server_version': server['redis_version'], 'server_run_id': server['run_id'],
                  'maxmemory_bytes': memory['maxmemory'], 'eviction_policy': memory['maxmemory_policy'],
                  'payload_sha256': hashlib.sha256(payload).hexdigest(), 'cleanup_verified': True,
                  'elapsed_seconds': time.monotonic() - start}
        events.append({'utc': utc_now(), **record})
        return record


async def database_health(config: dict, events: list) -> dict:
    settings = config['database']
    password = os.environ[settings['password_env']]
    start = time.monotonic()
    # Use kwargs so credentials are never part of a persisted command or conninfo.
    async with AsyncConnectionPool('', kwargs={'host': settings['host'], 'port': settings['port'],
                                              'dbname': settings['dbname'], 'user': settings['user'],
                                              'password': password, 'connect_timeout': settings['timeout_seconds']},
                                   min_size=settings['pool_min_size'], max_size=settings['pool_max_size'],
                                   timeout=settings['timeout_seconds'], open=False) as pool:
        await pool.wait(timeout=settings['timeout_seconds'])
        async with pool.connection() as connection:
            await connection.execute('SET LOCAL statement_timeout = 5000')
            database = await (await connection.execute('SELECT current_database(), version()')).fetchone()
            assert database[0] == settings['dbname'] == 'paper2_research', 'Unexpected research database'
            await connection.execute('CREATE TEMP TABLE paper2_health (key text PRIMARY KEY, value bytea) ON COMMIT DROP')
            key = uuid.uuid4().hex
            payload = b'phase0-authoritative-value'
            await connection.execute('INSERT INTO paper2_health VALUES (%s, %s)', (key, payload))
            result = await (await connection.execute('SELECT value FROM paper2_health WHERE key = %s', (key,))).fetchone()
            assert result is not None and bytes(result[0]) == payload, 'PostgreSQL payload mismatch'
            await connection.execute('DELETE FROM paper2_health WHERE key = %s', (key,))
            assert (await (await connection.execute('SELECT count(*) FROM paper2_health')).fetchone())[0] == 0
        async with pool.connection() as connection:
            assert (await (await connection.execute("SELECT to_regclass('pg_temp.paper2_health')")).fetchone())[0] is None
        record = {'component': 'database', 'status': 'verified', 'server_version': database[1],
                  'client_libpq_version': psycopg.pq.version(), 'pool_max_size': settings['pool_max_size'],
                  'payload_sha256': hashlib.sha256(payload).hexdigest(), 'cleanup_verified': True,
                  'elapsed_seconds': time.monotonic() - start}
        events.append({'utc': utc_now(), **record})
        return record


async def health(config: dict, config_path: Path, run_id: str, retry_of: str | None) -> int:
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}', run_id):
        raise ValueError('Invalid run ID')
    if retry_of and not (ROOT / 'runs' / retry_of / 'manifest.json').is_file():
        raise ValueError('Retry must reference an existing retained manifest')
    directory = ROOT / 'runs' / run_id
    directory.mkdir(parents=True, exist_ok=False)
    started, monotonic_start = utc_now(), time.monotonic()
    write_json(directory / 'effective_config.json', config)
    write_json(directory / 'source.json', source_fingerprint())
    events, results = [], []
    status, code = 'infrastructure_failure', 1
    error_record = None
    try:
        async with asyncio.timeout(config['health_timeout_seconds']):
            # Sequential checks retain successes preceding any failure.
            for index in range(3):
                results.append(await cache_health(config, index, events))
            assert len({r['server_run_id'] for r in results}) == 3, 'Cache endpoints are not independent instances'
            results.append(await database_health(config, events))
        status, code = 'completed', 0
    except Exception as error:
        message = str(error)
        password = os.environ.get(config['database']['password_env'])
        if password:
            message = message.replace(password, '[REDACTED]')
        trace = traceback.format_exc()
        if password:
            trace = trace.replace(password, '[REDACTED]')
        error_record = {'type': type(error).__name__, 'message': message}
        (directory / 'error.log').write_text(trace, encoding='utf-8')
        events.append({'utc': utc_now(), 'status': 'failed', 'error': error_record})
    (directory / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
    write_json(directory / 'results.json', {'checks': results, 'error': error_record})
    write_json(directory / 'manifest.json', {'run_id': run_id, 'kind': 'phase0_service_health', 'status': status,
               'retry_of': retry_of, 'started_utc': started, 'ended_utc': utc_now(),
               'elapsed_seconds': time.monotonic() - monotonic_start, 'exit_code': code,
               'config_path': config_path.relative_to(ROOT).as_posix(),
               'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
               'source_sha256': json.loads((directory / 'source.json').read_text())['aggregate_sha256'],
               'issue_id': None, 'boundary': 'Connection/read/write/cleanup check; not a scale-out experiment.'})
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir() if p.is_file()}
    write_json(directory / 'checksums.json', checksums)
    print(json.dumps({'run_id': run_id, 'status': status, 'exit_code': code, 'evidence': str(directory), 'error': error_record}))
    return code

