"""Benchmark task (SPEC App. E): auto-login ERP -> query order -> modify
status -> submit -> fetch result.

Each step delivers a semantic event to the decision engine and expects one
decision. In simulation mode every model produces the same (scripted)
decision — success rate is equalized by construction, so the benchmark
measures CONTEXT EFFICIENCY and COST, not reasoning quality.
"""
STEPS = [
    {
        "event": "login.form.detected",
        "data": {"fields": ["username", "password"], "autofill": True},
        "decision": "fill_login",
    },
    {
        "event": "login.submitted",
        "data": {"ok": True},
        "decision": "wait_dashboard",
    },
    {
        "event": "dashboard.loaded",
        "data": {"menus": ["orders", "invoices", "reports"]},
        "decision": "open_orders",
    },
    {
        "event": "orders.list.loaded",
        "data": {"count": 120, "page": 1},
        "decision": "search_order",
    },
    {
        "event": "orders.search.results",
        "data": {"order_id": "A12345", "matched": True},
        "decision": "open_order",
    },
    {
        "event": "order.detail.loaded",
        "data": {
            "order_id": "A12345",
            "status": "pending",
            "total": 299.0,
            "customer": "c_001",
            "fields": ["status", "total", "customer"],
        },
        "decision": "decide_status_change",
    },
    {
        "event": "order.status.editable",
        "data": {"target": "approved"},
        "decision": "set_status",
    },
    {
        "event": "order.form.submitted",
        "data": {"ok": True},
        "decision": "fetch_result",
    },
    {
        "event": "result.page.loaded",
        "data": {"result": "success", "doc_id": "D-9"},
        "decision": "extract_result",
    },
]

# Routing classes for the cascade models (SPEC §9.9, §11.2).
RULES = {"fill_login", "wait_dashboard", "set_status", "fetch_result", "extract_result"}
SMALL = {"open_orders", "search_order", "open_order"}
LLM = {"decide_status_change"}