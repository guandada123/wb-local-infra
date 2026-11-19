# archive/.bak 收敛台账（阶段3，2026-11-19）

源文件全部**原地保留未动**；本目录为留痕副本。删除源侧 .bak 属待审批项（阶段4/单独审批），未执行。

| 来源 | 目标子目录 | 数量 | 校验 |
|---|---|---|---|
| ~/.local/bin/*.bak-* | local-bin/ | 28 | cmp 逐文件 0 失败 |
| Claw/.workbuddy/scripts/*.bak-* | claw-wb-scripts/ | 14 | 同上 |
| ~/Library/LaunchAgents/*.bak* | launchd/ | 6 | 同上 |
| ~/.workbuddy/scripts/_bak-2026101x-*（12 个整目录） | wb-scripts-bakdirs/ | 12 目录 | cp -R 计数一致 |

注：Claw `.workbuddy/scripts/_archive/`（17 项）本身已是归档目录，非散落 .bak，未纳入本次收敛。
