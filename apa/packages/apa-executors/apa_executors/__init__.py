"""apa-executors — 标准执行器（设计文档 §5）。"""

from .api_executor import APIExecutor
from .browser_executor import BrowserExecutor, PageOps, PlaywrightPageOps, open_browser

__all__ = [
    "APIExecutor",
    "BrowserExecutor",
    "PageOps",
    "PlaywrightPageOps",
    "open_browser",
]

__version__ = "0.1.0"