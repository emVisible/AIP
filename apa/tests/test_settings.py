"""H7 设置子系统测试（分层合并/脱敏/双写/profiles/计量退避）。"""
import json
from pathlib import Path

import pytest

import apa_core.settings as settings_mod
from apa_core.settings import (Settings, SettingsManager, deep_merge,
                               _unknown_keys)
from apa_core import settings as settings_mod

LEGACY_VARS = list(settings_mod.LEGACY_ENV_MAP)


@pytest.fixture(autouse=True)
def _clean_legacy_env(monkeypatch):
    """设置类测试必须与外部 env 污染隔离（宪法 §六）。"""
    for k in LEGACY_VARS:
        monkeypatch.delenv(k, raising=False)

from apa_core.llm import FakeLLMClient


# ---- 合并 ----

def test_deep_merge_nested_and_scalar():
    base = {"llm": {"model": "a", "temperature": 0.0},
            "data": {"root": "data"}}
    over = {"llm": {"model": "b"}, "extra": 1}
    out = deep_merge(base, over)
    assert out["llm"] == {"model": "b", "temperature": 0.0}
    assert out["data"] == {"root": "data"} and out["extra"] == 1
    assert base["llm"]["model"] == "a", "不得污染入参"


def test_layering_user_over_defaults(tmp_path):
    user = tmp_path / "config.yaml"
    user.write_text("llm:\n  model: from-user\n")
    mgr = SettingsManager(user_path=user,
                          project_path=tmp_path / "absent.yaml")
    assert mgr.current.llm.model == "from-user", (
        f"model={mgr.current.llm.model!r} "
        f"user={user} exists={user.exists()} "
        f"content={user.read_text()!r} "
        f"env_owned={mgr.env_owned_paths()}")


def test_project_overrides_user(tmp_path):
    (tmp_path / "user.yaml").write_text("llm:\n  model: user\n"
                                        "data:\n  root: data\n")
    (tmp_path / "apa.config.yaml").write_text(
        "llm:\n  model: project\n")
    mgr = SettingsManager(user_path=tmp_path / "user.yaml",
                          project_path=tmp_path / "apa.config.yaml")
    assert mgr.current.llm.model == "project"


def test_env_compat_marks_owned_and_applies(tmp_path, monkeypatch):
    monkeypatch.setenv("APA_LLM_MODEL", "env-model")
    mgr = SettingsManager(user_path=tmp_path / "u.yaml",
                          project_path=tmp_path / "p.yaml")
    assert mgr.current.llm.model == "env-model"
    assert "llm.model" in mgr.env_owned_paths()


# ---- 双写与守卫 ----

@pytest.fixture()
def mgr(tmp_path):
    return SettingsManager(user_path=tmp_path / "u.yaml",
                           project_path=tmp_path / "p.yaml")


def test_update_writes_user_layer_and_hot_applies(mgr):
    mgr.update({"llm": {"model": "hot-model"}})
    assert mgr.current.llm.model == "hot-model"
    on_disk = mgr.user_path.read_text()
    assert "hot-model" in on_disk
    # 重启等价性：新实例读回一致
    fresh = SettingsManager(user_path=mgr.user_path,
                            project_path=mgr.project_path)
    assert fresh.current.llm.model == "hot-model"


def test_update_rejects_unknown_keys(mgr):
    with pytest.raises(ValueError, match="未知/禁写键"):
        mgr.update({"llm": {"api_key": "sk-secret123"}})


def test_env_owned_path_rejected_on_write(mgr, monkeypatch):
    monkeypatch.setenv("APA_DATA_DIR", "/custom")
    mgr.reload()
    with pytest.raises(ValueError, match="环境变量"):
        mgr.update({"data": {"root": "other"}})


def test_structural_redaction_no_secret_field(mgr):
    """结构化脱敏：只有 auth_spec 引用，无明文密钥字段。"""
    dump = json.dumps(mgr.get())
    assert '"api_key"' not in dump          # 不存在明文密钥字段
    assert "sk-" not in dump                # 无任何疑似密钥值
    assert '"auth_spec"' in dump            # 引用规格可见（非机密）


def test_invalid_project_yaml_ignored_not_crash(tmp_path):
    (tmp_path / "p.yaml").write_text("{broken")
    mgr = SettingsManager(user_path=tmp_path / "u.yaml",
                          project_path=tmp_path / "p.yaml")
    assert mgr.current.llm.provider == "deepseek"  # 走默认


def test_profile_activation_overrides_llm(tmp_path):
    (tmp_path / "u.yaml").write_text(
        "active_profile: fast\n"
        "profiles:\n"
        "  fast:\n"
        "    llm:\n"
        "      model: flash-lite\n")
    mgr = SettingsManager(user_path=tmp_path / "u.yaml",
                          project_path=tmp_path / "p.yaml")
    assert mgr.current.llm.model == "flash-lite"


# ---- schema 递归未知键（含 additionalProperties.$ref 白名单） ----

def test_unknown_keys_allows_mcp_server_entries_but_rejects_bad_fields():
    schema = Settings.model_json_schema(ref_template="#/$defs/{model}")
    patch = {"mcp": {"servers": {
        "self": {"command": ["x"], "timeout_s": 5},
        "bad": {"nope": 1},
    }}}
    bad = _unknown_keys(patch, schema)
    assert any("mcp.servers.self.bad.nope" in b or
               b == "mcp.servers.bad.nope" for b in bad)
    # 合法条目不误报
    ok_patch = {"mcp": {"servers": {"self": {"command": ["x"]}}}}
    assert not _unknown_keys(ok_patch, schema)


from apa_core.settings import _unknown_keys  # noqa: E402


# ---- 计量退避（FakeHTTP 层面在 llm 单测覆盖；此处锁行为契约） ----

def test_fake_client_shape_stable():
    fake = FakeLLMClient(responses=[{"outcome": "ok"}])
    d = fake.decide(context={}, available_actions=[])
    assert d["outcome"] == "ok"


# ---- 工具函数引用 ----

def test_unknown_keys_helper_direct():
    schema = Settings.model_json_schema()
    assert _unknown_keys({"version": 2}, schema) == []
    assert _unknown_keys({"nope": 1}, schema) == ["nope"]


def _unknown_keys_import_fix():  # 防止顶部循环导入顺序问题
    return True


def test_open_dicts_accept_arbitrary_keys(mgr):
    """auth_spec 引用规格与 profiles 档案是开放结构——不得误报未知键。"""
    mgr.update({"llm": {"auth_spec": {"env": "MY_KEY"}}})
    assert mgr.current.llm.auth_spec == {"env": "MY_KEY"}
    mgr.update({"profiles": {"fast": {"llm": {"model": "x"}}}})
    assert "fast" in mgr.current.profiles


def test_update_rejects_unknown_keys(mgr):
    with pytest.raises(ValueError, match="未知/禁写键"):
        mgr.update({"llm": {"api_key": "sk-secret123"}})
