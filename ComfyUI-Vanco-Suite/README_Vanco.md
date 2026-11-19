# Vanco 导演台 · 长期记忆（交接用）

> 这份文件写给"接手的 AI/人"。读完它你应该能在**不重新踩坑**的前提下接手这套 ComfyUI 短剧流水线。
> 最后更新：2026-11-16

---

## 〇、一句话概况

用户（Vanco）在自己的 Windows 机器上，用 ComfyUI + MiniMax-H3 模型，做**自建的多段短剧生成流水线**：
在界面里贴一段分镜文本 → 一次运行自动逐段生成 → 自动接尾帧/换场景 → 拼接 → 可选超分 → 带元数据保存。

核心诉求：**"我只需要调参数、贴剧本、点生成，它就一段段跑出来。"** 不要脚本、不要拖 bat、不要在软件外操作。

---

## 一、环境（精确值）

| 项 | 值 |
|---|---|
| 系统 | Windows，RTX 5070 Ti 16GB，68GB 内存 |
| ComfyUI | 0.45.0，路径 `D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-Vanco\ComfyUI` |
| 共享 input/output | `D:\Comfy-Desktop\ComfyUI-Shared\input` / `...\output` |
| 独立 Python（跑脚本用） | `D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-Vanco\standalone-env\python.exe` |
| ComfyUI 端口 | 8188（API：`/prompt`、`/history/<id>`、`/object_info`） |
| 日志 | `D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-Vanco\logs\comfyui.log` |
| 工作目录（我的） | `E:\System default\文档\deepseek-harness\default-workspace` |

**注意**：`standalone-env` 里**没有 torch**，不能直接 import comfy。要在 ComfyUI 里挂节点才能测运行时行为。

---

## 二、节点包（唯一启用）

