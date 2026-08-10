"""
路径解析核心 — 兼容 PyInstaller 打包与 dev 运行

打包(onefile)后 __file__ 指向临时 _MEI 解压目录，退出即删，
因此数据(DB/backups)必须放 EXE 所在目录，资源(templates/static/fonts)从 _MEIPASS 读。
"""
import os
import sys


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def app_base_dir() -> str:
    """DB + backups 存放处（可写）。frozen → EXE 同目录；dev → 源码目录。"""
    if is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(rel: str) -> str:
    """打包的只读资源（templates/static/fonts）。frozen → _MEIPASS；dev → 源码目录。"""
    if is_frozen():
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(app_base_dir(), rel)
