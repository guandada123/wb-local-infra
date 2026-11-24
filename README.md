# wb-local-infra

~/.local/bin 与 LaunchAgents 的版本化快照仓（2026-11-19 建仓，审计 P0 修复）。

- bin/: ~/.local/bin 脚本快照 / 活源（cp -p，含 mtime）
- launchd/: ~/Library/LaunchAgents plist 快照（只读留痕，原位不动）
- autoloop/: `~/.agent-autoloop/rules.json` 规则真源快照 **+ 漂移闸门**（2026-11-23 加）
- archive/: 各处 .bak 收敛留痕
- docs/: plist-live-map 等台账

**本仓是快照备份，不是部署真源**：live 文件仍在原路径运行，更新流程 = 改 live → 拷回本仓提交。

## 结构升级（2026-11-20：从「快照仓」升级为「中台基础设施源仓」）

- **bin/ = 30 个中台脚本的唯一源**（活源；已剔除 14 个「有 Claw 镜像」的重复快照，移至 archive/claw-mirror-snapshots/）：
  无版本控制的 30 个脚本（autoloop-*/feishu-*/hub-*/lark-*/wb-*/push_card/gate-health-daily/zhongtai-board 等）全部纳管。
  **2026-11-23 补两个审计漏网**：`autoloop-deepseek`（1,101 行，整个自主系统的执行内核）与
  `autoloop-result-stats.py` —— 二者当时只存在于 `~/.local/bin` 一份，无 git、无远端、无 Claw 镜像，
  与 mem-search 当初「902 行唯一副本」同型。现已纳管，`install.sh` 已确认 30 个零差异。
- **install.sh**：仓 → ~/.local/bin 单向部署（默认 dry-run，`--apply` 落盘；部署前 py_compile 校验）。
- **tests/test_deploy_sync.py**：逐字节同步闸门——live 漂移即红（已做三向验证：绿/漂移红/恢复绿）。
- **原则**：改脚本改仓内 bin/，`./install.sh --apply` 部署；禁止直接改 live（会被闸门判红）。
- launchd/ = 52 plist 快照；archive/ = 历史备份与迁移前快照（含 claw-mirror-snapshots）。

## autoloop 规则真源快照（2026-11-23 加）

`autoloop/rules.json` = `~/.agent-autoloop/rules.json` 的逐字节快照，由
`tests/test_deploy_sync.py::TestRulesSnapshot` 守门（漂移即红；live 路径不在则 fail 不 skip）。

- **为什么需要**：该文件是自主调度的唯一手写真源，`chflags uchg` 只防改写、**不防磁盘故障**，
  而它此前不在任何 git 仓（本仓 bin/ 只覆盖脚本）。
- **实测规模**（`python3 -c` 数出来的，不凭记忆）：规则 **6 条** + 拍板清单 `askFirst` **7 条**
  + agent 2 个 + 通道 1 个 + 源 1 个，20,697 字节。
- **改规则流程**：`chflags nouchg` → 改 → `cp -p` 回本仓 `autoloop/rules.json` → 跑测试 → 提交 → `chflags uchg`。
- **有意不纳管**：`config.json`（内含 43 字符 hub 密钥 `worker.key`/`source.key`/`owner`/`channels`）、
  `feishu.json`、`*.state.json` —— 凭据与运行态不进远端。
  **2026-11-23 更正**：光「不进远端」等于没有第二副本。现由 `wb-autoloop-backup.py` 每日把这些
  连同 `hub.db`（26MB，57,990 行 facts）、`master.key` 备份到**外置卷**并逐项校验，见
  `docs/backup-hub-db.md`。
- **`app/`（引擎本体）不纳入也无需纳入**：它是上游 `KKKKhazix/agent-autoloop` 的干净克隆
  （`v1.8.4-8-gd3a44ca`，`git status` 0 改动），恢复 = clone 后切到 `d3a44ca`；本机无本地补丁。

## plist 三处来源的真源关系（2026-11-20 审计补充）

