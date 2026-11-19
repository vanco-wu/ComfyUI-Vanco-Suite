import { app } from "../../scripts/app.js";

// Vanco · 引擎瘦身：被「设置台」接管的参数，在引擎节点上隐藏
// 值仍然保留在工作流里（不删 schema），所以旧工作流不会错位。
const TARGET = "VancoChainEngine";

const HIDDEN = [
  "保存分段", "引擎也存成片", "剧本名", "省内存模式", "段间清理",
  "只跑第N段", "重跑后交给画布", "上游已变时", "下游处理", "精确重跑",
  "硬接模式", "接缝处理", "参考尾帧数", "尾帧取样",
  "人物检测", "检测帧数", "自动裁空镜", "成片只存画布",
];

function slim(node) {
  if (node.__vancoSlimmed) return;
  node.__vancoSlimmed = true;
  for (const name of HIDDEN) {
    const w = node.widgets?.find((x) => x.name === name);
    if (w) {
      w.computeSize = () => [0, -4];
      w.type = "hidden";
    }
    const idx = (node.inputs || []).findIndex((x) => x?.name === name);
    if (idx >= 0) node.inputs.splice(idx, 1);
  }
  // 底部提示
  try {
    const dom = document.createElement("div");
    dom.textContent = "其余开关在「📦 输出设置 / 🔁 重跑设置 / 🔍 衔接与质检」三个节点上";
    dom.style.cssText = "font-size:10px;color:#8a7a99;padding:2px 4px;";
    const w = node.addDOMWidget("vanco_slim_hint", "提示", dom, { serialize: false, hideOnZoom: true });
    w.computeSize = () => [node.size[0] - 20, 16];
  } catch (e) { /* 忽略 */ }
  // 高度统一交给 vanco-autosize.js 处理
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "Vanco.EngineSlim",
  nodeCreated(node) {
    if (node.comfyClass === TARGET || node.type === TARGET) setTimeout(() => slim(node), 30);
  },
  async afterConfigureGraph() {
    for (const n of app.graph?._nodes || []) {
      if (n.type === TARGET) {
        slim(n);
        try {
          const sz = n.computeSize();
          if (sz && sz[1] && n.size[1] > sz[1] + 6) n.setSize([n.size[0], sz[1]]);
        } catch (e) { /* 忽略 */ }
      }
    }
  },
});
