# SuperAgent 五项能力对照：本机中台缺口与处置

**来源**：《从 Agent Team 到常驻 SuperAgent》（Ooder 架构组，2026-11-04）。原文只到 5.5（后半为付费预览），
可用的判断集中在五点：Router/Worker 分层、conversationId Thread 直通、两级事件过滤、启动只读恢复、Watchdog + 三档回滚。

**一句话结论**：本机中台的「传输、派发、串行化、幂等、事件过滤」已经够用，缺的是文章强调的**系统层收口**——
非终态轮次无人收敛、运行中没有进展判据、没有全局开关。前三项已落地为 `bin/autoloop-warden.py`（16/16 自检通过）；
Thread 直通与 `unknown` 收敛涉及内核状态机与锁定配置，判 **no-go（本期）**，路径见第四节。

---

## 一、逐项对照

| # | 文章能力 | 本机现状（证据） | 判定 |
|---|---|---|---|
| 1 | Router 常驻、管关系不干活 | 内核 tick 常驻（`app/host/server.ts:78-100`），规则匹配与派发在 `kernel/decide.ts:225-253`；执行体无状态、每轮重建 `messages=[system,user]`（`autoloop-deepseek:997-1000`） | **已具备**。代价是"没人记得上一轮"，属第 5 项范畴 |
| 2 | 同会话单写者串行 | `claimNext` 四道闸门：同组同 lane 唯一 + groupLimit + maxActive + agent 上限（`decide.ts:310-323`）；实测历史最大并发 2，全是不同规则组 | **已具备** |
| 3 | conversationId 即 Thread + 直通 | `runs.lane` 289 轮**全为空**（`select count(*) ... lane<>''` = 0）；`events` 视图无 chat_id/conversation 列；群维度只有一个全局 `chat_id`（`autoloop-feishu-hub.py:70`） | **缺失**，见第二节 no-go-1 |
| 4 | 两级过滤（程序快路径 + 模型慢路径） | 事实上有 4 层：bridge 启发式（`feishu-event-bridge.py:107-128`）→ hub 白名单 11 条（`autoloop-feishu-hub.py:43-55`）→ 模型语义研判（`Claw/scripts/feishu_ai_triage.py:137-160`）→ 内核类型匹配（`decide.ts:225`） | **已具备，且更强**。唯一缺口：bot 消息/超 2 小时旧消息只写 log，不留原因（见第三节 P2） |
| 5 | 启动状态机 + 只读恢复（只对账不重派） | worker 侧很强：`worker/runs/*/entry.json` 收养 + `pid + marker` 判活 + 进程组（`worker/worker.ts:207-214,424-504`）。hub 侧**无对账**：`sweep()` 把超租约 claimed 改 `unknown`（`decide.ts:283-288`）后无人收口，而 `CLI stop` 只认 claimed（`decide.ts:827`） | **半缺失**。claimed 死轮已能收敛（warden reconcile），`unknown` 仍黑洞 |
| 6 | Watchdog 判"有无实质进展" | 事后有（`autopilot_gate_check.py` 判产物/QUEUE/HANDOFF）；中段无——运行中只有 5 分钟心跳与 180 分钟超时；且 `wb-job-watch.py:50-54` 的 4 个 job 里**没有 agent-autoloop** | **缺失**。warden progress + status 补上 |
| 7 | 三档回滚（全局开关 / kill switch / 单会话） | 规则级 `pause/resume`（`decide.ts:696-762`）、单轮 `stop`（`decide.ts:831-840`）、通道级标志文件（`feishu-bridge-active`）。**无全局开关**：停中台只能 `launchctl bootout`，而 detached agent 还在跑 | **缺第一档**。warden pause-all / resume-all 补上 |

---

## 二、no-go（本期不做，理由与路径）

### no-go-1：conversationId Thread 直通

- **为什么想要**：群里连问两句，第二句现在被压进同一条「规则一条串行道」，没有"这件事归谁"的归属。
- **为什么不现在做**：需要同时改三处——① `events` 增会话列（`protocol/validate.ts:52-85` 与 schema）；
  ② 给群消息规则开 `parallel` 让 `lane = event.subject`（`decide.ts:251`）；③ 改 `rules.json`。
  而 `rules.json` 是 `chflags uchg` 的配置真源，`autoloop-deepseek` 内置 `forbidden_config_mutation()` 拦截写入，
  越界改会同时打破「配置真源保护」与字节闸门。
