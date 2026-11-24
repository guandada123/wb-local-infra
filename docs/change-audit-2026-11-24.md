# 变更审计：2026-11-23 12:11 → 2026-11-24 20:30

> 审计对象：本次对话中产生的**全部**变更（两个仓库 + 系统级改动 + 一条定时任务）
> 方法：git 逐提交取证 + 运行态回读 + 代码走查。证据分三类并逐条标注：
> **【实测】** 有命令输出；**【推导】** 读代码得出、未实跑；**【不可确认】** 拿不到证据。

## 零、一句话结论

13 个提交（`wb-local-infra`）+ 1 个（`workbuddy-user-memory`），涉及 14 个文件、约 +2.5k 行。
**没有数据丢失，没有不可逆破坏**（抹盘弹窗被 Esc 取消、FileVault 按指令关闭、临时卷已删并复核）。

但审计出 **5 处 P1**，其中 2 处是**闸门自己的验证逻辑在给假绿灯** ——
闸门不可信比没有闸门更危险，这两条应当优先修。

## 一、变更时间线（按发生顺序）

| # | 时间 | 提交 | 主要文件 | 目的 | 影响面 | 验证 |
|---|---|---|---|---|---|---|
| 1 | 11-24 10:05 | `39c2130` | `bin/hc-create-check.py`、`docs/backup-hub-db.md`、README | 给备份作业建独立 healthchecks check（外部观测） | 新增 1 个外部 check；不改作业逻辑 | 【实测】面板 Last Duration 17s、User-Agent 匹配 |
| 2 | 11-24 10:28 | `84300d0` | `bin/wb-autoloop-backup.py`、tests、README、docs | 把 `~/.local/etc/*.conf` 纳入快照（A12 集合比对） | 备份覆盖面扩大；A 系列校验 12 项 | 【实测】12/12 + 15/15 故障注入 |
| 3 | 11-24 12:29 | `cb3706e` | `bin/wb-offsite-mirror.py`（新）、plist、launchd/active.txt、tests、docs、README | 只此一份的数据（Claw/output、projects、memory）镜像到内盘 | **新增每日 03:20 作业**；内盘占 6.5G | 【实测】V1–V6 全过、32,829 文件 |
| 4 | 11-24 12:39 | `b1e190e` | `bin/wb-offsite-mirror.py`、`bin/wb-autoloop-backup.py`、docs、tests | V0 容量闸门：写前算空间，不足则一字节不写 | 镜像写盘前多一道判据；失败 rc=3 | 【实测】"待写 0.3G / 余 58.2G"；自检 25 项 |
| 5 | 11-24 12:46 | `d64101f` | `bin/wb-offsite-mirror.py`、docs、tests、README | 补 `workbuddy.db`(261MB) —— 全机无第二份 | DB_ITEMS 走 sqlite backup 快照 + V6 校验 | 【实测】副本 262MB/20 表/quick_check=ok |
| 6 | 11-24 16:18 | `6b0859e` | `docs/agentic-os-gap-audit.md`、`docs/session-audit-2026-11-24.md` | Agentic OS 文章对照片 + 本会话审计（19 条） | 纯文档 | 【实测】计数 awk 复核 4/8/7=19 |
| 7 | 11-24 16:46 | `aa22f5b` | `bin/wb-ui-guard.py`（新）、tests、docs、README | GUI 物理闸门（D1 前台禁令 / D2 危险词 / D3 机密词） | **改 `/opt/homebrew/bin/cliclick`**；所有 cliclick 调用 +0.3~1.6s | 【实测】D1 拦截 rc=3、直通 rc=0 |
| 8 | 11-24 16:50 | `ecaa34f` | `docs/session-audit-2026-11-24.md` | 撤回两条自己判错的"待办" | 纯文档 | 【实测】读盘复核 USER.md 早已修正、/var/root 文件不存在 |
| 9 | 11-24 17:05 | `212893a` | `bin/wb-offsite-mirror.py`、docs、tests、**`patches/…-cancel-false.patch`（删除）** | 镜像日志加时间戳 | 日志格式变；**夹带他人删除** | 【实测】变异测试反证；55 项测试 |
| 10 | 11-24 17:05 | `ad3c29c` | `docs/session-audit-2026-11-24.md` | 记录"`git add -A` 夹带他人删除"为第 20 条 | 纯文档 | 【实测】计数 4/8/8=20 |
| 11 | 11-24 17:54 | `2911aaf` | `bin/wb-ui-guard.py`、tests、docs、README | D1 改用 bundle id 兜底（钥匙串改名「密码」后名字表失效） | 拦截准确性；新增 DENY_BUNDLES | 【实测】实弹 Passwords → rc=3 |
| 12 | 11-24 19:46 | `8c0cd5d` | `bin/wb-ui-guard.py`、tests、docs | 扫描范围从「只看前台」改为「前台 + 系统对话框属主」 | 闸门能看见浮层框；+1.3s 最坏开销 | 【实测】5 个模态全部识别 |
| 13 | 11-24 20:08 | `0d7d046` | `docs/gui-automation-guard.md` | 写明 z 序缺口与三条失败路径 | 纯文档 | 【实测】撤回 rects 后 12/12 |
| 14 | 11-24 16:50 | `84646e8`(档案仓) | `USER.md` | 补"备份与加密最终结论"五条，防重复劝 | 影响后续所有会话的上下文 | 【实测】`check_memory_budget.py` 通过 |

