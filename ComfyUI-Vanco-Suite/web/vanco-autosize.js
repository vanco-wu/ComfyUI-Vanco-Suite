import { app } from "../../scripts/app.js";

// Vanco · 节点自动高度：纵向永远贴合内容，横向保持用户拉的宽度
// 覆盖范围：本包全部节点
const TYPES = [
  "VancoChainEngine", "VancoScript", "VancoAssetGrid", "VancoParamBox",
  "VancoSR", "VancoRelaySR", "VancoH3ModelLoader", "VancoH3LoraLoader",
  "VancoOutSet", "VancoRunSet", "VancoQcSet",
];
const MIN_H = 60;

function fit(node) {
  if (!node || !TYPES.includes(node.comfyClass || node.type)) return;
  try {
    const sz = node.computeSize();
    if (!sz || !sz[1]) return;
    const w = node.size[0];
    const h = Math.max(MIN_H, Math.round(sz[1]));
    if (Math.abs(node.size[1] - h) > 2) {
      node.setSize([w, h]);
      node.setDirtyCanvas?.(true, true);
    }
  } catch (e) { /* 某些节点计算尺寸会抛错，忽略 */ }
}

function fitAll() {
  for (const n of app.graph?._nodes || []) fit(n);
}

app.registerExtension({
  name: "Vanco.AutoHeight",
  async nodeCreated(node) {
    // 两拍：控件建好后、DOM 面板渲染后再量一次
    setTimeout(() => fit(node), 50);
    setTimeout(() => fit(node), 260);
  },
  async afterConfigureGraph() {
    setTimeout(fitAll, 60);
    setTimeout(fitAll, 320);
  },
  async setup() {
    // 拖动节点 / 缩放画布后不强制重排，只在打开和新建时贴合
    setTimeout(fitAll, 800);
  },
});
