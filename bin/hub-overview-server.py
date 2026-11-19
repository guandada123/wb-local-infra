#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 中台工作台 — 只读聚合 API + 静态托管
GET /api/hub/overview  → 前端 DATA 结构对齐的 JSON
GET /                  → 同目录 index.html
GET /<file>            → 同目录静态文件

设计约束（对齐数据连接三关卡）：
- 只读：hub.db 以 mode=ro 打开；不写任何中台文件、不读凭据文件（config.json/feishu.json 均不碰）
- 入校验：每个真源独立 try/except，单源失败降级为 {"error": ...} 字段，不拖垮整体
- 出核对：响应带 generated_at 与各源 raw 计数，前端可核对口径
启动：python3 hub_overview.py [--port 3355]
"""
import json, sqlite3, os, re, time, shutil, argparse, subprocess
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HUB_DIR = os.path.expanduser("~/.agent-autoloop")
HUB_DB = os.path.join(HUB_DIR, "hub.db")
RULES = os.path.join(HUB_DIR, "rules.json")
LOG_DIR = os.path.join(HUB_DIR, "logs")
QUEUE = "/Volumes/ZHITAI/WorkBuddy/Claw/.autopilot/QUEUE.md"
CLAW_REPO = os.path.dirname(os.path.dirname(QUEUE))          # <repo>/.autopilot/QUEUE.md → <repo>
CLAW_SCRIPTS = os.path.join(CLAW_REPO, "scripts")
BASE_DIR = os.path.dirname(CLAW_REPO)                        # 各项目同级父目录，避免逐条写死绝对路径
# 项目卡真源：只在同级目录里按名字探测 .git，找不到就诚实标「未定位」
PROJECTS = [("Claw", "Claw", "P0"), ("QTS", "QTS", "P1"),
            ("StockInsight", "StockInsight", "P1"), ("PMF", "project-monitor-fusion", "P1"),
            ("EAK", "engineering-audit-kit", "P2")]
PROXY_LOGS = [os.path.expanduser("~/Library/Logs/proxy-deepseek.stdout.log"),  # v1.8.0 起（持久路径）
              "/tmp/proxy-deepseek.stdout.log"]                                  # 切换前旧路径，过渡期合并计数
PROXY_TAIL = 4 * 1024 * 1024   # 只读尾部 4MB（约 10 天量），避免日志无限增长后每次全量扫
PROXY_DAILY = os.path.expanduser("~/.agent-autoloop/hub-proxy-daily.json")  # 每日计数快照（补重启丢数）
_proxy_cache = {"key": None, "stats": None}
TZ = timezone(timedelta(hours=8))  # Asia/Shanghai
AA = shutil.which("agent-autoloop") or os.path.expanduser("~/.local/bin/agent-autoloop")
AUTH_PY = os.path.expanduser("~/.workbuddy/binaries/python/versions/3.13.12/bin/python3")
PUSH_DAILY = os.path.expanduser("~/.local/bin/autoloop-feishu-push.py")
CI_SCRIPT = os.path.expanduser("~/.local/bin/hub-ci-status.py")   # 由 install 脚本从 deploy/ 同步
ACTION_LOG = os.path.expanduser("~/Library/Logs/hub-overview-actions.log")

# 快捷操作白名单：key 是页面唯一可传的标识，命令 argv 由服务端**固定拼装**，
# 前端永远无法传入命令或参数（杜绝命令注入）。mode=confirm 需请求带 ack=true。
# 只收「已核过源码/副作用」的动作：inspection 用 --print 不写盘，digest 用 --dry-run 不推群。
ACTIONS = {
    "status":       {"name": "查中台状态", "desc": "只读 · agent-autoloop status", "mode": "safe"},
    "doctor":       {"name": "检查配置",   "desc": "只读 · 已知 2 项告诫（Node<24 / 未接原生通道）", "mode": "safe"},
    "diagnose":     {"name": "触发一轮诊断", "desc": "emit chain.start → 诊断/复核双角色", "mode": "confirm", "timeout": 60},
    "repush_daily": {"name": "重推今日日报", "desc": "幂等 · 已有则 SKIP", "mode": "confirm", "timeout": 60},
    "inspection":   {"name": "立即巡检",   "desc": "只读 · inspection_report.py --print（不写盘、不推送）", "mode": "safe", "timeout": 90, "out_limit": 1800},
    "digest_dry":   {"name": "群总结预览", "desc": "dry-run · 只输出摘要，不推群", "mode": "safe", "timeout": 90, "out_limit": 2200},
    "ci_status":    {"name": "查 CI 状态", "desc": "只读 · gh 逐仓取最近 3 次（约 8s）", "mode": "safe", "timeout": 90, "out_limit": 2400},
}
_last_hit = {}   # 防连点：同动作 5s 内重复直接忽略

def now(): return datetime.now(TZ)

def db_ro():
    con = sqlite3.connect(f"file:{HUB_DB}?mode=ro", uri=True, timeout=3)
    con.row_factory = sqlite3.Row
    return con

def q(con, sql, args=()):
    try:
        return [dict(r) for r in con.execute(sql, args).fetchall()]
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

def local_day(iso):
    """ISO UTC 字符串 → 本地日期 'YYYY-MM-DD'；失败返回 None"""
    if not iso: return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ).strftime("%Y-%m-%d")
    except Exception:
        return None

def proxy_stats():
    """代理请求计数：实时读 /tmp 日志 + 每日快照取 max，解决「重启后计数归零」。
    /tmp 日志仍可能缺数（重启到本次采集之间），故口径标注为「快照 + 实时取大」。"""
    today = now().strftime("%Y-%m-%d")
    days = [(now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

    pat = re.compile(r"^\[req\] ts=(\S+) model=(\S+) status=(\d+)")
    keys, readable = [], False
    for path in PROXY_LOGS:
        try:
            st = os.stat(path)
        except Exception:
            continue
        readable = True
        keys.append((path, st.st_mtime, st.st_size))
    ck = (today, tuple(keys))
    if keys and _proxy_cache.get("key") == ck and _proxy_cache.get("stats"):
        return _proxy_cache["stats"]          # 文件未变 + 同日 → 直接用缓存

    live, fail_live = {}, {}
    for path, _mt, size in keys:
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                if size > PROXY_TAIL:          # 大文件只读尾部，跳过可能被截断的首行
                    fh.seek(size - PROXY_TAIL)
                    fh.readline()
                for line in fh:
                    if not line.startswith("[req]"):
                        continue
                    m = pat.match(line)
                    if not m:
                        continue
                    d = m.group(1)[:10]
                    if d in days:
                        live[d] = live.get(d, 0) + 1
                        if m.group(3) != "200":
                            fail_live[d] = fail_live.get(d, 0) + 1
        except Exception:
            continue
    _proxy_cache["key"] = ck

    # 合并快照：取每日 max，避免重启后倒退
    daily = {}
    try:
        daily = json.load(open(PROXY_DAILY, encoding="utf-8")) or {}
    except Exception:
        daily = {}
    before = json.dumps(daily, sort_keys=True)
    for d in days:
        cur = daily.get(d) or [0, 0]
        n = max(int(cur[0]), live.get(d, 0))
        f = max(int(cur[1] if len(cur) > 1 else 0), fail_live.get(d, 0))
        daily[d] = [n, f]
    if json.dumps(daily, sort_keys=True) != before:
        try:
            os.makedirs(os.path.dirname(PROXY_DAILY), exist_ok=True)
            with open(PROXY_DAILY, "w", encoding="utf-8") as fh:
                json.dump({k: daily[k] for k in sorted(daily)[-30:]}, fh)
        except Exception:
            pass

    t, tf = daily.get(today, [0, 0])
    week = sum(daily.get(d, [0, 0])[0] for d in days)
    out = {"ok": True, "today": t, "week": week, "fail_today": tf,
           "note": ("代理计数 · 快照+双日志" if readable else "代理日志不可读，仅用快照")}
    _proxy_cache["stats"] = out
    return out

def git_info(path):
    """取 branch / 最近提交 / 未提交改动数；失败返回 None"""
    try:
        br = subprocess.run(["git", "-C", path, "rev-parse", "--abbrev-ref", "HEAD"],
                            capture_output=True, text=True, timeout=5).stdout.strip()
        lg = subprocess.run(["git", "-C", path, "log", "-1", "--format=%h|%ad|%s", "--date=format:%m-%d %H:%M"],
                            capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", path, "status", "--porcelain"],
                               capture_output=True, text=True, timeout=8).stdout.count("\n")
        if not br or not lg:
            return None
        h, t, s = (lg.split("|", 2) + ["", "", ""])[:3]
        return {"branch": br, "hash": h, "time": t, "subject": s[:42], "dirty": dirty}
    except Exception:
        return None

def collect():
    # 预置完整空结构：任何单源失败都返回空数组而非「缺键」，
    # 避免前端在「真数据模式」下沿用示例数据造成假事实（审计 M1 的服务端侧保险）
    out = {"generated_at": now().isoformat(timespec="seconds"), "sources": {},
           "kpi": {"today": [], "week": []},
           "tasks": [], "logs": [], "todos": [], "metrics": [],
           "callChart": {"days": [], "ok": [], "fail": [], "note": "暂无数据"},
           "assets": {"models": [], "services": [], "apps": []}}
    today = now().strftime("%Y-%m-%d")
    days = [(now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]

    # 一次性采集（审计 L1）：QUEUE.md 与 launchctl 各只取一次，供后续多处复用
    todo_blocks, todo_err = None, None
    try:
        todo_blocks = parse_todo()
    except Exception as e:
        todo_err = f"{type(e).__name__}: {e}"
    svc_rows, svc_err = launchd_rows()
    ps = proxy_stats()

    # ---- hub.db（只读）----
    con = None
    try:
        con = db_ro()
        runs = q(con, "SELECT id,rule,state,agent,created_at,finished_at,summary,error,usage FROM runs ORDER BY created_at DESC LIMIT 500")
        if isinstance(runs, dict): raise RuntimeError(runs["error"])
        scheds = q(con, "SELECT rule,cron,next_at,skipped_at FROM schedules")
        if isinstance(scheds, dict): raise RuntimeError(scheds["error"])
        evs = q(con, "SELECT id,source,type,subject,summary,received_at FROM events ORDER BY received_at DESC LIMIT 300")
        if isinstance(evs, dict): raise RuntimeError(evs["error"])
        out["sources"]["hub.db"] = {"runs": len(runs), "runs_limit": 500,
                                    "schedules": len(scheds), "events_tail": len(evs)}

        # 按日聚合（本地时区）
        by_day = {d: 0 for d in days}
        done_day = {d: 0 for d in days}
        fail_day = {d: 0 for d in days}   # cancelled 计入失败侧（保守口径）
        tok_day = {d: [0, 0] for d in days}  # [input, output]
        for r in runs:
            d = local_day(r.get("created_at"))
            if d in by_day:
                by_day[d] += 1
                s = r.get("state")
                if s == "done": done_day[d] += 1
                elif s == "cancelled": fail_day[d] += 1
                u = r.get("usage")
                if isinstance(u, dict):
                    tok_day[d][0] += u.get("input", 0) or 0
                    tok_day[d][1] += u.get("output", 0) or 0

        t_runs = [r for r in runs if local_day(r.get("created_at")) == today]
        t_done = sum(1 for r in t_runs if r["state"] == "done")
        # LLM token 近 7 日
        sum_in = sum(v[0] for v in tok_day.values()); sum_out = sum(v[1] for v in tok_day.values())
        t_in = tok_day[today][0]; t_out = tok_day[today][1]

        # 无时序真源的 KPI 不伪造趋势条（spark=None → 前端不渲染）
        out["kpi"] = {
            "today": [
                {"label": "调度轮次(今日)", "value": len(t_runs), "unit": "轮",
                 "trend": f"7日 {sum(by_day.values())} 轮", "cls": "", "spark": [by_day[d] for d in days]},
                {"label": "完成轮次(今日)", "value": t_done, "unit": "轮",
                 "trend": f"7日 done {sum(done_day.values())}", "cls": "ok", "spark": [done_day[d] for d in days]},
                {"label": "LLM Token(今日)", "value": f"{(t_in+t_out)/1000:.1f}k",
                 "unit": "tok", "trend": f"in {t_in//1000}k/out {t_out//1000}k", "cls": "purple",
                 "spark": [round((tok_day[d][0]+tok_day[d][1])/1000, 1) for d in days]},
                {"label": "hub 调度规则", "value": len(scheds), "unit": "条",
                 "trend": "hub.db schedules", "cls": "", "spark": None},
                {"label": "待办事项", "value": len(todo_blocks) if todo_blocks is not None else "—", "unit": "条",
                 "trend": "QUEUE.md TODO 段", "cls": "warn", "spark": None},
                {"label": "事件(近7日)", "value": sum(1 for e in evs if local_day(e.get("received_at")) in days),
                 "unit": "条", "trend": f"取样最近 {len(evs)} 条", "cls": "", "spark": None},
                {"label": "代理请求(今日)", "value": ps.get("today", 0), "unit": "次",
                 "trend": f"7日 {ps.get('week', 0)} 次", "cls": "", "spark": None},
                {"label": "代理失败(今日)", "value": ps.get("fail_today", 0), "unit": "次",
                 "trend": ps.get("note", ""),
                 "cls": "bad" if ps.get("fail_today") else "ok", "spark": None},
            ],
            "week": None,  # 前端保留切换；真数据暂只出今日口径，week 复用今日
        }
        out["kpi"]["week"] = [
            {"label": "调度轮次(7日)", "value": sum(by_day.values()), "unit": "轮",
             "trend": "runs 视图", "cls": "", "spark": [by_day[d] for d in days]},
            {"label": "完成轮次(7日)", "value": sum(done_day.values()), "unit": "轮",
             "trend": f"cancelled {sum(fail_day.values())} 未计", "cls": "ok", "spark": [done_day[d] for d in days]},
            {"label": "LLM Token(7日)", "value": f"{(sum_in+sum_out)/1000:.0f}k", "unit": "tok",
             "trend": f"in {sum_in//1000}k / out {sum_out//1000}k", "cls": "purple",
             "spark": [round((tok_day[d][0]+tok_day[d][1])/1000, 1) for d in days]},
            {"label": "hub 调度规则", "value": len(scheds), "unit": "条", "trend": "", "cls": "", "spark": None},
            {"label": "待办事项", "value": len(todo_blocks) if todo_blocks is not None else "—", "unit": "条", "trend": "", "cls": "warn", "spark": None},
            {"label": "事件(7日)", "value": sum(1 for e in evs if local_day(e.get("received_at")) in days),
             "unit": "条", "trend": f"取样最近 {len(evs)} 条", "cls": "", "spark": None},
            {"label": "代理请求(7日)", "value": ps.get("week", 0), "unit": "次", "trend": "", "cls": "", "spark": None},
            {"label": "代理失败(今日)", "value": ps.get("fail_today", 0), "unit": "次",
             "trend": ps.get("note", ""),
             "cls": "bad" if ps.get("fail_today") else "ok", "spark": None},
        ]

        # 状态映射以 runs 表真实取值为准（实测：done/nothing/cancelled/claimed），缺失值保留原文并落 queue 色
        state_map = {"done": ("done", "已完成"), "claimed": ("run", "运行中"), "running": ("run", "运行中"),
                     "queued": ("queue", "排队中"), "cancelled": ("fail", "已取消"),
                     "failed": ("fail", "失败"), "error": ("fail", "失败"), "nothing": ("queue", "无操作")}
        out["tasks"] = [{
            "name": f"#{r['id']} {r['rule']}",
            "desc": (r.get("summary") or r.get("error") or "")[:80],
            "status": state_map.get(r["state"], ("queue", r["state"]))[0],
            "statusText": state_map.get(r["state"], ("queue", r["state"]))[1],
            "pct": 100 if r["state"] == "done" else (60 if r["state"] in ("claimed", "running") else 0),
            "time": (local_day(r.get("created_at")) or "") + " " + (r.get("created_at") or "")[11:19],
        } for r in runs[:8]]

        # 近 7 日轮次柱状图（口径：轮次数，非 LLM 原始调用次数）
        out["callChart"] = {"days": [d[5:] for d in days],
                            "ok": [done_day[d] for d in days],
                            "fail": [fail_day[d] for d in days],
                            "note": "口径=hub 轮次（done/cancelled），非模型原始调用次数"}

        # 资源水位：只给可核算的真实数值 + 口径说明，不做无阈值依据的百分比条
        out["metrics"] = [
            {"label": "runs 取样条数", "val": f"{len(runs)} 条（上限 500）", "note": "hub.db runs 视图，按 created_at 倒序"},
            {"label": "今日 Token in/out", "val": f"{t_in//1000}k / {t_out//1000}k", "note": "runs.usage 聚合，非原始请求数"},
            {"label": "cancelled（取样内）", "val": str(sum(1 for r in runs if r['state'] == 'cancelled')), "note": "失败侧保守计入"},
            {"label": "hub.db 体积", "val": db_size(), "note": "含 -wal/-shm"},
            {"label": "launchd com.user.*", "val": f"{len(svc_rows)} 个", "note": "launchctl list 实时计数"},
            {"label": "代理请求(今日)", "val": f"{ps.get('today', 0)} 次 / 失败 {ps.get('fail_today', 0)}",
             "note": ps.get("note", "")},
        ]

        # 日志区 = events 事件账（结构化、有级别可判）+ 尾部日志行补充
        logs = []
        for e in evs[:300]:
            typ = (e.get("type") or "").lower()
            lvl = "ERROR" if ("fail" in typ or "error" in typ) else ("WARN" if ("warn" in typ or "pause" in typ or "skip" in typ) else "INFO")
            msg = " · ".join(str(x) for x in (e.get("summary"), e.get("subject")) if x) or f"事件 {e.get('id')} ({e.get('type')})"
            logs.append({"time": (e.get("received_at") or "")[11:19], "date": local_day(e.get("received_at")) or "",
                         "lvl": lvl, "src": e.get("type") or "event",
                         "msg": msg[:120]})
        out["logs"] = logs
    except Exception as e:
        out["sources"]["hub.db"] = {"error": f"{type(e).__name__}: {e}"}
    finally:
        # 常驻进程必须保证连接释放：异常路径漏关会每次泄漏 1 个 fd，数天耗尽后服务整体不可用
        if con is not None:
            try:
                con.close()
            except Exception:
                pass

    # ---- rules.json（agents → 模型卡）----
    try:
        rj = json.load(open(RULES))
        ags = rj.get("agents", {})
        for k, a in ags.items():
            out["assets"]["models"].append({
                "name": k, "desc": a.get("name", "") + (" · " + a.get("use", "") if a.get("use") else ""),
                "tag": "运行中", "tagCls": "done",
                "meta": {"执行": "command" if a.get("use") == "command" else str(a.get("use", "")),
                         "worker": a.get("worker", "-")}})
        out["sources"]["rules.json"] = {"agents": len(ags)}
    except Exception as e:
        out["sources"]["rules.json"] = {"error": str(e)}

    # ---- launchd com.user.* → 服务卡（复用开头一次性采集，审计 L1）----
    if svc_err:
        out["sources"]["launchd"] = {"error": svc_err}
    else:
        for s in svc_rows[:12]:
            running = s["pid"] != "-"
            out["assets"]["services"].append({
                "name": s["label"], "desc": f"launchd 服务 · last exit code {s['code']}",
                "tag": "运行中" if running else "待触发", "tagCls": "done" if running and s["code"] == "0" else ("warn" if s["code"] != "0" else "queue"),
                "meta": {"PID": s["pid"], "退出码": s["code"]}})
        out["sources"]["launchd"] = {"com.user": len(svc_rows)}

    # ---- QUEUE.md TODO 段（复用开头一次性解析，审计 L1）----
    if todo_err:
        out["sources"]["QUEUE.md"] = {"error": todo_err}
    else:
        for b in (todo_blocks or [])[:12]:
            first = b.lstrip("-[] ").strip()          # 去 markdown 勾选框前缀
            title = first.split("风险")[0].strip()[:80]  # 取风险标注前的主体
            out["todos"].append({"p": "P1", "title": title, "src": "QUEUE.md TODO 段", "due": "-", "done": False})
        out["sources"]["QUEUE.md"] = {"todo_blocks": len(todo_blocks or [])}

    # ---- 应用卡：同级目录探测 git 真源（找不到就诚实标「未定位」，不伪造状态）----
    apps = []
    for name, sub, prio in PROJECTS:
        p = os.path.join(BASE_DIR, sub)
        gi = git_info(p) if os.path.isdir(os.path.join(p, ".git")) else None
        if gi:
            dirty = gi["dirty"]
            apps.append({"name": f"{name}（{prio}）",
                         "desc": f"{gi['branch']} · {gi['subject']}",
                         "tag": f"未提交 {dirty}" if dirty else "工作区干净",
                         "tagCls": "warn" if dirty else "done",
                         "meta": {"最近提交": gi["time"], "hash": gi["hash"], "分支": gi["branch"]}})
        else:
            apps.append({"name": f"{name}（{prio}）", "desc": "同级目录下未找到 git 仓库",
                         "tag": "未定位", "tagCls": "queue", "meta": {"路径": "未找到"}})
    out["assets"]["apps"] = apps
    out["sources"]["git"] = {"projects": len(PROJECTS),
                             "found": sum(1 for a in apps if a["tag"] != "未定位")}

    # 快捷操作元数据（白名单唯一真源在服务端，前端只按 key 调用）
    out["actions"] = [{"key": k, **v} for k, v in ACTIONS.items()]
    return out

def build_argv(key):
    """按 key 固定拼装命令；前端无法影响任何参数。
    Claw 脚本路径由 QUEUE 位置推导（单一配置点），不另写死绝对路径。"""
    if key == "status":       return [AA, "status"]
    if key == "doctor":       return [AA, "doctor"]
    if key == "diagnose":     return [AA, "emit", "chain.start", "--subject", f"web-{int(time.time())}"]
    if key == "repush_daily": return [AUTH_PY, PUSH_DAILY]
    if key == "inspection":   return [AUTH_PY, os.path.join(CLAW_SCRIPTS, "inspection_report.py"), "--print"]
    if key == "digest_dry":   return [AUTH_PY, os.path.join(CLAW_SCRIPTS, "feishu_daily_digest.py"),
                                      "--dry-run", "--date", now().strftime("%Y-%m-%d")]
    if key == "ci_status":    return [AUTH_PY, CI_SCRIPT]
    raise KeyError(key)

def audit_action(key, rc, elapsed, out_text):
    try:
        os.makedirs(os.path.dirname(ACTION_LOG), exist_ok=True)
        with open(ACTION_LOG, "a", encoding="utf-8") as f:
            f.write(f"{now().strftime('%Y-%m-%d %H:%M:%S')}\t{key}\trc={rc}\t{elapsed}s\t"
                    f"{out_text.replace(chr(10), ' ')[:200]}\n")
    except Exception:
        pass

def run_action(key, ack):
    """执行白名单动作，返回 (http_code, payload)"""
    meta = ACTIONS.get(key)
    if not meta:
        return 400, {"error": f"未知动作：{key}"}
    if meta["mode"] == "confirm" and ack is not True:
        return 412, {"error": "该动作有副作用，需要 ack=true 确认"}
    t = time.time()
    if key in _last_hit and t - _last_hit[key] < 5:
        return 429, {"error": "5 秒内已触发过，忽略重复点击"}
    _last_hit[key] = t
    try:
        argv = build_argv(key)
    except KeyError:
        return 400, {"error": "动作未实现"}
    t0 = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=int(meta.get("timeout", 45)))
        rc, raw = p.returncode, (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    except subprocess.TimeoutExpired:
        rc, raw = -1, f"执行超时（{meta.get('timeout', 45)}s 上限），已终止"
    except Exception as e:
        rc, raw = -1, f"{type(e).__name__}: {e}"
    elapsed = round(time.time() - t0, 2)
    # 轻脱敏：抹掉本机绝对路径，输出截断（报告类动作可放宽上限），避免把内部路径带给前端
    limit = int(meta.get("out_limit", 600))
    text = re.sub(r"/Users/[\w.\-]+(?:/[\w.\-\u4e00-\u9fa5]+)*", "<path>", raw.strip())[:limit]
    audit_action(key, rc, elapsed, text)
    return 200, {"ok": rc == 0, "action": key, "rc": rc, "elapsed": elapsed, "out": text}

def launchd_rows():
    """一次采集 launchctl 列表，供服务卡与 metrics 共用；返回 (rows, err)"""
    try:
        rows = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
        names = []
        for l in rows.splitlines():
            parts = l.split("\t")
            if len(parts) >= 3 and parts[2].startswith("com.user."):
                names.append({"pid": parts[0], "code": parts[1], "label": parts[2]})
        return names, None
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"

def parse_todo():
    """QUEUE.md 的 TODO 段按 '---' 分块，返回非空块文本列表"""
    txt = open(QUEUE, encoding="utf-8").read()
    seg = txt.split("## TODO", 1)[1]
    seg = re.split(r"^## (DOING|BLOCKED|DONE|HANDOFF)\b", seg, flags=re.M)[0]
    blocks = [b.strip().replace("\n", " ") for b in seg.split("\n---\n")]
    return [b for b in blocks if b and b != ""]

def db_size():
    try:
        total = sum(os.path.getsize(os.path.join(HUB_DIR, f))
                    for f in ("hub.db", "hub.db-wal", "hub.db-shm") if os.path.exists(os.path.join(HUB_DIR, f)))
        return f"{total/1048576:.1f}MB"
    except Exception:
        return "-"

def launchd_count():
    try:
        rows = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=5).stdout
        return sum(1 for l in rows.splitlines() if "com.user." in l)
    except Exception:
        return -1

BASE = os.path.realpath(os.path.join(HERE, ".."))   # 静态根默认 = 脚本上级（仓库内直接跑时）

class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        """健康检查/监控工具常用 HEAD，返回与 GET 一致的元信息，不返回 body"""
        if self.path.startswith("/api/hub/overview"):
            self._send(200, b"", "application/json; charset=utf-8")
        else:
            fp = self._resolve()
            if fp: self._send(200, b"", "text/html; charset=utf-8" if fp.endswith(".html") else "application/octet-stream")
            else: self._send(404, b"", "text/plain")

    def _resolve(self):
        """把请求路径解析为静态根内的真实文件；越界或不存在返回 None"""
        path = os.path.normpath(self.path.split("?", 1)[0].lstrip("/") or "index.html")  # 剥离 query，审计 M2
        fp = os.path.realpath(os.path.join(BASE, path))
        if fp != BASE and not fp.startswith(BASE + os.sep):
            return None   # 越界（如 ../../etc/hosts）
        return fp if os.path.isfile(fp) else None

    def do_POST(self):
        """快捷操作执行入口：只有白名单 key 能跑，命令 argv 完全由服务端拼装"""
        if self.path.split("?", 1)[0] != "/api/hub/action":
            self._send(404, b'{"error":"not found"}', "application/json; charset=utf-8"); return
        # 防 CSRF：要求自定义头（跨站请求会触发 preflight，本服务不响应 CORS 预检）
        if self.headers.get("X-Hub-Request") != "1":
            self._send(403, json.dumps({"error": "缺少 X-Hub-Request 头，拒绝执行"},
                                       ensure_ascii=False).encode(), "application/json; charset=utf-8"); return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 2048:
                raise ValueError("body 长度为 0 或超限")
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception as e:
            self._send(400, json.dumps({"error": f"请求体解析失败：{e}"}, ensure_ascii=False).encode(),
                       "application/json; charset=utf-8"); return
        code, payload = run_action(str(body.get("action", "")), body.get("ack") is True)
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path.startswith("/api/hub/overview"):
            try:
                body = json.dumps(collect(), ensure_ascii=False).encode()
                self._send(200, body, "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode(),
                           "application/json; charset=utf-8")
        else:
            fp = self._resolve()
            if not fp:
                self._send(404, b"not found", "text/plain"); return
            ctype = "text/html; charset=utf-8" if fp.endswith(".html") else "application/octet-stream"
            self._send(200, open(fp, "rb").read(), ctype)

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # 工作台数据不缓存
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass  # 静默访问日志

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=3355)
    ap.add_argument("--static-root", default=None,
                    help="页面静态根目录；常驻安装时指向内盘副本目录（默认=脚本上级）")
    args = ap.parse_args()
    if args.static_root:
        BASE = os.path.realpath(args.static_root)   # 内盘副本运行时静态根不等于脚本位置
    print(f"[hub-overview] 只读聚合 API 就绪 → http://127.0.0.1:{args.port}  (静态根 {BASE})")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
