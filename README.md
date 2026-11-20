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