| 位置 | 角色 | 数量 | 说明 |
|---|---|---|---|
| `Claw/.workbuddy/deploy/*.plist` | **真源（有部署脚本）** | 9 | 活跃 job 的 plist 源 + install-*.sh 部署器 |
| `本仓 launchd/` | **只读快照** | 53 | 全量存档（含历史/停用），不部署、不作比较基准 |
| `~/Library/LaunchAgents/` | 运行副本 | 31 | 由 Claw 部署脚本安装；本仓 install.sh **不碰 plist** |

纪律：改 plist 改 Claw deploy/ → 跑其 install 脚本 → 本仓 launchd/ 快照按需更新（非门禁）。

## plist 灾难恢复（2026-11-20 补）

`launchd/active.txt` 记录当前活跃的 31 个 launchd job，`[deploy]` 标记的 9 个由 Claw `.workbuddy/deploy` 脚本管理，其余 **22 个为 ad-hoc job（无 deploy 源，仅快照存档）**。

```bash
./install.sh --plists          # dry-run：列出换机后需补装的 plist
./install.sh --plists-apply    # 实际补装（只补缺失、绝不覆盖已有）
```

安全边界：① 只处理 active.txt 列出的 job；② `[deploy]` 项跳过；③ 目标已存在一律跳过；④ 补装后需 `launchctl bootstrap gui/$(id -u) <plist>` 才生效。
验证：真实 live 幂等跳过 22 / 空目录补装 22 / 集合完全一致 / 53 个快照 plist 全部 `plutil -lint` 通过。

## .bak 存量（2026-11-20 已归档）

`~/.local/bin` 下 34 个历史 `.bak-*`（2026-08-04 ~ 11-20，共 732K）已移入 `.deploy-backups/legacy-20261120/`，附 `MANIFEST.txt` 记录原路径，可原路还原。新备份由 `install.sh` 写入 `.deploy-backups/`（保留最近 5 份/脚本），不再污染 PATH 目录。

## 每日漂移检查覆盖两类（2026-11-20 扩展）

`com.user.infra-sync-check`（每日 10:35）现在同时检查：

| 类 | 判据 | 漂移时 |
|---|---|---|
| ① 脚本 | 仓内 `bin/` ↔ `~/.local/bin` 逐字节（unittest 闸门） | 推卡（含文件清单 + 修法） |
| ② plist 快照 | `live → launchd/` 快照是否过期（`--snapshot-plists` 探测） | 推卡（提示 `--snapshot-plists-apply` 刷新） |

- 全绿时只写日志（`~/.agent-autoloop/logs/infra-sync-check.log`），不刷群；
- `DRY_RUN=1` 零副作用可测；`AGENTS=/tmp/x` 可指定 plist 目录演练；
- 新增 job 未登记 `active.txt` 只记 INFO 日志，不推卡（属正常演进）。

刷新快照：`./install.sh --snapshot-plists`（dry-run）/ `--snapshot-plists-apply`（落盘）。
纪律：改线上 plist 后立刻刷新快照，否则 DR 会恢复旧配置。

## 清单重建与硬编码路径豁免（2026-11-20 审计 S6/S7）

**清单重建（S6）**：`launchd/active.txt` 不再依赖一次性内联脚本，一条命令可重生：

```bash
./install.sh --regen-active           # dry-run：打印将写入的完整清单
./install.sh --regen-active-apply     # 落盘（deploy 项自动打 [deploy] 标）
```

- 新装/卸载 launchd job 后跑一次，否则 `--plists` 恢复会漏 job；
- 护栏同 snapshot：`AGENTS` 或 `OUT` 非默认时拒绝写盘（需 `FORCE=1`）。

**硬编码路径豁免（S7）**：本机 plist 内含 `~` 展开后的绝对路径 **3 处**（形如 `/Users/<用户名>/...`）（`com.user.infra-sync-check.plist` 的 python 解释器与两个日志路径）。这是**有意豁免**，原因是 launchd 不支持 `~` 与变量展开，`ProgramArguments` 只接受绝对路径。

| 替代方案 | 为何不采用 |
|---|---|
| 用 `$HOME` 展开 | launchd 不做 shell 展开，写了会当字面量找不到文件 |
| 改为相对路径 | launchd 工作目录不确定，相对路径不可靠 |
| 生成时模板替换 | 增加一层间接，收益仅限换机场景（而换机本就需人工介入） |

