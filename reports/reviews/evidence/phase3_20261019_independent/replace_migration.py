from pathlib import Path
path = Path('src/cache_scaleout/migration.py')
source = path.read_text(encoding='utf-8')
start = source.index('    async def _migrate_one(')
end = source.index('    @property\n    def residency_state_expired', start)
source = source[:start] + '''    async def _migrate_one(self, item: DatasetItem, deadline_ns: int,
                           allow_db_fallback: bool) -> MigrationResult:
        bucket = self.ownership.bucket_for_key(item.key)
        donor_owner = str(self.ownership.old_owner(bucket))
        destination_owner = str(self.destination_cache.node_id)
        size = item.object_bytes
        # The immutable registry bounds payload; the envelope covers namespaced
        # RESP keys, commands, framing and small replies. SQL actual bytes remain
        # unknown rather than being misreported as payload length.
        encoded_bound = size + 1024
        attempts = 0
        value = None
        source_name = None
        reservation = None
        acquired = False
        def terminal(reason):
            return MigrationResult(item.key, bucket, "not_warmed", source_name, attempts, reason)
        try:
            await self._buffer_acquire(size, deadline_ns)
            acquired = True
            reservation = await self.grants.reserve_destination(encoded_bound)
            if reservation is None:
                return terminal("destination_grant_exhausted_or_pressure_paused")
            # Source IO requires both a payload slot and a destination reservation.
            for stage, client, policy, source, owner, work_class in (
                ("donor", self.donor_caches[donor_owner], self.donor_retry,
                 DataSource.DONOR_CACHE, donor_owner, WorkClass.DONOR_READ),
                ("database", self.database, self.db_retry, DataSource.DATABASE,
                 "database", WorkClass.DISCRETIONARY_DATABASE_WARMUP)):
                if value is not None or (stage == "database" and not allow_db_fallback):
                    break
                for attempt in range(1, policy.max_attempts + 1):
                    token_deadline = min(deadline_ns, self.grants.valid_until_ns)
                    dimensions = ({"donor_operations": 1, "donor_bytes": encoded_bound}
                                  if stage == "donor" else {"background_db_operations": 1})
                    await self.tokens.acquire(dimensions, token_deadline)
                    # A replacement must not leave source work using an obsolete
                    # destination promise.
                    if reservation.generation != self.grants.last_decided_at_ns:
                        return terminal("destination_grant_replaced")
                    issued = (await self.grants.issue_donor(encoded_bound) if stage == "donor"
                              else await self.grants.issue_database())
                    if not issued:
                        break
                    attempts += 1
                    attempt_deadline = min(deadline_ns, time.monotonic_ns() + int(
                        policy.attempt_timeout_seconds * 1e9))
                    operation = (client.read(item.key, source=source, deadline_ns=attempt_deadline)
                                 if stage == "donor" else client.read_for_warmup(
                                     item.key, deadline_ns=attempt_deadline))
                    try:
                        result = await self._attempt(item=item, stage=stage, attempt=attempt,
                            source=source, source_owner=owner, work_class=work_class,
                            reserved_bytes=encoded_bound, deadline_ns=attempt_deadline,
                            operation=operation)
                        value = result.value if stage == "donor" else result
                        if value is not None:
                            source_name = "donor_cache" if stage == "donor" else "database"
                        break
                    except TRANSIENT_ERRORS:
                        if attempt < policy.max_attempts:
                            await self._sleep_backoff(policy.backoff_seconds[attempt-1], deadline_ns)
            if value is None:
                return terminal("source_exhausted_or_db_budget_unavailable")
            if value.payload != item.payload:
                raise ValueError(f"authoritative payload mismatch for {item.key}")
            # Registry expiry caps both donor and authoritative values, even if a
            # service unexpectedly retained the object with an extended TTL.
            expiries = [expiry for expiry in (value.absolute_expiry_ns, item.absolute_expiry_ns)
                        if expiry is not None]
            if expiries:
                from dataclasses import replace
                value = replace(value, absolute_expiry_ns=min(expiries))
            if value.absolute_expiry_ns is not None and time.monotonic_ns() >= value.absolute_expiry_ns:
                self.residency.invalidate(item.key, state=self.residency_state_expired,
                                          observed_at_ns=time.monotonic_ns())
                return terminal("expired_before_destination_write")
            for attempt in range(1, self.write_retry.max_attempts + 1):
                if attempt > 1:
                    reservation = await self.grants.reserve_destination(encoded_bound)
                if reservation is None:
                    return terminal("destination_retry_grant_exhausted")
                await self.tokens.acquire({"destination_write_operations": 1,
                                           "destination_write_bytes": encoded_bound},
                                          min(deadline_ns, self.grants.valid_until_ns))
                await self.grants.issue_destination(reservation)
                attempts += 1
                attempt_deadline = min(deadline_ns, time.monotonic_ns() + int(
                    self.write_retry.attempt_timeout_seconds * 1e9))
                try:
                    await self._attempt(item=item, stage="write", attempt=attempt,
                        source=DataSource.NEW_CACHE, source_owner=destination_owner,
                        work_class=WorkClass.DESTINATION_WRITE, reserved_bytes=encoded_bound,
                        deadline_ns=attempt_deadline,
                        operation=self.destination_cache.write(item.key, value, deadline_ns=attempt_deadline))
                    self.residency.confirm(item.key, observed_at_ns=time.monotonic_ns(),
                                           valid_until_ns=value.absolute_expiry_ns)
                    return MigrationResult(item.key, bucket, "warmed", source_name, attempts, "written")
                except TRANSIENT_ERRORS:
                    if attempt < self.write_retry.max_attempts:
                        await self._sleep_backoff(self.write_retry.backoff_seconds[attempt-1], deadline_ns)
            return terminal("destination_write_retries_exhausted")
        except TimeoutError:
            return terminal("task_or_grant_deadline_expired")
        finally:
            if reservation is not None:
                reservation.release()
            if acquired:
                await self._buffer_release(size)

''' + source[end:]
path.write_text(source, encoding='utf-8')
