# -*- coding: utf-8 -*-
"""Vanco 设置台：把引擎上的一大堆开关拆成三个小节点，用一根 JSON 线传进去。

设计原则
- 引擎只留「生成相关」的少数参数
- 输出 / 重跑 / 质检 分成三个节点，各自 5–7 个开关
- 不接任何设置节点时，引擎用内置默认值（行为不变）
"""
import json


def _emit(data):
    return (json.dumps(data, ensure_ascii=False),)


class VancoOutSet:
    """输出与内存设置。"""

    CATEGORY = "Vanco/设置"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("输出设置",)
    DESCRIPTION = "成片存哪、存几份、是否省内存。接到引擎的「输出设置」输入。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "剧本名": ("STRING", {"default": "未命名剧本",
                                       "tooltip": "输出归档到 视频合集/Vanco/多段导演台/<剧本名>/"}),
                "保存分段": ("BOOLEAN", {"default": True, "tooltip": "每段单独落盘 mp4 + json，便于逐段查看与重跑"}),
                "成片只存画布": ("BOOLEAN", {"default": True,
                                             "tooltip": "开：段间淡化在内存完成，只由画布出唯一成片（带元数据、只编码一次）"}),
                "引擎也存成片": ("BOOLEAN", {"default": False,
                                             "tooltip": "关：成片只由画布 SaveVideo 保存，避免存两份"}),
                "省内存模式": ("BOOLEAN", {"default": False,
                                           "tooltip": "长片（>8段）建议开：不把全片帧留在内存，代价是画布不再输出成片"}),
                "段间清理": (["关", "只清缓存", "卸载模型+清缓存"], {"default": "关",
                                                                     "tooltip": "每段结束后释放显存"}),
            }
        }

    def build(self, 剧本名, 保存分段, 成片只存画布, 引擎也存成片, 省内存模式, 段间清理):
        return _emit({"剧本名": 剧本名, "保存分段": 保存分段, "成片只存画布": 成片只存画布,
                      "引擎也存成片": 引擎也存成片, "省内存模式": 省内存模式, "段间清理": 段间清理})


class VancoRunSet:
    """重跑设置。"""

    CATEGORY = "Vanco/设置"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("重跑设置",)
    DESCRIPTION = "只跑第N段 / 级联重跑 / 首尾帧精确重跑。接到引擎的「重跑设置」输入。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "只跑第N段": ("INT", {"default": 0, "min": 0, "max": 999,
                                      "tooltip": "0=全跑；>0 只重跑这一段，前面的分段自动复用"}),
                "下游处理": (["只跑这一段", "级联重跑"], {"default": "只跑这一段",
                                                           "tooltip": "级联重跑：第 N+1、N+2… 若写「续接=上一段」则跟着重跑"}),
                "重跑后交给画布": ("BOOLEAN", {"default": False,
                                               "tooltip": "关=阻断画布输出（快、无损）；开=解码整片交给画布"}),
                "上游已变时": (["停下提醒", "照跑不管"], {"default": "停下提醒"}),
                "精确重跑": (["关", "首尾帧"], {"default": "关",
                                                "tooltip": "重跑第N段时，用第N+1段的首帧当终点，避免牵连下游"}),
            }
        }

    def build(self, 只跑第N段, 下游处理, 重跑后交给画布, 上游已变时, 精确重跑):
        return _emit({"只跑第N段": 只跑第N段, "下游处理": 下游处理, "重跑后交给画布": 重跑后交给画布,
                      "上游已变时": 上游已变时, "精确重跑": 精确重跑})


class VancoQcSet:
    """衔接与质检设置。"""

    CATEGORY = "Vanco/设置"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("质检设置",)
    DESCRIPTION = "段间怎么接、色彩是否归一、要不要检测人物与空镜。接到引擎的「质检设置」输入。"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "硬接模式": (["关", "每段锚定上段尾帧"], {"default": "关",
                                                          "tooltip": "开=每段用 FL2VA 的 first_frame 硬锚上一段尾帧（构图锁死）"}),
                "接缝处理": (["关", "微淡化", "微淡化+逐段色彩归一"], {"default": "关",
                                                                     "tooltip": "微淡化=段间混合 3 帧；+逐段色彩归一=每段对齐第一段"}),
                "参考尾帧数": ("INT", {"default": 1, "min": 1, "max": 64, "tooltip": "大于1=额外喂参考视频（自动吸附 5/22/39/56）；1=只喂最后一帧"}),
                "尾帧取样": (["最后一帧", "倒数第2帧"], {"default": "最后一帧"}),
                "人物检测": ("BOOLEAN", {"default": False,
                                         "tooltip": "检测开头帧人数是否符合剧本「角色=」的数量；只报告"}),
                "检测帧数": ("INT", {"default": 12, "min": 1, "max": 48,
                                     "tooltip": "只检查开头这么多帧（12 帧 ≈ 0.5 秒）"}),
                "自动裁空镜": ("BOOLEAN", {"default": False,
                                           "tooltip": "开头无人而后出现人时，自动裁掉前面的空镜帧（需开启人物检测）"}),
            }
        }

    def build(self, 硬接模式, 接缝处理, 参考尾帧数, 尾帧取样, 人物检测, 检测帧数, 自动裁空镜):
        return _emit({"硬接模式": 硬接模式, "接缝处理": 接缝处理, "参考尾帧数": 参考尾帧数,
                      "尾帧取样": 尾帧取样, "人物检测": 人物检测, "检测帧数": 检测帧数,
                      "自动裁空镜": 自动裁空镜})


NODE_CLASS_MAPPINGS = {
    "VancoOutSet": VancoOutSet,
    "VancoRunSet": VancoRunSet,
    "VancoQcSet": VancoQcSet,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "VancoOutSet": "📦 输出设置",
    "VancoRunSet": "🔁 重跑设置",
    "VancoQcSet": "🔍 衔接与质检",
}
