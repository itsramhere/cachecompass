"""Safe, explicit evidence capture shared by the Phase 0 tools."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def source_fingerprint() -> dict:
    """Hash reviewable source/config inputs, excluding changing reports and outputs."""
    files = []
    for path in sorted(ROOT.rglob('*')):
        relative = path.relative_to(ROOT)
        if (relative.parts[0] in {'.wheelhouse', '.git', 'reports', 'runs', 'test_out', 'venv',
                                 'build', 'dist', 'htmlcov', '.codex', '.cache', '.aws', '.agents',
                                 '.idea', '.vscode', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
                or relative.parts[0].startswith('.venv')):
            continue
        if ('__pycache__' in relative.parts or not path.is_file() or path.suffix in {'.pyc','.pem','.key'}
                or path.name == '.env' or (path.name.startswith('.env.') and path.name not in {'.env.example','.env.sample'})):
            continue
        files.append({'path': relative.as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    canonical = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
    return {'algorithm': 'sha256', 'aggregate_sha256': hashlib.sha256(canonical).hexdigest(),
            'definition': 'SHA256 of canonical JSON file list; excludes reports, runs, ignored test_out/build/cache/agent state, virtualenvs, wheels, bytecode and secrets',
            'files': files}


def command(args: list[str], timeout: float = 20) -> dict:
    start = time.monotonic()
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, cwd=ROOT)
        # WSL commands can emit UTF-16LE despite being invoked by native Python.
        def decode(data: bytes) -> str:
            return data.decode('utf-16le' if b'\x00' in data else 'utf-8', errors='replace').strip()
        return {'command': args, 'exit_code': result.returncode, 'stdout': decode(result.stdout),
                'stderr': decode(result.stderr), 'elapsed_seconds': time.monotonic() - start}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'command': args, 'exit_code': None, 'error': str(error),
                'elapsed_seconds': time.monotonic() - start}

