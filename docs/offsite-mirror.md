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

代码仓不在此列（11 个仓都有 GitHub 远端）；`hub.db` 与 `~/.local/etc/*.conf` 由
`wb-autoloop-backup.py` 覆盖；`workbuddy_data` 下的 `binaries`(4.9G) / `logs`(1.4G) /
`file-tree-manifests`(2.9G) 可重下或可重建，有意不镜像。

落点：`~/Backups/offsite-mirror/<相对路径>`，内盘，按 `st_dev` 校验异卷。

## 三、判据 V1–V5

| id | 判据 | 判红条件 |
|---|---|---|
| V1 | 异卷 | 源与落点 `st_dev` 相同（路径前缀靠不住） |
| V2 | 每项存在且非空 | 某项 0 文件，或通配展开为 0 个目录（源不可见 ≠ 全通过） |
| V3 | 集合包含 | 源有而落点无；落点偏短而源未再更新；落点比源大；落点 0 字节 |
| V4 | 抽样 sha256 | 默认 30 个，`--sample 0` 全量。防同大小内容损坏 |
| V5 | 落点旧文件 | 只 WARN。这是一份备份，不跟随删除 |

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
python3 ~/.local/bin/wb-offsite-mirror.py self-test  # 13 项故障注入（每项断言恰好那一项红）
```

首次实测（2026-11-24 12:14–12:31）：32,833 文件 / 6.6GB，V1–V5 全过、V4 抽样 30 个一致、
增量 run 8 秒、launchd 实跑 `last exit code = 0`、外部 check 收到打卡（Last Duration 17s）。

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
