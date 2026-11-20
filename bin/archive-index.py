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
import time
from pathlib import Path

# 处置结论（按文件名前缀/全名匹配）。新增归档时在此登记，否则落「未分类/待评估」。
VERDICT = {
    "cron-mail-spool-": ("噪音归档", "**建议删**：356,687 封中 99.99% 是两个 watchdog 的重复输出；有效 36 封已单列", "不可再生"),
    "cron-mail-interesting-": ("邮件存档", "保留：从噪音 mbox 抽出的有效 cron 输出", "不可再生"),
    "XtItClient_": ("安装包", "**建议删**：券商官网可重下", "可再生"),
    "workspace-session-dirs-": ("会话归档", "保留：历史会话目录，逐目录 diff 验过", "不可再生"),
    "marvis-bridge-final": ("项目归档", "保留：收尾快照（仓已 archived）", "不可再生"),
    "MarvisBridge-runtime": ("运行时归档", "保留", "不可再生"),
    "wechat-download-api.STALE": ("项目归档", "保留：标 STALE，待确认后处理", "不可再生"),
    "MANIFEST-": ("文档", "保留：归档说明", "可再生"),
}


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


def classify(name: str) -> tuple[str, str, str]:
    for prefix, verdict in VERDICT.items():
        if name.startswith(prefix):
            return verdict
    return ("未分类", "**待评估**：未在 VERDICT 登记", "未知")


def build(root: Path) -> tuple[str, int, int]:
    rows = []
    for p in sorted(root.iterdir()):
        if p.name == "INDEX.md" or p.name.startswith("."):
            continue
        if p.is_dir():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            rows.append((p.name + "/", size, p.stat().st_mtime, "目录", "见目录内文件", "—", "—"))
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(Path.home() / "WorkBuddy" / "_archive"))
    ap.add_argument("--print-only", action="store_true", help="只打印不写盘")
    a = ap.parse_args()
    root = Path(a.dir)
    if not root.is_dir():
        print(f"目录不存在: {root}")
        return 1
    text, n, total = build(root)
    if a.print_only:
        print(text)
        return 0
    (root / "INDEX.md").write_text(text, encoding="utf-8")
    print(f"已重建 {root / 'INDEX.md'}：{n} 项 / {human(total)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
