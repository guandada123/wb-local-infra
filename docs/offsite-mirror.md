# 离线镜像：把「只此一份」的数据复制到内盘

2026-11-24 建立。解决的问题不在备份工具上，而在**备份指向了错误的盘**。

## 一、为什么做

`~/WorkBuddy` 与 `~/.workbuddy` 都是软链，指向 `/Volumes/ZHITAI`：

```
/Users/guan/WorkBuddy      -> /Volumes/ZHITAI/WorkBuddy
/Users/guan/.workbuddy     -> /Volumes/ZHITAI/workbuddy_data
```

也就是**用户产生的全部数据都在那块 2TB 便携 SSD 上**。而此前唯一的整机备份手段是
Time Machine —— 它没有配置任何目标（`No destinations configured`）。

更关键的一点：**Time Machine 的目的地卷不会被 TM 自己备份**。把 TM 指到 ZHITAI，
得到的只是内盘那 123G（系统 / 应用 / `~/Library`，重装能重建），而真正不可替代的
这 6.6G 恰好落在保护范围之外。所以正确做法不是「等第三块盘」，而是先把这几块
**靶向复制到内盘剩余空间**（62G 可用）。

内盘剩下的 123G 已用空间里，值得救的部分（`~/.agent-autoloop/hub.db`、`~/.local/bin`、
配置）各有各的副本：`wb-autoloop-backup.py` 每日 23:40 把 hub.db 等送到 ZHITAI，
仓里也纳管了脚本与配置。所以本作业只做**反方向**：ZHITAI → 内盘。

## 二、覆盖清单

`bin/wb-offsite-mirror.py` 的 `ITEMS`（相对 `/Volumes/ZHITAI`）：

| 项 | 文件数 | 体积 | 为什么它只此一份 |
|---|---|---|---|
| `WorkBuddy/Claw/output` | 4,101 | 714M | 早晚报/周报/前瞻等产物。`git ls-files output` 只有 1 个文件 —— 全在 `.gitignore` 里 |
| `workbuddy_data/projects` | 28,067 | 5.5G | 全部会话历史（JSONL）。mem-search 索引的源，丢了搜不回来 |
| `WorkBuddy/*/.workbuddy/memory` | 690 | 15M | 各 workspace 的记忆。Claw 下 157 个里仅 22 个在 git 里 |

另外**点名单文件库**（`DB_ITEMS`，不进 rsync 清单，走 sqlite 在线快照）：

| 项 | 体积 | 为什么它只此一份 |
|---|---|---|
| `workbuddy_data/workbuddy.db` | 261M | WorkBuddy 自己的库：`automations` 240 条、`sessions` 13,945 条、`automation_runs` 3,422 条。全机的定时自动化配置都在这一个文件里，2026-11-24 审计确认**没有任何作业在备份它** |

代码仓不在此列（11 个仓都有 GitHub 远端）；`hub.db` 与 `~/.local/etc/*.conf` 由
`wb-autoloop-backup.py` 覆盖；`workbuddy_data` 下的 `binaries`(4.9G) / `logs`(1.4G) /
`file-tree-manifests`(2.9G) 可重下或可重建，有意不镜像。

落点：`~/Backups/offsite-mirror/<相对路径>`，内盘，按 `st_dev` 校验异卷。

## 三、判据（V0 写前闸门 + V1–V6 事后校验）

### V0 容量闸门 —— 在动手之前

这份镜像**只增不删**（见下 V5），体积只会涨。内盘被它写满不是「备份失败」这么轻的事：
系统更新、编译临时文件、sleepimage 都要那块盘，写满会把与备份无关的工作一起弄坏。所以
容量是闸门，不是报表：

| 项 | 规则 |
|---|---|
| 待写量 | 按**相对路径集合**算「源有而落点无、或大小不同」的字节数 |
| 需要量 | `待写 × 1.10 + 64MiB`（rsync 写临时文件再 rename，同一份会短暂占两份） |
| 放行条件 | `可用 − 需要量 ≥ 20GiB` |

不放行时 `run` 直接 `rc=3`，**一个文件都不写**，状态里记 `V0`，`daily` 随之打 `/fail`。

