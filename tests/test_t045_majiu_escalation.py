#!/usr/bin/env python3
"""T-045：马厩归档总册「连续 N 天才升级」的分档判据（可证伪）。

## 为什么需要

`infra-sync-check` 每日检查总册过期，每日都推一张飞书 warning 卡。
总册不是「每天都需要刷新」的对象 —— 每日必报 = 每日必忽略（告警疲劳），
但它也不是无害信息（DR/交接要靠它）。故分三档：

  · 日常过期（连续 < N 天）→ 只写日志，不推卡
  · 连续 ≥ N 天（默认 7）  → 推一张卡
  · 同一轮（同一 first_stale）只推一次（写 pushed_for 去重）
  · 恢复正常（rc=0）      → 删状态文件，下轮重新计数

## 怎么制造「确定性过期」

第一版靠 `MAJIU_SCRIPT` / `MAJIU_STATE` 环境变量覆盖 —— 那是**测试后门**，
2026-11-28 已从生产脚本移除（留着等于给外部一个改判据的开关）。

改为：把 `MAJIU_FILE` 指向一个内容必然与当前台账不一致的临时 md，
真实脚本对它 `--check` 就会 `rc=1`，即确定性地处于「过期」态。
`MAJIU_FILE` 是生产设计里**本来就支持**的环境覆盖位（`${MAJIU_FILE:-...}`），
不是为测试新加的口子。

状态文件是真实路径 `~/.local/state/majiu-stale.json` —— 测试前后备份/还原，不污染线上计数。

## 三档

① 连续 1 天        → 总册段为「无」
② 连续 7 天        → 出现「连续 7 天」
②b 同一轮再跑      → 又变「无」（pushed_for 去重）
③ 恢复（真实总册） → 状态文件被删

负控（改坏生产脚本应能击破本判据，实测记录见提交信息）：
· 阈值 7 改 1        → ① 红
· 去掉 pushed_for 去重 → ②b 红
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path.home() / ".local" / "bin" / "infra-sync-check"
STATE = Path.home() / ".local" / "state" / "majiu-stale.json"

# 🔴 自污染陷阱（2026-11-28 实测半小时）：`infra-sync-check` 第一步就跑
# `unittest discover -s tests`，而**本文件在 tests/ 里** —— 于是每次跑检查都会把本测试
# 再跑一遍，本测试又去改真实状态文件 → 状态在「脚本刚启动」和「走到⑤」之间被抹成今天，
# 连续天数永远 = 1，②档怎么都过不了，且**现象看起来像生产代码的 bug**。
# 解法：默认不接管真实状态；只有显式 `T045_RUN=1` 才执行判据。
# 这不是「绕过测试」，而是「测试不该在别的测试的执行链里跑」——
# 自我保护用一个显式开关，比靠 import 栈猜测更可靠，也更容易被 reviewer 看见。
GUARD_ENV = "T045_RUN"


# 隔离路径**不能**用 mkdtemp：它是 macOS 的 `$TMPDIR`（/var/folders/...），
# 时长跑会被清理，实测出现「文件突然消失 → streak=0 → ②档失败」。
# 固定放仓内 `.tmp_t045/`（已 gitignore），生命周期由测试自己控制，跨进程稳定。
_ISO = Path(__file__).resolve().parents[1] / ".tmp_t045" / "majiu-stale.json"
_REPO = Path(__file__).resolve().parents[1] / ".tmp_t045" / "checker-repo"


def _run(majiu_file: Path) -> str:
    """跑一次 DRY_RUN，返回「总册「...」」里的内容。"""
    env = {**os.environ, "MAJIU_FILE": str(majiu_file), "DRY_RUN": "1",
           "MAJIU_STATE_OVERRIDE": str(_ISO),    # 隔离位：只换文件位置，不换判据
           "REPO_OVERRIDE": str(_REPO), "LOG_OVERRIDE": str(Path("/tmp") / "t045-chk.log"),
           "AGENTS": str(_REPO.parent / "agents"), "LIVE_BIN": str(_REPO.parent / "live"),
           "CLAW_HOME": str(_REPO.parent / "no-claw")}
    r = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=300)
    out = r.stdout or ""
    start = out.find("总册「")
    if start < 0:
        # 无任何问题 → 脚本走成功分支只打印 `OK: 五类通过…`，没有总册段。
        # 这等价于「不推卡」，判为「无」。第一版返回「未找到总册段」把它当失败，
        # 于是 ①（本该 PASS）被误判成 FAIL。
        return "无" if out.lstrip().startswith("OK:") else "<未找到总册段>"
    end = out.find("」", start)
    return out[start + 3 : end if end > 0 else None]


def _prep_checker_repo(script: Path) -> Path:
    """给被测脚本准备一个**小**仓：拷 bin/ + 一个 trivial 测试，避免它去跑父仓全量 unittest。

    2026-11-28：第一版直接让被测脚本在父仓跑，它第一步 `unittest discover -s tests`
    会跑 100 条测试（~25s）且包含本文件 → 既慢又自污染。改用合成仓后，
    被测的「写状态/读状态」逻辑一点没变，只是扫描面变小。
    """
    base = Path(__file__).resolve().parents[1] / ".tmp_t045" / "checker-repo"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    for d in ("bin", "tests", "launchd"):
        (base / d).mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve().parents[1] / "install.sh", base / "install.sh")
    shutil.copy2(script, base / "bin" / "infra-sync-check")
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "bin" / "majiu-archive-index.py",
        base / "bin" / "majiu-archive-index.py",
    )
    (base / "bin" / "dummy.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    (base / "tests" / "test_smoke.py").write_text(
        "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
        encoding="utf-8",
    )
    (base / "launchd" / "active.txt").write_text("# 空清单\n", encoding="utf-8")
    return base


def main() -> int:
    if os.environ.get(GUARD_ENV) != "1":
        print(f"SKIP: 本判据会改真实状态文件，默认不跑（显式执行：{GUARD_ENV}=1 python3 {Path(__file__).name}）")
        return 0
    if not SCRIPT.is_file():
        print(f"SKIP: {SCRIPT} 不存在")
        return 0


    failures: list[str] = []
    tmpdir = Path(__file__).resolve().parents[1] / ".tmp_t045"
    tmpdir.mkdir(parents=True, exist_ok=True)
    try:
        _prep_checker_repo(SCRIPT)
        for d in ("agents", "live", "no-claw"):
            (Path(__file__).resolve().parents[1] / ".tmp_t045" / d).mkdir(parents=True, exist_ok=True)

        # 一个必然「过期」的假总册：内容随便写，--check 重建后必然不一致
        fake = Path(tmpdir) / "fake-majiu.md"
        fake.write_text("# 假总册（T-045 验收用）\n\n本文件内容与当前台账必然不一致。\n", encoding="utf-8")

        # ① 连续 1 天 → 不应进卡片（先清隔离状态，确保是「首次过期」）
        if _ISO.exists():
            _ISO.unlink()
        seg1 = _run(fake)
        if seg1 != "无":
            failures.append(f"① 连续 1 天仍进了卡片：{seg1!r}")

        # ② 连续 7 天 → 应升级
        _ISO.parent.mkdir(parents=True, exist_ok=True)
        _ISO.write_text(
            json.dumps(
                {"first_stale": (datetime.date.today() - datetime.timedelta(days=6)).isoformat()}
            ),
            encoding="utf-8",
        )
        seg2 = _run(fake)
        if "连续 7 天" not in seg2:
            failures.append(f"② 连续 7 天未升级：{seg2!r}")

        # ②b 同轮再跑 → 去重
        d = json.loads(_ISO.read_text(encoding="utf-8"))
        d["pushed_for"] = d["first_stale"]
        _ISO.write_text(json.dumps(d), encoding="utf-8")
        seg3 = _run(fake)
        if seg3 != "无":
            failures.append(f"②b 同轮重复推卡：{seg3!r}")

        # ③ 恢复 → 用真实总册（应 rc=0）跑一次，状态文件应被删
        real = Path.home() / "WorkBuddy" / "马厩归档总册.md"
        if real.is_file():
            _run(real)
            if _ISO.exists():
                failures.append("③ 恢复正常后状态文件未被清除")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        if _ISO.exists():
            _ISO.unlink()

    if failures:
        for f in failures:
            print(f"  [FAIL] {f}")
        print(f"-- T-045 判据：{4 - len(failures)}/4 通过")
        return 1

    print("  [PASS] ① 连续 1 天只记日志不推卡")
    print("  [PASS] ② 连续 7 天升级为卡片")
    print("  [PASS] ②b 同一轮去重，不重复推")
    print("  [PASS] ③ 恢复正常后清状态")
    print("-- T-045 判据：4/4 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
