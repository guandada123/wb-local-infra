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
  ④ 若含「铁律证据库」：证据块数 == 规则行数（规则↔证据一一对应，防拆层时丢条目）
  ⑤ 若索引头/规则层标题**声明了**条数、规则止字节、余量或行范围：声明值 == 实测值
     （09-30 新增：09-29 新增 2 条铁律后，索引头仍写「60 条各一行」而实测 62 条，
       脚本只报实测值、不比对声明 → **声明静默腐烂、无人发现**。同族于铁律
       「同一事实只允许一处自由」：声明是副本，副本必须机器核对。）
  ⑥ 证据库小标题若声明「共 N 条」：声明值 == 证据块实测数
     （10-08 新增：⑤ 只覆盖了「索引头/规则层标题」两处声明，**漏了证据库小标题**这第三处
       → 用户级写「共 66 条」实测 72 块、项目级写「共 58 条」实测 63 块，两处各腐烂
       6/5 天无人发现。教训：同族判据必须**穷举同一事实的全部声明点**，否则
       「已机器化」只是覆盖了一个副本，剩下的照烂。）

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
import re
import sys
from pathlib import Path

# 实测注入上限（skill context-health-cleanup Step 0.1/0.4；换机器/换版本须重新实测）
DEFAULT_LIMITS = {
    '/Users/guan/.workbuddy/MEMORY.md': 7353,
    '/Users/guan/WorkBuddy/Claw/.workbuddy/memory/MEMORY.md': 16474,
    # 🔴 2026-10-14 新增：这才是**实际被注入**的用户级记忆（平台 Layer 2；旧路径
    #   ~/.workbuddy/MEMORY.md 自 10-11 起已冻结、不再被任何注入消费 → 只查旧路径＝假绿灯）。
    #   上限 7,913B 为 2026-10-14 用「当日注入块末尾原文串回定位」实测（skill Step 0.1/0.4），
    #   换机器/换版本/换注入预算须重新实测——**不许手算，也不许把它当恒定值**。
    '/Users/guan/.workbuddy/user-24688a34-03ff-4299-8736-08d5a6585c6b-personal/MEMORY.md': 7913,
}
DEFAULT_FILES = list(DEFAULT_LIMITS)

TOKEN = re.compile(r'[\u4e00-\u9fa5]{2,6}|[A-Za-z_][A-Za-z0-9_.]{2,}')
EVID_MARK = '铁律证据库'
MAX_FIX_ROUNDS = 5


def _layout(text, limit):
    """算出索引/规则层/证据库的位置与实测值（纯函数，供 check 与 fix 共用）。"""
    lines = text.split('\n')
    info = {'bytes': len(text.encode()), 'limit': limit}
    idx_lines = [i for i, l in enumerate(lines) if '速查索引' in l]
    if not idx_lines:
        info.update(idx_s=None, idx_e=None, index_end=None)
    else:
        s = idx_lines[0]
        e = next((i for i in range(s + 1, len(lines)) if lines[i].startswith('## ')), len(lines))
        info.update(idx_s=s, idx_e=e, index_end=len('\n'.join(lines[:e]).encode()) + 1)
    rule_head = next((i for i, l in enumerate(lines)
                      if l.startswith('## ') and '铁律' in l and not l.startswith('## 📎')), None)
    if rule_head is not None:
        rule_end = next((i for i in range(rule_head + 1, len(lines))
                         if lines[i].startswith('## ')), len(lines))
        # 行范围口径（10-09 固化，防两义）：A=规则层标题行(1-based)，
        # B=规则层内**最后一个非空行**(1-based)——不含标题与下一节之间的空行，
        # 因为「行 24–88」在人读时指的是标题到末条规则，不是标题到空行。
        rule_last = next((i for i in range(rule_end - 1, rule_head, -1) if lines[i].strip()),
                         rule_head) + 1  # 转 1-based：与 A 同口径
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
        _tail = len('\n'.join(lines[:rule_last]).encode())
        # 🔴 2026-10-17 新增 longest_rule：**物理口径**（推算术，非阈值）。
        #   判据③ 回答「规则现在可不可见」；本字段回答**另一个问题**——
        #   「余量还够不够装下一条最长的规则」。两者不同口径，故**只作信息输出、
        #   不参与 rc**（同 Step 0.30：一个判据只答一件事）。用途：把「余量 238B
        #   到底够不够」从手工推算变成机器给数 —— 实测 B 最长规则 261B > 238B，
        #   即「再加最长那条就会挤出可见区」是可机器判定的，无须人工估。
        #   口径与 rules 完全一致（同一切片、同一 `startswith('- ')` 谓词），
        #   避免「同一事实两处口径」（Step 0.30 的病根）。
        _rules_lines = [l for l in lines[rule_head + 1:rule_end]
                        if l.startswith('- ') and l.strip()]
        info.update(rule_head=rule_head, rule_end=rule_end,
                    rule_last=rule_last,
                    rule_off=_tail,
                    rule_section_end=len('\n'.join(lines[:rule_end]).encode()) + 1,
                    headroom=limit - _tail,
                    rules=len(_rules_lines),
                    longest_rule=max((len(l.encode()) for l in _rules_lines), default=0))
        ev = next((i for i, l in enumerate(lines) if l.startswith('## 📎')), None)
        if ev is not None:
            info.update(ev=ev, evidence=sum(1 for l in lines[ev:] if l.startswith('**── 证据 ')))
    return lines, info


