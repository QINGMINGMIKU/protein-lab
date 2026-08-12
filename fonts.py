"""
CJK 字体解析 + matplotlib 中文配置

打包用 Noto Sans SC（OFL 开源，可随公开仓库再分发），dev 下回退到
旧跨工作区 simhei.ttf 或系统字体（Windows SimHei / macOS PingFang）。
"""
import os

from paths import app_base_dir, resource_path


def find_cjk_font() -> str | None:
    """返回第一个可用的 CJK 字体路径，找不到返回 None。"""
    candidates = [
        resource_path("fonts/NotoSansSC-Regular.otf"),          # 打包的 Noto（dev+EXE 都有）
        os.path.join(app_base_dir(), "..", "fonts", "simhei.ttf"),  # 旧 dev 回退（跨工作区）
        "C:/Windows/Fonts/simhei.ttf",                          # Windows 系统字体
        "C:/Windows/Fonts/msyh.ttc",
        "/System/Library/Fonts/PingFang.ttc",                   # macOS 系统字体
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
    ]
    return next((p for p in candidates if p and os.path.exists(p)), None)


def find_cjk_font_bold() -> str | None:
    """同 family 的 Bold 变体。随 Regular 一起打进 fonts/（OFL），找不到返回 None。

    没有 Bold 变体时 matplotlib 无法合成粗体——请求 fontweight="bold" 会回退
    400 并打印 "Failed to find font weight bold" 告警。有则注册后粗体真正渲染。
    """
    candidates = [
        resource_path("fonts/NotoSansSC-Bold.otf"),             # 打包的 Noto Bold（可选）
        "C:/Windows/Fonts/msyhbd.ttc",                          # 系统 YaHei Bold
    ]
    return next((p for p in candidates if p and os.path.exists(p)), None)


def setup_matplotlib_cjk() -> str | None:
    """配置 matplotlib 使用 CJK 字体。须在 import pyplot 之前调用（内部已 use('Agg')）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    font_path = find_cjk_font()
    if font_path:
        try:
            font_manager.fontManager.addfont(font_path)
            name = font_manager.FontProperties(fname=font_path).get_name()
            plt.rcParams["font.family"] = name
        except Exception:
            pass
        # Bold 变体：仅当与主字体同 family 才注册（否则 matplotlib 权重匹配不上）。
        # 单面 OTF 可 addfont；.ttc 集合常失败，静默忽略 = 回到无粗体现状。
        try:
            bold_path = find_cjk_font_bold()
            if bold_path:
                bname = font_manager.FontProperties(fname=bold_path).get_name()
                if bname == name:
                    font_manager.fontManager.addfont(bold_path)
        except Exception:
            pass
    plt.rcParams["axes.unicode_minus"] = False
    return font_path
