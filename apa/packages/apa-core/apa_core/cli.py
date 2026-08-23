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
                          tenant=args.tenant, token=args.token)
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


def _cmd_serve(args) -> int:
    import uvicorn

    from .api import create_app
    from .launcher import default_registries
    from .registry import load_registries
    from .serve import ServeApp

    reg_paths = args.registries or [str(p) for p in default_registries()]
    reg = load_registries(*reg_paths)

    serve_app = ServeApp(
        journals=args.journals,
        port=args.port,
        processes_dir=args.processes_dir or None,
        registry=reg,
        runs_dir=args.runs_dir or None,
        mock_erp=not args.no_mock_erp,
        erp_base_url=args.erp_url or "",
        token=args.token or None,
        tenant=args.tenant or None,
        frontend_dist=args.frontend_dist or None,
    )
    if args.jobs:
        n = serve_app.load_jobs(args.jobs)
        print(f"==> 已加载调度任务 {n} 个")

    fast_app = create_app(
        journals=args.journals,
        processes_dir=args.processes_dir or None,
        registry=reg,
        frontend_dist=args.frontend_dist or None,
        token=args.token or None,
        ai_status={"mode": "rules_only", "model": "deepseek-chat"},
        dispatch_event=serve_app.dispatch_external_event,
        resolve_task=None,
    )

    print(f"==> APA 常驻服务: http://127.0.0.1:{args.port}   （Ctrl-C 退出）")
    uvicorn.run(fast_app, host="127.0.0.1", port=args.port,
                log_level="warning")
    return 0


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



def _cmd_record(args) -> int:
    """交互式浏览器录制 → process.yaml。"""
    import yaml as _y
    from pathlib import Path as _P
    from .recorder import RecorderSession, events_to_process

    session = RecorderSession(args.url)
    print(f"▶ 录制中：{args.url}")
    print("  在打开的浏览器窗口中操作；关闭窗口即结束录制。")
    try:
        session.start()
        session.wait_until_closed()
    finally:
        events = session.snapshot_events()
        session.stop()

    proc = events_to_process(
        events,
        process_id=args.process_id,
        trigger_name=args.trigger,
    )
    yaml_out = _y.safe_dump(proc, allow_unicode=True, sort_keys=False)
    if args.out:
        out = _P(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml_out, encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(yaml_out)
    n_steps = len(proc["process"]["steps"])
    print(f"✅ 录制完成：{n_steps} 个步骤")
    return 0


def _cmd_flow_compile(args) -> int:
    from .flow import parse_flow
    from pathlib import Path as _P
    import yaml as _y

    text = _P(args.input).read_text(encoding="utf-8")
    proc = parse_flow(text)
    yaml_out = _y.safe_dump({"process": proc}, allow_unicode=True,
                            sort_keys=False)
    if args.out:
        _P(args.out).write_text(yaml_out, encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(yaml_out)
    return 0


def _cmd_flow_decompile(args) -> int:
    from .flow import decompile_flow
    from pathlib import Path as _P
    import yaml as _y

    data = _y.safe_load(_P(args.input).read_text(encoding="utf-8"))
    text = decompile_flow(data)
    if args.out:
        _P(args.out).write_text(text, encoding="utf-8")
        print(f"→ {args.out}")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apa",
        description="APA — Agentic Process Automation 控制台")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_studio = sub.add_parser("studio", help="启动 APA-Studio 监控面板")
    p_studio.add_argument("--journals", nargs="+", required=True)
    p_studio.add_argument("--port", type=int, default=8686)
    p_studio.add_argument("--tenant", default=None)
    p_studio.add_argument("--token", default=None,
                          help="启用 Bearer 认证（客户端须携带同值）")
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

    p_serve = sub.add_parser("serve", help="常驻服务：面板+调度器+本地执行")
    p_serve.add_argument("--journals", nargs="+", required=True)
    p_serve.add_argument("--port", type=int, default=8686)
    p_serve.add_argument("--jobs", default=None, help="scheduler.yaml 任务文件")
    p_serve.add_argument("--processes-dir", default="data/processes")
    p_serve.add_argument("--frontend-dist", default=None,
                         help="React SPA 构建产物目录")
    p_serve.add_argument("--runs-dir", default=None)
    p_serve.add_argument("--registries", nargs="+", default=None)
    p_serve.add_argument("--no-mock-erp", action="store_true",
                         help="禁用内置沙盒 ERP（生产接真实端点时用）")
    p_serve.add_argument("--erp-url", default="")
    p_serve.add_argument("--token", default=None)
    p_serve.add_argument("--tenant", default=None)
    p_serve.set_defaults(fn=_cmd_serve)

    p_flow_c = sub.add_parser("flow-compile", help=".flow → process.yaml")
    p_flow_c.add_argument("input", help=".flow 文件")
    p_flow_c.add_argument("--out", default=None, help="输出 YAML 文件")
    p_flow_c.set_defaults(fn=_cmd_flow_compile)

    p_flow_d = sub.add_parser("flow-decompile", help="process.yaml → .flow")
    p_flow_d.add_argument("input", help="process.yaml 文件")
    p_flow_d.add_argument("--out", default=None)
    p_flow_d.set_defaults(fn=_cmd_flow_decompile)

    p_rec = sub.add_parser("record", help="浏览器录制：操作→自动生成 process.yaml")
    p_rec.add_argument("url", help="起始 URL")
    p_rec.add_argument("--process-id", default="recorded_flow")
    p_rec.add_argument("--trigger", default=None,
                       help="事件触发名（默认 manual）")
    p_rec.add_argument("--out", default=None, help="输出 YAML 文件")
    p_rec.set_defaults(fn=_cmd_record)

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