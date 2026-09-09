"""APA 测试基座（架构宪法 §六）。

共享夹具：
  core_services   —— 隔离目录的 CoreServices
  stub_serve      —— ServeApp 最小桩（save/test/list_job_specs）
  client          —— TestClient(create_app(..., services=core, serve_app=stub))
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apa_core.api import create_app
from apa_core.core_services import CoreServices


@pytest.fixture(autouse=True)
def _loopback_proxy_guard():
    """回环代理隔离（B2）：Clash 等系统代理会劫持 httpx 的回环请求
    （127.0.0.1 → 502，curl 直连正常；python 经系统代理配置）。
    为回环强制 NO_PROXY；无代理机器上零影响（仅补 localhost 条目）。"""
    import os

    keys = ("NO_PROXY", "no_proxy")
    addition = "127.0.0.1,localhost"
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        cur = saved[k]
        if cur is None:
            os.environ[k] = addition
        elif "127.0.0.1" not in cur:
            os.environ[k] = cur + "," + addition
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def core_services(tmp_path):
    return CoreServices(
        sessions=str(tmp_path / "sessions"),
        spills=tmp_path / "spills",
    )


@pytest.fixture()
def stub_serve():
    return SimpleNamespace(
        save_process_yaml=lambda pid, yaml: {"ok": True, "id": pid},
        test_run_process=lambda yaml, event, data, step_observer=None: (
            [step_observer and step_observer(
                {"step_id": "s1", "action": "demo.a", "status": "ok"})],
            {"outcome": "success", "gateway_state": "",
             "steps": [{"step": "s1", "action": "demo.a",
                        "status": "ok"}]})[1],
        list_job_specs=lambda: [],
    )


@pytest.fixture()
def client(tmp_path, core_services, stub_serve, monkeypatch):
    # 类级补丁：内部 server 实例同样被替换；保留 step_observer 直播语义
    from apa_core.studio import StudioServer

    def _fake_test(self, yaml_text, event_name, event_data,
                   step_observer=None):
        if step_observer:
            step_observer({"step_id": "s1", "action": "demo.a",
                           "status": "ok"})
        return {"outcome": "success", "gateway_state": "",
                "steps": [{"step": "s1", "action": "demo.a",
                           "status": "ok"}]}

    monkeypatch.setattr(StudioServer, "test_run_process", _fake_test)
    monkeypatch.setattr(StudioServer, "save_process_yaml",
                        lambda self, pid, yaml: {"ok": True, "id": pid})

    app = create_app(journals=[],
                     sessions_dir=str(tmp_path / "sessions"),
                     services=core_services,
                     serve_app=stub_serve)
    return TestClient(app)


@pytest.fixture()
def legacy_env(client, core_services, monkeypatch):
    """在应用构建后设置遗留 env，并 reload 使 owned 标记生效。"""
    monkeypatch.setenv("APA_LLM_MODEL", "env-wins")
    monkeypatch.setenv("APA_DATA_DIR", "/custom-data")
    core_services.settings.reload()


@pytest.fixture(autouse=True)
def _legacy_llm_env_guard():
    """跨测试隔离：ServeApp 等会经 .env 向全局 environ 注入遗留变量，
    泄漏会破坏下游设置类测试的 owned 语义（H7 事故固化）。"""
    import os

    from apa_core.settings import LEGACY_ENV_MAP

    keys = list(LEGACY_ENV_MAP)
    saved = {k: os.environ.get(k) for k in keys}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
