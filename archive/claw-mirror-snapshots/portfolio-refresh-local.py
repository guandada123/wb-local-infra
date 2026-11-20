#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
"""持仓价格刷新本地兜底（2026-11-18）。

背景：平台「📈【持仓】每日价格刷新（交易日 15:12）」是**会话型自动化**，
平台会话中断即失效（11-17 全天 Automation prompt stopped / Conversation ended before，
导致持仓行情断供 2 个交易日）。持仓行情是投资决策的基础数据，不能依赖平台可用性。

本启动器由 launchd 每交易日 15:15 调用（平台 15:12 之后 3 分钟，作为兜底）：
- 纯本地执行 refresh_portfolio.py（只读行情 + 写价格字段，不改持仓结构/现金）
- 幂等：重复刷新只覆盖价格，不累计
- 由已授权 python 派生，继承外置卷 TCC 权限
- 失败写日志并推送飞书（不静默）
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 环境变量可覆盖（CLAW_HOME）；默认本机路径以保持 launchd 零配置。
# 2026-11-19：与 claw-script-runner 同步，避免硬编码绝对路径在异地环境失效。
CLAW = Path(os.environ.get("CLAW_HOME", "/Volumes/ZHITAI/WorkBuddy/Claw"))
SCRIPT = CLAW / ".workbuddy" / "scripts" / "refresh_portfolio.py"
LOG = Path.home() / ".agent-autoloop" / "logs" / "portfolio-refresh.log"
PUSH = Path.home() / ".local" / "bin" / "autoloop-feishu-push.py"
WEEKEND_FROM = 5  # weekday(): 周一=0 … 周六=5


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def main() -> int:
    # 只在工作日跑（周一~周五）。仓库无交易日历模块，节假日会多刷一次——
    # 但节假日价格不变，重复刷新幂等无害；宁可多刷也不能漏刷。
    if datetime.now().weekday() >= WEEKEND_FROM:
        log("周末，跳过")
        return 0

    r = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=str(CLAW), capture_output=True, text=True, timeout=300
    )
    out = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-6:])
    if r.returncode == 0 and "[OK] 持仓已保存" in out:
        log(f"[OK] 刷新成功 rc=0\n{tail}")
        return 0
    log(f"[FAIL] rc={r.returncode}\n{out[-1500:]}")
    # 失败必须告警（与平台自动化同口径：禁止静默）
    try:
        subprocess.run(
            [
                sys.executable,
                str(PUSH),
                "--text",
                f"⚠️ 持仓价格刷新失败（本地兜底）rc={r.returncode}\n{tail[-500:]}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as e:  # noqa: BLE001 告警失败不影响退出码
        log(f"[warn] 告警发送失败: {type(e).__name__}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
