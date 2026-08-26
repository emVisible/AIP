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
