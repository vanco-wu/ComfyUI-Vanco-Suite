# -*- coding: utf-8 -*-
"""Vanco LoRA 堆栈加载器（动态清单，不限槽位）。

与上游实现完全解耦，只用 ComfyUI 官方 API：
    comfy.sd.load_lora_for_models / comfy.utils.load_torch_file

节点 id 保持 `VancoH3LoraLoader`，输入顺序与旧版逐位一致，
所以已有工作流（16 个）不需要改任何连线。
"""
import os
import folder_paths

SLOT_COUNT = 24
NONE = "none"


def _lora_list():
    """LoRA 下拉选项：none + models/loras 下的全部文件。"""
    try:
        items = folder_paths.get_filename_list("loras") or []
    except Exception:
        items = []
    return [NONE] + list(items)


def _parse_stack(raw):
    """解析面板写入的 JSON 清单：[{"name":..., "strength":...}, ...]"""
    import json
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for it in data:
        if isinstance(it, dict):
            if it.get("enabled") is False:
                continue
            out.append((str(it.get("name") or ""), float(it.get("strength") or 0.0)))
        elif isinstance(it, (list, tuple)) and len(it) >= 2:
            out.append((str(it[0]), float(it[1] or 0.0)))
    return out


def _finish(model, clip, bundle_in, stack, applied):
    """把清单写进 bundle 并返回三元组。"""
    bundle_out = None
    if bundle_in is not None:
        try:
            from dataclasses import replace
            bundle_out = replace(bundle_in, loras=tuple(stack))
        except Exception as e:
            print("[Vanco LoRA] 写入 bundle 失败，仅外部 MODEL 生效:", e)
            bundle_out = bundle_in
    return (model, clip, bundle_out)


def _is_none(name):
    return str(name or "").strip().lower() in ("", "none", "无", "关闭")


class VancoLoraLoader24:
    """把最多 24 个 LoRA 依次叠加到 MODEL / CLIP。

    - 只接 model：等价于官方 LoraLoaderModelOnly
    - 同时接 clip：LoRA 的文本编码器部分也会生效
    - 接 bundle：把同一份清单写进 bundle，供导演台等内部采样节点使用
    """

    CATEGORY = "Vanco/LoRA"
    FUNCTION = "load"
    RETURN_TYPES = ("MODEL", "CLIP", "MINIMAX_H3_BUNDLE")
    RETURN_NAMES = ("model", "clip", "h3_bundle")
    DESCRIPTION = (
        "可无限追加的 LoRA 叠加。可独立用于任意工作流（Flux / Wan / H3 / SDXL 等）；"
        "接 h3_bundle 时会把清单写入 bundle，导演台内部采样才会吃到 LoRA。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        loras = _lora_list()
        optional = {
            "model": ("MODEL", {"tooltip": "主模型。至少要接这个。"}),
            "clip": ("CLIP", {"tooltip": "可选。LoRA 训练了文本编码器时才需要接。"}),
        }
        optional["lora_stack"] = (
            "STRING",
            {"default": "", "multiline": False,
             "tooltip": "动态 LoRA 清单（JSON）。由面板自动维护，不要手改。"},
        )
        optional["bundle"] = (
            "MINIMAX_H3_BUNDLE",
            {"tooltip": "可选：接 H3 模型加载器的 h3_bundle，把 LoRA 清单写进 bundle。"},
        )
        return {"required": {}, "optional": optional}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return str(kwargs.get("lora_stack", ""))

    def load(self, model=None, clip=None, **kwargs):
        if model is None:
            raise ValueError("Vanco LoRA 加载器：请至少把 MODEL 接到 model 输入。")

        try:
            import comfy.sd as sd
            import comfy.utils as cu
        except Exception as e:
            raise RuntimeError("无法导入 comfy.sd / comfy.utils：%s" % e)

        # ① 优先读动态清单（面板维护，无限槽位）
        stack = []
        applied = 0
        dyn = _parse_stack(kwargs.get("lora_stack"))
        if dyn:
            for name, strength in dyn:
                if _is_none(name) or not strength:
                    continue
                try:
                    if folder_paths.get_full_path("loras", name) is None:
                        print("[Vanco LoRA] 跳过缺失文件:", name)
                        continue
                    lora_sd = cu.load_torch_file(
                        folder_paths.get_full_path("loras", name), safe_load=True)
                    model, clip = sd.load_lora_for_models(model, clip, lora_sd, strength, strength)
                    stack.append((name, strength))
                    applied += 1
                except Exception as e:
                    print("[Vanco LoRA] 应用失败（已跳过）:", name, e)
            print("[Vanco LoRA] 动态清单：已应用 %d 个 LoRA" % applied)
            return _finish(model, clip, kwargs.get("bundle"), stack, applied)

        # ② 回落：旧的 24 固定槽
        for i in range(1, SLOT_COUNT + 1):
            name = str(kwargs.get("lora_%d" % i) or NONE)
            if _is_none(name):
                continue
            # 本机没有这个文件就跳过，避免整条工作流中断
            try:
                if folder_paths.get_full_path("loras", name) is None:
                    print("[Vanco LoRA] 跳过缺失文件:", name)
                    continue
            except Exception:
                pass
            strength = float(kwargs.get("lora_%d_strength" % i) or 0.0)
            if strength == 0.0:
                continue
            try:
                lora_sd = cu.load_torch_file(
                    folder_paths.get_full_path("loras", name), safe_load=True)
                model, clip = sd.load_lora_for_models(model, clip, lora_sd, strength, strength)
                stack.append((name, strength))
                applied += 1
            except Exception as e:
                print("[Vanco LoRA] 应用失败（已跳过）:", name, e)

        print("[Vanco LoRA] 固定槽：已应用 %d 个 LoRA" % applied)
        return _finish(model, clip, kwargs.get("bundle"), stack, applied)


NODE_CLASS_MAPPINGS = {"VancoH3LoraLoader": VancoLoraLoader24}
NODE_DISPLAY_NAME_MAPPINGS = {"VancoH3LoraLoader": "Vanco LoRA 加载器（无限槽）"}
