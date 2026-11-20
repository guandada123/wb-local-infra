#!/usr/bin/env python3
"""wb-memory-push.py — 用户级 MEMORY.md 远端备份推送（2026-10-30 P1）

为什么核心逻辑是 python 而不是 bash：
  2026-10-30 实测（TCC）：新装载的 launchd 任务与 cron 上下文对 /Volumes/ZHITAI
  的文件 open/getcwd 全部 EPERM；但 ~/.workbuddy/binaries 的 python **已被系统
  放行**（wb-liveness.sh:138-139 既有先例「launchd 下 python 读 SSD 脚本可用」）。
  TCC 按二进制授权且子进程继承 —— 所以 git/push_card 全部经由 PY_BIN 子进程跑。

职责：宿主 memory-lock-bot 只 commit 不 push；本脚本由 wb-liveness 两个模式
  挂靠调用（每小时级），把 main 推到 GitHub 私有仓。独立于记忆写入路径，
  失败只告警不阻塞写入。

告警通路：push_card.py → 飞书主群（与 wb-liveness 同一 PY_BIN 调用方式）。
退出码：0 正常（含"已是最新"）/ 1 检测到故障（已按节流告警）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME = Path(os.environ.get("HOME") or Path.home())
CONF = Path(os.environ.get("WB_MEMORY_PUSH_CONF") or HOME / ".local/etc/wb-memory-push.conf")
LOG = Path(os.environ.get("WB_MEMORY_PUSH_LOG") or HOME / "Library/Logs/wb-memory-push.log")
STATE = Path(os.environ.get("WB_MEMORY_PUSH_STATE") or HOME / ".local/state/wb-memory-push")
LOCK = Path(str(STATE) + ".lock")

MODE = sys.argv[1] if len(sys.argv) > 1 else "run"  # run | --dry-run | --test-alert

DEFAULTS = {
    "REPO_PATH": "",
    "BRANCH": "main",
    "PUSH_CARD": str(HOME / "WorkBuddy/Claw/.workbuddy/scripts/push_card.py"),
    "CHAT_ID": "",
    "ALERT_THROTTLE_SEC": "21600",
}

LOG_ROTATE_BYTES = 1_048_576  # 1MB，同 wb-heartbeat 约定
STALE_LOCK_SEC = 900  # 15min：陈锁清理阈值


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        if LOG.exists() and LOG.stat().st_size > LOG_ROTATE_BYTES:
            shutil.move(LOG, str(LOG) + ".1")
    except OSError:
        pass
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def fail(reason: str, detail: str) -> int:
    log(f"FAIL {reason}")
    if MODE == "--dry-run":
        return 1
    alert(reason, detail)
    return 1


def alert(reason: str, detail: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    last_file = STATE / "last_alert"
    now = int(time.time())
    try:
        last = int(last_file.read_text().strip() or 0)
    except (OSError, ValueError):
        last = 0
    if MODE != "--test-alert" and now - last < int(CFG["ALERT_THROTTLE_SEC"]):
        log(f"ALERT 抑制（节流期内）reason={reason}")
        return
    last_file.write_text(str(now))
    dedupe = f"wb-memory-push-{reason}-{datetime.now():%Y%m%d}"
    log(f"ALERT reason={reason} dedupe={dedupe}")
    cmd = [
        PY_BIN,
        str(Path(CFG["PUSH_CARD"])),
        "--title",
        "[memory-push] 🔴 记忆远端备份异常",
        "--level",
        "alert",
        "--section",
        "故障",
        reason,
        "--section",
        "详情",
        detail,
        "--section",
        "处置",
        "先跑 wb-memory-push.sh --dry-run 复核；恢复手册见仓库 RESTORE.md",
        "--chat-id",
        CFG["CHAT_ID"],
        "--dedupe-key",
        dedupe,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0 and "om_" in (r.stdout + r.stderr)
        log("ALERT 已发送" if ok else f"ALERT 发送失败 rc={r.returncode} {r.stderr.strip()[:200]}")
    except Exception as e:  # noqa: BLE001 —— 告警失败只记日志，不改变主流程
        log(f"ALERT 发送异常 {e}")


def git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", CFG["REPO_PATH"], *args], capture_output=True, text=True, timeout=timeout
    )


# ---- 入口 ----
if not CONF.exists():
    log(f"未配置 {CONF} → 跳过（装完可控，同 wb-heartbeat 约定）")
    sys.exit(0)

CFG = dict(DEFAULTS)
for raw_line in CONF.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        if k in DEFAULTS:
            CFG[k] = v.strip()

PY_BIN = HOME / ".workbuddy/binaries/python/envs/default/bin/python"
if not PY_BIN.exists():  # ⚠️ 必须是这套被 TCC 放行的 python；/usr/bin/python3 会 EPERM
    log(f"放行 python 不存在：{PY_BIN} → 无法在本上下文读外置卷，退出")
    sys.exit(1)

if MODE == "--test-alert":
    log("TEST-ALERT 触发")
    alert(
        "测试（可证伪：本条来自 --test-alert，非真实故障）",
        "验证 push_card → 飞书主群通路；见即通路正常，无需处置。",
    )
    sys.exit(0)

# ---- 互斥（陈锁 15min 清理） ----
STATE.mkdir(parents=True, exist_ok=True)
if LOCK.exists():
    age = int(time.time()) - int(LOCK.stat().st_mtime)
    if age < STALE_LOCK_SEC:
        log(f"已有实例在跑（锁龄 {age}s）→ 退出")
        sys.exit(0)
    log(f"清理陈锁（锁龄 {age}s）")
    shutil.rmtree(LOCK, ignore_errors=True)
LOCK.mkdir()
try:
    repo = Path(CFG["REPO_PATH"])
    # 1) 仓库可达（外置盘挂载 / 链接有效；python 二进制已放行，可直接 stat）
    if not (repo / ".git").is_dir():
        sys.exit(
            fail(
                "仓库不可达",
                f"路径 {repo} 下没有 .git —— 大概率外置 SSD 未挂载或 ~/.workbuddy "
                "符号链接悬空。记忆此刻不在被备份。",
            )
        )

    # 2) 本地分支
    r = git("rev-parse", "--verify", CFG["BRANCH"])
    if r.returncode != 0:
        sys.exit(fail("本地分支缺失", f"{repo} 上找不到分支 {CFG['BRANCH']}"))
    local_head = r.stdout.strip()

    # 3) 远端可达（40s 超时防挂死）
    try:
        r = git("ls-remote", "origin", f"refs/heads/{CFG['BRANCH']}", timeout=40)
    except subprocess.TimeoutExpired:
        r = None
    remote_head = (
        r.stdout.strip().split("\t")[0] if r and r.returncode == 0 and r.stdout.strip() else ""
    )
    if not remote_head:
        sys.exit(
            fail(
                "远端不可达",
                "ls-remote origin 无响应/超时 —— 网络或 GitHub 侧问题；"
                "备份已停更，恢复后自动接续。",
            )
        )

    # 4) 决策
    if remote_head == local_head:
        log(f"OK 已是最新（{local_head}）")
        (STATE / "last_alert").unlink(missing_ok=True)
        sys.exit(0)

    anc = git("merge-base", "--is-ancestor", remote_head, local_head)
    if anc.returncode == 0:
        n = git("rev-list", "--count", f"{remote_head}..{local_head}").stdout.strip()
        if MODE == "--dry-run":
            log(f"DRY-RUN 将 push {n} commit（{remote_head} → {local_head}）")
            sys.exit(0)
        p = git("push", "origin", CFG["BRANCH"], timeout=120)
        if p.returncode == 0:
            log(f"OK 已 push {n} commit（现 {local_head}）")
            (STATE / "last_alert").unlink(missing_ok=True)
            sys.exit(0)
        sys.exit(
            fail(
                "push 失败",
                f"本地 {local_head} 领先远端 {n} commit，但 push 被拒/失败："
                f"{p.stderr.strip()[:200]}",
            )
        )

    sys.exit(
        fail(
            "远端分叉",
            f"远端 main={remote_head} 不是本地 {local_head} 的祖先 —— "
            "出现预期外写入方，禁 force，需人工比对。",
        )
    )
finally:
    shutil.rmtree(LOCK, ignore_errors=True)
