from pathlib import Path
p = Path('src/cache_scaleout/phase3.py')
s = p.read_text(encoding='utf-8')
s = s.replace('from .migration import BoundedMigrationScheduler',
              'from .migration import BoundedMigrationScheduler\nfrom .sampling import PressureSampler\nfrom .load import dispatch_offers')
s = s.replace('    caches: dict[str, RedisCacheAdapter] = {}',
              '    caches: dict[str, RedisCacheAdapter] = {}\n    background_caches = {}\n    sampler = None\n    generator = None')
s = s.replace('max_connections=config["resources"]["foreground_cache_connections_per_node"]\n                                + config["resources"]["background_cache_connections_per_node"],',
              'max_connections=config["resources"]["foreground_cache_connections_per_node"],')
anchor = '        db_config = config["services"]["database"]'
s = s.replace(anchor, '''        for node, port in node_ports.items():
            background_caches[node] = RedisCacheAdapter(
                node_id=node, host=cache_config["host"], port=port, namespace=namespace,
                max_connections=config["resources"]["background_cache_connections_per_node"],
                socket_timeout_seconds=cache_config["socket_timeout_seconds"], pressure_limits=pressure)
''' + anchor, 1)
s = s.replace('cleanup_timeout_seconds=config["timing"]["cleanup_timeout_seconds"])',
              'cleanup_timeout_seconds=config["timing"]["cleanup_timeout_seconds"], residency=residency)')
start = s.index('        schedule_items = affected_items[:')
end = s.index('        await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.HANDOVER,', start)
s = s[:start] + '''        timing = config["timing"]
        workload_origin_ns = time.monotonic_ns()
        miss_item = affected_items[0]
        post_count = config["workload"]["post_cutover_requests"]
        schedule_items = tuple(affected_items[index % len(affected_items)] for index in range(post_count))
        relative_offers = [
            {"request_id": "pre-miss-0", "key": str(miss_item.key), "relative_arrival_ns": 50_000_000},
            {"request_id": "pre-miss-1", "key": str(miss_item.key), "relative_arrival_ns": 50_000_000}]
        relative_offers += [{"request_id": f"post-{index:03d}", "key": str(item.key),
            "relative_arrival_ns": int(timing["stability_start_seconds"]*1e9) + index*25_000_000}
            for index, item in enumerate(schedule_items)]
        schedule = tuple({**offer, "scheduled_arrival_ns": workload_origin_ns+offer["relative_arrival_ns"]}
                         for offer in relative_offers)
        write_json(run_dir / "offered_schedule.json", {"origin_ns": workload_origin_ns, "requests": schedule,
                   "checksum": hashlib.sha256(json.dumps(schedule, sort_keys=True,
                                                           separators=(",", ":")).encode()).hexdigest()})
        async def arrival(offer):
            await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.HANDOVER,
                epoch=int(ownership.snapshot.epoch), kind=EventKind.ARRIVAL_SCHEDULED,
                reason="independent_offered_schedule", detail=offer), timing["metric_timeout_seconds"])
        async def observation(row):
            await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.HANDOVER,
                epoch=int(ownership.snapshot.epoch), kind=EventKind.OBSERVATION,
                reason="fixed_common_pressure_round", detail=row), timing["metric_timeout_seconds"])
        sampler = PressureSampler(caches=background_caches, database=database, key=dataset.items[0].key,
            interval_seconds=timing["observation_interval_seconds"],
            timeout_seconds=timing["observation_timeout_seconds"], on_round=observation, residency=residency)
        miss_owner = str(ownership.old_owner(ownership.bucket_for_key(miss_item.key)))
        await caches[miss_owner].delete(miss_item.key, deadline_ns=deadline)
        await sampler.start()
        generator = asyncio.create_task(dispatch_offers(schedule=schedule, router=router,
            items=dataset.by_key(), on_arrival=arrival, metrics=metrics,
            timeout_seconds=timing["foreground_timeout_seconds"],
            metric_timeout_seconds=timing["metric_timeout_seconds"]), name="independent-generator")
        await asyncio.sleep(max(0, (workload_origin_ns+int(timing["expansion_at_seconds"]*1e9)
                                    - time.monotonic_ns())/1e9))
        expansion_ns = time.monotonic_ns()
''' + s[end:]
s = s.replace('donor_caches={node: caches[node] for node in routing["old_nodes"]},\n            destination_cache=caches[routing["destination"]]',
              'donor_caches={node: background_caches[node] for node in routing["old_nodes"]},\n            destination_cache=background_caches[routing["destination"]]')
s = s.replace('attempt_timeout_seconds=config["timing"]["migration_attempt_timeout_seconds"])',
              'attempt_timeout_seconds=config["timing"]["migration_attempt_timeout_seconds"],\n            rates=config["migration_rates"], bursts=config["migration_bursts"],\n            cleanup_timeout_seconds=timing["cleanup_timeout_seconds"])')
