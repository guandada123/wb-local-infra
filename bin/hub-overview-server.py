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
# 项目卡真源：sub 可为目录名（相对 BASE_DIR）或绝对路径（~ 展开）。
# QTS 不在外置卷同级目录，2026-11-25 由 docker inspect 的 bind mount 查出真实路径。
PROJECTS = [("Claw", "Claw", "P0"),
            ("QTS", os.path.expanduser("~/WorkBuddy/QuantTradingSystem"), "P1"),
            ("StockInsight", "StockInsight", "P1"), ("PMF", "project-monitor-fusion", "P1"),
            ("EAK", "engineering-audit-kit", "P2")]
PROXY_LOGS = [os.path.expanduser("~/Library/Logs/proxy-deepseek.stdout.log"),  # v1.8.0 起（持久路径）
              "/tmp/proxy-deepseek.stdout.log"]                                  # 切换前旧路径，过渡期合并计数
PROXY_TAIL = 4 * 1024 * 1024   # 只读尾部 4MB（约 10 天量），避免日志无限增长后每次全量扫
PROXY_DAILY = os.path.expanduser("~/.agent-autoloop/hub-proxy-daily.json")
# 第三方补丁的落点（上游仓的克隆）。重装/升级会整目录覆盖，补丁随之消失。
# 仅"等它再出错"太慢（可能几周），故每次采集直接核对两处签名。
PATCH_VALIDATE = os.path.expanduser("~/.agent-autoloop/app/protocol/validate.ts")
CI_CACHE = os.path.expanduser("~/.agent-autoloop/hub-ci-cache.json")
# QTS 告警库（只读）。2026-11-26 起页面要能直接看到「当前有几条未恢复告警」——
# 当晚就有一条真实的板块超限 open 着，而页面上完全看不见。
DOCKER = shutil.which("docker") or "/opt/homebrew/bin/docker"
QTS_PG = "quant-postgres"
QTS_DB = "quant_trading"
QTS_PG_USER = "quant_user"       # CI 结果后台缓存（15 分钟过期）
_proxy_cache = {"key": None, "stats": None}
_status_cache = {"ts": 0, "data": None}
_ci_trigger = {"at": 0}
_collect_cache = {"ts": 0, "data": None}
CACHE_TTL = 5          # 主接口响应缓存（秒）：页面 5 分钟刷新，无需每次全量采集
CI_STALE = 900         # CI 缓存 15 分钟视为过期
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

def iso_mtime(path):
    """文件最后修改时间（本地时区 ISO）；读不到返回 None，绝不抛。

    供 sources 的数据新鲜度判定使用：只写字段，不参与任何展示逻辑，
    观察侧（hub-overview-watch.py）自行决定阈值。
    """
    try:
        return datetime.fromtimestamp(os.stat(path).st_mtime, TZ).isoformat(timespec="seconds")
    except OSError:
        return None

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
            # 原子写：服务是多线程的，直写会被并发请求读到半个 JSON（读失败 → daily={} →
            # 只写回最近 7 天、历史天数被抹掉，且当日值可能倒退）。先写临时文件再 replace。
            tmp = PROXY_DAILY + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({k: daily[k] for k in sorted(daily)[-30:]}, fh)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, PROXY_DAILY)
        except Exception:
            pass

    t, tf = daily.get(today, [0, 0])
    week = sum(daily.get(d, [0, 0])[0] for d in days)
    out = {"ok": True, "today": t, "week": week, "fail_today": tf,
           "note": ("代理计数 · 快照+双日志" if readable else "代理日志不可读，仅用快照")}
    _proxy_cache["stats"] = out
    return out

def status_snapshot():
    """取中台权威状态（`agent-autoloop status --json`）：等你决策 / 在跑 / 排队 / 今日完成 + 待回答卡片。
    这是唯一「需要人动手」的指标来源，30s 缓存避免频繁起进程。"""
    t = time.time()
    if _status_cache["data"] and t - _status_cache["ts"] < 30:
        return _status_cache["data"]
    try:
        p = subprocess.run([AA, "status", "--json"], capture_output=True, text=True, timeout=15)
        d = json.loads(p.stdout or "{}")
        tot = d.get("totals") or {}
        cards = [{"title": (c.get("title") or "")[:60], "kind": c.get("kind") or "",
                  "at": (c.get("createdAt") or "")[5:16]} for c in (d.get("cards") or [])[:5]]
        out = {"ok": True, "attention": tot.get("attention", 0), "running": tot.get("running", 0),
               "queued": tot.get("queued", 0), "retrying": tot.get("retrying", 0),
               "done_today": tot.get("doneToday", 0), "cards": cards}
    except Exception as e:
        out = {"ok": False, "attention": -1, "running": -1, "queued": -1, "retrying": -1,
               "done_today": -1, "cards": [], "note": type(e).__name__}
    _status_cache.update({"ts": t, "data": out})
    return out