系统级改动（不在 git 内）：`/opt/homebrew/bin/cliclick` 被换成 4 行 shim；`~/.local/etc/wb-ui-guard.json` 记录真身路径。
一次性任务：`31480701-…`，2026-11-25 03:35 回读镜像日历触发。

## 二、逻辑错误与缺陷

### P1（假绿灯 / 文档失真，必须修）

| # | 位置 | 问题 | 证据 | 影响 |
|---|---|---|---|---|
| P1-1 | `bin/wb-ui-guard.py:402-415` `cmd_install` | 接线自检用 `cliclick p` 验证，但此刻 `cliclick` 已指向 shim → **自检本身要过闸门**。实测出现矛盾：同一前台（`Passwords`）下，单独 `cliclick p` 返回 `rc=3`，而 `install-interlock` 却报"已接线成功"两次中的一次 | 现象【实测】，成因【不可确认】 | 安装结论不可靠；若真回滚过，用户会以为装好了 |
| P1-2 | `tests/test_deploy_sync.py:904` | `assertIn(p.returncode, (0, 7))` —— **rc=7 正是"未接线"**，测试却判通过。名为「self asserts wiring」的测试对"没接线"无能为力 | 【推导】读断言即明 | 接线断了自己不知道，属典型假绿灯 |
| P1-3 | `docs/offsite-mirror.md:153` | 写"一次运行共三次全量遍历"。代码实际：`capacity_preflight` 每项 2 次 walk（源+落点），`verify` 至少再来 2 次 | 【实测】`grep walk(` 行号 18/20 与 verify 体内 6 处 | 性能预期被低估；15 分钟→实际可能更久 |
| P1-4 | `docs/backup-hub-db.md:172` | 写"同时通过 10 项校验"，实际 `A1`–`A12` 共 **12** 项 | 【实测】`grep -o '"A[0-9]*"'` 去重 = 12 | 文档与代码不一致，验收口径失真 |
| P1-5 | 提交 `212893a` | 夹带 `patches/agent-autoloop-later-cancel-false.patch` 的删除（他人 17:02 改名后遗留的未提交改动），提交信息未提 | 【实测】`git show --stat` | 归属错误；已入审计第 20 条，历史不改写 |

### P2（过度拒绝 / 健壮性）

