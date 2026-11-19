import { app } from "../../scripts/app.js";

const NODE_TYPE = "PromptManagerVanco";
const API_BANK = "/promptmanager_vanco/bank";
const API_ADD = "/promptmanager_vanco/add";
const API_DEL = "/promptmanager_vanco/delete";
const ACCENT = "#d7e1ec"; // 银白点缀（与 LoRA 加载器统一），呼应头像的黑白月牙

function injectTheme() {
  if (document.getElementById("vanco-pm-style")) return;
  const s = document.createElement("style");
  s.id = "vanco-pm-style";
  s.textContent = `
  .vanco-pm {
    border:1px solid #464c55; border-radius:8px; background:#2b2e33;
    padding:8px 9px; margin:4px 2px; color:#dfe3e8; font-size:12px;
    box-shadow:0 1px 3px rgba(0,0,0,.35);
    display:flex; flex-direction:column; overflow-y:auto;
  }
  .vanco-pm .pm-head{
    display:flex; align-items:center; gap:7px;
    border-bottom:1px solid #383d45; padding-bottom:5px; margin-bottom:6px;
    font-weight:700; letter-spacing:.5px; color:#e6e9ed; flex:0 0 auto;
  }
  .vanco-pm .pm-head .dot{ width:10px; height:10px; border-radius:50%; background:${ACCENT}; box-shadow:0 0 0 3px rgba(215,225,236,.18); }
  .vanco-pm label{ display:block; margin:6px 0 3px; color:#aab2bc; font-weight:600; flex:0 0 auto; }
  .vanco-pm select, .vanco-pm input[type=text], .vanco-pm textarea{
    width:100%; box-sizing:border-box; border:1px solid #464c55; border-radius:6px;
    background:#1f2227; color:#e6e9ed; font-size:12px; padding:5px 7px; font-family:inherit;
  }
  .vanco-pm select:focus, .vanco-pm input:focus, .vanco-pm textarea:focus{
    outline:none; border-color:${ACCENT}; box-shadow:0 0 0 2px rgba(215,225,236,.22);
  }
  .vanco-pm .pm-preview{
    min-height:90px; flex:1 1 auto; overflow:auto; resize:vertical; line-height:1.5;
    white-space:pre-wrap; background:#1a1d21; border:1px solid #3a3f47; color:#d8dde3;
  }
  .vanco-pm .pm-btn{
    background:#34383e; color:#eeeeee; border:1px solid #4a505a; border-radius:6px;
    padding:6px 13px; cursor:pointer; font-size:12px; font-weight:700; margin-top:6px;
  }
  .vanco-pm .pm-btn:hover{ background:#41464e; border-color:${ACCENT}; }
  .vanco-pm .pm-msg{ color:#7fb37f; margin-left:8px; font-weight:600; }
  .vanco-pm .pm-add{ border-top:1px dashed #4a505a; margin-top:9px; padding-top:8px; flex:0 0 auto; }
  .vanco-pm .pm-add .pm-sub{ font-weight:700; margin-bottom:5px; color:#e0e4e8; }
  .vanco-pm .pm-delbar{ flex:0 0 auto; margin-top:8px; }
  .vanco-pm .pm-actionrow{ display:flex; gap:7px; flex-wrap:wrap; }
  .vanco-pm .pm-actionrow .pm-btn{ flex:1 1 auto; margin-top:0; }
  .vanco-pm .pm-edit{ background:#3b424b; color:#e2e9f1; border-color:#556170; }
  .vanco-pm .pm-edit:hover{ background:#4a535e; border-color:${ACCENT}; }
  .vanco-pm .pm-canceledit{ background:#34383e; color:#ccd2d9; border-color:#4a505a; margin-left:6px; }
  .vanco-pm .pm-canceledit:hover{ background:#41464e; }
  .vanco-pm .pm-del{ background:#4a2a2a; color:#ffd9d9; border-color:#6e3a3a; }
  .vanco-pm .pm-del:hover{ background:#6e3a3a; border-color:#c05050; }
  .vanco-pm .pm-delconfirm{ display:flex; align-items:center; flex-wrap:wrap; gap:7px; margin-top:6px;
    background:#3a2626; border:1px solid #6e3a3a; border-radius:6px; padding:6px 8px; color:#ffb3b3; font-weight:600; }
  .vanco-pm .pm-del-yes{ background:#8a2f2f; color:#fff; border-color:#b04a4a; margin-top:0; }
  .vanco-pm .pm-del-yes:hover{ background:#b04040; border-color:#d06060; }
  .vanco-pm .pm-del-no{ background:#34383e; color:#eeeeee; border-color:#4a505a; margin-top:0; }
  .vanco-pm .pm-delmsg{ color:#e0a0a0; margin-left:8px; font-weight:600; }
  `;
  document.head.appendChild(s);
}

