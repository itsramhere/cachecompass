"""Only Phase 0 doctor and health are implemented; later experiment commands are deferred."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from .evidence import ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    for name in ('doctor', 'health'):
        child = subparsers.add_parser(name)
        child.add_argument('--config', default='configs/environment.json')
        if name == 'doctor':
            child.add_argument('--output', default='reports/environment.json')
        else:
            child.add_argument('--run-id', required=True)
            child.add_argument('--retry-of')
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if args.command == 'doctor':
        from .environment import doctor
        return doctor(config, ROOT / args.output)
    from .health import health
    # Psycopg async connections on Windows require Selector, not default Proactor.
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(health(config, config_path, args.run_id, args.retry_of))


if __name__ == '__main__':
    raise SystemExit(main())