| # | 位置 | 问题 | 证据 |
|---|---|---|---|
| P2-1 | `DENY_BUNDLES` | 含 `com.apple.MobileSMS`（信息），**无任何证据支撑**，是我照"敏感类 App"顺手加的 | 【推导】代码可读；无事故记录 |
| P2-2 | `SECRET_CN` | `("恢复密钥", "密钥")` —— `"密钥"` 过宽且已包含前者（冗余）。任何含"密钥"的对话框（如钥匙串口令、SSH 私钥口令）都会被判 SECRET 且**故意不按 Esc** | 【推导】代码可读 |
| P2-3 | `real_cliclick()` | 回退路径硬编码 `Cellar/cliclick/5.1`。若 brew 升级到 5.2，state 里的 5.1 路径消失 → 回退到不存在的路径 → `forward` 报"找不到真 cliclick"，**易被误判为未安装** | 【推导】读代码；brew 升级未实测 |
| P2-4 | `/opt/homebrew/bin/cliclick` shim | `exec python3 …` 依赖 PATH 里有 `python3`。最小 PATH（如某些 cron/launchd）下可能失败 | 【推导】shim 内容 |
| P2-5 | 扫描开销 | 每次 cliclick 调用固定 +0.32s（无模态）、最坏 +1.6s（有模态）。文档写 1.6s，未写常态值 | 【实测】`time` 两次 |
| P2-6 | 一次性任务 `31480701` | 创建时被自动附带 7 个 `connectorIds`（feishu/github/tencent-docs/tmeet/tushare/westock/zsxq），非我请求，任务本身不需要 | 【实测】创建返回值 |

### P3（整洁 / 可维护）

| # | 位置 | 问题 |
|---|---|---|
| P3-1 | `test_process_names_fetched_before_by_name` | 只断言源码里存在字符串 `allNames`，属代理指标，注释改了就会失效 |
| P3-2 | 本会话两份审计文档 | 曾两次把"已修/不存在"写成"待办"（USER.md 93 条、/var/root 残留），已自我更正并留痕 |
| P3-3 | `cmd_install` 的回滚分支 | 无任何测试覆盖（回滚只在失败时触发，属最需要测的路径） |

## 三、引入的风险

| 风险 | 说明 | 缓解 / 现状 |
|---|---|---|
| **仓外系统改动** | `/opt/homebrew/bin/cliclick` 被替换，不受 git 管理 | `state.json` 记真身路径，`remove-interlock` 可还原；`status` rc=7 可发现退化 |
| brew 升级覆盖 shim | 升级后闸门消失（退化为裸 cliclick），非静默报错 | 文档已写；`status` 会报未接线 |
| 误拦导致流程中断 | D2 词表含"全部删除/初始化"等宽词；P2-2 的"密钥"更宽 | 一律 fail-closed；代价是人工解除 |
| 点击延迟 | 每次 +0.32~1.6s | 影响面已核实：**全机只有闸门自己调用 cliclick**（`grep -rl` 仅 1 处 + 1 篇旧记忆） |
| TCC 依赖 | 闸门用 osascript 读 AX；授权缺失时返回 rc=4 拒绝 | fail-closed，不会误点 |
| 测试用假对话框残留 | 曾留下 4 个关不掉的僵尸窗口，需 `killall "System Events"` | 已清理并复核 0 模态；教训写入文档 |

## 四、遗漏

1. **D3（机密词）未实弹**——需真出现恢复密钥，只有开 FileVault 才有，用户已否决。仅靠故障注入+变异测试。
2. **z 序未解决**——D1 判"前台"，坐标点击命中的是"最上层窗口"；三条路均不通（无 pyobjc、JXA 桥取不到、AX 矩形会过度拒绝）。
3. **`osascript` 直接点击不经闸门**——它不是沙箱。
4. **V0 阈值（20GiB / ×1.10）未做压力验证**——只测过"余量充足"与故障注入，没有在真实低余量下跑过。
5. **镜像"增量 0.3G"以外的容量场景未测**（如 source 突然增长 5G）。
6. **`cmd_install` 回滚路径无测试**（P3-3）。

## 五、与原始需求的一致性

