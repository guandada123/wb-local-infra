# 工作台（hub-overview）

本机 127.0.0.1:3355 的运维看板。一个页面看三件事：中台自动化跑得怎么样、有没有卡在本人这里、各项目什么状态。

## 三处文件的关系

| 位置 | 是什么 |
|---|---|
| `bin/hub-overview-server.py` | 服务端（HTTP + 数据聚合）。**源**，由 `install.sh` 统一部署 |
| `bin/hub-overview-watch.py` | 探活脚本（launchd 每 10 分钟，状态翻转才发飞书） |
| `bin/hub-ci-status.py` | 查各仓 CI 状态，写缓存供页面读（按需/后台 15 分钟刷新） |
| `share/hub-overview/index.html` | 页面。路径与 live 镜像（`~/.local/share/hub-overview/`），便于对照 |
| `workbench/install-hub-overview.sh` | 本组专用部署器：仓 → live + 重启 + 探活 |
| `docs/hub-workbench.md` | 工作台档案（7 节：场景/页面/数据源/自动化/权限/待优化/变更） |

## 部署

```bash
bash workbench/install-hub-overview.sh           # dry-run，只比对差异
bash workbench/install-hub-overview.sh --apply    # 落盘 + kickstart + 探活(非200即失败)
```

只改了 `bin/` 里的脚本、没碰页面时，也可以走仓根的 `./install.sh --apply`（带 30 个脚本的统一闸门）。

## 回滚

```bash
git revert <commit> && bash workbench/install-hub-overview.sh --apply
```

launchd 靠 KeepAlive 保活，`kickstart -k` 后会自动拉起；服务没起来时看 `~/Library/Logs/hub-overview.err`。

## 闸门

```bash
python3 -m unittest tests.test_deploy_sync -v   # bin/ 与 live 逐字节
python3 -m unittest tests.test_share_sync -v    # share/ 与 live 逐字节（含负控）
```

live 与仓不一致就红。**只改 live 会被判红**——改仓再部署，这是本仓的规矩。

## 已知边界

- 端口 3355 只监听本机，**无鉴权**；不要直接暴露到外网
- 页面数据全部只读：`hub.db`、`rules.json`、`QUEUE.md`、`launchctl`、git、日志。写入点仅 `~/.agent-autoloop/` 下 3 个状态文件
- 不持有任何凭据；飞书推送沿用中台既有通道
