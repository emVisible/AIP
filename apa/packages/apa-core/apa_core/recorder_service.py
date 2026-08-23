"""apa-core: 录制器会话管理 —— serve 模式下的多会话录制服务。

每个会话在独立线程中运行 Playwright（sync API 不能进 asyncio 事件循环）。
API 层通过 start/status/stop 控制生命周期。

用法（api.py 内）：
    recorder = RecorderService()
    sid = recorder.start("https://example.com")
    ...
    yaml_text, events = recorder.stop(sid)
"""
from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, List, Optional

import yaml as _yaml

from .recorder import RecorderSession, events_to_process


class RecorderError(RuntimeError):
    pass


class _Session:
    """单次录制会话：线程 + Recorder + 事件缓冲。"""

    def __init__(self, url: str) -> None:
        self.url = url
        self.session = RecorderSession(url)
        self.thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None
        self.started_at = threading.Event()
        self.finished = threading.Event()

    def run(self) -> None:
        try:
            self.session.start()
            self.started_at.set()
            # 阻塞等待浏览器关闭；stop() 也会触发 close
            self.session.wait_until_closed()
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self.started_at.set()
        finally:
            try:
                self.session.stop()
            except Exception:
                pass
            self.finished.set()


class RecorderService:
    """录制器多会话注册表。进程内单例。"""

    def __init__(self, max_sessions: int = 3) -> None:
        self._sessions: Dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._max = max_sessions

    def start(self, url: str) -> Dict[str, Any]:
        with self._lock:
            active = [s for s in self._sessions.values() if not s.finished.is_set()]
            if len(active) >= self._max:
                raise RecorderError(
                    f"too many active recording sessions ({self._max})")
            sid = uuid.uuid4().hex[:12]
            sess = _Session(url)
            self._sessions[sid] = sess

        t = threading.Thread(target=sess.run, daemon=True,
                             name=f"apa-recorder-{sid}")
        sess.thread = t
        t.start()
        return {"session_id": sid}

    def status(self, sid: str) -> Dict[str, Any]:
        sess = self._get(sid)
        return {
            "session_id": sid,
            "url": sess.url,
            "events": len(sess.session.events),
            "active": not sess.finished.is_set(),
            "error": sess.error,
        }

    def stop(self, sid: str, *, process_id: str = "recorded_flow") -> Dict[str, Any]:
        sess = self._get(sid)
        if not sess.finished.is_set():
            try:
                # 触发浏览器关闭 → wait_until_closed 返回
                sess.session.stop()
            except Exception:
                pass
            sess.finished.wait(timeout=10)

        events = sess.session.snapshot_events()
        proc = events_to_process(events, process_id=process_id)
        yaml_text = _yaml.safe_dump(proc, allow_unicode=True, sort_keys=False)
        n_steps = len(proc["process"]["steps"])

        with self._lock:
            self._sessions.pop(sid, None)
        return {
            "steps": n_steps,
            "events": len(events),
            "yaml": yaml_text,
            "error": sess.error,
        }

    def _get(self, sid: str) -> _Session:
        with self._lock:
            sess = self._sessions.get(sid)
        if sess is None:
            raise RecorderError(f"unknown recording session {sid!r}")
        return sess

    def list_active(self) -> List[Dict[str, Any]]:
        with self._lock:
            sids = [sid for sid, s in self._sessions.items()
                    if not s.finished.is_set()]
        return [{"session_id": sid, **self.status(sid)} for sid in sids]