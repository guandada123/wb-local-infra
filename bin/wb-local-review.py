#!/usr/bin/env python3
"""本机 AI 审查 shadow（ai-review 方案 B 回退版，2026-11-14）

背景：原 GitHub Actions 版把 DEEPSEEK_API_KEY 放进 GitHub Secrets（凭据外移），
与方案审计 §二 P2-1「不动 CI、不加 Secrets、零凭据外移」的定案相反；且 schedule
被平台延迟 6.6h（同仓 n=20 中位）。本脚本按 11-02 修正方案实现：

- 本机 launchd 定时（21:00 本地，无平台排队延迟）
- 扫近 N 小时提交的 diff（默认 24h，截断 400 行）
- 调 DeepSeek 直连（key 只在本机文件，零凭据外移、零 CI 成本）
- 结果写内盘 ~/.workbuddy/ai-review/<date>.md，只报告不阻塞
- 有 high/med 才推飞书卡片，无问题静默（沿「全绿静默」惯例）

判据（总纲 §四·E「判据勘误与重写」，11-27 生效）：发现数 / 测试没拦住比例 /
≥3 条真实问题；真实问题由人工判定，不由写代码方自评。

用法：wb-local-review.py [--dry-run] [--since-hours 24] [--max-lines 400]
退出码：0 正常（含静默）/ 1 出错 / 2 无变更
"""

import contextlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HOME = Path.home()
CLAW = HOME / "WorkBuddy" / "Claw"
OUT_DIR = HOME / ".workbuddy" / "ai-review"
STATE = OUT_DIR / ".state.json"
# 2026-11-19（审计 P0-2）：评估原始数据原本只有本机单副本，镜像到 Claw 仓内。
# 🔴 必须落成「恒定已跟踪 + 白名单扩展名」的两个文件，不能逐文件复制：
#   1) .jsonl 不在自动提交白名单（只认 .json/.md）→ 永远进不了远端；
#   2) 每天新生成的 YYYY-MM-DD.md 是未跟踪新文件 → 白名单判据 1 仍判 B 类。
MIRROR_DIR = CLAW / ".workbuddy" / "data" / "eval" / "ai-review"
MIRROR_FINDINGS = "findings.json"  # findings.jsonl 的合并版（全量重建）
MIRROR_REPORTS = "reports.md"  # 全部日报告的合并版（全量重建）
# 结构化落盘：11-27 评估要能机器统计（md 只能人工读）。每次审查追加一行。
FINDINGS_LOG = OUT_DIR / "findings.jsonl"
KEY_FILE = HOME / ".workbuddy" / "auth" / "deepseek-key.sh"
PUSH_CARD = CLAW / ".workbuddy" / "scripts" / "push_card.py"
PY_BIN = HOME / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "bin" / "python3"
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"
DEFAULT_HOURS = 24
DEFAULT_MAX_LINES = 400
# 只审代码类文件：.autopilot/*.md、docs/、.learnings/、output/ 等会吃掉全部行数预算
# （2026-11-17 实测：前 400 行全是 HANDOFF/QUEUE/chat-*.md，一行代码没审到 → 假绿）
CODE_SUFFIXES = {
    ".py",
    ".sh",
    ".bash",
    ".zsh",
    ".yml",
    ".yaml",
    ".toml",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".sql",
    ".cfg",
    ".ini",
}
CODE_NAMES = {"Dockerfile", "Makefile"}
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
MIN_SAMPLE_FOR_STATS = 5
MIN_PARTS = 3  # 一行发现至少三段：位置 | 严重度 | 理由
# 2026-11-14 实测：模型会把自我否决写在条目的理由里（「…故实际风险低——不报」「此条撤回」），
# 仅按格式行解析会收进假阳性。命中这些标记的条目视为模型已自行否决。
REPEAT_THRESHOLD = 2  # 同一位置出现 ≥2 次视为可复现信号
# 无效采样标记：截断预算被文档占满、一行代码没审到的 run，不算有效审查样本
SAMPLING_INVALID = "invalid_no_code"
# 自我否决标记：模型仍会在理由里写「此条不成立/跳过」这类撤回语（实测 2026-11-19
# 出现「此条不成立，跳过」未被拦下 → 假阳性入库）。宁可多拦，这些词不可能出现在
# 真实缺陷的理由里。
REVOKE_MARKERS = (
    "撤回",
    "不报",
    "无实际",
    "风险低",
    "属误判",
    "实际不存在",
    "不成立",
    "跳过",
    "无碍",
)