| 原始要求 | 实际结果 | 判定 |
|---|---|---|
| 「1、2，你来做」= 时间机器 + FileVault | TM：**未配置**（用户指出单盘会抹盘，我按 Esc 取消）；FileVault：**开过又按指令关闭** | **需求变更**（用户后续指令），非遗漏；净效果 = 两项都未启用 |
| 「3C」= 第三份拷贝暂不做 | 未做任何第三副本 | ✅ 遵守 |
| 「关掉，不要加密，我自己都记不住」 | `fdesetup status` = `FileVault is Off.`；两卷 `No (Encrypted at rest)` | ✅ 遵守并回读 |
| 「把本对话全部内容审计一遍」 | `docs/session-audit-2026-11-24.md`，20 条 | ✅ 交付；但文档自身出过 2 次错（已更正） |
| 「可以」（做 GUI 闸门） | `wb-ui-guard.py` + 接线 + 文档 + 测试 | ✅ 交付；但闸门自身有 P1-1/P1-2 |
| 「请审计本对话中产生的全部变更」 | 本文件 | ✅ |

## 六、无法确认的信息

1. **healthchecks 面板的当前状态**——只有脚本侧 `HTTP 200` 与历史 Last Duration 17s 证据，外部面板未在本次审计中复核。
2. **明早 03:35 的一次性任务能否触发并产出**——属未来事件。
3. **P1-1 的成因**——"受禁前台下安装仍成功"与"单独 cliclick 被拒"并存，独立变量未分离。
4. **`brew upgrade cliclick` 后的真实行为**——P2-3 是推导，未实测。
5. **`/var/root` 目录完整内容**——第二次提权被取消，只确认了 `tm-setd-cmd.sh` 不存在。
6. **恢复密钥纸质件是否已销毁**——由用户处置，我无法查证。
7. **他人提交 `ca6253e` / `9c25db6`（17:01–17:02）的意图**——非本会话由我发起。
8. **FileVault 关闭后 PRK 是否已被系统清除**——需 root 查 `haspersonalrecoverykey`，未做。

## 七、审计结论

- 变更方向与用户指令一致；**没有造成不可逆后果**，关键操作都有回读证据。
- 工程质量上有一类反复出现的偏差：**"验证动作"本身没有被验证**。
  P1-1（安装自检经 shim）、P1-2（测试接受未接线）、P1-3/P1-4（文档数字与代码不符）是同一根因的四个表现。
- 三处系统级副作用（替换 cliclick、创建一次性任务、曾开过一次 FileVault）都可回退或已回退，但**都不在 git 里**，
  只能靠文档与 `status` 发现。

## 八、优先修正建议

| 优先级 | 动作 | 验收标准 |
|---|---|---|
| **P1-1** | `cmd_install` 的接线自检改为**直接调用真身绝对路径**（`real_cliclick() p`），不经 shim；再单独确认 shim 存在且可执行 | 新测试：把前台设为受禁应用时 `install-interlock` 仍能成功；现有 12 项自检不变 |
| **P1-2** | 断言改为：`status` 输出含"已接线"时 `rc` 必须为 0；未接线时 `rc` 必须为 7 | 变异测试：把 shim 换成裸软链 → 该测试必须红 |
| **P1-3** | 把"三次全量遍历"改成实测次数（≥4），或给 `verify` 加计数后写实数 | 文档数字与 `grep -c walk(` 一致 |
| **P1-4** | `backup-hub-db.md` 的"10 项校验"改 12 项 | 与 `grep -o '"A[0-9]*"'` 一致 |
| **P2-2** | `SECRET_CN` 收窄为 `("恢复密钥", "recovery key")`，去掉裸"密钥" | 自检新增："含'密钥'字样的普通对话框"应判 UNKNOWN 而非 SECRET |
| **P2-1** | 删掉 `com.apple.MobileSMS`（无证据）；若要保留需写依据 | 代码审查 |
| **P2-3** | 回退改为"现解析 INTERLOCK 软链；解析失败时报明确指引（`brew reinstall` + 重装接线）" | 构造 state 指向不存在路径 → 报错文案可执行 |
| **P3-3** | 补 `cmd_install` 回滚路径测试（注入失败的 verification） | 回滚后 `/opt/homebrew/bin/cliclick` 必须是软链 |

**不建议做的**：为凑齐"D3 实弹"去开 FileVault；为 z 序引入 pyobjc 之类的重依赖。
两者都是"为了验证而制造风险"，与本次审计的价值取向相反。

