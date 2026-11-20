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