为什么要按路径集合、而不是「源总量 − 落点总量」：落点积着源里已删除的旧文件时，旧文件
会把这笔增量抵消掉、甚至算出负数，于是「空间不够」被算成「不用空间」。self-test 里
「落点旧文件抵消增量」这条用例带**对偶断言**——同一组输入下旧口径必须放行，否则这个
用例证明不了任何事（变异测试实测：把 `pending_bytes` 换回旧口径，17 项里恰好那 1 项变红）。

| id | 判据 | 判红条件 |
|---|---|---|
| V1 | 异卷 | 源与落点 `st_dev` 相同（路径前缀靠不住） |
| V2 | 每项存在且非空 | 某项 0 文件，或通配展开为 0 个目录（源不可见 ≠ 全通过） |
| V3 | 集合包含 | 源有而落点无；落点偏短而源未再更新；落点比源大；落点 0 字节 |
| V4 | 抽样 sha256 | 默认 30 个，`--sample 0` 全量。防同大小内容损坏 |
| V5 | 落点旧文件 | 只 WARN。这是一份备份，不跟随删除 |
| V6 | 单文件库副本 | 副本缺失 / quick_check 不过 / 与 sidecar 字节数或行数不符 / 快照超过 26h |

### V6 为什么不用 rsync，而要 sqlite 自己拷

`workbuddy.db` 是 **WAL 库且正被 WorkBuddy 写**。文件级复制（`cp` / rsync）可能拿到
「一半旧页一半新页」，而 `-wal` 里还有没落盘的提交 —— 拷出来的东西能打开、能查表，
但数据是错的。所以走 `sqlite3.Connection.backup()`：sqlite 自己在读事务里逐页拷，给的
是一个自洽时间点；拷完再 `journal_mode=delete`，副本自成一体（不依赖 `-wal`/`-shm`），
最后 `os.replace` 原子落地，绝不出现半截副本。

副本能不能信，靠两条**不同来源**的证据：

| 证据 | 防的是什么 |
|---|---|
| sidecar（`*.snapshot.json`：字节数 + 每表行数 + 时间） | 副本落地后被改过 / 被部分重写 / 过期 |
| 源读数区间（备份前、备份后各读一次，副本行数必须被夹住） | **副本自证抓不到的那类错**：拷错库、只拷了 schema、空库 |

第二条是补上的：sidecar 的行数是从副本自己算出来的，一个系统性错误的副本也会「自洽」。
源是活的，行数会变，所以不能要求相等，只能要求落在两个真实读数构成的区间内 ——
这是唯一不靠副本自证的口径（self-test 里两条对偶用例分别验「夹住算过」和「出区间必红」，
变异测试：把区间判据改成永远放行，25 项里恰好那 1 项变红）。

### V3 为什么这么绕

源是活的 —— 会话 JSONL 随时在追加。于是「大小不同」有三种原因，必须分开：

| 现象 | 判定 | 依据 |
|---|---|---|
| 落点缺文件，源文件 mtime **晚于**上次成功 | WARN（下次 run 补） | 上次成功之后才出现 |
| 落点缺文件，源文件 mtime 早于上次成功 | **FAIL** | 该拷的没拷到 |
| 落点偏短，源 mtime 更新 | WARN（正常增长） | 复制后源又被写过 |
| 落点偏短，源 mtime 没更新 | **FAIL** | 复制不完整 |
| 落点比源大 / 落点 0 字节 | **FAIL** | 只可能是坏的 |

单靠「落点内容是源的前缀」**区分不了增长与截断** —— 截断也是前缀。这条是写这一版时
实测出来的：先只用前缀判据，故障注入里「文件被截断」那条变绿了（10/11），补上 mtime
判据才抓住。

还有两个反向闸门，防止「WARN 变多等于没人管」：

- 新增文件数 > max(2, 总数×0.5%) → FAIL
- 距上次成功 > 26 小时 → FAIL（镜像停了，不是源在动）

## 四、调度与外部观测

- `launchd/com.user.wb-offsite-mirror.plist`：每日 **03:20**（23:40 的 hub.db 备份之后，
  08:00 自动化与 09:25 开盘之前），`LowPriorityIO` + `Nice 5`
- 三组 healthchecks **不能合并**：Mac alive（机器活着吗 / 10 分钟）、Autoloop Backup
  （hub.db 备份跑了吗 / 1 天）、Offsite Mirror（镜像跑了吗 / 1 天）。合成一个 check 时，
  活着的那部分会把停摆的那部分打成绿的

