#!/usr/bin/env python3
"""重建 ~/WorkBuddy/_archive/INDEX.md —— 让二进制归档「可检索」。

设计（2026-11-20 审计 P2-9 的判断）：
- 562MB 的二进制归档**不进云端资料库、不进 git**（不可检索、体积大）；
- 但「有哪些归档、什么时候的、能不能再生、怎么恢复」必须可检索 → 索引进仓（本脚本），
  索引产物每次重建（不手工维护，避免过期）。单一真源 = 本脚本 + _archive 实体。
- 天然支持「噪音识别」：重复输出占比 >95% 的归档标为可删，并要求先抽有效部分。

用法：
    python3 archive-index.py            # 重建 _archive/INDEX.md
    python3 archive-index.py --dir X    # 指定归档目录
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

# 处置结论分两张表（2026-11-21 审计 P1-2）：
#   EXACT  —— 精确文件名 → 可以写「这一份的取证事实」（如 356,687 封）；
#   PREFIX —— 前缀 → 只能给通用处置，**不能继承某一份文件的事实**。
# 历史 bug：前缀表里写了「356,687 封中 99.99% 是噪音」，于是任何新建的同类文件
# 都被套上这份事实并建议删除 —— 结论与证据错配，会误导未来的删除决策。
EXACT = {
    "cron-mail-spool-20261012.mbox": (
        "噪音归档",
        "**已核实并已于 2026-11-22 移入废纸篓**（251MB）：原 356,687 封中 99.99% 是两个 watchdog 的重复输出，"
        "有效 38 封已抽出为 `cron-mail-interesting-20261012.mbox`；若再出现同名文件，先确认是否新生成",
        "不可再生",
    ),
    "cron-mail-interesting-20261012.mbox": (
        "邮件存档",
        "保留：从上述噪音 mbox 抽出的 **36 封**有效 cron 输出（2026-11-22 已去重，"
        "原 38 信封含 2 封重复 Message-ID）",
        "不可再生",
    ),
    "XtItClient_x64_国金证券QMT模拟_模拟_2.1.19.0.exe": (
        "安装包",
        "**已于 2026-11-22 移入废纸篓**（237MB）：国金证券官网可重下，本机 macOS 亦无法运行；"
        "若再出现请确认版本",
        "可再生",
    ),
    "workspace-session-dirs-20261120.tgz": (
        "会话归档", "保留：148 个历史会话目录，逐目录 diff 验过", "不可再生",
    ),
}

PREFIX = {
    "cron-mail-spool-": (
        "噪音归档", "同类历史为 watchdog 噪音；**本文件未核实**，删前先抽样统计", "不可再生",
    ),
    "cron-mail-interesting-": ("邮件存档", "保留：抽出的有效 cron 输出", "不可再生"),
    "XtItClient_": ("安装包", "同类可从券商官网重下；**本文件未核实版本**", "可再生"),
    "workspace-session-dirs-": ("会话归档", "保留：历史会话目录归档", "不可再生"),
    "marvis-bridge-final": ("项目归档", "保留：收尾快照（仓已 archived）", "不可再生"),
    "MarvisBridge-runtime": ("运行时归档", "保留", "不可再生"),
    "wechat-download-api.STALE": ("项目归档", "保留：标 STALE，待确认后处理", "不可再生"),
    "MANIFEST-": ("文档", "保留：归档说明", "可再生"),
}


# 目录级登记（目录不逐个文件列，只给处置结论；未登记的一律"见目录内文件"）
DIR_NOTE = {
    "知识库/": (
        "弃用知识库",
        "**已处置 2026-11-22**：2026-06 建的 LLM Wiki，只跑过初始化即停摆（log 仅 1 条）；"
        "5 页中 3 页是他处活文档的旧摘要或已被取代、1 页严重过时，"
        "仅「LLM Wiki 规格」与「Karpathy 模式笔记」为独有资产 → "
        "已抽出到 Claw `.workbuddy/docs/knowledge-wiki/`，原件留此作为历史快照",
        "不可再生",
    ),
    "old_experiments/": ("实验草稿", "保留：2026-07 实验会话目录", "不可再生"),
    "session-backups-20260711/": ("文档归档", "保留：阶段性完成报告", "不可再生"),
}


def classify(name: str) -> tuple[str, str, str]:
    """精确名优先（可带事实），其次前缀（只给通用处置），否则待评估。"""
    if name in EXACT:
        return EXACT[name]
    for prefix, verdict in PREFIX.items():
        if name.startswith(prefix):
            return verdict
    return ("未分类", "**待评估**：未在 EXACT/PREFIX 登记", "未知")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def sha16(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def build(root: Path) -> tuple[str, int, int]:
    rows = []
    for p in sorted(root.iterdir()):
        if p.name == "INDEX.md" or p.name.startswith("."):
            continue
        if p.is_dir():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            key = p.name + "/"
            kind, verdict, rege = DIR_NOTE.get(key, ("目录", "见目录内文件", "—"))
            rows.append((key, size, p.stat().st_mtime, kind, verdict, rege, "—"))
            continue
        kind, verdict, regen = classify(p.name)
        rows.append((p.name, p.stat().st_size, p.stat().st_mtime, kind, verdict, regen, sha16(p)))

    total = sum(r[1] for r in rows)
    lines = [
        "# `~/WorkBuddy/_archive` 归档索引",
        "",
        f"> 由 `wb-local-infra/bin/archive-index.py` 生成 {time.strftime('%Y-%m-%d %H:%M')}｜"
        f"{len(rows)} 项 / **{human(total)}**",
        "> 二进制归档不进云端资料库、不进 git；本索引可检索，产物可随时重建（勿手工编辑）。",
        "",
        "## 处置原则",
        "",
        "| 类别 | 处置 |",
        "|---|---|",
        "| 可再生（官网可重下/脚本可重跑） | 可删，索引留证 |",
        "| 不可再生但已抽索引 | 保留本地，索引可检索 |",
        "| 噪音（重复输出占 95%+） | 抽有效部分后删原件 |",
        "",
        "## 清单",
        "",
        "| 大小 | 名称 | 日期 | 类型 | 处置 | 可再生 | SHA256(前16) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, size, mt, kind, verdict, regen, h in sorted(rows, key=lambda r: -r[1]):
        d = time.strftime("%Y-%m-%d", time.localtime(mt))
        lines.append(f"| {human(size)} | `{name}` | {d} | {kind} | {verdict} | {regen} | `{h}` |")

    deletable = [r for r in rows if "建议删" in r[4]]
    if deletable:
        lines += ["", f"## 建议清理（待确认，共 ~{human(sum(r[1] for r in deletable))}）", ""]
        for i, r in enumerate(sorted(deletable, key=lambda x: -x[1]), 1):
            lines.append(f"{i}. `{r[0]}`（{human(r[1])}）——{r[4].replace('**建议删**：', '')}")
        lines += ["", f"清理后 ≈ {human(total - sum(r[1] for r in deletable))}，"
                      "剩下的都是不可再生的项目/会话归档 + 本索引。"]
    return "\n".join(lines) + "\n", len(rows), total


def normalize(text: str) -> str:
    """去掉「生成时间」行后比对——时间戳每次都不同，不能算漂移。"""
    keep = [ln for ln in text.splitlines() if not (ln.startswith("> 由 ") and "生成 " in ln)]
    return "\n".join(keep).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.home() / "WorkBuddy" / "_archive"))
    ap.add_argument("--print-only", action="store_true", help="只打印不写盘")
    ap.add_argument("--check", action="store_true",
                    help="与现有 INDEX.md 比对（忽略生成时间行）：0=一致 1=过期 2=无法比对")
    a = ap.parse_args()
    root = Path(a.dir)
    if not root.is_dir():
        print(f"目录不存在: {root}")
        return 1
    text, n, total = build(root)
    if a.check:
        idx = root / "INDEX.md"
        if not idx.exists():
            print(f"无法比对：{idx} 不存在（先跑一次重建）")
            return 2
        if normalize(idx.read_text(encoding="utf-8")) == normalize(text):
            print(f"索引最新：{n} 项 / {human(total)}")
            return 0
        print(f"索引已过期：{idx} 与当前目录不一致 —— 跑 `python3 {Path(__file__).name}` 重建")
        return 1
    if a.print_only:
        # sys.stdout.write：print() 会多加一个换行，导致 --print-only 与文件产物差一行空行
        # （2026-11-21 审计纠正：上一轮把这条差异误判为"手工版 vs 脚本版"，其实是 print 的锅）
        sys.stdout.write(text)
        return 0
    (root / "INDEX.md").write_text(text, encoding="utf-8")
    print(f"已重建 {root / 'INDEX.md'}：{n} 项 / {human(total)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
