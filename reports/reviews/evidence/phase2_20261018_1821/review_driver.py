"""Offline, append-only evidence for the independent Phase 2 review."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from cache_scaleout.evidence import source_fingerprint


def save(name, value):
    with (OUT / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def historical_files():
    result = {}
    for directory, children, files in os.walk(ROOT / "reports"):
        children[:] = [c for c in children if c != "tools" and Path(directory) / c != OUT]
        for name in files:
            path = Path(directory) / name
            result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


parser = argparse.ArgumentParser()
parser.add_argument("step", choices=("capture", "suite", "preservation", "audit"))
parser.add_argument("--label", required=True)
parser.add_argument("--retry-of")
args = parser.parse_args()
stamp = datetime.now(timezone.utc).isoformat()
if args.step == "capture":
    source = source_fingerprint()
    save(f"source_{args.label}.json", source)
    if args.label == "before":
        save("historical_before.json", historical_files())
    print(source["aggregate_sha256"], len(source["files"]))
elif args.step == "suite":
    command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"]
    run = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    save(f"tests_{args.label}.json", dict(started_utc=stamp,
         ended_utc=datetime.now(timezone.utc).isoformat(), command=command,
         retry_of=args.retry_of, exit_code=run.returncode, stdout=run.stdout, stderr=run.stderr,
         source=source_fingerprint()))
    print(run.stdout, run.stderr)
    raise SystemExit(run.returncode)
elif args.step == "preservation":
    before = json.loads((OUT / "historical_before.json").read_text(encoding="utf-8"))
    # These three living records are explicitly authorized to change.
    allowed = {"reports/STATUS.md", "reports/ISSUE_INDEX.md", "reports/DECISIONS.md", "reports/phase_02.md"}
    changed = [p for p, digest in before.items()
               if not (ROOT / p).is_file() or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != digest]
    unexpected = sorted(set(changed) - allowed)
    source = source_fingerprint()
    captured = json.loads((OUT / f"source_{args.label}.json").read_text(encoding="utf-8"))
    passed = not unexpected and source == captured
    save(f"preservation_{args.label}.json", dict(utc=stamp, checked=len(before), changed=changed,
         unexpected=unexpected, final_source_matches=source == captured, passed=passed))
    print(json.dumps(dict(passed=passed, checked=len(before), unexpected=unexpected,
                          final_source_matches=source == captured)))
    raise SystemExit(0 if passed else 1)
else:
    checks = []
    def check(name, passed, detail=None):
        checks.append(dict(name=name, passed=bool(passed), detail=detail))
    def read(name):
        return json.loads((OUT / name).read_text(encoding="utf-8"))
    before, final = read("source_before.json"), read(f"source_{args.label}.json")
    advertised = json.loads((ROOT / "reports/source_state_phase2_final.json").read_text(encoding="utf-8"))
    check("submitted_source_reproduced", before == advertised)
    check("final_source_matches", final == source_fingerprint())
    check("final_tests_use_final_source", read(f"tests_{args.label}.json")["source"] == final)
    baseline = read("tests_baseline.json")
    negative = read("tests_regressions_before.json")
    corrected = read(f"tests_{args.label}.json")
    check("baseline_tests", baseline["exit_code"] == 0 and "Ran 13 tests" in baseline["stderr"])
    check("negative_failure_preserved", negative["exit_code"] == 1 and "Ran 25 tests" in negative["stderr"]
          and "failures=15" in negative["stderr"])
    check("corrected_tests", corrected["exit_code"] == 0 and "Ran 39 tests" in corrected["stderr"])
    check("rerun_link", corrected["retry_of"] == "reports/reviews/evidence/phase2_20261018_1821/tests_regressions_before.json")
    original_map = {item["path"]: item["sha256"] for item in before["files"]}
    final_map = {item["path"]: item["sha256"] for item in final["files"]}
    delta = sorted(p for p in original_map.keys() | final_map.keys() if original_map.get(p) != final_map.get(p))
    expected = {"README.md", "docs/ARCHITECTURE.md", "docs/DATA_SCHEMAS.md", "docs/INVARIANTS.md",
                "docs/POLICIES.md", "docs/PHASE2_EXECUTION_CONTRACT.md", "src/cache_scaleout/contracts.py",
                "src/cache_scaleout/interfaces.py", "src/cache_scaleout/policies.py", "tests/test_phase2_contracts.py",
                "tests/test_phase2_review.py"}
    check("scoped_source_delta", set(delta) == expected, delta)
    original_paths = [p for p in expected if p in original_map]
    check("original_changed_files_preserved", all(
          hashlib.sha256((OUT / "original" / Path(p).name).read_bytes()).hexdigest() == original_map[p]
          for p in original_paths))
    check("historical_preservation", read(f"preservation_{args.label}.json")["passed"])
    markdown = [ROOT / p for p in expected if p.endswith(".md")]
    markdown += [ROOT / "reports/reviews/phase_02_independent_20261018_1821.md",
                 ROOT / "reports/phase_02.md", ROOT / "reports/STATUS.md", ROOT / "reports/ISSUE_INDEX.md"]
    missing, count = [], 0
    for path in markdown:
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            link = link.split("#", 1)[0].strip("<>")
            if not link or "://" in link or link.startswith("mailto:"):
                continue
            count += 1
            target = (path.parent / link).resolve()
            if target != OUT / f"audit_{args.label}.json" and not target.exists():
                missing.append(dict(file=str(path.relative_to(ROOT)), link=link))
    check("local_document_links", not missing, dict(checked=count, missing=missing))
    passed = all(c["passed"] for c in checks)
    save(f"audit_{args.label}.json", dict(utc=stamp, passed=passed, checks=checks,
         command=[sys.executable, "-B", str(Path(__file__).relative_to(ROOT)), *sys.argv[1:]],
         scope="Offline integrity/link/source checks only; semantic review is manual."))
    print(json.dumps(dict(passed=passed, checks=len(checks), failed=[c for c in checks if not c["passed"]])))
    raise SystemExit(0 if passed else 1)
