# 中台数据异地备份（hub.db / master.key）

建立于 2026-11-23。脚本 `bin/wb-autoloop-backup.py`，定时 `launchd/com.user.autoloop-backup.plist`。

## 一句话

`~/.agent-autoloop/hub.db` 是整套自主系统的**唯一数据存储**，此前零备份。现在每日 23:40
打一份到外置卷，12 项校验全过才算完；恢复能力用「真恢复到临时 HOME 再逐表比对」证明，不靠声称。

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
| 「备份成功」无第三方校验 | 12 项闸门 + 15 项故障注入（含对偶用例的反证记录） |
| `feishu.json` 不在官方范围 | 补拷（`copyfile`，非 `copy2`，见下） |
| 恢复能力从未验证 | `drill`：真恢复 + 逐表行数比对 |

## 12 项校验

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
| A12 | 本机配置 | 快照 `etc/` 与 `~/.local/etc/*.conf` **同名集合不相等**，或权限过宽 |

A2 与 A9 的方向性说明：live 在跑，行数只会长，所以**不要求相等**（相等是假要求，会把正常备份判红），
只要求「备份不多于 live」+「核心表非空」。

**闸门自身可证伪**：`self-test` 做 15 项故障注入，每项只破坏一个维度，断言**恰好那一项**变红。
12 项校验里除 A1/A10 外每项都至少有一条对应的注入用例。

**用例本身的强度做过变异测试**（2026-11-24）：A12 的判据是「同名集合相等」，专门写了
`源换名 conf 未跟上` 这个**对偶用例** —— 源里删掉 `wb-memory-push.conf`、加上 `brand-new.conf`，
快照仍是旧的三个，两边数量都是 3。把 A12 判据临时改成 `len(want) == len(have)` 后重跑：
该用例变成「红项=无」，14/15 —— 说明它确实能区分两种实现，不是摆设。改回后 15/15。

## 本机配置也进快照（2026-11-24 加）

审计发现 `~/.local/etc` 下四个 `*.conf` **全部只有一份**，且都是整机自动化的神经中枢：

| 文件 | 内容 | 丢了会怎样 |
|---|---|---|
| `wb-heartbeat.conf` | `HC_PING_URL`（Mac 存活打卡凭据） | 存活监控哑掉；URL 可在 healthchecks 页面再取 |
| `wb-autoloop-backup.conf` | `HC_BACKUP_PING_URL`（本备份打卡） | 备份打卡断；同上可再取 |
| `wb-memory-push.conf` | 记忆推送仓路径、分支、群 id、节流 | 记忆自动推送断；群 id 要重新查 |
| `workbuddy_memwatch.conf` | 内存守护阈值（11 个数值，无凭据） | 回落默认值 |

现在随每份快照存进 `etc/`（目录 0700、文件 0600，**用 `copyfile` 不用 `copy2`**，理由同 `feishu.json`
—— 防 `st_flags` 被搬进备份）。`*.state.json` 有意不备：运行态每天变，丢了最多重发一次提醒。

`drill` 也会把 `etc/` 恢复到临时目录并逐文件比 sha256，同时与线上内容比 —— 若线上在备份之后
改过配置，会报「与线上内容不同（备份后又改过？）」，那是提示不是失败（不改变 `drill` 的通过判定）。

## 命令

