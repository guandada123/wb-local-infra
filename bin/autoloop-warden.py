#!/usr/bin/env python3
"""中台看护 warden：非终态对账 / 出活看护 / 运行中空转 / 全局开关。

借鉴《从 Agent Team 到常驻 SuperAgent》（Ooder 架构组 2026-11-04）第 5.4「启动状态机 + 只读恢复」
与 5.5「Watchdog + 三档回滚」，只补本机实测缺失的三处（证据见 docs/superagent-gap-map.md）：

  reconcile  内核把超租约的 claimed 改成 unknown 后无人收口（kernel/decide.ts:283-288），
             而 CLI stop 只认 claimed（decide.ts:827）——unknown 是黑洞。
  progress   运行中只有 RUN_LEASE=5min 心跳与 180 分钟超时，没有「还有没有实质进展」的判据。
  pause-all  没有全局开关；停中台只能 launchctl bootout，会连 worker 一起停（detached agent 还在跑）。

与文章同口径的刻意不做：
  - 不写 hub.db：真源是 facts 追加日志 + 单写者事务（kernel/store.ts:32-42），直写会撕裂投影。
    收敛动作只走官方 CLI（stop / pause），状态机仍由内核改。
  - 不重派：对账只收敛不补跑，从根上避免重启风暴。
  - 不杀进程：progress 只诊断，处置留给人。

用法：
    autoloop-warden.py status [--json]          全景：非终态轮次 / 定时是否还在推进 / 暂停态 / 最后落笔
    autoloop-warden.py reconcile [--apply]      非终态对账，死轮收敛（默认只报不动）
    autoloop-warden.py progress [--apply]       在跑轮次是否空转（默认只报不动；--apply 只写诊断文件）
    autoloop-warden.py pause-all [--apply]      全局暂停所有规则（三档回滚的第一档）
    autoloop-warden.py resume-all [--apply]     只恢复被本工具暂停的规则
    autoloop-warden.py --self-test              用伪造 fixture 反证上述判据

退出码：0 健康 / 1 有确定性问题 / 3 判不了（有 doubt，且无确定性问题）
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(os.environ.get("AL_HOME") or (Path.home() / ".agent-autoloop"))
HUB_DB = Path(os.environ.get("AL_HUB_DB") or (HOME / "hub.db"))
RUNS = Path(os.environ.get("AL_RUNS") or (HOME / "worker" / "runs"))
RULES = Path(os.environ.get("AL_RULES") or (HOME / "rules.json"))
STATE = Path(os.environ.get("AL_STATE") or (HOME / "warden-state.json"))
CLI = os.environ.get("AL_CLI") or (shutil.which("agent-autoloop") or "agent-autoloop")
PS = os.environ.get("AL_PS") or "/bin/ps"

OPEN_STATES = ("queued", "claimed", "unknown")
# 与 worker/worker.ts:120 同一形态：agent-autoloop-run:<run>:<attempt>:<turn>
MARKER = "agent-autoloop-run:{run}:"
SCHEDULE_LAG = timedelta(minutes=30)  # next_at 落在过去这么久 = tick 没推进
QUEUED_STALE = timedelta(hours=6)  # 排队这么久没人接 = worker 没连上


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def ago(dt):
    if dt is None:
        return "未知"
    delta = now_utc() - dt
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return f"{mins} 分钟前"
    if mins < 1440:
        return f"{mins // 60} 小时前"
    return f"{mins // 1440} 天前"


# ---------- 证据读取（只读） ----------


def open_db():
    """只读打开 hub.db。真源是 facts 日志，看护只读不写。"""
    con = sqlite3.connect(f"file:{HUB_DB}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def load_open_runs(con):
    marks = ",".join("?" * len(OPEN_STATES))
    rows = con.execute(
        "select id, rule, state, attempts, created_at, claimed_at, seen_at, cancel_at,"
        f" substr(coalesce(error, ''), 1, 120) as error from runs where state in ({marks}) order by id",
        OPEN_STATES,
    ).fetchall()
    return [dict(r) for r in rows]


def load_schedules(con):
    try:
        rows = con.execute("select rule, next_at, skipped_at from schedules").fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def load_pauses(con):
    try:
        rows = con.execute("select name, reason from pauses").fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def find_entry(run_id):
    """worker/runs/<run>-<attempt>/entry.json；取了 attempt 最大的那个。"""
    best = None
    for path in sorted(RUNS.glob(f"{run_id}-*")):
        entry = path / "entry.json"
        if entry.is_file():
            best = entry
    if not best:
        return None
    try:
        data = json.loads(best.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    data["_dir"] = str(best.parent)
    return data


def probe_ps(args):
    """跑一次 ps。返回 (状态, 输出)：状态 ok / gone / unknown（与前两轮语义严格区分）。"""
    try:
        done = subprocess.run([PS, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown", ""
    if done.returncode == 1 and not done.stdout.strip():
        return "gone", ""
    if done.returncode != 0:
        return "unknown", ""
    return "ok", done.stdout


def process_alive(pid, run_id):
    """True 活 / False 死 / None 看不到。判据照抄 worker/worker.ts:122-135。"""
    if not pid:
        return False
    status, out = probe_ps(["-ww", "-o", "command=", "-p", str(pid)])
    if status == "gone":
        return False
    if status == "unknown":
        return None
    return MARKER.format(run=run_id) in out


def group_alive(pgid):
    """进程组还有没有活人（僵尸不算）。判据照抄 worker/worker.ts:143-166。"""
    if not pgid:
        return False
    status, out = probe_ps(["-ax", "-o", "pgid=", "-o", "stat="])
    if status != "ok":
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[0].isdigit() and int(parts[0]) == int(pgid) and not parts[1].startswith("Z"):
            return True
    return False


def scan_marker(run_id):
    """没有 entry.json 时，全表扫一遍标记，确认进程是不是真的没了。"""
    status, out = probe_ps(["-axww", "-o", "command="])
    if status != "ok":
        return None
    return MARKER.format(run=run_id) in out


def cpu_seconds(pid):
    if not pid:
        return None
    status, out = probe_ps(["-o", "time=", "-p", str(pid)])
    if status != "ok":
        return None
    text = out.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        head, text = text.split("-", 1)
        days = int(head)
    chunks = text.split(":")
    try:
        nums = [float(c) for c in chunks]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.insert(0, 0.0)
    return days * 86400 + nums[0] * 3600 + nums[1] * 60 + nums[2]


def classify(run):
    """给一条非终态轮次定性：alive / dead / doubt / queued / queued-stale。"""
    run_id = run["id"]
    entry = find_entry(run_id)
    result = {"id": run_id, "rule": run["rule"], "state": run["state"], "entry": bool(entry)}

    if run["state"] == "queued":
        created = parse_iso(run.get("created_at"))
        stale = bool(created and now_utc() - created > QUEUED_STALE)
        result["verdict"] = "queued-stale" if stale else "queued"
        result["why"] = (
            f"排队超过 {QUEUED_STALE.total_seconds() / 3600:.0f} 小时无人接单（worker 没连上？）"
            if stale
            else "已入队，等 worker 接单"
        )
        return result

    if entry:
        pid = entry.get("pid")
        alive = process_alive(pid, run_id)
        group = group_alive(pid)
        result["pid"] = pid
        if alive is None and group is None:
            result["verdict"] = "doubt"
            result["why"] = "ps 看不到（权限/沙箱），不敢判死"
        elif alive or group:
            result["verdict"] = "alive"
            result["why"] = f"进程 {pid} 还带着标记在跑"
        else:
            result["verdict"] = "dead"
            result["why"] = f"entry.json 指向 pid {pid}，进程与进程组都没了"
        return result

    seen = scan_marker(run_id)
    if seen is None:
        result["verdict"] = "doubt"
        result["why"] = "没有 entry.json，且 ps 不可用，判不了"
    elif seen:
        result["verdict"] = "alive"
        result["why"] = "没有 entry.json，但进程还带着标记在跑"
    else:
        result["verdict"] = "dead"
        result["why"] = "没有 entry.json，进程表里也找不到标记"
    return result


# ---------- 写动作（只走官方 CLI） ----------


def run_cli(args, apply=True):
    if not apply:
        return 0, f"DRY-RUN: {CLI} {' '.join(args)}"
    try:
        done = subprocess.run([CLI, *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        return 1, f"调用失败：{error}"
    text = (done.stdout or done.stderr or "").strip().splitlines()
    return done.returncode, text[-1] if text else ""


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


# ---------- 子命令 ----------


def cmd_reconcile(args):
    con = open_db()
    runs = load_open_runs(con)
    con.close()
    findings = [classify(r) for r in runs]

    if not findings:
        print("非终态轮次：0 条。中台没有卡在半路的活。")
        return 0

    actions, exit_code = [], 0
    print(f"非终态轮次：{len(findings)} 条")
    for item in findings:
        print(f"  #{item['id']}「{item['rule']}」state={item['state']} → {item['verdict']}")
        print(f"      {item['why']}")
        if item["verdict"] == "dead" and item["state"] == "claimed":
            code, text = run_cli(["stop", str(item["id"])], apply=args.apply)
            actions.append({"id": item["id"], "action": "stop", "rc": code, "out": text})
            print(f"      {'已请求停止' if args.apply else '建议'}：{text}")
            if code != 0:
                exit_code = 1
        elif item["verdict"] == "dead" and item["state"] == "unknown":
            exit_code = 1
            print("      ⚠️ unknown 无收敛通道：CLI stop 只认 claimed（decide.ts:827），")
            print("         这条要等内核补 reconcile 或人工判定；本工具不动它（见 docs/superagent-gap-map.md）。")
        elif item["verdict"] == "queued-stale":
            exit_code = 1
        elif item["verdict"] in ("doubt", "unknown"):
            exit_code = exit_code or 3

    if args.apply and actions:
        print(f"\n已执行 {len(actions)} 个动作（官方 CLI，未直写 hub.db）")
    print(f"\n结论：{sum(1 for f in findings if f['verdict'] == 'dead')} 条死轮 / "
          f"{sum(1 for f in findings if f['verdict'] == 'alive')} 条在跑 / "
          f"{sum(1 for f in findings if f['verdict'] == 'doubt')} 条判不了")
    if args.json:
        print(json.dumps({"findings": findings, "actions": actions}, ensure_ascii=False, indent=1))
    return exit_code


def cmd_progress(args):
    con = open_db()
    runs = [r for r in load_open_runs(con) if r["state"] in ("claimed", "unknown")]
    con.close()

    state = load_state()
    samples = state.setdefault("progress", {})
    idle_limit = timedelta(minutes=args.idle_minutes)
    flagged, notes = [], []

    for run in runs:
        run_id = str(run["id"])
        entry = find_entry(run["id"])
        if not entry:
            notes.append(f"#{run_id} 没有 entry.json，跳过（交 reconcile 处理）")
            continue
        turn = entry.get("turn", 0)
        folder = Path(entry.get("_dir") or "")
        sizes = {}
        for name in ("stdout", "stderr"):
            path = folder / f"{name}-{turn}.log"
            sizes[name] = path.stat().st_size if path.is_file() else None
        if sizes["stdout"] is None and sizes["stderr"] is None:
            notes.append(f"#{run_id} 连日志都没落，交 reconcile 处理")
            continue
        signature = {
            "at": iso(now_utc()),
            "bytes": sum(v or 0 for v in sizes.values()),
            "cpu": cpu_seconds(entry.get("pid")),
            "exit": (folder / f"exit-{turn}").is_file(),
        }
        previous = samples.get(run_id)
        samples[run_id] = signature
        if not previous:
            notes.append(f"#{run_id} 首次采样已记基线（{signature['bytes']}B / CPU {signature['cpu']}s）")
            continue
        elapsed = now_utc() - (parse_iso(previous.get("at")) or now_utc())
        moved = []
        if signature["bytes"] != previous.get("bytes"):
            moved.append(f"日志 {previous.get('bytes')}→{signature['bytes']}B")
        if signature["cpu"] != previous.get("cpu"):
            moved.append(f"CPU {previous.get('cpu')}→{signature['cpu']}s")
        if signature["exit"] and not previous.get("exit"):
            moved.append("已落 exit 文件（在收尾）")
        if moved:
            notes.append(f"#{run_id} 有进展：" + "，".join(moved))
        elif elapsed >= idle_limit:
            flagged.append(
                {
                    "id": run["id"],
                    "rule": run["rule"],
                    "idle_minutes": int(elapsed.total_seconds() // 60),
                    "bytes": signature["bytes"],
                    "cpu": signature["cpu"],
                }
            )
        else:
            notes.append(f"#{run_id} 静默 {int(elapsed.total_seconds() // 60)} 分钟，未到阈值")

    stale = [k for k in samples if k not in {str(r["id"]) for r in runs}]
    for key in stale:
        samples.pop(key, None)
    save_state(state)

    for note in notes:
        print(f"  · {note}")
    if not runs:
        print("在跑轮次：0 条，没有对象需要看护。")
        return 0
    if flagged:
        print(f"\n疑似空转 {len(flagged)} 条（四信号 {args.idle_minutes} 分钟内零增长）：")
        for item in flagged:
            print(f"  🔴 #{item['id']}「{item['rule']}」静默 {item['idle_minutes']} 分钟，"
                  f"日志 {item['bytes']}B，CPU {item['cpu']}s")
            print("      下一步：看 worker/runs 里该轮 stderr 末 20 行；执行体可能卡在等模型或等工具返回。")
        if args.json:
            print(json.dumps({"flagged": flagged, "notes": notes}, ensure_ascii=False, indent=1))
        return 1
    print("\n结论：在跑的轮次都有进展（或未到阈值），未发现空转。")
    if args.json:
        print(json.dumps({"flagged": [], "notes": notes}, ensure_ascii=False, indent=1))
    return 0


def cmd_status(args):
    con = open_db()
    runs = load_open_runs(con)
    schedules = load_schedules(con)
    pauses = load_pauses(con)
    con.close()

    findings = [classify(r) for r in runs] if runs else []
    lags = []
    for item in schedules:
        at = parse_iso(item.get("next_at"))
        if at and now_utc() - at > SCHEDULE_LAG:
            lags.append({"rule": item["rule"], "next_at": item["next_at"],
                         "late": str(now_utc() - at).split(".")[0]})
        elif at is None:
            lags.append({"rule": item["rule"], "next_at": item.get("next_at"), "late": "无法解析"})

    marks = [p for p in (HUB_DB, HUB_DB.with_name(HUB_DB.name + "-wal")) if p.exists()]
    last_write = max((datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) for p in marks),
                     default=None)

    print(f"中台库：{HUB_DB}")
    print(f"最后落笔：{ago(last_write)}（{iso(last_write) if last_write else '未知'}）")
    print(f"定时推进：{'正常' if not lags else f'{len(lags)} 条滞后'}")
    for lag in lags:
        print(f"  🔴「{lag['rule']}」next_at={lag['next_at']}，已逾期 {lag['late']}")
        print("      next_at 落在过去 = 内核 tick 没在推进（hub 进程活着也不代表在出活）。")
    print(f"暂停规则：{len(pauses)} 条" + ("：" + "、".join(p["name"] for p in pauses) if pauses else ""))
    print(f"非终态轮次：{len(findings)} 条")
    for item in findings:
        print(f"  #{item['id']}「{item['rule']}」{item['state']} → {item['verdict']}（{item['why']}）")

    healthy = not lags and all(f["verdict"] in ("alive", "queued") for f in findings)
    print("\n结论：" + ("健康" if healthy else "有需要看的项"))
    if args.json:
        print(json.dumps(
            {"last_write": iso(last_write) if last_write else None, "schedules": lags,
             "pauses": pauses, "runs": findings, "healthy": healthy},
            ensure_ascii=False, indent=1))
    if lags:
        return 1
    return 0 if healthy else (3 if any(f["verdict"] == "doubt" for f in findings) else 1)


def rule_names():
    try:
        data = json.loads(RULES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r.get("name") for r in data.get("rules", []) if r.get("name")]


def cmd_pause_all(args):
    names = rule_names()
    if not names:
        print(f"读不到规则列表：{RULES}")
        return 1
    state = load_state()
    paused = state.setdefault("paused_by_warden", [])
    print(f"全局暂停 {len(names)} 条规则" + ("（预演，不改状态）" if not args.apply else ""))
    exit_code = 0
    for name in names:
        code, text = run_cli(["pause", name, "--reason", args.reason], apply=args.apply)
        print(f"  {'✅' if code == 0 else '🔴'} {name}：{text}")
        if code == 0 and args.apply and name not in paused:
            paused.append(name)
        if code != 0:
            exit_code = 1
    if args.apply:
        save_state(state)
        print(f"\n已记 {len(paused)} 条由本工具暂停；恢复用 resume-all（只恢复这些，不动你手动暂停的）。")
    return exit_code


def cmd_resume_all(args):
    state = load_state()
    paused = state.get("paused_by_warden", [])
    if not paused:
        print("没有本工具暂停过的规则。别人手动暂停的请用 agent-autoloop resume <规则> 逐条恢复。")
        return 0
    print(f"恢复 {len(paused)} 条规则" + ("（预演）" if not args.apply else ""))
    exit_code, done = 0, []
    for name in list(paused):
        code, text = run_cli(["resume", name], apply=args.apply)
        print(f"  {'✅' if code == 0 else '🔴'} {name}：{text}")
        if code == 0 and args.apply:
            done.append(name)
        if code != 0:
            exit_code = 1
    if args.apply:
        state["paused_by_warden"] = [n for n in paused if n not in done]
        save_state(state)
    return exit_code


# ---------- 自检：判据必须被反例打过 ----------


def self_test():
    global HUB_DB, RUNS, RULES, STATE, CLI, PS

    checks = []

    def check(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    with tempfile.TemporaryDirectory() as raw:
        td = Path(raw)
        HUB_DB = td / "hub.db"
        RUNS = td / "runs"
        RULES = td / "rules.json"
        STATE = td / "state.json"
        RUNS.mkdir()
        log = td / "cli.log"
        RULES.write_text(json.dumps({"rules": [{"name": "甲"}, {"name": "乙"}]}), encoding="utf-8")

        fake_cli = td / "fake-cli.py"
        fake_cli.write_text(
            "import os, sys\n"
            f"open({str(log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n",
            encoding="utf-8")
        wrapper = td / "agent-autoloop"
        wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {fake_cli} \"$@\"\n", encoding="utf-8")
        wrapper.chmod(0o755)
        CLI = str(wrapper)

        con = sqlite3.connect(HUB_DB)
        con.executescript(
            "create table runs(id integer, rule text, agent text, grp text, state text,"
            " attempts integer, created_at text, claimed_at text, seen_at text, cancel_at text,"
            " last_result text, summary text, error text);"
            "create table schedules(rule text, cron text, next_at text, skipped_at text);"
            "create table pauses(name text, reason text);"
        )
        old = iso(now_utc() - timedelta(minutes=40))
        rows = [
            (1, "甲", "claimed", iso(now_utc())),
            (2, "甲", "claimed", iso(now_utc())),
            (3, "乙", "claimed", iso(now_utc())),
            (4, "乙", "unknown", iso(now_utc())),
            (5, "甲", "queued", iso(now_utc() - timedelta(hours=9))),
        ]
        for rid, rule, state, created in rows:
            con.execute(
                "insert into runs(id, rule, agent, grp, state, attempts, created_at, claimed_at)"
                " values(?,?,'agent',?,?,0,?,?)", (rid, rule, rule, state, created, created))
        con.execute("insert into schedules(rule, cron, next_at) values('甲','0 9 * * *',?)",
                    (iso(now_utc() - timedelta(hours=3)),))
        con.execute("insert into schedules(rule, cron, next_at) values('乙','0 9 * * *',?)",
                    (iso(now_utc() + timedelta(hours=3)),))
        con.commit()
        con.close()

        # 1 号：真起一个带标记的进程（反例：活进程绝不能被判死）
        live = subprocess.Popen(["/bin/bash", "-c", "sleep 30", "agent-autoloop-run:1:1:0"],
                                start_new_session=True)
        for rid, attempt, pid in ((1, 1, live.pid), (2, 1, 999999), (3, 1, 999999)):
            folder = RUNS / f"{rid}-{attempt}"
            folder.mkdir()
            (folder / "entry.json").write_text(json.dumps(
                {"run": rid, "attempt": attempt, "turn": 0, "pid": pid, "dir": str(folder)}),
                encoding="utf-8")
            (folder / "stdout-0.log").write_text("start\n", encoding="utf-8")
        for rid in (4, 5):
            (RUNS / f"{rid}-1").mkdir()
        (RUNS / "4-1" / "entry.json").write_text(
            json.dumps({"run": 4, "attempt": 1, "turn": 0, "pid": 999999}), encoding="utf-8")

        try:
            con = open_db()
            verdicts = {f["id"]: f["verdict"] for f in (classify(r) for r in load_open_runs(con))}
            con.close()
            check("活进程不被判死", verdicts.get(1) == "alive", f"实际 {verdicts.get(1)}")
            check("死轮被判死", verdicts.get(2) == "dead", f"实际 {verdicts.get(2)}")
            check("无 entry 且无进程判死", verdicts.get(3) == "dead", f"实际 {verdicts.get(3)}")
            check("unknown 单列不误判", verdicts.get(4) == "dead", f"实际 {verdicts.get(4)}")
            check("排队超时被标出来", verdicts.get(5) == "queued-stale", f"实际 {verdicts.get(5)}")

            # ps 不可用 → doubt，不是死
            PS = str(td / "no-such-ps")
            con = open_db()
            doubt = {f["id"]: f["verdict"] for f in (classify(r) for r in load_open_runs(con))}
            con.close()
            check("ps 不可用判 doubt 不判死", doubt.get(2) == "doubt", f"实际 {doubt.get(2)}")
            PS = "/bin/ps"

            # 预演不落动作
            exit_code = cmd_reconcile(argparse.Namespace(apply=False, json=False))
            check("对账预演不调 CLI", not log.exists() or log.read_text() == "", "有 CLI 调用")
            check("未 apply 时退出码非 0", exit_code == 1, f"rc={exit_code}")

            # apply：只 stop 死掉的 claimed，不碰 alive / unknown / queued
            cmd_reconcile(argparse.Namespace(apply=True, json=False))
            calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
            check("apply 只对死轮发 stop（活轮与 unknown 不动）", calls == ["stop 2", "stop 3"],
                  f"实际 {calls}")

            # 定时滞后能被发现
            exit_code = cmd_status(argparse.Namespace(json=False))
            check("tick 不推进被发现", exit_code == 1, f"rc={exit_code}")

            # 全局暂停：预演不发命令；apply 两条规则各一条
            log.write_text("", encoding="utf-8")
            cmd_pause_all(argparse.Namespace(apply=False, reason="自检"))
            check("暂停预演不落动作", log.read_text(encoding="utf-8") == "", "有 CLI 调用")
            cmd_pause_all(argparse.Namespace(apply=True, reason="自检"))
            calls = log.read_text(encoding="utf-8").splitlines()
            check("暂停 apply 一规则一条", len(calls) == 2 and all(c.startswith("pause ") for c in calls),
                  f"实际 {calls}")
            log.write_text("", encoding="utf-8")
            cmd_resume_all(argparse.Namespace(apply=True))
            calls = log.read_text(encoding="utf-8").splitlines()
            check("恢复只恢复本工具暂停的", len(calls) == 2 and all(c.startswith("resume ") for c in calls),
                  f"实际 {calls}")

            # 空转判定：首次只记基线，第二次零增长才报
            con = sqlite3.connect(HUB_DB)
            con.execute("update runs set state='done' where id in (2,3,4,5)")
            con.commit()
            con.close()
            exit_code = cmd_progress(argparse.Namespace(idle_minutes=0, apply=False, json=False))
            check("首采只记基线不报警", exit_code == 0, f"rc={exit_code}")
            exit_code = cmd_progress(argparse.Namespace(idle_minutes=0, apply=False, json=False))
            check("零增长判空转", exit_code == 1, f"rc={exit_code}")
            (RUNS / "1-1" / "stdout-0.log").write_text("start\nmore\n", encoding="utf-8")
            exit_code = cmd_progress(argparse.Namespace(idle_minutes=0, apply=False, json=False))
            check("日志增长即算有进展", exit_code == 0, f"rc={exit_code}")
        finally:
            live.terminate()
            live.wait(timeout=5)

    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  {'✅' if ok else '🔴'} {name}" + ("" if ok else f"—— {detail}"))
    print(f"\n自检：{len(checks) - len(failed)}/{len(checks)} 通过")
    return 0 if not failed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="中台看护：非终态对账 / 出活看护 / 空转判定 / 全局开关")
    sub = parser.add_subparsers(dest="cmd")
    p_status = sub.add_parser("status", help="全景")
    p_status.add_argument("--json", action="store_true")
    p_reconcile = sub.add_parser("reconcile", help="非终态对账")
    p_reconcile.add_argument("--apply", action="store_true", help="真的发 stop（默认只报）")
    p_reconcile.add_argument("--json", action="store_true")
    p_progress = sub.add_parser("progress", help="在跑轮次空转判定")
    p_progress.add_argument("--idle-minutes", type=int, default=8)
    p_progress.add_argument("--apply", action="store_true", help="保留参数，当前只诊断不处置")
    p_progress.add_argument("--json", action="store_true")
    p_pause = sub.add_parser("pause-all", help="全局暂停所有规则")
    p_pause.add_argument("--apply", action="store_true")
    p_pause.add_argument("--reason", default="warden 全局暂停")
    p_resume = sub.add_parser("resume-all", help="恢复本工具暂停的规则")
    p_resume.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true", help="用伪造 fixture 反证判据")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.cmd:
        parser.print_help()
        return 2
    return {"status": cmd_status, "reconcile": cmd_reconcile, "progress": cmd_progress,
            "pause-all": cmd_pause_all, "resume-all": cmd_resume_all}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
