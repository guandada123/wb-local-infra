#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记忆文件「规则层可见性」硬判据（默认纯读；加 --fix 才写盘）。

背景（2026-09-28 实测）：
  MEMORY.md 注入上下文时有字节上限；超限部分**静默截断**。
  用户级 ~/.workbuddy/MEMORY.md 上限 ≈7,353B，而文件 86.9KB → 只有前 8.5% 可见。
  于是**规则与证据必须分层**：规则层（每条一行命令）置顶落在可见区内，
  证据层（事故复现/取证）沉到文末，按需 grep。否则「规则被自己的证据挤出可见区」。

判据（任一不满足即 rc=1，并打印原因）：
  ① 索引块存在（含「速查索引」的段落）且其结束偏移 < 注入上限
  ② 每个 ##/### 标题至少有一个词能在索引块里命中（覆盖率 0 盲区）
  ③ 若含「## 🔴 铁律」规则层：**末条规则行的独占结束偏移** ≤ 注入上限（**全部规则可见**）
     （10-15 修口径：旧口径取「规则层段落结束偏移」＝含「末条规则→下一节标题」之间的
       分隔空行并再 +1 → 规则层恰好填满上限时误报「有规则落在可见区外（溢出 2B）」，
       而事实一条都没出去。可见余量是否够大由 memory_headroom_check.py 负责。）
  ④ 若含「铁律证据库」：规则数 − 证据块数 = 0，或该差值已在 `memory_known_issues.json`
     的 `rules_evidence_gap` 里登记（含 `expected_gap` 与 `reason`）。
     口径于 2026-10-23 放宽：原为「必须相等」，但规则层会拆分/下沉（规则数变、证据块不变），
     在那个假设下每动一次结构就要改登记或报假红。现在只校验「差值是否为登记值」——
     差值一变就报，仍能抓住「突然丢了一批证据块」。
  ⑤ 若索引头/规则层标题**声明了**条数、规则止字节、余量或行范围：声明值 == 实测值
     （09-30 新增：09-29 新增 2 条铁律后，索引头仍写「60 条各一行」而实测 62 条，
       脚本只报实测值、不比对声明 → **声明静默腐烂、无人发现**。同族于铁律
       「同一事实只允许一处自由」：声明是副本，副本必须机器核对。）
  ⑥ 证据库小标题若声明「共 N 条」：声明值 == 证据块实测数
     （10-08 新增：⑤ 只覆盖了「索引头/规则层标题」两处声明，**漏了证据库小标题**这第三处
       → 用户级写「共 66 条」实测 72 块、项目级写「共 58 条」实测 63 块，两处各腐烂
       6/5 天无人发现。教训：同族判据必须**穷举同一事实的全部声明点**，否则
       「已机器化」只是覆盖了一个副本，剩下的照烂。）
  ⑧ 证据块只能落在「## 📎」之后，且编号不得重复（2026-10-26 新增，disc-20261026-02）：
     计数只扫 `## 📎` 之后 → 越界块**完全不可见**，还会让 ④ 的差值少算一个（差值一旦
     被 expected_gap 豁免就永久隐形）；同号两条则让「按编号检索」拿到别人的证据。
     两类都可按 `evidence_out_of_bounds` / `evidence_duplicate_no` 登记豁免（须写 reason）。
  ⑨ 索引头若声明「每条≤NB」（单条规则字节预算）：实测最长规则不得超过该预算
     （2026-10-26 新增）。动因：该声明**从未被核对**，用户级文件写 90B 而实测 100B，
     烂了至少 12 天无人发现 —— 同族于 ⑤⑥，声明是副本，副本必须机器核对。
     取 `≤` 不取 `==`：预算是上限，允许留余量；超了要么压规则，要么显式调高预算。

--fix（10-09 新增，治 ⑤⑥ 的复发根因）：
  声明腐烂的**根因是「人改内容 + 手算偏移」**——09-29/09-30/10-03/10-08/10-09 五次复发，
  其中 10-09 是**差 1 字节**（第 3 行加 77B，声明写 14,101 实测 14,102）。
  差 1 的来源是两种口径混淆：「规则层占 N 字节」vs「下一段起于 N+1 字节」。
  → 结论：**声明里的数值一律不许手算，必须由脚本写**。
  --fix 用实测值回写 ⑤⑥ 的全部声明点（含行范围），**迭代到稳定**（改声明长度会移动偏移，
  须重算，最多 5 轮），改前打印逐条 before→after。

用法：
  python3 check_memory_visibility.py                 # 检查用户级 + Claw 项目级
  python3 check_memory_visibility.py <文件> ...       # 指定文件
  python3 check_memory_visibility.py --fix [<文件>...] # 回写声明值（写盘！先备份）
