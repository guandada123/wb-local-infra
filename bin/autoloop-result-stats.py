#!/usr/bin/python3
"""agent-autoloop 轮次结果统计（2026-11-20，SaResultEnvelope 可观测子集的消费端）。

数据源（均为落盘真源，不解析模型正文）：
  · runs/<run>/exit-1      —— 权威退出码（0=成功，非 0=失败），改造前轮次也有
  · runs/<run>/stderr-1.log —— 尾部 AGENT_RESULT_JSON 标记行（2026-11-20 起），
                               含 ck / rounds / tools / final_chars；缺行 = 改造前轮次
  · runs/<run>/runner-meta.json —— 机器注入的 expected_ck（2026-11-14 起）

口径（结论审计纪律）：
  · 保守口径：全部轮次都计入，rc!=0 或 exit-1 缺失均计失败；
  · 标记口径：仅统计带 AGENT_RESULT_JSON 的轮次（成功率/轮次分布只在该口径下给出）。
    两个口径同时输出，只报好看的那个 = 造假。

用法：
  autoloop-result-stats.py            # 人读摘要（近 limit 轮，默认 30）
  autoloop-result-stats.py --json     # 机器可读（巡检/看板可调）
  autoloop-result-stats.py --self-test
退出码：0=正常（含零样本）｜1=自检失败
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS_DIR = Path.home() / ".agent-autoloop" / "worker" / "runs"
DEFAULT_LIMIT = 30
MARKER = "AGENT_RESULT_JSON "
RUNNING_WINDOW_SEC = 900  # stderr 近 15 分钟内仍活跃且无 exit-1 → 在飞轮次，不计失败
# （铁律：在飞/间隔探针须自检配对——把正在跑的轮次计成失败=口径失真）


def _read_exit(run: Path) -> int | None:
    try:
        return int(run.joinpath("exit-1").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _in_flight(run: Path) -> bool:
    """无 exit-1 且 stderr-1.log 近期仍有写入 → 视为进行中。"""
    try:
        import time

        mtime = run.joinpath("stderr-1.log").stat().st_mtime
        return time.time() - mtime < RUNNING_WINDOW_SEC
    except OSError:
        return False


def _read_marker(run: Path) -> dict | None:
    """标记行恒在 stderr 文件尾（executor 退出前最后写入），只读尾部 64KB 防大日志放大。"""
    try:
        with run.joinpath("stderr-1.log").open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 65536))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    for line in reversed(text.splitlines()):
        if line.startswith(MARKER):
            try:
                d = json.loads(line[len(MARKER) :])
                return d if isinstance(d, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def collect(runs_dir, limit=DEFAULT_LIMIT) -> dict:
    """扫近 limit 轮（按 run 目录名数字排序，新 run 编号更大）。

    返回 dict；目录不存在返回 {"runs": []}，不抛错（fail-safe，统计不该炸巡检）。
    """
    root = Path(runs_dir)
    if not root.is_dir():
        return {"runs": []}
    items = []
    for run in sorted(
        (p for p in root.iterdir() if p.is_dir()),
        key=lambda p: (len(p.name), p.name),
        reverse=True,
    )[: max(1, int(limit))]:
        rc = _read_exit(run)
        marker = _read_marker(run)
        meta_ck = ""
        try:
            meta_ck = str(json.loads(run.joinpath("runner-meta.json").read_text()).get("expected_ck") or "")
        except (OSError, json.JSONDecodeError):
            pass
        running = rc is None and _in_flight(run)
        items.append(
            {
                "run": run.name,
                "rc": rc,
                "ok": rc == 0,
                "running": running,
                "has_marker": marker is not None,
                "ck": (marker or {}).get("ck") or meta_ck,
                "rounds": (marker or {}).get("rounds"),
                "tools": (marker or {}).get("tools"),
                "final_chars": (marker or {}).get("final_chars"),
            }
        )
    n = len(items)
    finished = [x for x in items if not x["running"]]
    marked = [x for x in items if x["has_marker"]]
    # 保守口径：只对已终态轮次计失败；在飞轮次单列，不混进失败（防口径失真）
    cons_ok = sum(1 for x in finished if x["ok"])
    rounds_list = sorted(x["rounds"] for x in marked if isinstance(x["rounds"], int))

    def p(q):
        # 标准 nearest-rank 分位数：ceil(q*n) 名，1-based
        import math

        if not rounds_list:
            return None
        idx = max(0, math.ceil(q * len(rounds_list)) - 1)
        return rounds_list[idx]
    return {
        "runs": items,
        "count": n,
        "running": len(items) - len(finished),
        "marked": len(marked),
        "conservative": {
            "success": cons_ok,
            "fail": len(finished) - cons_ok,
            "rate": round(cons_ok / len(finished), 4) if finished else None,
        },
        "marked_only": {
            "success": sum(1 for x in marked if x["ok"]),
            "fail": sum(1 for x in marked if not x["ok"]),
            "rate": round(sum(1 for x in marked if x["ok"]) / len(marked), 4) if marked else None,
            "rounds_p50": p(0.5),
            "rounds_p90": p(0.9),
        },
    }


def summary(stats: dict, limit=DEFAULT_LIMIT) -> str:
    c, m = stats.get("conservative", {}), stats.get("marked_only", {})
    if not stats.get("count"):
        return "【轮次统计】无 run 目录或零样本"
    lines = [
        "【轮次统计（近 %d 轮）】" % stats["count"],
        "· 保守口径: 成功 %d / 失败 %d（成功率 %s；已终态轮次，rc 缺失计失败）"
        % (c.get("success", 0), c.get("fail", 0), c.get("rate") if c.get("rate") is not None else "N/A"),
    ]
    if stats.get("running"):
        lines.append("· 进行中: %d 轮（无 exit-1 且 stderr 活跃，不计失败）" % stats["running"])
    lines.append(
        "· 标记口径: %d 轮带 AGENT_RESULT_JSON（成功率 %s；rounds p50=%s p90=%s）"
        % (
            stats.get("marked", 0),
            m.get("rate") if m.get("rate") is not None else "N/A",
            m.get("rounds_p50") if m.get("rounds_p50") is not None else "N/A",
            m.get("rounds_p90") if m.get("rounds_p90") is not None else "N/A",
        )
    )
    fails = [x for x in stats["runs"] if not x["ok"] and not x.get("running")][:5]
    if fails:
        lines.append("· 近期失败: " + "；".join("%s rc=%s ck=%s" % (x["run"], x["rc"], x["ck"] or "-") for x in fails))
    return "\n".join(lines)


def self_test() -> int:
    import tempfile

    cases: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 正样本：带标记的成功轮
        r1 = root / "101-1"
        r1.mkdir()
        (r1 / "exit-1").write_text("0\n")
        (r1 / "stderr-1.log").write_text("过程日志\nAGENT_RESULT_JSON {\"ck\":\"manual:chore:T-013\",\"final_chars\":120,\"rc\":0,\"rounds\":4,\"tools\":7}\n")
        (r1 / "runner-meta.json").write_text("{\"expected_ck\":\"manual:chore:T-013\"}")
        # 失败轮（带标记）
        r2 = root / "102-1"
        r2.mkdir()
        (r2 / "exit-1").write_text("1\n")
        (r2 / "stderr-1.log").write_text("AGENT_RESULT_JSON {\"ck\":\"\",\"final_chars\":0,\"rc\":1,\"rounds\":2,\"tools\":1}\n")
        # 改造前轮次：只有 exit-1，无标记；ck 回落 runner-meta（marker 缺失路径）
        r3 = root / "103-1"
        r3.mkdir()
        (r3 / "exit-1").write_text("0\n")
        (r3 / "runner-meta.json").write_text("{\"expected_ck\":\"manual:chore:T-013\"}")
        # rc 缺失轮（保守口径计失败）；runner-meta 损坏 → ck 为空串（不炸）
        r4 = root / "104-1"
        r4.mkdir()
        (r4 / "runner-meta.json").write_text("{corrupt json")
        # 截断的非法 JSON 标记行样本（先建齐 5 轮再 collect，保证排序预期成立）
        r5 = root / "105-1"
        r5.mkdir()
        (r5 / "exit-1").write_text("0\n")
        (r5 / "stderr-1.log").write_text("AGENT_RESULT_JSON {\"ck\": \"截断")
        s = collect(root)
        cases.append(("5 轮全部计入", s["count"] == 5))
        cases.append(("标记轮数正确（2）", s["marked"] == 2))
        cases.append(("保守口径 3 成功 2 失败（rc 缺失计失败）", s["conservative"]["success"] == 3 and s["conservative"]["fail"] == 2))
        cases.append(("标记口径成功率 0.5", s["marked_only"]["rate"] == 0.5))
        cases.append(("标记口径 rounds nearest-rank p50=2 p90=4", s["marked_only"]["rounds_p50"] == 2 and s["marked_only"]["rounds_p90"] == 4))
        cases.append(("改造前轮次 has_marker=False", not s["runs"][2]["has_marker"]))
        cases.append(("marker 缺失时 ck 回落 runner-meta", s["runs"][2]["ck"] == "manual:chore:T-013"))
        cases.append(("runner-meta 损坏不炸（ck 为空串）", s["runs"][1]["ck"] == ""))
        # 反证：截断的非法 JSON 标记行必须判 has_marker=False，不能静默当有效（样本已提前建好）
        s2 = collect(root, limit=1)
        cases.append(("截断标记行判为无标记（不静默吞）", s2["marked"] == 0))
        # 在飞轮次：rc 缺失 + stderr 近期活跃 → running=True，不计失败（反证：旧口径会误报失败）
        r6 = root / "106-1"
        r6.mkdir()
        (r6 / "stderr-1.log").write_text("第 1 轮：1 个工具调用\n")
        s3 = collect(root, limit=1)
        cases.append(
            (
                "在飞轮次判进行中且不计失败",
                s3["running"] == 1
                and s3["conservative"]["fail"] == 0
                and s3["runs"][0]["running"] is True,
            )
        )
        # 陈旧无 rc（stderr 超过窗口）→ 仍按失败计（探针须配对，不能永远豁免）
        import os as _os
        import time as _time

        old = _time.time() - (RUNNING_WINDOW_SEC + 60)
        _os.utime(root / "106-1" / "stderr-1.log", (old, old))
        s4 = collect(root, limit=1)
        cases.append(("超窗陈旧无 rc 仍计失败（在飞豁免不变成永久豁免）", s4["running"] == 0 and s4["conservative"]["fail"] == 1))
        # 空目录 fail-safe
        cases.append(("不存在目录返回空 runs", collect(root / "nope") == {"runs": []}))
        # 排序：105 最新在前
        cases.append(("按编号新→旧排序", s["runs"][0]["run"] == "105-1"))
    for label, ok in cases:
        print("%s %s" % ("[PASS]" if ok else "[FAIL]", label))
    good = all(ok for _, ok in cases)
    print("统计器自检: %s（%d/%d）" % ("OK" if good else "失败", sum(ok for _, ok in cases), len(cases)))
    return 0 if good else 1


def main() -> int:
    args = sys.argv[1:]
    if "--self-test" in args:
        return self_test()
    limit = DEFAULT_LIMIT
    if "--limit" in args:
        i = args.index("--limit")
        if i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass
    stats = collect(RUNS_DIR, limit)
    if "--json" in args:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(summary(stats, limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
