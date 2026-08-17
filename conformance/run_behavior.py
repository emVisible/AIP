#!/usr/bin/env python3
"""AIP behavior conformance runner.

Replays the `kind: behavior` tests from conformance/tests/*.json through
the reference Gateway (examples/hello-rpa/gateway.py) via
conformance/harness.py.

Usage:
    python3 conformance/run_behavior.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from harness import run_behavior_test  # noqa: E402


def main() -> int:
    passed = failed = skipped = 0
    failures = []

    for path in sorted((HERE / "tests").glob("*.json")):
        group = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n[{group['group']}] {group['name']}")
        for test in group["tests"]:
            if test["kind"] != "behavior":
                continue
            status, detail = run_behavior_test(test)
            if status == "PASS":
                passed += 1
                print(f"  PASS  {test['id']}: {test['description']}")
            elif status == "SKIP":
                skipped += 1
                print(f"  SKIP  {test['id']}: {test['description']}  ({detail})")
            else:
                failed += 1
                failures.append((test["id"], detail))
                print(f"  FAIL  {test['id']}: {test['description']}\n        {detail}")
        print()

    print(f"summary: {passed} passed, {failed} failed, {skipped} skipped")
    if failures:
        print("\nfailures:")
        for test_id, detail in failures:
            print(f"  {test_id}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())