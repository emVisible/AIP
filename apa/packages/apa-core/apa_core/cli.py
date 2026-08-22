"""apa-core: 统一 `apa` 命令行入口。

    apa studio     --journals 'data/*.jsonl' [--port 8686] [--tenant ...]
    apa analytics  --journals 'data/*.jsonl' [--tenant ...]
    apa tasks      list --journal data/s.jsonl
    apa latency    [--n 200]

安装 console script 后（pip install -e ./apa/packages/apa-core）：
    apa studio --journals 'data/*.jsonl'
"""
from __future__ import annotations

import argparse
import sys


def _cmd_studio(args) -> int:
    from .studio import StudioServer
    server = StudioServer(args.journals, port=args.port,
                          tenant=args.tenant)
    print(f"APA-Studio → http://127.0.0.1:{args.port}")
    server.serve_forever()
    return 0


def _cmd_analytics(args) -> int:
    from .analytics import report, summarize
    data = summarize(args.journals, tenant=args.tenant)
    print(report(data))
    if args.json:
        import json
        from pathlib import Path
        Path(args.json).write_text(json.dumps(data), encoding="utf-8")
    return 0


def _cmd_tasks(args) -> int:
    from .human_loop import main as human_main
    sys.argv = [sys.argv[0], args.action, "--journal", args.journal] + \
        ([args.task_id] if args.task_id else []) + \
        (["--outcome", args.outcome] if getattr(args, "outcome", None) else [])
    return human_main()


def _cmd_latency(args) -> int:
    bench_dir = Path(__file__).resolve().parents[2] / "benchmarks"
    sys.path.insert(0, str(bench_dir))
    from benchmarks.latency import run as latency_run  # type: ignore

    data = latency_run(n_actions=args.n)
    print(json_dumps(data))
    return 0


def json_dumps(data: dict) -> str:
    import json
    return json.dumps(data, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apa",
        description="APA — Agentic Process Automation 控制台")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_studio = sub.add_parser("studio", help="启动 APA-Studio 监控面板")
    p_studio.add_argument("--journals", nargs="+", required=True)
    p_studio.add_argument("--port", type=int, default=8686)
    p_studio.add_argument("--tenant", default=None)
    p_studio.set_defaults(fn=_cmd_studio)

    p_ana = sub.add_parser("analytics", help="运行指标报告")
    p_ana.add_argument("--journals", nargs="+", required=True)
    p_ana.add_argument("--tenant", default=None)
    p_ana.add_argument("--json", default=None)
    p_ana.set_defaults(fn=_cmd_analytics)

    p_tasks = sub.add_parser("tasks", help="人工任务管理")
    p_tasks.add_argument("action", choices=["list"])
    p_tasks.add_argument("--journal", required=True)
    p_tasks.add_argument("task_id", nargs="?")
    p_tasks.add_argument("--outcome", default=None)
    p_tasks.set_defaults(fn=_cmd_tasks)

    p_lat = sub.add_parser("latency", help="动作往返延迟基准")
    p_lat.add_argument("--n", type=int, default=200)
    p_lat.set_defaults(fn=_cmd_latency)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.fn(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())