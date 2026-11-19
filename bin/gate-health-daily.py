#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
"""门禁每日调度（2026-11-16）：queue_health + event_liveness 汇总推卡。

设计：
- 两个只读门禁各自 rc：1=FAIL｜0=PASS｜2=数据不可得（SKIP，不冒充）
- 任一 FAIL → 当天推一张 alert 卡（--dedupe-key=日期+verdict 天然幂等）
- 昨日 FAIL 今日 PASS → 推 success 恢复卡（对齐 automation_failure_watchdog 先例）
- 持续 PASS 静默不推（不刷群）；rc=2 写日志不推（数据问题≠队列问题）
- 必须由授权 python（~/.workbuddy/binaries）承载：脚本读外置卷 ZHITAI，
  系统 python 会被 TCC 静默 EPERM（.learnings/2026-10-30）

launchd: com.user.gate-health（每日 17:25——巡检转队列 17:15 之后、17:30 轮之前）
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

PY = Path("/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3")
CLAW = Path("/Volumes/ZHITAI/WorkBuddy/Claw")
PUSH_CARD = CLAW / ".workbuddy" / "scripts" / "push_card.py"
STATE = Path.home() / ".local" / "state" / "gate-health-last-verdict"
LOG = Path.home() / "Library" / "Logs" / "gate-health.log"

SCRIPTS = [
    ("queue_health", CLAW / "scripts" / "queue_health.py", []),
    ("event_liveness", CLAW / "scripts" / "event_liveness.py", ["--no-write"]),
]


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def run_gate(name: str, script: Path, extra: list[str]) -> tuple[str, str, int]:
    r = subprocess.run(
        [str(PY), str(script), *extra], capture_output=True, text=True, timeout=120
    )
    return name, (r.stdout + r.stderr).strip(), r.returncode


def main() -> int:
    day = datetime.now().strftime("%Y-%m-%d")
    results = [run_gate(n, s, x) for n, s, x in SCRIPTS]
    rc_map = {n: rc for n, _, rc in results}
    body_parts = []
    for name, out, rc in results:
        tail_lines = [l for l in out.splitlines() if l.startswith(("🔴", "🟡", "[", "--"))]
        body_parts.append(f"【{name}】rc={rc}\n" + "\n".join(tail_lines[-8:]))
    if any(rc == 1 for rc in rc_map.values()):
        verdict = "FAIL"
    elif any(rc == 2 for rc in rc_map.values()):
        verdict = "SKIP"
    else:
        verdict = "PASS"
    log(f"verdict={verdict} rc={rc_map}")

    if verdict == "SKIP":
        log("SKIP：数据不可得，不推卡不冒充")
        return 2

    last = STATE.read_text().strip() if STATE.exists() else ""
    should_push = verdict == "FAIL" or (verdict == "PASS" and last == "FAIL")
    if not should_push:
        log("PASS 静默（昨日亦 PASS），不推卡")
        STATE.write_text(verdict)
        return 0

    level = "alert" if verdict == "FAIL" else "success"
    title = f"[门禁日报] {verdict}" + ("（队列/事件活性异常）" if verdict == "FAIL" else "（已恢复）")
    dedupe = f"gate-health-{day}-{verdict}"
    cmd = [
        str(PY), str(PUSH_CARD),
        "--title", title,
        "--level", level,
        "--section", "门禁汇总", "\n".join(body_parts) or "（无输出）",
        "--footer", f"queue_health + event_liveness ｜ {day} ｜ 同日同结论幂等",
        "--dedupe-key", dedupe,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    log(f"push rc={r.returncode} out={r.stdout.strip()[:120]} err={r.stderr.strip()[:120]}")
    STATE.write_text(verdict)
    return 1 if verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