**换机处置**：`--plists-apply` 补装后，用 `sed -i '' "s|/Users/旧用户名|/Users/新用户名|g"` 批量替换，再 `launchctl bootstrap`。`active.txt` 头部已写此提醒。

## 归档索引：`_archive` 不进资料库，进索引（2026-11-20 审计 P2-9 判断）

`~/WorkBuddy/_archive`（562MB）里 86% 是不可检索的二进制（250MB cron 邮件堆 + 236MB 券商安装包）。**结论：不进云端资料库、不进 git**——大二进制会让库变垃圾场，且无法检索。正确形态是「索引进仓 + 二进制留本地」：

```bash
python3 bin/archive-index.py            # 重建 _archive/INDEX.md
python3 bin/archive-index.py --print-only   # 只打印（零写盘）
```

- 索引产物**不手工维护**，每次由脚本重建（避免过期）；脚本里的 `VERDICT` 表登记每个归档的处置结论与「可再生性」；
- 未登记的归档自动标「未分类/待评估」，不会静默通过；
- 索引含 SHA256 前 16 位，可校验归档未被悄悄替换。

**噪音识别**：`cron-mail-spool-20261012.mbox` 有 356,687 封，其中 99.99% 是 `openclaw_watchdog.sh` 与 `feishu_qa_bot_watchdog.sh` 的重复输出；有效 36 封已抽出为 `cron-mail-interesting-20261012.mbox`（29.5KB）。

## 每日检查的五类（2026-11-21 扩到 4 类，11-22 扩到 5 类）

| # | 类 | 判据 | 修复 |
|---|---|---|---|
| ① | 脚本漂移 | 仓 `bin/` ↔ `~/.local/bin` 逐字节（unittest） | 回迁或 `./install.sh --apply` |
| ② | plist 快照 | `launchd/` 是否过期（`--snapshot-plists`） | `--snapshot-plists-apply` |
| ③ | 归档索引 | `_archive/INDEX.md` 是否与目录一致（`archive-index.py --check`） | 跑 `archive-index.py` |
| ④ | **cwd 锚点** | `launchd/cwd-anchors.txt` 列出的目录是否还在 | 从废纸篓恢复 |
| ⑤ | **马厩总册** | `~/WorkBuddy/马厩归档总册.md` 与台账/档案/归档区/云端清单是否一致（rc=1 过期 / rc=3 判不了） | `bin/majiu-archive-index.py --with-library --out …` |

全绿时日志写 `OK: 五类通过（…）` 并把五类逐项列出 —— 删掉某一类时日志立刻可见，
不靠"少一行也算绿"蒙过去。第 ⑤ 类的 rc 分三态：0 最新 / 1 过期 / 3 无法比对（云端读不到），
**判不了不许压成过期**，否则上游一抖就是一片假红。

第 ④ 类的由来：12 条自动化（做T/Alpha/资料库/理财工作台/鱼盆/记忆快照等）的 `cwds` 指向历史会话目录，
删了就会全部失联。`automation_update` **拒绝**把 Claw 或 `/Volumes/...` 真实路径作为 cwd
（报 `workspace ... cannot host automations`），所以只能把这些目录当锚点长期保留（合计约 21MB），
清单纳管、每日校验。详见 `launchd/cwd-anchors.txt` 的说明。

## 自托管 runner（不进 active.txt，换机需单独恢复）

两个 GitHub Actions runner 跑在本机（launchd 服务名 `actions.runner.<owner>-<repo>.<name>`）：

| 仓库 | runner 名 | 标签 | 用途 |
|---|---|---|---|
| Claw | `guandeMac-mini` | `self-hosted, macOS, ARM64, mac-local` | Claw CI / Shell Deletion Guard |
| ai-autonomy-team | `guandeMac-mini-autonomy` | 同上 | selftest（私有仓 hosted 分钟有计费墙，曾 4 次 steps=0 从未执行） |

