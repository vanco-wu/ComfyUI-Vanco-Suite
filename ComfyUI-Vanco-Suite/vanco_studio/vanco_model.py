# -*- coding: utf-8 -*-
"""Vanco H3 集成模型加载器（双主干 + 文本编码器 + 双 VAE → bundle）。

只用 ComfyUI 官方 API：
    comfy.sd.load_diffusion_model / load_lora_for_models
    nodes.CLIPLoader / nodes.VAELoader

节点 id 保持 `VancoH3ModelLoader`，7 个控件顺序与旧版逐位一致，
已有工作流的 widgets_values 不会错位。
"""
from dataclasses import dataclass, field, replace
from typing import Any

import folder_paths

NONE = "none"
POLICY = ("自动回落", "按所选加载")
ATTN_OFF = "关闭"
ATTN_AUTO = "自动（Sage 优先）"
ATTN_CHOICES = [ATTN_AUTO, ATTN_OFF, "SageAttention", "SageAttention3（Blackwell）", "FlashAttention"]


def _names(folders):
    out = []
    for f in folders:
        try:
            out.extend(folder_paths.get_filename_list(f) or [])
        except Exception:
            pass
    seen, res = set(), []
    for n in out:
        if n not in seen:
            seen.add(n)
            res.append(n)
    return res or [NONE]


def _ref_capable(name: str) -> bool:
    s = str(name).lower()
    return any(k in s for k in ("ref2v", "reference", "fused", "hybrid", "refdelta"))


@dataclass
class VancoH3Bundle:
    """H3 双主干包：按需加载，LoRA 清单在解析时统一叠加。"""

    fl2va_model: str
    ref2va_model: str
    clip_name: str
    video_vae_name: str
    audio_vae_name: str
    clip: Any = None
    video_vae: Any = None
    audio_vae: Any = None
    policy: str = POLICY[0]
    attn: str = ATTN_OFF
    loras: tuple = ()
    _cache: dict = field(default_factory=dict, repr=False)

    def _path(self, kind: str) -> str:
        if kind == "ref2va" and self.ref2va_model and str(self.ref2va_model).lower() not in ("none", ""):
            return self.ref2va_model
        return self.fl2va_model

    def model_for(self, kind: str = "ref2va"):
        kind = "ref2va" if kind == "ref2va" else "fl2va"
        name = self._path(kind)
        key = (name, self.loras)
        if key in self._cache:
            return self._cache[key]

        import comfy.sd as sd
        import comfy.utils as cu
        path = folder_paths.get_full_path("diffusion_models", name) or \
               folder_paths.get_full_path("unet", name)
        if path is None:
            raise ValueError("找不到模型文件：%s" % name)
        model = sd.load_diffusion_model(path)

        # 叠加 LoRA（外部 MODEL 已打过，但内部采样走这里，必须重复施加）
        for lora_name, strength in (self.loras or ()):
            try:
                lp = folder_paths.get_full_path("loras", lora_name)
                if lp is None or not strength:
                    continue
                model, _ = sd.load_lora_for_models(model, None, cu.load_torch_file(lp, safe_load=True),
                                                   float(strength), 0.0)
            except Exception as e:
                print("[Vanco H3] bundle 内 LoRA 施加失败（跳过）:", lora_name, e)

        self._cache = {key: model}      # 只留最新一条，避免吃显存
        return model


class _LazyModel:
    """把 bundle 当成普通 MODEL 用：真正解析推迟到下游取属性时。"""

    def __init__(self, bundle: VancoH3Bundle, kind: str = "ref2va"):
        object.__setattr__(self, "_bundle", bundle)
        object.__setattr__(self, "_kind", kind if kind in ("ref2va", "fl2va") else "ref2va")
        object.__setattr__(self, "_resolved", None)

    def _r(self):
        m = object.__getattribute__(self, "_resolved")
        if m is None:
            b = object.__getattribute__(self, "_bundle")
            m = b.model_for(object.__getattribute__(self, "_kind"))
            object.__setattr__(self, "_resolved", m)
        return m

    def __getattr__(self, name):
        return getattr(self._r(), name)

    def __setattr__(self, name, value):
        if name in ("_bundle", "_kind", "_resolved"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._r(), name, value)

    def __repr__(self):
        return "<VancoH3LazyModel kind=%s>" % object.__getattribute__(self, "_kind")


