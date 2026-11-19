import { app } from "../../scripts/app.js";

// Vanco · 引擎参数前缀分组（只改显示文字，不碰控件、不碰布局，零风险）
const GROUPS = [
  ["①", ["步数", "采样器", "调度器", "种子", "control_after_generate"]],
  ["②", ["开二采", "二采模型", "二采倍数", "二采步数", "二采降噪"]],
  ["③", ["参考尺寸"]],
];

const NICE = {
  control_after_generate: "种子控制",
};

const MAP = {};
for (const [mark, names] of GROUPS) for (const n of names) MAP[n] = mark;

function relabel(node) {
  if (!node.widgets) return;
  for (const w of node.widgets) {
    const mark = MAP[w.name];
    if (!mark) continue;
    if (w.__vancoOrig === undefined) {
      w.__vancoOrig = w.label ?? (NICE[w.name] || w.name);
    }
    const base = NICE[w.name] || w.__vancoOrig;
    const want = `${mark} ${base}`;
    if (w.label !== want) w.label = want;
  }
  app.graph?.setDirtyCanvas(true, true);
}

app.registerExtension({
  name: "Vanco.GroupPrefix",
  nodeCreated(node) {
    if (node.type === "VancoChainEngine") setTimeout(() => relabel(node), 40);
  },
  async afterConfigureGraph() {
    for (const n of app.graph?._nodes || []) {
      if (n.type === "VancoChainEngine") relabel(n);
    }
  },
});
