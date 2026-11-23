# 中台数据异地备份（hub.db / master.key）

建立于 2026-11-23。脚本 `bin/wb-autoloop-backup.py`，定时 `launchd/com.user.autoloop-backup.plist`。

## 一句话

`~/.agent-autoloop/hub.db` 是整套自主系统的**唯一数据存储**，此前零备份。现在每日 23:40
打一份到外置卷，11 项校验全过才算完；恢复能力用「真恢复到临时 HOME 再逐表比对」证明，不靠声称。

## 被备份的东西（实测规模，不凭记忆）

| 文件 | 大小 | 为什么不能丢 |
|---|---|---|
| `hub.db` | 26MB | 5 张表：`facts` 57,990 行、`projection_refs` 12,600 行、`projections` 956 行。密钥派生、轮次历史、卡片账本全在里面 |
| `master.key` | 43B | 签卡片链接的主密钥；丢了历史卡片链接全部失效 |
| `config.json` | 490B | hub/worker/source/channel 四把密钥（各 43 字符），**有意不进 git** |
| `rules.json` | 20,697B | 自主调度唯一手写真源（仓内另有快照 + 漂移闸门） |
| `feishu.json` | 354B | 飞书自建应用 `app_id`/`app_secret` —— **官方备份不覆盖**，本脚本补拷 |

官方 `agent-autoloop backup` 的 `FILES` 只有 `master.key/config.json/rules.json/secrets.env`
（`cli/backup.ts`），`feishu.json` 不在其中；`*.state.json`、`worker/`、`logs/` 属运行态，不备份。

## 为什么要自己写一层

官方本来就带 `backup`/`restore`（在线页拷贝 + `quick_check` + 主密钥形状校验），**缺的不是工具**：

| 缺口 | 修法 |
|---|---|
| 没有任何调度在跑它 | launchd 每日 23:40 |
| 落点若与源同卷 = 假备份 | 按 `st_dev` 判物理卷，同卷直接拒绝（rc=2） |
| 「备份成功」无第三方校验 | 11 项闸门 + 12 项故障注入 |
| `feishu.json` 不在官方范围 | 补拷（`copyfile`，非 `copy2`，见下） |
| 恢复能力从未验证 | `drill`：真恢复 + 逐表行数比对 |

## 11 项校验

| ID | 项 | 判红条件 |
|---|---|---|
| A1 | 快照存在 | 目录或 `hub.db` 缺失 |
| A2 | 新鲜度 | 距今 > 26h（每日一次 + 2h 抖动余量） |
| A3 | 异卷 | 源与落点 `st_dev` 相同（同盘不同目录 = 假备份） |
| A4 | 完整性 | `quick_check != ok` 或表数 = 0 |
| A5 | 非空 | `facts` 行数 = 0（空库/截断库） |
| A6 | 主密钥形状 | `master.key` 不是 43 字符 |
| A7 | 权限 | 目录非 0700 或文件带 group/other 位 |
| A8 | 额外文件 | 缺 `feishu.json` |
| A9 | 与 live 比对 | 备份行数 > live，或缺表（旧库冒充/串备份） |
| A10 | 轮转 | 保留份数 > 8 |
| A11 | 不可变标志 | 快照内文件带 `uchg`/`schg`/`restricted`（轮转会删不掉） |

A2 与 A9 的方向性说明：live 在跑，行数只会长，所以**不要求相等**（相等是假要求，会把正常备份判红），
只要求「备份不多于 live」+「核心表非空」。

**闸门自身可证伪**：`self-test` 做 12 项故障注入，每项只破坏一个维度，断言**恰好那一项**变红。
11 项校验里除 A1/A10 外每项都有一条对应的注入用例。

## 命令

```bash
python3 ~/.local/bin/wb-autoloop-backup.py backup        # 打一份 + 补拷 + 校验 + 轮转
python3 ~/.local/bin/wb-autoloop-backup.py check [--all] [--json]
python3 ~/.local/bin/wb-autoloop-backup.py drill         # 真恢复演练
python3 ~/.local/bin/wb-autoloop-backup.py daily         # launchd 入口：备份→校验→出问题才推
python3 ~/.local/bin/wb-autoloop-backup.py self-test     # 12 项故障注入
```

退出码：0 全过｜1 有 FAIL｜2 环境/参数错误（如落点同卷被拒）。

## 定时与告警

- `com.user.autoloop-backup`，每日 23:40，日志 `~/Library/Logs/wb-autoloop-backup.log`
- 只在**出问题**时推飞书（走既有出口 `autoloop-feishu-push.py --text`）：
  状态变化即推，持续失败每 7 天提醒一次，避免永久红灯变噪音
- 状态文件 `~/.local/etc/wb-autoloop-backup.state.json`

## 恢复（真跑过的步骤）

```bash
# 1) 停中台（restore 会替换正在被打开的文件）
# 2) 恢复
agent-autoloop restore /Volumes/ZHITAI/backups/agent-autoloop/<时间戳> --yes
# 3) 起来
agent-autoloop up   或   agent-autoloop service install
```

演练（不停中台、不碰本机 home，用官方 `AGENT_AUTOLOOP_HOME` 覆盖口）：

```bash
python3 ~/.local/bin/wb-autoloop-backup.py drill
```

实测 2026-11-23：恢复 0.3s，5 张表逐表行数一致，`master.key` 形状正常。

## 残余风险（都还没解决，别当成已解决）

1. **整机没有任何整体保护**：`fdesetup status` = FileVault **Off**；`tmutil destinationinfo` =
   **No destinations configured**。也就是说磁盘故障/丢失时，除了本仓这份 `hub.db` 之外，
   其余一切（代码仓、报告、workspace）都只有一份。这两项都需要人来做（FileVault 要重启 +
   保管恢复密钥；TM 要一块独立物理盘），脚本不做也不假装做了。
2. **落点卷未加密**：ZHITAI 是 APFS 但 `Encrypted: No`，因此备份里的 `master.key`/`config.json`
   是明文躺在便携 SSD 上。该卷上 `~/.workbuddy` 本来就存着 mcp 凭据，这是**既有**暴露面；
   单一修复口是给卷或整机加密。脚本不加密备份 —— 加密就要口令，口令落盘就等于没加密，
   落纸/密码管理器又不归脚本管，做成「自动加密」只会得到安全剧场。
3. **作业无法自证「自己没跑」**：plist 里硬编码授权 python 路径（`3.13.12`），WorkBuddy 升级
   若移除该版本，作业静默不跑且无人知道。缓解：`tests/test_deploy_sync.py::TestBackupGate::
   test_plist_points_at_existing_python` 会在路径失效时变红（前提是有人跑测试）。
   彻底解法是接 healthchecks.io 独立 UUID（外部观测），需要用户建 check。

## 轮转与删除

保留最近 8 份（≈216MB）。删除快照前若曾触发 A11，先 `chflags -R nouchg <目录>`，
否则 `rm -rf` 会被拒（`uchg` 连 root 也拦）。

## 复盘

Claw 仓 `.learnings/2026-11-23-hub-db-single-copy-and-copy2-uchg.md`（坑 28–33）。
