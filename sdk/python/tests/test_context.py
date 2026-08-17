#!/usr/bin/env python3
"""ContextStore unit tests (SPEC §9.2 profile). Run: python3 sdk/python/tests/test_context.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from aip import ContextStore, FakeClock  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def test_put_get_full():
    store = ContextStore(clock=FakeClock())
    store.put("ctx_1", {"total": 299.0, "customer": "c_001", "status": "pending"})
    data, err = store.get("ctx_1")
    check("put/get full returns all data", data == {"total": 299.0, "customer": "c_001", "status": "pending"} and err is None)


def test_fields_subset():
    store = ContextStore(clock=FakeClock())
    store.put("ctx_1", {"total": 299.0, "customer": "c_001", "status": "pending"})
    data, err = store.get("ctx_1", fields=["total", "customer"])
    check("get with fields returns only requested fields",
          data == {"total": 299.0, "customer": "c_001"} and err is None)
    check("missing fields are omitted", "status" not in (data or {}))


def test_not_found():
    store = ContextStore(clock=FakeClock())
    data, err = store.get("ctx_missing")
    check("missing ref -> context.not_found", data is None and err == "context.not_found")


def test_expired():
    store = ContextStore(clock=FakeClock(), ttl_ms=1000)
    store.put("ctx_1", {"total": 1.0})
    _, err = store.get("ctx_1")
    check("within TTL is readable", err is None)
    store.clock.advance(1001)
    data, err = store.get("ctx_1")
    check("after TTL -> context.expired", data is None and err == "context.expired")


def test_put_bumps_version():
    store = ContextStore(clock=FakeClock())
    store.put("ctx_1", {"total": 1.0})
    v1 = store.version("ctx_1")
    store.put("ctx_1", {"total": 2.0})
    v2 = store.version("ctx_1")
    check("version increments on update", v1 == 1 and v2 == 2)


def test_delete():
    store = ContextStore(clock=FakeClock())
    store.put("ctx_1", {"total": 1.0})
    store.delete("ctx_1")
    data, err = store.get("ctx_1")
    check("delete -> context.not_found", data is None and err == "context.not_found")


def main():
    print("ContextStore tests (SPEC §9.2)")
    test_put_get_full()
    test_fields_subset()
    test_not_found()
    test_expired()
    test_put_bumps_version()
    test_delete()
    print(f"\n{FAIL} failed, {PASS} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())