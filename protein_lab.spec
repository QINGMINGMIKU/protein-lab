# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir 打包配置 — Windows EXE / macOS 二进制共用。

onedir（非 onefile）：免启动解压、杀毒误报低、进程冷启动 <1s。
产物是 dist/protein_lab/ 目录，CI 里压缩为 zip 分发。
构建：pyinstaller protein_lab.spec --noconfirm
"""
datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("fonts", "fonts"),                      # 打包 Noto Sans SC（OFL）
]
# 惰性 import 的模块，PyInstaller 静态分析看不到，必须显式声明：
#   mcp_server / fonts — app.py 函数体内 import；pandas/logomaker/matplotlib — 路由内惰性 import
hiddenimports = [
    "mcp_server",
    "fonts",
    "paths",
    "pandas",
    "logomaker",
    "matplotlib",
    "matplotlib.backends.backend_agg",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,                    # onedir：二进制交给 COLLECT，不进 EXE
    name="protein_lab",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                               # 避免压缩伪报毒，体积影响可忽略
    console=True,                            # 服务日志 + MCP stdio 都需要 stdout
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="protein_lab",
)
