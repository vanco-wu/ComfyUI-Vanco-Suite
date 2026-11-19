import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE = "VancoAssetGrid";
const COLS = 3;
const CELL = 92;

function parse(v) {
  try { return JSON.parse(v || "[]"); } catch (e) { return []; }
}

app.registerExtension({
  name: "Vanco.AssetGrid",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      const node = this;
      const w = node.widgets.find((x) => x.name === "assets_json");
      if (!w) return r;
      w.computeSize = () => [0, -4];
      w.type = "hidden";
      let list = parse(w.value);

      const el = document.createElement("div");
      el.style.cssText =
        "display:grid;grid-template-columns:repeat(" + COLS + ",1fr);gap:4px;padding:4px;" +
        "background:#1b1b1b;border:1px solid #333;border-radius:6px;";
      const tip = document.createElement("div");
      tip.style.cssText = "grid-column:1/-1;font-size:11px;color:#999;";

      function sync() {
        const clean = list.filter((x) => x && x.file);
        w.value = JSON.stringify(clean);
        tip.textContent = clean.length ? "共 " + clean.length + " 张：" + clean.map((x,i)=>(i+1)+"."+(x.name||"未命名")).join("  ") : "点 ＋ 上传素材";
        node.setDirtyCanvas?.(true, true);
      }

      function render() {
        el.innerHTML = "";
        list.forEach((it, idx) => {
          const cell = document.createElement("div");
          cell.style.cssText =
            "position:relative;width:" + CELL + "px;height:" + CELL + "px;border:1px solid #444;" +
            "border-radius:4px;overflow:hidden;background:#000;";
          if (it.file) {
            const img = document.createElement("img");
            img.src = "/view?filename=" + encodeURIComponent(it.file.split("/").pop()) +
              "&type=input&subfolder=" + encodeURIComponent(it.file.split("/").slice(0, -1).join("/"));
            img.draggable = false;
            img.style.cssText = "width:100%;height:100%;object-fit:cover;pointer-events:none;";
            cell.appendChild(img);
          }
          const mkMove = (txt, dir, right) => {
            const b = document.createElement("div");
            b.textContent = txt;
            b.style.cssText = "position:absolute;bottom:16px;" + (right ? "right:2px;" : "left:2px;") +
              "width:16px;height:16px;line-height:14px;text-align:center;background:#333c;color:#fff;" +
              "font-size:11px;cursor:pointer;border-radius:3px;";
            b.onclick = (e) => {
              e.stopPropagation();
              const j = idx + dir;
              if (j < 0 || j >= list.length) return;
              const t = list[idx]; list[idx] = list[j]; list[j] = t;
              render(); sync();
            };
            return b;
          };
          cell.appendChild(mkMove("◀", -1, false));
          cell.appendChild(mkMove("▶", 1, true));
          const no = document.createElement("div");
          no.textContent = idx + 1;
          no.style.cssText = "position:absolute;left:2px;top:2px;font-size:10px;color:#fff;background:#0008;padding:0 3px;border-radius:3px;";
          cell.appendChild(no);
          const del = document.createElement("div");
          del.textContent = "×";
          del.style.cssText = "position:absolute;right:0;top:0;width:16px;height:16px;line-height:14px;" +
            "text-align:center;background:#c33;color:#fff;font-size:13px;cursor:pointer;border-radius:0 0 0 4px;";
          del.onclick = (e) => { e.stopPropagation(); list.splice(idx, 1); render(); sync(); };
          cell.appendChild(del);
          const nm = document.createElement("input");
          nm.value = it.name || "";
          nm.placeholder = "名字";
          nm.title = "这个名字给提示词用，和文件名无关";
          nm.style.cssText = "position:absolute;left:0;right:0;bottom:0;width:100%;box-sizing:border-box;" +
            "background:#000a;color:#fff;border:none;font-size:10px;padding:1px 3px;outline:none;";
          nm.onclick = (e) => e.stopPropagation();
          nm.oninput = () => { it.name = nm.value; };
          nm.onchange = () => { it.name = nm.value; sync(); };
          cell.appendChild(nm);
          el.appendChild(cell);
        });
        const add = document.createElement("div");
        add.textContent = "＋";
        add.style.cssText =
          "width:" + CELL + "px;height:" + CELL + "px;border:1px dashed #666;border-radius:4px;" +
          "display:flex;align-items:center;justify-content:center;color:#888;font-size:26px;cursor:pointer;";
        add.onclick = () => pick((item) => { list.push(item); render(); sync(); });
        el.appendChild(add);
        el.appendChild(tip);
        sync();
      }

      let picker = null;
      function pick(cb) {
        if (!picker) {
          picker = document.createElement("input");
          picker.type = "file";
          picker.accept = "image/*";
          picker.multiple = true;
          picker.style.display = "none";
          document.body.appendChild(picker);
        }
        picker.onchange = async () => {
          for (const f of picker.files) {
            const name = f.name.replace(/\.[^.]+$/, "");
            const body = new FormData();
            body.append("image", f, f.name);
            body.append("type", "input");
            
            try {
              const r = await api.fetchApi("/upload/image", { method: "POST", body });
              const j = await r.json();
              const sub = j.subfolder ? j.subfolder + "/" : "";
              cb({ name, file: sub + j.name });
            } catch (e) {
              console.error("[Vanco] 上传失败", e);
            }
          }
          picker.value = "";
        };
        picker.click();
      }

      const dom = node.addDOMWidget("vanco_assets", "素材", el, {
        serialize: false,
        hideOnZoom: false,
        getValue: () => w.value,
        setValue: () => {},
      });
      const MINW = COLS * (CELL + 10) + 16;
      dom.computeSize = () => [MINW, Math.ceil((list.length + 1) / COLS) * (CELL + 10) + 30];
      if (node.size[0] < MINW) node.setSize([MINW, node.size[1]]);
      const onResize = node.onResize;
      node.onResize = function (size) {
        if (size[0] < MINW) size[0] = MINW;
        return onResize?.apply(this, arguments);
      };
      render();
      // 工作流加载时，widget 的值是稍后才注入的，必须重新读一次
      const cfg = node.onConfigure;
      node.onConfigure = function () {
        const res = cfg?.apply(this, arguments);
        try { list = parse(w.value); } catch (e) { list = []; }
        render(); sync();
        app.graph?.setDirtyCanvas(true, true);
        return res;
      };

      return r;
    };
  },
});
