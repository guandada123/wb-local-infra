#!/usr/bin/env python3
"""majiu-archive-index.py —— 生成《马厩归档总册》（台账 + 成果档案 + 归档区 + 遗留）。

背景：马厩（工作空间治理）的归纳分三层——台账（STALL_LOG.md）、归档区（_archive/）、
成果档案（archive/<日期>-conversation/）。三层分散在三处，找东西要翻。
本脚本把它们汇成一份可直接上传资料库的总册，避免每次手写内联代码（那版逻辑只活在会话里，不可复跑）。

用法：
    python3 majiu-archive-index.py                        # 打印到 stdout
    python3 majiu-archive-index.py --out 总册.md          # 落盘
    python3 majiu-archive-index.py --check 总册.md        # 比对（0 一致 / 1 过期 / 2 文件不存在 / 3 无法比对）
    python3 majiu-archive-index.py --with-library         # 额外实读资料库「00 对话成果档案」清单

生成模式自描述：总册头部写 `> 生成模式：…`，`--check` 按**文件自己声明的模式**重建再比对。
（2026-11-22 修：此前 --check 恒按本机模式重建，对 --with-library 生成的总册必然判「过期」——
一个刚生成的文件被判过期，闸门就等于永远假红，挂到每日检查只会制造噪音。）

设计约束：
- 只读，不改任何源数据；台账/档案/归档区都只读。
- 本机部分零外部依赖（纯 stdlib）；--with-library 才调腾讯文档无关的 library space_api.py，
  失败只在对应小节标注「未取」并给出原因，不中断生成。
- 数字一律现算（不写死），因此不会随档案增减而失真。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()

# 资料库「00 对话成果档案」（2026-11-22 实读确认：space/d/{id} 的父空间即此 space）
LIB_SPACE = "YHKOkiUC0ilqsTpMOwxtYw"
LIB_FOLDER = "NO8kdWuj4SS5PizPfbZEjh"
LIB_SKILL = (
    "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/resources/"
    "plugins/workbuddy-builtin/skills/library/space_api.py"
)

# 遗留项（长期文本；变更时改这里，总册随之更新）
TODO_ROWS = [
    ("L1", "3 条 prompt 耦合自动化", "已裁定不动"),
    ("L2", "`_archive` 清理", "**已执行 2026-11-22**：mbox 251MB + exe 237MB 移废纸篓；562MB → 75MB"),
    ("L3", "废纸篓 3.8GB", "待手动清倒"),
    ("L4", "StockInsight 公开仓跟踪持仓明细", "**已执行 2026-11-22**：`模拟盘.json`、`全链路精选组合.json` 均 `git rm --cached`（本地文件保留，程序产物）"),
    ("L5", "QTS 模块拆分", "暂缓（缺模块级 tests）"),
    ("L6", "`_archive/知识库/` 原件", "保留"),
    ("L7", "每日检查五类（脚本 / plist / 索引 / 锚点 / 总册）", "运行中"),
    ("L8", "`STALL_LOG.md` 不入 git（.gitignore:210）", "现状接受（资料库有云端副本）"),
    ("L9", "云端档案分两处", "已汇总：主库 41 份；腾讯文档旁支 4 份（历史未迁）"),
]

# 生成模式标记（自描述）：--check 按文件这一行决定用什么模式重建
MODE_LIB = "--with-library"
MODE_LOCAL = "本机三层"


def parse_stall_log(path: Path) -> list[list[str]]:
    """解析台账「栏位记录」表格，返回 [#, 名称, kind, 状态, 开始, 结束]。"""
    if not path.exists():
        return []
    rows, in_table = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 栏位记录"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if in_table and re.match(r"^\| \d+ \|", line):
            cells = [c.strip() for c in line.strip("|").split("|")]
            rows.append(cells[:6])
    return rows


def find_local_archives(workbuddy: Path) -> list[tuple[str, str]]:
    """本机成果档案：Claw/.workbuddy/archive 与 <workbuddy>/2026-*/archive 两处。"""
    found = []
    roots = [
        (workbuddy / "Claw" / ".workbuddy" / "archive", "*-conversation"),
        (workbuddy, "2026-*/archive/*-conversation"),
    ]
    for base, pattern in roots:
        if not base.exists():
            continue
        for d in sorted(base.glob(pattern)):
            f = d / "成果档案.md"
            if f.exists():
                found.append((d.name.split("-conversation")[0], str(f)))
    return found


def archive_summary(workbuddy: Path) -> tuple[int, float] | None:
    """归档区：从 _archive/INDEX.md 数条目与总大小。

    读不到（文件缺失 / 格式变化）返回 None——**绝不返回 (0, 0.0)**：
    那会在总册里显示「0 项 / 0MB」这种假事实，比不显示更危险。
    """
    idx = workbuddy / "_archive" / "INDEX.md"
    if not idx.exists():
        return None
    text = idx.read_text(encoding="utf-8", errors="ignore")
    # 兼容「共 N 项」与「N 项」两种写法
    m = re.search(r"(?:共\s*)?(\d+)\s*项\s*/\s*\*\*([\d.]+)\s*([MGT]?B)\*\*", text)
    if not m:
        return None
    size = float(m.group(2))
    unit = m.group(3)
    size *= {"B": 1 / 1024 / 1024, "KB": 1 / 1024, "MB": 1, "GB": 1024, "TB": 1024 * 1024}[unit]
    return int(m.group(1)), size


def library_docs() -> tuple[list[str], str]:
    """实读资料库「00 对话成果档案」。返回 (标题列表, 错误说明)。

    MAJIU_LIB_DOCS_FILE 指向一个 JSON（标题数组或 {"titles": [...]}）时走该文件当替身，
    用于离线测试与排障——真实调用要网络+登录，测试里跑不了。
    """
    stub = os.environ.get("MAJIU_LIB_DOCS_FILE")
    if stub:
        try:
            data = json.loads(Path(stub).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [], f"替身文件不可读（{type(exc).__name__}）"
        titles = data.get("titles", []) if isinstance(data, dict) else data
        if not isinstance(titles, list):
            return [], "替身文件格式不对（需标题数组）"
        return sorted(str(t) for t in titles), ""

    py = HOME / ".workbuddy/binaries/python/envs/default/bin/python"
    exe = str(py) if py.exists() else sys.executable
    if not Path(LIB_SKILL).exists():
        return [], "未找到资料库脚本（非 WorkBuddy 桌面端环境）"
    cmd = [exe, LIB_SKILL, "space.workspace.list-nodes",
           "--space-id", LIB_SPACE, "--parent-node-id", LIB_FOLDER, "--limit", "200"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return [], f"调用失败: {type(exc).__name__}"
    try:
        data = json.loads(r.stdout)["data"]["nodes"]
    except (json.JSONDecodeError, KeyError):
        return [], "返回不可解析（可能未登录或网络不可达）"
    return sorted(n["title"] for n in data if n.get("kind") == "doc"), ""


def build(workbuddy: Path, with_library: bool) -> tuple[str, str]:
    """生成总册正文。返回 (正文, 云端实读错误说明为空即成功)。"""
    claw = workbuddy / "Claw"
    ledger = parse_stall_log(claw / "STALL_LOG.md")
    local = find_local_archives(workbuddy)
    arc = archive_summary(workbuddy)
    cloud, cloud_err = library_docs() if with_library else ([], "未启用 --with-library")

    mode = MODE_LIB if with_library else MODE_LOCAL
    out: list[str] = [
        "# 马厩归档总册", "",
        "> 本册由 `wb-local-infra/bin/majiu-archive-index.py` 生成，**不手工维护**。",
        f"> 生成模式：{mode}（`--check` 按此行选择重建口径）",
        "> 马厩（工作空间治理）把归纳分三层存放，本册是资料库侧的汇总入口。", "",
        "| 层 | 内容 | 位置 |", "|---|---|---|",
        "| ① 台账 | 任务生命周期：出栏日期、产物落点、失败模式 | `Claw/STALL_LOG.md`（本机）+ 资料库 `马厩台账_STALL_LOG` |",
        "| ② 归档区 | 被归档的栏位本体与历史文件 | `Claw/_archive/`、`~/WorkBuddy/_archive/` |",
        "| ③ 成果档案 | 每次收尾的产出 / 结论 / 资产索引 / 遗留 | 本机 `archive/<日期>-conversation/` + 资料库「00 对话成果档案」 |",
        "",
        f"## 一、台账（{len(ledger)} 个栏位）", "",
    ]
    if ledger:
        out += ["| # | 名称 | kind | 状态 | 开始 | 结束 |", "|---|---|---|---|---|---|"]
        out += ["| " + " | ".join(r) + " |" for r in ledger]
        out += ["", "> 产物位置与失败模式原文见台账末两列。"]
    else:
        out += ["台账未读到（`Claw/STALL_LOG.md` 不存在或无「栏位记录」表）。"]

    out += ["", f"## 二、成果档案（资料库「00 对话成果档案」）", ""]
    if cloud:
        out += [f"实读 **{len(cloud)} 份**：", "", "| # | 档案 |", "|---|---|"]
        out += [f"| {i} | {t} |" for i, t in enumerate(cloud, 1)]
        out += ["", "> 2026-11-22 归位动作：13 份此前散落在资料库根目录的档案已全部移入本文件夹"
                    "（`move-node` 13/13），根目录 doc 归零。"]
    else:
        out += [f"未实读（{cloud_err}）。运行加 `--with-library` 可拉取实际清单。"]

    out += ["", f"## 三、本机原件（{len(local)} 份）", "",
            "**本机是云端的子集，不是互为副本**：本机只保留仍有 `archive/<日期>-conversation/` 目录的那批，"
            "其余档案随会话工作区清理后**仅云端留存**。找历史档案以云端为准，本机路径只便于脚本读取。", ""]
    if local:
        out += ["| 日期 | 本机路径 |", "|---|---|"]
        out += [f"| {d} | `{p.replace(str(HOME) + '/', '~/')}` |" for d, p in sorted(local)]
    else:
        out += ["未找到 `archive/*-conversation/成果档案.md`。"]

    arc_title = f"{arc[0]} 项 / {arc[1]:.0f}MB" if arc else "未读到索引"
    if arc is None:
        note = ["", "> ⚠️ `~/WorkBuddy/_archive/INDEX.md` 未读到或格式变化 —— 先跑 `archive-index.py` 重建。"]
    else:
        note = []
    out += ["", f"## 四、归档区（{arc_title}）", ""] + note + [
            "完整清单与处置结论见 `~/WorkBuddy/_archive/INDEX.md`（由 `archive-index.py` 重建）。要点：", "",
            "| 项 | 大小 | 处置 |", "|---|---|---|",
            "| `cron-mail-spool-20261012.mbox` | 250MB | 356,687 封中 99.99% 是两 watchdog 重复输出；有效 36 封已抽出 → 建议删 |",
            "| `XtItClient_...exe` | 236MB | QMT Windows 安装包，官网可重下 → 建议删 |",
            "| `workspace-session-dirs-20261120.tgz` | 19MB | 148 个历史会话目录，逐目录 diff 验过 → 保留 |",
            "| 项目归档（marvis / wechat / 会话包） | ~23MB | 不可再生 → 保留 |",
            "| `知识库/` | 13KB | 仅初始化过；2 样独有已抽到 Claw docs → 原件留档 |",
            "", "## 五、遗留", "", "| # | 事项 | 状态 |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in TODO_ROWS]

    out += ["", "## 六、怎么用", "",
            "1. **要看某次做成了什么** → 资料库按日期找 `对话成果档案_YYYYMMDD_*`；",
            "2. **要看任务全貌与踩过的坑** → `马厩台账_STALL_LOG`；",
            "3. **要找某次归档的文件** → `~/WorkBuddy/_archive/INDEX.md`；",
            "4. **新收尾后** → 本机写完 `archive/<日期>-conversation/` → 上传资料库 → 重跑本脚本更新总册。", "",
            "## 七、一句话", "",
            "台账记「谁出栏了」，归档区存「栏位本体」，成果档案记「这次做成了什么」——本册把三层在云端汇到一处。", ""]
    return "\n".join(out), cloud_err


def detect_mode(text: str) -> str:
    """读总册自己声明的生成模式；无标记（旧版手写总册）→ 按本机模式。"""
    m = re.search(r"^> 生成模式：(.+?)（", text, re.M)
    return m.group(1).strip() if m else MODE_LOCAL


def normalize(text: str) -> str:
    """比对时忽略「生成时间」类易变行。"""
    return "\n".join(l for l in text.splitlines() if "本册由" not in l).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="生成马厩归档总册")
    ap.add_argument("--workbuddy-home", default=str(HOME / "WorkBuddy"))
    ap.add_argument("--out", help="写入该路径")
    ap.add_argument("--check", metavar="PATH", help="与既有文件比对：0 一致 / 1 过期 / 2 不存在 / 3 无法比对")
    ap.add_argument("--with-library", action="store_true", help="实读资料库「00 对话成果档案」清单")
    a = ap.parse_args()

    if a.check:
        p = Path(a.check)
        if not p.exists():
            print(f"无法比对：{p} 不存在")
            return 2
        old = p.read_text(encoding="utf-8")
        # 按文件声明的模式重建，否则 --with-library 生成的总册永远被判过期（假红）
        with_lib = detect_mode(old) == MODE_LIB
        text, cloud_err = build(Path(a.workbuddy_home), with_lib)
        if with_lib and cloud_err:
            # 读不到云端清单 ≠ 总册过期：这是"比对没做成"，必须与 1 区分开
            print(f"无法比对：{p} 声明了资料库实读，但本次未读到（{cloud_err}）")
            return 3
        if normalize(old) == normalize(text):
            print(f"总册最新：{p}")
            return 0
        print(f"总册已过期：{p} 与当前台账/档案不一致 —— 重跑本脚本并加 --out {p}")
        return 1

    text, _ = build(Path(a.workbuddy_home), a.with_library)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"已写入 {a.out}（{len(text)} 字符）")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