**为什么不在 `active.txt` 里**：`--regen-active` 只扫 `com.user.*.plist`，runner 是 `actions.runner.*`、
由 `./svc.sh` 自管，恢复方式与普通 plist 不同（要重新向 GitHub 注册）。所以它不会出现在每日检查的
「未登记」提示里 —— 也就是说**没有任何自动检查会提醒你它丢了**，只能靠这份文档。

换机重建（每个仓库各做一次）：

```bash
mkdir -p ~/actions-runner-<repo> && cd ~/actions-runner-<repo>
# ① 取 runner 包（版本随意，与另一台一致更好）；从旧机复制时排除 _work/_diag/.runner*
TOKEN=$(gh api -X POST repos/<owner>/<repo>/actions/runners/registration-token --jq .token)
./config.sh --unattended --url https://github.com/<owner>/<repo> --token "$TOKEN" \
            --name guandeMac-mini[-autonomy] --labels mac-local --work _work
./svc.sh install "$(id -un)" && ./svc.sh start
gh api repos/<owner>/<repo>/actions/runners --jq '.runners[]|"\(.name) \(.status)"'   # 应为 online
```

三个坑（都踩过）：

1. **从旧机复制 runner 目录会带 `.runner_migrated`** → `config.sh` 报 "already configured"，
   删掉该文件再注册。
2. **重启服务后报 "A session for this runner already exists"** → 旧会话未过期，
   监听器每 30s 重试，约 4–5 分钟后自愈；期间 runner 显示 offline、`busy=true`。
3. **工具缓存必须预热**：`~/.env` 写 `RUNNER_TOOL_CACHE=<已装过 Python 的 _work/_tool>`（两个 runner
   共用 Claw 那份）。缓存空时 `setup-python` 会现场装 Python，在 self-hosted macOS 上报
   `sudo: a password is required` 直接失败。注意 workflow 里**不能**写死该路径，也**不能**
   在 job 级 env 用 `${{ runner.tool_cache }}`（runner 上下文在 job env 不合法，job 会零创建）。

## 马厩重打总册（`bin/majiu-archive-index.py`）

马厩归纳分散在三层：台账 `Claw/STALL_LOG.md`、归档区 `~/WorkBuddy/_archive/`、成果档案 `archive/<日期>-conversation/`。
本脚本把三层汇成一份可直接上传资料库的《马厩归档总册》，**不手工维护**。

```bash
python3 bin/majiu-archive-index.py                      # 打印
python3 bin/majiu-archive-index.py --with-library       # 额外实读资料库「00 对话成果档案」清单
python3 bin/majiu-archive-index.py --with-library --out 总册.md
python3 bin/majiu-archive-index.py --check 总册.md      # 0 一致 / 1 过期 / 2 文件不存在
```

三条硬约束（都有用例守着）：

| 约束 | 原因 |
|---|---|
| 数字全部现算 | 写死会在档案增减后失真（总册曾写 25 份而实际 41 份） |
| 归档索引读不到 → 显示「未读到索引」 | **不返回 0 项**：那会在总册里造出「0 项 / 0MB」的假事实 |
| 未加 `--with-library` → 明说「未实读」 | 不静默输出空清单 |

`--with-library` 依赖 WorkBuddy 桌面端的 `space_api.py`，非桌面环境下该节自动降级为「未取」，其余照常生成。

## hub.db 异地备份（2026-11-23 加）

`~/.agent-autoloop/hub.db` + `master.key` + `config.json` + `rules.json` + `feishu.json`
每日 23:40 备份到 `/Volumes/ZHITAI/backups/agent-autoloop/<时间戳>`（异卷、0700/0600、保留 8 份）。

- 脚本 `bin/wb-autoloop-backup.py`：`backup / check / drill / daily / self-test`
- 定时 `launchd/com.user.autoloop-backup.plist`（必须先跑 `install.sh --apply` 部署脚本）
- 12 项校验 + 15 项故障注入（A12 与它的对偶用例做过变异测试）；恢复演练真恢复到临时 `AGENT_AUTOLOOP_HOME` 后逐表比对
- 快照含 `etc/`：`~/.local/etc/*.conf`（心跳/记忆推送/备份打卡/镜像打卡/memwatch/UI 闸门状态）此前全部只有一份
- **外部观测**（2026-11-24 接通）：healthchecks.io check `Autoloop Backup`（1 day / 2h grace），
  `daily` 打 `/start`、成功打 plain、失败打 `/fail`；ping URL 只在 `~/.local/etc/wb-autoloop-backup.conf`
