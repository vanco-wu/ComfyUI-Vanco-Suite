import os
import json

# ---------------------------------------------------------------------------
# 提示词库文件：与节点包放在一起，独立于任何工作流。
# 删除/移动工作流都不会影响这里的提示词；界面也不提供删除键，避免误删。
# ---------------------------------------------------------------------------
BANK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_bank.json")


def load_bank():
    try:
        with open(BANK_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"categories": {}}


def save_bank(bank):
    with open(BANK_PATH, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=2)


BANK = load_bank()


def _cats():
    return list(BANK.get("categories", {}).keys())


def _combos():
    out = []
    for c, items in BANK.get("categories", {}).items():
        for n in items.keys():
            out.append(f"{c} / {n}")
    return out


def _lookup(combined, category=None):
    """兼容两种写法：'分类 / 标题' 或裸标题。找得到就返回提示词，找不到返回空串。"""
    cats = BANK.get("categories", {})
    if combined is None:
        return ""
    if " / " in combined:
        c, n = combined.split(" / ", 1)
        return cats.get(c, {}).get(n, "")
    if category and combined in cats.get(category, {}):
        return cats[category][combined]
    for items in cats.values():
        if combined in items:
            return items[combined]
    return ""


# ---------------------------------------------------------------------------
# 注册到 ComfyUI 的 HTTP 接口：前端“保存到提示词库”按钮会调用这里。
# 用 try 包住，万一接口没注册成功，节点本身（读取/输出）仍可用，只是添加功能退回“记事本编辑”。
# ---------------------------------------------------------------------------
try:
    from server import PromptServer
    from aiohttp import web

    @PromptServer.instance.routes.get("/promptmanager_vanco/bank")
    async def _get_bank(request):
        return web.json_response(BANK)

    @PromptServer.instance.routes.post("/promptmanager_vanco/add")
    async def _add_prompt(request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        cat = (data.get("category") or "").strip()
        name = (data.get("title") or "").strip()
        text = data.get("prompt") or ""
        if not cat or not name or not text.strip():
            return web.json_response({"ok": False, "error": "字段不完整"}, status=400)
        BANK.setdefault("categories", {}).setdefault(cat, {})[name] = text
        save_bank(BANK)
        return web.json_response({"ok": True})

    @PromptServer.instance.routes.post("/promptmanager_vanco/delete")
    async def _delete_prompt(request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "bad json"}, status=400)
        cat = (data.get("category") or "").strip()
        name = (data.get("title") or "").strip()
        cats = BANK.setdefault("categories", {})
        if cat in cats and name in cats[cat]:
            del cats[cat][name]
            # 分类删空后一并移除，避免下拉里留下空分类
            if not cats[cat]:
                del cats[cat]
            save_bank(BANK)
            return web.json_response({"ok": True})
        return web.json_response({"ok": False, "error": "未找到该提示词"}, status=404)

except Exception as e:
    print("[PromptManager-Vanco] 警告：API 路由未注册（添加按钮将不可用，仍可手动编辑 prompt_bank.json）：", e)


class PromptManagerVanco:
    @classmethod
    def INPUT_TYPES(cls):
        cats = _cats() or ["(暂无分类)"]
        titles = _combos() or ["(暂无提示词)"]
        # 用 STRING 而不是 combo：界面完全由自定义面板驱动，
        # combo 会做"值必须在下拉列表内"的校验（execution.py 的 Value not in list），
        # 而列表在服务启动时就缓存了，新增提示词后不重启就会报错，故改为自由字符串。
        return {
            "required": {
                "category": ("STRING", {"default": cats[0]}),
                "title": ("STRING", {"default": titles[0]}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "get_prompt"
    CATEGORY = "Vanco/提示词"

    def get_prompt(self, category, title):
        return (_lookup(title, category),)


NODE_CLASS_MAPPINGS = {"PromptManagerVanco": PromptManagerVanco}
NODE_DISPLAY_NAME_MAPPINGS = {"PromptManagerVanco": "Vanco 提示词管理器"}
