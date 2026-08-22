# apa-executors

标准执行器（设计文档 §5）：

- `browser_executor.py` — `BrowserExecutor`（Playwright），动作 navigate/click/input/extract/
  select_option/wait_element/scroll/take_screenshot；target 解析优先级
  data-apa-id → aria-label/role+text → CSS
- `api_executor.py` — `APIExecutor`（httpx），api.http.* + erp.order.* 演示动作

安装（可选依赖）：

```bash
pip install "apa-executors[browser,api]"
```

依赖：`apa-core`、`apa-sdk-python`、`aip`。