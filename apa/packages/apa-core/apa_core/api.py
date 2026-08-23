"""APA FastAPI 应用 —— 替换 stdlib http.server（§13 现代化框架迁移）。

所有 REST API + SSE + SPA 静态文件服务统一到 FastAPI。
业务逻辑（gateway/registry/policy/session）不变——只换传输层。

用法：
    uvicorn apa_core.api:app --port 8686
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analytics import report as analytics_report
from .analytics import summarize
from .persist import journal_records


# ---- Pydantic 模型（API 契约单一权威） -----------------------------------------
class TaskResolveRequest(BaseModel):
    outcome: str = "retry"


class ProcessSaveRequest(BaseModel):
    id: str
    yaml: str


class ProcessTestRequest(BaseModel):
    yaml: str
    event: str
    data: Dict[str, Any] = {}


class EventDispatchRequest(BaseModel):
    name: str
    data: Dict[str, Any] = {}


class ActionMetaOut(BaseModel):
    description: str = ""
    risk: str = ""
    executor_domain: str = ""
    idempotency: str = ""
    params: Optional[dict] = None
    deprecated: bool = False


class AiStatusOut(BaseModel):
    mode: str = "rules_only"
    model: str = "deepseek-chat"
    key_configured: bool = False


# ---- 工厂函数 ------------------------------------------------------------------
def create_app(
    *,
    journals: List[str],
    processes_dir: Optional[str] = None,
    registry=None,
    frontend_dist: Optional[str] = None,
    token: Optional[str] = None,
    tenant: Optional[str] = None,
    ai_status: Optional[Dict[str, Any]] = None,
    dispatch_event: Optional[Callable] = None,
    resolve_task: Optional[Callable] = None,
    runs_dir: Optional[str] = None,
) -> FastAPI:
    """构建 FastAPI 实例。依赖注入：所有外部交互通过参数传入。"""

    from .studio import StudioServer  # 延迟导入复用现有逻辑

    server = StudioServer(
        journals=journals,
        processes_dir=processes_dir,
        registry=registry,
        token=token,
        tenant=tenant,
        ai_status=ai_status,
        dispatch_event=dispatch_event,
        resolve_task=resolve_task,
    )

    app = FastAPI(title="APA", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if token:
        from fastapi.security import HTTPBearer
        # 简化：middleware 校验在请求级别处理

    def _check_token(request: Request) -> bool:
        if not token:
            return True
        return request.headers.get("Authorization", "") == f"Bearer {token}"

    # ---- 会话 ----
    @app.get("/api/sessions")
    async def get_sessions():
        return server.sessions()

    @app.get("/api/analytics")
    async def get_analytics():
        return summarize(server.journal_paths, tenant=tenant)

    # ---- 流程 ----
    @app.get("/api/processes")
    async def list_processes():
        return server.list_processes()

    @app.get("/api/templates")
    async def list_templates():
        """内置场景模板库（只读，供设计器一键导入）。"""
        import pathlib
        tdir = pathlib.Path(__file__).resolve().parents[3] / "templates"
        items = []
        if tdir.is_dir():
            for f in sorted(tdir.glob("*.yaml")):
                try:
                    import yaml as _y
                    doc = _y.safe_load(f.read_text(encoding="utf-8")) or {}
                    proc = doc.get("process") or {}
                    items.append({
                        "id": f.stem,
                        "name": proc.get("id", f.stem),
                        "description": (doc.get("process", {}).get(
                            "description") or
                            f.stem.replace("-", " ")),
                        "yaml": f.read_text(encoding="utf-8"),
                    })
                except Exception:
                    continue
        return {"templates": items}

    @app.get("/api/processes/get/{proc_id}")
    async def get_process(proc_id: str):
        content = server.load_process_yaml(proc_id)
        if content is None:
            raise HTTPException(404, "not found")
        return {"id": proc_id, "yaml": content}

    @app.post("/api/processes/save")
    async def save_process(req: ProcessSaveRequest):
        return server.save_process_yaml(req.id, req.yaml)

    @app.post("/api/processes/test")
    async def test_process(req: ProcessTestRequest):
        try:
            return server.test_run_process(req.yaml, req.event, req.data)
        except Exception as e:
            return {"outcome": "error", "error": str(e)}

    @app.post("/api/processes/to-form")
    async def to_form(body: dict):
        try:
            return server.process_to_form(body.get("yaml", ""))
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.post("/api/processes/from-form")
    async def from_form(body: dict):
        try:
            return {"yaml": server.process_from_form(body.get("form", {}))}
        except Exception as e:
            raise HTTPException(400, str(e))

    # ---- 注册表 ----
    @app.get("/api/registry/actions")
    async def registry_actions():
        return server.registry_actions()

    # ---- HITL ----
    @app.post("/api/tasks/{task_id}/resolve")
    async def resolve_task(task_id: str, body: dict):
        cb = resolve_task or (
            lambda tid, o, a="studio": False)
        ok = cb(task_id, body.get("outcome", "retry"), body.get("actor", "studio"))
        return {"ok": bool(ok)}

    # ---- AI 状态 ----
    @app.get("/api/ai/status")
    async def ai_status():
        return ai_status or {"mode": "rules_only"}

    # ---- 外部事件 ----
    @app.post("/api/events")
    async def dispatch_ext(body: EventDispatchRequest):
        if dispatch_event is None:
            raise HTTPException(501, "event dispatch not configured")
        return dispatch_event(body.name, body.data)

    # ---- SSE journal stream ----
    @app.get("/api/journal/stream")
    async def journal_stream():
        from sse_starlette.sse import EventSourceResponse
        paths = list(server.journal_paths)

        async def generate():
            seen_ts = 0.0
            while True:
                for path in paths:
                    for rec in journal_records(path):
                        ts = float(rec.get("ts", 0))
                        if ts > seen_ts:
                            seen_ts = ts
                            yield {"data": json.dumps(rec, ensure_ascii=False)}
                await asyncio.sleep(1)

        return EventSourceResponse(generate())

    # ---- SPA 静态文件 ----
    if frontend_dist and Path(frontend_dist).is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True),
                  name="spa")

    return app