路径：`custom_nodes\ComfyUI-Vanco-Suite\`（一个包，内部三块）

```
ComfyUI-Vanco-Suite/
├── __init__.py          # 汇总注册（sys.path 注入 + 合并 NODE_CLASS_MAPPINGS）
├── vanco_h3/            # H3 模型加载器 / LoRA 24 槽加载器（源自 AICG3D 改版，已改名去痕）
├── vanco_studio/        # 自研：素材面板/参数盒/分镜文本/分段引擎/两个超分
├── vanco_prompt/        # 提示词管理器
└── web/                 # 前端（只有 5 个文件在用，见下）
```

`web/` 里**有效文件只有**：
- `vanco_assets.js` —— 素材网格
- `vanco-lora-panel.js` —— LoRA 24 槽面板
- `vanco-engine-panel.js` —— 分段引擎参数面板
- `vanco-sync.js` —— 剧本名 → SaveVideo 路径同步 + 外接分镜时隐藏文本框
- `prompt_manager.js` —— 提示词管理器
- `vanco-group.js.disabled` —— **故意停用**（它给控件加 ①②③ 前缀，会和引擎面板抢标签）

**旧包全部在 `custom_nodes\.disabled\`**（ComfyUI 不加载隐藏目录）：
`ComfyUI-Vanco-Studio`、`ComfyUI-MiniMax_H3-AICG3D-Vanco`、`ComfyUI-PromptManager-Vanco`

---

## 三、节点清单与参数（用户日常用到的）

### 1. `★ 素材面板（多图上传）` — `VancoAssetGrid`

- 3 列网格，点 **＋** 多选上传（存到 `input/` 根目录），点 **×** 删除
- 每格底部有**名字输入框**（默认取文件名，可改成中文名）——这个名字就是剧本里 `新图:XXX` 要匹配的名字
- 每格左右有 **◀ ▶** 调序（**不是拖拽**：浏览器原生拖拽会被画布吃掉）
- 输出：`图片批次(IMAGE)`、`名字列表(STRING，名字用 " / " 分隔)`、`张数(INT)`
- 参数：`缺图处理`（跳过 / 报错）
- **状态存在 widget `assets_json` 里**，跟着工作流保存；加载时靠 `onConfigure` 重新解析（否则会丢图）

### 2. `★ 参数盒（比例/像素/秒）` — `VancoParamBox`

- 输入：`画幅比例`(16:9 等)、`百万像素`、`每段秒数`、`对齐倍数`(32)
- 输出：`宽`、`高`（对齐到 32 的倍数）、`帧数`（对齐 17k+5）、`秒数`
- 用户**经常改**比例/百万像素，所以宽高走**连线**进引擎

### 3. `★ 分镜文本` — `VancoScript`

- 一个大文本框，输出整篇分镜（STRING）
- 接到引擎的 `分镜输入`；**接上后引擎内部的文本框会自动隐藏**（`vanco-sync.js` 的 `hideTextWidgetWhenLinked`），扯线会恢复（靠 `onConnectionsChange` 监听）

### 4. `★ 分段引擎（一键出片）` — `VancoChainEngine`（核心）

**输入口**（连线）：
`主模型 MODEL`、`文本编码器 CLIP`、`视频VAE`、`音频VAE`、`素材 IMAGE`、`名字列表 STRING`、`默认秒数 FLOAT`、`分镜输入 STRING`
（`宽`/`高` 是 widget 转输入，由参数盒连线传入）

**输出口**：
`合并帧 IMAGE`、`音频 AUDIO`、`段数 INT`、`分段清单 STRING`

**参数（面板已分 5 组，彩色标签行）**：

| 组 | 参数 | 说明 |
|---|---|---|
| ① 基础采样 | 步数 / 采样器 / 调度器 / 种子 / 种子控制 | 种子实际每段用「种子 + 段号」 |
| ② 输出 / 归档 | 保存分段 / 参考尺寸 / 引擎也存成片 / 剧本名 | `剧本名` 决定归档目录，且会同步改 SaveVideo 前缀 |
| ③ 二次采样 | 开二采 / 二采模型 / 放大倍数 / 步数 / 降噪 | 关掉时其余自动变灰不可改 |
| ④ 重跑 | 只跑第N段 / 下游处理 / 精确重跑 / 重跑后交给画布 / 上游已变时 | 只跑=0 时这些自动变灰 |
| ⑤ 接缝 | 接缝处理 / 参考尾帧数 / 尾帧取样 | 见下 |

**关键行为**：
- 解析分镜：按 `[n]` 切块，头行 `续接=…` `角色=…` `秒=…`
- `续接=新图:名字`：在「名字列表」里找名字 → 用那张图；**找不到就用第 1 张（不报错！）**
- `续接=上一段`：用上一段尾帧（`尾帧取样` 决定取最后一帧还是倒数第 2 帧）
- 时长：头行 `秒=` 优先，没写才用 `默认秒数`，再没有用 8；帧数对齐 17k+5
- 端口：`角色=` 目前**只写进 json，不参与选图**（参考图是素材面板全部图片按顺序给进去）
- `保存分段`：每段落盘 `segNN_vN.mp4` + `segNN_vN.json`（含指纹/参数）
- `只跑第N段 > 0`：只生成目标段，其余段复用已有 mp4；`下游处理=级联重跑` 时，后面凡写 `续接=上一段` 的段跟着重跑
- `精确重跑=首尾帧`：重跑时用下一段的**首帧**当终点（`MiniMaxH3ImageToVideo`），避免牵连下游。**已验证：动作差异很大也能接上**
- 重跑模式默认 `重跑后交给画布=false` → 用 `ExecutionBlocker` 阻断画布，只把拼接结果写到 `成片/`，画布不产生文件
- `接缝处理`：`关` / `微淡化`(0.12s xfade) / `微淡化+色彩对齐`；**全跑和重跑都会执行**（全跑时引擎额外拼一份到成片目录）
- 采样核心：单时钟（`BasicGuider + BasicScheduler + SamplerCustomAdvanced`）。**不需要双时钟插件**——ComfyUI 0.45 自带 `comfy/model_sampling.py::ModelSamplingAV`，官方 euler 已是双时钟语义

### 5. `★ 超分（ReCaVSR，可旁路）` — `VancoSR`

- 参数：`启用超分`、`超分模型`（从 `models\recavsr` 扫 `transformer*`）、`倍数`、`对色`(adain/wavelet/none)、`解码器`(flashdecoder/vae)、`内核`(fast/exact)、`省显存`、`编码器`、`种子`
- `启用超分=false` 时原样放行（注意：放行后下游 SaveVideo 仍会存一份副本——这是历史坑，现用组开关规避）

### 6. `★ RelayVSR 超分（可旁路）` — `VancoRelaySR`

- 只暴露：`启用`、`主模型`、`解码VAE`、`Detail`(0.8)、`种子`
- 步数/CFG/采样器写死（1 步 / CFG 1.0 / euler），因为 RelayVSR 是"1 步精修"

---

## 四、主工作流

`user\default\workflows\03_导演台\Vanco-H3-多段导演台(分镜文本·尾帧接力·双超分·V5).json`

链路：

```
VancoH3ModelLoader ──model──→ VancoH3LoraLoader ──model──→ 引擎.主模型
                   └──clip──────────────────────────────→ 引擎.文本编码器
                   └──video_vae / audio_vae─────────────→ 引擎.视频VAE/音频VAE
