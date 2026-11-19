# -*- coding: utf-8 -*-
"""Vanco Studio · 分段引擎（v0.1：逐段生成 → 接尾帧/换图 → 落盘 → 合并）"""
import json
import os
import re
import subprocess
import tempfile
import time

import numpy as np
import torch
from PIL import Image

import comfy.sample
import comfy.samplers
import comfy.utils
import folder_paths
import latent_preview

CAT = "Vanco/核心"
try:
    import comfy.samplers as _cs
    SAMPLER_CHOICES = list(getattr(_cs.KSampler, "SAMPLERS", None) or getattr(_cs, "SAMPLER_NAMES", None) or [])
except Exception:
    SAMPLER_CHOICES = []
if not SAMPLER_CHOICES:
    SAMPLER_CHOICES = ["euler", "res_multistep", "er_sde", "dpmpp_2m", "dpmpp_sde", "uni_pc", "seeds_2"]
try:
    SCHEDULER_CHOICES = list(getattr(_cs.KSampler, "SCHEDULERS", None) or getattr(_cs, "SCHEDULER_NAMES", None) or [])
except Exception:
    SCHEDULER_CHOICES = []
if not SCHEDULER_CHOICES:
    SCHEDULER_CHOICES = ["simple", "beta", "sgm_uniform", "karras", "normal", "exponential", "ddim_uniform"]

FFMPEG = None


def _ffmpeg():
    global FFMPEG
    if FFMPEG:
        return FFMPEG
    try:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG = "ffmpeg"
    return FFMPEG


def parse_script(txt, 默认秒数=8.0):
    shots, cur = [], None
    for line in (txt or "").lstrip("\ufeff").replace("\r\n", "\n").split("\n"):
        m = re.match(r"^\s*\[(\d+)\]\s*(.*)$", line)
        if m:
            if cur:
                shots.append(cur)
            kv = {}
            for _piece in re.split(r"\s*(?=(?:续接|角色|秒|图)\s*=)", m.group(2)):
                _m = re.match(r"(续接|角色|秒|图)\s*=\s*(.*)$", _piece.strip(), re.S)
                if _m:
                    kv[_m.group(1)] = _m.group(2).strip()
            cur = dict(n=int(m.group(1)), cont=kv.get("续接", "上一段"),
                       cast=[c.strip() for c in kv.get("角色", "").split(",") if c.strip()],
                       sec=float(kv.get("秒") or 默认秒数 or 8.0),
                       imgs=[int(x) for x in re.findall(r"\d+", kv.get("图", ""))],
                       body=[])
        elif cur is not None:
            cur["body"].append(line)
    if cur:
        shots.append(cur)
    for s in shots:
        s["body"] = "\n".join(s["body"]).strip()
    return shots


def align_frames(sec):
    n = max(5, int(round(sec * 24)))
    while n % 17 != 5:
        n += 1
    return n


