#!/Users/guan/.workbuddy/binaries/python/envs/default/bin/python3
"""
wb-job-watch.py — launchd job 单点存活监控（router v0 扩展 #6）
2026-11-10 用户「全开」授权实施；方案候选见台账 §九（11-05）、判据见扩展实施总纲 §三。

职责（只观察，不处置）：
  每 30 分钟检查白名单 launchd job：
    ① 未加载   — launchctl print 失败（被 bootout / plist 损坏）
    ② 非零退出 — last exit code != 0
    ③ runs 停滞 — 超 stall 窗口×2 仍 Δ=0（连续两窗，压睡眠/瞬时跳轮误报）
    ④ 流日志非空 — StandardOut/ErrorPath 文件 size>0（正常态全 0；
       崩溃 traceback 会写入，如 wb-event-poller 的 EX_CONFIG 就是它暴露的）
  告警经 push_card.py（放行 python 子进程，先例=wb-event-poller.py）。

设计依据（勿删）：
  · TCC：必须用 ~/.workbuddy/binaries 放行 python，子进程继承授权。
  · 睡眠：机器睡眠时本 job 与被监控 job 同停，唤醒后 Δ=0 是停摆信号；
    误报由「连续两窗」压制；真实失联另有 wb-heartbeat→healthchecks.io 外部告警兜底。
  · 状态文件放 ~/.workbuddy/events/（与事件基础设施同目录）；SSD 掉线时状态不可用
    → 跳过停滞检测与 size 比对，硬检查（①②）照跑。
  · 凭据不入库：本脚本不含 webhook/token，推送全部委托 push_card.py。
  · watch job 自身不被监控（自举悖论）：其失联由外部心跳与巡检兜底，记录为已知边界。

退出码：0 正常（含已告警）/ 1 内部异常 / 2 依赖缺失
配置：~/.local/etc/wb-job-watch.conf（可选 KEY=VALUE：DRY_RUN=1、ONLY_JOBS=白名单子集、
      ADD_JOBS=name:interval,name:interval 注入额外监控对象——受控故障验证用，
      如 ADD_JOBS=com.user.fake:600，检查到未加载即真实推卡，验证告警端到端）
"""

import json
import os
import plistlib
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path(os.environ.get("HOME", "/Users/guan"))
CONF = HOME / ".local/etc/wb-job-watch.conf"
STATE = HOME / ".workbuddy/events/job-watch-state.json"
LAUNCH_AGENTS = HOME / "Library/LaunchAgents"
LOGS_DIR = HOME / "Library/Logs"
PUSH_CARD = HOME / "WorkBuddy/Claw/.workbuddy/scripts/push_card.py"
PY_BIN = HOME / ".workbuddy/binaries/python/envs/default/bin/python"
UID = os.getuid()

# 白名单：job → 预期 StartInterval 秒（与各 plist 实际值一致，2026-11-10 plutil 实测）
JOBS = {
    "com.user.wb-event-poller": 300,
    "com.user.wb-heartbeat": 600,
    "com.user.wb-failures": 3600,
    "com.user.wb-liveness": 7200,
}
ALERT_TTL_H = 24  # 同 key 告警抑制
TAIL_BYTES = 200  # 流日志告警附尾部字节数
WATCH_INTERVAL_S = 1800  # 本 job 调度间隔（plist StartInterval，供停滞窗口参考）


def load_conf():
    cfg = {}
    if CONF.exists():
        for raw in CONF.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip()
    return cfg


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"jobs": {}, "logs": {}, "alerts": {}}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1))
    tmp.rename(STATE)


# ── 检查逻辑（纯函数，fixture 可测） ─────────────────────
def check_load_and_exit(print_output: str, job: str):
    """①未加载 ②非零退出。print_output 为 launchctl print stdout，加载失败传 None。"""
    issues = []
    if print_output is None:
        issues.append(("not-loaded", "launchctl print 失败：job 未加载或 plist 不可读"))
        return issues
    m = re.search(r"last exit code = (-?\d+)", print_output)
    if not m:
        issues.append(("unparseable", "launchctl print 输出中无 last exit code 字段"))
    elif int(m.group(1)) != 0:
        issues.append(("exit", f"last exit code = {m.group(1)}（应为 0）"))
    return issues


def check_stall(job: str, interval_s: int, runs: int, prev: dict, now_s: float):
    """③runs 停滞。返回 (issues, new_entry)。
    stall 窗口 = max(interval×2.5, 30min)；连续两窗（×2）才告警。
    prev=None（首见）只建档不告警。"""
    stall = max(interval_s * 2.5, WATCH_INTERVAL_S)
    if runs > prev["runs"]:
        return [], {"runs": runs, "ts": now_s}
    stalled_s = now_s - prev["ts"]
    if stalled_s >= stall * 2:
        return (
            [
                (
                    "stall",
                    f"runs {prev['runs']}→{runs} 停滞 {stalled_s / 3600:.1f}h（阈值 {stall * 2 / 3600:.1f}h）",
                )
            ],
            {"runs": runs, "ts": now_s},
        )  # 告警后刷新 ts，同次停滞期只提醒一次
    return [], prev


