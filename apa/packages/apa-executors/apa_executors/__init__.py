"""apa-executors — 标准执行器（设计文档 §5）。"""

from .api_executor import APIExecutor
from .browser_executor import BrowserExecutor, PageOps, PlaywrightPageOps, open_browser
from .desktop_executor import (
    DesktopBackend,
    DesktopExecutor,
    MockDesktopBackend,
    OsascriptBackend,
)
from .document_executor import DocumentExecutor

__all__ = [
    "APIExecutor",
    "BrowserExecutor",
    "DesktopBackend",
    "DesktopExecutor",
    "MacOSInputEngine",
    "MacOSWindowManager",
    "DocumentExecutor",
    "MockDesktopBackend",
    "OsascriptBackend",
    "PageOps",
    "PlaywrightPageOps",
    "open_browser",
]

__version__ = "0.3.0"