```bash
python3 ~/.local/bin/wb-autoloop-backup.py backup        # 打一份 + 补拷 + 校验 + 轮转
python3 ~/.local/bin/wb-autoloop-backup.py check [--all] [--json]
python3 ~/.local/bin/wb-autoloop-backup.py drill         # 真恢复演练
python3 ~/.local/bin/wb-autoloop-backup.py daily         # launchd 入口：备份→校验→出问题才推
python3 ~/.local/bin/wb-autoloop-backup.py self-test     # 15 项故障注入
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
   若移除该版本，作业静默不跑且无人知道。缓解①：`tests/test_deploy_sync.py::TestBackupGate::
   test_plist_points_at_existing_python` 会在路径失效时变红（前提是有人跑测试）。
   缓解②（外部观测，已接线并实测）：见下节。

## 外部观测：healthchecks.io 独立 check

**为什么不复用 Mac Alive（`com.user.wb-heartbeat` 那条）**：两者回答的问题不同。
Mac Alive 回答「机器还活着吗」（10min 一拍）；本 check 回答「昨晚的 hub.db 备份跑了吗」。
合并的话，机器活着就会盖住「备份静默停摆」——正是要抓的那一类。

**为什么必须是外部**：本地任何闸门都跑在这台机器上，作业静默不跑时它们一起不跑。
只有「另一台机器按周期等打卡、收不到就报警」能覆盖这种情况。

**语义（脚本已实现，`cmd_daily`）**：

| 阶段 | 请求 | healthchecks 侧 |
|---|---|---|
| 开始 | `GET <url>/start` | 记为 running |
| 通过 | `GET <url>` | 记成功、重置计时 |
| 失败 | `GET <url>/fail` | **立即**告警，不等周期 |

**配置**：`~/.local/etc/wb-autoloop-backup.conf`（0600，不进 git）

```
HC_BACKUP_PING_URL=https://hc-ping.com/<uuid>
```

未配置时脚本**明说**「外部收不到打卡，check 会一直红」，不静默当成功 ——
`_ping()` 永不抛异常、永不影响备份结论，`tests/test_deploy_sync.py::TestBackupPing` 守这三条。

**建 check 时填的值**：Name=`Autoloop Backup`、Period=`1 day`、Grace=`2 hours`。

✅ **现状（2026-11-24 10:02 建成并实测）**：check 名 `Autoloop Backup`，uuid 仅记前 8 位
`f4b27c1b`（完整 ping URL 在 conf 里 —— 它等于打卡凭据，能伪造成功，不进文档也不进 git）。
建的时候没看到集成选项，保存后到 Integrations 页核对，两条集成均显示
**Assigned Checks `2 of 2`** —— 即 Mac alive 与本 check 都覆盖，不存在「建了个哑 check」。

实测证据（不是「配置写好了」）：

| 证据 | 值 | 说明 |
|---|---|---|
| check 详情 Events | `#1 Started` → `#2 OK` | 10:02 两次，Last Duration 1 sec，new → up |
| 事件 User-Agent | `wb-autoloop-backup/1.0` | 是本机脚本打的，不是别处同名探测 |
| 集成 Last Notification | `Delivered`（2 周 3 天前，非 Failed） | 这条 webhook 历史上真送出过 |
| `wb-autoloop-backup.py daily` 输出 | `打卡[开始] HTTP 200` / `打卡[结束] HTTP 200` | 备份那一步同时通过 12 项校验（A1–A12） |

**没做的一件**：对新 check 造一次 `/fail` 实弹。理由是 11-23 刚因误报往群里道过歉，不再为
「验证」制造假告警。第一次实弹会是真失败（>26h 无打卡），届时以群消息 + check 状态双向核对。

**告警频率（防刷群，已核对语义）**：healthchecks 只在 check **状态变化**时通知（up→down、down→up），
同一 down 状态下重复 `/fail` 不重复发。所以连续失败不会每天刷群；对应地，「持续失败但已通知过一次」
的沉默由脚本本地那条 7 天提醒补上 —— 两条链路是互补而非重复。恢复时 healthchecks 会再发一次 up 通知。

**两条建 check 的路径都留档**：

- 浏览器（本次实际走的）：Add Check → 填 Name/Period/Grace → Save → 去 Integrations 页核对 `N of N`
- API（`bin/hc-create-check.py`，需 Full access key）：`list` 先查重再 `create`。
  ⚠️ 该路径**未实跑**，只验证了缺 key / key 过短 / 端点不可达三条降级分支

⚠️ 踩过的坑：用 `pbpaste > key 文件` 让人存 key 是坏设计 —— 对方要粘命令就得先复制命令，
剪贴板里刚复制的 key 被命令覆盖，结果文件里存的是命令本身（实测 79 字符正是那条命令）。
存凭据别让用户同时做「复制值」和「复制命令」两件事。

## 轮转与删除

保留最近 8 份（≈216MB）。删除快照前若曾触发 A11，先 `chflags -R nouchg <目录>`，
否则 `rm -rf` 会被拒（`uchg` 连 root 也拦）。

## 复盘

Claw 仓 `.learnings/2026-11-23-hub-db-single-copy-and-copy2-uchg.md`（坑 28–33）。
