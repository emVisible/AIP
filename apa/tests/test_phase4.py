"""Phase 4（v1.0）测试：Vault / 凭据注入 / Policy 升级 / 速率限制 / 租户隔离 / Analytics / MockERP。"""
import asyncio
import json
import time
from pathlib import Path

import pytest

from aip import AIPPeer, FakeClock, make_action, make_result

from apa_core.analytics import report, summarize
from apa_core.embedded import EmbeddedGateway
from apa_core.llm import FakeLLMClient
from apa_core.mock_erp import MockERP
from apa_core.persist import SessionJournal
from apa_core.policy import PolicyConfig, PolicyDecision
from apa_core.registry import RegistryEntry, load_registries
from apa_core.vault import (
    EncryptedFileVault,
    EnvVault,
    VaultError,
    VaultManager,
)

APA_ROOT = Path(__file__).resolve().parent.parent
SESSION = "s_p4_001"
EXEC, AGENT = "bot_01", "proc_01"


def all_registries():
    return load_registries(
        APA_ROOT / "registries" / "core.yaml",
        APA_ROOT / "registries" / "browser.yaml",
        APA_ROOT / "registries" / "desktop.yaml",
        APA_ROOT / "registries" / "document.yaml",
        APA_ROOT / "registries" / "api.yaml")


def build(**kw):
    gw = EmbeddedGateway(SESSION, registry=all_registries(),
                         identities={"executor": EXEC, "agent": AGENT}, **kw)
    gw.run()
    return gw


# --- Vault ----------------------------------------------------------------------
class TestVault:
    def test_roundtrip_and_at_rest_encryption(self, tmp_path):
        v = EncryptedFileVault(tmp_path / "v.json", master_key=b"k" * 32)
        secret = "sk-live-abc123"
        v.put("erp_token", secret)
        assert v.get("erp_token") == secret
        raw = (tmp_path / "v.json").read_text()
        assert secret not in raw and "erp_token" in raw

    def test_tamper_detected(self, tmp_path):
        vpath = tmp_path / "v.json"
        v = EncryptedFileVault(vpath, master_key=b"k" * 32)
        v.put("t", "value")
        data = json.loads(vpath.read_text())
        ct = data["entries"]["t"]["ct"]
        data["entries"]["t"]["ct"] = ("A" + ct[1:]) if not ct.startswith("A") else ("B" + ct[1:])
        vpath.write_text(json.dumps(data))
        fresh = EncryptedFileVault(vpath, master_key=b"k" * 32)
        with pytest.raises(VaultError):
            fresh.get("t")

    def test_wrong_key_rejected(self, tmp_path):
        vpath = tmp_path / "v.json"
        EncryptedFileVault(vpath, master_key=b"a" * 32).put("x", "y")
        with pytest.raises(VaultError):
            EncryptedFileVault(vpath, master_key=b"b" * 32).get("x")

    def test_ttl_expiry(self, tmp_path):
        v = EncryptedFileVault(tmp_path / "v.json", master_key=b"k" * 32)
        v.put("short", "s", ttl_ms=50)
        assert v.get("short") == "s"
        time.sleep(0.06)
        assert v.get("short") is None
        assert "short" not in v.list_names()

    def test_env_backend(self, monkeypatch):
        monkeypatch.setenv("APA_SECRET_ERP_TOKEN", "from-env")
        assert EnvVault().get("erp_token") == "from-env"

    def test_c4_literal_spec_forbidden(self):
        vm = VaultManager(EnvVault())
        with pytest.raises(VaultError):
            vm.resolve({"literal": "sk-secret"})

    def test_inject_headers_from_env(self, monkeypatch):
        monkeypatch.setenv("APA_SECRET_ERP_TOKEN", "tok-9")
        vm = VaultManager(EnvVault())
        headers = vm.inject_headers({}, {"vault": "erp_token"})
        assert headers["Authorization"] == "Bearer tok-9"