- **完整说明与残余风险**（整机无 TM/FileVault、落点卷未加密、作业无法自证未跑）：`docs/backup-hub-db.md`

## 离线镜像：只此一份的数据 → 内盘（2026-11-24 加）

`~/WorkBuddy` 与 `~/.workbuddy` 都是指向 `/Volumes/ZHITAI` 的软链 —— 用户数据全在那块便携 SSD 上，
而报告、会话历史、各 workspace 记忆既无第二副本、也不在任何 git 里。本作业把它们靶向复制到内盘：

- 脚本 `bin/wb-offsite-mirror.py`：`run / verify / daily / status / self-test`
- 定时 `launchd/com.user.wb-offsite-mirror.plist`：每日 03:20（LowPriorityIO + Nice 5）
- 覆盖：`Claw/output`(714M) + `workbuddy_data/projects`(5.5G) + 各 `.workbuddy/memory`(15M)
- 外加**单文件库** `workbuddy_data/workbuddy.db`(261M，240 个自动化配置)：不走 rsync，
  用 sqlite `backup()` 在线快照 + 原子替换，副本自带 sidecar
- 判据 V0 容量闸门（写前，写后仍须 ≥20GiB，不过就一个字节都不写）+ V1–V6：异卷 / 非空 /
  **集合包含**（不是数量比）/ 抽样 sha256 / 落点旧文件只 WARN / 库副本可读且行数被源读数夹住
- **不跟随删除**：镜像不做 `--delete`，否则一次误删两边都没了
- 25 项故障注入；V3 的增长/截断靠 mtime 区分（只靠「前缀一致」分不出来，实测踩过）
- 外部观测：healthchecks check `Offsite Mirror`（1 day / 2h grace），配置在
  `~/.local/etc/wb-offsite-mirror.conf`
- **完整说明、残余风险（单设备/未加密/TM 仍未配）与「TM 为什么配不上」的实测记录**：
  `docs/offsite-mirror.md`

## GUI 自动化闸门：点之前先看屏幕（2026-11-24 加）

起因：给时间机器加盘时用坐标点击在系统设置里连点七八次，中途弹出「抹掉 ZHITAI」（=删 274GB 全部数据），
靠 Esc 救回来 —— **没出事靠临场反应，不是设计**。本作业把「小心点」变成机器判据：

- 脚本 `bin/wb-ui-guard.py`：`scan / forward / click / status / install-interlock / remove-interlock / self-test`
- **D1 前台应用禁令**：系统设置 / 磁盘工具 / 密码(钥匙串) / SecurityAgent 一律不接坐标点击，**名字与 bundle id 双轨**（macOS 26 把钥匙串改成「密码」，只认名字会整条失效 —— 实测漏拦过）
- **D2 危险词 → 先 Esc 再拒**（抹掉/抹除/格式化/删除卷/erase/wipe…，英文按词边界防 `formatted` 误命中）
- **D3 机密词 → 拒但绝不 Esc**（恢复密钥/recovery key；Esc 会关掉唯一一次显示）
- **fail-closed**：看不懂的模态框、读不到屏幕，一律拒绝执行
- **必须接线**：PATH 里 `/opt/homebrew/bin` 在 `~/.local/bin` 之前，所以在 local 放同名脚本挡不住；
  `install-interlock` 把 `/opt/homebrew/bin/cliclick` 换成 shim（目录属 guan:admin，无需 sudo），可一键还原
- **自身位断言**：`status` 的 rc 就是接线状态（0 已接 / 7 未接），避免「仓库里躺个文件当闸门」
- 12 项故障注入 + 3 次变异测试（删「抹掉」/ 机密分支按 Esc / 去掉 bundle 判据，各恰好 1 项红）；自检不写真实日志
- **完整边界（只管 cliclick / 网页对话框不在 AX 树 / 未做实弹测试 / brew 升级会覆盖 shim）**：
  `docs/gui-automation-guard.md`
