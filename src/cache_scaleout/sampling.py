"""Fixed common observation rounds, independent of migration grants."""
import asyncio
import time


class PressureSampler:
    def __init__(self, *, caches, database, key, interval_seconds, timeout_seconds,
                 on_round, residency=None, maximum_rounds=64, stop_at_ns=None):
        if interval_seconds <= 0 or timeout_seconds <= 0:
            raise ValueError('finite positive sampling timing required')
        self.caches = caches
        self.database = database
        self.key = key
        self.interval = interval_seconds
        self.timeout = timeout_seconds
        self.on_round = on_round
        self.residency = residency
        self.rounds = []
        self._task = None
        self._stop = asyncio.Event()
        self._evictions = {node: 0 for node in caches}
        self.maximum_rounds = maximum_rounds
        self.stop_at_ns=stop_at_ns

    async def start(self):
        if self._task is not None:
            raise RuntimeError('sampler already started')
        self._task = asyncio.create_task(self._run(), name='common-pressure-sampler')

    async def _run(self):
        next_tick = time.monotonic()
        while not self._stop.is_set():
            if len(self.rounds) >= self.maximum_rounds:
                raise BufferError('bounded observation history exhausted')
            delay = next_tick-time.monotonic()
            if delay > 0:
                try:
                    await asyncio.wait_for(self._stop.wait(), delay)
                    break
                except TimeoutError:
                    pass
            started = time.monotonic_ns()
            if self._stop.is_set() or self.stop_at_ns is not None and started>=self.stop_at_ns:break
            deadline = started + int(self.timeout*1e9)
            # One task per service and no overlapping rounds. Migration uses the
            # same bounded background pools; foreground pools remain reserved.
            results = await asyncio.gather(
                *(cache.sample_pressure(deadline_ns=deadline) for cache in self.caches.values()),
                self.database.sample_pressure(self.key, deadline_ns=deadline))
            residency_reset_ns=None
            if self.residency is not None:
                for node, cache in self.caches.items():
                    if cache.evicted_keys > self._evictions[node] and node == self.residency.destination:
                        self.residency.reset()
                        residency_reset_ns=time.monotonic_ns()
                    self._evictions[node] = cache.evicted_keys
            row = {'started_ns': started, 'ended_ns': time.monotonic_ns(),'residency_reset_ns':residency_reset_ns,
                   'raw_cache_samples':{node:dict(cache.last_pressure_detail) for node,cache in self.caches.items()},
                   'raw_database_sample':dict(self.database.last_pressure_detail),
                   'samples': {node: {'state': result.state.value, 'reason': result.reason,
                                     'observed_at_ns': result.observed_at_ns}
                               for node, result in zip((*self.caches, 'database'), results)}}
            self.rounds.append(row)
            await self.on_round(row)
            # Missed ticks are lost, never caught up in a burst.
            next_tick += self.interval
            if next_tick < time.monotonic():
                next_tick = time.monotonic()+self.interval

    async def close(self):
        self._stop.set()
        if self._task is not None:
            await self._task