| 阶段 | 请求 | 语义 |
|---|---|---|
| 开始 | `GET <url>/start` | 记 running |
| 通过 | `GET <url>` | 记成功 |
| 失败 | `GET <url>/fail` | 立即告警 |

配置：`~/.local/etc/wb-offsite-mirror.conf`（0600）里的 `HC_MIRROR_PING_URL=`。
未配置时脚本**明说**「外部收不到打卡，check 会一直红」，不静默当成功。

## 五、命令

```bash
python3 ~/.local/bin/wb-offsite-mirror.py run        # rsync 增量 + 立即校验
python3 ~/.local/bin/wb-offsite-mirror.py verify     # 只校验（不动落点）
python3 ~/.local/bin/wb-offsite-mirror.py daily      # launchd 入口：备份→校验→打卡/告警
python3 ~/.local/bin/wb-offsite-mirror.py status     # 上次结果与距上次成功
python3 ~/.local/bin/wb-offsite-mirror.py self-test  # 故障注入（每项断言恰好那一项红）
```

自检当前 25 项：V1–V5 各 1–2 项、V0 容量 4 项、V6 库快照 8 项。

库副本实测（2026-11-24 12:43）：`workbuddy_data/workbuddy.db` 262MB / 20 表 / 0.7 秒；
独立打开副本读到 `automations` 240 条、`sessions` 13,945 条、`automation_runs` 3,422 条、
自动化名称为真实值、`quick_check=ok`、无 `-wal`/`-shm` 残留 —— 这是「能读出来」而不是
「校验通过」的证据。

首次实测（2026-11-24 12:14–12:31）：32,833 文件 / 6.6GB，V1–V5 全过、V4 抽样 30 个一致、
增量 run 8 秒、launchd 实跑 `last exit code = 0`、外部 check 收到打卡（Last Duration 17s）。

打卡**端到端**复验（12:36）：`daily` 打出 `打卡[start] HTTP 200` / `打卡[success] HTTP 200`，
随后在 healthchecks 面板读到 `Offsite Mirror` 绿点、`Last Ping 10 minutes ago`、
`Period 1 day / Grace 2 hours`。
「HTTP 200」只证明对面收下了，不证明 check 里那条记录是绿的 —— 两步都要看。

## 六、残余风险（未解决，按严重度）

1. **单设备风险**：镜像落在内盘，源在外置盘，但**两块盘都在同一台机器上**。整机丢失 /
   被盗 / 火灾 = 两份一起没。只有异地（第三块盘放别处、或对象存储）能解决。
2. **未加密**：ZHITAI `Encrypted: No`，FileVault 仍为 `Off`。镜像里含会话历史全文。
   落盘权限 0600 只挡别的用户，挡不住拆盘。
3. **Time Machine 仍未配置**：见下节 —— 被 macOS 的 TCC 挡住，需要人的手。
4. **本作业也无法自证「自己没跑」**：靠 healthchecks 外部 check 覆盖（同上）。

## 七、Time Machine 为什么没配上（实测记录，不是推测）

两次尝试，都拿到 root，都被拒：

| 路径 | 结果 |
|---|---|
| `osascript -e 'do shell script "tmutil setdestination -a /Volumes/ZHITAI" with administrator privileges'` | `tmutil: setdestination requires Full Disk Access privileges ... (80)` |
| 同上，但改为写一次性 `/Library/LaunchDaemons` plist、由 **root 的 launchd** 执行同一命令 | 同样 `rc=80` |

结论：macOS 26 上 `tmutil setdestination` 要求调用进程有 **Full Disk Access**，
**root 不等于有权限** —— 这是 TCC 归因，不是 UNIX 权限。授予 FDA 必须经 GUI。

因此 TM 只能由人在 GUI 里配：系统设置 → 通用 → 时间机器 → 添加备份磁盘 → 选 ZHITAI。
（或先把某个终端 App 加进「完全磁盘访问权限」，再跑上面的 tmutil。）

**注意方向**：TM 指到 ZHITAI 保护的是**内盘** 123G。ZHITAI 上的数据要靠本镜像（已完成），
以及将来的第三块盘。两者互补，不可互相替代。
