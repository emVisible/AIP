"""apa-core: Human-in-the-Loop 任务管理（设计文档 §4.3）。

human.task.create action 由 Gateway 拦截 → Session SUSPENDED；
人工完成后经 APAGateway.resolve_human_task 注入完成事件恢复。

CLI：
    python -m apa_core.human_loop list   --journal data/s.jsonl
    python -m apa_core.human_loop resolve --journal data/s.jsonl ht_xxx --outcome retry
"""
from __future__ import annotations

from typing import Dict, List, Optional


class HumanTaskManager:
    def __init__(self) -> None:
        self.tasks: Dict[str, dict] = {}

    def create(self, *, action_id: str, task_type: str, assignee_role: str,
               context_ref: str = "", priority: str = "normal") -> str:
        task_id = f"ht_{action_id}"
        self.tasks[task_id] = {
            "task_id": task_id,
            "task_type": task_type,
            "assignee_role": assignee_role,
            "context_ref": context_ref,
            "priority": priority,
            "status": "open",
            "outcome": None,
            "actor": None,
        }
        return task_id

    def resolve(self, task_id: str, *, outcome: str, actor: str) -> bool:
        task = self.tasks.get(task_id)
        if task is None or task["status"] != "open":
            return False
        task["status"] = "resolved"
        task["outcome"] = outcome
        task["actor"] = actor
        return True

    def get(self, task_id: str) -> Optional[dict]:
        return self.tasks.get(task_id)

    def open_tasks(self) -> List[dict]:
        return [t for t in self.tasks.values() if t["status"] == "open"]

    def restore(self, record: dict) -> None:
        """持久化恢复。"""
        self.tasks[record["task_id"]] = dict(record)


def main() -> int:  # pragma: no cover
    import argparse
    from .persist import load_journal

    parser = argparse.ArgumentParser(prog="human_loop",
                                     description="APA 人工任务 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="列出未完成任务")
    p_list.add_argument("--journal", required=True)
    p_res = sub.add_parser("resolve", help="解析任务（注入完成事件需运行中的网关）")
    p_res.add_argument("task_id")
    p_res.add_argument("--journal", required=True)
    p_res.add_argument("--outcome", default="retry")
    args = parser.parse_args()

    records = load_journal(args.journal)
    open_tasks = [r for r in records if r.get("kind") == "task" and r.get("status") == "open"]
    resolved_ids = {r["task_id"] for r in records if r.get("kind") == "task" and r.get("status") == "resolved"}
    open_tasks = [t for t in open_tasks if t["task_id"] not in resolved_ids]
    if args.cmd == "list":
        for t in open_tasks:
            print(f"{t['task_id']}  type={t.get('task_type')}  ctx={t.get('context_ref')}")
        print(f"共 {len(open_tasks)} 个待处理任务")
        return 0
    # resolve：仅提示（真正的解析需要连到运行中的 Gateway；嵌入式模式用
    # gateway.resolve_human_task，WS 模式经控制端口）
    match = [t for t in open_tasks if t["task_id"] == args.task_id]
    if not match:
        print(f"任务 {args.task_id} 不存在或已处理")
        return 1
    print(f"任务 {args.task_id} 存在。请在运行中的网关上执行 resolve_human_task("
          f"\"{args.task_id}\", outcome=\"{args.outcome}\")")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())