"""Phase 9 测试：.env 接口 / WS 后台调度循环 / Studio 认证。"""
import asyncio
import json
import time
from pathlib import Path

import os as _os
import pytest

from aip import make_action

from apa_core.config import (
    env_first,
    find_dotenv,
    load_dotenv,
    parse_env_file,
)
from apa_core.embedded import EmbeddedGateway
from apa_core.policy import PolicyConfig
from apa_core.registry import load_registries

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p9_001"


def registries():
    return load_registries(APA_ROOT / "registries" / "core.yaml",
                           APA_ROOT / "registries" / "browser.yaml")


# --- .env 接口 --------------------------------------------------------------------
class TestEnvConfig:
    def test_parse_env_file(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text(
            "# comment\n"
            "DEEPSEEK_API_KEY=sk-123\n"
            'export DEEPSEEK_BASE_URL="https://api.deepseek.com"\n'
            "\n"
            "EMPTY=\n", encoding="utf-8")
        data = parse_env_file(f)
        assert data["DEEPSEEK_API_KEY"] == "sk-123"
        assert data["DEEPSEEK_BASE_URL"] == "https://api.deepseek.com"
        assert data["EMPTY"] == ""

    def test_load_no_override_existing(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("A=from-file\nB=from-file\n", encoding="utf-8")
        monkeypatch.setenv("A", "already-set")
        loaded = load_dotenv(f)
        import os
        assert os.environ["A"] == "already-set"      # 不覆盖
        assert os.environ["B"] == "from-file"
        assert loaded == {"B": "from-file"}

    def test_find_dotenv_walks_up(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        found = find_dotenv()
        assert found is not None and found.name == ".env"

    def test_env_first_llm_fallback_chain(self, tmp_path, monkeypatch):
        f = tmp_path / ".env"
        f.write_text("DEEPSEEK_API_KEY=sk-from-deepseek-env\n",
                     encoding="utf-8")
        # 重置模块级幂等状态（其他测试可能已触发过加载）
        monkeypatch.setattr("apa_core.config._LOADED_FROM", None)
        monkeypatch.setattr("apa_core.config.find_dotenv",
                            lambda **kw: f)
        monkeypatch.delenv("APA_LLM_API_KEY", raising=False)
        from apa_core import config as _cfg
        from apa_core.llm import LLMClient
        print("DBG _LOADED_FROM:", _cfg._LOADED_FROM,
              "| finder:", _cfg.find_dotenv,
              "| env:", _os.environ.get("DEEPSEEK_API_KEY"))
        client = LLMClient()
        print("DBG after:", client.api_key, "| env:",
              _os.environ.get("DEEPSEEK_API_KEY"))
        assert client.api_key == "sk-from-deepseek-env"

    def test_repo_env_example_matches_deepseek(self):
        """仓库模板必须以 DeepSeek 为底座且含关键键名。"""
        text = (APA_ROOT / ".env.example").read_text(encoding="utf-8")
        for key in ("DEEPSEEK_API_KEY=", "DEEPSEEK_BASE_URL=",
                    "APA_LLM_MODEL=", "APA_VISION_"):
            assert key in text


# --- WS 后台调度循环 -----------------------------------------------------------------
class TestWsBackgroundTick:
    def test_timeout_retry_fires_without_external_tick(self):
        """独立部署：无外部 tick 驱动，后台循环应触发超时→标记 timeout。"""
        asyncio_run(self._scenario())

    async def _scenario(self):
        import websockets

        clock = FakeClock(start_ms=0) if False else None  # 真实时间驱动
        gw = EmbeddedGateway(SESSION, registry=registries(),
                             identities={"executor": "ws_ex",
                                         "agent": "ws_ag"})
        gw.run()
        from apa_core.ws_gateway import WsGatewayServer
        server = WsGatewayServer(gw.gateway, port=0,
                                 tick_interval_s=0.1)
        port = await server.start()
        url = f"ws://127.0.0.1:{port}"

        ex = await websockets.connect(url)
        await ex.send(json.dumps({"type": "hello", "role": "executor",
                                  "source": "ws_ex"}))
        await asyncio.wait_for(ex.recv(), 3)   # hello ack

        ag = await websockets.connect(url)
        await ag.send(json.dumps({"type": "hello", "role": "agent",
                                  "source": "ws_ag"}))
        await asyncio.wait_for(ag.recv(), 3)

        # agent 发 browser.scroll（timeout_ms=3000，retries=0）
        # 执行器侧为裸连接不回应 —— 由网关后台循环推进超时（§8.3）
        act = make_action(SESSION, "ws_ag", "browser.scroll",
                          params={"direction": "down"})
        act.seq = 1
        await ag.send(json.dumps(act.to_dict()))

        # 无外部 tick：后台循环应在 ~timeout 后把动作标记为 timeout
        # （超时属网关内部终态，不产生对 agent 的额外帧 —— §6.5）
        deadline = asyncio.get_running_loop().time() + 8
        outcome = None
        while asyncio.get_running_loop().time() < deadline:
            outcome = gw.gateway.session.actions.outcome(act.id)
            if outcome and outcome[0] == "timeout":
                break
            await asyncio.sleep(0.1)
        assert outcome and outcome[0] == "timeout"
        # retries=0 → 无重发记录
        assert gw.gateway.retry_scheduler.retry_events == 0

        for sock in (ex, ag):
            try:
                await sock.close()
            except Exception:
                pass
        await asyncio.sleep(0.05)
        await server.close()


def asyncio_run(coro):
    import asyncio
    asyncio.run(coro)


# --- Studio 认证 -------------------------------------------------------------------
class TestStudioAuth:
    def test_bearer_required_when_configured(self, tmp_path):
        jpath = tmp_path / "j.jsonl"
        jpath.write_text(json.dumps({
            "kind": "state", "ts": int(time.time() * 1000),
            "session": "sx", "to": "COMPLETED"}) + "\n")
        from apa_core.studio import StudioServer
        studio = StudioServer([str(jpath)], port=0, token="secret-t")
        port = studio.start_background()
        import urllib.error
        import urllib.request
        base = f"http://127.0.0.1:{port}"

        try:
            urllib.request.urlopen(f"{base}/api/sessions", timeout=3)
            raise AssertionError("expected 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401

        req = urllib.request.Request(
            f"{base}/api/sessions",
            headers={"Authorization": "Bearer secret-t"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        assert "sx" in data
        studio.shutdown()

    def test_open_when_no_token(self, tmp_path):
        from apa_core.studio import StudioServer
        studio = StudioServer([str(tmp_path / "none.jsonl")], port=0)
        port = studio.start_background()
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions",
                                    timeout=3) as resp:
            json.loads(resp.read())   # 200
        studio.shutdown()