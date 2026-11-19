#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3.13
# launchd CLI 的产出写进日志（重定向到 ~/.local/log），与 pmf-db-snapshot.py 同理。
# ruff: noqa: T201
"""pmf 每日快照的「补班车」（catch-up）。

## 为什么需要
03:00 的 launchd StartCalendarInterval 在宿主机睡眠 / DarkWake 时会错过，
且原 plist `RunAtLoad=false` 不补跑 —— 2026-11-06 实测整天没备份，
`last-snapshot.json` 停在 11-05 03:00，断档约 45 小时才被发现。

本任务每小时检查一次：当天还没有成功快照就补跑一次，已跑过就静默跳过。
原 03:00 任务一行不改，回滚只需 `launchctl unload` 对应 plist。

## 纪律
· 每日最多补跑一次：以 db/last-snapshot.json 的 taken_at（UTC）换算本地日期为准
· 04:00 前不判漏跑：跨午夜后 marker 日期仍是「昨天」，00:34 会被误判成漏跑
  （2026-11-08 / 11-09 实测各误补一次、各多一个提交与一条飞书误告警）
· 先判「今日已快照」再判宽限窗：反过来的话，00:1x 手动跑过快照也会被记成
  「未过宽限期」，把两个口径混在一起（审计 11-14 指出）
· 与本进程的文件锁只能防「兜底自己并发」；原 03:00 任务**没有锁**，所以补跑前
  必须额外用 pgrep 探测原任务是否在跑，在跑就跳过本轮（2026-11-14 修虚假声明）
· 补跑后**回读 marker**：退出码 0 不等于产物更新了（本次事故的核心教训）
· 告警失败不拖垮主链路：只记日志，不改退出码
· `--dry-run` 只判断、不执行、不发告警，且日志写独立文件（不污染生产日志口径）
· 后台任务读写外置卷必须走 WorkBuddy 自带 python（TCC 按二进制授权）
"""

import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HOME = Path("/Users/guan")
REPO = Path("/Volumes/ZHITAI/WorkBuddy/project-monitor-fusion")
MARKER = REPO / "db" / "last-snapshot.json"
WRAPPER = HOME / ".local/bin/pmf-db-snapshot.py"
LOCK = HOME / ".local/var/pmf-db-snapshot-catchup.lock"
LOG = HOME / ".local/log/pmf-db-snapshot-catchup.log"
# 人工 dry-run 单独一份，避免「检查：」行走势混进生产日志、污染触发分布统计。
LOG_DRYRUN = HOME / ".local/log/pmf-db-snapshot-catchup.dryrun.log"
PY_BIN = "/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3.13"
PUSH_CARD = HOME / "WorkBuddy/Claw/.workbuddy/scripts/push_card.py"
CHAT_ID = "oc_9ee5303497f5e0e71666b610d6bdc346"
DRY_RUN = "--dry-run" in sys.argv
# 03:00 原任务 + 1 小时宽限；04:00 起才允许判定「今天漏跑」。
GRACE_HOUR = 4

ENV = {
    **os.environ,
    "PATH": "/Users/guan/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": str(HOME),
}


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    # plist 的 StandardOutPath 与 LOG 是同一个文件。若这里同时 print + 手写文件，
    # 每行会被写两遍（2026-11-09 实测 314 行里 146 行是相邻重复，计数全翻倍）。
    # 只在手工 dry-run 时打印到终端；常驻运行只写文件一份。
    # dry-run 另写 LOG_DRYRUN：人工检查不计入「每小时触发分布 / 补跑率」分母。
    target = LOG_DRYRUN if DRY_RUN else LOG
    if DRY_RUN:
        print(line, flush=True)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def within_grace_period(now: datetime) -> bool:
    """03:00 原任务 + 1h 宽限：之前不判漏跑（跨午夜 marker 日期仍是昨天）。"""
    return now.hour < GRACE_HOUR


