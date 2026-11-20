# wb-local-infra

~/.local/bin 与 LaunchAgents 的版本化快照仓（2026-11-19 建仓，审计 P0 修复）。

- bin/: ~/.local/bin 非 autoloop- 前缀脚本快照（cp -p，含 mtime）
- launchd/: ~/Library/LaunchAgents plist 快照（只读留痕，原位不动）
- archive/: 各处 .bak 收敛留痕
- docs/: plist-live-map 等台账

**本仓是快照备份，不是部署真源**：live 文件仍在原路径运行，更新流程 = 改 live → 拷回本仓提交。

## 结构升级（2026-11-20：从「快照仓」升级为「中台基础设施源仓」）

- **bin/ = 25 个中台脚本的唯一源**（活源；已剔除 14 个「有 Claw 镜像」的重复快照，移至 archive/claw-mirror-snapshots/）：
  无版本控制的 25 个脚本（autoloop-*/feishu-*/hub-*/lark-*/wb-*/push_card/gate-health-daily/zhongtai-board 等）全部纳管。
- **install.sh**：仓 → ~/.local/bin 单向部署（默认 dry-run，`--apply` 落盘；部署前 py_compile 校验）。
- **tests/test_deploy_sync.py**：逐字节同步闸门——live 漂移即红（已做三向验证：绿/漂移红/恢复绿）。
- **原则**：改脚本改仓内 bin/，`./install.sh --apply` 部署；禁止直接改 live（会被闸门判红）。
- launchd/ = 52 plist 快照；archive/ = 历史备份与迁移前快照（含 claw-mirror-snapshots）。

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

**硬编码路径豁免（S7）**：本机 plist 内含 `/Users/guan/...` 绝对路径 **3 处**（`com.user.infra-sync-check.plist` 的 python 解释器与两个日志路径）。这是**有意豁免**，原因是 launchd 不支持 `~` 与变量展开，`ProgramArguments` 只接受绝对路径。

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
