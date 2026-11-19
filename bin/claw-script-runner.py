#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
"""Claw 脚本本地执行器 —— 把平台会话型自动化下放到 launchd（2026-11-19）。

## 为什么需要它
平台的自动化是**会话型**：一次运行要起一个 AI 会话。平台侧会话被收走
（`Automation prompt stopped` / `Conversation ended before…`）时任务就失败，
2026-11-17/18 连续两天因此大面积中断（含持仓行情断供 2 个交易日）。
纯脚本任务（取数/同步/回填/校验）不该受这个影响。

## 两个必须解决的约束
1. **TCC**：launchd 后台进程读外置卷 `/Volumes/ZHITAI` 必须由
   `~/.workbuddy/binaries` 的 python 发起（按二进制授权、子进程继承）。
2. **依赖**：业务脚本的依赖装在仓库 `.venv`（如 psycopg2 2.9.13），
   而授权 python 没有。

本执行器由授权 python 运行，再用 `subprocess` 派生 `.venv/bin/python`
执行目标脚本——子进程继承父进程的 TCC 授权，同时拿到 venv 的依赖。

## 适用边界（重要，2026-11-19 审计 P3-2 补）
仅用于**幂等**脚本。`--trading-day-only` 在交易日判据不可用时采取 **fail-open**
（按交易日执行），对幂等的取数/回填/同步无害；但对会发消息、累加计数、产生副作用的
脚本，fail-open 会变成「重复执行」。迁非幂等脚本前必须改判据或加去重。

## 用法
    claw-script-runner.py --name qts-backfill \
        --script .workbuddy/scripts/qts_daily_backfill.py \
        --timeout 1800 --trading-day-only -- --days 1
"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 🔴 2026-11-19：原为硬编码绝对路径，CI（/home/runner/work/Claw）上必然失效，
# 导致 is_trading_day() 里 checker.exists() 为 False、门禁静默降级为 None。
# 改为环境变量可覆盖（CLAW_HOME），默认仍为本机路径以保持 launchd 零配置。
CLAW = Path(os.environ.get("CLAW_HOME", "/Volumes/ZHITAI/WorkBuddy/Claw"))
VENV_PY = CLAW / ".venv" / "bin" / "python"
LOG_DIR = Path.home() / ".agent-autoloop" / "logs"
PUSH = Path.home() / ".local" / "bin" / "autoloop-feishu-push.py"


def log(name: str, msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / f"{name}.log").open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def is_trading_day() -> bool | None:
    """用仓库既有脚本判断交易日；不可判定时返回 None（调用方决定策略）。

    🔴 2026-11-19 修正（审计 P1-1）：原实现按退出码判断（rc=0 交易日 / rc=1 非交易日），
    但 `is_trading_day.py` **从不设置非零退出码**——它只输出文本、始终 rc=0。
    实测 `is_trading_day.py 2026-11-21` → 打印「非交易日 ❌」而 rc=0，
    导致本函数恒返回 True，`--trading-day-only` 门禁形同虚设（周末照跑）。
    现改为解析输出文本。注意「非交易日」包含「交易日」子串，必须先判前者。
    """
    checker = CLAW / "scripts" / "is_trading_day.py"
    if not checker.exists():
        return None
    try:
        r = subprocess.run(
            [str(VENV_PY), str(checker)], cwd=str(CLAW), capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "") + (r.stderr or "")
    if "非交易日" in out:
        return False
    if "交易日" in out:
        return True
    return None


def notify(text: str) -> None:
    """失败告警。禁止静默——失败本身已写日志，此处仅尝试推送。

    告警通道自身失败不改变退出码（否则会掩盖真正的失败原因）。
    """
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(
            [str(VENV_PY), str(PUSH), "--text", text],
            capture_output=True,
            text=True,
            timeout=60,
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="日志/告警标识")
    ap.add_argument("--script", required=True, help="相对 CLAW 的脚本路径")
    ap.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help="`--` 之后的所有参数原样透传给目标脚本",
    )
    ap.add_argument("--timeout", type=int, default=1800, help="硬超时秒数")
    ap.add_argument("--trading-day-only", action="store_true", help="非交易日跳过")
    args = ap.parse_args()

    # 先校验根目录（2026-11-19 审计 P3-1）：CLAW_HOME 拼错时若只报「脚本不存在」，
    # 排查会绕路。此处明确给出当前 CLAW 值与覆盖方式，且发生在任何 subprocess 之前。
    if not CLAW.is_dir():
        log(
            args.name,
            f"[FAIL] CLAW 根目录不存在: {CLAW}（用 CLAW_HOME 覆盖，当前值来自"
            f"{'环境变量' if os.environ.get('CLAW_HOME') else '默认值'}）",
        )
        notify(f"⚠️ {args.name} 本地执行失败：CLAW 根目录不存在 {CLAW}")
        return 2

    script = CLAW / args.script
    if not script.exists():
        log(args.name, f"[FAIL] 脚本不存在: {script}")
        notify(f"⚠️ {args.name} 本地执行失败：脚本不存在 {args.script}")
        return 2
    if not VENV_PY.exists():
        log(args.name, f"[FAIL] venv python 不存在: {VENV_PY}")
        notify(f"⚠️ {args.name} 本地执行失败：venv 缺失")
        return 2

    if args.trading_day_only:
        td = is_trading_day()
        if td is False:
            log(args.name, "[SKIP] 非交易日")
            return 0
        if td is None:
            # 判不出就不跳：宁可多跑一次（脚本幂等），也不要漏跑
            log(args.name, "[warn] 交易日判据不可用，按交易日处理")

    extra = [a for a in args.passthrough if a != "--"]
    log(args.name, f"[RUN] {args.script} {' '.join(extra)}（超时 {args.timeout}s）")
    try:
        r = subprocess.run(
            [str(VENV_PY), str(script), *extra],
            cwd=str(CLAW),
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
    except subprocess.TimeoutExpired:
        log(args.name, f"[FAIL] 超时 >{args.timeout}s，已终止")
        notify(f"⚠️ {args.name} 本地执行超时（>{args.timeout}s），请检查数据源或网络")
        return 1

    out = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-8:])
    if r.returncode == 0:
        log(args.name, f"[OK] rc=0\n{tail}")
        return 0
    log(args.name, f"[FAIL] rc={r.returncode}\n{out[-2000:]}")
    notify(f"⚠️ {args.name} 本地执行失败 rc={r.returncode}\n{tail[-600:]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
