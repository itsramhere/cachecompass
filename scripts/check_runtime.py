import importlib.metadata
import json
import platform
import sys

import redis.asyncio
import psycopg
import psycopg_pool
import yaml

if sys.version_info[:2] != (3, 12):
    raise SystemExit('The reviewed runtime requires CPython 3.12')
print(json.dumps({'status': 'imports_verified', 'python': platform.python_version(),
                  'packages': {name: importlib.metadata.version(name)
                               for name in ('redis', 'psycopg', 'psycopg-pool', 'PyYAML')}}))

