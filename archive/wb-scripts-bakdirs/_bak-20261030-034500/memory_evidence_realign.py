#!/usr/bin/env python3
"""证据块 ↔ 规则层的**重对齐辅助**（人工确认 + 机器执行，默认只读）。

## 为什么不做全自动（2026-10-26 实测结论）

用户级文件 88 块 / 91 条规则，编号错位自 10-14 起登记豁免、检索靠内容 grep。
想用「字符二元组召回」自动重排号，先做了两步验证：

1. **方法本身有效**：拿**已知对齐良好**的项目级文件（71/71、94% 对齐）回测，
   内容匹配能找回自身号 **69/71 = 97%**，best−second 中位差 0.64。
2. **但这份文件的数据不够**：高置信（score≥0.5）只有 **67/88**，其中还有 **4 个冲突**
   （两块指向同一条规则）→ 凑不出一一对应。强行解成双射 ＝ **用噪声造出一套看起来
   权威的编号**，比"已知错位"更危险（错位能被 `grep 内容` 绕过，假编号会让人信）。

⇒ 定位改为：机器出**候选**、人做**裁决**、机器执行**校验后的重编号**。
`--apply` 会拒绝任何非双射/越界/缺项的映射，绝不"尽力而为"。

## 用法

    # 1) 看统计（纯读）
    python3 memory_evidence_realign.py

    # 2) 生成审阅表（每块一行：现号 / 正文摘要 / top3 候选及分数）
    python3 memory_evidence_realign.py --sheet /tmp/evidence_sheet.md

    # 3) 人工填好映射表（TSV：旧块号<TAB>新规则号，# 开头为注释；目标 0=归档块，
    #    重编号到规则数之后的保留号段，用于「规则已刻意下沉」的证据存档）后执行
    python3 memory_evidence_realign.py --apply /tmp/evidence_map.tsv --yes

退出码：0 正常 / 1 映射校验失败 / 2 用法或文件错误
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_lock  # noqa: E402  # 写盘走同一套原子写+CAS

BLK_RE = re.compile(r"^\*\*── 证据 (?P<n>\d+) ──\*\*(?P<rest>.*)$")
CJK = re.compile(r"[^\u4e00-\u9fa5A-Za-z0-9]")
HI_SCORE = 0.50


def bigrams(text: str) -> set[str]:
    s = CJK.sub("", text)
    return {s[i : i + 2] for i in range(len(s) - 1)}


def parse(text: str) -> tuple[list[str], list[dict]]:
    """返回 (规则行, 证据块列表[{'no','rest','body','idx'}])。"""
    lines = text.split("\n")
    head = next((i for i, l in enumerate(lines) if l.startswith("## ") and "铁律" in l), None)
    if head is None:
        raise SystemExit("🔴 找不到「## … 铁律」规则层标题")
    end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    rules = [l for l in lines[head + 1 : end] if l.startswith("- ") and l.strip()]
    idxs = [i for i, l in enumerate(lines) if BLK_RE.match(l)]
    blocks = []
    for k, i in enumerate(idxs):
        stop = idxs[k + 1] if k + 1 < len(idxs) else len(lines)
        m = BLK_RE.match(lines[i])
        blocks.append(
            {
                "no": int(m.group("n")),
                "rest": m.group("rest"),
                "body": "\n".join(lines[i + 1 : stop]),
                "idx": i,
            }
        )
    return rules, blocks


def score_matrix(rules: list[str], blocks: list[dict]) -> list[dict]:
    rb = [bigrams(r) for r in rules]
    out = []
    for b in blocks:
        bb = bigrams(b["body"] + b["rest"])
        sc = sorted(
            ((len(rb[j] & bb) / max(1, len(rb[j])), j + 1) for j in range(len(rules))),
            reverse=True,
        )
        out.append(
            {
                "no": b["no"],
                "cands": [(round(s, 3), r) for s, r in sc[:3]],
                "score": sc[0][0],
                "margin": sc[0][0] - (sc[1][0] if len(sc) > 1 else 0.0),
                # 摘要优先取块头行的剩余正文（很多块的正文就写在块头那行），再退到正文首行
                "brief": next(
                    (x for x in [b["rest"].strip()] + list(b["body"].split("\n")) if x.strip()),
                    "",
                ).strip()[:38],
            }
        )
    return out


def cmd_report(rows: list[dict], n_rules: int) -> int:
    hi = [r for r in rows if r["score"] >= HI_SCORE]
    claimed = [r["cands"][0][1] for r in hi]
    dup = len(claimed) - len(set(claimed))
    print(f"规则 {n_rules} 条 / 证据块 {len(rows)} 块")
    print(f"  高置信（score≥{HI_SCORE}）：{len(hi)} 块；其中指向重复规则 {dup} 个")
    print(f"  低置信：{len(rows) - len(hi)} 块（需人工判断）")
    print("  → 结论：可自动？不。只有凑齐**双射**才可执行，见 --sheet 人工裁决")
    return 0


def cmd_sheet(rows: list[dict], n_rules: int, out: Path) -> int:
    lines = [
        "# 证据块重对齐 · 审阅表（2026-10-26 生成）",
        "",
        f"> 规则 {n_rules} 条 / 证据块 {len(rows)} 块。请把最后一列填成新规则号（留空=保持现号），",
        "> 然后存成 TSV（列：块号<TAB>新号）供 `--apply` 使用。",
        "> 判据：一份合法映射必须**一一对应**（每个块一个号、每个号最多一个块）。",
        "",
        "| 块号 | 正文摘要 | 候选1 | 候选2 | 候选3 | 建议 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        c = r["cands"] + [(0.0, "-")] * (3 - len(r["cands"]))
        top = r["cands"][0]
        sug = top[1] if r["score"] >= HI_SCORE and r["margin"] >= 0.30 else "（需人工）"
        lines.append(
            f"| {r['no']} | {r['brief']} | {c[0][1]} ({c[0][0]:.2f}) | "
            f"{c[1][1]} ({c[1][0]:.2f}) | {c[2][1]} ({c[2][0]:.2f}) | {sug} |"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sug_n = sum(1 for r in rows if r["score"] >= HI_SCORE and r["margin"] >= 0.30)
    print(f"审阅表已写：{out}（{len(rows)} 行；机器建议可直接采纳 {sug_n} 行）")
    return 0


def read_mapping(path: Path) -> dict[int, int]:
    m: dict[int, int] = {}
    for raw in path.read_text(encoding="utf-8").split("\n"):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = re.split(r"[\t,;\s]+", line)
        if len(parts) < 2:
            raise SystemExit(f"🔴 映射行无法解析：{raw!r}（需要 旧块号<TAB>新规则号）")
        m[int(parts[0])] = int(parts[1])
    return m


def validate(mapping: dict[int, int], blocks: list[dict], n_rules: int) -> list[str]:
    errs = []
    cur = {b["no"] for b in blocks}
    miss = sorted(cur - set(mapping))
    extra = sorted(set(mapping) - cur)
    if miss:
        errs.append(f"缺 {len(miss)} 个块的映射：{miss[:8]}")
    if extra:
        errs.append(f"映射里有多余的块号（文件里没有）：{extra[:8]}")
    # 目标 0 = 归档块（规则已被刻意下沉/删除的证据存档，如 10-23 下沉的 MCP/混元块），
    # 不占规则号，--apply 时重编号到 n_rules 之后的保留号段；多个 0 合法。
    tgts = [t for t in mapping.values() if t != 0]
    dup = sorted({t for t in tgts if tgts.count(t) > 1})
    if dup:
        errs.append(f"目标号重复（一一对应被破坏）：{dup[:8]}")
    oob = sorted({t for t in tgts if not (1 <= t <= n_rules)})
    if oob:
        errs.append(f"目标号越界（1..{n_rules}，或 0=归档）：{oob[:8]}")
    return errs


def cmd_apply(path: Path, mapping_file: Path, yes: bool) -> int:
    text = path.read_text(encoding="utf-8")
    rules, blocks = parse(text)
    mapping = read_mapping(mapping_file)
    errs = validate(mapping, blocks, len(rules))
    if errs:
        print(f"🔴 映射校验失败（{len(errs)} 项），未写盘：")
        for e in errs:
            print(f"   → {e}")
        return 1

    changed = sum(1 for b in blocks if mapping[b["no"]] != b["no"])
    arch = sorted(b["no"] for b in blocks if mapping[b["no"]] == 0)
    used = {t for t in mapping.values() if t != 0}
    unused = sorted(set(range(1, len(rules) + 1)) - used)
    print(
        f"映射合法：{len(blocks)} 块全部有唯一目标；需改号 {changed} 块；"
        f"归档块 {len(arch)} 个（{arch} → 编号 {len(rules) + 1}+）；无证据规则 {len(unused)} 条（{unused}）"
    )
    if not yes:
        print("（dry-run，加 --yes 才写盘）")
        return 0

    lines = text.split("\n")
    # 归档块按现号升序拿保留号段（n_rules+1 起），保证编号稳定可复现
    arch_map = {no: len(rules) + 1 + k for k, no in enumerate(arch)}
    for b in blocks:
        new = mapping[b["no"]]
        if new == 0:
            new = arch_map[b["no"]]
        if new != b["no"]:
            lines[b["idx"]] = f"**── 证据 {new} ──**{b['rest']}"
    new_text = "\n".join(lines)

    # 写后自检：块数不变且编号不重复
    _r2, blocks2 = parse(new_text)
    nums = [b["no"] for b in blocks2]
    if len(blocks2) != len(blocks) or len(set(nums)) != len(nums):
        print("🔴 写后自检失败（块数变了或编号重复），放弃写入", file=sys.stderr)
        return 1

    bak = path.with_name(f"{path.name}.bak-realign-{datetime.now():%H%M%S}")
    shutil.copy2(path, bak)
    memory_lock.atomic_write(path, new_text, expect_sha=memory_lock.sha1_text(text))
    print(f"✅ 已重编号 {changed} 块；备份 {bak}")
    print("   下一步：跑 check_memory_visibility.py --fix 让声明跟上，再跑 check 确认 rc=0")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--file",
        default=None,
        help="目标 MEMORY.md；缺省时自动发现 ~/.workbuddy/user-*/MEMORY.md（"
        "唯一候选直接用，多候选/零候选则报错要求显式指定 —— 不猜）",
    )
    ap.add_argument("--sheet", help="生成审阅表到指定路径（md）")
    ap.add_argument("--apply", help="按映射表执行重编号（需 --yes）")
    ap.add_argument("--yes", action="store_true", help="真写盘")
    a = ap.parse_args()

    if a.file is None:  # 自动发现：不硬编码 user-id（换机/换 user 后写死路径会静默指错）
        cands = sorted((Path.home() / ".workbuddy").glob("user-*/MEMORY.md"))
        if len(cands) == 1:
            a.file = str(cands[0])
        elif not cands:
            print("🔴 未找到 ~/.workbuddy/user-*/MEMORY.md，请显式 --file", file=sys.stderr)
            return 2
        else:
            print(
                "🔴 发现多份 user-*/MEMORY.md，无法猜测目标，请显式 --file：\n  "
                + "\n  ".join(str(c) for c in cands),
                file=sys.stderr,
            )
            return 2

    p = Path(a.file).expanduser()
    if not p.exists():
        print(f"🔴 文件不存在：{p}", file=sys.stderr)
        return 2
    rules, blocks = parse(p.read_text(encoding="utf-8"))
    if a.apply:
        return cmd_apply(p, Path(a.apply).expanduser(), a.yes)
    rows = score_matrix(rules, blocks)
    if a.sheet:
        return cmd_sheet(rows, len(rules), Path(a.sheet).expanduser())
    return cmd_report(rows, len(rules))


if __name__ == "__main__":
    sys.exit(main())