"""

import json
import re
import sys
from pathlib import Path

# 写入原语（锁 + 原子写 + CAS）与 memory_add_rule 共用一份实现（2026-10-26 审计）。
# ⚠️ 必须用 resolve()：本文件常以 `~/.workbuddy/scripts/` 下的**符号链接**被调用，
#    拿 __file__ 的父目录会把 sys.path 指到链接所在目录，那里没有 memory_lock.py。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_lock  # noqa: E402

# 实测注入上限（skill context-health-cleanup Step 0.1/0.4；换机器/换版本须重新实测）
_H = Path.home()  # P1-12：禁写死本机绝对路径，一律从 home 派生
DEFAULT_LIMITS = {
    str(_H / ".workbuddy" / "MEMORY.md"): 7353,
    # 项目级记忆：Claw 仓库的 `.workbuddy/memory/MEMORY.md`。
    # 🔴 2026-10-26 审计闭环：`~/WorkBuddy` 是 → `/Volumes/ZHITAI/WorkBuddy` 的符号链接，
    #    同一文件有两种等价写法。登记**两个键**（符号链接写法 + resolve 后的真实挂载写法），
    #    保证「默认跑」与「显式传真实挂载路径」两种调用都能命中，避免判据⑨盲区。
    #    查表侧保持精确串匹配（不对所有键 resolve，否则会把 `~/.workbuddy` 这种
    #    本身也是符号链接的键解析偏掉，反而让 home/user 文件漏检）。
    str(_H / "WorkBuddy" / "Claw" / ".workbuddy" / "memory" / "MEMORY.md"): 16474,
    str((_H / "WorkBuddy" / "Claw" / ".workbuddy" / "memory" / "MEMORY.md").resolve()): 16474,
    # 🔴 2026-10-14 新增：这才是**实际被注入**的用户级记忆（平台 Layer 2；旧路径
    #   ~/.workbuddy/MEMORY.md 自 10-11 起已冻结、不再被任何注入消费 → 只查旧路径＝假绿灯）。
    #   上限用「当日注入块末尾原文串回定位」实测（skill Step 0.1/0.4）——
    #   **不许手算，也不许把它当恒定值**：10-14 实测 7,913B，10-18 复测 **7,757B**
    #   （同一方法，差 156B）⇒ 上限确非恒定。按 Step 0.6「取当日实测 ∩ 内置的较小者」
    #   取**历史较小值 7,757B**：宁可保守报红，也不能高估余量（10-18 实测：
    #   内置 7,913 会把真实余量 82B 报成 238B，高估 2.9 倍）。
    str(
        _H / ".workbuddy" / "user-24688a34-03ff-4299-8736-08d5a6585c6b-personal" / "MEMORY.md"
    ): 7757,
}
# 🔴 2026-10-27：**已冻结、且不再被任何注入消费**的副本。
#   依据 references/memory_two_copy_consistency.md（2026-10-14 已记录：A 冻结 / B 被注入）。
#   这些路径仍留在 DEFAULT_LIMITS 与 DEFAULT_FILES 里做**历史对照**：
#     · 超限时照样 🔴（保护能力不减）；
#     · 健康时**不打 ✅ 而打 🟡** —— 因为「✅ = 这份是活的」是个错误暗示。
#   实证代价（为什么值得改）：2026-10-27 一次跨会话审计中，审计者看到 4 个 ✅，
#   把本文件当成「新发现的两份记忆分叉」上报，而 references/ 里 9 天前就记过此事。
#   绿灯的措辞本身成了一次误读的入口 —— 这就是本条要堵的东西。
NON_INJECTED_FILES = {
    str(_H / ".workbuddy" / "MEMORY.md"),
}


def tag_for(problems, path: str) -> str:
    """输出标签（三分支）。抽成函数是为了让三态**可被单测击破**。

    关键不变量：`problems` 非空时**必须 🔴**，即使该文件在 NON_INJECTED_FILES 里。
    「已冻结」只影响**健康时**的措辞，不构成免检 —— 否则等于用一条豁免把判据关成常绿
    （同类错误见 KNOWN_ISSUES 的「空 reason 不生效」设计）。
    """
    if problems:
        return "🔴"
    if path in NON_INJECTED_FILES:
        return "🟡"
    return "✅"


DEFAULT_FILES = list(DEFAULT_LIMITS)

TOKEN = re.compile(r"[\u4e00-\u9fa5]{2,6}|[A-Za-z_][A-Za-z0-9_.]{2,}")
EVID_MARK = "铁律证据库"
# 判据⑦ 的两个线（集中声明，避免正文里散落魔法数）
EV_MATCH_MIN = 0.15  # 块↔规则词面重合低于此值不参与偏移统计（太短/纯符号块）
EV_ALIGN_MIN = 0.80  # 「偏移 0 的块」占比低于此值 ⇒ 判错位（正常文件实测 93%~99%）
MAX_FIX_ROUNDS = 5
# 「已知问题」登记表（2026-10-21 新增）：把**已核实并已说明**的不一致与**新出现的腐烂**
# 区分开，避免告警疲劳（用户明确忌讳：噪音告警会让人连真信号一起忽略）。
# 只对登记过的「文件 + 问题类型」生效，且**必须写 reason** —— 空理由的豁免不生效，
# 防止有人用一条空记录把判据关掉（那等于把判据改成常绿）。
KNOWN_ISSUES = Path.home() / ".workbuddy" / "memory_known_issues.json"


def _known_issue_entry(path, kind):
    """返回该文件该类的登记条目（dict）；无登记或 reason 为空则 None。

    ★ 返回**整条**而不只是 bool：有些豁免必须带可证伪条件（如「规则↔证据差 N 条」），
      只判「有没有登记」会让豁免变成永久绿灯 —— 差值从 6 变成 60 也照样免检。
    """
    try:
        if not KNOWN_ISSUES.exists():
            return None
        data = json.loads(KNOWN_ISSUES.read_text(encoding="utf-8"))
        table = data.get(kind) or {}
        # ⚠️ 必须同查「原样路径」与「realpath」：本机 ~/.workbuddy 是符号链接，
        #   解析后落在 /Volumes/ZHITAI/workbuddy_data/...，只按 resolve() 查会漏配。
        #   2026-10-21 首版就踩了：JSON 写原路径、代码查 resolve → waived=False，
        #   豁免静默失效（同族于「符号链接须防静默失败」）。
        for key in {str(path), str(Path(path).resolve())}:
            entry = table.get(key)
            if entry and str(entry.get("reason", "")).strip():
                return entry
        return None
    except Exception:  # noqa: BLE001  # 辅助/兜底路径，异常不影响主流程，安全忽略
        # 登记表坏了就当没登记（宁可多报，不可漏报）
        return None


def _known_issue_waived(path, kind):
    """该文件的这类问题是否已登记为已知（有理由才算）。"""
    return _known_issue_entry(path, kind) is not None


def _layout(text, limit):
    """算出索引/规则层/证据库的位置与实测值（纯函数，供 check 与 fix 共用）。"""
    lines = text.split("\n")
    info = {"bytes": len(text.encode()), "limit": limit}
    # 🔴 2026-10-22 加固：原判据 `"速查索引" in l` 是包含式匹配 —— 正文里只要有人
    #   写一句「参见速查索引」且位置在索引块之前，索引区起点就会取错，进而把整个
    #   「索引止 / 规则止 / 余量」算偏。与 evidence 插入那个撕裂 bug 同族：
    #   **无法区分「提到某标记」与「该标记本身」**。
    #   现在只认两种真身：粗体行 `**速查索引**…` 或标题行 `## …速查索引…`。
    idx_lines = [
        i
        for i, l in enumerate(lines)
        if l.startswith("**速查索引**") or (l.startswith("## ") and "速查索引" in l)
    ]
    if not idx_lines:
        info.update(idx_s=None, idx_e=None, index_end=None)
    else:
        s = idx_lines[0]
        e = next((i for i in range(s + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        info.update(idx_s=s, idx_e=e, index_end=len("\n".join(lines[:e]).encode()) + 1)
    rule_head = next(
        (
            i
            for i, l in enumerate(lines)
            if l.startswith("## ") and "铁律" in l and not l.startswith("## 📎")
        ),
        None,
    )
    if rule_head is not None:
        rule_end = next(
            (i for i in range(rule_head + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
        )
        # 行范围口径（10-09 固化，防两义）：A=规则层标题行(1-based)，
        # B=规则层内**最后一个非空行**(1-based)——不含标题与下一节之间的空行，
        # 因为「行 24–88」在人读时指的是标题到末条规则，不是标题到空行。
        rule_last = (
            next((i for i in range(rule_end - 1, rule_head, -1) if lines[i].strip()), rule_head) + 1
        )  # 转 1-based：与 A 同口径
        # 🔴 2026-10-15 修口径（第 N 次「输出在说谎」）：rule_off **必须**是
        #   「最后一条规则行的独占结束偏移」= len('\n'.join(lines[:rule_last]))，
        #   不能是「规则层段落结束偏移」= len('\n'.join(lines[:rule_end])) + 1。
        #   旧口径把「末条规则 → 下一个 `## ` 标题」之间的**分隔空行**算进了规则层，
        #   还额外 +1，于是当规则层恰好填满上限（末条规则最后一字节落在 limit-1、
        #   后面只跟一个空行）时，会报「有规则落在可见区外（溢出 2B）」——
        #   而事实是**一条规则都没出去**：报告的是不存在的事实（同族于「取不到证
        #   渲染成通过」，只是方向相反：把「刚好贴边」渲染成「已经溢出」）。
        #   判据③ 要回答的问题是「全部规则可见吗」；答案「是」时不该报红。
        #   可见余量**够不够大**由 1a-2（memory_headroom_check.py，阈值 500B）负责，
        #   两件事分工不同，不要用一个判据同时答。
        #   旧口径值保留在 rule_section_end，仅供诊断与对照。
        _tail = len("\n".join(lines[:rule_last]).encode())
        # 🔴 2026-10-17 新增 longest_rule：**物理口径**（推算术，非阈值）。
        #   判据③ 回答「规则现在可不可见」；本字段回答**另一个问题**——
        #   「余量还够不够装下一条最长的规则」。两者不同口径，故**只作信息输出、
        #   不参与 rc**（同 Step 0.30：一个判据只答一件事）。用途：把「余量 238B
        #   到底够不够」从手工推算变成机器给数 —— 实测 B 最长规则 261B > 238B，
        #   即「再加最长那条就会挤出可见区」是可机器判定的，无须人工估。
        #   口径与 rules 完全一致（同一切片、同一 `startswith('- ')` 谓词），
        #   避免「同一事实两处口径」（Step 0.30 的病根）。
        _rules_lines = [
            l for l in lines[rule_head + 1 : rule_end] if l.startswith("- ") and l.strip()
        ]
        info.update(
            rule_head=rule_head,
            rule_end=rule_end,
            rule_last=rule_last,
            rule_off=_tail,
            rule_section_end=len("\n".join(lines[:rule_end]).encode()) + 1,
            headroom=limit - _tail,
            rules=len(_rules_lines),
            longest_rule=max((len(l.encode()) for l in _rules_lines), default=0),
        )
        ev = next((i for i, l in enumerate(lines) if l.startswith("## 📎")), None)
        if ev is not None:
            # 🔴 2026-10-27 修：证据块首标记有两种形态，旧谓词只认第一种。
            #   ① 主体：`## 📎 铁律证据库` 段内的 `**── 证据 N ──**`（N=数字，按编号检索靠它）
            #   ② 变体：独立的 `## 📚 历史证据` 段内的 `**── 证据(历史 89) ──**`
            #      （对应规则已被合并删除，编号作废、明确声明「不与规则层对齐」）
            #   实测病根：2026-10-27 该文件规则 106 / 证据 107 → 差值 **−1**，而
            #   10-26 同一内容算成 **+1** → **同一份事实两天两个答案**，坏的正是
            #   「证据到底有几块」这个数。原因是 `evidence` 只数到 `## 📎` 段结束
            #   之前的块（107 个主体块），而末尾那个变体块位于 `## 📚` 段内，
            #   两种口径谁对「判据答不了」—— 必须由 memory_known_issues.json 的
            #   `count_includes_variant` **显式声明**，两种口径都算出来报给人看。
            #   主体计数谓词保持不变（判据⑧ 重复号检测与既有登记值都依赖它）；
            #   变体单独计数，绝不混进 `evidence` —— 一个谓词只答一件事。
            # ★ 2026-10-27 口径修正（本轮第 3 次翻车，必须写清）：
            #   `## 📎` 证据库段**到下一个 `## ` 标题就结束**（该文件实测 263→666），
            #   段内 107 个主体块；而 `## 📚 历史证据` 在 **777 行**，是**另一个独立段**，
            #   两者之间还夹着「注入上限」与「索引句原文存档」两段。
            #   旧写法把 `_hist` 当成「📎 段内某处」去找，于是主体切片一路吃到 777 行，
            #   把主体数算成 107 的同时把变体也算进主体 → 两个口径都偏，`_gap_alt` 成 −2。
            #   这正好复现了本轮要修的病根：**段边界不明确，计数口径就随口径漂**。
            _hist = next(
                (i for i in range(ev + 1, len(lines)) if lines[i].startswith("## ")),
                len(lines),
            )
            _harness = re.compile(r"^\*\*── 证据 \d+ ──\*\*")  # ① 主体：数字编号
            _variant = re.compile(r"^\*\*── 证据\s*[\(（]")  # ② 变体：`证据(历史 N)`
            _main = [l for l in lines[ev:_hist] if _harness.match(l)]
            info.update(
                ev=ev,
                evidence=len(_main),
                evidence_variant=sum(1 for l in lines[ev:] if _variant.match(l)),
            )
    return lines, info


def check(path: str, limit: int):
    """返回 (problems, info, notes)。

    notes 是「本文件专属的提示行」（如被豁免的原因），由 main() 在与本文件
    同屏的位置打印 —— 这就是 2026-10-24 改变签名的原因（原先在函数内 print，
    会印到上一个文件的标题下面）。
       为什么：main() 里 check() 在 `print(f"{tag} {f}")` **之前**调用 →
       内部 print 的豁免行会出现在**上一个文件的标题之下**，读者会把 B 的
       「规则↔证据差 +3」与「编号错位」读成**项目级**的问题（实测就是这样：
       项目级 71/71 明明相等，却挂着两条属于 B 的豁免）。豁免是「这一份文件
       被免检」的信息，归错文件等于给了另一份文件假安全感 —— 与
       「一个判据只答一件事」同族：**输出必须归到它真正描述的那个对象上**。
       现在改为返回 `notes`，由 main() 在统计行**之后**打印。
    """
    p = Path(path)
    problems = []
    notes = []  # 良性豁免说明，由调用方在正确位置打印（见 docstring）
    if not p.exists():
        # ★ 返回 info=None 而不是空 dict（2026-10-23 审计修）。
        #   原先返回 {}，而输出模板对 bytes/limit 用 %d、兜底值是字符串 "-"，
        #   于是打印阶段抛 TypeError：%d format: a real number is required, not str。
        #   崩溃点在 for f in files 的打印语句里 → 循环整体终止，
        #   **后续文件的真实违规一条都报不出来**（实测：第一个文件缺失时，
        #   第二个文件「缺速查索引」完全不显示）。rc 仍是 1（不误放），但诊断全丢。
        #   None 让调用方知道「这份没有统计可打」，与「解析失败」区分开。
        return [f"{path}: 文件不存在（未检查，勿当作通过）"], None, notes
    text = p.read_text(encoding="utf-8")
    lines, info = _layout(text, limit)

    idx = "" if info.get("idx_s") is None else "\n".join(lines[info["idx_s"] : info["idx_e"]])

    # ① 索引块存在 + 落在可见区
    if info.get("idx_s") is None:
        problems.append("缺少「速查索引」段（不可检索 = 尾部永久不可见）")
    elif info["index_end"] >= limit:
        problems.append(f"索引块结束偏移 {info['index_end']}B ≥ 上限 {limit}B → 索引自己也被截断")

    # ② 标题覆盖率
    if idx:
        miss = []
        for i, l in enumerate(lines):
            if not (l.startswith("## ") or l.startswith("### ")) or "速查索引" in l:
                continue
            toks = TOKEN.findall(re.sub(r"^#+\s*", "", l))
            if toks and not any(t in idx for t in toks):
                miss.append((i + 1, l[:60]))
        info["miss"] = miss
        if miss:
            problems.append("索引覆盖盲区 %d 处：%s" % (len(miss), miss[:3]))

    # ⑧ 证据块越界 / 编号重复（2026-10-26，disc-20261026-02）
    #   `_layout` 的证据计数只扫 `## 📎` 之后 → 落在规则层的证据块**完全不可见**，
    #   还让「规则↔证据差值」少算一个（差值一旦被 expected_gap 豁免，就永远看不见）。
    #   编号重复更直接：证据是按编号检索的，同号两条 = 检索方拿到的是**别人的**证据
    #   （同族 `2026-10-22-misaligned-evidence-index-silently-serves-wrong-forensics`）。
    ev_i = info.get("ev")
    if ev_i is not None:
        oob = [i for i, l in enumerate(lines[:ev_i]) if l.startswith("**── 证据 ")]
        if oob:
            msg = (
                f"证据块越界 {len(oob)} 处（行 {[i + 1 for i in oob[:3]]}）："
                "证据只能落在「## 📎」之后；越界块不计入证据数，规则↔证据差值会跟着偏"
            )
            if _known_issue_waived(path, "evidence_out_of_bounds"):
                notes.append(f"ℹ️ 已豁免（{KNOWN_ISSUES.name} 有登记）：{msg}")
            else:
                problems.append(msg)

        nums = []
        for line in lines[ev_i:]:
            m = re.match(r"^\*\*── 证据 (\d+) ──\*\*", line)
            if m:
                nums.append(int(m.group(1)))
        dup = sorted({n for n in nums if nums.count(n) > 1})
        if dup:
            show = "、".join(str(n) for n in dup[:5]) + ("…" if len(dup) > 5 else "")
            msg = f"证据编号重复：{show}（同号两条 → 按编号检索会拿到别的证据）"
            if _known_issue_waived(path, "evidence_duplicate_no"):
                notes.append(f"ℹ️ 已豁免（{KNOWN_ISSUES.name} 有登记）：{msg}")
            else:
                problems.append(msg)

    # ③ 规则层可见性 + ④ 规则↔证据对应
    if "rule_head" in info:
        off, n_rules = info["rule_off"], info["rules"]
        if off > limit:
            problems.append(
                f"规则层末条规则止于 {off}B > 上限 {limit}B → 有规则落在可见区外（溢出 {off - limit}B）"
            )
        n_ev = info.get("evidence")
        if n_ev is not None:
            # ④ 判据（2026-10-23 改口径）：不再要求「必须相等」，改为「差值为 0 或已登记」。
            #
            # 为什么改：规则层本来就可增删 —— 拆分（1 条拆 2 条，规则数 +1）、下沉
            #   （规则移出、证据保留，规则数 −1）都会让差值变化。原「必须相等」的假设
            #   在这种文件上不成立，于是每动一次结构就要么改登记、要么报假红。
            #   实测 2026-10-23：一天内差值从 0 → +6（拆分）→ +3（下沉），
            #   每次都得人工同步登记值，登记成了易变数。
            #
            # 但**不能**退化成「有登记就免检」（那就是永久绿灯）。保留的检测力是：
            #   差值必须与登记的 expected_gap **逐字相等**，变了就报 —— 这才是能抓住
            #   「突然丢了 10 个证据块」的东西。
            #
            # 允许负差值：证据多于规则 = 规则被下沉/删除但证据保留，是合法状态。
            gap = n_rules - n_ev
            # 🔴 2026-10-27 新增：登记值可以是**含变体块的口径**（见 memory_known_issues.json
            #   `count_includes_variant`）。动因：2026-10-26/27 同一文件同一内容，
            #   差值一天算 +1、一天算 0 —— 因为证据库里有 1 个 `**── 证据(历史 89) ──**`
            #   变体块，旧计数谓词带尾随空格，恰好在某个环节被算进/漏算。
            #   「哪个口径对」不是判据能答的（两口径各自自洽），**必须由登记值声明**；
            #   但声明之后差值仍须逐字相等 —— 否则这条豁免就成了永久绿灯。
            #   两个口径都不等时，两个数都报出来，免得人只看见一个数字以为是笔误。
            _entry4 = _known_issue_entry(path, "rules_evidence_gap")
            _n_var = info.get("evidence_variant", 0) or 0
            _gap_alt = n_rules - (n_ev + _n_var) if _n_var else None
            # ★ 幂等断言（2026-10-27 自查）：`count_includes_variant` 只改变**用哪个数去比**，
            #   绝不能单独构成豁免 —— 它必须与「按该口径算出的差值 == expected_gap」同时成立。
            #   写这段的理由：本轮首版把 `_expect_gap` 从同一段 entry 取，导致后面
            #   `entry = _known_issue_entry(...)` 拿到 None 时不进「登记缺字段」也不进
            #   「相等」分支，输出一句「登记期望差 0 ≠ 实测 -1」而 `_use_alt` 明明为真 ——
            #   即**豁免条件满足却仍报红**（同族 10-26「修与判各执一套口径」，这次是
            #   「同一函数里两处判定各执一套变量」）。已把判定收敛到 `_entry4` 单一来源。
            _use_alt = (
                _entry4 is not None
                and _entry4.get("count_includes_variant") is True
                and gap != 0
                and _gap_alt == _entry4.get("expected_gap")
            )
            _expect_gap = _entry4.get("expected_gap") if _entry4 is not None else None
            # ★ 2026-10-27 自查（当场第二次翻车）：首版写的是
            #   `if (gap == 0 and _expect_gap == 0) or (gap == 0 and not _use_alt)`
            #   —— 两个分支都以 `gap == 0` 为前提，于是 gap=−1 时明明 `_use_alt`
            #   为真，仍掉进 else 报红。病根：**把「登记的口径」写成了「登记的值」**
            #   （`gap==0` 是 10-27 的新值，口径字段是 `count_includes_variant`）。
            #   改法：差值 0 → 通过；否则**先看是否命中登记口径**，再比原值。
            if gap == 0:
                pass  # 完全相等，无需登记
            else:
                entry = _entry4  # 单一来源，不再重复查询
                # ★ 登记值必须归一到 int（2026-10-23 审计修）。
                #   手改 JSON 时写成 "3"（字符串）会让 `entry["expected_gap"] == gap`
                #   恒为 False，报出「登记期望差 3 ≠ 实测 +3」—— 3 ≠ 3，把人引向
                #   错误方向（以为数字变了，实际是类型变了）。
                eg_raw = entry.get("expected_gap") if entry is not None else None
                eg, type_bad = None, False
                if eg_raw is not None:
                    # 严格判类型，不做宽容转换：JSON 里写成 "3"（字符串）是**笔误**，
                    # 静默 int() 掉等于把笔误变成「没事」，下次照样写错。
                    # 本项目对「判不了」的一贯处置是明说，不是猜（见 _limit_for）。
                    # bool 是 int 的子类，单独排除，免得多 True/False 混进差值。
                    if isinstance(eg_raw, bool) or not isinstance(eg_raw, int):
                        type_bad = True
                    else:
                        eg = eg_raw

                if type_bad:
                    problems.append(
                        f"规则↔证据差值未登记：登记里 expected_gap 不是整数"
                        f"（{eg_raw!r}），无法比对；实测差值 {gap:+d}，"
                        f"请把 {KNOWN_ISSUES.name} 里的 expected_gap 改成整数"
                    )
                elif _use_alt:
                    notes.append(
                        f"ℹ️ 已豁免（{KNOWN_ISSUES.name} 有登记）：规则↔证据差 {gap:+d} 条"
                        f"（按登记口径**含变体块** {_n_var} 个计为 {_gap_alt:+d}，与登记值一致；"
                        f"{entry.get('accepted_at', '未记日期')}）"
                    )
                elif entry is not None and eg == gap:
                    notes.append(
                        f"ℹ️ 已豁免（{KNOWN_ISSUES.name} 有登记）：规则↔证据差 {gap:+d} 条，"
                        f"与登记值一致（{entry.get('accepted_at', '未记日期')}）"
                    )
                else:
                    if gap > 0:
                        why = f"规则比证据多 {gap} 条（可能拆分过规则，或证据块被删）"
                    else:
                        why = f"证据比规则多 {-gap} 个（可能规则被下沉/删除，但证据保留）"
                    if entry is not None:
                        if eg_raw is None:
                            # 登记存在但没写 expected_gap → 无法比对。
                            # 旧写法直接把 None 打进消息（「登记期望差 None ≠ 实测 +3」），
                            # 读者看不出该补什么。这里显式说要补字段。
                            why += "；登记缺 expected_gap 字段（无法比对），请补上具体差值"
                        else:
                            why += (
                                f"；登记期望差 {eg} ≠ 实测 {gap:+d}，登记已过期，请复核后更新或删除"
                            )
                    else:
                        why += "；未登记"
                    problems.append(f"规则↔证据差值未登记：{why}")

        # ⑤ 声明值 vs 实测值（声明是副本，副本会腐烂）—— 穷举全部声明点
        declared = []
        for m in re.finditer(r"(\d+)\s*条各一行", idx):
            declared.append(("索引头「N 条各一行」", int(m.group(1)), n_rules))
        for m in re.finditer(r"规则层\s*·\s*(\d+)\s*条一览", lines[info["rule_head"]]):
            declared.append(("规则层标题「N 条一览」", int(m.group(1)), n_rules))
        for m in re.finditer(r"止于\s*\*\*([\d,]+)B\*\*", idx):
            declared.append(("索引头「止于 NB」", int(m.group(1).replace(",", "")), off))
        for m in re.finditer(r"余量\s*≈\s*([\d,]+)B", idx):
            declared.append(("索引头「余量 ≈NB」", int(m.group(1).replace(",", "")), limit - off))
        for m in re.finditer(r"行\s*(\d+)\s*[–—\-]\s*(\d+)", idx):
            # 🔴 2026-10-26 修口径（同族「一个值两义」）：B 端必须用
            #   **末条规则行号**，不是 rule_last。`_layout` 里 rule_last 的口径是
            #   「规则层内最后一个非空行」（10-09 为 rule_off 的偏移计算而定），
            #   而人写「行 8–109」指的是**标题→末条规则**；当标题与末条规则之间
            #   没有散文时两者恒差 1，会让正确声明被判成「声明腐烂」——检测器在
            #   报一个它自己换算出来的数，而不是文件里的事实（假红诱导人去改对的）。
            #   A 端用标题行号（rule_head+1），B 端用「最后一条 `- ` 规则」的行号。
            #   ⚠️ 2026-10-26 二次修：上一版把 A 端写成 `_rule_lines_1b[0]`（首条规则行号），
            #   与上面这句注释不符 —— 正常文件里标题行与首条规则恒差 1，结果**任何**
            #   符合口径的声明（如 fixture 的「行 8–9」、真实 MEMORY.md 的「行 8–109」）
            #   都会被判「声明腐烂」= 恒假红。A 端恢复为 rule_head+1。
            #   若规则层无 bullet（极端畸形），B 端退回 rule_last 并保持可读。
            _rule_lines_1b = [
                i + 1
                for i in range(info["rule_head"] + 1, info["rule_end"])
                if lines[i].startswith("- ") and lines[i].strip()
            ]
            _a = info["rule_head"] + 1
            _b = _rule_lines_1b[-1] if _rule_lines_1b else info["rule_last"]
            declared.append(
                (
                    "索引头「行 A–B」",
                    (int(m.group(1)), int(m.group(2))),
                    (_a, _b),
                )
            )
        info["declared"] = declared

        # ⑥ 证据库小标题「共 N 条」声明（同一事实的第三处副本）
        if n_ev is not None:
            for m in re.finditer(r"共\s*(\d+)\s*条", "\n".join(lines[info["ev"] : info["ev"] + 6])):
                declared.append(("证据库小标题「共 N 条」", int(m.group(1)), n_ev))

        for label, val, actual in declared:
            if val != actual:
                problems.append(f"声明腐烂：{label} 声明 {val}，实测 {actual}")

        # ⑨ 索引头「每条≤NB」= 单条规则的字节预算（2026-10-26 新增）
        #   动因：用户级 MEMORY.md 的索引头写着「规则层按行排列(每条≤90B)」，
        #   而 `longest_rule` 实测 100B —— 该声明**从未被任何判据核对**，
        #   烂了至少 12 天无人发现。同族于 ⑤⑥：声明是副本，副本必须机器核对；
        #   也同族于「同一语义的值必须单一真源」——预算写在索引头，实测在 _layout，
        #   两者之间此前没有任何消费者。
        #   判据方向取 `≤`（预算可留余量）而不是 `==`：等价于「最长规则不得超过预算」，
        #   超了就喊。这样写规则的人要么压缩，要么显式调高预算，不会静默越界。
        for m in re.finditer(r"每条\s*≤\s*([\d,]+)\s*B", idx):
            cap = int(m.group(1).replace(",", ""))
            lr = info.get("longest_rule")
            if lr and lr > cap:
                problems.append(
                    f"声明腐烂：索引头「每条≤{cap}B」但已有一条 {lr}B 的规则"
                    f"（超 {lr - cap}B）—— 要么压缩该条，要么把预算改成实测值"
                )

        # ⑦ 证据编号 ↔ 规则顺序**对齐**（2026-10-20 新增：条数相等 ≠ 依次对齐）
        #   为什么必须加：契约是「证据编号 = 规则层第 N 条（同序）」，按需检索靠
        #   `grep -n "── 证据 N ──"`。10-14 实测整体偏移 +1、10-20 实测「中间插入
        #   11 条规则后整体偏移 −2」—— 两次 ④（条数）都是绿的，而取到的是**另一条**
        #   规则的取证，且不报错。④ 只比数量，补条数即可让它转绿，**错位就再也测不出**。
        #   口径（刻意不用单块阈值）：压缩后的规则是 ≤60B 索引句，与证据正文的词面
        #   重合度天然参差（实测 0.20~1.00），单块阈值必假红。改用**众数**：
        #   对每块取「最匹配的规则序号」，统计 (best_rule - block_no) 的众数；
        #   众数偏移 ≠ 0 且覆盖 ≥40% 块 ⇒ 整体错位（10-14 的 +1、10-20 的 −2 都
        #   覆盖 55%~95%，而正常文件是 90%+ 的 0）。单块噪声（实测 88 块里 4 块）
        #   不会构成众数，故不假红。
        if n_ev is not None and n_rules:
            _evs = []
            _lines_ev = [(i, _ln) for i, _ln in enumerate(lines) if _ln.startswith("**── 证据 ")]
            for _k, (_i, _l) in enumerate(_lines_ev):
                _end = _lines_ev[_k + 1][0] if _k + 1 < len(_lines_ev) else len(lines)
                # 🔴 用**声明出来的编号**（`**── 证据 N ──**` 里的 N），不是块的位置序号。
                #   10-20 首版用了 enumerate 位置 → 证伪实验里「把标签整体 +1」竟然全绿：
                #   位置没变、内容没变，变的正是**标签与内容的对应关系**，而这恰恰是
                #   要测的东西。用位置 = 测「内容顺序」，用标签 = 测「标签是否说真话」；
                #   契约要的是后者（`grep "── 证据 N ──"` 命中的是不是第 N 条规则）。
                _m = re.match(r"\*\*── 证据 (\d+) ──\*\*", _l)
                # 🔴 2026-10-26 修：原实现只看 `lines[_i+1:_end]`，把**同一行**的正文丢了。
                #   而实际记忆文件的块头后面直接跟正文（`**── 证据 N ──** 10-23 …`），
                #   于是这些块被当成空内容跳过 → ⑦ 只覆盖了"正文另起一行"的少数块，
                #   对齐率统计静默缺样本（缺得越多越像正常）。
                #   现把块头行的剩余部分并入块文本。
                _rest = re.sub(r"^\*\*── 证据 \d+ ──\*\*\s*", "", _l)
                _evs.append(
                    (
                        int(_m.group(1)) if _m else _k + 1,
                        "\n".join([_rest] + lines[_i + 1 : _end]),
                    )
                )
            _rtok = [
                TOKEN.findall(r)
                for r in lines[info["rule_head"] + 1 : info["rule_end"]]
                if r.startswith("- ") and r.strip()
            ]
            _offs = []
            for _n, _t in _evs:
                _tt = set(TOKEN.findall(_t))
                if not _tt:
                    continue
                _best, _bj = 0.0, None
                for _j, _rt in enumerate(_rtok, 1):
                    _s = set(_rt)
                    if not _s:
                        continue
                    _sc = len(_s & _tt) / len(_s)
                    if _sc > _best:
                        _best, _bj = _sc, _j
                if _bj is not None and _best >= EV_MATCH_MIN:
                    _offs.append(_bj - _n)
            if _offs:
                _mode = max(set(_offs), key=_offs.count)
                _share = _offs.count(_mode) / len(_offs)
                _zero = _offs.count(0) / len(_offs)
                info["ev_offset"] = (
                    _mode,
                    round(_share, 2),
                    len(_offs),
                    "zero=%d%%" % round(_zero * 100),
                )
                # 判据用「偏移 0 的占比」而不是「众数占比」——
                #   10-20 证伪实验：只把后段 39 块的标签 +1 时，众数仍是 0（占 53%），
                #   「众数≠0 且 ≥40%」会放行 44% 的错位。而正常文件三份实测 zero=99%/95%/93%
                #   （单块词面噪声 1~7 块），故取 80% 为线：留出 20% 容噪，又能抓住
                #   「过半块错位」这种真正让人取错证据的形态。
                if _zero < EV_ALIGN_MIN:
                    _desc = (
                        f"{_share:.0%} 的块偏移 {_mode:+d}" if _mode else f"仅 {_zero:.0%} 的块对齐"
                    )
                    _msg = (
                        f"证据编号错位：{_desc}（对齐率 {_zero:.0%} < 80%）"
                        f' → `grep "── 证据 N ──"` 会取到别的规则的取证（④ 只看条数，掩盖了它）'
                    )
                    if _known_issue_waived(path, "evidence_number_shift"):
                        notes.append(
                            f"ℹ️ 已豁免（{KNOWN_ISSUES.name} 有登记）：编号错位属已知状态，"
                            f"检索请按内容 grep"
                        )
                    else:
                        problems.append(_msg)

    # ⑩ 写入审计一致性（2026-10-29 挂巡检，原 handoff 遗留③）：
    #    磁盘 sha 必须与审计「最后一次走锁写入」的 new_sha 一致 —— 不一致 =
    #    有人绕过工具直写（P1-5 的探测判据，从一次性 CLI 升级为每日自动跑）。
    #    no-record（审计 2026-10-29 起算；历史写入、从未走锁的文件）不算失败。
    #    审计基础设施自身故障按 R044 fail-safe：报不通过，不许静默放行 ——
    #    「审计挂了还绿灯」恰恰是本判据要消灭的假安全感。
    try:
        import memory_lock as _ml

        _verdict, _vmsg = _ml._verify(p)
        if _verdict == "unaudited-write":
            problems.append(f"未走锁直写：{_vmsg}")
    except Exception as _e:  # noqa: BLE001
        problems.append(f"审计校验自身故障（fail-safe，不当作通过）：{type(_e).__name__}: {_e}")
    return problems, info, notes


def fix(path: str, limit: int):
    """用实测值回写全部声明点，迭代到稳定。返回 (改动列表, 轮数)。"""
    p = Path(path)
    if not p.exists():
        return [(path, "文件不存在", "")], 0
    # 🔴 2026-10-16 新增「合理性闸门」：修复器**绝不把解析失败固化成文件内容**。
    #   事故（当日实测）：一次批量排印改写把规则行的 bullet `- ` 的空格一起删掉，
    #   规则行变成 `-🔴 …`；_layout 的判据是 `l.startswith('- ')` → 数出 rules=0；
    #   而本函数**照单写入** → 文件里出现「规则层 0 条各一行」「0 条一览」。
    #   判据用「两个独立口径必须一致」而不是「数出来是 0」——因为损坏通常只吃掉
    #   **部分** bullet（实测破坏后仍有 5 条 `- ` 幸存 → 只判 0 会放过它，
    #   而 --fix 会把 5 写进「N 条各一行」，同样是固化一个解析 bug）。
    #   两个口径：严格 `- ` / 宽松 `-` 后可有空白（容忍 bullet 空格被删）。
    _, info0 = _layout(p.read_text(encoding="utf-8"), limit)
    if "rule_head" in info0:
        _lines0 = p.read_text(encoding="utf-8").split("\n")
        _sec = _lines0[info0["rule_head"] + 1 : info0.get("rule_end", len(_lines0))]
        _strict = sum(1 for l in _sec if l.startswith("- "))
        _robust = sum(1 for l in _sec if re.match(r"-\s*\S", l))
        n_r, off = info0.get("rules"), info0.get("rule_off")
        if not n_r or _robust != _strict:
            return [
                (
                    path,
                    f"🔴 拒绝回写：规则层解析口径不一致（严格 `- ` = {_strict} 条 / 宽松 `-` = {_robust} 条）",
                    "疑似 bullet 语法损坏 → 不写盘，先修文件",
                )
            ], 0
        if not off or off <= 0 or off > info0["bytes"]:
            return [
                (
                    path,
                    f"🔴 拒绝回写：规则层结束偏移 {off} 不合常理（文件 {info0['bytes']}B）",
                    "疑似 layout 解析失败 → 不写盘",
                )
            ], 0
    changes = []
    for _ in range(MAX_FIX_ROUNDS):
        text = p.read_text(encoding="utf-8")
        lines, info = _layout(text, limit)
        if "rule_head" not in info:
            break
        off, n_rules, n_ev = info["rule_off"], info["rules"], info.get("evidence")
        new = list(lines)
        rounds = []

        def sub(i, pattern, repl, tag):
            before = new[i]
            after = re.sub(pattern, repl, before)
            if after != before:
                rounds.append((tag, before.strip()[:90], after.strip()[:90]))
                new[i] = after

        # 索引块：条数 / 止于 / 余量 / 行范围
        # 🔴 2026-10-26：行范围必须与判据⑤ **同一口径**（A=**标题行** rule_head+1，
        #   B=末条规则行），否则 --fix 会把「按 rule_last 算的 B 端」写回文件，而下一轮
        #   check 又用「末条规则行」去比 —— 修与判各执一套口径，结果是**每跑一次就翻一次脸**
        #   （实测：第一次 --fix 把 9 改成 8，第二次又改回 9，用户会以为文件在自愈）。
        # ⚠️ 同日二次发生：上一版把 A 端写成 `_rl[0]`（首条规则行），判据却按
        #   `rule_head+1`（标题行）比较 → 差 1 → 写 25 / 判 24 的死循环（--fix 认为
        #   「已是 25 无需改」，check 认为「应 24」）。A/B 两端现已统一：
        #   A=标题行（与用户真实写法「行 8–109」「行 24–96」一致），B=末条规则行。
        _rl = [
            i + 1
            for i in range(info["rule_head"] + 1, info["rule_end"])
            if lines[i].startswith("- ") and lines[i].strip()
        ]
        _rng = f"行 {info['rule_head'] + 1}–{_rl[-1] if _rl else info['rule_last']}"
        for i in range(info["idx_s"], info["idx_e"]):
            sub(i, r"(\d+)\s*条各一行", f"{n_rules} 条各一行", "索引头条数")
            sub(i, r"止于\s*\*\*([\d,]+)B\*\*", f"止于 **{off:,}B**", "索引头止字节")
            sub(i, r"余量\s*≈\s*([\d,]+)B", f"余量 ≈{limit - off:,}B", "索引头余量")
            sub(i, r"行\s*(\d+)\s*[–—\-]\s*(\d+)", _rng, "索引头行范围")
        # 规则层标题条数
        sub(info["rule_head"], r"(\d+)\s*条一览", f"{n_rules} 条一览", "规则层标题条数")
        # 证据库小标题「共 N 条」
        if n_ev is not None:
            for i in range(info["ev"], min(info["ev"] + 6, len(new))):
                sub(i, r"共\s*(\d+)\s*条", f"共 {n_ev} 条", "证据库共N条")

        if not rounds:
            break
        changes.extend(rounds)
        # 🔴 2026-10-26：原为 `p.write_text(...)`（无锁、无原子、无比对）——
        #   写入口 memory_add_rule 早就有 flock+原子写，唯独这里没有，于是
        #   「别覆盖别人的改动」这条语义在仓库里有两套强度不同的实现。
        #   现改为 CAS 写：expect_sha 是本轮**刚读到的**文本指纹，期间被人改过就抛
        #   ConcurrentWriteError → 放弃本轮、下一轮重新读（最多 MAX_FIX_ROUNDS 轮）。
        #   每轮都重读，所以不需要额外持锁：输的一方会干净地退出，不产生半截写入。
        try:
            memory_lock.atomic_write(p, "\n".join(new), expect_sha=memory_lock.sha1_text(text))
        except memory_lock.ConcurrentWriteError as e:
            print(f"   ⚠️ {p.name}: {e}；本轮跳过，重新读取后重试")
            continue
    return changes, len(changes)


def main():
    # 默认纯读、加 --fix 才写盘；但 --help 不该触发一次全量判据检查。
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print((__doc__ or "").strip())
        return 0
    argv = sys.argv[1:]
    do_fix = "--fix" in argv

    # --limit 显式指定上限（2026-10-23 审计加）。
    # 为什么需要它：原先未登记的文件会被静默按 7353B 判，而写入口
    # memory_add_rule._limit_for 在未登记时是**拒绝写入、绝不猜**的。
    # 同一套件两种相反策略，检查器会在真实上限更大时少算余量（报假红），
    # 在真实上限更小时多算余量（**误放**）。现在与写入口对齐：不猜，给 --limit 才判。
    cli_limit = None
    if "--limit" in argv:
        i = argv.index("--limit")
        try:
            cli_limit = int(argv[i + 1])
        except (IndexError, ValueError):
            print("🔴 --limit 需要一个整数字节值，例如 --limit 7757", file=sys.stderr)
            return 2
        if cli_limit <= 0:
            print(f"🔴 --limit 必须为正数，收到 {cli_limit}", file=sys.stderr)
            return 2
        del argv[i : i + 2]

    files = [a for a in argv if a != "--fix"] or DEFAULT_FILES
    bad = 0
    frozen = 0
    usage_error = False
    for f in files:
        # ★ 先判存在性，再判上限（2026-10-23 审计修）。
        #   反过来会把「文件不存在」误报成「未登记上限，拒绝猜测」——
        #   缺文件往往恰恰因为路径失效，那时它的上限当然也查不到。
        if Path(f).exists():
            limit = DEFAULT_LIMITS.get(f) or cli_limit
            if limit is None:
                print(
                    f"🔴 {f} 不在内置上限表，拒绝猜测上限 —— **该文件未检查**。\n"
                    f"   请用 --limit <字节> 显式指定；拿别的文件的上限顶替会误判\n"
                    f"   （实测过：项目级真实上限 16,474B，按 7,353B 判会少算 9,121B 余量）。",
                    file=sys.stderr,
                )
                usage_error = True
                continue
        else:
            limit = cli_limit or 0  # check() 遇缺失文件立即返回，limit 不参与计算
        if do_fix:
            changes, _ = fix(f, limit)
            print(f"🔧 {f}")
            if not changes:
                print("   无声明需要回写")
            for tag, before, after in changes:
                print(f"   · {tag}\n     - {before}\n     + {after}")
        problems, info, notes = check(f, limit)
        # ★ 2026-10-27 三分支（原为二元 "✅ if not problems else 🔴"）：
        #   健康但已冻结/非注入源的文件打 🟡 而非 ✅。判定与退出码**完全不变**，
        #   只改「绿灯的措辞」——因为把废弃副本报成 ✅ 会让人以为它也在被维护。
        #   判定逻辑在 tag_for() 里，便于单测覆盖「frozen + problems → 🔴」。
        tag = tag_for(problems, f)
        if tag == "🟡":
            frozen += 1
        print(f"{tag} {f}")
        if tag == "🟡":
            print("   ⓘ 已冻结·非注入源：本文件不再被任何注入消费，仅作历史对照")
            print(
                "     （依据 references/memory_two_copy_consistency.md；实际注入的是 user-*/MEMORY.md）"
            )
        # ★ 只有拿到 info 才打统计行（2026-10-23 审计修）。
        #   文件缺失/解析失败时 info 为 None，此时**跳过统计但继续报问题**——
        #   原先无条件打印，模板里的 %d 撞上兜底字符串 "-" 直接抛 TypeError，
        #   把整个循环连同后续文件一起带走。
        if info is not None:
            print(
                "   %(bytes)dB | 上限 %(limit)dB | 索引止 %(index_end)sB | 规则止 %(rule_off)sB"
                " | 可见余量 %(headroom)sB | 规则 %(rules)s 条 / 证据 %(evidence)s 块"
                % {
                    k: info.get(k, "-")
                    for k in (
                        "bytes",
                        "limit",
                        "index_end",
                        "rule_off",
                        "headroom",
                        "rules",
                        "evidence",
                    )
                }
            )
        # ★ 豁免说明在**统计行之后**打印（2026-10-24 修）。
        #   原来由 check() 内部打印 → 归到上一个文件标题下（见 check 的 docstring）。
        for nt in notes:
            print(f"   {nt}")
        for pr in problems:
            print(f"   → {pr}")
        bad += len(problems)
    tail = "全部通过" if not bad else f"共 {bad} 项不通过"
    if frozen:
        tail += f"（其中 {frozen} 项为已冻结副本 🟡，不计入不通过）"
    print(tail)
    if usage_error:
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
