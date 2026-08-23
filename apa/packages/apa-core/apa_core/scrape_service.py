"""apa-core: 数据抓取向导会话（Playwright 注入 + 点击路径回传）。

线程模型（关键约束）：Playwright sync 对象绑定创建线程。
本服务用「命令队列」把所有页面操作路由回专属线程：
  公有方法(assign/preview/generate/stop) → 打包闭包入队
  专属线程 run(): 启动浏览器+绑定 → 循环执行队列命令

注入脚本与录制器同款：点击被 preventDefault 拦截，仅上报结构化路径
[{tag,idx,cls,id,n(父内同标签兄弟数)}] root-first。
"""
from __future__ import annotations

import queue
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

from .scrape import build_scrape_steps, infer_row_selector, relative_column_path


class ScrapeError(RuntimeError):
    pass


_PICK_JS = """
(() => {
  // 注意：不加 document 级守卫——document.open()/setContent 会保留
  // expando 属性但清掉监听器，守卫会阻止重装（与录制器同款教训）。
  // 重复注入安全：旧监听器已随文档清除；同文档内多次调用由调用方约束。
  function pathOf(el) {
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && cur.tagName !== "HTML") {
      const tag = cur.tagName.toLowerCase();
      let idx = 1, s = cur;
      while ((s = s.previousElementSibling)) {
        if (s.tagName === cur.tagName) idx++;
      }
      const parent = cur.parentElement;
      let same = {};
      if (parent) {
        for (const c of parent.children) {
          const t = c.tagName.toLowerCase();
          same[t] = (same[t] || 0) + 1;
        }
      }
      parts.push({
        t: tag,
        i: idx - 1,
        c: (typeof cur.className === "string" ? cur.className : ""),
        id: cur.id || "",
        n: same,
        text: (cur.innerText || "").slice(0, 80),
      });
      cur = cur.parentElement;
    }
    return parts.reverse();
  }

  document.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    try { window.__apa_pick({ kind: "pick", path: pathOf(e.target) }); }
    catch (_) {}
  }, true);
})();
"""


class _Session:
    def __init__(self, url: str, headless: bool) -> None:
        self.url = url
        self.headless = headless
        self.picks: List[Dict] = []
        self.rows: List[List[Dict]] = []
        self.columns: Dict[str, Dict] = {}
        self.next_selector: Optional[str] = None
        self.row_info: Optional[Dict] = None
        self.error: Optional[str] = None
        self.started = threading.Event()
        self.stop_flag = threading.Event()
        self.finished = threading.Event()
        self.session = None            # RecorderSession（专属线程内访问）
        self.page = None
        self.cmd_q: "queue.Queue" = queue.Queue()


