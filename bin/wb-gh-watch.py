#!/Users/guan/.workbuddy/binaries/python/envs/default/bin/python3
"""
wb-gh-watch.py — GitHub 事件源（router v0 扩展源 B / #1+#5，2026-11-10 全开授权）
判据真源：工作区 扩展实施总纲-20261110.md §四·B。

职责（只观察，不处置）：
  每 30 分钟扫白名单仓库近 WINDOW_MIN 分钟内**收尾**（updatedAt）且
  conclusion=failure 的 workflow runs：
    → 去重（run_id 幂等 + 同 repo 24h 推送抑制）
    → 追加 ~/.workbuddy/events/events.jsonl（source=github, handled_by:null）
    → 推送经 push_card.py（白名单：仅 CI 失败事件）
  持续 red 是常态而非新事件：同 repo 24h 只推一次，事件照落盘供巡检消费。

设计依据（勿删）：
  · gh 在 /opt/homebrew/bin（launchd PATH 必须含它，wb-liveness 先例）；
    认证走 keyring（env -i 实测可用），凭据不入库、脚本不含 token。
  · 窗口按 updatedAt（run 收尾时刻）过滤，不按 createdAt——run 可能跑很久，
    按 createdAt 会漏长 run（同 poller 的 created_at 教训，2026-11-03 实测）。
  · TCC：放行 python + 子进程继承（先例 wb-event-poller.py / wb-job-watch.py）。
  · 事件行格式与 poller 对齐（巡检 prompt 第 0 步消费全队列，无需改巡检）。

退出码：0 正常（含无事发生）/ 1 运行出错 / 2 单仓库查询失败（降级继续其余仓库）
配置：~/.local/etc/wb-gh-watch.conf（KEY=VALUE：REPOS=逗号分隔、DRY_RUN=1、
      WINDOW_MIN=扫描窗口分钟数，默认 40；调大可回溯验证扫描链路）
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path(os.environ.get("HOME", "/Users/guan"))
CONF = HOME / ".local/etc/wb-gh-watch.conf"
EVENTS_DIR = HOME / ".workbuddy/events"
EVENTS_FILE = EVENTS_DIR / "events.jsonl"
GH_BIN = "/opt/homebrew/bin/gh"
PUSH_CARD = HOME / "WorkBuddy/Claw/.workbuddy/scripts/push_card.py"
PY_BIN = HOME / ".workbuddy/binaries/python/envs/default/bin/python"
WINDOW_MIN = 40  # 30min 轮询 ×1.3 余量（按 updatedAt）
GH_TIMEOUT = 60
PUSH_SUPPRESS_H = 24
MAX_EVENTS_PER_RUN = 20  # 单轮熔断（防平台故障期风暴）
# 单轮「详细卡」上限。抑制粒度细化到 repo/workflow 后，6 仓 22 个活跃 workflow
# 在平台故障日最坏一轮推 20+ 张卡（旧实现按 repo 天然上限 6 张）→ 必须限流。
# 超出部分仍全部入队不丢，改由一张汇总卡通知。
MAX_PUSH_PER_RUN = 5
SUMMARY_LABEL_LIMIT = 8  # 汇总卡里最多列几个仓库名（其余只报数量）
DEFAULT_REPOS = [
    "guandada123/Claw",
    "guandada123/ai-autonomy-team",
    "guandada123/workbuddy-user-memory",
    "guandada123/QuantTradingSystem",
    "guandada123/project-monitor-fusion",
    "guandada123/StockInsight",
]


def load_conf():
    cfg = {}
    if CONF.exists():
        for raw in CONF.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip()
    return cfg


def log(msg):
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_DIR / "gh-watch.log", "a") as f:
        f.write(f"[{datetime.now():%F %T}] {msg}\n")


# ── 事件文件状态（与 poller 同模式） ──────────────────────
def existing_keys(events_file):
    if not events_file.exists():
        return set()
    out = set()
    for line in events_file.read_text().splitlines():
        try:
            k = json.loads(line).get("dedupe_key", "")
            if k.startswith("ghci:"):
                out.add(k)
        except (json.JSONDecodeError, KeyError):
            continue  # 损坏行跳过（JSONL 容错）
    return out


def last_push_by_key(events_file):
    """按 repo/workflow 取最近一次成功推送时刻。

    2026-11-19 修（审计 P1-3）：原按 repo 抑制，同仓出现**新的、不同 workflow** 的失败时
    24h 内不推卡，等于静默漏报；改为 repo/workflow 粒度。
    兼容旧记录：旧事件无 workflow 维度时退回 repo 作键（`subject` 一直是 `repo/wf`）。
    """
    out = {}
    if not events_file.exists():
        return out
    for line in events_file.read_text().splitlines():
        try:
            e = json.loads(line)
            # 2026-11-19：overflow（被限流、只发了汇总卡）也必须计入，
            # 否则下一轮（30min 后）它们又成候选 → 变成周期性汇总卡噪音。
            if e.get("source") == "github" and (e.get("pushed") or e.get("notified") == "overflow"):
                key = e.get("subject") or e.get("repo")
                if key and (key not in out or e["ts"] > out[key]):
                    out[key] = e["ts"]
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def should_suppress(prev_ts, now, hours):
    """上次推送距今是否在抑制窗口内。prev_ts 为空/坏值 → 不抑制。

    纯函数，便于 fixture 断言边界（正好 24h、缺时区、畸形字符串）。
    """
    if not prev_ts:
        return False
    try:
        prev_dt = datetime.fromisoformat(prev_ts)
    except (ValueError, TypeError):
        return False
    now_dt = datetime.now(prev_dt.tzinfo) if prev_dt.tzinfo else now
    return (now_dt - prev_dt).total_seconds() < hours * 3600


def apply_overflow(candidates, overflow_idx, summary_ok, last_push, note):
    """按汇总卡是否发送成功，决定溢出事件的标记与抑制状态。返回已通知条数。

    🔴 2026-11-19 自查修复（本仓 AI 审查对本文件的 high 发现）：
    原实现无条件写 last_push 并标 notified=overflow —— 汇总卡发送失败时，
    这 N 条会被 24h 静默，真实失败被永久吞掉。
    正确语义：只有汇总卡真发出去了才算「已通知」；失败则标 overflow_failed，
    不写 last_push（不抑制），事件仍入队由巡检消费。
    """
    marked = 0
    for i in overflow_idx:
        c = candidates[i]
        if summary_ok:
            c["ev"]["notified"] = "overflow"
            c["ev"]["notified_note"] = note
            last_push[c["suppress_key"]] = c["ev"]["ts"]
            marked += 1
        else:
            c["ev"]["notified"] = "overflow_failed"
            c["ev"]["notified_note"] = "汇总卡发送失败，未通知；事件仍入队待巡检消费"
    return marked


def plan_pushes(candidates, limit):
    """把候选分成「本轮推详细卡」与「溢出」两组，返回 (push_idx, overflow_idx)。

    candidates: [{"suppress": bool}, ...]
    被抑制的不占名额（它们本来就不推），只有未抑制的才参与截断。
    纯函数：不推卡、不改事件，只决定分组 —— 否则限流逻辑无法被单测覆盖。
    """
    pending = [i for i, c in enumerate(candidates) if not c.get("suppress")]
    return pending[:limit], pending[limit:]


# ── 过滤逻辑（纯函数，fixture 可测） ──────────────────────
def filter_failed_runs(runs_json_text: str, window_min: int, now_utc=None):
    """从 gh run list JSON 过滤：conclusion=failure 且 updatedAt 在窗口内。
    返回 [(run_id, workflow_name, display_title, updated_at, url)]。"""
    now = now_utc or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_min)
    out = []
    try:
        runs = json.loads(runs_json_text)
    except json.JSONDecodeError:
        return None  # 解析失败 → 调用方按仓库级失败处理
    for r in runs:
        if r.get("conclusion") != "failure":
            continue
        upd = str(r.get("updatedAt", ""))
        if not upd:
            continue
        try:
            t = datetime.fromisoformat(upd.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t >= cutoff:
            out.append(
                (
                    r.get("databaseId"),
                    r.get("workflowName", ""),
                    r.get("displayTitle", ""),
                    upd,
                    r.get("url", ""),
                )
            )
    return out


def gh_call(repo):
    cmd = [
        GH_BIN,
        "run",
        "list",
        "-R",
        repo,
        "--limit",
        "30",
        "--json",
        "databaseId,displayTitle,conclusion,createdAt,updatedAt,workflowName,url",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=GH_TIMEOUT)
    if r.returncode != 0:
        return None
    return r.stdout


# ── 推送（委托 push_card，同 poller 模式） ─────────────────
def safe_dedupe_key(key: str) -> str:
    """🔴 2026-11-13 缺陷修复：push_card.py 的 dedupe 文件路径是
    /tmp/feishu_card_dedupe_{key}，key 含 '/' 会生成不存在的子目录路径
    → open() 抛异常 → 卡片已发出但进程 rc=1，推送被记失败、24h 抑制失效。
    ghci key 形如 ghci:guandada123/Claw:12345，必须先清掉路径敏感字符。"""
    return key.replace("/", "-").replace(":", "-").replace(" ", "_")


def push_card(title, body, dedupe_key, dry):
    dedupe_key = safe_dedupe_key(dedupe_key)
    if dry:
        log(f"[DRY-RUN] 待推送: {title} | key={dedupe_key}")
        return True
    if not (PY_BIN.exists() and PUSH_CARD.exists()):
        log(f"推送通路不可用（PY_BIN={PY_BIN.exists()} push_card={PUSH_CARD.exists()}）→ 仅落盘")
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
            log(f"push_card rc={r.returncode} out={(r.stdout or r.stderr or '')[-300:]}")
        return r.returncode == 0
    except Exception as e:
        log(f"push_card 异常: {e}")
        return False


# ── 主流程 ────────────────────────────────────────────────
def main():
    cfg = load_conf()
    dry = cfg.get("DRY_RUN", "0") == "1" or "--dry-run" in sys.argv
    window = int(cfg.get("WINDOW_MIN", WINDOW_MIN))
    repos = [x.strip() for x in cfg.get("REPOS", "").split(",") if x.strip()] or DEFAULT_REPOS

    if not gh_bin_exists():
        log(f"gh 不存在：{GH_BIN} → 退出")
        return 2

    seen = existing_keys(EVENTS_FILE)
    last_push = last_push_by_key(EVENTS_FILE)
    now_utc = datetime.now(timezone.utc)
    now_s = now_utc.astimezone().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    new_lines, pushed, failed_repos = [], 0, 0
    cands = []  # 候选推送（跨仓库统一排序后限流，否则每仓各自截断=形同虚设）

    for repo in repos:
        if len(cands) >= MAX_EVENTS_PER_RUN:
            log(f"单轮达 {MAX_EVENTS_PER_RUN} 条 → 停扫剩余仓库")
            break
        raw = gh_call(repo)
        if raw is None:
            failed_repos += 1
            log(f"{repo}: gh 查询失败 → 跳过（降级继续）")
            continue
        hits = filter_failed_runs(raw, window, now_utc)
        if hits is None:
            failed_repos += 1
            log(f"{repo}: 返回非 JSON → 跳过")
            continue
        for run_id, wf, title, upd, url in hits:
            key = f"ghci:{repo}:{run_id}"
            if key in seen:
                continue
            suppress_key = f"{repo}/{wf}"
            ev = {
                "ts": now_s,
                "source": "github",
                "type": "ci.failed",
                "subject": f"{repo}/{wf}",
                "repo": repo,
                "run_id": run_id,
                "summary": title,
                "updated_at": upd,
                "url": url,
                "dedupe_key": key,
                "handled_by": None,
                "pushed": False,
            }
            cands.append(
                {
                    "ev": ev,
                    "suppress": should_suppress(
                        last_push.get(suppress_key), datetime.now(), PUSH_SUPPRESS_H
                    ),
                    "suppress_key": suppress_key,
                    "label": f"{repo}/{wf}",
                    "title": f"🔴 CI 失败：{repo} · {wf}",
                    "body": f"**run**: {title}\n**收尾**: {upd}\nthread: `{key}`",
                    "key": key,
                }
            )

    push_idx, overflow_idx = plan_pushes(cands, MAX_PUSH_PER_RUN)
    for i in push_idx:
        c = cands[i]
        ok = push_card(c["title"], c["body"], c["key"], dry)
        c["ev"]["pushed"] = ok
        if ok:
            pushed += 1
            last_push[c["suppress_key"]] = c["ev"]["ts"]

    if overflow_idx:
        labels = "、".join(cands[i]["label"] for i in overflow_idx[:SUMMARY_LABEL_LIMIT])
        tail = ""
        if len(overflow_idx) > SUMMARY_LABEL_LIMIT:
            tail = f" 等 {len(overflow_idx)} 个"
        # 不打 pushed=True（那是假的：没发详细卡），改用 notified 表达「已由汇总卡通知」。
        # 但必须先确认汇总卡真的发出去了，否则不能抑制（见 apply_overflow 注释）。
        ok_sum = push_card(
            f"🔴 CI 失败：另有 {len(overflow_idx)} 个仓库/流程",
            f"超单轮详细卡上限（{MAX_PUSH_PER_RUN}），已全部入队待巡检消费：\n{labels}{tail}",
            f"ghci-summary:{now_s[:10]}",
            dry,
        )
        if not ok_sum:
            log(f"🔴 汇总卡发送失败：{len(overflow_idx)} 条溢出事件未通知（已入队，等巡检消费）")
        apply_overflow(
            cands,
            overflow_idx,
            ok_sum,
            last_push,
            f"超单轮详细卡上限 {MAX_PUSH_PER_RUN}，并入汇总卡；24h 内不再单独推",
        )

    for c in cands:
        new_lines.append(json.dumps(c["ev"], ensure_ascii=False))

    if new_lines:
        # 🔴 dry-run 禁止落盘生产事件文件（2026-11-10 实测踩坑：dry 回溯验证把
        # 14 条 14 天窗口的历史失败写进了真队列，巡检会被噪音消费；
        # poller 的 dry 不落盘是靠 WB_EVENT_DIR fixture 隔离的，本脚本
        # 没有 fixture 目录机制 → dry 时必须显式跳过落盘）
        if dry:
            log(f"[DRY-RUN] 命中 {len(new_lines)} 条（不落盘不推送）")
        else:
            with open(EVENTS_FILE, "a") as f:
                f.write("\n".join(new_lines) + "\n")
            log(f"落盘 {len(new_lines)} 条 CI 失败事件，推送 {pushed} 条")
    if failed_repos:
        log(f"{failed_repos}/{len(repos)} 仓库查询失败（降级）")
        return 2
    return 0


def gh_bin_exists():
    return Path(GH_BIN).exists()


if __name__ == "__main__":
    sys.exit(main())