def check(path: str, limit: int):
    p = Path(path)
    problems = []
    if not p.exists():
        return [f'{path}: 文件不存在'], {}
    text = p.read_text(encoding='utf-8')
    lines, info = _layout(text, limit)

    idx = '' if info.get('idx_s') is None else '\n'.join(lines[info['idx_s']:info['idx_e']])

    # ① 索引块存在 + 落在可见区
    if info.get('idx_s') is None:
        problems.append('缺少「速查索引」段（不可检索 = 尾部永久不可见）')
    elif info['index_end'] >= limit:
        problems.append(f"索引块结束偏移 {info['index_end']}B ≥ 上限 {limit}B → 索引自己也被截断")

    # ② 标题覆盖率
    if idx:
        miss = []
        for i, l in enumerate(lines):
            if not (l.startswith('## ') or l.startswith('### ')) or '速查索引' in l:
                continue
            toks = TOKEN.findall(re.sub(r'^#+\s*', '', l))
            if toks and not any(t in idx for t in toks):
                miss.append((i + 1, l[:60]))
        info['miss'] = miss
        if miss:
            problems.append('索引覆盖盲区 %d 处：%s' % (len(miss), miss[:3]))

    # ③ 规则层可见性 + ④ 规则↔证据对应
    if 'rule_head' in info:
        off, n_rules = info['rule_off'], info['rules']
        if off > limit:
            problems.append(f'规则层末条规则止于 {off}B > 上限 {limit}B → 有规则落在可见区外（溢出 {off - limit}B）')
        n_ev = info.get('evidence')
        if n_ev is not None and n_ev != n_rules:
            problems.append(f'规则↔证据不匹配：规则 {n_rules} 条 vs 证据块 {n_ev} 个（拆层时可能丢条目）')

        # ⑤ 声明值 vs 实测值（声明是副本，副本会腐烂）—— 穷举全部声明点
        declared = []
        for m in re.finditer(r'(\d+)\s*条各一行', idx):
            declared.append(('索引头「N 条各一行」', int(m.group(1)), n_rules))
        for m in re.finditer(r'规则层\s*·\s*(\d+)\s*条一览', lines[info['rule_head']]):
            declared.append(('规则层标题「N 条一览」', int(m.group(1)), n_rules))
        for m in re.finditer(r'止于\s*\*\*([\d,]+)B\*\*', idx):
            declared.append(('索引头「止于 NB」', int(m.group(1).replace(',', '')), off))
        for m in re.finditer(r'余量\s*≈\s*([\d,]+)B', idx):
            declared.append(('索引头「余量 ≈NB」', int(m.group(1).replace(',', '')), limit - off))
        for m in re.finditer(r'行\s*(\d+)\s*[–—\-]\s*(\d+)', idx):
            declared.append(('索引头「行 A–B」',
                             (int(m.group(1)), int(m.group(2))),
                             (info['rule_head'] + 1, info['rule_last'])))
        info['declared'] = declared

        # ⑥ 证据库小标题「共 N 条」声明（同一事实的第三处副本）
        if n_ev is not None:
            for m in re.finditer(r'共\s*(\d+)\s*条', '\n'.join(lines[info['ev']:info['ev'] + 6])):
                declared.append(('证据库小标题「共 N 条」', int(m.group(1)), n_ev))

        for label, val, actual in declared:
            if val != actual:
                problems.append(f'声明腐烂：{label} 声明 {val}，实测 {actual}')
    return problems, info


