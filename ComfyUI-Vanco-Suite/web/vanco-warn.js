import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Vanco · 运行警告浮层：引擎跑完把警告发到前端，用户不用翻日志
const STYLE_ID = "vanco-warn-style";

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const st = document.createElement("style");
  st.id = STYLE_ID;
  st.textContent = `
  #vanco-warn-box{position:fixed;right:18px;top:72px;z-index:99999;width:380px;max-height:60vh;
    overflow:auto;background:#1b2530;border:1px solid #d9b45f;border-radius:10px;
    box-shadow:0 8px 28px rgba(0,0,0,.55);color:#e8eef5;
    font:13px/1.55 "Microsoft YaHei",system-ui,sans-serif;}
  #vanco-warn-box .vw-head{display:flex;align-items:center;justify-content:space-between;
    padding:10px 12px;border-bottom:1px solid #2c3a49;background:#22303d;border-radius:10px 10px 0 0;}
  #vanco-warn-box .vw-title{font-weight:600;color:#f0c869;}
  #vanco-warn-box .vw-close{cursor:pointer;color:#9fb3c8;padding:0 4px;}
  #vanco-warn-box .vw-body{padding:10px 12px;}
  #vanco-warn-box li{margin:6px 0 6px 16px;}
  #vanco-warn-box .vw-foot{padding:8px 12px;border-top:1px solid #2c3a49;color:#9fb3c8;font-size:12px;word-break:break-all;}
  `;
  document.head.appendChild(st);
}

function showWarn(data) {
  ensureStyle();
  const old = document.getElementById("vanco-warn-box");
  if (old) old.remove();
  const box = document.createElement("div");
  box.id = "vanco-warn-box";
  const items = (data.items || []).map((t) => `<li>${t}</li>`).join("");
  box.innerHTML = `
    <div class="vw-head">
      <span class="vw-title">⚠ ${data.title || "运行警告"}</span>
      <span class="vw-close" title="关闭">✕</span>
    </div>
    <div class="vw-body"><ul>${items}</ul></div>
    ${data["报告"] ? `<div class="vw-foot">报告：${data["报告"]}</div>` : ""}`;
  document.body.appendChild(box);
  box.querySelector(".vw-close").onclick = () => box.remove();
  // 30 秒后自动淡出（可随时手动关）
  setTimeout(() => { if (box.isConnected) box.remove(); }, 30000);
}

api.addEventListener("vanco-warn", (e) => {
  try {
    showWarn(e.detail || {});
  } catch (err) {
    console.error("[Vanco] 警告浮层渲染失败", err);
  }
});

app.registerExtension({ name: "Vanco.WarnBox" });