def original_running() -> str | None:
    """探测 03:00 原任务是否正在跑，返回命中的进程描述。

    为什么要单独探测：本进程的 flock 只锁自己这把 LOCK 文件，而原 wrapper
    （pmf-db-snapshot.py）**完全没有加锁**。机器 03:00 睡过、04:15 唤醒时，
    launchd 会立刻补跑原任务，本任务 04:17 又判定「marker 还是昨天」→ 两个
    dump 并发 → index.lock 冲突 → 其中一个提交失败 → 这里误报「补跑失败」。
    不修改原链路（方案 B），只在补跑前避让。
    """
    for pattern, label in (
        (str(WRAPPER), "原 wrapper 进程"),
        (f"{REPO}/scripts/db-snapshot.sh", "db-snapshot.sh"),
    ):
        try:
            r = subprocess.run(
                ["/usr/bin/pgrep", "-f", pattern],
                env=ENV,
                timeout=15,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            # 探测本身失败时不要乐观放行：宁可少补一次（下一小时还会再判），
            # 也不要和原任务抢同一个 index.lock。
            log(f"⚠️ 原任务探测失败（本轮跳过，下小时重试）：{exc}")
            return "探测异常"
        if r.returncode == 0 and r.stdout.strip():
            pids = ",".join(r.stdout.split())
            return f"{label} pid={pids}"
    return None


def marker_date():
    """返回上次成功快照的本地日期；读不到返回 None。"""
    try:
        data = json.loads(MARKER.read_text(encoding="utf-8"))
        ts = data["taken_at"].replace("Z", "+00:00")
        return datetime.fromisoformat(ts).astimezone().date(), ts
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log(f"⚠️ marker 读取失败（按「未备份」处理）：{exc}")
        return None, None


def notify(level: str, title: str, sections) -> None:
    """复用 Claw push_card.py。告警通路故障不得影响备份主链路。"""
    if DRY_RUN:
        return
    cmd = [PY_BIN, str(PUSH_CARD), "--title", title, "--level", level]
    for heading, body in sections:
        cmd += ["--section", heading, body]
    cmd += [
        "--chat-id",
        CHAT_ID,
        "--dedupe-key",
        f"pmf-snapshot-catchup-{level}-{datetime.now():%Y%m%d}",
    ]
    try:
        r = subprocess.run(cmd, env=ENV, timeout=90, capture_output=True, text=True)
        log(f"📨 告警发送 rc={r.returncode} level={level} out={r.stdout.strip()[:200]}")
    except Exception as exc:  # noqa: BLE001 - 告警是旁路，任何异常都不能改主链路结果
        log(f"⚠️ 告警发送失败（非致命）：{exc}")


def main() -> int:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w", encoding="utf-8") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("ℹ️ 另一个快照任务正在运行，本次跳过")
            return 0

        now = datetime.now().astimezone()
        today = now.date()
        last, raw = marker_date()
        log(f"检查：今日={today} 上次快照日期={last} taken_at={raw}")

        # 「今天已有快照」优先于宽限窗判断：否则 00:1x 手动跑过快照也会被记成
        # 「未过宽限期」，两个口径混在一起，跳过量与宽限量的统计都不准。
        if last == today:
            log("✅ 今日已快照，跳过")
            return 0

        # 跨午夜后 marker 日期仍是昨天，但 03:00 原任务还没到点 —— 不是漏跑。
        if within_grace_period(now):
            log(f"ℹ️ 当前 {now:%H:%M} 未过 {GRACE_HOUR}:00 宽限期，不判漏跑（03:00 原任务尚未到点）")
            return 0

        running = original_running()
        if running is not None:
            log(f"ℹ️ 检测到原 03:00 任务正在运行（{running}），本轮跳过以免并发争抢")
            return 0

        if DRY_RUN:
            log("🔎 dry-run：判定为「需要补跑」，未执行、未告警")
            return 0

        log("🚨 检测到今日尚未快照，开始补跑（原 03:00 任务可能错过）")
        rc = subprocess.run(
            [PY_BIN, str(WRAPPER)],
            # 让 wrapper 在 commit message 上打 [catchup]：否则补跑与原任务产出
            # 两条同名提交（11-08 / 11-09 已实际发生），事后无法区分。
            env={**ENV, "PMF_SNAPSHOT_CATCHUP": "1"},
            check=False,
        ).returncode

        # 回读实际状态：退出码 0 不等于产物真的更新了
        new_last, new_raw = marker_date()
        if rc == 0 and new_last == today:
            log(f"✅ 补跑成功并已回读确认：taken_at={new_raw}")
            notify(
                "warning",
                "[pmf] 🟡 03:00 快照漏跑，已自动补跑",
                [
                    ("故障", f"原定 03:00 的每日快照未执行，上次成功快照为 {last or '未知'}。"),
                    ("处置", "补班车（每小时检查）已自动补跑，产物已回读确认。"),
                    (
                        "依据",
                        f"`db/last-snapshot.json` taken_at={new_raw}；已提交并推送 origin/main。",
                    ),
                ],
            )
            return 0

        log(f"❌ 补跑失败：rc={rc} marker={new_last}（期望 {today}）")
        notify(
            "alert",
            "[pmf] 🔴 快照补跑失败",
            [
                ("故障", f"今日快照缺失且补跑未成功（rc={rc}）。"),
                ("状态", f"`last-snapshot.json` 仍为 {new_raw or '读不到'}。"),
                ("处置", "请手工执行 `~/.local/bin/pmf-db-snapshot.py` 并核对日志与 origin/main。"),
            ],
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
