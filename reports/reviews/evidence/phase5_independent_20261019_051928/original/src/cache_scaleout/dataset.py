"""Deterministic immutable datasets and stable seeded ownership."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from collections.abc import Iterable, Mapping

from .contracts import (
    BucketAdvance, BucketId, BucketState, CacheValue, Key, NodeId,
    RouteCapture, RoutingEpoch,
)


def _digest(*parts: object) -> bytes:
    encoded = b"\x00".join(str(part).encode("utf-8") for part in parts)
    return hashlib.sha256(encoded).digest()


@dataclass(frozen=True, slots=True)
class DatasetItem:
    key: Key
    payload: bytes
    version: str
    absolute_expiry_ns: int | None = None

    @property
    def object_bytes(self) -> int:
        return len(self.payload)

    def cache_value(self) -> CacheValue:
        return CacheValue(self.payload, self.absolute_expiry_ns, self.version)


@dataclass(frozen=True, slots=True)
class ImmutableDataset:
    seed: int
    items: tuple[DatasetItem, ...]
    checksum: str

    def by_key(self) -> Mapping[Key, DatasetItem]:
        return MappingProxyType({item.key: item for item in self.items})


def create_dataset(*, seed: int, key_count: int, value_bytes: int,
                   absolute_expiry_ns: int | None = None) -> ImmutableDataset:
    if type(seed) is not int or type(key_count) is not int or key_count < 1:
        raise ValueError("dataset seed and positive integer key_count are required")
    if type(value_bytes) is not int or value_bytes < 32:
        raise ValueError("value_bytes must be an integer >= 32")
    items: list[DatasetItem] = []
    for index in range(key_count):
        key = Key(f"key-{index:08d}")
        material = bytearray()
        counter = 0
        while len(material) < value_bytes:
            material.extend(_digest("dataset", seed, index, counter))
            counter += 1
        payload = bytes(material[:value_bytes])
        version = hashlib.sha256(payload).hexdigest()
        items.append(DatasetItem(key, payload, version, absolute_expiry_ns))
    canonical = [{"key": item.key, "payload_sha256": item.version,
                  "bytes": item.object_bytes, "absolute_expiry_ns": item.absolute_expiry_ns}
                 for item in items]
    checksum = hashlib.sha256(json.dumps(canonical, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    return ImmutableDataset(seed, tuple(items), checksum)


@dataclass(frozen=True, slots=True)
class RoutingSnapshot:
    epoch: RoutingEpoch
    states: Mapping[BucketId, BucketState]


class StableOwnershipMap:
    """SHA-256 bucket/rendezvous map with atomic immutable snapshots."""

    def __init__(self, *, mapping_seed: int, bucket_count: int,
                 old_nodes: tuple[NodeId, ...], final_nodes: tuple[NodeId, ...],
                 destination: NodeId) -> None:
        if type(mapping_seed) is not int or type(bucket_count) is not int or bucket_count < 1:
            raise ValueError("mapping seed and positive bucket count are required")
        if len(old_nodes) != 2 or len(final_nodes) != 3 or len(set(final_nodes)) != 3:
            raise ValueError("Phase 3 requires two unique old nodes and three unique final nodes")
        if destination in old_nodes or destination not in final_nodes or not set(old_nodes) < set(final_nodes):
            raise ValueError("destination must be the one final-only node")
        self.mapping_seed = mapping_seed
        self.bucket_count = bucket_count
        self.old_nodes = tuple(old_nodes)
        self.final_nodes = tuple(final_nodes)
        self.destination = destination
        self._old = MappingProxyType({BucketId(bucket): self._owner(bucket, old_nodes)
                                      for bucket in range(bucket_count)})
        self._final = MappingProxyType({BucketId(bucket): self._owner(bucket, final_nodes)
                                        for bucket in range(bucket_count)})
        self._affected = tuple(bucket for bucket in self._old
                               if self._final[bucket] == destination and self._old[bucket] != destination)
        if not self._affected:
            raise ValueError("mapping has no buckets affected by expansion")
        states = MappingProxyType({bucket: BucketState.OLD for bucket in self._affected})
        self._snapshot = RoutingSnapshot(RoutingEpoch(0), states)

    def _owner(self, bucket: int, nodes: Iterable[NodeId]) -> NodeId:
        return max(nodes, key=lambda node: (_digest("owner", self.mapping_seed, bucket, node), str(node)))

    def bucket_for_key(self, key: Key) -> BucketId:
        if not key:
            raise ValueError("key is required")
        return BucketId(int.from_bytes(_digest("bucket", self.mapping_seed, key)[:8], "big")
                        % self.bucket_count)

    def old_owner(self, bucket: BucketId) -> NodeId:
        return self._old[bucket]

    def final_owner(self, bucket: BucketId) -> NodeId:
        return self._final[bucket]

    @property
    def affected_buckets(self) -> tuple[BucketId, ...]:
        return self._affected

    @property
    def snapshot(self) -> RoutingSnapshot:
        return self._snapshot

    def state(self, bucket: BucketId) -> BucketState:
        return self._snapshot.states.get(bucket, BucketState.OLD)

    def capture(self, key: Key) -> RouteCapture:
        snapshot = self._snapshot
        bucket = self.bucket_for_key(key)
        state = snapshot.states.get(bucket, BucketState.OLD)
        owner = self._final[bucket] if state is BucketState.NEW else self._old[bucket]
        return RouteCapture(snapshot.epoch, bucket, owner, state)

    def publish(self, advances: tuple[BucketAdvance, ...], *,
                expected_epoch: RoutingEpoch) -> RoutingEpoch:
        snapshot = self._snapshot
        if expected_epoch != snapshot.epoch:
            raise ValueError("routing epoch changed")
        if not advances:
            return snapshot.epoch
        if len({advance.bucket for advance in advances}) != len(advances):
            raise ValueError("duplicate bucket in atomic publication")
        next_states = dict(snapshot.states)
        for advance in advances:
            if advance.bucket not in next_states:
                raise ValueError("only affected buckets may transition")
            if next_states[advance.bucket] is not advance.expected:
                raise ValueError("bucket state changed")
            next_states[advance.bucket] = advance.path[-1]
        epoch = RoutingEpoch(int(snapshot.epoch) + 1)
        self._snapshot = RoutingSnapshot(epoch, MappingProxyType(next_states))
        return epoch

    def keys_by_bucket(self, dataset: ImmutableDataset) -> Mapping[BucketId, tuple[DatasetItem, ...]]:
        grouped: dict[BucketId, list[DatasetItem]] = {BucketId(i): [] for i in range(self.bucket_count)}
        for item in dataset.items:
            grouped[self.bucket_for_key(item.key)].append(item)
        return MappingProxyType({bucket: tuple(sorted(items, key=lambda item: item.key))
                                 for bucket, items in grouped.items()})

    def summary(self) -> dict[str, object]:
        mapping = {
            "mapping_seed": self.mapping_seed,
            "bucket_count": self.bucket_count,
            "old_nodes": list(self.old_nodes),
            "final_nodes": list(self.final_nodes),
            "destination": self.destination,
            "old_owners": {str(k): v for k, v in self._old.items()},
            "final_owners": {str(k): v for k, v in self._final.items()},
            "affected_buckets": list(self._affected),
        }
        canonical = json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()
        return {**mapping, "checksum": hashlib.sha256(canonical).hexdigest()}