class TestCredentialInjectionEndToEnd:
    def test_secret_flows_via_vault_not_protocol(self, tmp_path):
        """C4 端到端：机密走 Vault 注入，协议里只有引用名；ERP 收到 Bearer 头。"""
        erp = MockERP(token="real-secret-42")
        port = erp.start()

        vault = EncryptedFileVault(tmp_path / "v.json", master_key=b"k" * 32)
        vault.put("erp_token", "real-secret-42")

        from apa_executors.api_executor import APIExecutor
        from apa_sdk.composite import CompositeExecutor
        from apa_core.rules import RuleBasedAgent

        gw = EmbeddedGateway(SESSION, registry=all_registries(),
                             policy=PolicyConfig(),
                             identities={"executor": EXEC, "agent": AGENT})
        gateway = gw.gateway
        router = CompositeExecutor(EXEC, SESSION)
        api_mod = APIExecutor(EXEC, SESSION,
                              base_url=f"http://127.0.0.1:{port}",
                              vault=vault)
        router.register(("api", "erp"), api_mod)
        agent = RuleBasedAgent(AIPPeer(source=AGENT, session_id=SESSION), [])

        inbox = []
        gw.attach_executor(router, EXEC)
        gw.attach_agent(agent, AGENT)
        # 包装 agent 处理器以捕获协议面帧（断言机密不出现）
        inner = gateway.handlers.get("agent")
        gateway.set_handler("agent",
                            lambda raw: (inbox.append(raw), inner(raw)))
        gw.run()

        m = make_action(SESSION, AGENT, "api.http.post", params={
            "url": f"http://127.0.0.1:{port}/notify",
            "json": {"text": "hi"},
            "auth": {"vault": "erp_token"},
        })
        m.seq = 1
        gateway.deliver("agent", m.to_dict())

        assert len(erp.notifications) == 1
        auth_header = [r for r in erp.requests if r["method"] == "POST"][0]
        # 协议面（agent 收到的帧）不含任何机密值
        blob = json.dumps(inbox, ensure_ascii=False)
        assert "real-secret-42" not in blob
        # 审计凭据扫描干净（引用名不是机密）
        scans = [r["security"]["credential_scan"] for r in gateway.audit.read_all()
                 if r.get("security")]
        assert scans and all(s == "clean" for s in scans)
        erp.stop()


class TestPolicyUpgrade:
    ENTRY = RegistryEntry(name="t", risk="L1")

    def test_deny_pattern_wildcard(self):
        p = PolicyConfig(deny_patterns=["bank.*", "erp.payment.initiate"])
        d, rule = p.evaluate("bank.transfer", self.ENTRY)
        assert d == PolicyDecision.REJECT and rule == "deny_pattern:bank.*"
        d, _ = p.evaluate("erp.payment.initiate", self.ENTRY)
        assert d == PolicyDecision.REJECT

    def test_principal_blacklist(self):
        p = PolicyConfig(principals_deny={"rogue"})
        assert p.evaluate("any.action", self.ENTRY, source="rogue")[0] == PolicyDecision.REJECT
        assert p.evaluate("any.action", self.ENTRY, source="good")[0] == PolicyDecision.PERMIT

    def test_rule_with_source_and_pattern(self):
        p = PolicyConfig(rules=[
            {"name": "flash_only", "action_pattern": "erp.invoice.*",
             "source": "dsh_flash_001", "decision": "reject"}])
        d, _ = p.evaluate("erp.invoice.post", self.ENTRY, source="dsh_flash_001")
        assert d == PolicyDecision.REJECT
        d, _ = p.evaluate("erp.invoice.post", self.ENTRY, source="dsh_pro_001")
        assert d == PolicyDecision.PERMIT


class TestRateLimit:
    def test_per_source_sliding_window(self):
        clock = FakeClock(start_ms=0)
        gw = build(clock=clock, rate_limit_per_minute=3)
        statuses = []
        for seq in range(1, 6):
            m = make_action(SESSION, AGENT, "browser.scroll",
                            params={"direction": "down"}, seq=seq)
            out = gw.gateway.receive("agent", m.to_dict())
            if out[0].type == "action":
                statuses.append(None)      # 放行（转发 executor）
            else:
                statuses.append(out[0].payload.get("code") or
                                out[0].payload.get("status"))
        # 前 3 个转发，第 4/5 被限流
        assert statuses[:3] == [None, None, None]
        assert statuses[3] == "rate_limited" and statuses[4] == "rate_limited"
        # 窗口滑过后恢复放行
        clock.advance(61_000)
        m = make_action(SESSION, AGENT, "browser.scroll",
                        params={"direction": "up"}, seq=6)
        out = gw.gateway.receive("agent", m.to_dict())
        assert out[0].type == "action"


class TestTenantIsolation:
    def test_ws_hello_tenant_mismatch_rejected(self, tmp_path):
        asyncio_run(_tenant_scenario())