VancoAssetGrid ──IMAGE──→ 引擎.素材        └──名字列表──→ 引擎.名字列表
VancoParamBox  ──宽/高──→ 引擎（连线）      └──秒数────→ 引擎.默认秒数
VancoScript    ──STRING──→ 引擎.分镜输入
引擎 ──合并帧+音频──→ CreateVideo ─┬→ SaveVideo（原始成片，带元数据）
                                   ├→ VancoSR → SaveVideo（超分成片）
                                   └→ VancoRelaySR → SaveVideo（Relay 成片）
```

- 超分两组各有 **rgthree `Fast Groups Bypasser`** 节点（`开关 · 六、RelayVSR 超分…` / `开关 · 七、ReCaVSR 超分…`），整组旁路 = 变紫跳过、不存文件
- 引擎节点底色被 JS 强制为 `#2b2b2f` / `#3a3a40`

---

## 五、输出约定（用户很在意）

```
output\视频合集\Vanco\多段导演台\<剧本名>\
├── 分段\
│   ├── seg01_v1.mp4 + seg01_v1.json
│   ├── seg02_v1.mp4 …（重跑会 +v2，永不覆盖）
│   └── …
└── 成片\
    └── 合并-<时间戳>.mp4        ← 引擎 ffmpeg 拼接/接缝淡化（无元数据）

output\视频合集\超分\
├── ReCaVSR-<时间戳>_00001_.mp4  ← 扁平，不分目录，模型名即文件名
└── RelayVSR-<时间戳>_00001_.mp4
```

