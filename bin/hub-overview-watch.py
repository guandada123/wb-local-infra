#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hub-overview 健康探针（独立进程，不与被观测服务同生命）
- 探活校验「响应身份」：HTTP 200 且 JSON 含 generated_at/kpi/sources，防 200-but-empty 假绿灯
- 状态翻转才告警（up→down / down→up），常态不刷群
- 告警走既有出口 autoloop-feishu-push.py（中台独立应用，不新建应用、不读凭据）
用法：
  python3 hub-overview-watch.py              # 探一次（launchd 每 10 分钟调用）
  python3 hub-overview-watch.py --self-test  # 状态机自测，不联网不推送
  python3 hub-overview-watch.py --force-notify "文本"  # 手动验证推送链路
"""
import json, os, subprocess, sys, urllib.request
from datetime import datetime

URL = "http://127.0.0.1:3355/api/hub/overview"
STATE = os.path.expanduser("~/.agent-autoloop/hub-overview-watch.state")
PUSH = os.path.expanduser("~/.local/bin/autoloop-feishu-push.py")
AUTH_PY = os.path.expanduser("~/.workbuddy/binaries/python/versions/3.13.12/bin/python3")
LOG = os.path.expanduser("~/Library/Logs/hub-overview-watch.log")

def log(msg):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def probe():
    """返回 (ok, 说明, 降级源列表)。校验响应身份而不只看状态码。"""
    try:
        req = urllib.request.Request(URL, headers={"Cache-Control": "no-store"})
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status != 200:
                return False, f"HTTP {r.status}", []
            d = json.loads(r.read().decode())
        missing = [k for k in ("generated_at", "kpi", "sources") if k not in d]
        if missing:
            return False, f"响应缺字段 {missing}", []
        kpi_n = len(d.get("kpi", {}).get("today", []) or [])
        if kpi_n == 0:
            return False, "kpi.today 为空", []
        srcs = d.get("sources") or {}
        errs = sorted(k for k, v in srcs.items() if isinstance(v, dict) and v.get("error"))
        detail = f"ok · {len(srcs)} 源 · {kpi_n} KPI" + (f" · 降级 {','.join(errs)}" if errs else "")
        return True, detail, errs
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:140], []

def read_state():
    """状态文件格式：`state[:deg1,deg2]`；兼容旧的纯 `up`/`down`"""
    try:
        raw = open(STATE, encoding="utf-8").read().strip()
    except Exception:
        return "unknown", []
    if ":" in raw:
        s, d = raw.split(":", 1)
        return (s.strip() or "unknown"), [x for x in d.split(",") if x.strip()]
    return (raw or "unknown"), []

def write_state(state, deg=()):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        f.write(f"{state}:{','.join(sorted(deg))}" if state == "up" else state)

def notify(text):
    """调既有推送出口；失败只记日志，不阻断、不重试爆炸"""
    try:
        py = AUTH_PY if os.path.exists(AUTH_PY) else sys.executable
        r = subprocess.run([py, PUSH, "--text", text], capture_output=True, text=True, timeout=40)
        if r.returncode == 0:
            log(f"通知已发：{text[:40]}")
        else:
            log(f"通知发送失败 rc={r.returncode} {(r.stderr or '').strip()[:120]}")
        return r.returncode == 0
    except Exception as e:
        log(f"通知异常 {type(e).__name__}: {e}")
        return False

def decide(prev_state, prev_deg, ok, errs):
    """告警决策（main 与 --self-test 共用的唯一实现）。
    返回 (notify, kind)，kind ∈ down / up / degraded / recovered / None。
    规则：服务可用性翻转必报；服务可用时，仅当降级源集合发生变化才报（防每 10 分钟刷群）。
    """
    cur = "up" if ok else "down"
    if prev_state == "unknown":
        # 首次运行：服务正常→建基线（有降级源则直接报降级）；真挂了报 down
        if not ok:
            return True, "down"
        return (True, "degraded") if errs else (False, None)
    if cur != prev_state:
        return True, ("down" if cur == "down" else "up")
    if cur == "up":
        a, b = set(prev_deg), set(errs)
        if a != b:
            return True, ("degraded" if (b - a) else "recovered")
    return False, None

LEVEL_TITLE = {
    "down": "🔴 中台工作台 API 不可用",
    "up": "🟢 中台工作台 API 已恢复",
    "degraded": "🟡 中台工作台数据源降级",
    "recovered": "🟢 中台工作台数据源已全部恢复",
}

def build_text(kind, detail, errs):
    if kind == "down":
        return (f"🔴 中台工作台 API 不可用\n检测：{detail}\n地址：{URL}\n"
                f"影响：工作台降级为示例数据；launchd KeepAlive 会自动重启，持续未恢复需人工介入")
    if kind == "up":
        return f"🟢 中台工作台 API 已恢复\n检测：{detail}\n地址：{URL}"
    if kind == "degraded":
        return (f"🟡 中台工作台数据源降级\n降级源：{', '.join(errs)}\n检测：{detail}\n"
                f"影响：对应区块显示为空，顶栏标「N 源降级」；其余数据正常")
    return f"🟢 中台工作台数据源已全部恢复\n检测：{detail}"

def self_test():
    """状态机自测：直接测 main 复用的 decide()，不联网、不推送"""
    cases = [
        # (prev_state, prev_deg, ok, errs, 期望 notify, 期望 kind)
        ("unknown", [],      False, [],            True,  "down"),
        ("unknown", [],      True,  [],            False, None),   # 首次正常只建基线，不误报「已恢复」
        ("unknown", [],      True,  ["A"],         True,  "degraded"),  # 首次就带降级 → 报
        ("down",    [],      False, [],            False, None),
        ("down",    [],      True,  [],            True,  "up"),
        ("up",      [],      True,  [],            False, None),
        ("up",      [],      False, [],            True,  "down"),
        ("up",      [],      True,  ["QUEUE.md"],  True,  "degraded"),
        ("up",      ["QUEUE.md"], True, ["QUEUE.md"], False, None),
        ("up",      ["QUEUE.md"], True, [],        True,  "recovered"),
        ("up",      ["A"],   True,  ["B"],         True,  "degraded"),
        ("down",    [],      False, ["X"],         False, None),   # 整体挂时降级不单独报
    ]
    ok = 0
    for p, pd, c, e, want_n, want_k in cases:
        got_n, got_k = decide(p, pd, c, e)
        ok += (got_n == want_n and got_k == want_k)
    print(f"self-test {ok}/{len(cases)} 通过")
    return 0 if ok == len(cases) else 1

def main():
    global URL, STATE
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    if "--url" in args:                      # 便于测试/指向其它实例，不动生产常量
        URL = args[args.index("--url") + 1]
    if "--state-file" in args:
        STATE = args[args.index("--state-file") + 1]
    dry = "--dry-run" in args
    if "--force-notify" in args:
        i = args.index("--force-notify")
        if i + 1 >= len(args) or not args[i + 1].strip():
            print('用法：--force-notify "要发送的文本"', file=sys.stderr)
            return 2
        if dry:
            print("[dry-run] 将发送：", args[i + 1]); return 0
        return 0 if notify(args[i + 1]) else 1

    prev_state, prev_deg = read_state()
    ok, detail, errs = probe()
    notify_needed, kind = decide(prev_state, prev_deg, ok, errs)
    cur = "up" if ok else "down"

    if not notify_needed:
        log(f"探活 {detail} · 状态未变({cur}{'/' + ','.join(errs) if errs else ''})，不告警")
        write_state(cur, errs)
        return 0 if ok else 1

    text = build_text(kind, detail, errs)
    if dry:
        print(f"[dry-run] kind={kind}\n{text}")
    else:
        notify(text)
    write_state(cur, errs)
    log(f"状态 {prev_state}{'/' + ','.join(prev_deg) if prev_deg else ''} → {cur}"
        f"{'/' + ','.join(errs) if errs else ''}（{kind}）：{detail}")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
