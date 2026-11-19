import { app } from "../../scripts/app.js";

// Vanco · 设置联动：互斥/依赖的选项自动纠正，避免"设了却不生效"
const RULES = {
  // 📦 输出设置
  VancoOutSet: function (node) {
    const get = (n) => node.widgets?.find((w) => w.name === n);
    const 成片只存画布 = get("成片只存画布");
    const 引擎也存成片 = get("引擎也存成片");
    const 省内存模式 = get("省内存模式");

    if (省内存模式?.value) {
      if (成片只存画布 && 成片只存画布.value) 成片只存画布.value = false;
      if (引擎也存成片 && 引擎也存成片.value) 引擎也存成片.value = false;
    }
    if (成片只存画布?.value && 引擎也存成片?.value) {
      引擎也存成片.value = false;
    }
  },

  // 🔁 重跑设置
  VancoRunSet: function (node) {
    const get = (n) => node.widgets?.find((w) => w.name === n);
    const n = get("只跑第N段");
    if (!n) return;
    if (Number(n.value) === 0) {
      const a = get("重跑后交给画布");
      const b = get("精确重跑");
      if (a && a.value) a.value = false;
      if (b && b.value && b.value !== "关") b.value = "关";
    }
  },

  // 🔍 衔接与质检
  VancoQcSet: function (node) {
    const get = (n) => node.widgets?.find((w) => w.name === n);
    const 检测 = get("人物检测");
    const 裁空镜 = get("自动裁空镜");
    if (检测 && !检测.value && 裁空镜 && 裁空镜.value) {
      裁空镜.value = false;
    }
  },
};

function bind(node) {
  const rule = RULES[node.comfyClass] || RULES[node.type];
  if (!rule) return;
  if (node.__vancoLinked) return;
  node.__vancoLinked = true;

  // 包装控件的 callback，任一变化就重跑规则
  for (const w of node.widgets || []) {
    const orig = w.callback;
    w.callback = function () {
      const r = orig?.apply(this, arguments);
      try {
        rule(node);
        node.setDirtyCanvas?.(true, true);
        app.graph?.setDirtyCanvas(true, true);
      } catch (e) { /* 忽略 */ }
      return r;
    };
  }
  try { rule(node); } catch (e) { /* 忽略 */ }
}

app.registerExtension({
  name: "Vanco.SettingLinkage",
  nodeCreated(node) {
    if (["VancoOutSet", "VancoRunSet", "VancoQcSet"].includes(node.comfyClass || node.type)) {
      setTimeout(() => bind(node), 40);
    }
  },
  async afterConfigureGraph() {
    for (const n of app.graph?._nodes || []) bind(n);
  },
});
