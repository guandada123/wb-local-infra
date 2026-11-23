# 工作台档案

> 本档案 2026-11-23 22:5x **重建**：原档随会话工作区被平台生命周期清理而丢失（工作区目录 22:52 被重建为空）。
> 本版依据内盘部署副本 + 基础设施仓 `wb-local-infra` 的实际状态回写；v1.10.0 之前的逐条变更记录已不可恢复，见文末说明。

## 一、使用场景

单人（本人）日常运维与投资的统一入口。目标：把「中台自动化跑得怎么样、有没有卡在我这里、各项目什么状态」三件事，从翻命令行变成开一个页面就看到。

每天实际使用频次：早晚各看一次为主（盘前、盘后）。

## 二、页面清单

单页应用 `index.html`（无框架、无外部依赖，单文件），8 个区块：

| 区块 | 内容 | 交互 |
|---|---|---|
| ① 关键指标 | 10 张 KPI 卡（等你决策/在跑轮次/调度轮次/完成轮次/LLM Token/调度规则/待办/事件/代理请求/代理失败）+ 迷你趋势条 | 今日 / 近 7 日切换 |
| ② 任务进度 | 中台轮次最近记录，含状态中文映射（done/nothing/cancelled/claimed） | 点击展开摘要 |
| ③ 图表 | 轮次趋势 / Token 趋势（SVG 手绘，跟随主题重绘） | — |
| ④ 资产卡 | 模型（rules.json agents）/ 服务（launchctl com.user.*）/ 应用（4 个项目 git 真源 + CI 红灯绿） | Tab 切换 |
| ⑤ 待办 | QUEUE.md TODO 段逐条（按 `- [ ]` 行解析，非 markdown 分块） | — |
| ⑥ 日志与告警 | hub.db events 300 条 + **launchd 服务日志真实报错** | 级别筛选 / 时间范围 / 搜索 / 每页 20 |
| ⑦ 快捷操作 | 6 个白名单动作（4 只读 + 2 需确认） | 点击执行 + 确认 + 结果回显 |
| ⑧ 页尾 | 数据接入现状说明 | — |

访问地址：http://127.0.0.1:3355 （仅本机 127.0.0.1，未做鉴权，不外网暴露）

## 三、数据源清单

| 数据 | 真源 | 状态 |
|---|---|---|
| KPI / 任务 / 图表 / 事件日志 | `~/.agent-autoloop/hub.db`（runs/schedules/events，`mode=ro` 只读） | ✅ 接通。events 取样最近 300 条（非总数） |
| 日志区·服务真实报错（v1.9.2） | `~/.agent-autoloop/logs/*.log`（launchd 各服务日志，只读尾部 256KB） | ✅ 接通。抽 traceback/exception/error/failed/rc≠0；**时间只认行内时间戳，无则留空**；滤 `[JUDGE]` 与栈体行 |
| Token 用量 | `runs.usage`（**JSON 文本**，需 `json.loads`） | ✅ v1.10.0 修复：此前 `isinstance(u, dict)` 恒假 → Token 长期显示 0 |
| 模型卡 | `~/.agent-autoloop/rules.json` agents | ✅ 接通（只读；该文件有 `chflags uchg`） |
| 服务卡 | `launchctl list` 的 `com.user.*` | ✅ 接通 |
| 待办 | `Claw/.autopilot/QUEUE.md` TODO 段 | ✅ 接通（按 `- [ ]` 行） |
| 应用卡 git | 各项目目录 `git status --branch` + `log -1` | ✅ 4/5 命中（QTS 无本地 git → 标「未定位」，不伪造） |
| 应用卡 CI | `~/.agent-autoloop/hub-ci-cache.json`（后台 15 分钟刷新，由 `hub-ci-status.py` 写） | ✅ 接通 |
| 代理请求数 | `~/Library/Logs/proxy-deepseek.stdout.log` + `~/.agent-autoloop/hub-proxy-daily.json`（每日快照，取 max） | ✅ 接通，重启不归零 |
| 等你决策 | `agent-autoloop status --json` 的 `totals.attention` + 首张卡标题 | ✅ 接通 |

## 四、自动化规则

| 名称 | 类型 | 频率 | 作用 |
|---|---|---|---|
| `com.user.hub-overview` | launchd 常驻 | KeepAlive + RunAtLoad | 跑 `hub-overview-server.py --port 3355 --static-root ~/.local/share/hub-overview` |
| `com.user.hub-overview-watch` | launchd | 每 600 秒 | 探活；状态翻转（up↔down）才发飞书，避免刷屏 |
| CI 缓存刷新 | 主接口内子进程 | 15 分钟过期 | 调 `hub-ci-status.py` 写 `hub-ci-cache.json` |

写入点（知情披露，共 3 个，均在 `~/.agent-autoloop/`）：`hub-overview-watch.state`、`hub-proxy-daily.json`、`hub-ci-cache.json`。hub.db / rules.json / QUEUE.md / 实盘账本**从未写入**。

