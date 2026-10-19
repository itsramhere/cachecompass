"""Persisted independent offers dispatched without waiting for responses."""
import asyncio
import time

from .contracts import RequestRecord, OperationOutcome, DataSource


async def sleep_until_ns(deadline_ns):
    while deadline_ns > time.monotonic_ns():
        await asyncio.sleep(max(.001, (deadline_ns-time.monotonic_ns())/1e9))


async def dispatch_offers(*, schedule, router, items, on_arrival, metrics,
                          timeout_seconds, metric_timeout_seconds):
    responses = []
    submitted = set()
    tasks = []
    try:
        for offer in schedule:
            # Selector timers and CPython 3.12 monotonic ticks may wake before
            # the registered nanosecond arrival. Never submit an offer early.
            await sleep_until_ns(offer['scheduled_arrival_ns'])
            await on_arrival(offer)
            item = items[offer['key']]
            submitted.add(offer['request_id'])
            tasks.append(asyncio.create_task(router.read(
                request_id=offer['request_id'], key=item.key,
                scheduled_arrival_ns=offer['scheduled_arrival_ns'], timeout_seconds=timeout_seconds,
                object_bytes=item.object_bytes), name='offer:'+offer['request_id']))
        responses = await asyncio.gather(*tasks)
        return responses
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for offer in schedule:
            if offer['request_id'] not in submitted:
                await sleep_until_ns(offer['scheduled_arrival_ns'])
                await on_arrival(offer)
                await metrics.emit_request(RequestRecord(
                    1, router.run_id, offer['request_id'], offer['scheduled_arrival_ns'], None, None,
                    timeout_seconds, OperationOutcome.UNSUBMITTED, None, DataSource.NONE,
                    None, 0, 0, None, 'generator_stopped_before_submission', offer['key']),
                    deadline_ns=time.monotonic_ns()+int(metric_timeout_seconds*1e9))
        await router.finalize_requests()
