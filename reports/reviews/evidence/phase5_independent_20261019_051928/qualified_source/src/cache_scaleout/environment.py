"""Prerequisite inspection. Never installs software or changes engine settings."""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys

from .evidence import ROOT, command, source_fingerprint, utc_now, write_json


def docker_path() -> str:
    candidates = [shutil.which('docker'),
                  str(Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/DockerDesktop/resources/bin/docker.exe'),
                  'C:/Program Files/Docker/Docker/resources/bin/docker.exe']
    return next((p for p in candidates if p and Path(p).is_file()), 'docker')


def inspect_containers(docker: str, config: dict) -> tuple[list, list]:
    checks, containers = [], []
    ids_result = command([docker, 'ps', '-aq', '--filter', f"label=com.docker.compose.project={config['compose_project']}"])
    checks.append(ids_result)
    for identifier in ids_result.get('stdout', '').splitlines():
        if not re.fullmatch('[0-9a-f]{12,64}', identifier):
            continue
        # Never collect Config.Env or complete docker inspect output: they contain credentials.
        template = ('{"id":{{json .Id}},"image_id":{{json .Image}},"image_reference":{{json .Config.Image}},'
                    '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
                    '"state":{{json .State.Status}},"health":{{json .State.Health.Status}},'
                    '"memory_bytes":{{json .HostConfig.Memory}},"nano_cpus":{{json .HostConfig.NanoCpus}},'
                    '"shm_bytes":{{json .HostConfig.ShmSize}},"ports":{{json .NetworkSettings.Ports}}}')
        result = command([docker, 'inspect', identifier, '--format', template])
        checks.append(result)
        if result.get('exit_code') == 0:
            record = json.loads(result['stdout'])
            image = command([docker, 'image', 'inspect', record['image_id'], '--format',
                             '{"digests":{{json .RepoDigests}},"os":{{json .Os}},"architecture":{{json .Architecture}}}'])
            checks.append(image)
            if image.get('exit_code') == 0:
                record['image'] = json.loads(image['stdout'])
            containers.append(record)
    return checks, containers


def doctor(config: dict, output: Path) -> int:
    checks = []
    versions = {}
    required = {'redis': 'redis.asyncio', 'psycopg': 'psycopg', 'psycopg-pool': 'psycopg_pool', 'PyYAML': 'yaml'}
    for package, module in required.items():
        try:
            importlib.import_module(module)
            versions[package] = importlib.metadata.version(package)
        except (ImportError, importlib.metadata.PackageNotFoundError) as error:
            checks.append({'check': f'import {module}', 'passed': False, 'error': str(error)})
    lock_ok = True
    lock_versions = {}
    lock_path = ROOT / 'requirements.lock'
    if not lock_path.exists():
        lock_ok = False
    else:
        for line in lock_path.read_text().splitlines():
            match = re.match(r'([\w-]+)==(\S+) --hash=sha256:', line)
            if match:
                package, expected = match.groups()
                try:
                    actual = importlib.metadata.version(package)
                except importlib.metadata.PackageNotFoundError:
                    actual = None
                lock_versions[package] = {'expected': expected, 'actual': actual}
                lock_ok &= expected == actual
    runtime_ok = sys.version_info[:2] == (3, 12) and len(versions) == len(required) and lock_ok
    checks.append({'check': 'runtime_and_dependency_lock', 'passed': runtime_ok})
    docker = docker_path()
    for args in [['version', '--format', '{{json .}}'], ['compose', 'version']]:
        checks.append(command([docker, *args]))
    info = command([docker, 'info', '--format',
                    '{"os_type":{{json .OSType}},"architecture":{{json .Architecture}},"server_version":{{json .ServerVersion}},'
                    '"cpus":{{json .NCPU}},"memory_bytes":{{json .MemTotal}},"kernel":{{json .KernelVersion}},'
                    '"cgroup_version":{{json .CgroupVersion}},"storage_driver":{{json .Driver}}}'])
    checks.append(info)
    engine = json.loads(info['stdout']) if info.get('exit_code') == 0 else {}
    engine_ok = engine.get('os_type') == 'linux'
    container_checks, containers = inspect_containers(docker, config)
    checks.extend(container_checks)
    expected = {'cache-old-1', 'cache-old-2', 'cache-new', 'database'}
    services_ok = {c['service'] for c in containers} == expected and all(
        c['state'] == 'running' and c['health'] == 'healthy' and c.get('image', {}).get('digests')
        for c in containers)
    hardware = {}
    if sys.platform == 'win32':
        script = ('$ErrorActionPreference="Stop"; '
                  '$o=Get-CimInstance Win32_OperatingSystem; $p=Get-CimInstance Win32_Processor; '
                  '$d=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID=\'C:\'"; '
                  '@{os=@{caption=$o.Caption;version=$o.Version;total_ram_kib=$o.TotalVisibleMemorySize;free_ram_kib=$o.FreePhysicalMemory};'
                  'cpu=@{name=$p.Name;cores=$p.NumberOfCores;logical_processors=$p.NumberOfLogicalProcessors};'
                  'disk=@{total_bytes=$d.Size;free_bytes=$d.FreeSpace}} | ConvertTo-Json -Depth 4 -Compress')
        hardware_result = command(['powershell.exe', '-NoProfile', '-Command', script])
        checks.append(hardware_result)
        if hardware_result.get('exit_code') == 0:
            hardware = json.loads(hardware_result['stdout'])
        checks.extend([command(['wsl.exe', '--version']), command(['wsl.exe', '--list', '--verbose'])])
    checks.append(command(['git', '--version']))
    checks.append(command(['git', 'rev-parse', '--show-toplevel']))
    # An unborn parent repository is expected here. Fingerprints identify this project.
    checks.append(command(['git', 'rev-parse', '--verify', 'HEAD']))
    checks.append(command(['git', 'status', '--short', '--', '.']))
    manifest = {'schema_version': 1, 'captured_utc': utc_now(), 'platform': platform.platform(),
                'shell': 'Native Windows PowerShell 5.1; not WSL execution',
                'runtime': {'version': platform.python_version(), 'executable': sys.executable,
                            'implementation': platform.python_implementation(), 'machine': platform.machine()},
                'packages': versions, 'locked_packages': lock_versions, 'hardware': hardware,
                'docker_engine': engine, 'containers': containers, 'checks': checks,
                'source': source_fingerprint(),
                'gate_checks': {'runtime': runtime_ok, 'linux_engine': engine_ok,
                                'required_containers_healthy_with_digests': services_ok},
                'status': 'verified' if runtime_ok and engine_ok and services_ok else 'missing_prerequisites',
                'boundary': 'Doctor checks prerequisites and container health; run health separately for client read/write verification.'}
    # Refuse overwriting previous environment evidence; use a new output for reruns.
    if output.exists():
        raise FileExistsError(f'Environment evidence already exists: {output}; choose a new output')
    write_json(output, manifest)
    print(json.dumps({'status': manifest['status'], 'gate_checks': manifest['gate_checks'], 'output': str(output)}))
    return 0 if manifest['status'] == 'verified' else 1

