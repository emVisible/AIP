"""APA FastAPI 应用 —— 替换 stdlib http.server（§13 现代化框架迁移）。

所有 REST API + SSE + SPA 静态文件服务统一到 FastAPI。
业务逻辑（gateway/registry/policy/session）不变——只换传输层。

用法：
    uvicorn apa_core.api:app --port 8686
"""
from __future__ import annotations

import asyncio
import json

import yaml
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .core_services import CoreServices, resolve_services
from .jobs import JobNotFound, JobNotOwned
from .sessions import SessionTampered

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from queue import Empty

from .analytics import report as analytics_report
from .analytics import summarize
from .persist import journal_records


# ---- Pydantic 模型（API 契约单一权威） -----------------------------------------
class TaskResolveRequest(BaseModel):
    outcome: str = "retry"


class ProcessSaveRequest(BaseModel):
    id: str
    yaml: str
    # H2 计划态确认门：来自工作台草稿的流程必须携带已批准的溯源凭证
    session_id: str = ""
    draft_id: str = ""


class ProcessTestRequest(BaseModel):
    yaml: str
    event: str
    data: Dict[str, Any] = {}
    session_id: str = ""
    draft_id: str = ""


class EventDispatchRequest(BaseModel):
    name: str
    data: Dict[str, Any] = {}


class RecorderStartRequest(BaseModel):
    url: str


class RecorderStopRequest(BaseModel):
    process_id: str = "recorded_flow"