def ci_cache():
    """CI 结果缓存：读到就立即返回（0 成本）；过期或缺失则**后台异步**刷新，不阻塞本次响应。"""
    data, mtime = {}, 0.0
    try:
        mtime = os.stat(CI_CACHE).st_mtime
        data = json.load(open(CI_CACHE, encoding="utf-8"))
    except Exception:
        pass
    stale = (time.time() - mtime) > CI_STALE
    if (stale or not data) and time.time() - _ci_trigger["at"] > 60:
        _ci_trigger["at"] = time.time()
        try:
            subprocess.Popen([AUTH_PY, CI_SCRIPT, "--json", "--out", CI_CACHE],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except Exception:
            pass
    return data or {}

def git_info(path):
    """取 branch / 最近提交 / 未提交数：2 次 git 调用（status --branch 合并拿分支与脏文件）"""
    try:
        st = subprocess.run(["git", "-C", path, "status", "--porcelain=v1", "--branch"],
                            capture_output=True, text=True, timeout=8)
        if st.returncode != 0:
            return None
        lines = (st.stdout or "").splitlines()
        head = lines[0] if lines else ""
        m = re.match(r"^## ([^\s.]+)", head)
        branch = m.group(1) if m else "?"
        changed = [l for l in lines[1:] if l.strip()]
        dirty = len(changed)
        # 运行产物（.autopilot/ 与 work/ 下的落盘）不该被当成"代码改动"，单列出来避免误判
        runtime = sum(1 for l in changed
                      if re.search(r"(?:^|\s)(?:\.autopilot|work)/", l[3:] if len(l) > 3 else l))
        lg = subprocess.run(["git", "-C", path, "log", "-1", "--format=%h|%ad|%s", "--date=format:%m-%d %H:%M"],
                            capture_output=True, text=True, timeout=5).stdout.strip()
        if not lg:
            return None
        h, tm, s = (lg.split("|", 2) + ["", "", ""])[:3]
        return {"branch": branch, "hash": h, "time": tm, "subject": s[:42],
                "dirty": dirty, "runtime": runtime}
    except Exception:
        return None


# ── 服务日志真实报错（events 表覆盖不到底层 traceback / 端点不支持 / 计费类错误）──
SVC_LOG_DIR = os.path.expanduser("~/.agent-autoloop/logs")
SVC_LOG_TAIL = 256 * 1024        # 每个文件只读尾部，防日志膨胀拖慢采集
SVC_ERR_RE = re.compile(r"(traceback|exception|\berror\b|\bfailed\b|❌|rc=[1-9])", re.I)
# 噪音：① no such file 等已知易过 ② triage 的 [JUDGE] 行是「被研判消息的标题」（标题本身常含"失败"二字），不是报错
SVC_SKIP_RE = re.compile(r"(no such file|Cache hit|git config|\[JUDGE\])", re.I)
# 栈体行（缩进的 File "..."/源码片段/^~）无独立信息，只留异常类型与消息那行
_SVC_TBODY = re.compile(r"^\s+(File \"|\^+~*|response =|raise |return |self\.)")
_SVC_BARE = re.compile(r"^traceback \(most recent call last\):?\s*$", re.I)  # 孤零零的栈头无信息
_SVC_TS1 = re.compile(r"^\[?(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")     # 2026-11-11 08:31:05
_SVC_TS2 = re.compile(r"^\[?(\d{2}-\d{2})\s(\d{2}:\d{2}:\d{2})")             # 11-11 08:31:05（无年）
_svc_cache = {"key": None, "rows": None}


def _svc_ts(line):
    """只认行内时间戳；没有就返回 ("", "")，绝不拿文件 mtime 冒充行时间。"""
    m = _SVC_TS1.match(line)
    if m:
        return m.group(1), m.group(2)
    m = _SVC_TS2.match(line)
    if m:
        return f"{datetime.now().year}-{m.group(1)}", m.group(2)
    return "", ""


def patch_state():
    """核对回执补丁是否还在。返回 (状态文案, 说明)。
    两处签名缺一不可：cancel 宽容（!== true）+ 报错指位（laterProblem）。"""
    try:
        with open(PATCH_VALIDATE, encoding="utf-8", errors="ignore") as fh:
            body = fh.read()
    except Exception as e:
        return "不可读", f"{type(e).__name__}"
    has_cancel = "later.cancel !== true" in body
    has_why = "function laterProblem" in body
    if has_cancel and has_why:
        return "在位", "两处签名齐（cancel 宽容 + 报错指位）"
    missing = []
    if not has_cancel:
        missing.append("cancel 宽容")
    if not has_why:
        missing.append("报错指位")
    return "缺失", "缺 " + "、".join(missing) + " → 回执会重新丢 later，按 patches/ 重打"

def open_alerts(limit=3):
    """读 QTS alerts 表里 status='open' 的行数与前几条文案（只读，docker exec psql）。"""
    sql = ("SELECT rule_id || '|' || coalesce(level,'') || '|' || "
           "regexp_replace(left(message, 90), '[|\n\r]', ' ', 'g') "
           f"FROM alerts WHERE status = 'open' ORDER BY triggered_at DESC")
    try:
        p = subprocess.run(
            [DOCKER, "exec", QTS_PG, "psql", "-U", QTS_PG_USER, "-d", QTS_DB, "-tAc", sql],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        return {"ok": False, "count": 0, "rows": [], "note": f"{type(e).__name__}"}
    if p.returncode != 0:
        return {"ok": False, "count": 0, "rows": [],
                "note": (p.stderr or "psql 失败").strip().splitlines()[0][:60]}
    rows = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    parsed = []
    for ln in rows[:limit]:
        parts = ln.split("|", 2)
        if len(parts) == 3:
            parsed.append({"rule": parts[0], "level": parts[1], "msg": parts[2]})
    return {"ok": True, "count": len(rows), "rows": parsed, "note": ""}

def service_logs(per_file=3, total=30):
    """从 ~/.agent-autoloop/logs/*.log 抽真实报错行 → 日志区可见。
    时间只取行内时间戳；行内无时间戳则留空（不臆造）。"""
    try:
        files = [os.path.join(SVC_LOG_DIR, n) for n in os.listdir(SVC_LOG_DIR) if n.endswith(".log")]
    except Exception:
        return []
    key = []
    rows = []
    for path in files:
        try:
            st = os.stat(path)
        except OSError:
            continue
        key.append((path, st.st_mtime, st.st_size))
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                if st.st_size > SVC_LOG_TAIL:
                    fh.seek(st.st_size - SVC_LOG_TAIL)
                    fh.readline()
                hits = [l.strip() for l in fh
                        if SVC_ERR_RE.search(l) and not SVC_SKIP_RE.search(l)
                        and not _SVC_BARE.match(l.strip()) and not _SVC_TBODY.match(l.rstrip())]
        except Exception:
            continue
        if not hits:
            continue
        for line in hits[-per_file:]:
            d, t = _svc_ts(line)
            lvl = "WARN" if re.search(r"\[warn\]|\bwarn(ing)?\b", line, re.I) else "ERROR"
            rows.append({"date": d, "time": t, "lvl": lvl,
                         "src": os.path.basename(path).replace(".log", ""),
                         "msg": line[:160], "_k": (d, t) if d else ("", "")})
    k = tuple(key)
    if _svc_cache["key"] == k and _svc_cache["rows"] is not None:
        out = _svc_cache["rows"]
    else:
        out = sorted(rows, key=lambda r: r["_k"], reverse=True)[:total]
        _svc_cache.update({"key": k, "rows": out})
    return [dict(r) for r in out]

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
    st = status_snapshot()
    ci = ci_cache()
    oa = open_alerts()
    old_days, old_title = (None, None)
    if todo_blocks is not None:
        try:
            old_days, old_title = queue_oldest()
        except Exception:
            pass

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
                                    "schedules": len(scheds), "events_tail": len(evs),
                                    "last_run_at": (runs[0].get("created_at") if runs else None)}

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
                if isinstance(u, str):          # 库里 usage 是 JSON 文本，不是 dict
                    try:
                        u = json.loads(u)
                    except Exception:
                        u = None
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
                # 置顶：唯一需要人动手的指标
                {"label": "等你决策", "value": st["attention"] if st["attention"] >= 0 else "—", "unit": "条",
                 "trend": (st["cards"][0]["title"][:26] if st["cards"] else "无待回答卡片"),
                 "cls": "bad" if st["attention"] > 0 else "ok", "spark": None},
                {"label": "在跑轮次", "value": st["running"] if st["running"] >= 0 else "—", "unit": "轮",
                 "trend": f"排队 {st['queued']} · 重试 {st['retrying']}",
                 "cls": "run" if st["running"] > 0 else "", "spark": None},
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
                 "trend": (f"最老 {old_days} 天 · {old_title[:20]}" if old_days is not None
                           else "QUEUE.md TODO 段"),
                 "cls": ("bad" if (old_days or 0) >= 7 else ("warn" if (old_days or 0) >= 3 else "")),
                 "spark": None},
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
            {"label": "等你决策", "value": st["attention"] if st["attention"] >= 0 else "—", "unit": "条",
             "trend": "当前态（非 7 日累计）", "cls": "bad" if st["attention"] > 0 else "ok", "spark": None},
            {"label": "在跑轮次", "value": st["running"] if st["running"] >= 0 else "—", "unit": "轮",
             "trend": f"排队 {st['queued']}", "cls": "run" if st["running"] > 0 else "", "spark": None},
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

        # 回执不合规次数（7 日）：既是问题指标，也是「第三方补丁是否被升级覆盖」的哨兵——
        # 补丁一旦丢失，这个数字会重新涨。created_at 是 UTC ISO（带 T 和 Z），比较前去 T。
        rc_cnt, rc_last = 0, ""
        try:
            row = q(con, "SELECT COUNT(*) AS c, datetime(MAX(replace(substr(created_at,1,19),'T',' ')),'+8 hours') AS m "
                         "FROM cards WHERE title LIKE '%回执%' "
                         "AND replace(substr(created_at,1,19),'T',' ') >= datetime('now','-7 days')")
            if isinstance(row, list) and row:
                rc_cnt = int(row[0].get("c") or 0)
                rc_last = (row[0].get("m") or "")
        except Exception:
            pass

        # 资源水位：只给可核算的真实数值 + 口径说明，不做无阈值依据的百分比条
        out["metrics"] = [
            {"label": "runs 取样条数", "val": f"{len(runs)} 条（上限 500）", "note": "hub.db runs 视图，按 created_at 倒序"},
            {"label": "今日 Token in/out", "val": f"{t_in//1000}k / {t_out//1000}k", "note": "runs.usage 聚合，非原始请求数"},
            {"label": "cancelled（取样内）", "val": str(sum(1 for r in runs if r['state'] == 'cancelled')), "note": "失败侧保守计入"},
            {"label": "hub.db 体积", "val": db_size(), "note": "含 -wal/-shm"},
            {"label": "launchd com.user.*", "val": f"{len(svc_rows)} 个", "note": "launchctl list 实时计数"},
            {"label": "代理请求(今日)", "val": f"{ps.get('today', 0)} 次 / 失败 {ps.get('fail_today', 0)}",
             "note": ps.get("note", "")},
            {"label": "最老待办", "val": (f"{old_days} 天" if old_days is not None else "—"),
             "note": (f"{old_title[:40]}（仅统计群消息来源条目）" if old_title else "无带原文的待办")},
            {"label": "回执补丁", "val": patch_state()[0],
             "note": f"{patch_state()[1]}（{PATCH_VALIDATE.replace(os.path.expanduser('~'), '~')}）"},
            {"label": "未恢复告警", "val": f"{oa['count']} 条",
             "note": ("；".join(f"[{r['level']}] {r['msg']}" for r in oa["rows"])[:150]
                      if oa["count"] else ("读取失败：" + oa["note"] if not oa["ok"] else "无（全部已恢复）"))},
            {"label": "CI 未启动", "val": f"{sum(1 for v in (ci.get('repos') or {}).values() if v.get('not_started'))} 仓",
             "note": ("未跑=计费/额度拦截，不是代码红：" +
                      "、".join(f"{k}({v.get('secs', 0)}s)" for k, v in (ci.get("repos") or {}).items() if v.get("not_started"))
                      if any(v.get("not_started") for v in (ci.get("repos") or {}).values())
                      else "无（各仓 CI 均在正常跑）")},
            {"label": "回执不合规(7日)", "val": f"{rc_cnt} 次",
             "note": (f"最近 {rc_last}（本地时间）；滞后指标——补丁是否还在，看上面「回执补丁」那行"
                      if rc_cnt else "近 7 天无新增（滞后指标；补丁在位与否见「回执补丁」行）")},
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
        # 补：launchd 各服务日志里的真实报错（events 表看不到底层 traceback / 计费 / 端点不支持等）
        try:
            svc = service_logs()
            if svc:
                logs = svc + logs
        except Exception:
            pass
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
        out["sources"]["rules.json"] = {"agents": len(ags), "mtime": iso_mtime(RULES)}
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
            out["todos"].append({"p": "P1", "title": todo_title(b),
                                 "src": "QUEUE.md TODO 段", "due": "-", "done": False})
        out["sources"]["QUEUE.md"] = {"todo_blocks": len(todo_blocks or []), "mtime": iso_mtime(QUEUE)}

    # ---- 应用卡：同级目录探测 git 真源（找不到就诚实标「未定位」，不伪造状态）----
    apps = []
    for name, sub, prio in PROJECTS:
        p = sub if os.path.isabs(sub) else os.path.join(BASE_DIR, sub)
        gi = git_info_cached(p) if os.path.isdir(os.path.join(p, ".git")) else None
        # CI 缓存的 key 是目录名（脚本按目录扫描），显示名不同，两者都试
        _repos = ci.get("repos") or {}
        c = _repos.get(sub) or _repos.get(name) or {}
        # 计费/额度拦截的 run 只有 2~4 秒、0 步骤，conclusion 仍是 failure。
        # 直接画 ❌ 会让人以为代码红 —— 这里单独标「未启动」（标签由 hub-ci-status.py 给）。
        icon = {"success": "✅", "failure": "❌"}.get(c.get("conclusion"), "⏳")
        if c.get("not_started"):
            ci_meta = f"⛔ 未启动(疑计费) · {c.get('secs', 0)}s · {c.get('at', '')}".strip(" ·")
        elif not ci:
            ci_meta = "采集中…（后台首次约 9s）"
        elif c:
            ci_meta = f"{icon} {c.get('conclusion') or c.get('reason') or '无记录'} · {c.get('at', '')}".strip(" ·")
        else:
            ci_meta = "无记录"
        if gi:
            dirty = gi["dirty"]
            runtime = gi.get("runtime", 0)
            tag = ("工作区干净" if not dirty else
                   (f"未提交 {dirty}（运行产物 {runtime}）" if runtime else f"未提交 {dirty}"))
            apps.append({"name": f"{name}（{prio}）",
                         "desc": f"{gi['branch']} · {gi['subject']}",
                         "tag": tag,
                         "tagCls": "warn" if dirty - runtime > 0 else ("queue" if dirty else "done"),
                         "meta": {"最近提交": gi["time"], "hash": gi["hash"], "CI": ci_meta}})
        else:
            apps.append({"name": f"{name}（{prio}）", "desc": "同级目录下未找到 git 仓库",
                         "tag": "未定位", "tagCls": "queue",
                         "meta": {"路径": "未找到", "CI": ci_meta}})
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

def todo_title(line):
    """从 QUEUE 条目行提取可读标题：优先「要求: 复核 …」，否则去 ID 前缀的正文段。"""
    if "要求: 复核 " in line:
        return line.split("要求: 复核 ", 1)[1].split("；", 1)[0].strip()[:80]
    core = line.split("风险")[0].strip()
    m = re.match(r"^(T-[\w-]+)\s*·\s*(.+)$", core)
    return (m.group(2) if m else core)[:80]

_backlog_cache = {"ts": 0, "data": (None, None)}
_git_cache = {}            # path -> (ts, info)
GIT_TTL = 300              # 应用卡 git 信息 5 分钟缓存
BACKLOG_TTL = 300          # 「最老待办」5 分钟缓存

def queue_oldest():
    """最老待办的排队天数（按 inbox 原文 mtime 估算，仅覆盖群消息来源条目）。
    返回 (days, title)；无可用数据返回 (None, None)。
    性能：launchd 进程访问外置卷有 TCC 开销（实测每次 stat 数十 ms），故用一次 scandir
    取全量 mtime + 5 分钟缓存，避免每条待办各 stat 一次（10 条 = 10 次跨卷调用）。"""
    t = time.time()
    if _backlog_cache["data"][0] is not None and t - _backlog_cache["ts"] < BACKLOG_TTL:
        return _backlog_cache["data"]
    inbox = os.path.join(CLAW_REPO, ".autopilot", "inbox")
    mtimes = {}
    try:
        with os.scandir(inbox) as it:
            for e in it:
                m = re.match(r"^chat-([0-9a-f]{12})\.md$", e.name)
                if not m:
                    continue
                try:
                    mtimes[m.group(1)] = e.stat().st_mtime
                except OSError:
                    pass
    except OSError:
        return (None, None)
    best = None
    todo = parse_todo()
    for line in todo:
        m = re.search(r"chat-([0-9a-f]{12})\.md", line)
        if not m:
            continue
        mt = mtimes.get(m.group(1))
        if mt is None:
            continue
        if best is None or mt < best[0]:
            best = (mt, todo_title(line))
    out = (None, None) if not best else (round((t - best[0]) / 86400, 1), best[1])
    _backlog_cache.update({"ts": t, "data": out})
    return out

def git_info_cached(path):
    """git 信息 5 分钟缓存：外置卷 subprocess 开销大，而分支/提交在分钟级不变。"""
    t = time.time()
    hit = _git_cache.get(path)
    if hit and t - hit[0] < GIT_TTL:
        return hit[1]
    info = git_info(path)
    _git_cache[path] = (t, info)
    return info

def parse_todo():
    """QUEUE.md TODO 段的待办条目：按 `- [ ]` 行数清点。
    2026-11-19 修复：原按 markdown `---` 分块，多条挤一块时 KPI 少报（实测 10 条只报 4 条）。"""
    txt = open(QUEUE, encoding="utf-8").read()
    seg = txt.split("## TODO", 1)[1]
    seg = re.split(r"^## (DOING|BLOCKED|DONE|HANDOFF)\b", seg, flags=re.M)[0]
    return [l.strip()[6:].strip() for l in seg.splitlines() if l.strip().startswith("- [ ]")]

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

def collect_cached(force=False):
    """主接口响应缓存：TTL 内直接复用，避免每次请求全量采集（含 8 次 git / CLI / 日志扫描）。
    force=True 由「手动刷新」触发，跳过缓存立即重算。"""
    t = time.time()
    if force:                       # 手动刷新：连 git / 积压缓存一起失效，拿最新
        _git_cache.clear()
        _backlog_cache["ts"] = 0
    if not force and _collect_cache["data"] and (t - _collect_cache["ts"]) < CACHE_TTL:
        d = dict(_collect_cache["data"])
        d["cached"] = True
        return d
    d = collect()
    _collect_cache.update({"ts": t, "data": d})
    return d

def invalidate_caches():
    """动作执行后立即失效缓存，保证点完就能看到变化"""
    _collect_cache["data"] = None
    _status_cache["data"] = None
    _ci_trigger["at"] = 0

class QuietServer(ThreadingHTTPServer):
    """客户端中途断开（刷新/关页/超时重试）会让 wfile.write 抛 BrokenPipe/ConnectionReset，
    socketserver 默认打整段 traceback 到 stderr。这些不是服务故障，却会淹没真错误
    （2026-11-25 实测 err 日志里出现过 1 次 BrokenPipe、1 次 ConnectionReset）。
    只静默这两类，其它异常照旧上抛。"""

    daemon_threads = True

    def handle_error(self, request, client_address):
        import sys

        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


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
        if code == 200:
            invalidate_caches()          # 动作已改变状态 → 让下次读接口立刻反映
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path.startswith("/api/hub/overview"):
            try:
                force = "force=1" in self.path
                body = json.dumps(collect_cached(force=force), ensure_ascii=False).encode()
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
    QuietServer(("127.0.0.1", args.port), Handler).serve_forever()