class VancoChainEngine:
    """一键出片：吃分镜文本 + 素材，逐段生成、自动接尾帧或换图，最后合并。"""

    @classmethod
    def INPUT_TYPES(cls):
        try:
            return cls._schema()
        except Exception:
            import traceback
            with open(os.path.join(os.path.dirname(__file__), "schema_error.txt"), "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            return {"required": {"分镜文本": ("STRING", {"multiline": True, "default": ""})}}

    @classmethod
    def _schema(cls):
        return {
            "required": {
                "主模型": ("MODEL",),
                "文本编码器": ("CLIP",),
                "视频VAE": ("VAE",),
                "音频VAE": ("VAE",),
                "分镜文本": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False}),
                "宽": ("INT", {"default": 960, "min": 32, "max": 4096, "step": 32}),
                "高": ("INT", {"default": 544, "min": 32, "max": 4096, "step": 32}),
                "步数": ("INT", {"default": 8, "min": 1, "max": 50}),
                "采样器": (SAMPLER_CHOICES, {"default": "euler"}),
                "调度器": (SCHEDULER_CHOICES, {"default": "simple"}),
                "种子": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
                "开二采": ("BOOLEAN", {"default": False}),
                "二采模型": (folder_paths.get_filename_list("latent_upscale_models"), {"default": "minimax_h3_latent_upscaler_3d_fp16.safetensors"}),
                "二采倍数": ("FLOAT", {"default": 1.4, "min": 1.0, "max": 2.0, "step": 0.1}),
                "二采步数": ("INT", {"default": 3, "min": 1, "max": 30}),
                "二采降噪": ("FLOAT", {"default": 0.3, "min": 0.05, "max": 1.0, "step": 0.05}),
                "保存分段": ("BOOLEAN", {"default": True, "tooltip": "每段单独落盘 mp4 + json，便于逐段查看与重跑"}),
                "参考尺寸": (["match", "max"], {"default": "match", "tooltip": "match=按生成分辨率缩放参考图；max=保留参考图原始尺寸（细节更多，更吃显存）"}),
                "引擎也存成片": ("BOOLEAN", {"default": False, "tooltip": "关闭时成片只由画布上的 SaveVideo 保存（带元数据），避免存两份"}),
                "剧本名": ("STRING", {"default": "未命名剧本", "tooltip": "输出归档到 视频合集/Vanco/多段导演台/<剧本名>/"}),
                "省内存模式": ("BOOLEAN", {"default": False, "tooltip": "长片（>8段）建议开：不把全片帧留在内存，代价是画布不再输出成片，只留引擎拼接那份"}),
                "段间清理": (["关", "只清缓存", "卸载模型+清缓存"], {"default": "关", "tooltip": "每段结束后释放显存。只清缓存≈无副作用；卸载模型会降低峰值显存，但每段要重新加载（更慢）"}),
                "只跑第N段": ("INT", {"default": 0, "min": 0, "max": 99, "tooltip": "0=全跑；填 3=只重跑第 3 段，其余段用已有文件拼接"}),
                "重跑后交给画布": ("BOOLEAN", {"default": False, "tooltip": "关=阻断画布输出（快、无损）；开=解码整片交给画布，超分和 SaveVideo 照常跑"}),
                "上游已变时": (["停下提醒", "照跑不管"], {"default": "停下提醒"}),
                "下游处理": (["只跑这一段", "级联重跑"], {"default": "只跑这一段", "tooltip": "级联重跑：第 N+1、N+2… 若写「续接=上一段」则跟着重跑，保证衔接"}),
                "精确重跑": (["关", "首尾帧"], {"default": "关", "tooltip": "重跑第N段时，用第N+1段的首帧当终点，避免牵连下游"}),
                "接缝处理": (["关", "微淡化", "微淡化+逐段色彩归一"], {"default": "微淡化", "tooltip": "微淡化=接缝交叉淡化；+逐段色彩归一=每段都对齐到第一段的亮度/饱和"}),
                "参考尾帧数": ("INT", {"default": 1, "min": 1, "max": 64, "tooltip": "大于1=额外喂一段参考视频（自动吸附到 17k+5：5/22/39/56）；1=只喂最后一帧"}),
                "硬接模式": (["关", "每段锚定上段尾帧"], {"default": "关", "tooltip": "开=每段用 FL2VA 的 first_frame 硬锚上一段尾帧（构图/景别锁死）。需要接 h3_bundle 且配了 FL2VA 模型"}),
                "尾帧取样": (["最后一帧", "倒数第2帧"], {"default": "倒数第2帧", "tooltip": "倒数第2帧通常比最后一帧干净，接缝更稳"}),
                "人物检测": ("BOOLEAN", {"default": False, "tooltip": "每段检测前 N 帧有没有人、人数是否符合剧本「角色=」的数量；只报告，不影响生成"}),
                "检测帧数": ("INT", {"default": 12, "min": 1, "max": 48, "tooltip": "只检查开头这么多帧（12 帧 ≈ 0.5 秒）"}),
                "自动裁空镜": ("BOOLEAN", {"default": False, "tooltip": "开头无人而后出现人时，自动裁掉前面的空镜帧（连带裁剪音频）"}),
                "成片只存画布": ("BOOLEAN", {"default": True, "tooltip": "开：段间淡化在内存完成，只由画布 SaveVideo 出唯一成片（带元数据、只编码一次）；关：引擎另存一份 合并-*.mp4"}),
            },
            "optional": {"素材": ("IMAGE",), "名字列表": ("STRING", {"forceInput": True}),
                         "默认秒数": ("FLOAT", {"default": 8.0, "min": 1.0, "max": 30.0, "step": 0.5, "forceInput": True}),
                         "分镜输入": ("STRING", {"forceInput": True, "multiline": True}),
                         "h3_bundle": ("MINIMAX_H3_BUNDLE", {"tooltip": "接 VancoH3ModelLoader 的 h3_bundle；首尾帧/硬接模式用它取 FL2VA 主干"}),
                         "输出设置": ("STRING", {"forceInput": True, "tooltip": "接「📦 输出设置」的输出"}),
                         "重跑设置": ("STRING", {"forceInput": True, "tooltip": "接「🔁 重跑设置」的输出"}),
                         "质检设置": ("STRING", {"forceInput": True, "tooltip": "接「🔍 衔接与质检」的输出"})},
        }

    RETURN_TYPES = ("IMAGE", "AUDIO", "INT", "STRING")
    RETURN_NAMES = ("合并帧", "音频", "段数", "分段清单")
    FUNCTION = "run"
    CATEGORY = CAT
    OUTPUT_NODE = True
    DESCRIPTION = "把分镜文本逐段生成、自动衔接，最后合并成一条视频。"

    def run(self, 主模型, 文本编码器, 视频VAE, 音频VAE, 分镜文本, 宽, 高,
            步数=8, 采样器="euler", 调度器="simple", 种子=0,
            开二采=False, 二采模型="", 二采倍数=1.4, 二采步数=3, 二采降噪=0.3,
            保存分段=True, 参考尺寸="match", 引擎也存成片=False, 剧本名="未命名剧本",
            省内存模式=False, 段间清理="关",
            只跑第N段=0, 重跑后交给画布=False, 上游已变时="停下提醒", 下游处理="只跑这一段",
            精确重跑="关", 接缝处理="微淡化", 参考尾帧数=1, 尾帧取样="倒数第2帧",
            人物检测=False, 检测帧数=12, 自动裁空镜=False, 成片只存画布=True, 硬接模式="关",
            素材=None, 名字列表="", 默认秒数=8.0, 分镜输入=None, h3_bundle=None,
            输出设置=None, 重跑设置=None, 质检设置=None):
        # 设置台覆盖（未接则保持节点上的值）
        def _ov(src, key, cur):
            try:
                import json as _j
                d = _j.loads(src) if isinstance(src, str) and src.strip() else {}
            except Exception:
                d = {}
            return d.get(key, cur)

        for _k in ("剧本名", "保存分段", "成片只存画布", "引擎也存成片", "省内存模式", "段间清理"):
            if _k == "剧本名":
                剧本名 = _ov(输出设置, _k, 剧本名)
            elif _k == "保存分段":
                保存分段 = _ov(输出设置, _k, 保存分段)
            elif _k == "成片只存画布":
                成片只存画布 = _ov(输出设置, _k, 成片只存画布)
            elif _k == "引擎也存成片":
                引擎也存成片 = _ov(输出设置, _k, 引擎也存成片)
            elif _k == "省内存模式":
                省内存模式 = _ov(输出设置, _k, 省内存模式)
            else:
                段间清理 = _ov(输出设置, _k, 段间清理)

        for _k in ("只跑第N段", "下游处理", "重跑后交给画布", "上游已变时", "精确重跑"):
            if _k == "只跑第N段":
                只跑第N段 = _ov(重跑设置, _k, 只跑第N段)
            elif _k == "下游处理":
                下游处理 = _ov(重跑设置, _k, 下游处理)
            elif _k == "重跑后交给画布":
                重跑后交给画布 = _ov(重跑设置, _k, 重跑后交给画布)
            elif _k == "上游已变时":
                上游已变时 = _ov(重跑设置, _k, 上游已变时)
            else:
                精确重跑 = _ov(重跑设置, _k, 精确重跑)

        for _k in ("硬接模式", "接缝处理", "参考尾帧数", "尾帧取样", "人物检测", "检测帧数", "自动裁空镜"):
            if _k == "硬接模式":
                硬接模式 = _ov(质检设置, _k, 硬接模式)
            elif _k == "接缝处理":
                接缝处理 = _ov(质检设置, _k, 接缝处理)
            elif _k == "参考尾帧数":
                参考尾帧数 = _ov(质检设置, _k, 参考尾帧数)
            elif _k == "尾帧取样":
                尾帧取样 = _ov(质检设置, _k, 尾帧取样)
            elif _k == "人物检测":
                人物检测 = _ov(质检设置, _k, 人物检测)
            elif _k == "检测帧数":
                检测帧数 = _ov(质检设置, _k, 检测帧数)
            else:
                自动裁空镜 = _ov(质检设置, _k, 自动裁空镜)

        text = 分镜输入 if (isinstance(分镜输入, str) and 分镜输入.strip()) else 分镜文本
        shots = parse_script(text, 默认秒数)
        _chain, _chains = [], []
        for _sh in shots:
            if str(_sh.get("cont", "")).startswith("新图"):
                if _chain:
                    _chains.append(_chain)
                _chain = [_sh["n"]]
            else:
                _chain.append(_sh["n"])
        if _chain:
            _chains.append(_chain)
        for _c in _chains:
            if len(_c) > 3:
                self._warn("第 %d-%d 段是同一条链（%d 段），从第 4 段起画质会明显下降"
                           % (_c[0], _c[-1], len(_c)))
        if not shots:
            raise RuntimeError("[Vanco] 分镜文本里没解析到任何 [n] 段落")
        out_root = folder_paths.get_output_directory()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        prev_img = None
        self._剧名 = 剧本名
        self._h3_bundle = h3_bundle
        self._fl2va = None
        self._warns = []

        files = []
        all_frames = []
        first_audio = None
        seg_files = []
        audios = []

        seg_dir = os.path.join(folder_paths.get_output_directory(), "视频合集", "Vanco",
                               "多段导演台", str(剧本名 or "未命名剧本"), "分段")
        rerun = int(只跑第N段 or 0)
        if rerun > 0:
            if not 保存分段:
                raise RuntimeError("[Vanco] 重跑需要「保存分段」开启")
            if not any(x["n"] == rerun for x in shots):
                raise RuntimeError("[Vanco] 分镜里没有第 %d 段" % rerun)
            self._check_upstream(shots, rerun, 上游已变时)
            run_set = {rerun}
            if 下游处理 == "级联重跑":
                for x in shots:
                    if x["n"] <= rerun:
                        continue
                    if str(x.get("cont", "")).startswith("上一段"):
                        run_set.add(x["n"])
                    else:
                        break
                print("[Vanco] 级联重跑段号:", sorted(run_set))

        try:
            import comfy.utils as _cu
            pbar = _cu.ProgressBar(len(shots))
        except Exception:
            pbar = None

        for i, s in enumerate(shots):
            n = align_frames(s["sec"])
            if pbar is not None:
                pbar.update_absolute(i, len(shots))
            if rerun > 0 and s["n"] not in locals().get("run_set", {rerun}):
                old = self._latest_seg(seg_dir, s["n"])
                if old:
                    seg_files.append(old)
                    print("[Vanco] 复用第 %d 段: %s" % (s["n"], os.path.basename(old)))
                    prev_img = self._tail_frame(old)
                    continue
            # 起幅图：上一段尾帧 or 素材池第 1 张
            seed_img = prev_img
            start_from_asset = False
            start_idx = -1
            if s["cont"].startswith("新图") and 素材 is not None:
                want = s["cont"].split(":", 1)[1].strip() if ":" in s["cont"] else ""
                names = [x.strip() for x in (名字列表 or "").split("/") if x.strip()]
                if want.isdigit():
                    idx = int(want) - 1
                else:
                    idx = names.index(want) if want in names else 0
                if idx >= 素材.shape[0]:
                    idx = 0
                print("[Vanco] 换图 -> %s (第 %d 张)" % (want if not want.isdigit() else "序号", idx + 1))
                seed_img = 素材[idx:idx + 1]
                start_from_asset = True
                start_idx = idx
            ref_vid = None
            want_tail = int(参考尾帧数 or 1)
            if want_tail > 1:
                # 吸附到 H3 合法的 17k+5 长度，避免用户填 7 这种值时采样异常
                snap = 5
                for cand in (5, 22, 39, 56):
                    if want_tail <= cand:
                        snap = cand
                        break
                else:
                    snap = 56
                if snap != want_tail:
                    print("[Vanco] 参考尾帧数 %d 吸附为 %d（H3 需要 17k+5 长度）" % (want_tail, snap))
                want_tail = snap
            if want_tail > 1 and s["n"] > 1:
                prev_file = self._latest_seg(seg_dir, s["n"] - 1)
                if prev_file:
                    ref_vid = self._last_frames(prev_file, want_tail)
                    if ref_vid is not None:
                        print("[Vanco] 参考尾帧: 第 %d 段最后 %d 帧" % (s["n"] - 1, ref_vid.shape[0]))

            _t0 = time.time()
            本次模型 = 主模型

            if rerun > 0 and 精确重跑 == "首尾帧" and s["n"] == rerun:
                nxt = next((x for x in shots if x["n"] == rerun + 1), None)
                end_img = None
                if nxt is not None:
                    nxt_file = self._latest_seg(seg_dir, rerun + 1)
                    if nxt_file:
                        end_img = self._head_frame(nxt_file)
                if seed_img is None and 素材 is not None:
                    seed_img = 素材[:1]
                if seed_img is not None and end_img is not None:
                    if self._fl2va is None:
                        self._fl2va = self._fl2va_model()
                    if self._fl2va is not None:
                        本次模型 = self._fl2va
                    else:
                        print("[Vanco] ⚠ 首尾帧模式拿不到 FL2VA 主干，keyframes 可能被 REF2VA 忽略"
                              "（请把 VancoH3ModelLoader 的 h3_bundle 接到本节点）")
                    print("[Vanco] 首尾帧模式：起点=当前段起点，终点=第 %d 段首帧" % (rerun + 1))
                    cond, latent = self._condition_fl(文本编码器, 视频VAE, s["body"], 宽, 高, n,
                                                      seed_img, end_img)
                else:
                    if seed_img is None:
                        print("[Vanco] 首尾帧模式跳过：缺起点图（上一段还没生成）→ 用正常模式")
                    elif end_img is None:
                        print("[Vanco] 首尾帧模式跳过：第 %d 段还没生成，没有终点帧 → 用正常模式"
                              % (rerun + 1))
                    else:
                        print("[Vanco] 首尾帧模式跳过 → 用正常模式")
                    cond, latent = self._condition(文本编码器, 视频VAE, 音频VAE, s["body"], 宽, 高, n,
                                                   素材, seed_img, 参考尺寸, ref_vid)
            else:
                cond, latent = self._condition(文本编码器, 视频VAE, 音频VAE, s["body"], 宽, 高, n, 素材,
                                                seed_img, 参考尺寸, ref_vid,
                                                skip_asset=start_from_asset, skip_idx=start_idx,
                                            shot_imgs=s.get("imgs"))
            # 硬接模式：覆盖前面的参考图条件，改用 FL2VA 的 first_frame 硬锚上段尾帧
            if 硬接模式 == "每段锚定上段尾帧" and str(s["cont"]).startswith("上一段") and seed_img is not None:
                if self._fl2va is None:
                    self._fl2va = self._fl2va_model()
                if self._fl2va is None:
                    print("[Vanco] ⚠ 硬接模式拿不到 FL2VA 主干（没接 h3_bundle 或没配 FL2VA 模型），"
                          "本段退回参考图模式")
                    本次模型 = 主模型
                else:
                    本次模型 = self._fl2va
                    cond, latent = self._condition_fl(文本编码器, 视频VAE, s["body"], 宽, 高, n,
                                                      seed_img, None)
                    print("[Vanco] 段 %d 硬接：first_frame = 上段尾帧（FL2VA）" % s["n"])

            lat = self._sample(本次模型, cond, latent, 步数, 采样器, 调度器, 种子 + i)
            _t_sample = time.time()
            samples = lat["samples"]
            while isinstance(samples, dict):
                samples = samples.get("samples", samples)
            if 开二采 and 二采倍数 > 1.0:
                lat = self._pass2(主模型, cond, lat, 宽, 高, 二采倍数, 采样器, 调度器, 二采步数, 二采降噪, 二采模型, 种子 + i)
            av_lat = lat["samples"] if isinstance(lat, dict) else lat
            if not isinstance(av_lat, dict):
                av_lat = {"samples": av_lat}
            elif "samples" not in av_lat and isinstance(av_lat.get("samples"), dict):
                pass
            print("[Vanco] av_latent keys:", list(av_lat.keys()))
            imgs, audio = self._decode_av(av_lat, 视频VAE, 音频VAE)
            while imgs.ndim > 4:
                imgs = imgs[0]
            imgs = imgs.clamp(0, 1)
            _t_decode = time.time()
            prev_img = imgs[-2:-1] if (尾帧取样 == "倒数第2帧" and imgs.shape[0] > 1) else imgs[-1:]
            _t_color = time.time()
            if 人物检测:
                try:
                    imgs, audio = self._check_and_trim(imgs, audio, s, 检测帧数, 自动裁空镜)
                except Exception as _e:
                    print("[Vanco] 人物检测失败:", _e)

            if "色彩归一" in 接缝处理:
                imgs = self._color_match(imgs)

            if isinstance(audio, dict) and audio.get("waveform") is not None:
                audios.append(audio)
            if 保存分段:
                try:
                    fp = self._save_seg(imgs, audio, s, stamp, n)
                    seg_files.append(fp)
                except Exception as e:
                    print("[Vanco] 分段落盘失败:", e)
            if not 省内存模式:
                all_frames.append(imgs.detach().cpu() if hasattr(imgs, "detach") else imgs)
            files.append(seg_files[-1] if (保存分段 and seg_files) else "")
            _t_end = time.time()
            def _f(a, b):
                d = max(0.0, b - a)
                return "%d:%02d" % (int(d // 60), int(d % 60))
            print("[Vanco] 段 %d 分段耗时 ▼ 采样 %s | 解码 %s | 检测/色彩 %s | 落盘 %s | 合计 %s"
                  % (s["n"], _f(_t0, _t_sample), _f(_t_sample, _t_decode),
                     _f(_t_decode, _t_color), _f(_t_color, _t_end), _f(_t0, _t_end)))
            print("[Vanco] 段 %d/%d 完成（%s）" % (i + 1, len(shots), s["cont"]))
            if pbar is not None:
                pbar.update_absolute(i + 1, len(shots))
            if 段间清理 != "关":
                self._free_vram(段间清理)

        import torch
        if 省内存模式 and rerun == 0:
            # 省内存模式：先拼接成片，再阻断画布
            try:
                mf = self._concat_all(seg_dir, 剧本名, stamp, seg_files, 接缝处理)
                print("[Vanco] 省内存模式成片:", mf)
                self._finish_report(剧本名, stamp, seg_files, mf)
            except Exception as e:
                print("[Vanco] 省内存模式拼接失败:", e)
            print("[Vanco] 省内存模式：不向画布交帧")
            from comfy_execution.graph import ExecutionBlocker
            return (ExecutionBlocker(None), ExecutionBlocker(None),
                    len(seg_files), "\n".join(seg_files))

        merged = torch.cat(all_frames, 0) if all_frames else torch.zeros((1, 64, 64, 3))
        if rerun > 0:
            merged_file = self._concat_all(seg_dir, 剧本名, stamp, seg_files, 接缝处理)
            print("[Vanco] 重跑完成，整条成片:", merged_file)
            self._finish_report(剧本名, stamp, seg_files, merged_file)
            if not 重跑后交给画布:
                from comfy_execution.graph import ExecutionBlocker
                return (ExecutionBlocker(None), ExecutionBlocker(None), len(all_frames),
                        "\n".join(seg_files))
            frames, audio = self._read_back(merged_file)
            return (frames, audio, len(all_frames), "\n".join(seg_files))

        # 单成片模式：段间淡化在内存完成；引擎副本由「引擎也存成片」决定
        if 成片只存画布 and 保存分段 and seg_files:
            k = 3 if "微淡化" in str(接缝处理) else 0
            merged = self._blend_segments(all_frames, k)
            mf_single = None
            if 引擎也存成片:
                try:
                    mf_single = self._concat_all(seg_dir, 剧本名, stamp, seg_files, 接缝处理)
                    print("[Vanco] 单成片模式：引擎副本", mf_single)
                except Exception as e:
                    print("[Vanco] 单成片模式：引擎副本失败", e)
            self._finish_report(剧本名, stamp, seg_files, mf_single)
            print("[Vanco] 单成片模式：帧 %s 交给画布" % (tuple(merged.shape),))
            print("[Vanco] 提示：画布 SaveVideo 的前缀必须指向 …/%s/成片/，否则成片会落到别的目录" % 剧本名)
            return (merged, self._join_audio(audios), len(all_frames), "\n".join(seg_files))

        # 全跑时若开了接缝处理，也拼一份带淡化的成片（画布那份照旧带元数据）
        _mf_last = None
        if 保存分段 and seg_files and (接缝处理 != "关" or 引擎也存成片):
            try:
                mf = self._concat_all(seg_dir, 剧本名, stamp, seg_files, 接缝处理)
                print("[Vanco] 全跑成片(带接缝处理):", mf)
                _mf_last = mf
            except Exception as e:
                print("[Vanco] 全跑拼接失败:", e)

        if 保存分段 and 引擎也存成片 and files:
            try:
                self._concat(files, 剧本名, stamp)
            except Exception as e:
                print("[Vanco] 成片合并失败:", e)
        self._finish_report(剧本名, stamp, seg_files, _mf_last)
        print("[Vanco] 合并帧:", tuple(merged.shape), "段数:", len(all_frames))
        return (merged, self._join_audio(audios), len(all_frames), "\n".join(seg_files))

    # ---------- 内部 ----------
    def _blend_segments(self, seg_frames, k=3):
        """段间接缝在内存里做短淡化：不改变总时长，只混合后一段的开头几帧。"""
        import torch
        if not seg_frames or len(seg_frames) < 2 or k <= 0:
            return torch.cat(seg_frames, 0) if seg_frames else torch.zeros((1, 64, 64, 3))
        out = []
        for idx, seg in enumerate(seg_frames):
            seg = seg.clone()
            if idx > 0:
                prev = out[-1]
                m = min(int(k), prev.shape[0], seg.shape[0])
                if m > 0:
                    w = torch.linspace(0.0, 1.0, m + 2, dtype=seg.dtype, device=seg.device)[1:-1]
                    w = w.view(-1, 1, 1, 1)
                    seg[:m] = prev[-m:] * (1.0 - w) + seg[:m] * w
                    # 上一段末尾也吃一半权重，过渡更自然
                    out[-1] = torch.cat([prev[:-m], prev[-m:] * w + seg[:m] * (1.0 - w)], 0)
            out.append(seg)
        print("[Vanco] 内存淡化：%d 段，每处混合 %d 帧" % (len(out), k))
        return torch.cat(out, 0)

    def _decode_av(self, av_latent, video_vae, audio_vae):
        """解码 H3 的联合 AV latent → (帧, 音频)。

        只用 ComfyUI 内置 API；若形状不符合预期，退回 T8 的解码节点（若已安装）。
        """
        import torch
        samples = av_latent["samples"] if isinstance(av_latent, dict) else av_latent
        try:
            if not getattr(samples, "is_nested", False):
                raise ValueError("latent 不是嵌套 AV 结构")
            video, audio = samples.unbind()
            if video.ndim != 5 or audio.ndim != 4:
                raise ValueError("AV 形状异常 video=%s audio=%s" % (tuple(video.shape), tuple(audio.shape)))
            images = video_vae.decode(video)
            if images.ndim == 5:
                images = images.reshape(-1, *images.shape[-3:])
            from comfy_extras.nodes_audio import vae_decode_audio
            decoded = vae_decode_audio(audio_vae, {"samples": audio})
            print("[Vanco] 自研 AV 解码：帧 %s，音频 %s" %
                  (tuple(images.shape), getattr(decoded, "shape", type(decoded).__name__)))
            return images, decoded
        except Exception as e:
            print("[Vanco] 自研解码失败（%s），尝试 T8 解码节点" % e)
            import nodes as comfy_nodes
            dec = comfy_nodes.NODE_CLASS_MAPPINGS.get("MiniMaxH3AVDecodeT8")
            if dec is None:
                raise RuntimeError("自研解码失败，且未安装 minimax-h3-audio-T8 的解码节点：%s" % e)
            dout = dec.execute(av_latent=av_latent, video_vae=video_vae, audio_vae=audio_vae)
            dres = getattr(dout, "result", dout)
            return dres[0], (dres[1] if len(dres) > 1 else None)

    def _condition(self, clip, vae, audio_vae, prompt, w, h, n, 素材, seed_img,
                   ref_size="match", ref_vid=None, skip_asset=False, skip_idx=-1, shot_imgs=None):
        from comfy_extras.nodes_minimax_h3 import MiniMaxH3ReferenceToVideo
        # 参考图组装：优先用本段 图= 指定的，否则用全部素材
        sel = shot_imgs or []
        refs = []
        if sel and 素材 is not None:
            valid = [i - 1 for i in sel if 1 <= i <= int(素材.shape[0])]
            for i in valid:
                refs.append(素材[i:i + 1])
            # 起幅图必须排第一（模型靠第一位识别起幅图）
            if skip_asset and skip_idx >= 0:
                if skip_idx in valid:
                    refs = [素材[skip_idx:skip_idx + 1]] + [素材[i:i + 1] for i in valid if i != skip_idx]
                else:
                    refs = [素材[skip_idx:skip_idx + 1]] + refs
            print("[Vanco] 本段 图=%s → 参考图 %d 张" % (sel, len(refs)))
        else:
            if skip_asset and skip_idx >= 0 and 素材 is not None:
                refs.append(素材[skip_idx:skip_idx + 1])
                for k in range(min(int(素材.shape[0]), 8)):
                    if k != skip_idx:
                        refs.append(素材[k:k + 1])
            else:
                if seed_img is not None:
                    refs.append(seed_img)
                if 素材 is not None:
                    for k in range(min(int(素材.shape[0]), 8)):
                        refs.append(素材[k:k + 1])
                self._warn("本段没写 图=，已喂全部 %d 张素材（容易串人）" % len(refs))
        out = MiniMaxH3ReferenceToVideo.execute(
            clip=clip, vae=vae, audio_vae=audio_vae, prompt=prompt,
            width=w, height=h, length=n, ref_image_size=ref_size,
            ref_images={("ref_image_%d" % i): r for i, r in enumerate(refs)} if refs else None,
            ref_videos={"ref_video_1": ref_vid} if ref_vid is not None else None)
        outs = out.result if hasattr(out, "result") else out
        return outs[0], outs[1]

    def _sample(self, model, cond, latent, steps, sampler_name, scheduler, seed=0):
        from comfy_extras.nodes_custom_sampler import (BasicGuider, KSamplerSelect,
                                                      BasicScheduler, RandomNoise,
                                                      SamplerCustomAdvanced)
        def unwrap(x, i=0):
            r = getattr(x, "result", x)
            return r[i] if isinstance(r, (tuple, list)) else r
        guider = unwrap(BasicGuider.execute(model, cond))
        sampler = unwrap(KSamplerSelect.execute(sampler_name))
        sigmas = unwrap(BasicScheduler.execute(model, scheduler, steps, 1.0))
        noise = unwrap(RandomNoise.execute(int(seed) % 2 ** 63))
        out = SamplerCustomAdvanced.execute(noise, guider, sampler, sigmas, latent)
        return {"samples": unwrap(out, 0)}

    def _write_mp4(self, images, audio, lat, path, fps):
        import numpy as np
        from PIL import Image
        print("[Vanco] 写盘前形状:", tuple(images.shape))
        try:
            from comfy_extras.nodes_video import CreateVideo, SaveVideo
            v = CreateVideo.execute(images, float(fps), audio)
            v = getattr(v, "result", v)[0]
            SaveVideo.execute(v, path, {"format": "auto"}, {"codec": "auto"})
            print("[Vanco] 官方 SaveVideo 已写:", os.path.basename(path))
            return
        except Exception as e:
            print("[Vanco] 官方写盘失败，改用 ffmpeg：", e)
        frames = (images.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8) if hasattr(images, "cpu") else images
        if frames.ndim == 5:
            frames = frames.reshape(-1, frames.shape[-3], frames.shape[-2], frames.shape[-1])
        tmp = os.path.join(os.path.dirname(path), "_frames_%d" % int(time.time() * 1000))
        os.makedirs(tmp, exist_ok=True)
        for i in range(frames.shape[0]):
            Image.fromarray(frames[i]).save(os.path.join(tmp, "%05d.png" % i))
        subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
                        "-i", os.path.join(tmp, "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "16", "-y", path])
        print("[Vanco] 已写:", os.path.basename(path), os.path.exists(path))

    def _pass2(self, model, cond, lat, w, h, scale, sampler_name, scheduler, steps=3, denoise=0.3, model_name="none", seed=0):
        import nodes as cn
        try:
            L = cn.NODE_CLASS_MAPPINGS["LatentUpscaleModelLoader"]
            out = L.execute(model_name=model_name if model_name and model_name != "none" else "minimax_h3_latent_upscaler_3d_fp16.safetensors")
            um = getattr(out, "result", out)[0]
            up = cn.NODE_CLASS_MAPPINGS["MiniMaxH3LatentUpscaleWithModel"]
            r = up.execute(model=um, samples=lat["samples"] if isinstance(lat, dict) else lat, width=int(w * scale // 32 * 32),
                           height=int(h * scale // 32 * 32))
            lat2 = getattr(r, "result", r)[0]
            print("[Vanco] 二采：latent 放大 %.2fx" % scale)
            return self._sample(model, cond, lat2, steps, sampler_name, scheduler, seed)
        except Exception as e:
            print("[Vanco] 二采失败，跳过：", e)
            return lat

    def _sr(self, path, scale):
        import nodes as cn
        try:
            L = cn.NODE_CLASS_MAPPINGS["ReCaVSRLoader"]
            m = L.execute(transformer="transformer_int8_convrot.safetensors")
            mv = getattr(m, "result", m)[0]
            up = cn.NODE_CLASS_MAPPINGS["ReCaVSRUpscale"]
            LV = cn.NODE_CLASS_MAPPINGS["LoadVideo"]
            vid = getattr(LV.execute(os.path.basename(path)), "result", None)
            vid = vid[0] if vid else None
            out = up.execute(model=mv, scale=scale, color_fix="adain", seed=1, decoder="flashdecoder",
                             kernels="fast", kv_offload=False, encoder="auto", video=vid)
            res = getattr(out, "result", out)[0]
            sv = cn.NODE_CLASS_MAPPINGS["SaveVideo"].__new__(cn.NODE_CLASS_MAPPINGS["SaveVideo"])
            sv.save_video(res, os.path.splitext(path)[0] + "_SR", "auto", "auto")
            print("[Vanco] 超分完成：%.1fx" % scale)
            return os.path.splitext(path)[0] + "_SR.mp4"
        except Exception as e:
            print("[Vanco] 超分失败，跳过：", e)
            return path

    def _save_seg(self, images, audio, shot, stamp, frames):
        """落盘单段 mp4 + 指纹 json。"""
        import hashlib
        import wave
        import numpy as np
        from PIL import Image as _Img
        out_dir = os.path.join(folder_paths.get_output_directory(), "视频合集", "Vanco", "多段导演台",
                               str(getattr(self, "_剧名", "") or "未命名剧本"), "分段")
        os.makedirs(out_dir, exist_ok=True)
        idx = shot["n"]
        ver = 1
        while os.path.exists(os.path.join(out_dir, "seg%02d_v%d.mp4" % (idx, ver))):
            ver += 1
        name = "seg%02d_v%d" % (idx, ver)
        mp4 = os.path.join(out_dir, name + ".mp4")

        # 帧 -> rawvideo 管道直写（不落 PNG，省时间与磁盘）
        arr = None
        try:
            import torch as _th
            if hasattr(images, "mul"):
                arr = images.detach().mul(255.0).clamp(0, 255).to(_th.uint8).cpu().numpy()
            else:
                arr = (np.asarray(images) * 255.0).clip(0, 255).astype(np.uint8)
        except Exception:
            arr = (np.asarray(images) * 255.0).clip(0, 255).astype(np.uint8)

        h, w = int(arr.shape[1]), int(arr.shape[2])
        wav = os.path.join(out_dir, name + ".wav")
        has_audio = False
        try:
            if isinstance(audio, dict) and audio.get("waveform") is not None:
                wf = audio["waveform"]
                wf = wf.cpu().numpy() if hasattr(wf, "cpu") else np.asarray(wf)
                wf = wf.reshape(-1, wf.shape[-1])
                pcm = (wf.T * 32767).clip(-32768, 32767).astype(np.int16)
                with wave.open(wav, "wb") as wf2:
                    wf2.setnchannels(pcm.shape[1])
                    wf2.setsampwidth(2)
                    wf2.setframerate(int(audio.get("sample_rate", 44100)))
                    wf2.writeframes(pcm.tobytes())
                has_audio = True
        except Exception as e:
            print("[Vanco] 分段音频写入失败:", e)

        cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
               "-r", "24", "-i", "-"]
        if has_audio:
            cmd += ["-i", wav]
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16"]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
        cmd += ["-y", mp4]

        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
            proc.stdin.write(arr.tobytes())
            proc.stdin.close()
            err = proc.stderr.read() if proc.stderr else b""
            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError((err or b"").decode("utf-8", "ignore")[-300:])
        except Exception as e:
            print("[Vanco] 管道写盘失败，回退 PNG 路径:", e)
            tmp = os.path.join(out_dir, "_tmp_%02d" % idx)
            os.makedirs(tmp, exist_ok=True)
            for _i in range(arr.shape[0]):
                _Img.fromarray(arr[_i]).save(os.path.join(tmp, "%05d.png" % _i))
            _cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-framerate", "24",
                    "-i", os.path.join(tmp, "%05d.png")]
            if has_audio:
                _cmd += ["-i", wav]
            _cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16"]
            if has_audio:
                _cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
            _cmd += ["-y", mp4]
            subprocess.run(_cmd)
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

        if has_audio and os.path.exists(wav):
            os.remove(wav)

        # 指纹
        h = hashlib.sha1()
        h.update(str(shot.get("body", "")).encode("utf-8", "ignore"))
        h.update(str(frames).encode())
        h.update(str(shot.get("cont", "")).encode("utf-8", "ignore"))
        meta = {
            "段号": idx, "秒": shot.get("sec"), "帧数": int(arr.shape[0]),
            "续接": shot.get("cont", ""), "角色": shot.get("cast", []),
            "指纹": h.hexdigest()[:16], "文件": os.path.basename(mp4),
            "剧情指纹": hashlib.sha1((str(shot.get("body",""))+str(shot.get("sec",""))).encode("utf-8","ignore")).hexdigest()[:16],
            "有音频": has_audio,
        }
        import json as _json
        with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
            _json.dump(meta, f, ensure_ascii=False, indent=1)
        try:
            from PIL import Image as _PI
            _PI.fromarray(arr[-1]).save(os.path.join(out_dir, name + "_last.png"))
        except Exception as _e:
            print("[Vanco] 尾帧 PNG 保存失败:", _e)
        print("[Vanco] 分段已存:", name, meta["指纹"])
        return mp4

    def _latest_seg(self, seg_dir, num):
        if not os.path.isdir(seg_dir):
            return None
        best, best_v = None, -1
        for f in os.listdir(seg_dir):
            if not (f.startswith("seg%02d_v" % num) and f.endswith(".mp4")):
                continue
            try:
                v = int(f.split("_v")[1].split(".")[0])
            except Exception:
                continue
            if v > best_v:
                best, best_v = os.path.join(seg_dir, f), v
        return best

    def _seg_meta(self, seg_dir, num):
        p = self._latest_seg(seg_dir, num)
        if not p:
            return None
        j = os.path.splitext(p)[0] + ".json"
        if not os.path.exists(j):
            return None
        try:
            import json as _j
            return _j.load(open(j, encoding="utf-8"))
        except Exception:
            return None

    def _warn(self, msg):
        """记一条警告：日志 + 汇总，跑完统一提示。"""
        print("[Vanco] ⚠ " + msg)
        try:
            if msg not in self._warns:
                self._warns.append(msg)
        except Exception:
            pass

    def _finish_report(self, 剧本名, stamp, seg_files, merged=None):
        """写运行报告、维护 latest 指针、给界面发提示。"""
        try:
            base = os.path.join(folder_paths.get_output_directory(), "视频合集", "Vanco",
                                "多段导演台", str(剧本名 or "未命名剧本"))
            out_dir = os.path.join(base, "成片")
            os.makedirs(out_dir, exist_ok=True)
            lines = ["Vanco 导演台 运行报告", "时间: " + str(stamp),
                     "剧本: " + str(剧本名), "段数: %d" % len(seg_files), ""]
            if merged and os.path.exists(merged):
                lines.append("成片: " + os.path.basename(merged))
                # latest 指针：文本 + 硬链接（同盘秒完成）
                try:
                    lp = os.path.join(out_dir, "latest.mp4")
                    if os.path.exists(lp):
                        os.remove(lp)
                    try:
                        os.link(merged, lp)
                    except Exception:
                        import shutil as _sh
                        _sh.copy2(merged, lp)
                except Exception as e:
                    print("[Vanco] latest 指针写入失败:", e)
            else:
                lines.append("成片: 由画布 SaveVideo 保存（单成片模式，带元数据）")
                lp = os.path.join(out_dir, "latest.mp4")
                if os.path.exists(lp):
                    try:
                        os.remove(lp)
                    except Exception:
                        pass
            if self._warns:
                lines.append("")
                lines.append("警告 (%d 条):" % len(self._warns))
                lines.extend("  - " + w for w in self._warns)
            else:
                lines.append("")
                lines.append("警告: 无")
            with open(os.path.join(out_dir, "_运行报告.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            print("[Vanco] 运行报告:", os.path.join(out_dir, "_运行报告.txt"))
            # 界面浮层提示
            if self._warns:
                try:
                    from server import PromptServer
                    PromptServer.instance.send_sync("vanco-warn", {
                        "title": "本片有 %d 条警告" % len(self._warns),
                        "items": self._warns[:12],
                        "报告": os.path.join(out_dir, "_运行报告.txt"),
                    })
                except Exception as e:
                    print("[Vanco] 界面提示发送失败:", e)
        except Exception as e:
            print("[Vanco] 运行报告写入失败:", e)

    def _fl2va_model(self):
        """从 h3_bundle 取 FL2VA 主干；拿不到返回 None。"""
        b = getattr(self, "_h3_bundle", None)
        if b is None:
            return None
        try:
            return b.model_for("fl2va")
        except Exception as e:
            print("[Vanco] 取 FL2VA 主干失败:", e)
            return None

    def _check_and_trim(self, imgs, audio, shot, n_frames, auto_trim):
        """检测开头帧人数，必要时裁掉空镜。"""
        from .detect import detect_persons
        counts, _ = detect_persons(imgs, conf=0.2, max_frames=int(n_frames))
        if counts is None:
            print("[Vanco] 人物检测模型不可用，跳过")
            return imgs, audio
        expected = len(shot.get("cast") or [])
        got = max(counts) if counts else 0
        status = "OK" if (expected == 0 or got >= expected) else "人数不足"
        print("[Vanco] 段 %d 检测: 前 %d 帧人数=%s | 期望=%s | %s"
              % (shot.get("n", 0), n_frames, counts, expected or "未指定", status))

        first_human = next((i for i, c in enumerate(counts) if c > 0), None)
        if auto_trim and first_human is not None and first_human > 2:
            k = first_human
            if imgs.shape[0] - k >= 5:
                imgs = imgs[k:]
                if isinstance(audio, dict) and audio.get("waveform") is not None:
                    wf = audio["waveform"]
                    sr = int(audio.get("sample_rate", 44100))
                    cut = int(round(k / 24.0 * sr))
                    if wf.shape[-1] > cut:
                        audio = dict(audio)
                        audio["waveform"] = wf[..., cut:]
                print("[Vanco] 段 %d 裁掉 %d 帧空镜（%.2f 秒）"
                      % (shot.get("n", 0), k, k / 24.0))
        return imgs, audio

    def _color_match(self, imgs):
        """把本段色彩对齐到第一段（Reinhard 均值/标准差迁移）。"""
        import numpy as np
        try:
            a = imgs.detach().cpu().numpy() if hasattr(imgs, "detach") else np.asarray(imgs)
            flat = a.reshape(-1, a.shape[-1]).astype(np.float32)
            m, sd = flat.mean(axis=0), flat.std(axis=0) + 1e-6
            if getattr(self, "_cm_ref", None) is None:
                self._cm_ref = (m, sd)
                print("[Vanco] 色彩基准（第 1 段）:", np.round(m * 255).astype(int).tolist())
                return imgs
            rm, rsd = self._cm_ref
            out = (flat - m) / sd * rsd + rm
            out = np.clip(out, 0.0, 1.0).reshape(a.shape)
            print("[Vanco] 色彩归一 -> 参照第 1 段")
            import torch
            return torch.from_numpy(out.astype(np.float32))
        except Exception as e:
            print("[Vanco] 色彩归一跳过:", e)
            return imgs

    def _free_vram(self, mode):
        """段间释放显存：只清缓存 / 卸载模型+清缓存。"""
        try:
            import comfy.model_management as mm
            if mode == "卸载模型+清缓存":
                mm.unload_all_models()
            mm.soft_empty_cache()
            try:
                import torch
                if torch.cuda.is_available():
                    free, total = torch.cuda.mem_get_info()
                    print("[Vanco] 段间清理(%s) → 显存占用 %.2f/%.2f GB"
                          % (mode, (total - free) / 2 ** 30, total / 2 ** 30))
            except Exception:
                pass
        except Exception as e:
            print("[Vanco] 段间清理失败:", e)

    def _check_upstream(self, shots, rerun, policy):
        """第 N-1 段如果被改过，重跑第 N 段就会接错尾帧。"""
        prev = next((x for x in shots if x["n"] == rerun - 1), None)
        if prev is None or not str(prev.get("cont", "")).startswith("上一段"):
            return
        import hashlib
        h = hashlib.sha1(str(prev.get("body", "")).encode("utf-8", "ignore"))
        h.update(str(prev.get("sec", "")).encode("utf-8", "ignore"))
        want = h.hexdigest()[:16]
        meta = self._seg_meta(os.path.join(folder_paths.get_output_directory(), "视频合集", "Vanco",
                                           "多段导演台", str(getattr(self, "_剧名", "") or "未命名剧本"), "分段"),
                              rerun - 1)
        have = (meta or {}).get("剧情指纹")
        if have and have != want:
            msg = "[Vanco] 第 %d 段已改动，第 %d 段的起点图已过期" % (rerun - 1, rerun)
            if policy == "停下提醒":
                raise RuntimeError(msg + "；请先重跑第 %d 段，或把「上游已变时」改成「照跑不管」" % (rerun - 1))
            print(msg + "，继续执行（可能接错）")

        # 下游检查：第 N 段被重跑后，后面依赖"上一段尾帧"的段会过期
        later = []
        for x in shots:
            if x["n"] <= rerun:
                continue
            if str(x.get("cont", "")).startswith("上一段"):
                later.append(x["n"])
            else:
                break
        if later:
            self._warn("重跑第 %d 段后，第 %s 段接的是旧尾帧，建议一并重跑（用「级联重跑」）"
                       % (rerun, "、".join(str(v) for v in later)))

    def _concat_all(self, seg_dir, 剧本名, stamp, files=None, seam="关"):
        if files:
            segs = [p for p in files if p and os.path.exists(p)]
        else:
            segs = []
            for f in sorted(os.listdir(seg_dir)):
                if f.endswith(".mp4") and f.startswith("seg"):
                    segs.append(os.path.join(seg_dir, f))
        if not segs:
            raise RuntimeError("[Vanco] 没有任何分段，无法拼接")
        out_dir = os.path.join(folder_paths.get_output_directory(), "视频合集", "Vanco",
                               "多段导演台", str(剧本名 or "未命名剧本"), "成片")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "合并-%s.mp4" % stamp)
        lst = os.path.join(tempfile.gettempdir(), "vanco_cat_%s.txt" % stamp)
        with open(lst, "w", encoding="utf-8") as fh:
            for p in segs:
                fh.write("file '%s'\n" % p.replace("\\", "/"))
        sizes = {p: self._res(p) for p in segs}
        uniq = set(v for v in sizes.values() if v != (0, 0))
        mixed = len(uniq) > 1
        if mixed:
            print("[Vanco] 警告：分段分辨率不一致", uniq, "-> 将统一到第一段尺寸")

        # 先无损拼接（分辨率不一致时跳过 copy，直接重编码）
        if not mixed:
            subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error",
                            "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", lst,
                            "-c", "copy", "-avoid_negative_ts", "make_zero", "-y", out])
        want = sum(self._dur(p) for p in segs)
        got = self._dur(out) if not mixed else -1
        if mixed or abs(got - want) > 0.4:
            W, H = sizes.get(segs[0], (0, 0))
            if mixed and W and H:
                print("[Vanco] 分辨率不一致，重编码并统一到 %dx%d" % (W, H))
                ins = []
                for p in segs:
                    ins += ["-i", p]
                fc = "".join(
                    "[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
                    "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1[v%d];" % (i, W, H, W, H, i)
                    for i in range(len(segs)))
                fc += "".join("[v%d][%d:a]" % (i, i) for i in range(len(segs)))
                fc += "concat=n=%d:v=1:a=1[v][a]" % len(segs)
                subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error"] + ins +
                               ["-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                                "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                                "-c:a", "aac", "-b:a", "192k", "-y", out])
                print("[Vanco] 统一尺寸后重编码完成")
                return out
            print("[Vanco] 无损拼接时长不符(%.2f vs %.2f)，改重编码" % (got, want))
            subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error",
                            "-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", lst,
                            "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "192k", "-y", out])
            got = self._dur(out)
            print("[Vanco] 重编码后时长: %.2f" % got)
        if seam != "关" and len(segs) >= 2:
            try:
                self._seam_fade(segs, out, 0.12, color="色彩对齐" in seam)
            except Exception as e:
                print("[Vanco] 接缝处理失败，保留原始拼接:", e)
        print("[Vanco] 拼接 %d 段 -> %s" % (len(segs), out))
        return out

    def _seam_fade(self, segs, out, dur=0.12, color=False):
        """每两段之间 0.12 秒交叉淡化；可选统一色彩。"""
        durs = [self._dur(p) for p in segs]
        if min(durs) <= dur * 3:
            print("[Vanco] 段太短，跳过接缝淡化")
            return
        ins = []
        for p in segs:
            ins += ["-i", p]
        v, a = [], []
        acc = 0.0
        vprev, aprev = "[0:v]", "[0:a]"
        for i in range(1, len(segs)):
            acc += durs[i - 1]
            off = acc - dur * i
            vlab = "[v%d]" % i if i < len(segs) - 1 else "[vout]"
            alab = "[a%d]" % i if i < len(segs) - 1 else "[aout]"
            pre = ""
            if color and i == 1:
                pre = ""
            v.append("%s%s[%d:v]xfade=transition=fade:duration=%.3f:offset=%.3f%s"
                     % (vprev, "pre" if pre else "", i, dur, max(0.0, off), vlab)
                     if False else
                     "%s[%d:v]xfade=transition=fade:duration=%.3f:offset=%.3f%s"
                     % (vprev, i, dur, max(0.0, off), vlab))
            a.append("%s[%d:a]acrossfade=d=%.3f%s" % (aprev, i, dur, alab))
            vprev, aprev = vlab, alab
        fc = ";".join(v + a)
        cmd = ([_ffmpeg(), "-hide_banner", "-loglevel", "error"] + ins +
               ["-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-y", out])
        r = subprocess.run(cmd, capture_output=True, text=True, errors="ignore")
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "")[-400:])
        print("[Vanco] 接缝淡化完成（%d 个接缝，每个 %.2fs）" % (len(segs) - 1, dur))

    def _last_frames(self, mp4, count):
        """抽 mp4 最后 count 帧，返回 [T,H,W,C] float 张量。帧数裁到 17k+5。"""
        import tempfile
        import numpy as np
        from PIL import Image as _I
        import torch
        tmp = tempfile.mkdtemp(prefix="vanco_ref_")
        try:
            subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error",
                            "-sseof", "-%d" % (count + 2), "-i", mp4,
                            os.path.join(tmp, "%05d.png")], check=False)
            fs = sorted(os.listdir(tmp))
            if not fs:
                return None
            arr = np.stack([np.asarray(_I.open(os.path.join(tmp, f)).convert("RGB"))
                            for f in fs[-count:]])
            n = arr.shape[0]
            while n % 17 != 5 and n > 5:
                n -= 1
            arr = arr[:n]
            return torch.from_numpy(arr.astype(np.float32) / 255.0)
        except Exception as e:
            print("[Vanco] 抽参考帧失败:", e)
            return None
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

    def _head_frame(self, mp4):
        """抽分段的第一帧。"""
        import tempfile
        import numpy as np
        from PIL import Image as _I
        import torch
        tmp = tempfile.mkdtemp(prefix="vanco_head_")
        try:
            p = os.path.join(tmp, "first.png")
            subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", mp4,
                            "-frames:v", "1", "-y", p], check=False)
            if not os.path.exists(p):
                return None
            a = np.asarray(_I.open(p).convert("RGB")).astype(np.float32) / 255.0
            return torch.from_numpy(a).unsqueeze(0)
        except Exception as e:
            print("[Vanco] 抽首帧失败:", e)
            return None
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

    def _condition_fl(self, clip, vae, prompt, w, h, n, first_img, last_img):
        import nodes as cn
        out = cn.NODE_CLASS_MAPPINGS["MiniMaxH3ImageToVideo"].execute(
            clip=clip, vae=vae, prompt=prompt, width=w, height=h, length=n,
            first_frame=first_img, last_frame=last_img)
        r = getattr(out, "result", out)
        return r[0], r[1]

    def _tail_frame(self, mp4):
        """从已有分段里抽最后一帧，作为下一段的起点。优先用同名 _last.png（无损）。"""
        png = os.path.splitext(mp4)[0] + "_last.png"
        try:
            if os.path.exists(png):
                import numpy as _np
                from PIL import Image as _I2
                import torch as _t2
                a = _np.asarray(_I2.open(png).convert("RGB")).astype(_np.float32) / 255.0
                print("[Vanco] 尾帧取自 PNG（无损）:", os.path.basename(png))
                return _t2.from_numpy(a).unsqueeze(0)
        except Exception as _e:
            print("[Vanco] PNG 尾帧读取失败，回退 mp4:", _e)
        import tempfile
        import numpy as np
        from PIL import Image as _I
        import torch
        tmp = tempfile.mkdtemp(prefix="vanco_tail_")
        try:
            subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error",
                            "-sseof", "-0.6", "-i", mp4, "-update", "1",
                            os.path.join(tmp, "last.png")], check=False)
            p = os.path.join(tmp, "last.png")
            if not os.path.exists(p):
                return None
            a = np.asarray(_I.open(p).convert("RGB")).astype(np.float32) / 255.0
            return torch.from_numpy(a).unsqueeze(0)
        except Exception as e:
            print("[Vanco] 抽尾帧失败:", e)
            return None
        finally:
            import shutil as _sh
            _sh.rmtree(tmp, ignore_errors=True)

    def _res(self, path):
        try:
            r = subprocess.run([_ffmpeg(), "-hide_banner", "-i", path],
                               capture_output=True, text=True, errors="ignore")
            import re as _re
            m = _re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr or "")
            if m:
                return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
        return (0, 0)

    def _dur(self, path):
        """读视频时长（秒）。"""
        try:
            r = subprocess.run([_ffmpeg(), "-hide_banner", "-i", path],
                               capture_output=True, text=True, errors="ignore")
            import re as _re
            m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", r.stderr or "")
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            pass
        return 0.0

    def _read_back(self, mp4):
        """把整条成片解码回帧 + 音频，交给画布。"""
        import tempfile
        import numpy as np
        from PIL import Image as _I
        import torch
        tmp = tempfile.mkdtemp(prefix="vanco_rb_")
        subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", mp4,
                        "-vf", "fps=24", os.path.join(tmp, "%05d.png")], check=True)
        files = sorted(os.listdir(tmp))
        arr = np.stack([np.asarray(_I.open(os.path.join(tmp, f)).convert("RGB")) for f in files])
        frames = torch.from_numpy(arr.astype(np.float32) / 255.0)
        wav = os.path.join(tmp, "a.wav")
        subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", mp4,
                        "-vn", "-ac", "1", "-ar", "44100", "-y", wav])
        audio = None
        try:
            import wave
            with wave.open(wav, "rb") as w:
                raw = w.readframes(w.getnframes())
                pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                audio = {"waveform": torch.from_numpy(pcm).reshape(1, 1, -1),
                         "sample_rate": w.getframerate()}
        except Exception as e:
            print("[Vanco] 回读音频失败:", e)
        import shutil as _sh
        _sh.rmtree(tmp, ignore_errors=True)
        print("[Vanco] 回读帧:", tuple(frames.shape))
        return frames, audio

    def _join_audio(self, audios):
        """把每段的音频首尾相接，避免合并后只有第一段有声。"""
        if not audios:
            return None
        import torch
        ws, sr = [], None
        for a in audios:
            w = a.get("waveform")
            if w is None:
                continue
            w = w.cpu() if hasattr(w, "cpu") else w
            if w.dim() == 1:
                w = w.unsqueeze(0).unsqueeze(0)
            elif w.dim() == 2:
                w = w.unsqueeze(0)
            ws.append(w)
            sr = a.get("sample_rate", sr or 44100)
        if not ws:
            return None
        try:
            cat = torch.cat(ws, dim=-1)
        except Exception as e:
            print("[Vanco] 音频拼接失败，退回第一段:", e)
            return audios[0]
        print("[Vanco] 音频合并:", tuple(cat.shape), "sr", sr)
        return {"waveform": cat, "sample_rate": int(sr or 44100)}

    def _concat(self, seg_files, 剧本名, stamp):
        """把分段无损拼成一条，放到剧本目录的「成片」下。"""
        if not seg_files:
            return None
        out_dir = os.path.join(folder_paths.get_output_directory(), "视频合集", "Vanco", "多段导演台",
                               str(getattr(self, "_剧名", "") or "未命名剧本"), "成片")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "合并-%s.mp4" % stamp)
        lst = os.path.join(out_dir, "_list_%s.txt" % stamp)
        with open(lst, "w", encoding="utf-8") as f:
            for p in seg_files:
                f.write("file '%s'\n" % p.replace("\\", "/"))
        subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", lst, "-c", "copy", "-y", out])
        os.remove(lst)
        print("[Vanco] 成片已合并:", out)
        return out

    def _merge(self, files, out):
        if not files:
            return
        lst = os.path.join(tempfile.gettempdir(), "vanco_cat_%s.txt" % stamp)
        with open(lst, "w", encoding="utf-8") as f:
            for p in files:
                f.write("file '%s'\n" % p.replace("\\", "/"))
        subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", lst, "-c", "copy", "-y", out])