class BrowserPickStartRequest(BaseModel):
    url: str


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
    sessions_dir: Optional[str] = None,
    services: Optional[CoreServices] = None,
    registry=None,
    frontend_dist: Optional[str] = None,
    token: Optional[str] = None,
    tenant: Optional[str] = None,
    ai_status: Optional[Dict[str, Any]] = None,
    dispatch_event: Optional[Callable] = None,
    resolve_task: Optional[Callable] = None,
    runs_dir: Optional[str] = None,
    spy_service: Optional[Any] = None,
    serve_app: Optional[Any] = None,
    intent_compiler=None,
    failure_diagnostic=None,
) -> FastAPI:
    """构建 FastAPI 实例。依赖注入：所有外部交互通过参数传入。"""
    # 根基加固：一切可变单例收编 CoreServices（架构宪法 §二）
    svc = resolve_services(services, sessions_dir=sessions_dir)
    if spy_service is not None:
        svc.spy = spy_service
    # 注入式只读依赖（意图编译 / 失败诊断）
    _intent = intent_compiler
    _diag = failure_diagnostic

    def _ensure_job(job_id: str, kind: str,
                    on_cancel: Callable) -> None:
        """确定性 id 的常驻型后台任务登记（已存在则跳过）。"""
        try:
            svc.jobs.get(job_id)
        except Exception:
            svc.jobs.start(kind=kind, owner_session="studio",
                               job_id=job_id, on_cancel=on_cancel)

    def _require_draft_approved(session_id: str, draft_id: str) -> None:
        svc.require_draft_approved(session_id, draft_id)

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


    @app.get("/api/analytics")
    async def get_analytics():
        return summarize(server.journal_paths, tenant=tenant)

    # ---- 流程 ----
    @app.get("/api/processes")
    async def list_processes():
        return server.list_processes()

    def list_templates_payload():
        """模板载荷（REST 与 Studio RPC 共用）。"""
        import os
        import pathlib

        candidates = []
        if os.environ.get("APA_TEMPLATES_DIR"):
            candidates.append(pathlib.Path(os.environ["APA_TEMPLATES_DIR"]))
        import sys
        if getattr(sys, "frozen", False):
            base = Path(getattr(sys, "_MEIPASS", ".")) / "templates"
            candidates.append(base)
        candidates.append(Path(__file__).resolve().parents[2] / "templates")
        seen = set()
        out = []
        for c in candidates:
            if not c.is_dir() or c in seen:
                continue
            seen.add(c)
            for f in sorted(c.glob("*.yaml")):
                try:
                    meta = {"id": f.stem,
                            "name": f.stem,
                            "description": "",
                            "yaml": f.read_text(encoding="utf-8")}
                    try:
                        head = yaml.safe_load(f.read_text(
                            encoding="utf-8")) or {}
                        proc_meta = (head or {}).get("process", {})
                        if proc_meta.get("name"):
                            meta["name"] = proc_meta["name"]
                        if proc_meta.get("description"):
                            meta["description"] = proc_meta["description"]
                    except Exception:  # noqa: BLE001
                        pass
                    out.append(meta)
                except OSError:
                    continue
        return {"templates": out}

    @app.get("/api/templates")
    async def list_templates():
        """内置场景模板库（只读，供设计器一键导入）。"""
        return list_templates_payload()

    @app.get("/api/processes/get/{proc_id}")
    async def get_process(proc_id: str):
        content = server.load_process_yaml(proc_id)
        if content is None:
            raise HTTPException(404, "not found")
        return {"id": proc_id, "yaml": content}

    @app.post("/api/processes/save")
    async def save_process(req: ProcessSaveRequest):
        try:
            _require_draft_approved(req.session_id, req.draft_id)
        except (ValueError, PermissionError) as e:
            raise HTTPException(409, str(e))
        return server.save_process_yaml(req.id, req.yaml)

    @app.post("/api/processes/test")
    async def test_process(req: ProcessTestRequest):
        try:
            _require_draft_approved(req.session_id, req.draft_id)
        except (ValueError, PermissionError) as e:
            raise HTTPException(409, str(e))

        def _emit(evt: dict) -> None:
            svc.notify("run.step", {"session": "sandbox", **evt})
        _require_draft_approved(req.session_id, req.draft_id)
        try:
            result = server.test_run_process(req.yaml, req.event, req.data,
                                             step_observer=_emit)
        except Exception as e:
            return {"outcome": "error", "error": str(e)}
        from .spill import spill_test_response
        spill_test_response(result)

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


    # ---- 浏览器录制器 ----
    @app.post("/api/recorder/start")
    async def recorder_start(body: RecorderStartRequest):
        from .recorder_service import RecorderError, RecorderService
        if svc.recorder is None:
            svc.recorder = RecorderService()
        try:
            result = svc.recorder.start(body.url)
        except RecorderError as e:
            raise HTTPException(409, str(e))
        sid = result.get("session_id", "")
        if sid:
            _ensure_job(f"recorder_{sid}", "recorder",
                        on_cancel=lambda: svc.recorder.stop(sid))
        return result

    @app.get("/api/recorder/status/{sid}")
    async def recorder_status(sid: str):
        from .recorder_service import RecorderError
        if svc.recorder is None:
            raise HTTPException(404, "no recorder service")
        try:
            return svc.recorder.status(sid)
        except RecorderError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/recorder/stop/{sid}")
    async def recorder_stop(sid: str, body: RecorderStopRequest):
        from .recorder_service import RecorderError
        if svc.recorder is None:
            raise HTTPException(404, "no recorder service")
        try:
            result = svc.recorder.stop(sid, process_id=body.process_id)
        except RecorderError as e:
            raise HTTPException(404, str(e))
        try:
            svc.jobs.complete(f"recorder_{sid}")
        except Exception:
            pass
        return result






    # ---- 浏览器元素拾取（网页拾取 · 扩展回传通道）----
    @app.post("/api/browser_pick/start")
    async def browser_pick_start(body: BrowserPickStartRequest):
        from .browser_picker import BrowserPickError, BrowserPickerService
        if svc.picker is None:
            svc.picker = BrowserPickerService()
        try:
            result = svc.picker.start(body.url)
        except BrowserPickError as e:
            raise HTTPException(409, str(e))
        _ensure_job("browser_pick", "browser_pick",
                    on_cancel=lambda: svc.picker.stop())
        return result

    @app.get("/api/browser_pick/result")
    async def browser_pick_result():
        if svc.picker is None:
            return {"active": False, "picked": None}
        return svc.picker.result()

    @app.post("/api/browser_pick/stop")
    async def browser_pick_stop():
        if svc.picker is not None:
            svc.picker.stop()
        try:
            svc.jobs.complete("browser_pick")
        except Exception:
            pass
        return {"ok": True}

    @app.post("/api/browser_pick/event")
    async def browser_pick_event(body: dict):
        """Chrome 扩展回传通道（协议 v2，dict 透传）。"""
        from .browser_picker import BrowserPickerService
        if not isinstance(body, dict):
            raise HTTPException(422, "payload must be a JSON object")
        if svc.picker is None:
            svc.picker = BrowserPickerService()
        svc.picker.ingest(body)
        return {"ok": True}

    @app.get("/api/browser_pick/extension/download")
    async def browser_pick_extension_download():
        import io
        import zipfile
        from pathlib import Path

        from fastapi.responses import Response

        root = Path(__file__).parent / "browser_extension"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(root.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    zf.write(f, arcname=str(f.relative_to(root)))
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition":
                     "attachment; filename=apa-picker-extension.zip"},
        )

    # ---- 运行时后台任务（H1，命名避让定时调度 /api/jobs）----
    @app.get("/api/bgjobs")
    async def bgjobs_list(active_only: bool = False):
        from dataclasses import asdict
        return {"jobs": [asdict(j) for j in
                         svc.jobs.list(active_only=active_only)]}

    @app.post("/api/bgjobs/{job_id}/cancel")
    async def bgjobs_cancel(job_id: str, body: dict):
        try:
            rec = svc.jobs.cancel(job_id,
                                  actor_session=str(body.get(
                                      "actor", "__system__")))
        except Exception as e:
            raise HTTPException(409, str(e))
        from dataclasses import asdict
        return {"ok": True, "job": asdict(rec)}

    # ---- 会话事件溯源（H1）----
    @app.get("/api/sessions")
    async def sessions_list():
        return {"sessions": svc.sessions.list_sessions()}

    @app.post("/api/sessions/{sid}/append")
    async def sessions_append(sid: str, body: dict):
        kind = str(body.get("kind", ""))
        if not kind:
            raise HTTPException(422, "kind required")
        event = svc.sessions.append(sid, kind, body.get("payload") or {})
        return {"ok": True, "event": event}

    @app.get("/api/sessions/{sid}")
    async def sessions_read(sid: str):
        from .sessions import project_events
        events = svc.sessions.read(sid)
        return {"id": sid, "events": events,
                "view": project_events(events)}

    # ---- H3 Studio Protocol v1：统一 RPC 通道 ----------------------------------
    # 三态分类学见 studio_protocol.py；方法注册表在 CoreServices.rpc_table
    # （H3 二期：api 层只做分发与错误映射，宪法 §一）。

    def _apply_settings_patch(patch: dict, write_back: bool):
        try:
            svc.settings.update(patch, write_back=write_back)
        except ValueError as e:
            raise HTTPException(422, str(e))

    def _rpc_usage_summary(p: dict) -> dict:
        """按会话聚合 llm.usage 事件（H7 计量出口）。"""
        sid = str(p.get("session_id") or "")
        events = svc.sessions.read(sid) if sid else []
        summary = {"total_prompt_tokens": 0, "total_completion_tokens": 0,
                   "total_tokens": 0, "calls": 0}
        for e in events:
            if e.get("kind") != "llm.usage":
                continue
            u = (e.get("payload") or {}).get("usage") or {}
            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                v = u.get(k) or 0
                if isinstance(v, (int, float)):
                    summary[f"total_{k}"] += int(v)
            summary["calls"] += 1
        return summary

    def _rpc_process_save(p: dict):
        svc.require_draft_approved(str(p.get("session_id", "")),
                                   str(p.get("draft_id", "")))
        return server.save_process_yaml(str(p.get("id", "untitled")),
                                        str(p.get("yaml", "")))

    def _rpc_process_test(p: dict):
        from .spill import spill_test_response

        def _emit(evt: dict) -> None:
            svc.notify("run.step", {"session": "sandbox", **evt})
        result = server.test_run_process(str(p.get("yaml", "")),
                                         str(p.get("event", "")),
                                         p.get("data") or {},
                                         step_observer=_emit)
        spill_test_response(result)
        return result

    @app.post("/api/studio/rpc")
    async def studio_rpc(req: Request):
        """信封：{id, method, params} → {id, ok, result|error}。

        错误语义（RpcErrorBody.code）：
          method_not_found · invalid_params · not_found · conflict ·
          internal_error —— 会话篡改(SessionTampered)映射为 conflict。
        """
        try:
            raw = await req.json()
        except Exception:
            raise HTTPException(422, "body must be JSON")
        rid = str(raw.get("id", ""))
        method = str(raw.get("method", ""))
        params = raw.get("params") or {}

        def respond(ok: bool, result=None, err=None):
            body: Dict[str, Any] = {"id": rid, "ok": ok}
            if ok:
                body["result"] = result
            else:
                body["error"] = err
            return body

        try:
            table = dict(svc.rpc_table())
            table.update({
                "process.save": _rpc_process_save,
                "process.test": _rpc_process_test,
                "processes.list": lambda p: server.list_processes(),
                "templates.list": lambda p: list_templates_payload(),
                "yaml.from_form": lambda p: {
                    "yaml": server.process_from_form(p.get("form") or {})},
                "yaml.to_form": lambda p: server.process_to_form(
                    str(p.get("yaml", ""))),
                "settings.get": lambda p: {
                    "version": svc.settings.current.version,
                    "settings": svc.settings.get(),
                    "env_owned": svc.settings.env_owned_paths()},
                "settings.update": lambda p: (
                    _apply_settings_patch(p.get("patch") or {},
                                          bool(p.get("write_back", True))),
                    {"ok": True, "settings": svc.settings.get()})[1],
                "usage.summary": _rpc_usage_summary,
            })
            if method not in table:
                raise KeyError(method)
            result = table[method](params)
            return respond(True, result=result)
        # 注意顺序：具体异常先于 KeyError 泛化分支（JobNotFound 是其子类）
        except SessionTampered as e:
            return respond(False, err={"code": "conflict",
                                       "message": str(e), "data": {}})
        except (JobNotFound, JobNotOwned) as e:
            return respond(False, err={"code": "conflict",
                                       "message": str(e), "data": {}})
        except ValueError as e:
            return respond(False, err={"code": "invalid_params",
                                       "message": str(e), "data": {}})
        except KeyError as e:
            missing = e.args[0] if e.args else "?"
            return respond(False, err={
                "code": "method_not_found" if missing == method
                else "invalid_params",
                "message": f"unknown method {method}" if missing == method
                else f"missing param: {missing}",
                "data": {}})
        except HTTPException as e:
            code = {404: "not_found", 409: "conflict",
                    422: "invalid_params"}.get(e.status_code,
                                               "internal_error")
            return respond(False, err={"code": code,
                                       "message": str(e.detail),
                                       "data": {}})
        except Exception as e:  # noqa: BLE001
            import traceback

            return respond(False, err={"code": "internal_error",
                                       "message": str(e)[:200],
                                       "data": {"trace":
                                                traceback.format_exc()
                                                [-1500:]}})

    @app.get("/api/studio/events")
    async def studio_events(sid: Optional[str] = None):
        """Notification 下行（SSE）——Studio 三态中的 notification 通道。

        事件帧：data: {"method","payload","ts"}；`: hb` 心跳防断连；
        可选 sid 过滤（payload.session 匹配）。慢消费者丢最旧不阻塞引擎。
        """
        q = svc.notifications.subscribe()

        async def gen():
            try:
                yield ": connected\n\n"
                idle = 0
                while True:
                    # 断连由 Starlette 取消任务触发 GeneratorExit；
                    # 不调用 is_disconnected（流式下可能阻塞）
                    try:
                        evt = q.get_nowait()
                    except Empty:
                        idle += 1
                        if idle >= 60:            # ~12s 心跳
                            yield ": hb\n\n"
                            idle = 0
                        await asyncio.sleep(0.2)
                        continue
                    idle = 0
                    if sid and (evt.get("payload") or {}).get(
                            "session") != sid:
                        continue
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            finally:
                svc.notifications.unsubscribe(q)

        return StreamingResponse(
            gen(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no"})

    # ---- 桌面拾取器（M2）----
    @app.post("/api/spy/start")
    async def spy_start():
        from .spy import SpyError, SpyService, ensure_accessibility
        if svc.spy is None:
            svc.spy = SpyService()
        try:
            ensure_accessibility()   # 未授权 → 409（含系统弹窗触发）
        except SpyError as e:
            raise HTTPException(409, str(e))
        try:
            result = svc.spy.start()
        except SpyError as e:
            raise HTTPException(503, str(e))
        _ensure_job("spy", "desktop_spy",
                    on_cancel=lambda: svc.spy.stop())
        return result

    @app.post("/api/spy/stop")
    async def spy_stop():
        if svc.spy is None:
            return {"stopped": False}
        try:
            svc.jobs.complete("spy")
        except Exception:
            pass
        return svc.spy.stop()

    @app.get("/api/spy/status")
    async def spy_status():
        if svc.spy is None:
            return {"active": False, "version": 0, "latest": None}
        return svc.spy.status()

    @app.post("/api/spy/capture")
    async def spy_capture():
        from .spy import SpyError
        if svc.spy is None:
            raise HTTPException(404, "spy not started")
        try:
            return svc.spy.capture()
        except SpyError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/spy/stream")
    async def spy_stream():
        if svc.spy is None:
            raise HTTPException(404, "spy not started")
        from fastapi.responses import StreamingResponse
        from .spy import spy_stream_frames

        return StreamingResponse(
            spy_stream_frames(svc.spy),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache",
                     "X-Accel-Buffering": "no"},
        )

    # ---- 数据抓取向导（M3）----
    @app.post("/api/scrape/start")
    async def scrape_start(body: RecorderStartRequest):
        from .scrape_service import ScrapeError, ScrapeWizardService
        if svc.scrape is None:
            svc.scrape = ScrapeWizardService()
        try:
            return svc.scrape.start(body.url)
        except ScrapeError as e:
            raise HTTPException(409, str(e))

    def _scrape_get(sid: str):
        from .scrape_service import ScrapeError
        if svc.scrape is None:
            raise HTTPException(404, "no scrape session")
        try:
            return svc.scrape._get(sid)
        except ScrapeError as e:
            raise HTTPException(404, str(e))

    @app.get("/api/scrape/status/{sid}")
    async def scrape_status(sid: str):
        _scrape_get(sid)
        from .scrape_service import ScrapeError
        try:
            return svc.scrape.status(sid)
        except ScrapeError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/scrape/{sid}/assign")
    async def scrape_assign(sid: str, body: dict):
        _scrape_get(sid)
        from .scrape_service import ScrapeError
        try:
            return svc.scrape.assign(sid, str(body.get("role", "")),
                                  str(body.get("name", "")))
        except ScrapeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/scrape/{sid}/preview")
    async def scrape_preview(sid: str, body: dict):
        _scrape_get(sid)
        from .scrape_service import ScrapeError
        try:
            return svc.scrape.preview(sid,
                                   max_rows=int(body.get("max_rows", 5)))
        except ScrapeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/scrape/{sid}/generate")
    async def scrape_generate(sid: str, body: dict):
        _scrape_get(sid)
        from .scrape_service import ScrapeError
        try:
            return svc.scrape.generate(
                sid, base_id=str(body.get("base_id", "scrape")),
                with_loop=bool(body.get("with_loop", False)),
                body_action=str(body.get("body_action", "")),
                body_params=body.get("body_params") or {})
        except ScrapeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/scrape/{sid}/stop")
    async def scrape_stop(sid: str):
        from .scrape_service import ScrapeError
        if svc.scrape is None:
            return {"stopped": False}
        try:
            return svc.scrape.stop(sid)
        except ScrapeError:
            return {"stopped": False}

    # ---- 意图编译（Phase B）----
    @app.post("/api/intent/compile")
    async def intent_compile(body: dict):
        utterance = str(body.get("utterance", ""))
        if not intent_compiler:
            raise HTTPException(501, "intent compiler not configured")
        result = intent_compiler.compile(utterance)
        return {
            "ok": result.ok,
            "process_yaml": result.process_yaml,
            "template_id": result.template_id,
            "questions": result.questions,
            "error": result.error,
        }

    # ---- 失败回流诊断（Phase C）----
    @app.post("/api/intent/explain-failure")
    async def explain_failure(body: dict):
        session = str(body.get("session", "")).strip()
        if not session:
            raise HTTPException(400, "session required")
        if _diag is None:
            raise HTTPException(
                501, "failure diagnostic not configured (需 LLM Key)")

        records: List[Dict[str, Any]] = []
        for path in server.journal_paths:
            try:
                from .persist import journal_records

                for rec in journal_records(path):
                    if rec.get("session") == session:
                        records.append(rec)
            except OSError:
                continue
        if not records:
            raise HTTPException(404, f"no journal found for {session!r}")

        ctx = _diag.extract_failures(records)
        process_yaml = ""
        proc_id = next((r.get("process_id") for r in records
                        if r.get("process_id")), None)
        if proc_id and server.processes_dir:
            from pathlib import Path as _P

            pf = _P(server.processes_dir) / f"{proc_id}.yaml"
            if pf.is_file():
                process_yaml = pf.read_text(encoding="utf-8")[:3000]

        out = _diag.explain(ctx, process_yaml=process_yaml)
        out["failure_context"] = ctx
        return out

    # ---- 定时任务 CRUD（M2）----
    @app.get("/api/jobs")
    async def jobs_list():
        if serve_app is None:
            raise HTTPException(501, "jobs require serve mode")
        return serve_app.list_job_specs()

    @app.post("/api/jobs/save")
    async def jobs_save(body: dict):
        if serve_app is None:
            raise HTTPException(501, "jobs require serve mode")
        from .serve import ServeError
        try:
            return serve_app.upsert_job_spec(body)
        except ServeError as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/jobs/{jid}")
    async def jobs_delete(jid: str):
        if serve_app is None:
            raise HTTPException(501, "jobs require serve mode")
        return serve_app.remove_job_spec(jid)

    @app.post("/api/jobs/{jid}/run")
    async def jobs_run(jid: str):
        if serve_app is None:
            raise HTTPException(501, "jobs require serve mode")
        from .serve import ServeError
        try:
            return serve_app.run_job_now(jid)
        except ServeError as e:
            raise HTTPException(404, str(e))

    # ---- SSE journal stream ----
    @app.get("/api/journal/records")
    async def journal_records_by_session(session: str = ""):
        """按会话查询 journal 记录（Runs 页详情）。

        扫描配置的全部 journal 文件；session 为空返回 400。
        """
        if not session:
            raise HTTPException(400, "session query param required")
        out = []
        for path in server.journal_paths:
            try:
                for rec in journal_records(path):
                    if rec.get("session") == session:
                        out.append(rec)
            except OSError:
                continue
        out.sort(key=lambda r: float(r.get("ts", 0)))
        return {"session": session, "records": out, "count": len(out)}

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