async def _tenant_scenario():
    import websockets

    gw = EmbeddedGateway(SESSION, registry=all_registries(),
                         identities={"executor": "ws_ex", "agent": "ws_ag"},
                         tenant_id="corp_abc")
    gw.run()
    from apa_core.ws_gateway import WsGatewayServer
    server = WsGatewayServer(gw.gateway, port=0)
    port = await server.start()
    url = f"ws://127.0.0.1:{port}"

    bad = await websockets.connect(url)
    await bad.send(json.dumps({"type": "hello", "role": "executor",
                               "source": "ws_ex", "tenant": "corp_other"}))
    reply = json.loads(await asyncio.wait_for(bad.recv(), 2))
    assert reply["code"] == "UNAUTHORIZED"

    good = await websockets.connect(url)
    await good.send(json.dumps({"type": "hello", "role": "executor",
                                "source": "ws_ex", "tenant": "corp_abc"}))
    ack = json.loads(await asyncio.wait_for(good.recv(), 2))
    assert ack["type"] == "hello"
    await good.close()
    await server.close()


def asyncio_run(coro):
    import asyncio
    asyncio.run(coro)


class TestAnalytics:
    def test_summary_math(self, tmp_path):
        jpath = tmp_path / "a.jsonl"
        journal = SessionJournal(jpath)
        gw = EmbeddedGateway(SESSION, registry=all_registries(),
                             identities={"executor": EXEC, "agent": AGENT},
                             journal=journal, tenant_id="corp_x")
        gw.run()
        # 两个动作：一成一败（用 navigate 触发 expect 无妨）
        m1 = make_action(SESSION, AGENT, "browser.navigate",
                         params={"url": "https://x"}, seq=1)
        out1 = gw.gateway.receive("agent", m1.to_dict())
        r_ok = make_result(SESSION, EXEC, "ok", in_reply_to=out1[0].id)
        r_ok.seq = 1
        gw.gateway.receive("executor", r_ok.to_dict())
        m2 = make_action(SESSION, AGENT, "session.complete",
                         params={"outcome": "success"}, seq=2)
        gw.gateway.receive("agent", m2.to_dict())  # COMPLETED → 后续动作被拒

        data = summarize([str(jpath)])
        assert data["sessions"]["total"] >= 1
        assert data["actions"]["sent"] >= 1
        assert data["actions"]["ok"] >= 1
        rep = report(data)
        assert "APA Analytics" in rep and "success=" in rep

    def test_tenant_filter(self, tmp_path):
        jpath = tmp_path / "b.jsonl"
        journal = SessionJournal(jpath)
        gw = EmbeddedGateway(SESSION, registry=all_registries(),
                             identities={"executor": EXEC, "agent": AGENT},
                             journal=journal, tenant_id="corp_x")
        gw.run()
        m = make_action(SESSION, AGENT, "session.complete",
                        params={"outcome": "success"}, seq=1)
        gw.gateway.receive("agent", m.to_dict())
        data = summarize([str(jpath)], tenant="corp_y")  # 不同租户 → 空
        assert data["sessions"]["total"] == 0
        data2 = summarize([str(jpath)], tenant="corp_x")
        assert data2["sessions"]["total"] >= 1


class TestMockERP:
    def test_endpoints_and_auth(self):
        erp = MockERP(token="secret-t", seed_orders=[
            {"id": "O1", "amount": 100}, {"id": "O2", "amount": 200}])
        port = erp.start()
        import httpx
        base = f"http://127.0.0.1:{port}"
        # 无 token → 401
        assert httpx.post(f"{base}/orders/O1/approve",
                          json={"approver": "apa"}).status_code == 401
        headers = {"Authorization": "Bearer secret-t"}
        pending = httpx.get(f"{base}/orders", headers=headers).json()["items"]
        assert {o["id"] for o in pending} == {"O1", "O2"}
        r = httpx.post(f"{base}/orders/O1/approve", json={"approver": "apa_system"},
                       headers=headers)
        assert r.json()["status"] == "approved"
        inv = httpx.post(f"{base}/invoices", json={"invoice_no": "I-1", "total": 5},
                         headers=headers).json()
        assert inv["id"].startswith("INV-")
        assert erp.orders["O1"]["approver"] == "apa_system"
        assert len(erp.requests) >= 4
        erp.stop()