def fix(path: str, limit: int):
    """用实测值回写全部声明点，迭代到稳定。返回 (改动列表, 轮数)。"""
    p = Path(path)
    if not p.exists():
        return [(path, '文件不存在', '')], 0
    # 🔴 2026-10-16 新增「合理性闸门」：修复器**绝不把解析失败固化成文件内容**。
    #   事故（当日实测）：一次批量排印改写把规则行的 bullet `- ` 的空格一起删掉，
    #   规则行变成 `-🔴 …`；_layout 的判据是 `l.startswith('- ')` → 数出 rules=0；
    #   而本函数**照单写入** → 文件里出现「规则层 0 条各一行」「0 条一览」。
    #   判据用「两个独立口径必须一致」而不是「数出来是 0」——因为损坏通常只吃掉
    #   **部分** bullet（实测破坏后仍有 5 条 `- ` 幸存 → 只判 0 会放过它，
    #   而 --fix 会把 5 写进「N 条各一行」，同样是固化一个解析 bug）。
    #   两个口径：严格 `- ` / 宽松 `-` 后可有空白（容忍 bullet 空格被删）。
    _, info0 = _layout(p.read_text(encoding='utf-8'), limit)
    if 'rule_head' in info0:
        _lines0 = p.read_text(encoding='utf-8').split('\n')
        _sec = _lines0[info0['rule_head'] + 1:info0.get('rule_end', len(_lines0))]
        _strict = sum(1 for l in _sec if l.startswith('- '))
        _robust = sum(1 for l in _sec if re.match(r'-\s*\S', l))
        n_r, off = info0.get('rules'), info0.get('rule_off')
        if not n_r or _robust != _strict:
            return [(path,
                     f'🔴 拒绝回写：规则层解析口径不一致（严格 `- ` = {_strict} 条 / 宽松 `-` = {_robust} 条）',
                     '疑似 bullet 语法损坏 → 不写盘，先修文件')], 0
        if not off or off <= 0 or off > info0['bytes']:
            return [(path, f'🔴 拒绝回写：规则层结束偏移 {off} 不合常理（文件 {info0["bytes"]}B）',
                     '疑似 layout 解析失败 → 不写盘')], 0
    changes = []
    for _ in range(MAX_FIX_ROUNDS):
        text = p.read_text(encoding='utf-8')
        lines, info = _layout(text, limit)
        if 'rule_head' not in info:
            break
        off, n_rules, n_ev = info['rule_off'], info['rules'], info.get('evidence')
        new = list(lines)
        rounds = []

        def sub(i, pattern, repl, tag):
            before = new[i]
            after = re.sub(pattern, repl, before)
            if after != before:
                rounds.append((tag, before.strip()[:90], after.strip()[:90]))
                new[i] = after

        # 索引块：条数 / 止于 / 余量 / 行范围
        for i in range(info['idx_s'], info['idx_e']):
            sub(i, r'(\d+)\s*条各一行', f'{n_rules} 条各一行', '索引头条数')
            sub(i, r'止于\s*\*\*([\d,]+)B\*\*', f'止于 **{off:,}B**', '索引头止字节')
            sub(i, r'余量\s*≈\s*([\d,]+)B', f'余量 ≈{limit - off:,}B', '索引头余量')
            sub(i, r'行\s*(\d+)\s*[–—\-]\s*(\d+)',
                f"行 {info['rule_head'] + 1}–{info['rule_last']}", '索引头行范围')
        # 规则层标题条数
        sub(info['rule_head'], r'(\d+)\s*条一览', f'{n_rules} 条一览', '规则层标题条数')
        # 证据库小标题「共 N 条」
        if n_ev is not None:
            for i in range(info['ev'], min(info['ev'] + 6, len(new))):
                sub(i, r'共\s*(\d+)\s*条', f'共 {n_ev} 条', '证据库共N条')

        if not rounds:
            break
        changes.extend(rounds)
        p.write_text('\n'.join(new), encoding='utf-8')
    return changes, len(changes)


def main():
    argv = sys.argv[1:]
    do_fix = '--fix' in argv
    files = [a for a in argv if a != '--fix'] or DEFAULT_FILES
    bad = 0
    for f in files:
        limit = DEFAULT_LIMITS.get(f, 7353)
        if f not in DEFAULT_LIMITS:
            print(f'⚠️ {f} 不在内置上限表 → 按 7353B 处理（**别对副本跑 --fix，会写错余量**）')
        if do_fix:
            changes, _ = fix(f, limit)
            print(f'🔧 {f}')
            if not changes:
                print('   无声明需要回写')
            for tag, before, after in changes:
                print(f'   · {tag}\n     - {before}\n     + {after}')
        problems, info = check(f, limit)
        tag = '✅' if not problems else '🔴'
        print(f'{tag} {f}')
        print('   %(bytes)dB | 上限 %(limit)dB | 索引止 %(index_end)sB | 规则止 %(rule_off)sB'
              ' | 可见余量 %(headroom)sB | 规则 %(rules)s 条 / 证据 %(evidence)s 块' % {
                  k: info.get(k, '-') for k in
              ('bytes', 'limit', 'index_end', 'rule_off', 'headroom', 'rules', 'evidence')})
        for pr in problems:
            print(f'   → {pr}')
        bad += len(problems)
    print(('全部通过' if not bad else f'共 {bad} 项不通过'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