s = s.replace('migration_results = await migration.migrate(affected_items, deadline_ns=deadline)',
              'migration_results = await migration.migrate(affected_items, deadline_ns=min(\n            expansion_ns+int(timing["task_lifetime_seconds"]*1e9),\n            workload_origin_ns+int(timing["handover_deadline_seconds"]*1e9)))')
start = s.index('        post_responses = []')
end = s.index('        # Persist every foreground issued operation', start)
s = s[:start] + '''        final_publication_ns = time.monotonic_ns()
        responses = await generator
        generator = None
        await asyncio.sleep(max(0, (workload_origin_ns+int(timing["measurement_horizon_seconds"]*1e9)
                                    - time.monotonic_ns())/1e9))
        await sampler.close()
        await router.finalize_requests()
        for response in responses:
            expected = dataset.by_key()[response.record.key]
            if response.value is None or response.value.payload != expected.payload:
                raise ValueError("foreground authoritative payload check failed")
        miss_responses, post_responses = responses[:2], responses[2:]
        width = int(timing["stability_subwindow_seconds"]*1e9)
        stability_origin = workload_origin_ns+int(timing["stability_start_seconds"]*1e9)
        stability = []
        for index in range(timing["stability_subwindows"]):
            start_ns = stability_origin+index*width
            rows = [response.record for response in post_responses
                    if start_ns <= response.record.submitted_ns < start_ns+width]
            if (start_ns < final_publication_ns or len(rows) < timing["stability_min_requests"]
                    or any(row.route.owner != routing["destination"] or row.route.epoch != publication_epoch
                           for row in rows)):
                raise RuntimeError("traffic_stability_inconclusive_or_wrong_owner")
            stability.append({"start_ns": start_ns, "end_ns": start_ns+width,
                              "submitted_affected": len(rows), "destination_share": 1.0,
                              "completed": sum(row.outcome.value == "completed" for row in rows)})
        if stability[-1]["end_ns"] > workload_origin_ns+int(timing["handover_deadline_seconds"]*1e9):
            raise RuntimeError("handover_deadline_exceeded")
        write_json(run_dir / "stability.json", {"windows": stability,
                   "final_publication_ns": final_publication_ns, "measurement_ended_ns": time.monotonic_ns()})
        probe_records = [row for cache in background_caches.values() for row in cache.probe_records]
        probe_records += database.probe_records
        for operation in migration.operation_records + probe_records:
            await _emit(metrics, _event(run_id, origin_ns, phase=EventPhase.TERMINAL,
                epoch=int(ownership.snapshot.epoch), kind=EventKind.ACCOUNTING,
                reason="issued_operation", accounting={"issued_operations": 1}, detail=operation),
                timing["metric_timeout_seconds"])
        cache_pressure = {node: rows['state'] for node, rows in sampler.rounds[-1]['samples'].items()
                          if node != 'database'}
        db_pressure = sampler.rounds[-1]['samples']['database']['state']
''' + s[end:]
s = s.replace('"caches": {node: {"maximum_concurrency": client.maximum_concurrency,\n                                        "cancelled_operations": client.cancelled_operations}\n                                 for node, client in caches.items()}',
'''"caches": {node: {"foreground_maximum_concurrency": caches[node].maximum_concurrency,
                                        "background_maximum_concurrency": background_caches[node].maximum_concurrency,
                                        "maximum_concurrency": caches[node].maximum_concurrency+background_caches[node].maximum_concurrency}
                                 for node in caches}''')
s = s.replace('"pressure": {"database": db_pressure.state.value,\n                         "caches": {node: sample.state.value for node, sample in cache_pressure.items()},',
              '"pressure": {"database": db_pressure, "rounds": len(sampler.rounds),\n                         "caches": cache_pressure,')
s = s.replace('"observation_db_attempts": 1,',
              '"observation_db_attempts": len(database.probe_records),\n                           "observation_cache_attempts": sum(len(c.probe_records) for c in background_caches.values()),')
s = s.replace('    finally:\n        try:\n            await metrics.close(', '''    finally:
        if generator is not None:
            generator.cancel()
            await asyncio.gather(generator, return_exceptions=True)
        if sampler is not None:
            try:
                await sampler.close()
            except Exception as sampler_error:
                status, exit_code = "invalid_measurement", 1
                error_record = error_record or {"type": type(sampler_error).__name__, "message": str(sampler_error)}
        try:
            await metrics.close(''')
s = s.replace('        for client in caches.values():\n', '        for client in (*caches.values(), *background_caches.values()):\n')
p.write_text(s, encoding='utf-8')