- **原始成片**（画布 SaveVideo 存的、带元数据）落在 `<剧本名>\成片\`，文件名 `MiniMax_H3-多段导演台-<时间戳>_00001_.mp4`
- 命名规律沿用用户既有体系：`模型名-作者-功能-时间戳`（如 `MiniMax_H3-T8-加速双时钟-…`）
- 用户的价值判断：**超分文件不需要按剧分目录**，只按模型区分；原始片才要分剧

---

## 六、踩过的坑（按重要性排序，接手者必读）

### A. ComfyUI 前端 / 节点相关

1. **改 Python 必须重启**，刷新网页无效；改 JS 必须重启 + `Ctrl+F5`
2. **参数错位的根因**：`INPUT_TYPES` 里参数顺序/数量变了，而工作流 JSON 里 `widgets_values` 没同步 → 整排值错位，显示 `UNKNOWN_x`
   → 改参数时**只往末尾追加**，或改完必须重建 JSON
3. **中文 key 可以用**（`缺图处理`、`脚本名` 都正常）
4. **下拉框写法**：`("名字", (列表, {默认}))` 在部分节点会退化成文本框；`VancoSR/VancoChainEngine` 里曾因此错位过。稳法：列表来自真实目录扫描 + 默认值合法
5. **节点 id 一旦改动，旧工作流会红**。已把第三方 id 从 `AICG3D_*` 改成 `Vanco_*`（用户同意重连）
6. **不要用通配删除**：我曾用 `p*.py` 误删 `prompt_*.py` 四个模块，从备份恢复过
7. **别改第三方包的代码**（JZL / AICG3D 原件），作者更新会覆盖。要改就复制到自己的包
8. `addDOMWidget` 的节点**高度不能靠猜**：
   - ❌ 量 `scrollHeight`（容器被拉伸 → 反馈循环 → 越拖越长）
   - ❌ 覆盖 `onResize` 硬拉（和用户拖拽打架）
   - ✅ 用一个 `height:auto` 的**内层容器**量，且用 `last_y`（绘制时写入的真实坐标）当起点
9. **插槽（连线口）是画布层画的**，DOM 面板接管不了；隐藏 widget 会连带插槽/标签消失，`computeSize=()=>[0,-4]` 只压高度不删插槽
10. **前端生命周期钩子要挂全**：`onNodeCreated`、`onConfigure`（载入后取值）、`onConnectionsChange`（连线恢复 UI）。少挂一个就少一个时机（LoRA 面板、素材记忆都栽过）

### B. H3 模型 / 采样相关

11. **H3 是联合 AV 模型**：latent 是音视频打包结构，**必须用 `MiniMaxH3AVDecodeT8` 解码**，普通 `VAEDecode` 会报 `too many indices`
12. 采样入口要用 `BasicGuider + KSamplerSelect + BasicScheduler + SamplerCustomAdvanced`（旧 `comfy.samplers.KSampler` 不接 positive/negative）
13. `VAEDecode().decode(vae, samples)` —— **vae 在前**，参数顺序反了报 `'VAE' object is not subscriptable`
14. `CreateVideo` 在 `comfy_extras/nodes_video.py`，**不在 `nodes.py`**；`SaveVideo.execute(video, prefix, {"format":"auto"}, {"codec":"auto"})` 的 format/codec 要 dict
15. **官方 SaveVideo 在自定义节点里调用拿不到元数据**（`extra_pnginfo` 是 None）→ 想带元数据，必须让画布上的真节点存
16. `MiniMaxH3ReferenceToVideo.execute(clip, prompt, width, height, length, ref_image_size, vae, audio_vae, ref_images, ref_videos, …)`；`ref_videos` 是 `{"ref_video_1": 帧张量[T,H,W,C]}`，帧数会被裁到 17k+5（≥5）
17. `MiniMaxH3ImageToVideo(clip, vae, prompt, width, height, length, first_frame, last_frame)` → `(positive, LATENT)`，**没有 audio_vae**
18. **双时钟不需要装插件**：ComfyUI ≥ `bdcb886` 已内置 `ModelSamplingAV`

### C. 生成质量 / 提示词相关

19. **一条链别超过 3–5 段**（连续 `续接=上一段`）：超过后颜色一段比一段脏、对比度升高、脸变糊（实测 luma 0.578→0.177）。断链 = 换 `新图` 重置
20. **接缝会顿一下**，成因：尾帧是静止图（速度突变）+ 压缩残影 + 模型不复刻像素 + 色彩漂移
    - 有效：`尾帧取样=倒数第2帧`、`接缝处理=微淡化`（0.12s）、`参考尾帧数=1`
    - **无效甚至更差**：`参考尾帧数=22/39`（多帧参考会把构图带偏 → 接缝错位）
21. **中文不能出现在正文里**：会让模型念稿、出字幕。正文全英文，角色用 `<Subject n>` 指代
22. 每段结尾加 `All faces stay fully inside the frame`；末尾加 `No on-screen text, no captions, no subtitles.`
23. 8 秒 = 4 拍（0/2/4/6 秒），**一拍一个动作**；动作跨度大模型会自己加戏然后崩
24. `detailed_description` 第一句必须写死机位/景别，不能用 "cinematic" 空话开头（否则出空镜）
25. 台词要说得快 → **压缩段长**（4–5 秒），不是改文案

### D. 文件 / 路径相关

26. **模型路径分隔符不统一**：`CLIPLoader/UNETLoader/VAELoader` 用**反斜杠**；`VancoH3ModelLoader` 内部转成**正斜杠**；`VancoH3LoraLoader` 用**反斜杠**。改值前先查该控件的选项列表，**以选项为准**
27. **文件名不能有 `:`**：`%date:yyyyMMddhhmmss%` 在界面里会被替换，但走 API 提交不会 → 落盘被截断成 0 字节
28. ffmpeg 拼接 `-c copy` 遇到**分辨率不一致**会出怪现象（某段加速/时长变长）。现在拼接前会查分辨率，不一致就重编码统一
29. `concat -c copy` 时间戳不稳 → 加了 `-fflags +genpts -avoid_negative_ts make_zero`，并**校验总时长**，不符则自动重编码兜底
30. 之前"分段目录扫全目录"把历史版本全拼进去过（22 秒的片）→ 现在用**精确清单**（每段取最新版本）

---

## 七、用户的工作习惯 / 偏好（务必遵守）

- **不要动第三方包**；不要改他的素材目录结构
- 覆盖任何文件前**先备份**
- 每完成一个阶段**备份一次**，命名带阶段（见下）
- **不要让他反复重启**：改完先自检（JS `node --check`、Python import 扫描、JSON 参数比对），过了再叫他重启
- **跑 GPU 前先问**（他注意力在工作上时会拒绝）
- 他喜欢**真开关**，不喜欢 Ctrl+B 手动旁路
- 节点标题要中文；参数要中文
- 说话直白，别绕；给数字比给形容强
- 他会用语音输入，错别字常见（"子母板"=模板、"软件"=ComfyUI、"二彩"=二采）

---

## 八、备份位置

根目录：`E:\Summary of downloaded files\Deepseek Harness works\工作文件\_节点包备份_20261115\`

| 子目录 | 内容 |
|---|---|
| `阶段1_分段保存_完成_20261115_2036` | 阶段 1 完成时的包 + 工作流 |
| `阶段2+3_逐段重跑+首尾帧_完成_20261115_2140` | 重跑/首尾帧完成时 |
| `阶段4_UI改造前_20261115_2216` | UI 改造前 |
| `阶段4b_UI改造前_20261115_2232` | UI 改造前（更新） |
| `suite_before_rename` / `suite_before_idRename` | 去痕改造前 |
| `workflow` | 早期可跑版工作流 |
| `old_web` | 被移走的 `aicg3d-*.js` 等旧前端 |
| `ComfyUI-Vanco-Studio` / `ComfyUI-MiniMax_H3-AICG3D-Vanco` / `ComfyUI-PromptManager-Vanco` | 合并前的三个原始包 |

---

## 九、自检工具（工作目录里）

- `suite_check.py` —— 静态扫节点包所有 `import`，检查模块文件是否存在（防 `No module named`）。用法：`standalone-env\python.exe suite_check.py`
- 工作流校验脚本（临时写的 `p*.py`）—— 把 `widgets_values` 和 `/object_info` 的选项逐一比对
- JS 语法：`node --check <file>`（node 在 `C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`）

**改完必跑这三样，通过再让用户重启。**

---

## 十、当前状态与已知未完成项

### 可用
分段生成 / 尾帧接力 / 按名换场景 / 二采 / 双超分（带组开关）/ 分段保存 / 逐段重跑（只跑、级联）/ 首尾帧精确重跑 / 接缝淡化 / 按剧本名归档 / 素材记忆 / LoRA 24 槽面板（勾选·滑块·±0.1·两步选择）/ 剧本名自动同步

### 遗留
1. **`宽`/`高` 的文字显示**：它们是从参数盒连线进来的 widget，ComfyUI 对这类控件的绘制与普通输入不同；曾尝试隐藏导致插槽消失、连线断。当前策略：**保留原生行，不隐藏**
2. `引擎也存成片` 与 `接缝处理` 有重叠逻辑（都触发引擎拼接），未合并
3. 未做：逐段动态采样预览（架构限制）、双时钟（已确认不需要）
4. 未做：README/LICENSE/发布 GitHub（用户暂时不打算发）

---

## 十一、给接手者的一句话

这套东西的难点**不在功能，在接口**：ComfyUI 的内部节点调用约定、前端生命周期、参数序列化，坑都在这些地方。
所以：**改任何参数/节点结构前，先想清楚 `widgets_values` 会不会错位**；**改任何 import/文件名前，先跑 `suite_check.py`**。