class VancoScript:
    """独立分镜文本框：输出整篇剧本，接到「分段引擎」的分镜输入。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "分镜文本": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("分镜文本",)
    FUNCTION = "run"
    CATEGORY = CAT
    DESCRIPTION = "贴整篇分镜（[n] 续接=… 角色=… 秒=…），接到分段引擎。"

    def run(self, 分镜文本):
        return (分镜文本,)


class VancoSR:
    CATEGORY = "Vanco/超分"

    """独立超分：接在 CreateVideo 之后、SaveVideo 之前；不想用就把节点 Ctrl+B 旁路。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "视频": ("VIDEO",),
                "启用超分": ("BOOLEAN", {"default": True, "label_on": "开", "label_off": "关"}),
                "超分模型": ([x for x in folder_paths.get_filename_list("recavsr") if "transformer" in x.lower()] or ["transformer_int8_convrot.safetensors"],),
                "倍数": ("FLOAT", {"default": 2.0, "min": 1.0, "max": 4.0, "step": 0.25}),
                "对色": (["adain", "wavelet", "none"], {"default": "adain"}),
                "解码器": (["flashdecoder", "vae"], {"default": "flashdecoder"}),
                "内核": (["fast", "exact"], {"default": "fast"}),
                "省显存": ("BOOLEAN", {"default": False}),
                "编码器": (["auto", "hevc nvenc", "h264 nvenc", "h264"], {"default": "auto"}),
                "种子": ("INT", {"default": 1, "min": 0, "max": 2**31}),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("视频",)
    FUNCTION = "run"
    CATEGORY = CAT

    def run(self, 视频, 启用超分, 超分模型, 倍数, 对色, 解码器, 内核, 省显存, 编码器, 种子):
        if not 启用超分:
            print("[Vanco] 超分关闭，直通")
            return (视频,)
        import nodes as cn
        L = cn.NODE_CLASS_MAPPINGS["ReCaVSRLoader"]
        m = L.execute(transformer=超分模型)
        mv = getattr(m, "result", m)[0]
        up = cn.NODE_CLASS_MAPPINGS["ReCaVSRUpscale"]
        out = up.execute(model=mv, scale=倍数, color_fix=对色, seed=种子, decoder=解码器,
                         kernels=内核, kv_offload=省显存, encoder=编码器, video=视频)
        return (getattr(out, "result", out)[0],)


