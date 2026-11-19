# -*- coding: utf-8 -*-
"""ComfyUI-Vanco-Suite —— Vanco 分镜编排引擎（ComfyUI + MiniMax-H3）。"""

__author__ = "Vanco"
__license__ = "GPL-3.0-or-later"
__version__ = "1.0.0"

"""ComfyUI-Vanco-Suite：把三块自建节点合到一个包，内部各自独立，不做代码改写。

结构：
    vanco_studio/ 模型加载 / LoRA / 素材面板 / 参数盒 / 分段引擎 / 两个超分
    vanco_prompt/ 提示词管理器

原理：把三个子目录塞进 sys.path，再按它们原本的包名导入，最后合并注册表。
所以子包里的相对导入、绝对导入都不用改。
"""
import importlib
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SUBS = ["vanco_studio", "vanco_prompt"]

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
_loaded = []

for _sub in SUBS:
    _p = os.path.join(BASE, _sub)
    if not os.path.isdir(_p):
        print("[Vanco Suite] 跳过（目录不存在）：", _sub)
        continue
    for _d in (_p, BASE):
        if os.path.isdir(_d) and _d not in sys.path:
            sys.path.insert(0, _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)
    try:
        _mod = importlib.import_module("." + _sub, __name__)
        NODE_CLASS_MAPPINGS.update(getattr(_mod, "NODE_CLASS_MAPPINGS", {}) or {})
        NODE_DISPLAY_NAME_MAPPINGS.update(getattr(_mod, "NODE_DISPLAY_NAME_MAPPINGS", {}) or {})
        _loaded.append(_sub)
    except Exception as _e:
        import traceback
        print("[Vanco Suite] 子包加载失败：", _sub, _e)
        traceback.print_exc()

# 前端：web 目录已手工整理好
WEB_DIRECTORY = "./web"

print("[Vanco Suite] 已注册节点 %d 个，子包：%s" % (len(NODE_CLASS_MAPPINGS), ", ".join(_loaded) or "无"))
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