class ScrapeWizardService:
    """多会话抓取向导。公有方法线程安全。"""

    def __init__(self, max_sessions: int = 2,
                 start_timeout_s: float = 25.0) -> None:
        self._sessions: Dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._max = max_sessions
        self._start_timeout = float(start_timeout_s)

    # ---- 内部：命令路由 ------------------------------------------------------

    @staticmethod
    def _submit(sess: _Session, fn: Callable[[Any], Any],
                timeout: float = 30.0) -> Any:
        """在 Playwright 所属线程执行 fn(page) 并等待结果。"""
        fut: "queue.Queue" = queue.Queue()

        def job():
            try:
                fut.put(("ok", fn(sess.page)))
            except Exception as e:  # noqa: BLE001
                fut.put(("err", e))

        sess.cmd_q.put(job)
        try:
            kind, payload = fut.get(timeout=timeout)
        except queue.Empty:
            raise ScrapeError("wizard thread busy/no response") from None
        if kind == "err":
            raise payload
        return payload

    # ---- 会话管理 -----------------------------------------------------------

    def start(self, url: str, *, headless: bool = False) -> Dict[str, Any]:
        from .recorder import RecorderSession

        with self._lock:
            active = [s for s in self._sessions.values()
                      if not s.finished.is_set()]
            if len(active) >= self._max:
                raise ScrapeError(f"too many wizard sessions ({self._max})")
            sid = uuid.uuid4().hex[:12]
            sess = _Session(url, headless)
            self._sessions[sid] = sess

        def run() -> None:
            try:
                rs = RecorderSession(url, headless=headless)
                sess.session = rs
                rs.start()
                sess.page = rs._page
                rs._page.expose_binding(
                    "__apa_pick",
                    lambda src, ev: sess.picks.append(ev)
                    if isinstance(ev, dict) else None)

                def inject():
                    rs._page.evaluate(_PICK_JS)

                inject()
                sess.started.set()

                while not sess.stop_flag.is_set():
                    try:
                        job = sess.cmd_q.get(timeout=0.3)
                    except queue.Empty:
                        continue
                    job()
            except Exception as e:  # noqa: BLE001
                sess.error = f"{type(e).__name__}: {e}"
                sess.started.set()
            finally:
                sess.finished.set()
                try:
                    if rs is not None:
                        rs.stop()
                except Exception:
                    pass

        t = threading.Thread(target=run, daemon=True,
                             name=f"apa-scrape-{sid}")
        t.start()
        if not sess.started.wait(timeout=self._start_timeout):
            raise ScrapeError(
                f"wizard browser failed to start: {sess.error or 'timeout'}")
        return {"session_id": sid}

    # ---- 状态 ---------------------------------------------------------------

    def reinject(self, sid: str) -> None:
        """重装点击监听器（set_content / 文档替换后调用）。"""
        s = self._get(sid)
        self._submit(s, lambda pg: pg.evaluate(_PICK_JS))

    def status(self, sid: str) -> Dict[str, Any]:
        s = self._get(sid)
        return {
            "session_id": sid,
            "pending_picks": len(s.picks),
            "rows_marked": len(s.rows),
            "columns": {k: v["selector"] for k, v in s.columns.items()},
            "row_selector": (s.row_info or {}).get("selector", ""),
            "strategy": (s.row_info or {}).get("strategy", ""),
            "active": s.started.is_set() and not s.finished.is_set(),
            "error": s.error,
        }

    # ---- 标记 ---------------------------------------------------------------

    def assign(self, sid: str, role: str, name: str = "") -> Dict[str, Any]:
        s = self._get(sid)
        if not s.picks:
            raise ScrapeError("no pending click — 在浏览器中点击目标元素")
        ev = s.picks.pop(0)
        path = [
            {"tag": p["t"], "idx": p["i"], "cls": p.get("c", ""),
             "id": p.get("id", ""), "n": p.get("n", {})}
            for p in ev.get("path", [])
        ]
        text = ev.get("text", "")

        if role == "row":
            s.rows.append(path)
            if len(s.rows) == 2:
                ctx = {"repeat_parent":
                       {"same_tag_siblings": self._sibling_ctx(path)}}
                s.row_info = infer_row_selector(s.rows[0], s.rows[1], ctx=ctx)
                if not s.row_info.get("ok"):
                    reason = s.row_info.get("reason", "?")
                    s.row_info = None
                    s.rows.clear()
                    raise ScrapeError(f"行推断失败: {reason}——请重新点选两行")
            return {"assigned": "row", "rows_marked": len(s.rows)}

        if role == "column":
            if not s.rows or not s.row_info:
                raise ScrapeError("先标记两行再添加列")
            if not name:
                raise ScrapeError("column 需要 name")
            # 列可点在任一已标记行上（用户习惯点第一行的单元格）
            rel = None
            for rp in s.rows:
                r = relative_column_path(rp, path)
                if r.get("ok"):
                    rel = r
                    break
            if rel is None:
                raise ScrapeError("列不在已标记行的子树内——请点行内元素")
            s.columns[name] = {"selector": rel["selector"],
                               "text_sample": text}
            return {"assigned": "column", "name": name,
                    "selector": rel["selector"]}

        if role == "next":
            s.next_selector = _css_from_path(path)
            return {"assigned": "next", "selector": s.next_selector}

        raise ScrapeError(f"unknown role {role!r}")

    @staticmethod
    def _sibling_ctx(row_path: List[Dict]) -> Dict[str, int]:
        """重复轴兄弟统计：行元素自身的 n（其父容器=列表容器的子标签计数）。"""
        if row_path:
            n = row_path[-1].get("n")
            if isinstance(n, dict):
                return n
        return {}

    # ---- 预览 / 生成 / 停止 ---------------------------------------------------

    def preview(self, sid: str, *, max_rows: int = 5) -> Dict[str, Any]:
        s = self._get(sid)
        if not s.row_info:
            raise ScrapeError("尚未完成两行标记")

        js = """
([rowSel, cols, maxRows]) => {
  const rows = [...document.querySelectorAll(rowSel)].slice(0, maxRows);
  return rows.map(r => {
    const obj = {};
    for (const [name, sel] of Object.entries(cols)) {
      if (sel === ".") { obj[name] = r.innerText.trim().slice(0,60); continue; }
      const cell = r.querySelector(sel);
      obj[name] = cell ? cell.innerText.trim().slice(0,60) : "";
    }
    return obj;
  });
}
"""
        row_sel = s.row_info["selector"]
        cols = {k: v["selector"] for k, v in s.columns.items()}
        rows = self._submit(s, lambda pg: pg.evaluate(
            js, [row_sel, cols, max_rows]))
        return {"rows": rows, "count": len(rows),
                "row_selector": row_sel,
                "strategy": s.row_info.get("strategy")}

    def generate(self, sid: str, *, base_id: str,
                 with_loop: bool = False,
                 body_action: str = "",
                 body_params: Optional[Dict] = None) -> Dict[str, Any]:
        s = self._get(sid)
        if not s.row_info:
            raise ScrapeError("尚未完成两行标记")
        steps = build_scrape_steps(
            process_step_base=base_id,
            url=s.url,
            row_selector=s.row_info["selector"],
            columns={k: v["selector"] for k, v in s.columns.items()},
            next_selector=None,
            body_action=body_action if with_loop else None,
            body_params=body_params,
        )
        return {"steps": steps, "step_count": len(steps)}

    def stop(self, sid: str) -> Dict[str, Any]:
        s = self._get(sid)
        was_active = not s.finished.is_set()
        s.stop_flag.set()
        s.finished.wait(timeout=8)
        with self._lock:
            self._sessions.pop(sid, None)
        return {"stopped": was_active}

    def _get(self, sid: str) -> _Session:
        with self._lock:
            s = self._sessions.get(sid)
        if s is None:
            raise ScrapeError(f"unknown scrape session {sid!r}")
        return s


def _css_from_path(path: List[Dict], depth: int = 3) -> str:
    segs = path[-depth:]
    parts = []
    for p in segs:
        cls = (p.get("cls") or "").split()
        c = next((x for x in cls
                  if all(ch.isalnum() or ch in "-_" for ch in x)), "")
        parts.append(p["tag"] + (f".{c}" if c else ""))
    return " > ".join(parts)