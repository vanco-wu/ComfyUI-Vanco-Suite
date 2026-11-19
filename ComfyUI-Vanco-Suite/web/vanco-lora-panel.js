import { app } from "../../scripts/app.js";

// Vanco · LoRA 面板（无限槽位版）
// 数据存进节点的隐藏控件 lora_stack（JSON），面板只负责编辑它。
const TYPES = ["VancoH3LoraLoader", "VancoH3Loader"];
const OFF = new Set(["关闭", "none", "None", "无", ""]);
const RECENT_KEY = "vanco.lora.recent";

let OPTIONS = null;
async function loadOptions(type) {
  if (OPTIONS) return OPTIONS;
  const pick = (node) => {
    const inp = { ...(node?.input?.required || {}), ...(node?.input?.optional || {}) };
    for (const key of Object.keys(inp)) {
      const sp = inp[key];
      if (Array.isArray(sp) && Array.isArray(sp[0]) &&
          sp[0].some((v) => String(v).endsWith(".safetensors"))) return sp[0];
    }
    return [];
  };
  try {
    // 本节点已无固定槽位，改从通用 LoRA 列表取候选
    for (const t of [type, "LoraLoader"]) {
      const r = await fetch("/object_info/" + t);
      const j = await r.json();
      const list = pick(j[t]);
      if (list.length) { OPTIONS = list; return OPTIONS; }
    }
    OPTIONS = [];
  } catch (e) {
    OPTIONS = [];
  }
  return OPTIONS;
}