快捷操作白名单（服务端固定 argv，前端只传 key）：`status` `doctor` `inspection` `digest_dry` `ci_status`（只读）+ `diagnose` `repush_daily`（需 ack 确认）。

## 五、权限说明

- 服务用 `~/.workbuddy/binaries/python/versions/3.13.12/bin/python3` 启动（**必须**：后台进程读外置卷 ZHITAI 需 TCC 授权，系统 python 会静默 EPERM）
- 凭据：本工作台**不持有任何凭据**。飞书推送走中台已有的 `~/.agent-autoloop/feishu.json`（由 watch 脚本经既有通道发出），本工作台不读它
- 审计日志：`~/Library/Logs/hub-overview-actions.log`（每次动作的关键字段）
- 端口 3355 仅监听本机；跨机访问需另加 TLS + token，当前未做

## 六、待优化项

- [x] 主接口响应缓存（5s TTL）、动作后失效
- [x] 跨卷访问优化（QUEUE/git 结果缓存，冷采集 1.0–2.3s → 0.09–0.4s）
- [x] 日志区接服务日志真实报错（v1.9.2）
- [x] **Token KPI 修 0**（v1.10.0，见变更记录）
- [x] **页面纳入版本控制**（v1.10.0，`wb-local-infra/share/hub-overview/index.html`）
- [x] 源码持久化闭环（v1.10.1：部署器 → `wb-local-infra/workbench/install-hub-overview.sh`、档案 → `docs/hub-workbench.md`、页面 → `share/hub-overview/index.html`、服务端与探活 → `bin/`；**空机验证**：git clone 一份即可重建，7 个文件齐、服务端可编译、页面 JS 可解析）
- [x] `share/` 同步闸门（v1.10.1：`tests/test_share_sync.py`，逐字节 + 负控——只改 live 一字节必须报红、恢复必须变绿、文件缺失必须报红）
- [ ] 交互未验证项（L12/L15/L17）：资产卡按钮、日志翻页、级别筛选需人工点一次
- [ ] 代理日志无自动轮转（约 0.5MB/天，靠只读尾部 4MB 保性能）
- [ ] 「打开 QUEUE 台账」**不接**：后台服务执行 `open` 无 GUI 上下文，纯摆设

## 七、变更记录

| 版本 | 日期 | 摘要 |
|---|---|---|
| v1.10.1 | 2026-11-23 | **持久化闭环 + 部署器/闸门入仓**：① 部署器从「工作区 → live」改为「**仓 → live**」（`workbench/install-hub-overview.sh`，默认 dry-run、`--apply` 才落盘 + kickstart + 探活非 200 即失败）；② 档案入仓 `docs/hub-workbench.md`、补 `workbench/README.md`（三处文件关系/部署/回滚/两道闸门/边界）；③ 新增 `tests/test_share_sync.py`（share ↔ live 逐字节 + 三项负控）；④ 实测：`--apply` 端到端新 pid 起、页面/API 200、Token 仍 77809.7k；全量闸门 **41 tests OK**；⑤ 空机重建验证——clone 一份即 7 文件齐备、可编译可解析。提交 `cf01d02` 已推远端 |
| v1.10.0 | 2026-11-23 | **源码恢复 + Token 假数字修复 + 页面入仓**：① 会话工作区被平台清理后，从内盘部署副本恢复 server/index/deploy 四文件，与部署副本逐字节一致；② 修 `LLM Token(今日)` 长期显示 0 —— `runs.usage` 在库里是 JSON **文本**，代码只判 `isinstance(dict)` 恒假，改为先 `json.loads`，实测今日 **77,809.7k（=7781 万，与中台口径一致）**、7 日 337,226k；③ 页面纳入 `wb-local-infra/share/hub-overview/index.html`（此前是唯一无 git 的产物），两笔提交已推送远端；④ 重建本档案（原档随工作区丢失）。 |
| v1.9.2 | 2026-11-20 | 日志区接 launchd 服务日志真实报错（8 条真错，含 feishu-hub-launchd 502、feishu-events TCC EPERM）；时间只认行内时间戳；滤 JUDGE 与栈体行 |

> v1.9.1 及之前（v1.0.0 → v1.9.1，含数据接入、白名单 6 动作、双主题、日志分页、代理日志改持久路径、CI 进卡、等你决策等）的逐条记录随原档丢失。已完成的功能状态见第二节与第三节，代码历史见内盘副本 mtime 与 `wb-local-infra` 提交历史。

## 八、待确认（本轮实测留痕）

- `card 41「项目自动驾驶」的回执读不懂`（2026-11-23 13:36，run 252）：按 `app/protocol/validate.ts` 逐条比对，那份回执（`{"later":[{"key":"t027-commit-ci-verify","at":"2026-11-24T06:30:00+08:00","about":…418字}]}`）**应全部通过**（key≤100、at 带时区、about≤4000、无 cancel、对象非数组）。故拒绝原因不在回执本身，**未定位**。同类卡片 2026-11-19 已出现一次（#34），属复发。
