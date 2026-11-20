#!/Users/guan/.workbuddy/binaries/python/envs/default/bin/python3
"""
wb-event-poller.py — 事件轮询器 v0（router v0，2026-11-03 立项卡批准实现）

职责（只发现，不处置 —— 处置权归巡检中枢）：
  每 5 分钟只读扫描平台 automation_runs，捕获 result_success=0 的失败事件：
    → 去重（thread_id 幂等 + 同 automation 24h 推送抑制）
    → 追加 ~/.workbuddy/events/events.jsonl（月度归档）
    → 白名单（仅失败事件）经 push_card.py 推飞书卡片
    → 单日 >500 行熔断停写

设计依据（勿删）：
  · TCC：launchd 上下文读外置卷 EPERM，必须用 ~/.workbuddy/binaries 的放行 python
    且子进程继承 —— push_card.py（外置卷）经 PY_BIN 子进程调用，
    先例 = ~/.local/bin/wb-memory-push.py（2026-10-30 实测）。
  · 毫秒口径：automation_runs.created_at 是毫秒（learnings 2026-11-02）。
  · 判活/统计口径：本脚本只读 runs，不读 status 字段做判断。
  · 凭据不入库：本脚本不含任何 webhook/token，推送全部委托 push_card.py。

退出码：0 正常（含无事发生）/ 1 运行出错 / 2 熔断触发
配置：~/.local/etc/wb-event-poller.conf（可选 KEY=VALUE：DB/EVENTS_DIR/MAX_PER_DAY/DRY_RUN）
"""

import fcntl
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

HOME = Path(os.environ.get("HOME", "/Users/guan"))
CONF = HOME / ".local/etc/wb-event-poller.conf"
DEFAULT_DB = HOME / ".workbuddy/workbuddy.db"
EVENTS_DIR = HOME / ".workbuddy/events"
# 日志必须放本地盘：launchd/放行python 均可写；不可放 ~/.workbuddy（软链外置卷，
# launchd 打开 StandardOutPath 会被 TCC 拒 → EX_CONFIG，2026-11-03 实测）
LOG = HOME / "Library/Logs/wb-event-poller.log"
PUSH_CARD = HOME / "WorkBuddy/Claw/.workbuddy/scripts/push_card.py"
PY_BIN = HOME / ".workbuddy/binaries/python/envs/default/bin/python"
WINDOW_MIN = 15  # 扫描窗口（按 updated_at 过滤；5min 轮询 ×3 余量）
MAX_PER_DAY = 500  # 熔断阈值
PUSH_SUPPRESS_H = 24  # 同 automation 推送抑制
LOOKBACK_FAIL_COUNT = 3  # 卡片里附最近同类失败次数
LOG_ROTATE_BYTES = 1_000_000

# 日志路径容器（免 global；main() 按实际 events_dir 重绑）
_STATE = {"log": LOG}


# ── 基础设施 ─────────────────────────────────────────────
def load_conf():
    cfg = {}
    if CONF.exists():
        for raw in CONF.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip()
    return cfg


def log(msg, log_path: Optional[Path] = None):
    """日志跟随实际 events_dir（测试隔离：fixture 日志不写正式 poller.log）"""
    lp = log_path or _STATE["log"]
    lp.parent.mkdir(parents=True, exist_ok=True)
    if lp.exists() and lp.stat().st_size > LOG_ROTATE_BYTES:
        lp.rename(lp.with_suffix(".log.1"))
    with open(lp, "a") as f:
        f.write(f"[{datetime.now():%F %T}] {msg}\n")


# ── 事件文件 ─────────────────────────────────────────────
def _event_month(line: str) -> str:
    """取事件行的月份（YYYY-MM）。必须解析 JSON，不能用字符串匹配 —— json.dumps
    默认输出 `"ts": "..."`（冒号后带空格），匹配 '"ts":"' 会把所有行误判为旧月份
    （2026-11-03 实测：整批误归档 + events.jsonl 被清空）。"""
    try:
        return str(json.loads(line).get("ts", ""))[:7]
    except (json.JSONDecodeError, AttributeError):
        return ""


def month_archive_if_needed(events_file: Path):
    """把非本月的事件行归档到 archive/（按月分文件），本月行保留"""
    if not events_file.exists():
        return
    this_month = datetime.now().strftime("%Y-%m")
    keep, buckets = [], {}
    for line in events_file.read_text().splitlines():
        if not line.strip():
            continue
        m = _event_month(line)
        if m == this_month or not m:
            keep.append(line)
        else:
            buckets.setdefault(m, []).append(line)
    if not buckets:
        return
    arc = events_file.parent / "archive"
    arc.mkdir(exist_ok=True)
    for m, rows in buckets.items():
        out = arc / f"events-{m}.jsonl"
        with open(out, "a") as f:
            f.write("\n".join(rows) + "\n")
        log(f"月度归档：{len(rows)} 行（{m}）→ {out.name}")
    events_file.write_text("\n".join(keep) + ("\n" if keep else ""))


