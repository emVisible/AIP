"""apa-executors: DesktopExecutor（设计文档 §5.4）。

感知优先级：Accessibility API → OCR → VLM（POC 实现 1/3，OCR/VLM 留插槽）。
后端可插拔：
    · OsascriptBackend — macOS System Events（窗口列表/激活/键击）
    · MockDesktopBackend — 测试用桌面模型

VLM 在 Executor 本地终止，产物是语义元素列表，不进入 AIP 协议（C6）。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from apa_sdk.executor_base import AIPExecutor


@dataclass
class DesktopWindow:
    app_name: str = ""
    title: str = ""
    pid: int = 0
    focused: bool = False
    elements: List[dict] = field(default_factory=list)  # {role, text, id}


class DesktopBackend:
    """桌面抽象。"""

    def list_windows(self) -> List[DesktopWindow]:
        raise NotImplementedError

    def activate(self, *, app_name: str, title: str) -> bool:
        raise NotImplementedError

    def close_window(self, *, app_name: str, title: str) -> bool:
        raise NotImplementedError

    def keystroke(self, text: str) -> None:
        raise NotImplementedError

    def key_code(self, keys: str) -> None:
        raise NotImplementedError

    def launch(self, executable: str) -> None:
        raise NotImplementedError

    def screen_elements(self) -> List[dict]:
        """前台窗口的可交互元素（Accessibility 提升结果）。"""
        return []


class OsascriptBackend(DesktopBackend):
    """macOS System Events 后端。需要辅助功能权限（自动化授权）。"""

    def _osa(self, script: str) -> str:
        out = subprocess.run(["osascript", "-e", script],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip()[:200])
        return out.stdout.strip()

    def list_windows(self) -> List[DesktopWindow]:
        script = '''
        tell application "System Events"
            set out to ""
            repeat with p in (every application process whose background only is false)
                set pn to name of p
                repeat with w in (every window of p)
                    set out to out & pn & "|" & (name of w as text) & linefeed
                end repeat
            end repeat
            return out
        end tell'''
        try:
            raw = self._osa(script)
        except Exception:
            return []
        windows: List[DesktopWindow] = []
        for line in raw.splitlines():
            if "|" not in line:
                continue
            app_name, _, title = line.partition("|")
            windows.append(DesktopWindow(app_name=app_name, title=title))
        return windows

    def activate(self, *, app_name: str, title: str) -> bool:
        try:
            self._osa(
                f'tell application "System Events" to set frontmost of '
                f'(first process whose name is "{app_name}") to true')
            return True
        except Exception:
            return False

    def close_window(self, *, app_name: str, title: str) -> bool:
        try:
            self._osa(
                f'tell application "System Events" to tell (first process whose '
                f'name is "{app_name}") to click button 1 of window "{title}"')
            return True
        except Exception:
            return False

    def keystroke(self, text: str) -> None:
        safe = text.replace('"', '\\"')
        self._osa(f'tell application "System Events" to keystroke "{safe}"')

    def key_code(self, keys: str) -> None:
        self._osa(f'tell application "System Events" to key code {keys}')

    def launch(self, executable: str) -> None:
        self._osa(f'tell application "{executable}" to activate')


class MockDesktopBackend(DesktopBackend):
    """测试用桌面模型。"""

    def __init__(self) -> None:
        self.windows: List[DesktopWindow] = [
            DesktopWindow(app_name="Finder", title="桌面"),
            DesktopWindow(app_name="ERP客户端", title="采购订单 - 待审批",
                          pid=4242,
                          elements=[{"role": "button", "text": "批准",
                                     "id": "btn-approve"}]),
        ]
        self.activated: List[str] = []
        self.typed: List[str] = []
        self.closed: List[str] = []
        self.launched: List[str] = []

    def list_windows(self) -> List[DesktopWindow]:
        return list(self.windows)

    def activate(self, *, app_name: str, title: str) -> bool:
        for w in self.windows:
            if w.app_name == app_name and (not title or w.title == title):
                w.focused = True
                self.activated.append(f"{app_name}:{title}")
                return True
        return False

    def close_window(self, *, app_name: str, title: str) -> bool:
        before = len(self.windows)
        self.windows = [w for w in self.windows
                        if not (w.app_name == app_name and w.title == title)]
        if len(self.windows) < before:
            self.closed.append(title)
            return True
        return False

    def keystroke(self, text: str) -> None:
        self.typed.append(text)

    def key_code(self, keys: str) -> None:
        self.typed.append(f"<key:{keys}>")

    def launch(self, executable: str) -> None:
        self.launched.append(executable)

    def screen_elements(self) -> List[dict]:
        focused = [w for w in self.windows if w.focused]
        return focused[0].elements if focused else []


class DesktopExecutor(AIPExecutor):
    def __init__(self, source: str, session_id: str, transport=None, *,
                 backend: Optional[DesktopBackend] = None,
                 context_store=None) -> None:
        super().__init__(source, session_id, transport,
                         context_store=context_store)
        self.backend = backend or MockDesktopBackend()
        self._seen: List[DesktopWindow] = []

    def start_observation(self) -> None:
        """感知循环：由 driver 周期调用 observe() 发出窗口事件。"""

    def observe(self) -> int:
        """扫描窗口 → 语义事件（desktop.window.appeared/focused）。返回事件数。"""
        count = 0
        known = {(w.app_name, w.title) for w in self._seen}
        try:
            current = self.backend.list_windows()
        except Exception:
            return 0
        for w in current:
            if (w.app_name, w.title) not in known:
                ref = self.put_context(
                    f"win_{w.app_name}_{abs(hash(w.title)) % 10000}",
                    {"app": w.app_name, "title": w.title})
                self.emit("desktop.window.appeared",
                          {"app_name": w.app_name, "title": w.title,
                           "pid": w.pid, "context": ref})
                count += 1
            if w.focused:
                self.emit("desktop.window.focused",
                          {"app_name": w.app_name, "title": w.title})
                count += 1
        self._seen = current
        return count

    def _find_window(self, *, app_name: Optional[str],
                     title: Optional[str]) -> Optional[DesktopWindow]:
        for w in self.backend.list_windows():
            if app_name and w.app_name != app_name:
                continue
            if title and title not in w.title:
                continue
            return w
        return None

    def _execute_action(self, name: str, params: dict) -> Tuple[bool, dict]:
        b = self.backend
        match name:
            case "if.window_exists":
                title_kw = str(params.get("title_contains", ""))
                hits = [w for w in b.list_windows()
                        if title_kw.lower() in (w.title or "").lower()]
                return True, {"matched": bool(hits),
                              "windows": [{"app": w.app_name,
                                           "title": w.title}
                                          for w in hits[:5]]}

            case "wait.window":
                import time as _t

                title_kw = str(params.get("title_contains", ""))
                timeout_s = min(float(params.get("timeout_s", 30.0)), 300.0)
                deadline = _t.monotonic() + timeout_s
                while _t.monotonic() < deadline:
                    for w in b.list_windows():
                        if title_kw.lower() in (w.title or "").lower():
                            return True, {"window": {"app": w.app_name,
                                                      "title": w.title}}
                    _t.sleep(0.4)
                return False, {"code": "wait_timeout",
                               "title_contains": title_kw}

            case "desktop.window.activate":
                ok = b.activate(app_name=params.get("app_name", ""),
                                title=params.get("title", ""))
                if not ok:
                    return False, {"code": "window_not_found"}
                self.observe()
                return True, {}

            case "desktop.window.close":
                ok = b.close_window(app_name=params.get("app_name", ""),
                                    title=params.get("title", ""))
                return (True, {}) if ok else (False, {"code": "window_not_found"})

            case "desktop.element.click":
                elements = b.screen_elements()
                want = params.get("element_id") or ""
                hit = next((e for e in elements
                            if e.get("id") == want or e.get("text") == want), None)
                if hit is None:
                    return False, {"code": "target_not_found"}
                return True, {"clicked": hit}

            case "desktop.keyboard.input":
                b.keystroke(str(params.get("text", "")))
                return True, {}

            case "desktop.keyboard.shortcut":
                b.key_code(str(params.get("keys", "")))
                return True, {}

            case "desktop.process.list":
                import subprocess as _sp

                kw = str(params.get("name_contains", ""))
                r = _sp.run(["ps", "aux"], capture_output=True,
                            text=True, timeout=10)
                procs = []
                for line in (r.stdout or "").splitlines()[1:]:
                    parts = line.split(None, 10)
                    if len(parts) < 11:
                        continue
                    pname = parts[10]
                    if kw and kw.lower() not in pname.lower():
                        continue
                    procs.append({
                        "pid": int(parts[1]),
                        "cpu_pct": float(parts[2]),
                        "mem_pct": float(parts[3]),
                        "command": pname[:120],
                    })
                procs.sort(key=lambda x: -x["cpu_pct"])
                return True, {"processes": procs[:params.get("limit", 30)],
                               "count": len(procs)}

            case "desktop.window.resize":
                import subprocess as _sp

                app_name = str(params.get("app_name", ""))
                w, h = int(params.get("width", 800)), int(params.get("height", 600))
                script = (
                    f'tell application "System Events" to '
                    f'tell (first process whose name is "{app_name}") to '
                    f'set size of front window to {{{w}, {h}}}')
                _sp.run(["osascript", "-e", script],
                        capture_output=True, timeout=10)
                return True, {"resized": [w, h]}

            case "desktop.window.minimize":
                import subprocess as _sp

                app_name = str(params.get("app_name", ""))
                _sp.run(["osascript", "-e",
                    f'tell application "System Events" to '
                    f'set miniaturized of front window of '
                    f'(first process whose name is "{app_name}") to true'],
                    capture_output=True, timeout=10)
                return True, {"minimized": app_name}

            case "desktop.window.maximize":
                import subprocess as _sp

                _sp.run(["osascript", "-e",
                    'tell application "System Events" to '
                    'keystroke "f" using {control down, command down}'],
                    capture_output=True, timeout=10)
                return True, {"maximized": True}

            case "desktop.process.launch":
                b.launch(params["executable"])
                return True, {}

            case _:
                return False, {"code": "action_not_supported_by_executor"}