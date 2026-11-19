# Vanco 分镜编排引擎

给 ComfyUI + MiniMax-H3 用的多段视频编排节点包。写一份分镜脚本、传一组素材图，一次运行逐段生成、自动衔接、拼成成片；某一段不满意可以单独重跑，不必整条重来。

## 特点

- **逐段选图**：每段用 `图=2,3,5` 指定素材，不必全部喂进去
- **接法自由**：每段可选「接上一段尾帧」或「换成新场景图」，也可启用首帧硬锚定
- **单段可修**：只跑第 N 段，或级联重跑后续段落
- **超分可选**：ReCaVSR / RelayVSR 二选一，不影响生成流程

另外包含：逐段色彩归一、链长提示、人物检测与空镜裁剪、分段耗时日志、运行报告、警告浮层。

## 目录

```
ComfyUI-Vanco-Suite/   节点包（放进 ComfyUI/custom_nodes/）
docs/                  提示词模板 v1、v2
workflows/             示例工作流（分镜编排引擎 v1）
安装说明.md             三步安装、参数说明、常见问题
```

## 安装

1. 把 `ComfyUI-Vanco-Suite` 放进 `ComfyUI/custom_nodes/`
2. 重启 ComfyUI
3. 导入 `workflows/Vanco-H3-分镜编排引擎-v1.json`，选自己的模型与 LoRA

详细步骤见 [安装说明.md](安装说明.md)。

## 环境

- ComfyUI（0.45 左右）
- MiniMax-H3 模型：双主干 / 文本编码器 / 视频 VAE / 音频 VAE
- 可选：`models/yolo/yolov8n.onnx`（人物检测）
- 可选：ReCaVSR 或 RelayVSR 节点包（用超分时）

本包不需要额外 pip 依赖。

## 许可

由 Vanco 编写的代码采用 GPL-3.0-or-later，见 [ComfyUI-Vanco-Suite/LICENSE](ComfyUI-Vanco-Suite/LICENSE)。
第三方组件与依赖见 [ComfyUI-Vanco-Suite/THIRD_PARTY_NOTICES.md](ComfyUI-Vanco-Suite/THIRD_PARTY_NOTICES.md)。
模型权重与 MiniMax 官方提示词内容不在本仓库内。
