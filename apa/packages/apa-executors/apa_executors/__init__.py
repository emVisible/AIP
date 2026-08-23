"""apa-executors — 标准执行器（设计文档 §5）。"""

from .api_executor import APIExecutor
from .browser_executor import BrowserExecutor, PageOps, PlaywrightPageOps, open_browser
from .desktop_executor import (
    DesktopBackend,
    DesktopExecutor,
    MockDesktopBackend,
    OsascriptBackend,
)
from .data_executor import DataExecutor
from .document_executor import DocumentExecutor
from .excel_executor import ExcelExecutor

__all__ = [
    "APIExecutor",
    "BrowserExecutor",
    "DesktopBackend",
    "DesktopExecutor",
    "MacOSInputEngine",
    "MacOSWindowManager",
    "DataExecutor",
    "DocumentExecutor",
    "ExcelExecutor",
    "MockDesktopBackend",
    "OsascriptBackend",
    "PageOps",
    "PlaywrightPageOps",
    "open_browser",
]

__version__ = "0.3.0"