SYSTEM_PROMPT = """你是严格的代码审查员，只读 diff，只报**真会出错**的问题。

规则：
- 只报会导致运行错误、数据损坏、逻辑错误、安全问题、资源泄漏的问题
- 不报风格、命名、注释、格式、可选优化
- **不确定的不报**：不要输出「需确认」「若…则可能」这类假设性条目；宁可漏报
- **只输出最终结论行**：不要输出分析过程，不要输出被你否决的条目（先列后否=错）
- **不要对未完整展示的代码下判断**：diff 已截断，凡因截断看不清的直接跳过（不要报「文件被截断」「无法确认后续」）
- 逐条输出：文件名:行号 | 严重度(high/med/low) | 一句话理由
- 最多 10 条；按严重度排序
- 没有真问题就只输出：无问题（有真问题时不得出现「无问题」字样）"""


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def read_key() -> str:
    """从本机 key 文件解析（不执行脚本，避免副作用）。"""
    text = KEY_FILE.read_text()
    m = re.search(r"DEEPSEEK_API_KEY\s*=\s*[\"']?([A-Za-z0-9_\-]+)", text)
    return m.group(1) if m else ""


def git_patch(hours: int) -> tuple:
    """返回 (patch, commits)。无提交时 patch 为空串。"""
    since = f"{hours} hours ago"
    commits = subprocess.run(
        ["git", "-C", str(CLAW), "log", f"--since={since}", "--oneline"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if commits.returncode != 0:
        raise RuntimeError(f"git log 失败: {commits.stderr.strip()[:200]}")
    lines = [ln for ln in commits.stdout.splitlines() if ln.strip()]
    if not lines:
        return "", 0
    patch = subprocess.run(
        ["git", "-C", str(CLAW), "log", f"--since={since}", "-p", "--unified=3"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if patch.returncode != 0:
        raise RuntimeError(f"git diff 失败: {patch.stderr.strip()[:200]}")
    return patch.stdout, len(lines)


def is_code_path(path: str) -> bool:
    """代码类文件判定：后缀在白名单或文件名在白名单。"""
    name = path.rsplit("/", 1)[-1]
    if name in CODE_NAMES:
        return True
    return Path(name).suffix.lower() in CODE_SUFFIXES


def filter_patch(patch: str) -> tuple:
    """按文件切块，只保留代码类文件的 diff 块。返回 (text, kept, skipped)。"""
    chunks: list = []
    cur: list = []
    for ln in patch.splitlines():
        if ln.startswith("diff --git "):
            if cur:
                chunks.append(cur)
            cur = [ln]
        elif cur:
            cur.append(ln)
    if cur:
        chunks.append(cur)

    kept_text, kept, skipped = [], 0, 0
    for ch in chunks:
        m = _DIFF_GIT_RE.match(ch[0])
        path = m.group(2) if m else ""
        if path and is_code_path(path):
            kept_text.append("\n".join(ch))
            kept += 1
        else:
            skipped += 1
    return "\n".join(kept_text), kept, skipped


def truncate(patch: str, max_lines: int) -> tuple:
    """返回 (text, capped, total_lines)。"""
    lines = patch.splitlines()
    total = len(lines)
    if total <= max_lines:
        return patch, False, total
    return "\n".join(lines[:max_lines]), True, total


def build_messages(diff_text: str, meta: str) -> list:
    user = (
        f"仓库 Claw，近 24h 变更概览：{meta}\n\n"
        f"以下是 diff（可能已截断）：\n```diff\n{diff_text}\n```"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def call_llm(key: str, messages: list, timeout: int = 120) -> str:
    body = json.dumps(
        {"model": MODEL, "messages": messages, "temperature": 0, "max_tokens": 1200},
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(  # noqa: S310 —— 固定 https 常量 URL，无用户可控输入
        API_URL,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def parse_findings(text: str) -> list:
    """解析 '文件:行 | 严重度 | 理由' 行。

    2026-11-14 实测缺陷：模型可能先列条目再自我否决（输出条目 + 「…不报」+「无问题」），
    只按格式行解析会产出假阳性并推卡。规则：
    - 只要存在**独立成行**的「无问题」（去标点后），即判为 0 条
    - 否则按格式行解析
    """
    if not text:
        return []
    for ln in text.splitlines():
        if ln.strip().strip("。.:：") == "无问题":
            return []
    out = []
    for ln in text.splitlines():
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) < MIN_PARTS:
            continue
        sev = parts[1].lower()
        if sev not in ("high", "med", "medium", "low"):
            continue
        reason = parts[2]
        if any(m in reason for m in REVOKE_MARKERS):
            continue
        out.append({"loc": parts[0], "sev": sev[:3], "reason": reason})
    return out


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def should_skip(state: dict, head: str, day: str) -> bool:
    return state.get("head") == head and state.get("day") == day


def atomic_write_text(path: Path, text: str) -> None:
    """原子写：先写 .tmp 再 os.replace。

    避免 23:50 批量提交读到半截文件（write_bytes 是先截断后写）。
    .tmp 后缀不在自动提交白名单 → 天然落 B 类，不会被误提交。
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        # 失败路径也要清掉 .tmp，否则会在仓内累积（虽不在白名单，但会污染工作区）
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def rebuild_findings_json(jsonl_text: str) -> tuple:
    """findings.jsonl → 合并 JSON 数组文本。返回 (text, 记录数, 坏行数)。

    纯函数（不做 IO），便于 fixture 断言。坏行跳过并计数，不因一行坏了丢全部。
    """
    rows, bad = [], 0
    for line in jsonl_text.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    return json.dumps(rows, ensure_ascii=False, indent=1) + "\n", len(rows), bad


def rebuild_reports(items: list) -> tuple:
    """多份日报告 → 单一 reports.md。返回 (text, 天数)。

    items: [(文件名, 内容)]，按文件名排序（YYYY-MM-DD.md 天然按日期）。
    全量重建而非追加：同一天可能跑多次（实测 11-14/11-17 各 2 次），
    追加会产生重复段落。
    """
    parts = []
    for name, body in sorted(items):
        parts.append(f"<!-- {name} -->\n\n{body.rstrip()}\n")
    return "\n---\n\n".join(parts), len(parts)


def mirror_eval(src_dir: Path, dst_dir: Path) -> dict:
    """把评估数据整理成两个恒定文件镜像进仓。返回 {ok, findings, reports, bad_lines, error}。

    失败必须可见：写 mirror-error.txt 并返回 ok=False（调用方据此告警）。
    2026-11-19 首版只 log 一行就宣称「已修」，是同一类「假保障」的第二次复发。
    """
    res = {"ok": False, "findings": 0, "reports": 0, "bad_lines": 0, "error": ""}
    if not src_dir.exists():
        res["error"] = "源目录不存在"
        return res
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        jsonl = src_dir / "findings.jsonl"
        ftext, n_f, n_bad = rebuild_findings_json(jsonl.read_text() if jsonl.exists() else "")
        atomic_write_text(dst_dir / MIRROR_FINDINGS, ftext)
        items = [(q.name, q.read_text()) for q in sorted(src_dir.glob("*.md"))]
        rtext, n_r = rebuild_reports(items)
        atomic_write_text(dst_dir / MIRROR_REPORTS, rtext)
        err = dst_dir / "mirror-error.txt"
        if err.exists():
            err.unlink()
        res.update(ok=True, findings=n_f, reports=n_r, bad_lines=n_bad)
    except OSError as e:
        res["error"] = str(e)[:160]
        with contextlib.suppress(OSError):
            (dst_dir / "mirror-error.txt").write_text(
                f"{datetime.now().isoformat()} 镜像失败: {res['error']}\n"
                "含义：11-27 评估数据的远端副本未更新，仓内可能是旧快照。\n"
            )
    return res


def append_record(record: dict) -> None:
    """追加一行结构化记录（11-27 评估可机器统计，不必解析 md）。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(FINDINGS_LOG, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_records() -> list:
    if not FINDINGS_LOG.exists():
        return []
    out = []
    for ln in FINDINGS_LOG.read_text().splitlines():
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def compute_stats(rows: list) -> dict:
    """汇总：run 次数、有效自然日、发现总数、按严重度、跨次复现的位置。

    复现口径＝同一 loc 出现在 **≥2 个不同 run** 里（这才是「真问题可复现」的信号）；
    同一次审查内同一文件的多条发现不构成复现（2026-11-14 实测踩坑：4 条同文件被误判 4×）。
    """
    by_sev = {"hig": 0, "med": 0, "low": 0}
    loc_runs: dict = {}
    for i, r in enumerate(rows):
        for f in r.get("findings", []):
            sev = f.get("sev", "")
            if sev in by_sev:
                by_sev[sev] += 1
            loc_runs.setdefault(f.get("loc", ""), set()).add(i)
    valid = [r for r in rows if r.get("sampling") != SAMPLING_INVALID]
    invalid = [r for r in rows if r.get("sampling") == SAMPLING_INVALID]
    return {
        "runs": len(rows),
        # 有效天数只统计「真的审到代码」的 run（2026-11-18 修：此前把未审代码的 run 也计入）
        "active_days": len({r.get("date", "") for r in valid if r.get("date")}),
        "invalid_runs": len(invalid),
        "invalid_run_dates": sorted({r.get("date", "") for r in invalid if r.get("date")}),
        "total_findings": sum(len(r.get("findings", [])) for r in rows),
        "by_sev": by_sev,
        "distinct_locs": len(loc_runs),
        "repeated_locs": {k: len(v) for k, v in loc_runs.items() if len(v) >= REPEAT_THRESHOLD},
    }


def push(title: str, body: str, key: str) -> bool:
    if not (PY_BIN.exists() and PUSH_CARD.exists()):
        log("推送通路不可用 → 仅落盘")
        return False
    r = subprocess.run(
        [
            str(PY_BIN),
            str(PUSH_CARD),
            "--title",
            title,
            "--level",
            "alert",
            "--section",
            "审查结果",
            body,
            "--dedupe-key",
            key,
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if r.returncode != 0:
        log(f"push_card rc={r.returncode} {(r.stdout or r.stderr)[-200:]}")
    return r.returncode == 0


def main() -> int:
    dry = "--dry-run" in sys.argv
    no_push = "--no-push" in sys.argv

    # --stats：读结构化记录出汇总，不调 LLM、不推送
    if "--stats" in sys.argv:
        st = compute_stats(load_records())
        log(
            f"审查记录 {st['runs']} 次（有效天数 {st['active_days']}）｜发现 {st['total_findings']} 条 {st['by_sev']}"
        )
        if st.get("invalid_runs"):
            log(
                f"⚠️ 另有 {st['invalid_runs']} 次无效采样（未审到代码）已排除，涉及日期 {st['invalid_run_dates']}（该日可能另有有效 run）"
            )
        log(f"唯一位置 {st['distinct_locs']} 个｜重复出现(≥2 次) {len(st['repeated_locs'])} 个")
        for loc, n in st["repeated_locs"].items():
            log(f"  {n}× {loc}")
        # 样本量按**自然日**计：同一天因 HEAD 变化重审属同一批 diff 重复采样，不构成独立样本。
        if st["active_days"] < MIN_SAMPLE_FOR_STATS:
            log(
                f"⚠️ 有效审查天数 {st['active_days']} < {MIN_SAMPLE_FOR_STATS} 天，按判据不出统计结论"
            )
        return 0

    hours = DEFAULT_HOURS
    max_lines = DEFAULT_MAX_LINES
    for i, a in enumerate(sys.argv):
        if a == "--since-hours" and i + 1 < len(sys.argv):
            hours = int(sys.argv[i + 1])
        if a == "--max-lines" and i + 1 < len(sys.argv):
            max_lines = int(sys.argv[i + 1])

    head = subprocess.run(
        ["git", "-C", str(CLAW), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    day = datetime.now().strftime("%Y-%m-%d")

    if not dry and should_skip(load_state(), head, day):
        log(f"同日同 HEAD({head}) 已审 → 跳过")
        return 0

    patch, n_commits = git_patch(hours)
    if n_commits == 0:
        log(f"近 {hours}h 无提交 → 无变更")
        return 2

    code_patch, kept_files, skipped_files = filter_patch(patch)
    if not code_patch:
        # 无代码变更：明确写「未审代码」，绝不能用「无问题」（假绿）
        log(
            f"近 {hours}h 有 {n_commits} 个提交，但无代码变更（跳过 {skipped_files} 个文档/数据文件）"
        )
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{day}.md").write_text(
            f"# AI 审查 {day}\n\n"
            f"**状态**：无代码变更 —— {n_commits} 个提交，跳过 {skipped_files} 个文档/数据文件\n\n"
            "本次**未调用模型**。注意：这不等于「无问题」，只是本次没有代码可审。\n"
        )
        return 0

    diff_text, capped, total = truncate(code_patch, max_lines)
    meta = (
        f"{n_commits} 个提交｜代码文件 {kept_files} 个"
        f"（跳过 {skipped_files} 个文档/数据）｜代码 diff {total} 行"
        + ("（已截断）" if capped else "")
    )
    log(meta)

    key = read_key()
    if not key:
        log("key 读取失败 → 退出")
        return 1

    t0 = time.time()
    try:
        answer = call_llm(key, build_messages(diff_text, meta))
    except Exception as e:  # noqa: BLE001 —— 网络/配额异常一律 fail-safe 落盘
        log(f"LLM 调用失败: {str(e)[:200]}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{day}.md").write_text(
            f"# AI 审查 {day}\n\n**状态**：调用失败\n\n```\n{str(e)[:800]}\n```\n"
        )
        return 1

    findings = parse_findings(answer)
    report = [
        f"# AI 审查 {day}",
        "",
        f"- 范围：近 {hours}h，{meta}",
        f"- 采样：只审代码类文件；已跳过 {skipped_files} 个文档/数据文件（避免 .autopilot/ 等吞掉行数预算）",
        f"- 发现：{len(findings)} 条" + ("" if findings else "（无问题）"),
        "- 注：结论仅对被审查子集成立，不冒充全量",
        "- 🔴 **以下条目需人工判定真伪**：实测同 diff 三次跑分别 5/1/3 条，假阳性随机、真问题可复现",
        "",
        "---",
        "",
        answer,
        "",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUT_DIR / f"{day}.md"
    report_path.write_text("\n".join(report))
    log(f"落盘 {report_path}（发现 {len(findings)} 条）")

    if not dry:
        append_record(
            {
                "date": day,
                "head": head,
                "commits": n_commits,
                "diff_lines": total,
                "code_files": kept_files,
                "skipped_files": skipped_files,
                "sampling": "valid",
                "capped": capped,
                "findings": findings,
                "model": MODEL,
                "elapsed_s": round(time.time() - t0, 1),
                "ts": datetime.now().isoformat(),
            }
        )

    if not dry:
        # 必须放在 append_record 之后：否则镜像的是上一轮 findings.jsonl，永远少当天一条
        mr = mirror_eval(OUT_DIR, MIRROR_DIR)
        if mr["ok"]:
            log(
                f"镜像 {MIRROR_FINDINGS} {mr['findings']} 条 + {MIRROR_REPORTS} "
                f"{mr['reports']} 天 → {MIRROR_DIR}"
            )
            if mr["bad_lines"]:
                log(f"⚠️ 镜像时跳过 {mr['bad_lines']} 行坏 JSON（其余已镜像）")
        else:
            log(f"🔴 镜像失败（远端评估数据未更新）: {mr['error']}")
            push(
                "🔴 AI 审查数据镜像失败",
                f"原因：{mr['error']}\n影响：11-27 评估的**远端副本**未更新，仓内可能是旧快照",
                "ai-review:mirror-error",
            )

    if findings and not no_push:
        sev_rank = {"hig": 0, "med": 1, "low": 2}
        top = sorted(findings, key=lambda x: sev_rank.get(x["sev"], 9))[:5]
        body = "\n".join(f"- **{f['sev']}** {f['loc']} — {f['reason']}" for f in top)
        if dry:
            log(f"[DRY-RUN] 待推送 {len(findings)} 条")
        else:
            push(f"🔍 AI 审查发现 {len(findings)} 条（{day}）", body, f"ai-review:{day}:{head}")

    if not dry:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        STATE.write_text(
            json.dumps(
                {
                    "head": head,
                    "day": day,
                    "findings": len(findings),
                    "ts": datetime.now().isoformat(),
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log(f"未捕获异常: {exc}")
        sys.exit(1)