---

## 九、本报告的自我审计（2026-11-24 20:35，逐条用命令复核）

审计报告自己也要能被审计。以下 8 处是复核后查出的问题，**结论未变，数字与措辞要改**。

| # | 报告原文 | 复核结果 | 性质 |
|---|---|---|---|
| M1 | "约 +2.5k 行" | `git diff --numstat 8b0c618 0d7d046` = **加 2,782 / 删 127** | 数字低估约 280 行 |
| M2 | "涉及 14 个文件" | `wb-local-infra` 14 个 + 档案仓 `USER.md` = **15 个** | 少算 1 个（句子把两个仓合并统计了） |
| M3 | P1-1 "报成功两次中的一次" | 两次**都**报了成功；异常的是"前台是受禁应用那一次" | 措辞误导，像是概率问题 |
| M4 | P1-4 "文档与代码不一致" | 不止"后来过期"：写那行时（`39c2130`）脚本已有 **11** 项 A 校验，文档写 10 项，**当时就错 1 项** | 低估了性质 |
| M5 | 时间线第 1 行标【实测】"Last Duration 17s" | 那是**早前会话**的观测，本次审计未复核 | 证据等级标高了 |
| M6 | "三处不在 git 里的系统级改动" | 漏了：APFS 卷 `TMBackup` 的创建与删除、`~/.local/etc/wb-ui-guard.json`、`~/.local/log/wb-ui-guard.log`、镜像 state 文件 | 清单不全 |
| M7 | 把"`git add -A` 夹带删除"列为 **P1** | 与本文对 P1 的定义（假绿灯/文档失真）不符，它不产生运行时影响 | 分级不当，应降 P2 |
| M8 | P1-1 建议的验收标准："受禁前台下 install 仍能成功" | 这会把"未知成因"当成正常态。真正缺的是**安装路径不可观测**：`cmd_install` 全程没有任何 `_log`，front/rc/stdout 都没留痕 | 建议逻辑不完整 |

### M8 的追补建议（替换原 P1-1 建议）

1. 先补观测：`cmd_install` 在自检前后各写一条 `_log`（`front`、`rc`、`stdout` 前 60 字、`warn_reason`），
   使"为什么在受禁前台下通过"下次可查。
2. 再把自检改成**调用真身绝对路径**（`real_cliclick() + " p"`），使它不依赖闸门自身的判定。
3. 最后加测试：注入一个"真身可执行、shim 被 DENY 拦"的场景，断言自检仍通过且日志里能看到 front。

### 复核后仍然成立的部分

- P1-1 现象成立（同一前台，单独 `cliclick p` 得 `rc=3`，安装却报成功）
- P1-2 成立（`assertIn(rc, (0,7))` 对未接线无能为力）
- P1-3 成立且更重：`verify` 体内精确有 **5 处** `walk(`（行 26/57/58/111/132），
  `capacity_preflight` 每项 2 处；一次运行的全量遍历 ≥4 次，文档写 3 次
- P1-4 成立（且 M4 说明它写的时候就错）
- P2 六条全部成立（`com.apple.MobileSMS` 确无依据；`SECRET_CN` 含裸"密钥"；
  `FALLBACK_REAL` 硬编码 5.1；shim 依赖 PATH；0.32s/1.6s 实测；connector 附带为实测）
- 容量闸门失败返回 `rc=3` 成立（代码 532 行 + 自检 847 行断言）

---

## 十、修正记录（2026-11-24 21:15，按 M8 的三步执行）