def existing_thread_ids(events_file: Path) -> set:
    if not events_file.exists():
        return set()
    ids = set()
    for line in events_file.read_text().splitlines():
        try:
            if json.loads(line).get("dedupe_key", "").startswith("autofail:"):
                ids.add(json.loads(line)["subject"])
        except (json.JSONDecodeError, KeyError):
            continue  # 损坏行跳过（JSONL 容错；只读文件，无需中断）
    return ids


def last_push_by_automation(events_file: Path) -> dict:
    """automation_id → 最近一次推送 ts（24h 抑制用）"""
    out = {}
    if not events_file.exists():
        return out
    for line in events_file.read_text().splitlines():
        try:
            e = json.loads(line)
            if e.get("pushed"):
                t = e.get("automation_id")
                if t and (t not in out or e["ts"] > out[t]):
                    out[t] = e["ts"]
        except (json.JSONDecodeError, KeyError):
            continue  # 损坏行跳过（JSONL 容错；只读文件，无需中断）
    return out


def count_today(events_file: Path) -> int:
    """当日事件行数（熔断计数）。必须解析 JSON —— json.dumps 输出 `"ts": "` 带空格，
    字符串匹配 '"ts":"' 会恒返 0，熔断永不触发（2026-11-03 实测）。"""
    if not events_file.exists():
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    n = 0
    for ln in events_file.read_text().splitlines():
        if not ln.strip():
            continue
        if str(json.loads(ln).get("ts", "")).startswith(today):
            n += 1
    return n


