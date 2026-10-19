"""Local research environment and Phase 3 functional verification commands."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from .evidence import ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    for name in ('doctor', 'health', 'phase3-run', 'phase3-validate', 'phase4-calibrate', 'phase4-immediate'):
        child = subparsers.add_parser(name)
        child.add_argument('--config', default=('configs/phase3_smoke.yaml' if name.startswith('phase3-') else ('configs/phase4_calibration.yaml' if name.startswith('phase4-') else 'configs/environment.json')))
        if name == 'doctor':
            child.add_argument('--output', default='reports/environment.json')
        elif name in {'health', 'phase3-run'}:
            child.add_argument('--run-id', required=True)
            child.add_argument('--retry-of')
        elif name == 'phase3-validate':
            child.add_argument('--run', required=True)
            child.add_argument('--compare-run')
            child.add_argument('--output', required=True)
        elif name == 'phase4-calibrate':
            child.add_argument('--run-id', required=True); child.add_argument('--rate', required=True, type=float)
        elif name == 'phase4-immediate':
            child.add_argument('--run-id', required=True); child.add_argument('--rate', required=True, type=float); child.add_argument('--condition', required=True, choices=('control','immediate'))
    args = parser.parse_args()
    config_path = (ROOT / args.config).resolve()
    if args.command == 'doctor':
        config = json.loads(config_path.read_text(encoding='utf-8'))
        from .environment import doctor
        return doctor(config, ROOT / args.output)
    # Psycopg async connections on Windows require Selector, not default Proactor.
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if args.command == 'health':
        from .health import health
        config = json.loads(config_path.read_text(encoding='utf-8'))
        return asyncio.run(health(config, config_path, args.run_id, args.retry_of))
    if args.command == 'phase3-run':
        from .phase3 import load_phase3_config, run_phase3
        return asyncio.run(run_phase3(load_phase3_config(config_path), config_path,
                                      args.run_id, args.retry_of))
    if args.command == 'phase4-calibrate':
        from .phase4 import load_phase4_config, run_calibration
        return asyncio.run(run_calibration(load_phase4_config(config_path), config_path, args.run_id, args.rate))
    if args.command == 'phase4-immediate':
        from .phase4 import load_phase4_config, run_immediate
        return asyncio.run(run_immediate(load_phase4_config(config_path), config_path, args.run_id, args.rate, args.condition))
    from .evidence import write_json
    from .phase3 import validate_phase3_run
    output = (ROOT / args.output).resolve()
    if output.exists():
        raise ValueError('validation output exists; choose a new path')
    result = validate_phase3_run((ROOT / args.run).resolve(),
                                 None if not args.compare_run else (ROOT / args.compare_run).resolve())
    write_json(output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
