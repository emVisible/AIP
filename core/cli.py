"""CLI：submit / resolve / queue / demo（stdlib only）。"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.decide import engine_name  # noqa: E402
from core.store import ReviewStore  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _store() -> ReviewStore:
    return ReviewStore(DATA_DIR)


def cmd_submit(a) -> int:
    rec = _store().submit(a.kind, a.title, a.body, {})
    print(json.dumps({
        "id": rec.item.id, "state": rec.state,
        "action": rec.decision.action, "confidence": rec.decision.confidence,
        "engine": rec.decision.engine, "reasons": rec.decision.reasons,
    }, ensure_ascii=False, indent=1))
    return 0


def cmd_resolve(a) -> int:
    try:
        rec = _store().resolve(a.id, a.outcome, a.actor)
    except (KeyError, ValueError) as e:
        print(f"ERROR: {e}")
        return 1
    print(json.dumps({"id": a.id, "state": rec["state"]}, ensure_ascii=False))
    return 0


def cmd_queue(a) -> int:
    rows = _store().queue(a.state)
    for r in rows:
        it = r["item"]
        print(f'{it["id"]} [{r["state"]}] {it["kind"]}: {it["title"][:40]} '
              f'conf={r["decision"]["confidence"]:.2f} via={r.get("via")}')
    print(f"total={len(rows)} engine={engine_name()}")
    return 0


def cmd_context(a) -> int:
    import json as _json
    try:
        out = _store().context_get(a.ref, a.fields.split(","))
    except (ValueError, OSError) as e:
        print(f"ERROR: {e}")
        return 1
    print(_json.dumps(out, ensure_ascii=False, indent=1)[:2000])
    return 0


def cmd_demo(_a) -> int:    s = _store()
    samples = [
        ("article", "小区停水通知", "明早 8 点到 12 点停水维护，请提前储水。", {}),
        ("comment", "限时返利", "点击链接免费领取 888 元，刷单日结加微信。", {}),
        ("article", "账号申诉", "我的密码是 123456，请帮我找回账号。", {}),
    ]
    for kind, title, body, meta in samples:
        rec = s.submit(kind, title, body, meta)
        print(f'{rec.item.id} [{rec.state}] {rec.decision.action} '
              f'conf={rec.decision.confidence:.2f} {rec.decision.reasons}')
    print(f"engine={engine_name()}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="clearance", description="Clearance（放行）通用后台审核网关")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("submit")
    q.add_argument("--kind", default="other")
    q.add_argument("--title", default="")
    q.add_argument("--body", default="")
    q.set_defaults(fn=cmd_submit)

    r = sub.add_parser("resolve")
    r.add_argument("--id", required=True)
    r.add_argument("--outcome", required=True, choices=["approve", "reject"])
    r.add_argument("--actor", default="admin")
    r.set_defaults(fn=cmd_resolve)

    w = sub.add_parser("queue")
    w.add_argument("--state", default="", choices=["", "pending", "approved", "rejected"])
    w.set_defaults(fn=cmd_queue)

    d = sub.add_parser("demo")
    d.set_defaults(fn=cmd_demo)

    c = sub.add_parser("context-get")
    c.add_argument("--ref", required=True)
    c.add_argument("--fields", default="body")
    c.set_defaults(fn=cmd_context)

    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
