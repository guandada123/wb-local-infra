#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 历史会话只读查看器 (本地服务)
- 直接读 ~/.workbuddy/projects/**/*.jsonl, 绕开云端列表接口 404
- GET /                  → 会话索引页 (分组+搜索)
- GET /conv/<id>         → 单个会话完整对话
- GET /api/sessions      → 索引 JSON
用法: python3 wb_history_server.py [port]   (默认 8791)
"""
import glob, json, os, sys, html, datetime, functools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.expanduser("~/.workbuddy/projects")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8791

def esc(s):
    return html.escape(s or "", quote=True)

def ts2str(ms):
    if not ms: return "-"
    return datetime.datetime.fromtimestamp(ms/1000).strftime("%Y-%m-%d %H:%M:%S")

def wd_short(wd):
    return (wd.replace("Users-guan-WorkBuddy-", "~/WorkBuddy/")
              .replace("Volumes-ZHITAI-WorkBuddy-", "/Volumes/ZHITAI/WorkBuddy/"))

@functools.lru_cache(maxsize=1)
def build_index():
    rows = []
    for f in glob.glob(BASE + "/*/*.jsonl"):
        conv = os.path.basename(f)[:-6]
        wd = os.path.basename(os.path.dirname(f))
        ts_min = ts_max = None; nmsg = 0; first = ""; model = ""
        try:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try: ev = json.loads(line)
                    except Exception: continue
                    t = ev.get("timestamp")
                    if t:
                        ts_max = t if ts_max is None else max(ts_max, t)
                        ts_min = t if ts_min is None else min(ts_min, t)
                    if ev.get("type") == "message":
                        nmsg += 1
                        if ev.get("role") == "user" and not first:
                            txt = ""
                            for x in (ev.get("content") or []):
                                if isinstance(x, dict) and x.get("type") == "input_text":
                                    txt = x.get("text", "")
                            txt = txt.strip()
                            if txt and not txt.startswith("<system-reminder"):
                                first = txt.replace("\n", " ")[:140]
                    if ev.get("type") == "reasoning" and not model:
                        model = (ev.get("providerData") or {}).get("model") or ""
        except Exception:
            continue
        rows.append(dict(conv=conv, wd=wd, ts_min=ts_min, ts_max=ts_max,
                         nmsg=nmsg, first=first or "(无用户消息)", model=model))
    rows.sort(key=lambda r: r["ts_max"] or 0, reverse=True)
    return rows

def render_conversation(conv_id):
    """渲染单个会话为 HTML 片段"""
    f = os.path.join(BASE, "*", conv_id + ".jsonl")
    matches = glob.glob(f)
    if not matches:
        return None, None
    path = matches[0]
    wd = os.path.basename(os.path.dirname(path))
    blocks = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try: ev = json.loads(line)
            except Exception: continue
            typ = ev.get("type")
            ts = ts2str(ev.get("timestamp"))
            if typ == "message":
                role = ev.get("role")
                parts = []
                for x in (ev.get("content") or []):
                    if not isinstance(x, dict): continue
                    xt = x.get("type")
                    if xt == "input_text":
                        parts.append(("u", x.get("text", "")))
                    elif xt == "output_text":
                        parts.append(("a", x.get("text", "")))
                    elif xt == "tool_use":
                        parts.append(("tool", json.dumps({k: x.get(k) for k in ("name", "input")}, ensure_ascii=False)[:600]))
                    elif xt == "text":
                        parts.append(("a", x.get("text", "")))
                if isinstance(ev.get("content"), str):
                    parts.append(("a", ev["content"]))
                if role == "user":
                    for k, txt in parts:
                        if k == "u":
                            blocks.append(f'<div class="msg u"><div class="meta">用户 · {ts}</div><div class="body">{esc(txt)}</div></div>')
                elif role == "assistant":
                    for k, txt in parts:
                        if k == "a":
                            blocks.append(f'<div class="msg a"><div class="meta">助手 · {ts}</div><div class="body">{esc(txt)}</div></div>')
                        elif k == "tool":
                            blocks.append(f'<details class="tool"><summary>🔧 工具调用</summary><pre>{esc(txt)}</pre></details>')
            elif typ == "reasoning":
                rtxt = ""
                for x in (ev.get("content") or []):
                    if isinstance(x, dict) and x.get("type") == "text":
                        rtxt += x.get("text", "")
                if not rtxt and ev.get("reasoning_content"):
                    rtxt = ev["reasoning_content"]
                if rtxt:
                    blocks.append(f'<details class="rea"><summary>💭 思考过程</summary><div class="body">{esc(rtxt)}</div></details>')
    if not blocks:
        blocks.append('<div class="msg">(无对话内容)</div>')
    return wd, "\n".join(blocks)

INDEX_PAGE_TMPL = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>WorkBuddy 历史会话</title><style>
body{{font-family:-apple-system,"PingFang SC",sans-serif;background:#f6f7f9;color:#1f2329;margin:0;padding:24px}}
h1{{font-size:20px;margin:0 0 4px}}.sub{{color:#646a73;font-size:13px;margin-bottom:16px}}
#q{{width:100%;box-sizing:border-box;padding:10px 14px;font-size:14px;border:1px solid #d0d3d9;border-radius:8px;margin-bottom:16px}}
.g{{margin-bottom:14px;background:#fff;border:1px solid #e5e6eb;border-radius:10px;overflow:hidden}}
.g-h{{padding:8px 14px;font-weight:600;font-size:14px;background:#f2f3f5;border-bottom:1px solid #e5e6eb}}
.cnt{{color:#86909c;font-weight:400;font-size:12px;margin-left:6px}}
.s{{padding:8px 14px;border-bottom:1px solid #f0f1f3;cursor:pointer;text-decoration:none;display:block;color:inherit}}
.s:hover{{background:#f5f7fa}}.s:last-child{{border-bottom:none}}
.s-top{{display:flex;gap:8px;align-items:center;margin-bottom:3px}}
.t{{color:#4e5969;font-size:12px;min-width:86px}}.id{{color:#c9cdd4;font-size:11px}}
.m{{background:#e8f3ff;color:#165dff;font-size:11px;padding:1px 6px;border-radius:4px}}
.n{{margin-left:auto;color:#86909c;font-size:12px}}.q{{font-size:13px;color:#1f2329;line-height:1.5}}
.hide{{display:none}}
.msg{{margin:10px 0;padding:12px 14px;border-radius:10px;font-size:14px;line-height:1.65;white-space:pre-wrap;word-break:break-word}}
.msg.u{{background:#eef4ff;border:1px solid #d6e4ff}}
.msg.a{{background:#fff;border:1px solid #e5e6eb}}
.meta{{font-size:11px;color:#86909c;margin-bottom:6px}}
.tool,.rea{{margin:8px 0;background:#fafafa;border:1px solid #eee;border-radius:8px;padding:8px 12px}}
.tool pre{{white-space:pre-wrap;font-size:12px;color:#4e5969;margin:6px 0 0}}
summary{{cursor:pointer;color:#4e5969;font-size:13px}}
.back{{display:inline-block;margin-bottom:14px;color:#165dff;text-decoration:none;font-size:14px}}
</style></head><body>{body}</body></html>"""

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            rows = build_index()
            groups = {}
            for r in rows:
                groups.setdefault(r["wd"], []).append(r)
            cards = ""
            for wd, items in groups.items():
                items.sort(key=lambda r: r["ts_max"] or 0, reverse=True)
                s = ""
                for r in items:
                    mb = f'<span class="m">{esc(r["model"])}</span>' if r["model"] else ""
                    s += (f'<a class="s" href="/conv/{r["conv"]}">'
                          f'<div class="s-top"><span class="t">{ts2str(r["ts_max"])}</span>'
                          f'<span class="id">{esc(r["conv"][:8])}</span>{mb}'
                          f'<span class="n">{r["nmsg"]}条</span></div>'
                          f'<div class="q">{esc(r["first"])}</div></a>')
                cards += (f'<div class="g"><div class="g-h">{esc(wd_short(wd))} '
                          f'<span class="cnt">{len(items)}</span></div>{s}</div>')
            body = (f'<h1>WorkBuddy 历史会话</h1>'
                    f'<div class="sub">本地直读 · {len(rows)} 个会话 · 点会话看完整对话 · 生成于 {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}</div>'
                    f'<input id="q" placeholder="搜索内容 / ID / 工作区…"><div id="list">{cards}</div>'
                    f'<script>const q=document.getElementById("q");q.addEventListener("input",()=>{{'
                    f'const k=q.value.trim().toLowerCase();'
                    f'document.querySelectorAll(".s").forEach(s=>s.classList.toggle("hide",k&&!s.textContent.toLowerCase().includes(k)));'
                    f'document.querySelectorAll(".g").forEach(g=>g.classList.toggle("hide",![...g.querySelectorAll(".s")].some(s=>!s.classList.contains("hide"))));'
                    f'}});</script>')
            self._send(200, INDEX_PAGE_TMPL.format(body=body))
        elif path.startswith("/conv/"):
            conv_id = path[6:]
            wd, content = render_conversation(conv_id)
            if wd is None:
                self._send(404, INDEX_PAGE_TMPL.format(body="<h1>未找到会话</h1><a class='back' href='/'>← 返回</a>"))
                return
            body = (f'<a class="back" href="/">← 返回列表</a>'
                    f'<h1>会话 {esc(conv_id[:8])} · {esc(wd_short(wd))}</h1>'
                    f'<div class="sub">会话ID: {esc(conv_id)}</div>{content}')
            self._send(200, INDEX_PAGE_TMPL.format(body=body))
        elif path == "/api/sessions":
            self._send(200, json.dumps(build_index(), ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self._send(404, "Not Found", "text/plain")

if __name__ == "__main__":
    print(f"WorkBuddy 历史会话服务: http://127.0.0.1:{PORT}  (Ctrl+C 停止)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