class VancoRelaySR:
    CATEGORY = "Vanco/超分"

    """RelayVSR 超分（封装）：只暴露 Detail，其余用固定最优值。"""

    @classmethod
    def INPUT_TYPES(cls):
        unets = [x for x in folder_paths.get_filename_list("diffusion_models") if "relayvsr" in x.lower()]
        vaes = [x for x in folder_paths.get_filename_list("vae") if "relayvsr" in x.lower()]
        return {
            "required": {
                "视频": ("VIDEO",),
                "启用": ("BOOLEAN", {"default": True, "label_on": "开", "label_off": "关"}),
                "主模型": (unets or ["未找到 relayvsr 模型"],),
                "解码VAE": (vaes or ["未找到 relayvsr VAE"],),
                "Detail": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 1.0, "step": 0.05}),
                "种子": ("INT", {"default": 123456789, "min": 0, "max": 2**31, "control_after_generate": True}),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("视频",)
    FUNCTION = "run"
    CATEGORY = CAT

    def run(self, 视频, 启用, 主模型, 解码VAE, Detail, 种子):
        if not 启用:
            print("[Vanco] Relay 超分关闭，直通")
            return (视频,)
        import nodes as cn
        un = cn.NODE_CLASS_MAPPINGS["UNETLoader"].execute(unet_name=主模型, weight_dtype="default")
        un = getattr(un, "result", un)[0]
        va = cn.NODE_CLASS_MAPPINGS["VAELoader"].execute(vae_name=解码VAE)
        va = getattr(va, "result", va)[0]
        comp = cn.NODE_CLASS_MAPPINGS["GetVideoComponents"].execute(video=视频)
        c = getattr(comp, "result", comp)
        frames, audio, fps = c[0], c[1], (c[2] if len(c) > 2 else 24)
        cond = cn.NODE_CLASS_MAPPINGS["RelayVSRConditioning"].execute(model=un, images=frames)
        cd = getattr(cond, "result", cond)
        pos, lat = cd[0], cd[1]
        zero = cn.NODE_CLASS_MAPPINGS["ConditioningZeroOut"].execute(conditioning=pos)
        neg = getattr(zero, "result", zero)[0]
        ks = cn.NODE_CLASS_MAPPINGS["KSampler"].execute(model=un, seed=种子, steps=1, cfg=1.0,
                                                        sampler_name="euler", scheduler="simple",
                                                        positive=pos, negative=neg, latent_image=lat,
                                                        denoise=1.0)
        ks = getattr(ks, "result", ks)[0]
        dec = cn.NODE_CLASS_MAPPINGS["VSRDecode"].execute(vae=va, samples=ks, images=frames, detail=Detail)
        img = getattr(dec, "result", dec)[0]
        vid = cn.NODE_CLASS_MAPPINGS["CreateVideo"].execute(images=img, audio=audio, fps=float(fps or 24))
        print("[Vanco] Relay 超分完成")
        return (getattr(vid, "result", vid)[0],)


NODE_CLASS_MAPPINGS = {"VancoScript": VancoScript, "VancoChainEngine": VancoChainEngine, "VancoSR": VancoSR, "VancoRelaySR": VancoRelaySR}
NODE_DISPLAY_NAME_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS.update({"VancoScript": "★ 分镜文本", "VancoRelaySR": "★ RelayVSR 超分（可旁路）", "VancoSR": "★ 超分（ReCaVSR，可旁路）", "VancoChainEngine": "★ 分段引擎（一键出片）"})
