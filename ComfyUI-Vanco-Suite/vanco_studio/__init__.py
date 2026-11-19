import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from .nodes import NODE_CLASS_MAPPINGS as M1, NODE_DISPLAY_NAME_MAPPINGS as D1  # noqa: E402
try:
    from .engine import NODE_CLASS_MAPPINGS as M2, NODE_DISPLAY_NAME_MAPPINGS as D2
    NODE_CLASS_MAPPINGS = {**M1, **M2}
    NODE_DISPLAY_NAME_MAPPINGS = {**D1, **D2}
except Exception as e:  # 引擎还没调通时，至少保证前两个节点可用
    print("[Vanco Studio] 分段引擎未加载：", e)
    NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = M1, D1

# 自研 LoRA 加载器：同名覆盖上游实现（id 保持 VancoH3LoraLoader，旧工作流不用改）
try:
    from .vanco_lora import NODE_CLASS_MAPPINGS as M3, NODE_DISPLAY_NAME_MAPPINGS as D3
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **M3}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **D3}
    print("[Vanco Studio] 已挂载自研 LoRA 加载器（24 槽）")
except Exception as e:
    print("[Vanco Studio] 自研 LoRA 加载器未加载，继续用上游版：", e)

WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
print("[Vanco Studio] 已加载：素材面板 + 参数盒")

# 自研 H3 模型加载器：同名覆盖上游实现
try:
    from .vanco_model import NODE_CLASS_MAPPINGS as M4, NODE_DISPLAY_NAME_MAPPINGS as D4
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **M4}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **D4}
    print("[Vanco Studio] 已挂载自研 H3 模型加载器")
except Exception as e:
    print("[Vanco Studio] 自研 H3 模型加载器未加载，继续用上游版：", e)

# 设置台：输出 / 重跑 / 质检 三个小节点
try:
    from .vanco_settings import NODE_CLASS_MAPPINGS as M5, NODE_DISPLAY_NAME_MAPPINGS as D5
    NODE_CLASS_MAPPINGS = {**NODE_CLASS_MAPPINGS, **M5}
    NODE_DISPLAY_NAME_MAPPINGS = {**NODE_DISPLAY_NAME_MAPPINGS, **D5}
    print("[Vanco Studio] 已挂载设置台（输出/重跑/质检）")
except Exception as e:
    print("[Vanco Studio] 设置台未加载：", e)