# ── 事件源（只读） ────────────────────────────────────────
def fetch_failures(db_path: Path):
    """近 WINDOW_MIN 分钟内**收尾**的失败 run（按 updated_at 过滤）。

    ⚠️ 不能按 created_at 过滤：长任务失败时（实测 90 分钟超时，2026-11-03 两条漏报），
    run 结束时 created_at 早已出窗 —— 按创建时刻过滤会系统性漏掉所有长任务失败。
    updated_at = run 收尾时刻，失败结论（result_success=0）落库于同一时刻。
    毫秒口径（learnings 2026-11-02）。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        # cutoff 在 python 侧计算（毫秒口径），SQL 全参数化 —— 消 S608
        cutoff_ms = int((time.time() - WINDOW_MIN * 60) * 1000)
        rows = con.execute(
            """
            select r.thread_id, r.automation_id, coalesce(a.name,'(未知)'),
                   coalesce(r.failure_code,''), coalesce(r.reason_code,''),
                   datetime(r.updated_at/1000,'unixepoch','localtime')
            from automation_runs r left join automations a on a.id = r.automation_id
            where r.result_success = 0
              and r.updated_at > ?
            order by r.updated_at
        """,
            (cutoff_ms,),
        ).fetchall()
    finally:
        con.close()
    return rows


def count_recent_same_failures(db_path: Path, automation_id: str, hours: int = 72) -> int:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cutoff_ms = int((time.time() - hours * 3600) * 1000)
        n = con.execute(
            """
            select count(*) from automation_runs
            where result_success=0 and automation_id=?
              and created_at > ?
        """,
            (automation_id, cutoff_ms),
        ).fetchone()[0]
    finally:
        con.close()
    return n


# ── 推送（委托 push_card，经放行 python） ─────────────────
def push_card(title: str, body: str, dedupe_key: str, dry: bool) -> bool:
    if dry:
        log(f"[DRY-RUN] 待推送: {title} | key={dedupe_key}")
        return True
    if not (PY_BIN.exists() and PUSH_CARD.exists()):
        log(f"推送通路不可用（PY_BIN={PY_BIN.exists()} push_card={PUSH_CARD.exists()}）→ 仅落盘")
        return False
    import subprocess

    cmd = [
        str(PY_BIN),
        str(PUSH_CARD),
        "--title",
        title,
        "--level",
        "alert",
        "--section",
        "失败详情",  # 不能传空串：push_card 的 --section 是 nargs=2(TITLE BODY)，
        # 空 TITLE 会被占位符防护拒绝 → rc=1（2026-11-03 实测，当时 8 条失败全未推出）
        body,
        "--dedupe-key",
        dedupe_key,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            # push_card 的重试/兜底诊断全部走 stdout（其 main 用 print），
            # 只记 stderr 会得到空串 → 2026-11-04 审计实测：launchd 缺 PATH
            # 报 "env: node: No such file or directory" 被静默吞掉 1 天。
            detail = (r.stdout or r.stderr or "").strip()[-300:]
            log(f"push_card rc={r.returncode} out={detail}")
        return r.returncode == 0
    except Exception as e:
        log(f"push_card 异常: {e}")
        return False


# ── 主流程 ───────────────────────────────────────────────
def main():
    cfg = load_conf()
    # 测试钩子：环境变量优先（fixture 验证用，不污染真库/真事件文件）
    db_path = Path(os.environ.get("WB_EVENT_DB") or cfg.get("DB", DEFAULT_DB))
    events_dir = Path(os.environ.get("WB_EVENT_DIR") or cfg.get("EVENTS_DIR", EVENTS_DIR))
    _STATE["log"] = events_dir / "poller.log"
    max_per_day = int(os.environ.get("WB_EVENT_MAX") or cfg.get("MAX_PER_DAY", MAX_PER_DAY))
    dry = cfg.get("DRY_RUN", "0") == "1" or "--dry-run" in sys.argv
    events_file = events_dir / "events.jsonl"

    events_dir.mkdir(parents=True, exist_ok=True)
    # 进程级互斥锁：fd 由本进程退出时释放（单次短运行，无泄漏窗口）
    lock_fd = os.open(events_dir / ".poller.lock", os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        log("上一轮未结束 → 跳过本轮")
        return 0
    # 熔断标记期（24h）直接退出
    circuit = events_dir / ".circuit_open"
    if circuit.exists():
        ts = datetime.fromtimestamp(circuit.stat().st_mtime)
        if datetime.now() - ts < timedelta(hours=24):
            log("熔断期内 → 跳过")
            return 2
        circuit.unlink()

    month_archive_if_needed(events_file)
    if not db_path.exists():
        log(f"DB 不存在：{db_path} → 退出")
        return 1

    rows = fetch_failures(db_path)
    if not rows:
        return 0  # 无事发生，不写日志（静默，同 wb-heartbeat 惯例）

    seen = existing_thread_ids(events_file)
    last_push = last_push_by_automation(events_file)
    today_cnt = count_today(events_file)
    now_s = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    new_lines, pushed = [], 0
    circuit_hit = False

    for thread_id, automation_id, name, fcode, rcode, created in rows:
        if thread_id in seen or f"autofail:{thread_id}" in str(seen):
            continue
        if today_cnt + len(new_lines) >= max_per_day:
            circuit_hit = True
            break
        key = f"autofail:{thread_id}"
        prev = last_push.get(automation_id)
        suppress = False
        if prev:
            prev_dt = datetime.fromisoformat(prev)
            now_dt = datetime.now(prev_dt.tzinfo) if prev_dt.tzinfo else datetime.now()
            suppress = (now_dt - prev_dt).total_seconds() < PUSH_SUPPRESS_H * 3600
        same_n = count_recent_same_failures(db_path, automation_id)
        ev = {
            "ts": now_s,
            "source": "automation_runs",
            "type": "run.failed",
            "subject": thread_id,
            "automation_id": automation_id,
            "automation_name": name,
            "failure_code": fcode or "(空)",
            "reason_code": rcode or "",
            "recent_72h_same": same_n,
            "dedupe_key": key,
            "handled_by": None,
            "pushed": False,
        }
        if not suppress:
            ok = push_card(
                f"🔴 自动化失败：{name}",
                f"**failure_code**: `{ev['failure_code']}`\n"
                f"**run**: {created}\n**近72h同类**: {same_n} 次\n"
                f"thread: `{thread_id[:40]}`",
                key,
                dry,
            )
            ev["pushed"] = ok
            pushed += 1 if ok else 0
        # 同步内存索引：同轮内后继事件也要受 24h 抑制（V2b 实测踩点）
        if ev["pushed"]:
            last_push[automation_id] = ev["ts"]
        new_lines.append(json.dumps(ev, ensure_ascii=False))

    if new_lines:
        with open(events_file, "a") as f:
            f.write("\n".join(new_lines) + "\n")
        log(f"落盘 {len(new_lines)} 条失败事件，推送 {pushed} 条（dry={dry}）")

    if circuit_hit:
        circuit.write_text(datetime.now().isoformat())
        log(f"单日达 {max_per_day} 行 → 熔断 24h")
        push_card(
            "🔴 事件轮询器熔断",
            f"单日事件数达 {max_per_day}，已停写 24h。"
            "可能为平台级故障，请人工核查 automation_runs。",
            "event-circuit",
            dry,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
