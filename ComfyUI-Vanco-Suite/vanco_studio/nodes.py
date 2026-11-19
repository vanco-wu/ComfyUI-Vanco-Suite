# -*- coding: utf-8 -*-
"""Vanco Studio · 素材面板 + 参数盒（自建，不依赖第三方节点包）"""
import json
import os

import numpy as np
import torch
from PIL import Image, ImageOps

import folder_paths

CAT = "Vanco/核心"


def _load_image(path):
    p = path
    if not os.path.isfile(p):
        cand = os.path.join(folder_paths.get_input_directory(), path)
        if os.path.isfile(cand):
            p = cand
        else:
            return None
    img = Image.open(p)
    img = ImageOps.exif_transpose(img).convert("RGB")
    return img


class VancoAssetGrid:
    """素材面板：一个 JSON 列表，前端画成三列网格；输出 IMAGE 批次 + 名字列表。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "assets_json": ("STRING", {"default": "[]", "multiline": True}),
                "缺图处理": (["跳过", "报错"], {"default": "跳过"}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "STRING", "INT")
    RETURN_NAMES = ("图片批次", "名字列表", "张数")
    FUNCTION = "run"
    CATEGORY = CAT
    DESCRIPTION = "多图上传面板：顺序即 <Picture 1..N>，可增删，空行自动跳过。"

    def run(self, assets_json, 缺图处理="跳过", unique_id=None):
        try:
            items = json.loads(assets_json or "[]")
        except Exception:
            items = []
        imgs, names = [], []
        for it in items:
            f = it.get("file") or ""
            if not f:
                continue
            im = _load_image(f)
            if im is None:
                msg = "[Vanco] 素材加载失败：%s" % f
                if 缺图处理 == "报错":
                    raise RuntimeError(msg)
                print(msg)
                continue
            imgs.append(im)
            names.append(it.get("name") or os.path.basename(f))
        if not imgs:
            blank = Image.new("RGB", (64, 64), (0, 0, 0))
            return (torch.zeros((1, 64, 64, 3)), "", 0)
        w, h = imgs[0].size
        arr = [np.asarray(im.resize((w, h), Image.LANCZOS)).astype(np.float32) / 255.0 for im in imgs]
        batch = torch.from_numpy(np.stack(arr, 0))
        return (batch, " / ".join(names), len(imgs))


class VancoParamBox:
    """参数盒：比例 + 百万像素 → 宽高；每段秒数 → 帧（对齐 17k+5）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "画幅比例": (["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"], {"default": "16:9"}),
                "百万像素": ("FLOAT", {"default": 0.6, "min": 0.1, "max": 3.6, "step": 0.05}),
                "每段秒数": ("FLOAT", {"default": 8.0, "min": 1.0, "max": 20.0, "step": 0.5}),
                "对齐倍数": ("INT", {"default": 32, "min": 8, "max": 128, "step": 8}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT", "FLOAT")
    RETURN_NAMES = ("宽", "高", "帧数", "秒数")
    FUNCTION = "run"
    CATEGORY = CAT
    DESCRIPTION = "选比例和百万像素就出宽高；填秒数自动换算帧并对齐 17k+5 网格。"

    def run(self, 画幅比例="16:9", 百万像素=0.6, 每段秒数=8.0, 对齐倍数=32):
        rw, rh = {"16:9": (16, 9), "9:16": (9, 16), "4:3": (4, 3),
                  "3:4": (3, 4), "1:1": (1, 1), "21:9": (21, 9)}[画幅比例]
        total = 百万像素 * 1024 * 1024
        scale = (total / (rw * rh)) ** 0.5
        w = max(32, int(round(rw * scale / 对齐倍数)) * 对齐倍数)
        h = max(32, int(round(rh * scale / 对齐倍数)) * 对齐倍数)
        n = max(5, int(round(每段秒数 * 24)))
        while n % 17 != 5:
            n += 1
        return (w, h, n, n / 24.0)


NODE_CLASS_MAPPINGS = {
    "VancoAssetGrid": VancoAssetGrid,
    "VancoParamBox": VancoParamBox,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "VancoAssetGrid": "★ 素材面板（多图上传）",
    "VancoParamBox": "★ 参数盒（比例/像素/秒）",
}
