# 第三方组件与依赖声明

本仓库 `ComfyUI-Vanco-Suite` 的**自有代码**（`__init__.py`、`vanco_studio/`、`vanco_prompt/`、`web/`）
版权归 Vanco 所有，按 **GPL-3.0-or-later** 发布，全文见仓库根目录 `LICENSE`。

本包**不再包含**任何上游插件的源代码副本（2026-11-17 起已全部移除）。以下为**运行时依赖**，
需由使用者自行安装，各自适用其自身许可证。

---

## 1. ComfyUI（必需）

- 许可证：GPL-3.0
- 提供：核心执行引擎、采样器、VAE / CLIP / 模型加载 API、`comfy_extras` 中的
  `MiniMaxH3ReferenceToVideo`、`MiniMaxH3ImageToVideo`、`MiniMaxH3LatentUpscaleWithModel`、
  `CreateVideo`、`SaveVideo` 等节点。

## 2. minimax-h3-audio-T8（必需）

- 提供：`MiniMaxH3AVDecodeT8`（音视频 latent 解码）
- 本包的导演台在解码 AV latent 时调用该节点。缺失时引擎会在解码阶段报错。
- 许可证以该仓库为准。

## 3. ComfyUI-ReCaVSR（可选）

- 提供：`ReCaVSRLoader` / `ReCaVSRUpscale`
- 仅在启用「超分（ReCaVSR）」节点时需要。
- 许可证以该仓库为准。

## 4. RelayVSR（可选）

- 仅在启用「RelayVSR 超分」节点时需要；权重与节点由对应仓库提供。
- 许可证以该仓库为准。

## 5. ultralytics / YOLO 模型（可选）

- 本包**不依赖** `ultralytics` 库；人物检测使用 ONNX Runtime 直接推理 `yolov8n.onnx`。
- 若启用「人物检测」，需自行放置 `models/yolo/yolov8n.onnx`。
- YOLOv8 模型由 Ultralytics 发布，适用 AGPL-3.0；ONNX Runtime 适用 MIT。

## 6. 模型权重（不分发）

- MiniMax-H3 主干（FL2VA / REF2VA）、文本编码器、视频 / 音频 VAE 均**不随本仓库分发**。
- 使用需遵守 MiniMax H3 Community License Agreement（含地域与用途限制，详见其官方许可）。
- `MiniMax` / `MiniMax H3` 商标仅用于描述兼容性。

---

## 提示词内容声明

仓库内 `vanco_prompt/prompt_bank.json` 为**空库**（仅保留分类结构）。
任何提示词内容均由使用者自行维护，不属于本仓库分发内容。