const getRecent = () => { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch (e) { return []; } };
const pushRecent = (v) => {
  const r = [v, ...getRecent().filter((x) => x !== v)].slice(0, 8);
  localStorage.setItem(RECENT_KEY, JSON.stringify(r));
};
const baseName = (p) => String(p || "").replace(/^.*[\\/]/, "");
const groupOf = (path) => {
  const p = String(path).replace(/\//g, "\\");
  const i = p.lastIndexOf("\\");
  return i > 0 ? p.slice(0, i) : "";
};

function parseStack(raw) {
  try {
    const d = JSON.parse(raw || "[]");
    if (!Array.isArray(d)) return [];
    return d.map((it) => ({
      name: String(it?.name ?? it?.[0] ?? ""),
      strength: Number(it?.strength ?? it?.[1] ?? 0),
      enabled: it?.enabled === false ? false : true,
    }));
  } catch (e) {
    return [];
  }
}

app.registerExtension({
  name: "Vanco.LoraPanel",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!TYPES.includes(nodeData.name)) return;
    const orig = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = orig?.apply(this, arguments);
      const node = this;

      const stackW = node.widgets?.find((w) => w.name === "lora_stack");
      if (!stackW) return r;

      // 隐藏旧 24 槽 + 隐藏 stack 控件本身
      const legacy = [];
      const dropInput = (name) => {
        const idx = (node.inputs || []).findIndex((x) => x?.name === name);
        if (idx >= 0) node.inputs.splice(idx, 1);
      };
      for (let i = 1; i <= 24; i++) {
        const w = node.widgets?.find((x) => x.name === `lora_${i}`);
        const s = node.widgets?.find((x) => x.name === `lora_${i}_strength`);
        if (w) { w.computeSize = () => [0, -4]; w.type = "hidden"; dropInput(w.name); }
        if (s) { s.computeSize = () => [0, -4]; s.type = "hidden"; dropInput(s.name); }
        if (w) legacy.push({ name: String(w.value || ""), strength: Number(s?.value ?? 1) });
      }
      stackW.computeSize = () => [0, -4];
      stackW.type = "hidden";
      dropInput("lora_stack");

      // 迁移：新清单为空时，把旧槽位里非空的搬进来
      let list = parseStack(stackW.value);
      if (!list.length) {
        list = legacy.filter((x) => x.name && !OFF.has(x.name));
      }
      const save = () => {
        stackW.value = JSON.stringify(list);
        node.setDirtyCanvas?.(true, true);
        app.graph?.setDirtyCanvas(true, true);
      };

      const root = document.createElement("div");
      root.style.cssText = "display:flex;flex-direction:column;gap:4px;padding:4px;" +
        "background:#241a2b;border:1px solid #4a3560;border-radius:6px;";
      const head = document.createElement("div");
      head.style.cssText = "font-size:11px;color:#b9a7c9;padding:0 2px 2px;";

      function picker(anchor, onPick) {
        const groups = {};
        for (const opt of OPTIONS || []) {
          if (OFF.has(opt)) continue;
          const g = groupOf(opt);
          (groups[g] = groups[g] || []).push(opt);
        }
        const pop = document.createElement("div");
        const r0 = anchor.getBoundingClientRect();
        pop.style.cssText = "position:fixed;z-index:99999;left:" + r0.left + "px;top:" + (r0.bottom + 2) +
          "px;min-width:250px;max-height:330px;overflow:auto;background:#1b1420;border:1px solid #6a4a8a;" +
          "border-radius:6px;box-shadow:0 6px 20px #000a;font-size:11px;color:#e8dcf2;";
        const close = () => pop.remove();
        const item = (label, fn, dim) => {
          const d = document.createElement("div");
          d.textContent = label;
          d.style.cssText = "padding:4px 8px;cursor:pointer;" + (dim ? "color:#8a7a99;" : "");
          d.onmouseenter = () => (d.style.background = "#2d2138");
          d.onmouseleave = () => (d.style.background = "");
          d.onclick = (ev) => { ev.stopPropagation(); fn(); };
          return d;
        };
        const showGroups = () => {
          pop.innerHTML = "";
          pop.appendChild(item("（不加载）", () => { onPick(""); close(); }, true));
          const rec = getRecent().filter((x) => (OPTIONS || []).includes(x));
          if (rec.length) {
            pop.appendChild(item("— 最近使用 —", () => {}, true));
            for (const v of rec) pop.appendChild(item("★ " + baseName(v), () => { onPick(v); pushRecent(v); close(); }));
          }
          for (const g of Object.keys(groups).sort()) {
            pop.appendChild(item("📁 " + (g || "根目录") + "  (" + groups[g].length + ")", () => showFiles(g)));
          }
        };
        const showFiles = (g) => {
          pop.innerHTML = "";
          pop.appendChild(item("← 返回文件夹", showGroups, true));
          for (const v of groups[g]) pop.appendChild(item(baseName(v), () => { onPick(v); pushRecent(v); close(); }));
        };
        showGroups();
        document.body.appendChild(pop);
        const onDoc = (ev) => { if (!pop.contains(ev.target)) { close(); document.removeEventListener("mousedown", onDoc); } };
        setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
      }

      function render() {
        root.innerHTML = "";
        head.textContent = `LoRA 列表　共 ${list.length} 个`;
        root.appendChild(head);

        list.forEach((entry, idx) => {
          const row = document.createElement("div");
          row.style.cssText = "display:flex;align-items:center;gap:4px;";

          const on = entry.enabled !== false;
          const chk = document.createElement("div");
          chk.textContent = on ? "✓" : "";
          chk.style.cssText = "width:16px;height:16px;line-height:14px;text-align:center;font-size:11px;" +
            "border:1px solid #6a4a8a;border-radius:3px;cursor:pointer;color:#9b6bd6;background:#1b1420;";
          chk.title = on ? "已启用（点击禁用）" : "已禁用（点击启用）";
          chk.onclick = (e) => {
            e.stopPropagation();
            entry.enabled = !on;
            save(); render(); node.setDirtyCanvas?.(true, true);
          };
          row.appendChild(chk);

          const btn = document.createElement("div");
          btn.style.cssText = "flex:1;min-width:0;background:#1b1420;color:#e8dcf2;border:1px solid #4a3560;" +
            "border-radius:4px;font-size:11px;padding:2px 4px;cursor:pointer;overflow:hidden;" +
            "white-space:nowrap;text-overflow:ellipsis;" + (on ? "" : "opacity:.45;");
          btn.textContent = (entry.name ? baseName(entry.name) : "（点这里选 LoRA）") + (on ? "" : "（已禁用）");
          btn.title = entry.name || "";
          btn.onclick = (e) => {
            e.stopPropagation();
            picker(btn, (v) => {
              if (v) entry.name = v; else { list.splice(idx, 1); save(); render(); node.setDirtyCanvas?.(true, true); return; }
              save(); render(); node.setDirtyCanvas?.(true, true);
            });
          };
          row.appendChild(btn);

          const rng = document.createElement("input");
          rng.type = "range";
          rng.min = "0"; rng.max = "2"; rng.step = "0.05";
          rng.value = String(entry.strength ?? 1);
          rng.style.cssText = "width:70px;accent-color:#9b6bd6;";
          rng.oninput = () => { entry.strength = parseFloat(rng.value); num.textContent = entry.strength.toFixed(2); save(); };
          row.appendChild(rng);

          const num = document.createElement("div");
          num.textContent = Number(entry.strength ?? 1).toFixed(2);
          num.style.cssText = "width:30px;text-align:right;font-size:10px;color:#b9a7c9;";
          row.appendChild(num);

          const del = document.createElement("div");
          del.textContent = "×";
          del.style.cssText = "width:16px;height:16px;line-height:14px;text-align:center;background:#7a2b3a;" +
            "color:#fff;font-size:12px;cursor:pointer;border-radius:3px;";
          del.onclick = () => { list.splice(idx, 1); save(); render(); node.setDirtyCanvas?.(true, true); };
          row.appendChild(del);

          root.appendChild(row);
        });

        const add = document.createElement("div");
        add.textContent = "＋ 添加 LoRA";
        add.style.cssText = "text-align:center;font-size:11px;color:#9b6bd6;border:1px dashed #4a3560;" +
          "border-radius:4px;padding:3px;cursor:pointer;";
        add.onclick = () => {
          // 不自动填文件：先加一个空行，立刻弹选择器
          list.push({ name: "", strength: 1.0 });
          save(); render(); node.setDirtyCanvas?.(true, true);
          const rows = root.querySelectorAll("div");
          const target = rows[rows.length - 2];
          if (target) picker(target, (v) => {
            const last = list[list.length - 1];
            if (!v) { list.pop(); } else { last.name = v; }
            save(); render(); node.setDirtyCanvas?.(true, true);
          });
        };
        root.appendChild(add);

        const need = 46 + 24 * (list.length + 1);
        if (node.size[1] < need) node.setSize([node.size[0], need]);
        app.graph?.setDirtyCanvas(true, true);
      }

      loadOptions(nodeData.name).then(() => { render(); });
      // configure 之后（值已载入）再同步一次
      const origConfigure = node.onConfigure;
      node.onConfigure = function () {
        const r2 = origConfigure?.apply(this, arguments);
        try {
          const v = parseStack(stackW.value);
          if (v.length) list = v;
          render();
        } catch (e) { /* 忽略 */ }
        return r2;
      };

      const dom = node.addDOMWidget("vanco_loras", "LoRA", root, { serialize: false, hideOnZoom: false });
      dom.computeSize = () => [Math.max(320, node.size[0] - 20), 46 + 24 * (list.length + 1)];
      if (node.size[1] > 60 + 24 * (list.length + 1)) {
        node.setSize([node.size[0], 60 + 24 * (list.length + 1)]);
      }
      return r;
    };
  },
});