- **更便宜的近似**（建议下一步）：不动内核，把会话归属放到旁路——bridge 侧按 `chat_id + root_id` 维护
  `~/.agent-autoloop/sessions/<chat>.json`（焦点 / 最近三轮 / 未完成事项），emit 时把该摘要塞进 `--detail`。
  内核照旧无状态，但"谁记得这件事"落到文件上，可回放、可审计。

### no-go-2：`unknown` 的自动收敛

- **现状**：能收敛的只有 claimed 死轮（`agent-autoloop stop`）。`unknown` 在内核里是可回填的中间态
  （`finish` 仍接受 `claimed|unknown`，`decide.ts:495`），但没有"确认死掉"的出口。
- **最小补丁**（待你批）：`decide.ts:827` 的 `heldRun(..., ["claimed"])` 放开到 `["claimed","unknown"]`，
  再在 `sweep()` 里加一条：`unknown` 且进程与进程组都没了、且超过 N 分钟 → `failed`（附原因）。
  这会改状态机，必须带内核测试一起交，且不能在盘中窗口动。
- **在此之前**：warden reconcile 对 `unknown` 只报不动，并明确指路，不伪造已收敛。

---

## 三、已落地：`bin/autoloop-warden.py`

一个入口，五个子命令，只读 + 官方 CLI，不直写 `hub.db`（真源是 facts 追加日志，直写会撕裂投影）。

| 子命令 | 补的缺口 | 判据（可证伪） |
|---|---|---|
| `status` | 中台"活着不出活"无人发现 | `schedules.next_at` 落在过去 >30 分钟 = tick 没推进；hub 正常时 next_at 恒在未来 |
| `reconcile [--apply]` | 非终态轮次无人收口 | `entry.json` 的 pid 带标记在 ps 里 / 进程组有活人 → alive；两者都没有 → dead；ps 不可用 → doubt（不判死） |
| `progress --idle-minutes 8` | 运行中没有进展判据 | 四信号：stdout 字节、stderr 字节、CPU 时间、exit 文件。连续 N 分钟零增长才报，首次只记基线 |
| `pause-all --apply` | 缺全局开关 | 逐规则走官方 `pause`，并记账"哪些是我停的" |
| `resume-all --apply` | 避免误恢复 | 只恢复自己停的，不碰人手停的 |

**验收记录**（2026-11-26）：

- `--self-test` **16/16 通过**，含四条反例：活进程不被判死、ps 不可用判 doubt 不判死、预演不落任何 CLI 调用、
  apply 只对死轮发 stop（活轮与 unknown 不动）。
- 真实中台只读实跑：`status` → 健康（最后落笔 0 分钟前、定时推进正常、非终态 0 条）；`reconcile` → 0 条。
- 部署走 `./install.sh --apply`；`python3 -m unittest discover -s tests` **69 项全过**（逐字节闸门绿）。

**P2 未做**（不值得现在做）：bridge / hub 的三类静默丢弃（bot 消息、>2 小时旧消息、`sender_type=app`）
只写 log 不留原因。文章要求"被拒绝的事件一定带原因"，但目前这三类是防回环的必要丢弃，噪音大于收益；
若要补，落 `inbox/rejected-<date>.md` 比落库更贴合现状。

---

## 四、待定：要不要挂调度

脚本已在 `~/.local/bin`，但目前只能手动跑。三种接法，代价递增：

1. **并入现有**：`wb-job-watch.py` 的 JOBS 加 `agent-autoloop`（只判进程在不在，最小改动）。
2. **新增 hourly**：`com.user.autoloop-warden` 每小时跑 `status`，有问题才写日志（本机已有 40+ 个 job，需评估噪音）。
3. **挂到每日门禁**：`gate-health-daily.py`（17:25）里加一节 warden 结论，随日报一起出。

选 1 或 3 都能避免再加一个定时器；选 2 最灵敏但最吵。
