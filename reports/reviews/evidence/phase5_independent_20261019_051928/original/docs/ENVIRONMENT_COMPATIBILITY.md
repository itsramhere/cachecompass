# Environment compatibility and version selection

Official sources checked on 2026-10-09. Pinning stabilizes this research artifact; it is not a claim that selected versions are newest.

| Component | Selected environment | Official basis and verification |
| --- | --- | --- |
| Python | Existing CPython 3.12.10, Windows amd64; .python-version | [Python branch status](https://devguide.python.org/versions/) documents branch lifecycle. Local executable/runtime and client imports are checked by bootstrap and doctor. No runtime upgrade performed. |
| Redis client | redis-py 6.4.0 | [Tagged package configuration](https://github.com/redis/redis-py/blob/v6.4.0/pyproject.toml) and [release](https://github.com/redis/redis-py/releases/tag/v6.4.0) verify the version. [Official async guide](https://redis.io/docs/latest/develop/clients/redis-py/async/) documents redis.asyncio, connection limits and explicit cleanup. Actual commands are verified against the pinned server. |
| PostgreSQL client | psycopg / psycopg-binary 3.2.10; psycopg-pool 3.3.3 | [Official installation guide](https://www.psycopg.org/psycopg3/docs/basic/install.html) documents Windows, binary wheels and a separately versioned pool. Its current support range is not a retrospective guarantee for every earlier release; downloaded wheel metadata and actual imports/integration establish the selected combination here. |
| Windows asyncio | WindowsSelectorEventLoopPolicy | [Psycopg async documentation](https://www.psycopg.org/psycopg3/docs/advanced/async.html) requires an alternative to Windows' default Proactor loop. CLI selects Selector before running health. |
| Redis servers | Official redis:7.4-alpine, resolved to immutable digest | [Official image documentation](https://hub.docker.com/_/redis). Three independent instances; actual minor version and digest captured in health/environment evidence. |
| Database | Official postgres:17-alpine, resolved to immutable digest | [Official image documentation](https://hub.docker.com/_/postgres) and [PostgreSQL version policy](https://www.postgresql.org/support/versioning/) support the major-version choice. Server version is read through SQL. |
| Docker / Compose | Existing Docker Desktop; client 29.8.0; Compose v5.5.1 | [Windows requirements](https://docs.docker.com/desktop/setup/install/windows-install/) and [WSL2 backend documentation](https://docs.docker.com/desktop/features/wsl/). Existing Windows Home, WSL2 2.6.3 and Linux engine are checked; Ubuntu integration is not required for the native PowerShell path. |

requirements.lock includes exact versions and SHA256 hashes of all seven CPython 3.12 Windows wheels, including transitive dependencies. The pool release resolves independently from psycopg; both are locked. This lock is validated on Windows amd64; Linux package bootstrap is not certified by this phase. Dependency bootstrap avoids editable builds and uses PYTHONPATH=src, so the pyproject build backend is not exercised.

infra/images.env locks manifest digests and Compose forces linux/amd64. Tagged pulls are only for initial resolution; subsequent startup uses retained digests. The environment manifest records the resolved platform image IDs, repository digests, CPU/memory quotas, Docker engine allocation, hardware and package versions. No complete environment or container credential fields are collected.

