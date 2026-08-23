# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：冻结 APA 常驻服务（uvicorn + FastAPI 全家桶）。

路径基准：SPECPATH = frontend/ 目录。
"""
import os

SPEC_DIR = os.path.dirname(SPEC) if "SPEC" in dir() else os.getcwd()
APA_DIR = os.path.abspath(os.path.join(SPEC_DIR, ".."))
AIP_ROOT = os.path.abspath(os.path.join(APA_DIR, ".."))

a = Analysis(
    [os.path.join(SPEC_DIR, "electron", "apa_server_entry.py")],
    pathex=[
        os.path.join(APA_DIR, "packages", "apa-core"),
        os.path.join(APA_DIR, "packages", "apa-executors"),
        os.path.join(APA_DIR, "packages", "apa-sdk-python"),
        os.path.join(AIP_ROOT, "sdk", "python"),
    ],
    binaries=[],
    datas=[
        # 资源打进 bundle：冻结态 default_registries()/templates 从
        # sys._MEIPASS 解析（COLLECT 下 _MEIPASS = _internal 目录）
        (os.path.join(APA_DIR, "registries"), "registries"),
        (os.path.join(APA_DIR, "templates"), "templates"),
    ],
    hiddenimports=[
        # uvicorn 动态导入链
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.middleware.proxy_headers",
        # 执行器可选依赖（冻结进二进制）
        "openpyxl",
        "httpx",
        "yaml",
        "jsonschema",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="apa_server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="apa_server",
)