| 原问题 | 修法 | 验证 |
|---|---|---|
| **P1-1** 接线自检经 shim，过闸门自己；且全程无日志 | 新增 `_verify_interlock(real, runner, scanner)`：**直调真身绝对路径**，与闸门判定解耦；`cmd_install` 把 `front/bundle/rc/out/passed` 写进日志 | 【实测】受禁前台 `Passwords` 下安装成功，日志留 `front=Passwords bundle=com.apple.Passwords rc=0 passed=True out='917,610'`；**同一前台单独 `cliclick p` 仍被拒 `rc=3`**（闸门未失效） |
| **P1-2** Python 测试接受 `rc=7`（未接线） | 改为按 status 输出判定：称"已接线"则 `rc` 必须 0，否则必须 7 | 【实测】61 项测试 OK |
| **P1-3** 文档"三次全量遍历" | 改为实测口径：preflight 每项 2 次 + verify 体内 5 处 `walk(`，一次运行 **≥4 次** | 【实测】`grep -n 'walk('` 行号 26/57/58/111/132 |
| **P1-4** 文档"10 项校验" | 改为 12 项（A1–A12） | 【实测】`grep -o '"A[0-9]*"'` 去重 = 12 |

新增 3 项测试（`TestInterlockVerify`）：调真身而非 shim、受禁前台下仍通过且留痕、真身不可用时判失败。
**变异测试**：把自检改回 `["cliclick", "p"]` → `test_calls_real_binary_not_shim` 单独变红，其余通过（3 项中 1 红）。

### 仍未解决（保持诚实）

- **历史成因无法回溯**：16:44 与 20:2x 那两次"受禁前台下自检通过"的旧现象，因为没有日志，
  已无法确定当时 `cliclick p` 到底走到了哪。新实现不再依赖这条路径，且有日志可查，问题被绕过而非"解释清楚"。
- **P2-1 / P2-2 未动**：`com.apple.MobileSMS` 仍在 DENY 名单；`SECRET_CN` 仍含裸"密钥"。
  两者都会改变拦截行为，属产品判断，需用户点头再改。
- **P3-3 未动**：`cmd_install` 回滚路径仍无测试（现已有 `_verify_interlock` 可注入失败，
  补一条"注入失败 → 软链被还原"的断言即可，本次未做）。

### 修正记录 v2（2026-11-24 21:30，用户「全部授权你来判断」）

| 原问题 | 我的判断与理由 | 修法 | 验证 |
|---|---|---|---|
| **P2-1** `com.apple.MobileSMS` 无依据 | **删**。DENY 的理由只能是「坐标点击可能造成不可逆破坏」，而「信息」既不毁数据也不显示机密；留着只会增加误拦，侵蚀对闸门的信任 | 从 `DENY_BUNDLES` 移除 | 新增测试：源码不得出现该 bundle |
| **P2-2** `SECRET_CN` 含裸"密钥" | **收窄**。D3 存在的唯一理由是「Esc 会毁掉恢复密钥的唯一一次显示」；钥匙串口令框没有这个性质，判成机密态=白白停手 | 改为 `("恢复密钥",)` | 新增对偶用例「普通密钥提示不算机密态」→ 期望 UNKNOWN；**变异**：改回宽口径 → 恰好该项红（12/13） |
| **P2-3** 回退硬编码 `Cellar/cliclick/5.1` | **改**。brew 升级即失效，且报错像"没装" | `CELLAR_GLOB` 按版本排序取最新；取不到才退回 `/opt/homebrew/bin/cliclick` | 测试断言源码不再含 5.1 写死路径 |
| **P2-4** shim 裸依赖 PATH 里的 python3 | **改**。最小 PATH 下 exec 失败会让 cliclick 整个不可用 | shim 优先 `/usr/bin/python3` 绝对路径，不存在才回落 `python3` | 部署后 `cliclick p` 直通 rc=0 |
| **P3-3** 回滚路径零测试 | **补**。这是"出事时才走"的路径，最该有测试 | `TestInterlockRollback`：注入失败→rc=1 且恢复软链；注入成功→变 shim | 5 项新测试全过；写测试时自己踩了两个坑（断言写在 `TemporaryDirectory` 外、`/var` vs `/private/var`），已修正 |

**未做（明确判断，非遗漏）**：审计 P2-6 的一次性任务被自动附带 7 个 `connectorIds`。
不去动它——该任务 3:35 就要触发，改配置的收益（少几个无关连接）远小于风险（改坏调度）。

**测试总量**：66 项 OK（61 + 5）；自检 13/13；`install.sh` 零差异 34 脚本。
