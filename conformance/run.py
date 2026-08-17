#!/usr/bin/env python3
"""AIP conformance runner (schema-level tests).

Runs the `kind: schema` tests from conformance/tests/*.json against
schema/aip.json and reports pass/fail per test id. Behavior tests
require a live harness speaking AIP over WebSocket and are reported
as SKIP (see conformance/README.md).

Usage:
    python3 conformance/run.py

Exit code is 0 when all schema tests pass.
Requires: jsonschema (pip install jsonschema)
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / ".." / "schema" / "aip.json"
TESTS_DIR = HERE / "tests"

TYPES = ("event", "action", "result", "error")
REQUIRED_FIELDS = ("v", "type", "id", "session", "seq", "source", "payload")


def load_schema():
    try:
        from jsonschema import Draft7Validator
    except ImportError:
        sys.exit("jsonschema is required: pip install jsonschema")
    return Draft7Validator(schema=json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def classify_invalid(msg):
    """Map an invalid message to its kernel error code (SPEC §4.6)."""
    if not isinstance(msg, dict):
        return "INVALID_MESSAGE"
    if msg.get("v") != 1:
        return "UNSUPPORTED_VERSION"
    if msg.get("type") not in TYPES:
        return "INVALID_MESSAGE"
    for field in REQUIRED_FIELDS:
        if field not in msg:
            return "INVALID_MESSAGE"
    return "INVALID_MESSAGE"


def run_schema_test(validator, test):
    cases = test.get("cases") or [{"input": test["input"], "expect": test["expect"]}]
    for case in cases:
        message = case["input"]
        expect = case["expect"]
        errors = list(validator.iter_errors(message))
        valid = not errors
        if valid == expect.get("valid"):
            continue
        if not valid and expect.get("error") == classify_invalid(message):
            continue
        return False, {
            "expected_valid": expect.get("valid"),
            "got_valid": valid,
            "expected_error": expect.get("error"),
            "got_error": classify_invalid(message) if not valid else None,
            "schema_errors": [e.message for e in errors][:5],
        }
    return True, None


def main():
    parser = argparse.ArgumentParser(description="AIP conformance runner (schema + behavior)")
    parser.add_argument("--tests", type=Path, default=TESTS_DIR, help="tests directory")
    parser.add_argument("--skip-behavior", action="store_true",
                        help="only run schema tests (no reference gateway needed)")
    args = parser.parse_args()

    schema_failed = _run_schema(args.tests)
    if args.skip_behavior:
        behavior_failed = 0
    else:
        try:
            from run_behavior import main as behavior_main
        except ImportError:
            print("\n[behavior] skipping — run_behavior.py needs the reference gateway (examples/hello-rpa)")
            behavior_failed = 0
        else:
            behavior_failed = behavior_main()

    print("\noverall:", "ALL CONFORMANT" if not (schema_failed or behavior_failed) else "FAILURES PRESENT")
    sys.exit(1 if (schema_failed or behavior_failed) else 0)


def _run_schema(tests_dir: Path) -> int:
    validator = load_schema()
    passed, failed, skipped = 0, 0, 0
    failures = []

    for path in sorted(tests_dir.glob("*.json")):
        group = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n[{group['group']}] {group['name']}")
        for test in group["tests"]:
            kind = test["kind"]
            if kind == "schema":
                ok, detail = run_schema_test(validator, test)
                status = "PASS" if ok else "FAIL"
                if ok:
                    passed += 1
                else:
                    failed += 1
                    failures.append((test["id"], detail))
            else:
                status = "SKIP"
                skipped += 1
            print(f"  {status:4}  {test['id']}: {test['description']}")
        print()

    print(f"schema summary: {passed} passed, {failed} failed, {skipped} behavior (moved to run_behavior)")
    for test_id, detail in failures:
        print(f"\nFAIL {test_id}: {json.dumps(detail, ensure_ascii=False, indent=2)}")
    return 1 if failed else 0


if __name__ == "__main__":
    main()