function widgetOf(node, name) {
  return node.widgets ? node.widgets.find((w) => w.name === name) : null;
}

function hideWidget(w) {
  if (!w) return;
  w.hidden = true;
  if (w.element) w.element.style.display = "none";
}

function setupPanel(node) {
  injectTheme();

  // 原生下拉只负责"数据/输出"，界面上交给我们自己的主题面板
  const catW = widgetOf(node, "category");
  const titleW = widgetOf(node, "title");
  if (!catW || !titleW) return;
  hideWidget(catW);
  hideWidget(titleW);

  let bank = null;

  const root = document.createElement("div");
  root.className = "vanco-pm";
  root.innerHTML = `
    <div class="pm-head"><span class="dot"></span>提示词管理器</div>
    <label>分类</label>
    <select class="pm-cat"></select>
    <label>标题</label>
    <select class="pm-title"></select>
    <label>预览（只读）</label>
    <textarea class="pm-preview" readonly placeholder="选择标题后显示完整提示词"></textarea>
    <div class="pm-delbar">
      <div class="pm-actionrow">
        <button class="pm-btn pm-edit">✎ 编辑当前提示词</button>
        <button class="pm-btn pm-del">🗑 删除当前提示词</button>
      </div>
      <div class="pm-delconfirm" style="display:none">
        <span class="pm-delq"></span>
        <button class="pm-btn pm-del-yes">确认删除</button>
        <button class="pm-btn pm-del-no">取消</button>
      </div>
      <span class="pm-delmsg"></span>
    </div>
    <div class="pm-add">
      <div class="pm-sub">＋ 添加新提示词（保存到库文件）</div>
      <input type="text" class="pm-new-cat" placeholder="分类，如 男女"/>
      <input type="text" class="pm-new-title" placeholder="标题，如 新姿势"/>
      <textarea class="pm-new-text" placeholder="提示词正文" style="height:64px;margin-top:4px"></textarea>
      <button class="pm-btn pm-save">保存到提示词库</button>
      <button class="pm-btn pm-canceledit" style="display:none">取消编辑</button>
      <span class="pm-msg"></span>
    </div>
  `;

  const catSel = root.querySelector(".pm-cat");
  const titleSel = root.querySelector(".pm-title");
  const preview = root.querySelector(".pm-preview");
  const msg = root.querySelector(".pm-msg");

  // ---- 删除当前提示词（两步确认，防误删）----
  const delBtn = root.querySelector(".pm-del");
  const delConfirm = root.querySelector(".pm-delconfirm");
  const delQ = root.querySelector(".pm-delq");
  const delMsg = root.querySelector(".pm-delmsg");

  function resetDel() {
    delConfirm.style.display = "none";
    delBtn.style.display = "";
  }

  delBtn.addEventListener("click", () => {
    const name = titleSel.value;
    delMsg.textContent = "";
    if (!name) { delMsg.textContent = "没有可删除的提示词"; return; }
    delQ.textContent = `确定删除「${catW.value} / ${name}」？`;
    delConfirm.style.display = "flex";
    delBtn.style.display = "none";
  });

  root.querySelector(".pm-del-no").addEventListener("click", resetDel);

  root.querySelector(".pm-del-yes").addEventListener("click", async () => {
    const category = catW.value;
    const name = titleSel.value;
    if (!category || !name) { resetDel(); return; }
    try {
      const r = await fetch(API_DEL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, title: name }),
      });
      const j = await r.json();
      if (j.ok) {
        resetDel();
        delMsg.textContent = "已删除 ✓";
        await loadBank();
      } else {
        delMsg.textContent = "删除失败：" + (j.error || "");
      }
    } catch (e) {
      delMsg.textContent = "请求失败（可手动改 prompt_bank.json）";
    }
  });

  // ---- 编辑当前提示词：载入下方表单，保存即覆盖 ----
  const editBtn = root.querySelector(".pm-edit");
  const cancelEditBtn = root.querySelector(".pm-canceledit");
  const saveBtn = root.querySelector(".pm-save");
  const newCatEl = root.querySelector(".pm-new-cat");
  const newTitleEl = root.querySelector(".pm-new-title");
  const newTextEl = root.querySelector(".pm-new-text");
  let editing = null; // 编辑中的原始 {category, title}

  function resetEdit() {
    editing = null;
    newCatEl.value = "";
    newTitleEl.value = "";
    newTextEl.value = "";
    saveBtn.textContent = "保存到提示词库";
    cancelEditBtn.style.display = "none";
  }

  editBtn.addEventListener("click", () => {
    resetDel();
    const name = titleSel.value;
    if (!name) { msg.textContent = "没有可编辑的提示词"; return; }
    const items = (bank && bank.categories && bank.categories[catW.value]) || {};
    newCatEl.value = catW.value;
    newTitleEl.value = name;
    newTextEl.value = items[name] || "";
    editing = { category: catW.value, title: name };
    saveBtn.textContent = "保存修改";
    cancelEditBtn.style.display = "";
    msg.textContent = "已载入，改完点『保存修改』";
    newTextEl.focus();
    newTextEl.scrollTop = 0;
  });

  cancelEditBtn.addEventListener("click", () => {
    resetEdit();
    msg.textContent = "";
  });

  // 把当前"分类 + 标题"写回原生控件：title 统一写成 "分类 / 标题"，
  // 与后端 _lookup 的解析格式一致（只写裸标题会导致取值失败/校验报错）。
  function syncWidgets() {
    const name = titleSel.value;
    if (name) titleW.value = `${catW.value} / ${name}`;
  }

  function updatePreview() {
    const items = (bank && bank.categories && bank.categories[catW.value]) || {};
    preview.value = items[titleSel.value] || "";
  }

  function refreshCat() {
    const cats = bank && bank.categories ? Object.keys(bank.categories) : [];
    catSel.innerHTML = "";
    for (const c of cats) {
      const o = document.createElement("option");
      o.value = c; o.textContent = c; catSel.appendChild(o);
    }
    if (cats.includes(catW.value)) catSel.value = catW.value;
    else if (cats.length) { catW.value = cats[0]; catSel.value = cats[0]; }
    refreshTitle();
  }

  function refreshTitle() {
    const items = (bank && bank.categories && bank.categories[catW.value]) || {};
    const names = Object.keys(items);
    titleSel.innerHTML = "";
    for (const n of names) {
      const o = document.createElement("option");
      o.value = n; o.textContent = n; titleSel.appendChild(o);
    }
    // 兼容已保存的值：可能是 "分类 / 标题"，也可能是裸标题
    let pick = names[0] || "";
    const prev = titleW.value || "";
    const prevName = prev.includes(" / ") ? prev.split(" / ").slice(1).join(" / ") : prev;
    if (names.includes(prevName)) pick = prevName;
    if (pick) titleSel.value = pick;
    syncWidgets();
    updatePreview();
  }

  catSel.addEventListener("change", () => {
    resetDel(); // 切换选择时取消未完成的删除确认，避免误删到别的条目
    catW.value = catSel.value;
    refreshTitle();
  });
  titleSel.addEventListener("change", () => {
    resetDel();
    syncWidgets();
    updatePreview();
  });

  saveBtn.addEventListener("click", async () => {
    const category = newCatEl.value.trim();
    const title = newTitleEl.value.trim();
    const prompt = newTextEl.value;
    msg.textContent = "";
    if (!category || !title || !prompt.trim()) {
      msg.textContent = "三项都要填";
      return;
    }
    try {
      const r = await fetch(API_ADD, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category, title, prompt }),
      });
      const j = await r.json();
      if (!j.ok) { msg.textContent = "失败：" + (j.error || ""); return; }

      // 编辑时若改了分类/标题，删掉旧条目（相当于重命名/移动，不留两份）
      if (editing && (editing.category !== category || editing.title !== title)) {
        try {
          await fetch(API_DEL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ category: editing.category, title: editing.title }),
          });
        } catch (e) { /* 忽略：最坏情况只多留一条旧条目 */ }
      }

      const wasEditing = !!editing;
      msg.textContent = wasEditing ? "已更新 ✓" : "已保存 ✓";
      resetEdit();
      // 保存后让节点选中刚保存的这条
      catW.value = category;
      titleW.value = `${category} / ${title}`;
      await loadBank();
    } catch (e) {
      msg.textContent = "请求失败（可改 prompt_bank.json）";
    }
  });

  async function loadBank() {
    try {
      const r = await fetch(API_BANK);
      bank = await r.json();
    } catch (e) {
      bank = null;
    }
    refreshCat();
  }

  loadBank();

  // 设定节点最小尺寸：保证"删除/添加提示词"功能区始终在节点框内，拖小也挤不出去
  const _w = node.size && node.size[0] ? node.size[0] : 320;
  node.size_min = [Math.max(_w, 300), 500];
  if (!node.size) node.size = [_w, 500];
  node.size[1] = Math.max(node.size[1], 500);

  // 用 DOMWidget 让面板正确参与节点布局（此前直接 append 会被裁掉，导致按钮看不见）
  node.addDOMWidget("vanco_pm_panel", "vanco_pm", root, { serialize: false });

  // 与 Vanco LoRA 加载器统一：石墨黑标题栏 + 略浅底色
  node.color = "#1c1f24";
  node.bgcolor = "#26292f";
  node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
  name: "Vanco.PromptManager",
  async beforeRegisterNodeDef(nodeType, nodeData, app) {
    if (nodeData.name !== NODE_TYPE) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated ? onCreated.apply(this, arguments) : undefined;
      try {
        setupPanel(this);
      } catch (e) {
        console.warn("PromptManager setup error", e);
      }
      return r;
    };
  },
});