def check_log(log_path: Path, prev_entry):
    """④流日志非空。返回 (issues, new_entry)。size 与上次相同→不重复告警。"""
    size = log_path.stat().st_size if log_path.exists() else 0
    if size == 0:
        return [], None if prev_entry is None else {"size": 0}
    if prev_entry and prev_entry.get("size") == size:
        return [], prev_entry  # 同 size：上次已告警，不重复
    try:
        tail = log_path.read_text(errors="replace")[-TAIL_BYTES:]
    except OSError as e:
        tail = f"(读取失败: {e})"
    return [("log-nonempty", f"{log_path.name} 非空（{size}B）\n尾部: {tail}")], {"size": size}


def stream_log_paths(job: str):
    """从 plist 读 StandardOut/ErrorPath（通用，不硬编码文件名）"""
    paths = []
    try:
        pl = plistlib.loads((LAUNCH_AGENTS / f"{job}.plist").read_bytes())
        for k in ("StandardOutPath", "StandardErrorPath"):
            v = pl.get(k)
            if v:
                paths.append(Path(v))
    except Exception as e:  # plist 损坏/缺失：不阻断主流程，仅提示（判据降级为无流日志检查）
        print(f"stream_log_paths: {job}.plist 解析失败（{e}）→ 跳过流日志检查")
    return paths


# ── 告警（委托 push_card） ────────────────────────────────
def push_alert(title, body, dedupe_key, dry):
    if dry:
        print(f"[DRY-RUN] 待推送: {title} | key={dedupe_key}")
        return True
    if not (PY_BIN.exists() and PUSH_CARD.exists()):
        print(f"推送通路不可用（PY_BIN={PY_BIN.exists()} push_card={PUSH_CARD.exists()}）")
        return False
    cmd = [
        str(PY_BIN),
        str(PUSH_CARD),
        "--title",
        title,
        "--level",
        "alert",
        "--section",
        "详情",
        body,
        "--dedupe-key",
        dedupe_key,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            print(f"push_card rc={r.returncode} out={(r.stdout or r.stderr or '')[-300:]}")
        return r.returncode == 0
    except Exception as e:
        print(f"push_card 异常: {e}")
        return False


def launchctl_print(job):
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{UID}/{job}"], capture_output=True, text=True, timeout=30
        )
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


# ── 主流程 ────────────────────────────────────────────────
def main():
    cfg = load_conf()
    dry = cfg.get("DRY_RUN", "0") == "1" or "--dry-run" in sys.argv
    jobs_cfg = dict(JOBS)
    if cfg.get("ONLY_JOBS"):
        want = {x.strip() for x in cfg["ONLY_JOBS"].split(",") if x.strip()}
        jobs_cfg = {k: v for k, v in jobs_cfg.items() if k in want}
    if cfg.get("ADD_JOBS"):  # 注入额外对象（受控验证用）：name:interval
        for pair in cfg["ADD_JOBS"].split(","):
            name, _, itv = pair.strip().partition(":")
            if name and itv.isdigit():
                jobs_cfg[name.strip()] = int(itv)

    state_ok = True
    try:
        st = load_state()
    except Exception:
        state_ok = False
        st = {"jobs": {}, "logs": {}, "alerts": {}}
    now_s = time.time()
    now_label = datetime.now().strftime("%F %T")
    pushed, blocked = 0, 0

    for job, interval in sorted(jobs_cfg.items()):
        issues = []
        out = launchctl_print(job)
        issues += check_load_and_exit(out, job)
        runs = None
        if out is not None:
            m = re.search(r"runs = (\d+)", out)
            runs = int(m.group(1)) if m else None
            if runs is not None:
                prev = st["jobs"].get(job)
                if prev is None:
                    st["jobs"][job] = {"runs": runs, "ts": now_s}
                else:
                    si, entry = check_stall(job, interval, runs, prev, now_s)
                    issues += si
                    st["jobs"][job] = entry
            # ④流日志
            for lp in stream_log_paths(job):
                si, entry = check_log(lp, st["logs"].get(str(lp)))
                issues += si
                if si or entry is not None:
                    st["logs"][str(lp)] = entry or {"size": 0}

        for kind, detail in issues:
            key = f"jobwatch:{job}:{kind}:{detail[:40]}"
            last = st["alerts"].get(key, 0)
            if now_s - last < ALERT_TTL_H * 3600:
                blocked += 1
                continue
            if push_alert(
                f"🟡 launchd 异常：{job}", f"**{kind}**\n{detail}\n\n检出 {now_label}", key, dry
            ):
                st["alerts"][key] = now_s
                pushed += 1

    if state_ok:
        try:
            save_state(st)
        except OSError:
            print("状态文件不可写（SSD 掉线？）→ 本轮状态未保存")
    print(
        f"[{now_label}] job-watch 完成：检查 {len(jobs_cfg)} job，"
        f"告警 {pushed} 条（dry={dry}），抑制 {blocked} 条"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
