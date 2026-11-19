import { app } from "../../scripts/app.js";

// Vanco · 剧本名 → SaveVideo 输出路径自动同步
const PREFIX = "视频合集/Vanco/多段导演台";

function saveNodes() {
  const out = [];
  const walk = (nodes) => {
    for (const n of nodes || []) {
      if (n.type === "SaveVideo" && !(n.title || "").includes("超分")) out.push(n);
      if (n.subgraph) walk(n.subgraph._nodes);
    }
  };
  walk(app.graph?._nodes);
  return out;
}

function syncFrom(node) {
  const w = node.widgets?.find((x) => x.name === "剧本名");
  if (!w) return;
  const name = String(w.value || "未命名剧本").trim() || "未命名剧本";
  const prefix = `${PREFIX}/${name}/成片/MiniMax_H3-多段导演台-%date:yyyyMMddhhmmss%`;
  for (const sv of saveNodes()) {
    const pw = sv.widgets?.find((x) => x.name === "filename_prefix");
    if (pw && pw.value !== prefix) {
      pw.value = prefix;
      if (pw.inputEl) pw.inputEl.value = prefix;
    }
  }
  app.graph?.setDirtyCanvas(true, true);
}

function hookEngine(node) {
  if (node.__vancoSync) return;
  const w = node.widgets?.find((x) => x.name === "剧本名");
  if (!w) return;
  node.__vancoSync = true;
  const orig = w.callback;
  w.callback = function () {
    const r = orig?.apply(this, arguments);
    syncFrom(node);
    return r;
  };
  const el = w.inputEl;
  if (el) el.addEventListener("change", () => syncFrom(node));
}

// 引擎外接分镜后，隐藏内部那个扁文本框
function hideTextWidgetWhenLinked(node) {
  const inp = (node.inputs || []).find((i) => i.name === "分镜输入");
  const w = (node.widgets || []).find((x) => x.name === "分镜文本");
  if (!inp || !w) return;
  const linked = inp.link != null;
  if (linked && !w.__vancoHidden) {
    w.__vancoHidden = true;
    w.__origType = w.type;
    w.__origCompute = w.computeSize;
    w.computeSize = () => [0, -4];
    w.type = "hidden";
    node.setSize([node.size[0], Math.max(160, node.size[1] - 120)]);
    app.graph?.setDirtyCanvas(true, true);
  } else if (!linked && w.__vancoHidden) {
    w.__vancoHidden = false;
    w.type = w.__origType || "customtext";
    if (w.__origCompute) w.computeSize = w.__origCompute;
    else delete w.computeSize;
    app.graph?.setDirtyCanvas(true, true);
  }
}

app.registerExtension({
  name: "Vanco.SyncScriptName",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "VancoChainEngine") return;
    const orig = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function () {
      const r = orig?.apply(this, arguments);
      try { hideTextWidgetWhenLinked(this); } catch (e) {}
      return r;
    };
  },
  nodeCreated(node) {
    if (node.type === "VancoChainEngine") {
      hookEngine(node);
      setTimeout(() => { syncFrom(node); hideTextWidgetWhenLinked(node); }, 50);
    }
  },
  async afterConfigureGraph() {
    for (const n of app.graph?._nodes || []) {
      if (n.type === "VancoChainEngine") {
        hookEngine(n);
        syncFrom(n);
        hideTextWidgetWhenLinked(n);
      }
    }
  },
});