class VancoH3ModelLoaderOwn:
    CATEGORY = "Vanco/模型"
    FUNCTION = "load"
    RETURN_TYPES = ("MINIMAX_H3_BUNDLE", "MODEL", "CLIP", "VAE", "VAE")
    RETURN_NAMES = ("h3_bundle", "model", "clip", "video_vae", "audio_vae")
    DESCRIPTION = "加载 H3 双主干、文本编码器与视频/音频双 VAE，输出 bundle（不含 LoRA）。"

    @classmethod
    def INPUT_TYPES(cls):
        models = _names(("diffusion_models", "unet"))
        clips = _names(("text_encoders", "clip", "clip_gguf"))
        vaes = _names(("vae",))
        return {
            "required": {
                "fl2va_model": (models, {"default": models[0],
                                         "tooltip": "首尾帧主干（FL2VA）。"}),
                "ref2va_model": ([NONE] + models, {"default": NONE,
                                                   "tooltip": "多参考主干（REF2VA）。留 none 表示与 FL2VA 同一条权重。"}),
                "text_encoder": (clips, {}),
                "video_vae": (vaes, {"default": vaes[0], "tooltip": "H3 视频 VAE（latent_dim=3）。"}),
                "audio_vae": (vaes, {"default": vaes[0], "tooltip": "H3 音频 VAE（latent_dim=2）。"}),
                "non_h3_policy": (list(POLICY), {"default": POLICY[0],
                                                 "tooltip": "槽位里选到非 H3 权重时的处理方式。"}),
                "注意力加速(Sage)": (ATTN_CHOICES, {"default": ATTN_OFF,
                                                   "tooltip": "注意力后端；关闭=用 ComfyUI 默认。"}),
            }
        }

    @classmethod
    def IS_CHANGED(cls, **kw):
        return "|".join(str(kw.get(k, "")) for k in
                        ("fl2va_model", "ref2va_model", "text_encoder",
                         "video_vae", "audio_vae", "non_h3_policy", "注意力加速(Sage)"))

    def load(self, fl2va_model, ref2va_model, text_encoder, video_vae, audio_vae,
             non_h3_policy="自动回落", **kw):
        import nodes as cn

        if fl2va_model in (None, "", NONE) and ref2va_model in (None, "", NONE):
            raise ValueError("至少要选一个 H3 主干（FL2VA 或 REF2VA）。")

        clip, = cn.CLIPLoader().load_clip(text_encoder, type="minimax")
        v_vae, = cn.VAELoader().load_vae(video_vae)
        a_vae, = cn.VAELoader().load_vae(audio_vae)

        # 轻量角色校验：只提示，不阻断
        if getattr(v_vae, "latent_dim", None) == 2:
            print("[Vanco H3] ⚠ video_vae 看起来是音频 VAE（latent_dim=2），请检查")
        if getattr(a_vae, "latent_dim", None) == 3:
            print("[Vanco H3] ⚠ audio_vae 看起来是视频 VAE（latent_dim=3），请检查")

        attn = kw.get("注意力加速(Sage)", ATTN_OFF)
        if attn != ATTN_OFF:
            print("[Vanco H3] 注意力加速设置：%s（由 ComfyUI 后端处理）" % attn)

        bundle = VancoH3Bundle(
            fl2va_model=fl2va_model, ref2va_model=ref2va_model,
            clip_name=text_encoder, video_vae_name=video_vae, audio_vae_name=audio_vae,
            clip=clip, video_vae=v_vae, audio_vae=a_vae,
            policy=non_h3_policy, attn=attn,
        )
        print("[Vanco H3] 已加载：FL2VA=%s；REF2VA=%s" % (fl2va_model, ref2va_model or "（同 FL2VA）"))
        return (bundle, _LazyModel(bundle, "ref2va"), clip, v_vae, a_vae)


NODE_CLASS_MAPPINGS = {"VancoH3ModelLoader": VancoH3ModelLoaderOwn}
NODE_DISPLAY_NAME_MAPPINGS = {"VancoH3ModelLoader": "Vanco H3 模型加载器"}
