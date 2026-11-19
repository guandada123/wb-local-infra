#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wb_history_snapshot.py — WorkBuddy 历史会话静态快照 (双重兜底第2层)
- 生成单文件 ~/wb_history_snapshot.html: 全量索引(可搜索) + 最近活跃会话全文(<details>折叠)
- 即使 8791 本地服务挂了, 直接双击/打开该 HTML 仍可浏览历史
- 触发: wb_404_watcher 检测到云端列表 404 时刷新; 或每日保新; 或手动执行
用法:
  python3 wb_history_snapshot.py [--full N] [--out PATH]
    --full N  内联最近 N 个活跃会话全文 (默认 150)
    --out     输出路径 (默认 ~/wb_history_snapshot.html)
"""
import argparse, datetime, functools, glob, html, json, os

BASE = os.path.expanduser("~/.workbuddy/projects")

def esc(s):
    return html.escape(s or "", quote=True)

def ts2str(ms):
    if not ms: return "-"
    return datetime.datetime.fromtimestamp(ms/1000).strftime("%Y-%m-%d %H:%M:%S")

def wd_short(wd):
    return (wd.replace("Users-guan-WorkBuddy-", "~/WorkBuddy/")
              .replace("Volumes-ZHITAI-WorkBuddy-", "/Volumes/ZHITAI/WorkBuddy/"))

def build_index():
    """全量索引: 每会话元数据 (与 wb_history_server.build_index 逻辑一致)"""
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
    """渲染单个会话为 HTML 片段 (与 wb_history_server.render_conversation 逻辑一致)"""
    matches = glob.glob(os.path.join(BASE, "*", conv_id + ".jsonl"))
    if not matches:
        return None
    path = matches[0]
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
    return "\n".join(blocks)

TMPL = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>WorkBuddy 历史会话快照</title><style>
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
.conv{{margin-bottom:12px;background:#fff;border:1px solid #e5e6eb;border-radius:10px;padding:12px 16px}}
.conv summary{{font-weight:600;font-size:14px;color:#1f2329}}
.conv .sub{{margin-top:2px}}
</style></head><body>{body}</body></html>"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", type=int, default=150, help="内联最近 N 个活跃会话全文 (默认150)")
    ap.add_argument("--out", default=os.path.expanduser("~/wb_history_snapshot.html"))
    args = ap.parse_args()

    t0 = datetime.datetime.now()
    rows = build_index()
    idx = {r["conv"]: r for r in rows}

    # 最近 N 个会话全文 (先定义, 索引卡片需引用)
    full_conv_ids = [r["conv"] for r in rows[:args.full]]
    idx_full = set(full_conv_ids)

    # 按工作区分组索引
    groups = {}
    for r in rows:
        groups.setdefault(r["wd"], []).append(r)

    # 索引卡片
    cards = ""
    for wd, items in groups.items():
        items.sort(key=lambda r: r["ts_max"] or 0, reverse=True)
        s = ""
        for r in items:
            mb = f'<span class="m">{esc(r["model"])}</span>' if r["model"] else ""
            anchor = f'href="#conv-{r["conv"]}"' if r["conv"] in idx_full else ""
            s += (f'<a class="s" {anchor}>'
                  f'<div class="s-top"><span class="t">{ts2str(r["ts_max"])}</span>'
                  f'<span class="id">{esc(r["conv"][:8])}</span>{mb}'
                  f'<span class="n">{r["nmsg"]}条</span></div>'
                  f'<div class="q">{esc(r["first"])}</div></a>')
        cards += (f'<div class="g"><div class="g-h">{esc(wd_short(wd))} '
                  f'<span class="cnt">{len(items)}</span></div>{s}</div>')

    # 最近 N 个会话全文
    conv_html = ""
    for conv in full_conv_ids:
        r = idx[conv]
        content = render_conversation(conv)
        if not content:
            continue
        mb = f' · <span class="m">{esc(r["model"])}</span>' if r["model"] else ""
        conv_html += (f'<div class="conv"><details id="conv-{conv}" open>'
                      f'<summary>{esc(r["first"][:60])}</summary>'
                      f'<div class="sub">{ts2str(r["ts_max"])} · {esc(wd_short(r["wd"]))} · {r["nmsg"]}条{mb}</div>'
                      f'{content}</details></div>')

    body = (f'<h1>WorkBuddy 历史会话快照</h1>'
            f'<div class="sub">本地直读 · 共 {len(rows)} 个会话 · 全文内联最近 {len(full_conv_ids)} 个活跃会话 · 生成于 {t0.strftime("%Y-%m-%d %H:%M:%S")}</div>'
            f'<input id="q" placeholder="搜索内容 / ID / 工作区…"><div id="list">{cards}</div>'
            f'<div id="convs">{conv_html}</div>'
            f'<script>const q=document.getElementById("q");q.addEventListener("input",()=>{{'
            f'const k=q.value.trim().toLowerCase();'
            f'document.querySelectorAll(".s").forEach(s=>s.classList.toggle("hide",k&&!s.textContent.toLowerCase().includes(k)));'
            f'document.querySelectorAll(".g").forEach(g=>g.classList.toggle("hide",![...g.querySelectorAll(".s")].some(s=>!s.classList.contains("hide"))));'
            f'}});</script>')
    html_out = TMPL.format(body=body)

    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(html_out)
    os.replace(tmp, args.out)  # 原子替换, 避免半成品

    dur = (datetime.datetime.now() - t0).total_seconds()
    size_mb = os.path.getsize(args.out) / 1024 / 1024
    print(f"快照已生成: {args.out} ({size_mb:.1f} MB, {len(rows)} 会话, 耗时 {dur:.1f}s)")

if __name__ == "__main__":
    main()
