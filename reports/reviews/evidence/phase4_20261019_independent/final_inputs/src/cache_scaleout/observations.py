"""Bounded exact demand and conservative destination-residency observations."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from types import MappingProxyType

from .contracts import (
    BucketId, DemandSnapshot, Key, KeyDemand, NodeId, ObservationWindow,
    ResidencyEvidence, ResidencyState,
)


class BoundedDemandTracker:
    def __init__(self, *, subwindow_ns: int, retained_subwindows: int,
                 max_total_keys: int, max_keys_per_bucket: int, max_buckets: int,
                 max_age_ns: int, origin_ns: int = 0) -> None:
        values = (subwindow_ns, retained_subwindows, max_total_keys,
                  max_keys_per_bucket, max_buckets, max_age_ns)
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError("all demand bounds must be positive integers")
        self.subwindow_ns = subwindow_ns
        self.retained_subwindows = retained_subwindows
        self.max_total_keys = max_total_keys
        self.max_keys_per_bucket = max_keys_per_bucket
        self.max_buckets = max_buckets
        self.max_age_ns = max_age_ns
        self.origin_ns = origin_ns
        self._registry: dict[Key, tuple[BucketId, int]] = {}
        self._slots: OrderedDict[int, dict[Key, list[int]]] = OrderedDict()
        self._overflow: OrderedDict[int, dict[BucketId, int]] = OrderedDict()

    def register(self, keys_by_bucket: Mapping[BucketId, Mapping[Key, int]]) -> None:
        registry: dict[Key, tuple[BucketId, int]] = {}
        if len(keys_by_bucket) > self.max_buckets:
            raise ValueError("bucket registry exceeds bound")
        for bucket, keys in keys_by_bucket.items():
            if type(bucket) is not int or not 0 <= bucket < self.max_buckets:
                raise ValueError("invalid registry bucket")
            if len(keys) > self.max_keys_per_bucket:
                raise ValueError("per-bucket registry exceeds bound")
            for key, object_bytes in keys.items():
                if key in registry or not key or type(object_bytes) is not int or object_bytes < 1:
                    raise ValueError("invalid or duplicate registered key")
                registry[key] = (bucket, object_bytes)
        if len(registry) > self.max_total_keys:
            raise ValueError("total registry exceeds bound")
        self._registry = registry
        self._slots.clear()
        self._overflow.clear()

    @property
    def registered(self) -> Mapping[Key, tuple[BucketId, int]]:
        return MappingProxyType(dict(self._registry))

    def _rotate(self, slot: int) -> None:
        if self._slots and slot < max(self._slots)-(self.retained_subwindows-1)*self.subwindow_ns:
            raise ValueError('observation older than retained demand history')
        self._slots.setdefault(slot, {})
        self._overflow.setdefault(slot, {})
        self._slots = OrderedDict(sorted(self._slots.items()))
        latest = max(self._slots)
        for old in tuple(self._slots):
            if old < latest-(self.retained_subwindows-1)*self.subwindow_ns:
                self._slots.pop(old)
                self._overflow.pop(old, None)
        while len(self._slots) > self.retained_subwindows:
            old, _ = self._slots.popitem(last=False)
            self._overflow.pop(old, None)

    def observe(self, key: Key, bucket: BucketId, object_bytes: int, *, at_ns: int) -> None:
        if type(at_ns) is not int or at_ns < 0:
            raise ValueError("observation time must be nonnegative")
        if type(bucket) is not int or not 0 <= bucket < self.max_buckets:
            raise ValueError("overflow bucket outside configured registry bound")
        slot = self.origin_ns + ((at_ns-self.origin_ns) // self.subwindow_ns) * self.subwindow_ns
        self._rotate(slot)
        if slot not in self._slots:
            raise ValueError("observation older than retained demand history")
        registered = self._registry.get(key)
        if registered != (bucket, object_bytes):
            overflow = self._overflow[slot]
            overflow[bucket] = overflow.get(bucket, 0) + 1
            return
        entry = self._slots[slot].setdefault(key, [0, at_ns])
        entry[0] += 1
        entry[1] = max(entry[1], at_ns)

    def snapshot(self, *, start_ns: int, end_ns: int, observed_at_ns: int) -> DemandSnapshot:
        if ((start_ns-self.origin_ns) % self.subwindow_ns or (end_ns-self.origin_ns) % self.subwindow_ns
                or end_ns-start_ns != self.retained_subwindows*self.subwindow_ns):
            raise ValueError("demand windows must align to subwindows")
        counts: dict[Key, list[int]] = {}
        overflow: dict[BucketId, int] = {}
        for slot, entries in self._slots.items():
            if start_ns <= slot < end_ns:
                for key, (count, last_seen) in entries.items():
                    total = counts.setdefault(key, [0, last_seen])
                    total[0] += count
                    total[1] = max(total[1], last_seen)
                for bucket, count in self._overflow.get(slot, {}).items():
                    overflow[bucket] = overflow.get(bucket, 0) + count
        demand = tuple(sorted((KeyDemand(key, self._registry[key][0], value[0],
                                            self._registry[key][1], value[1])
                               for key, value in counts.items()), key=lambda entry: entry.key))
        return DemandSnapshot(ObservationWindow(start_ns, end_ns, observed_at_ns, self.max_age_ns),
                              demand, self.max_keys_per_bucket, self.max_total_keys,
                              self.max_buckets, overflow)

    def reset(self, namespace: str) -> None:
        if not namespace:
            raise ValueError("reset namespace is required")
        self._slots.clear()
        self._overflow.clear()


class ResidencyTracker:
    def __init__(self, *, destination: NodeId, registered_keys: tuple[Key, ...]) -> None:
        if not destination or len(set(registered_keys)) != len(registered_keys):
            raise ValueError("bounded unique residency registry required")
        self.destination = destination
        self._registered = frozenset(registered_keys)
        self._evidence: dict[Key, ResidencyEvidence] = {}

    def confirm(self, key: Key, *, observed_at_ns: int, valid_until_ns: int | None) -> None:
        if key not in self._registered:
            raise ValueError("unregistered residency key")
        self._evidence[key] = ResidencyEvidence(key, self.destination, ResidencyState.CONFIRMED,
                                                observed_at_ns, valid_until_ns)

    def invalidate(self, key: Key, *, state: ResidencyState, observed_at_ns: int) -> None:
        if state is ResidencyState.CONFIRMED:
            raise ValueError("invalidation requires a non-confirmed state")
        if key in self._registered:
            self._evidence[key] = ResidencyEvidence(key, self.destination, state,
                                                    observed_at_ns, observed_at_ns)

    def snapshot(self) -> Mapping[Key, ResidencyEvidence]:
        return MappingProxyType(dict(self._evidence))

    def reset(self) -> None:
        self._evidence.clear()
