# 关 — 长期记忆

**速查索引**（grep 入口）
**本文件**：注入上限 · 规则层 76 条各一行（止于 **7,915B**）· 铁律证据库 · 截断点
**其余**：项目·跨项目集成·跨项目架构方法论·长程Agent工程规范·自动化 preamble 自举(.zshenv)·`automations.last_run_at`·平台行为 cwds 规则·Hy4 夜间免费窗口·运维/CI/Push 全权委托·全项目日常助手授权·模型·持仓·版块·环境·对话·偏好·IMA知识库·workbuddy.db·管理面假成功·模型id·三系统边界·领域分区

## 🔴 铁律（规则层 · 76 条一览 · 证据正文见文末「铁律证据库」）
- 🔴 automation_update 关思考模式：`modelIsThinking` **必须传空串**（传 false/0 因 JS truthy 无效）；`modelId` 可直接改；改完回读 `automations.model_is_thinking`
- 🔴 搜到 ≠ 验完：否决现成方案的理由必须是「查过的」，且必须留复查点
- 删/移文件须「先复制→验证→再删源」+ 删前用户确认
- 🔴 并行 Bash 调用不可靠，且失败是静默的
- Shell 内 `cd` 后再用绝对路径调脚本也可能静默空输出
- 🔴 zsh 下 `source xxx.sh | tail -N` 会让 source 落在子 shell，函数/变量全部丢失
- Sidecar=对话载体，绝对禁止kill（memory_guard 已限 renderer）
- 自动化调LLM必走本地代理(:9999；preamble ensure_proxy 自愈；router 直连 deepseek 必 401)
- 行情/历史K线**腾讯优先**(qt.gtimg/fqkline qfqday)，Wind仅降级
- 🔴 数量骤降优先怀疑口径，而非康复；「条目数」≠「问题数」
- 🔴 `grep -c` 返回 0 时先验证模式本身能命中，再信"查无此物"
- 🔴 判自动化是否派发只认 `logs/automation.log` 的 run start/finished 事件对（DB/session 锚都会骗人）
- 🔴 WorkBuddy 调度器 `concurrency=3` 是装饰性的, 不执行限流
- 🔴 在飞/间隔类统计探针必须先自检配对口径（禁按 (id,时间戳) 配对；按 id 维护 open 队列 + 总量交叉校验）
- 飞书推送卡片化(push_card.py)禁--text降级；改脚本先--dry-run
- lark-cli 发消息默认身份=user 但缺 `im:message.send_as_user` scope
- 🔴🔴 诊断纪律：先抓证据日志再下结论，禁脑补根因；基线分层算 p50/p90；代理9999无 logprobs 真值
- 🔴 automation_update 改模型/专家用 camelCase（`modelId`/`modelIsThinking`/`expertId`/`expertMarketplace`）
- 🔴 监控/取证/告警类任务不得跑在被观测对象上（哨兵模型固定 hy3；不得跑在被观测时段内）
- 🔴 `source <preamble/shell脚本>` 不得接管道
- 🔴 多层缓存必须按"单次成本升序"排列
- 🔴 写 mock 测试的两个静默失效源（磁盘缓存泄漏须一并 patch；构造期副作用吃光 mock 队列→空异常消息）
- 🔴 静态快照类数据源必须有「刷新脚本+过期告警+备份」三件套
- 🔴 验证 `trap EXIT` 清理必须另起一个 shell 调用
- 🔴🔴 经验闭环(必走 incident-triage → 写项目 .learnings → 周度升级；不写=没吸取教训)
- 🔴 单链路日志≠全链路, 禁脑补归因
- 🔴 双自动化并发操作同一目标须互斥
- 🔴 容器/服务重启须连带重建 daemon 调度器
- 🔴 项目脚本目录禁与 stdlib 同名模块
- 🔴 `source xxx.sh | 管道` 会在子shell执行，函数不进父shell
- 🔴 A股股数必须整手（int(round(x/100))*100 且 ≥100；禁裸 round(金额/价)）
- 🔴 日志成功≠数据落库, 凡写库须 readback
- 🔴 容器内定时器(APScheduler)必须单 worker
- 🔴 第三方 GitHub Action 浮动 tag 会静默弄红 CI
- 🔴 Laravel 迁移禁共享时间戳+跨表外键
- 🔴 策略回测须过带成本全样本+随机对照
- 🔴 板块强弱判断禁单日涨跌幅
- 🔴 自动化 refusal/失败集群须按 code+reset 时间戳聚类定因
- 🔴 自动化模型配置在 workbuddy.db，不搜"混元"
- 🔴 僵尸一次性自动化必须定期清理
- 🔴 hy4-preview 无视觉能力，涉图任务禁挂 hy4
- 🔴 项目路径落外置SSD/符号链接须防静默失败
- 🔴 数据层/HTTP 调用禁止静默吞非 200 响应
- 🔴 CI 红排查须先验"时间相关 flaky"
- 🔴 AI 功能"降级"须显式区分 LLM 失败 vs 数据不足
- 🔴 校验/占位符/安全检测必须下沉到被复用的内层函数
- 🔴 长耗时扫描/批处理须硬性超时+孤儿进程检测+重跑
- 🔴 检测/守护逻辑「静默失效」三坑（日志须合并 stdout+stderr；「总数 0」先反证；裁剪窗口被单噪声源占满）
- 🔴 告警价值 = 症状准 × 药方对, 频率须匹配可处置性
- 🔴 readback 前先答"回读三问", 读错的 readback 比不读更致命
- 🔴 stale 判定：`next_run_at` 在未来即健康；gap 阈值按 FREQ/BYDAY 分级
- 🔴 验证"读起来像查询、实际会写盘"的函数须做三件事
- 🔴 MCP 工具"找不到"先查 `~/.workbuddy/mcp.json` 的 `disabled` 标记
- 🔴 框架级「成功」≠ 真实产出：`except` 必须 fail-safe 返不通过（缺键算不通过）；`except Exception` 接不住 SystemExit（属 BaseException）
- 🔴 同一语义的值必须单一真源; 「已配置」≠「被读取」
- 🔴 聚合值稳定 ≠ 状态稳定：MAX/COUNT/"持平"会抹平组成变化
- 🔴 容器 TZ=UTC + naive `now()` = 凌晨落库日期错位一天
- 🔴 LLM 逐步编排纯脚本 = 把执行时间暴露给队列，拥堵撞硬超时
- 🔴 外部数据接口验收必须「非空 + 字段完整性」双闸, 重试必须带判据
- 🔴 子进程必须显式锁 `cwd`; 后台派发 + 延迟落盘日志会掩盖失败
- 🔴 一次性取证判据不得依赖易失源+固定窗口（会静默退化不自愈）
- 🔴 数据完整性/新鲜度检查基准必须来自库外（库内自比答不了「缺什么」；须与交易日历做差集）
- 🔴 上游定时任务失败 → 下游静默产出旧结论（本系统最高频事故之一）
- 🔴 行数完整性 ≠ 数值完整性：盘中未收盘数据会让门槛池静默缩水
- 🔴 同形异因：告警命中先确认是否同一铁律的另一种根因
- 🔴 结论字段与证据字段必须一起输出；`dict.get` 静默返 None
- 🔴 低样本/过拟合信号下游禁表述为「推荐/买入信号」，只作统计倾向参考
- 🔴 上游公告「已修复」≠ 我链路已修复：先核平台适用性/走哪条轨/兜底轨能否顶上，再决定恢复
- 🔴 自动化用 MCP 必须先在 UI 勾 connector（API 改不动=管理面假成功）；直取可省三道工序
- 🔴 401 先穷举 5-6 种认证姿势再判死（错的头掩盖对的头）；RSS description 常是完整正文
- 🔴 容器健康 ≠ 可重新部署：带 Dockerfile 项目须把 `docker compose build` 纳入月度巡检（基础镜像刷新会引爆陈旧假设）
- 🔴 CI 红是聚合状态，须拆到 job 粒度定位（`needs:` 上游红静默跳过下游 job）；修上游时须预期下游首次暴露问题
- 🔴 禁写死本机绝对路径（`/Users/guan/...`）；本地全绿 ≠ CI 会绿——推送前用 `git clone --local` 的 tracked-only 树验证
- 🔴 比对口径须对齐(算法+粒度+编码), 否则结论会反: 哈希/diff/readback 任一对不齐→比对无效且给出相反结论而非报错(在用凭据在公开仓被判"已轮换"=P0反向安全结论); 固化成工具(--compare-env)不靠人记
- 🔴 凭据入版本控制防护: 产物型git仓库.gitignore须显式列凭据模式; "索引移除"≠修好(对象库仍在), 检查须落对象库(git cat-file -e); 轮换后须复核在用哈希已异于全历史值
- 🔴 检测必须可证伪, 其绿灯须能被已知正样本击破: 规则空/默认被替换→检测全关(CI密钥扫空跑68天); "取不到证"渲染成"通过"=假绿灯; 凡检测须用已知含目标对象试跑, 0命中即失效

## 项目
Claw(A股投顾核心,105自动化) | QTS(Docker 13容器量化) | StockInsight(桌面分析,外挂SSD) | marvis_bridge(休眠) | pmf(监控面板:8088) | wechat_api+download-api(公众号双轨)

## 跨项目集成（07-16；08-13 升级：Claw↔QTS 打通，不再区分）
🔴 **Claw↔QTS 打通（08-13 用户决策）**：禁互相 import 代码（QTS 在 Docker、Claw 本机，依赖环境不同），但**允许服务直连**——Claw 统一走 `scripts/qts_client.py`（唯一入口：PG 15432 只读 + HTTP API 8000），废除预生成 JSON 桥接(/tmp/qts_daily_brief.json)与 docker exec 容器注入(pull_qts_signals/export_qts_regime 已改直连)。brief 落库 PG `qts_daily_brief` 表单点共享；外部数据消费仍校验 report_date

## 🔴 自动化 preamble 自举（08-31 固化）
- `source $CLAW/.workbuddy/scripts/automation_preamble.sh` 是**自举死锁**：`CLAW` 由该文件自己 export，但调用方展开路径时就需要它。未定义时路径解析成 `/.workbuddy/...`（根目录）→ source 失败 → **L3 护栏(run_l3_pre/post)静默跳过**，而主脚本用绝对路径仍正常跑 → 极易漏判。
- 两层防御（08-31 08:00 修正，**此前只写 .zshrc 属选错文件**）：
  ① **环境层**：`~/.zshenv` 加 `[ -z "$CLAW" ] && export CLAW=/Users/guan/WorkBuddy/Claw`。
     ⚠️ **`.zshenv` 是 zsh 唯一「交互式/登录式/非交互非登录」每次都读的启动文件**；`.zshrc` 只交互式读、`.zprofile` 只登录式读 —— 自动化 runner 多为非交互非登录，写那两个无效（实证 07:45 仍 CLAW=UNSET）。bash 仍不覆盖（非交互 bash 也不读 .bashrc），故必须有第 ② 层。
  ② **调用层（关键，与 shell 无关）**：prompt 里先
     `[ -f "${CLAW:-}/.workbuddy/scripts/automation_preamble.sh" ] || export CLAW=/Users/guan/WorkBuddy/Claw`
     再 `source "$CLAW/.workbuddy/scripts/automation_preamble.sh"`。
     `-f` 校验比 `${CLAW:-默认}` 更强：后者只在 unset/empty 生效，**CLAW 指向错误路径时仍失败**。
- 三个坑：① **Bash 工具环境在会话初始化时快照一次**，改完 rc 本次会话仍看不到；验证须用 `env -u CLAW <shell> -c '<原文照抄的引导片段>'` 起全新子进程测 —— 验证的是**故障条件已解除**，不是正常路径没坏；② source 失败**不中断**后续命令，判护栏是否生效须 `type run_l3_pre` 自检（GUARDRAIL_OK），不能只看主脚本退出码；③ 整轮 rc=**127** = preamble 没解析出来，非脚本故障。
- **教训中的教训**：run#29 改完只验证"source 后能用"，方向反了，所以没发现 .zshrc 对 runner 无效。修法成立与否，必须复现故障条件验证。

## 🔴 自动化运行时间：别信 `automations.last_run_at`（08-31 实证，全平台通用）
- 平台**只在 run 达终态（PENDING_REVIEW）时回写 `automations.last_run_at`**；**托管自动执行（ACCEPTED）不回写** → 该字段会冻结在最后一个"需人工复核"的运行上。2026-08-31 实测 **59 个 ACTIVE 自动化中 52 个（88%）滞后**，滞后量恰为各自调度周期整数倍（日频 48h / 工作日 72h / 周频 168h）。
- 判"某自动化是否漏跑"，**权威锚是 `automation_runs` 表**（`~/.workbuddy/workbuddy.db`，每次派发无条件落记录），取 `MAX(created_at)`；写法 `max(last_run_at, runs[0].created_at)`。
- 连带：`automation_health.py` 里 `next_run > now → stale=False` 会短路掉 gap 判定，所以**只有 `next_run_at` 已过期/缺失的才报 🔴** —— 触发 🔴 的真实条件是"排期元数据没刷新"，不等于"任务真的没运行"。
- 与既有铁律同源（08-12「单链路日志≠全链路」、08-30「条件触发型日志不能反推没运行」）：**判定前先问：这个字段在什么条件下才写？**
- 改监控判据的验证模板：**必须同时跑「故障条件」与「正常路径」双向对照**。只看实跑不够 —— 实跑时短路分支生效，改动的分支根本没执行到（本次实跑只差 1 项，故障条件下差 24 项）。

## 🔧 长程Agent工程规范（08-03）
- **全局状态锚** `~/.workbuddy/cross_project_state.json`：换模型/会话/host先读此恢复现场，再读各项目memory。唯一权威源
- 四原则：①外置结构化状态 ②有界Turn ③验证回读(观察≠transition，对外动作确认实际效果才标done) ④stateful backoff(同identity失败15→30→60→120min)
- skill: `long-running-agent-control-plane`

## 模型
自动化Tier1+2免费/Tier3→deepseek-v4-flash(¥0.06)；本地代理~/.workbuddy/proxy-deepseek.py(:9999)
- 🔴 代理日志=`/tmp/proxy-deepseek.stdout.log`+`stderr.log`；plist `THINK_BUDGET=high` 会对 `deepseek-v4-flash` 注入 `extra_body.thinking` → 返回主`content`空仅`reasoning_content`有值(=reasoning-only降级根因, 08-11确诊)；现已全走积分池(`track=points is_direct=false`) → 再次发生 2026-08-13(read_wx_articles 同根因 reasoning-only)；约束收敛: 凡 deepseek-v4-flash 的结构化JSON抽取任务(文章精读/研报摘要)须 per-request 传 `extra_body={'thinking':{'type':'disabled'}}` 关思考, 代理须**尊重客户端显式 extra_body.thinking**(不无条件覆盖), 否则 reasoning_content 兜底对 JSON 任务无效；CI 契约测试: JSON 类调用方 payload 须含 thinking 关闭字段(已有 test_debate_engine 示例, 推广到 router.call_llm / read_wx_articles)；→ 再次发生 2026-08-17(北辰辩论降级复发, 8/15假修复仅加 content 兜底未关 thinking, 须从源头关 thinking 双写而非靠 reasoning 兜底)
- 三类故障识别: ①连不上→`nc -z`失败, 走ensure_proxy自愈 ②reasoning-only→content空, debate_engine已加reasoning_content兜底 ③服务端internal error→垃圾`!+`token流, debate_engine已加`_is_noise_response`拦截重试。诊断先查日志再定性, 禁脑补

## 💼 持仓（07-15）
实盘:长电600584(300)/华天002185(300)国金 | 模拟盘:美的000333/长电600900/紫金601899,总资¥50,000；user/portfolio.json current_price仅成本,止损实时拉qt.gtimg

## 📌 版块
主板/中小板+创业板(300/301)可；科创688/689、北交8/4禁；创业板-15%止损(主板-8%)

## 环境
**com.workbuddy.memwatch**(08-04启用, 08-11全量修复, 08-12修复三+四)：WB进程树RSS>8500MB 或 整机可用<512MB且WB>800MB 或 压力等级≥4且WB>800MB→优雅TERM+清残留+open重启；**5s轮询**(原10s, 抢在系统OOM前)/连续2次确认(修复二: B/C通道WB>4000MB时SUSTAIN动态降为1)/300s冷却/30min≤2次/mkdir锁防重入/重启后回读验证+会话自检；**强杀识别=告警+自动拉起**(08-12升级: 进程树意外消失→通知+飞书告警+open自动拉起)；**🔴08-12单一配置源: 参数统一在~/.local/etc/workbuddy_memwatch.conf, 脚本=只读逻辑, 巡检中枢bump也只改conf, 禁止任何自动化直接写watch_workbuddy_mem.sh**(08-11 23:45巡检中枢sed脚本打断do_restart停机5h11m根因; unified_ops_center MEMWATCH_TARGET_MB=8500已对齐, bump有2min防打断护栏)；日志~/Library/Logs/workbuddy_memwatch.log；**绝不用pkill -f模糊匹配**(防杀sidecar)；旧memory_guard.py plist已.disabled

## 🗂️ 对话
~/.workbuddy/tasks/<UUID>/；清旧对话走客户端UI(同步db+磁盘),不可rm直删

## 偏好
- **实盘止损不用提醒（2026-09-28）**：H1（长电 600584 / 华天 002185 双仓击穿 -8% 未清仓）**不再每日催办** —— 实盘下单属 human-only，处置权在人。
  落地方式：`cross_project_state.handoff.items[H1].no_reminder = true` + 必填 `no_reminder_reason`。
  ⚠️ **条目不删**（删掉会让账本说谎）：原期限、持仓证据、静音时间都留着；去掉该字段即恢复提醒。
  ⚠️ 缺理由的静音**不生效**（告警照发）—— 防止「关掉提醒」变成绕过检查的后门。
直接结论+结构化分析+验收摘要；飞书主群 oc_9ee5303497f5e0e71666b610d6bdc346
- **技术/专业领域决策授权（09-21 用户显式授权，后扩至泛指协作判断）**：专业判断类问题不要反问"你要怎么处理"，而是直接给**推荐方案 + 理由**并落地执行；破坏性删除/实盘下单/对外发布等仍须用户确认（守既有铁律），其余工程/配置/策略取舍由 agent 代决并说明依据。
- **沟通姿态校准 / 领域分区（09-21 用户请 agent 判断协作模式；20:32 用户自述修正）**：用户自述**金融=专家、计算机/模型/AI=小白(需解释专有名词)**。修正前一轮误判：用户本轮对 git/调度饱和/安全/依赖图推理流利，是因「具备技术读写能力——读得懂讲清的技术论证、能就技术议题拍板」，**非 CS 从业者**；故不可判为全局 principal，须作领域分区校准：
  · **金融领域**：用户为专家，agent 不班门弄斧、不解释基础术语、领域判断以用户为主；涉及金融/投资逻辑用户领衔，agent 只补技术实现。
  · **计算机/模型/AI**：agent 领衔并给推荐方案+理由；专有名词用大白话翻译(译术语、不假设词汇)，但用户能跟上讲清的论证，故非降智式科普而是「术语翻译」。
  · 反驳/委托两模式观感依旧成立：「你定」=agent 全权领衔、「我的看法是X」=对等辩论；反驳视为方向/细节信号而非出尔反尔，直接就内容接招，不把「你定」当禁言令。
  · 禁止因「小白」措辞低估其金融判断力或过度请示；金融相关默认用户领衔。用户若说「这个词什么意思」须补术语解释。
  · （22:1x 用户主动重锚定）CS/模型AI/DevOps 三类**明确由 agent 全权领衔**：用户不抢决策权、不就技术细节反驳、仅保留「术语翻译」请求。用户自承存在「自称小白却偶尔领衔补位/反驳」的观感来源，本次据此纠正——后续此类领域 agent 直接给推荐方案+理由执行、不再回抛决策权。领域地图与证据详见 `Claw/.workbuddy/memory/domain_expertise_map.md` 第二节。
**养猫（08-31 首次提及，居武汉、冬季无集中供暖）**：宠物用品决策偏好=材质安全优先（拒塑料接触面，认 304 不锈钢或釉面陶瓷）、明确要求"一台机器搞定"（拒绝多设备拼凑方案）、但排斥噱头功能。后续宠物类咨询沿用「材质 → 关键参数 → 维护成本 → 实测数据可信度标注」四段式；国内电商参数多为营销号口径（同款温控有 25/30/35/38℃ 多种说法），凡引用具体数值须标注来源口径并提示下单前向客服核实。

## IMA知识库使用约定（08-12）
- 已连 `星辰大海的知识库`(id:001a8910d1c01dc4)，MCP=ima-mcp；当前仅1条官方指南，基本空
- **防污染铁律**：绝不无脑批量灌原始抓取；仅入库「经消化、值得长期复用」的内容(投研框架/个股深度结论/方法论/带出处的数据快照)
- 原始资料(未读研报/公众号/时效新闻)留本地或现有通道，**不自动转 IMA**
- 入库前先定分类结构(建议: 研报精读/公众号精粹/自选股分析/方法论)；建结构本身不污染数据
- 触发式入库：仅当我产出的某份分析结论明确值得沉淀时，经用户确认再入库

## 🔧 运维/工程质量/CI/Push 全权委托（08-04起，08-06用户显式确认）
- **自主管理所有项目 Git 提交/Push**，无需逐项确认；准则：①只提交真实工作，排除构建产物/备份/密钥 ②push前fetch核验远端，非快进先rebase/pull，绝不force ③commit结构化 ④Claw=guandada123/Claw.git(main)
- **基础运维+工程质量+CI 全权负责**。载体：📊1782002834355(Claw单仓质量门禁,交易日18:00) 🔧1785825576843(周日21:00跨仓运维周报) 💾1782394153045备份 🩺1781780654327健康 📦1781871850433dependabot 🛡️1785506975961watchdog 🧹1780769419635记忆；CI状态经 `gh`(guandada123, /opt/homebrew/bin/gh) `gh run list`
- CI基线：仅 Claw/QTS/StockInsight/pmf 有 Actions；wechat 双仓仅 docker-publish/offline-export 只读
- wechat 双仓=同一仓库两份clone(HEAD一致)，origin=`guandada123/wechat-download-api.git`(fork存在可push)，upstream=`tmwgsicp/...`只读上游；wechat_api 备份副本保留不删
- 🔴 公众号断供(08-07确诊)：wechatrss 云端7/30停摆=微信关文章列表接口，平台重构SaaS+桌面客户端；本地5001容器登录有效但**全接口微信风控 ret=200013**→重启/重登治不了，勿空转，暂不建重启自动化

## 🤖 全项目日常助手授权（08-05升级）
- **工程类+监控类+运维类项目全权维护**，无需逐项询问；仍须用户：破坏性删除(守铁律)、实盘下单/发布
- 落地：每日跨项目健康巡检自动化(托管QTS工作区) + 统一巡检中枢(8检查/4Runbook/知识闭环 automation-1786000625371/自愈周报1786000798763) + 监控面含 Docker容器/磁盘/自动化失败扫描

## 🏗️ 跨项目架构方法论（08-07提炼）
> 所有 WorkBuddy 项目对齐此范式
- **五层**：L1 Memory(零Token检索) / L2 Skill三级(原子Atomic→流程Flow→角色Role, 新skill先拆5场景) / L3 Guardrail Hooks / L4 多Agent边界写死 / L5 分发层(单人可缓)
- **自动化契约五要素**：触发(单BYHOUR禁多值)/输入(源+依赖+降级)/输出(产物+推送+模板)/失败保护/有效期
- **权限三层**：沙箱隔离/操作审批(写删发分级对外确认)/目录授权(凭证走env不落git)
- **AI数值防错**：LLM填数值必过三闸门(G1实时偏离>30%/G2 52周区间/G3 MA20锚定)，详见skill `ai-output-sanity-guard`
- 🔴 **`source automation_preamble.sh` 禁止接管道**（09-02 实犯）：`source xxx.sh 2>&1 | tail -20` 会让 source 在**子 shell** 执行，其中定义的 `run_l3_pre` / `run_l3_post` / `ensure_proxy` 等函数在父 shell **全部丢失**，报 `command not found`，L3 护栏层静默失效（护栏失效比报错更危险——看起来跑过了实则没跑）。正确写法：`source xxx.sh >/tmp/preamble.log 2>&1`（重定向，不管道），再单独调用函数。此坑影响所有 100+ 个 source preamble 的自动化。
  - **修正(09-04 01:58 实锤): 「降触发量」路线已证伪, 勿再走**。近24h 触发总量仅 **69 条/47 个自动化**(历史拥堵期 90~106), **更低却依然坍塌** → 触发量不是杠杆。真因是**饿死运行占着槽位 2~7.7h**(排队不计入 90min 计时)构成正反馈, 所以有效动作是「缩短硬超时 / 让排队计入超时」, 不是减少任务数。
  - **实测排队量级(09-03~09-04, automation.log 按 id 配对 start/finish)**: 统一巡检中枢 run#78/79/80 的 start→finish = **217 / 314 / 238 min**, 但**实跑仅 79~180s、RC=0** → 跨度几乎全是排队, 脚本本身零故障。看门狗自身亦同: 257min / **383min** 两段。→ **判据更新: start→finish 跨度大 ≠ 脚本卡死/超时, 须再用 `ps` 看有无进程 + 对比实跑时长(通常 1~3min)才能定性。**
  - **运维层自身挤占被监控对象容量**: Top3 触发方 = 巡检中枢 10 + 失败扫表 watchdog 6 + 存活看门狗 6 = **22 条占 32%**。监控层降频属「可立即执行」但须整体评估(中枢与看门狗互相依赖, 单改一个会触发另一个告警), 待拍板。
- 🔴 **zsh 里 `${PIPESTATUS[0]}` 恒为空串，bash 语法在 zsh 静默失效**(09-06 实犯): 默认 shell 是 zsh，
  zsh 对应写法是 **`${pipestatus[1]}`**（数组，1-based）。用 `cmd | tee log` 再取 `${PIPESTATUS[0]}` 得到空值，
  传给下游（如 `run_l3_post $RC ...`）会因缺参进入**自检/测试模式**——输出仍是 OK 字样且 exit=0，
  **真实执行记录却没入账**，极具迷惑性。正解：**别用管道取退出码**，改 `cmd > log 2>&1; RC=$?`；
  确需管道时用 `${pipestatus[1]}`。凡是"取上一条命令退出码"的自动化，一律先确认 shell 是 bash 还是 zsh。
- 🔴 **zsh 默认不对未引号变量分词(`for n in $names` 整串当单元素, 09-23 实犯)**: 默认 shell 是 **zsh**(非 bash), zsh 的未引号标量变量**不按空格分词**(bash 才分)。`names="a b c"` 后 `for n in $names` 会把整串 "a b c" 当成**一个元素** → 循环体只跑一次、`mv "scripts/a b c.py"` 文件不存在 → 静默失败(moved=0/skipped=1), 看似"执行过"实则 no-op, 极易误判"已去重/已删"。**正解: zsh 用数组 `names=(a b c)`; bash 用 `names=(a b c)` 或 `for n in $names`**。任何"批量 mv/删/遍历文件名"脚本, 先确认 shell + 用数组; 跑完须校验**实际结果计数**(如 `ls trash|wc -l`、目标目录残留=0), 不能只看 exit=0。
- 🔴 **去重/搬迁脚本须先查其根目录解析方式, 别只比字节(09-23 实犯)**: 双副本去重把 scripts/ 的 source_weight.py/signal_consensus.py/qts_client.py 副本移除后, 15:00 信号溯源管线(从 .workbuddy/scripts/ 调用这些 helper)首次失败——`Path(__file__).resolve().parent.parent` 解析 Claw 根**假定脚本在 scripts/(→根)**, 移入 .workbuddy/scripts/ 后解析为 .workbuddy → 找不到 `.workbuddy/data` 与 `data/`。**去重/搬文件前先 grep 目标脚本的 `Path(__file__).resolve().parent` 链与 `os.path.dirname(__file__)` 用法**: 凡靠 `parent.parent` 定位项目根的脚本, 单源必须留在 scripts/ 或改为优先读 CLAW 环境变量(位置无关); 同理任何被其它脚本按相对路径 subprocess 调用的脚本, 搬迁会断调用方。**去重判定"活目录=.workbuddy/scripts"对这类不成立**——修复法: 这类脚本 `_PROJECT_ROOT` 改为优先取 `$CLAW`、否则向上找含 `.workbuddy/data` 的目录。
- 🔴 **状态锚 mtime 不能当心跳佐证（09-08 实犯）**: `~/.workbuddy/cross_project_state.json` 的 mtime
  会被 `automation_preamble.sh` 的 **L3 pre-hook 自身**写脏（实测 pre 10:04:15 → mtime 10:04:32）。
  「mtime == last_ok_ts 即心跳正常」只在无人写锚的静默窗口成立；**跑了 L3 preamble 的自动化自己就污染该判据**。
  心跳一律以 `automation.log` 的 start/finished 事件对 + 锚内 `self_health.last_ok_ts` 为准。
  📌 另：**统一巡检中枢**在日志里的 name 是 `🛡️ 统一巡检中枢（接管所有健康巡检）`，
  **不是** `automation-1781663740184`（那是「Quant 数据管线」，日更一次）—— 别拿错 id 去查心跳。

- 🔴 **回读"状态锚/配置文件"前先 grep 脚本里的路径常量，别沿用上轮路径也别猜文件名**(09-09 实犯):
  看门狗类脚本把锚路径硬编在常量里(如 `CROSS_STATE_PATH = Path.home()/".workbuddy"/"cross_project_state.json"`),
  上轮记下的"正确路径"可能只对另一个脚本/另一个仓; 猜 `Claw/.workbuddy/state/global_state.json` 则 glob 0 命中。
  且锚常是**嵌套**结构, 取字段先打 `TOP KEYS` 再下钻; **下钻字段也可能失真**(如 `self_health.interval_min` 写 1.5 而实测节律 185min),
  交叉验证应以权威日志为准, 别拿可疑字段互证。

## 🔴 调度时段：Hy4 夜间免费窗口 23:00→08:00（09-24 官方口径确认）
- 老大已体验过 Hy4 preview → **夜间闲时（23:00 → 次日 08:00）免费用**，其余时段正常扣积分；未体验过的新用户仍是"首次开启起 14 天每日额度"（政策窗口 09-11→10-10）。
- **凡可整体挪动的 LLM 类自动化，一律排进 23:00→08:00**；不可挪的（盘中监控、盘后依赖当日数据的）保持原时段。
- 排槽要点：①别挤开窗头 30min（23:00–23:30 是全用户涌入潮，易排队）；**跨 0 点后进新额度桶**，00:00–07:00 最稳。②同族自动化间隔 ≥5min。③**读写同一状态文件的自动化必须分处不同时段**（如"发现写 registry"与"周度读 registry"同刻 = 读半成品）。
- 已知仍占扣分时段的 LLM 类（待评估）：`📚【知识库】全网挖掘+文章精读`（每 6h，4 次/天中 ≥2 次在窗口外）、`💓 中枢存活看门狗`（每 2h，24h 全跑）。
- 相关：Hy4 无原生多模态，涉图/OCR 任务会被平台静默切模型并照样扣分（08-30 已固化）。

## 🧩 平台行为：`automation_update` 的 cwds 规则（09-24 实测）
- **create 时不认传入的 cwds** → 平台自动塞一个临时工作区（`/Users/guan/WorkBuddy/automation-YYYY-MM-DD-HH-MM-SS`）；**update 时可以改** cwds。
- **update 拒绝 cwds = `/Users/guan/WorkBuddy/Claw`**（报 `workspace "…/Claw" cannot host automations`）→ Claw 下只能改 prompt/rrule，改宿主得选 `automation-2026-09-21-13-02-04` 这类"常规项目工作区"（统一发现/落地/知识库三槽都在这）。
- **两查法判锁是否活着（通用）**：①`grep -n "done_schedule\|schedule_utils.py done" <prompt>` ②`ls /tmp/claw_lock_<name>_*`。**只 check 不 done = 守卫恒放行**（09-24 踩过：误判为"日锁生效、其余槽空跑"，实为 4 槽全跑）。

## 📎 铁律证据库（逐条复现与取证 · 09-28 从规则层剥离，正文逐字未改）
> 用法：`grep -n "── 证据 37 ──" ~/.workbuddy/user-24688a34-03ff-4299-8736-08d5a6585c6b-personal/MEMORY.md`；**证据编号 = 上方规则层第 N 条**（同序）。
> 共 76 条，默认不可见，按需检索。
> ℹ️ 2026-10-14 记忆维护：原编号**整体偏移 +1**（规则第 1 条在库首插入、证据库未同步重编号；全表 75/75 实测「证据 N == 规则 N+1」）→ 已重编号为 2–76 并回填 证据 1。「用法」行原指旧副本 `~/.workbuddy/MEMORY.md`（自 10-11 冻结、内容已分叉），已改为自指。

**── 证据 1 ──**
- 🔴 **`automation_update` 关思考模式（回填占位 · 2026-10-14；原始取证记录缺失）**：该规则由会话直接写入规则层、未附证据，导致编号整体错位。要点：关思考模式时 `modelIsThinking` **必须传空串** —— 传 `false`/`0` 会被 JS truthy 判真而无效；`modelId` 可直接改；改完必须回读 `automations.model_is_thinking` 核对。
- ⚠️ 本条**没有原始事故复现**，内容等同规则行；日后找回原始取证请**替换本块**（不算新增条数）。

**── 证据 2 ──**
- 🔴 **搜到 ≠ 验完：否决现成方案的理由必须是「查过的」，且必须留复查点**(09-28 用户追问「9/23 就让你搜，你也没找」→ 复查自己记录后发现：**我搜了**)
  真相：09-23 我确实全网搜过，找到 `workbuddy2api`(★1231，WorkBuddy 自动签到/任务) 与 `ZaiZaiCat-Checkin`(含 `script/workbuddy/`)，并写进调研报告「方案 B」；
  然后**用未经验证的风险判断当场否决**（"accessToken 等同账号控制权，泄露即被接管" —— 我**没读过那两个仓库一行代码**），
  且同一份报告里写着"若实施我会先对目标仓库做完整安全审计（凭证读写/外发请求/依赖树）"——**这个审计从没做**。
  此后 09-24~09-27 四天日志「开源/第三方/方案B」**零命中**，26KB 后续取证报告也零命中 → **一次否决 = 永久出局**，直到用户把方案递到手上。
  三步缺一不可：① **搜**（产品名+任务名）② **验**（否决前必须读过目标仓库的实际行为：动什么凭证 / 外发什么请求 / 依赖树 —— 不许用"我觉得有风险"替代）③ **留复查点**（被否决的方案进清单 + 写清"什么条件下重新评估"）
  两个技术误判（比"没搜"更值钱）：a) 我把"凭据是加密信封、密钥来源未公开"当成**此路不通**（判定"零 token 路径被否"），
  而正解是**不需要密钥 —— 复用客户端自己的运行时就地解密**；b) 收益算成"省掉点一下头像=极小"，**漏算"屏幕关着就断签"**（09-26 真断了）。
  ⚠️ 自查：我曾口头向用户承认"我根本没搜，一次都没搜"——**这句是错的**。我照用户的说法就下了结论，**没查自己的记录（记录就在磁盘上）**。→ **接受别人的判断（包括用户的）也要先核。**
  **缺这一步的代价 = 用户替我做研究。** 检索量级：搜 `workbuddy-auto-signin` 首条即中；搜 `WorkBuddy 自动签到 脚本 github` 至少 3 个独立实现，全部早于当日。

**── 证据 3 ──**
- 删/移文件须「先复制→验证→再删源」+ 删前用户确认
  - **例外（用户 2026-08-26 授权「全自动」）**：双副本/软链审计发现的**良性同名漂移副本**（仅 scripts/ ↔ .workbuddy/scripts/ 同名、已核实 0 活调用方、备份至 /tmp 后）可**全自动退役（验证→备份→删除，免用户确认）**。非此类（有调用方/数据层/跨项目/不确定）仍须删前确认。
  - **危害面核验须 grep 符号不是文件名(08-30 实锤)**: 搜 `import X` / `from X import` / `runpy` / `subprocess.*X.py`, 不搜文件名字符串——文件名在注释/审计文档/日志/git 历史里都会出现, 全是假阳性。文档里的 `file.py:NN` 行号引用**只证明这段文字提到过该位置, 不证明依赖关系**(实犯: 审计文档同一段同时出现两个文件名, 被误读为"删了会打断 3 个消费方")。import 冒烟须把**被测文件所在目录**(而非"我以为"的目录)加进 sys.path, 否则 ModuleNotFoundError 是测试假象不是真实故障。巡检发现"异常变更"先查是否有计划/授权在先, 再决定是否告警(否则是纯噪音误报)。

**── 证据 4 ──**
- 🔴 **并行 Bash 调用不可靠，且失败是静默的**(09-05 实犯):
  - **`~` 在并行 shell 里不展开**(HOME 未导出): `cd ~/xxx` 报 `no such file or directory` → cwd 回落到工作区 →
    相对路径被解析成 `/<工作区>/scripts/cli.mjs` 报 MODULE_NOT_FOUND。**自动化脚本一律写绝对路径, 禁用 `~`。**
  - **同一条 Bash 内并行发多个进程会静默失败**: 并行 4 个 Wind CLI 调用, 4 个输出文件**全 0 字节且 exit=0**
    (无任何 stderr); 改同一 shell 串行后 5/5 正常。**推翻「并行省墙钟」的旧印象。**
  - **硬纪律: 输出重定向到文件后必须校验字节数, 0 字节一律按"未执行"重跑, 不得据此写"无数据"结论。exit=0 ≠ 成功。**

**── 证据 5 ──**
- **Shell 内 `cd` 后再用绝对路径调脚本也可能静默空输出**: 某些 CLI(如 wind-mcp-skill 的 `scripts/cli.mjs`)
  按 `process.cwd()` 读配置, 必须先 `cd` 到脚本所在目录再用**相对路径**执行。

**── 证据 6 ──**
- 🔴 **zsh 下 `source xxx.sh | tail -N` 会让 source 落在子 shell，函数/变量全部丢失**(09-06 实犯):
  所有 L3 自动化都靠 `source $CLAW/.workbuddy/scripts/automation_preamble.sh` 注入 `run_l3_pre`/`run_l3_post`，
  一旦为"少刷屏"而接了管道，`type run_l3_pre` 为空、调用报 `command not found`(exit 127)，
  **且脚本自身仍打印"[preamble] 公共变量已加载"→极具迷惑性，看起来像加载成功了**。
  正解: **source 单独一行、不接任何管道/重定向**；要过滤输出就先 source，再用 `echo`/分命令各自加管道。

**── 证据 7 ──**
- **Sidecar=对话载体，绝对禁止kill**(memory_guard已硬护栏限renderer)

**── 证据 8 ──**
- 自动化调LLM必走本地代理:9999(preamble ensure_proxy自愈)；router直连deepseek必401

**── 证据 9 ──**
- 行情/历史K线**腾讯优先**(qt.gtimg/fqkline qfqday)，Wind仅降级

**── 证据 10 ──**
- 🔴 **数量骤降优先怀疑口径，而非康复；「条目数」≠「问题数」**(09-09 实犯): 巡检 stdout 打印 `len(alerts)`, 而多项检查把 N 个子问题**聚合进一条字符串**返回(`"自动化健康 10 项🔴: ..."`)→ 恒显示「1 项异常」而真实红数 10, 差一个量级。**run#117 据此写下「10🔴→1 项, 存量基本清退」并进长期记忆, 实际仍有 9🔴。** **虚假康复比虚假告警更贵**——它终止调查、写进记忆、被后续轮次沿用, 错误自我复制。凡「N→1」「10→0」断崖好转且**无对应修复动作/代码变更**者, 一律先回读原始正文再落笔。任何 `len(list)` 式健康度打印, 须确认 list 粒度==问题粒度。附带铁律: **只进日志文件、无 stdout 出口的告警正文等于没有**(同类缺陷在同一文件已复发两次)。

**── 证据 11 ──**
- 🔴 **`grep -c` 返回 0 时先验证模式本身能命中，再信"查无此物"**(09-02 实犯): 「没有」和「查法错了」输出完全相同。实犯: 用 `^2026-09-02 1[4-6]:` 查 `automation.log` 得 0 条→断言"派发中断", 实则该日志与 `extension-scheduler-diag.log`/`edge-sync.log` **全部用 ISO8601+Z(UTC)** 格式(`2026-09-02T06:55:02.123Z`), 换成 `^2026-09-02T0[6-9]` 立刻拿到 45 条。**取证前先取一行真实日志比对格式; UTC 小时 +8 = 本地小时。**
  - **工具层同源坑(09-06 实犯, 差点让整轮周度铁律升级空转)**: Grep/Glob 类工具**默认跳过以 `.` 开头的隐藏目录**, 搜 `**/.learnings/*.md` 恒返回 **0 条 No matches found**, 而实际有 68 处标记 —— 与"查法错了"完全同形, 极易被读成"本轮无候选"而静默结束。**查 `.learnings/` / `.workbuddy/` / 任何点号目录一律用 `bash grep -rn`/`find`, 不用带隐藏目录忽略的默认搜索。** 同理: 匹配模式可能有变体(`★升级候选` vs `★ 升级候选` 差一个空格), 声明"没有"前至少换一种写法复验。
  - **id 字段格式坑(09-05 实犯, 第 4 次栽在同一文件)**: 日志里 id 是 **`id=automation-1785982929477`**(带 `automation-` 前缀, **非纯数字**)。写正则 `run (start|finished): id=(\d+)` 匹配**恒为 0 条**, 极易被误读成"该自动化没派发"。正解: `grep -E "run (start|finished)" automation.log | grep "automation-<id>"`, 或用正则 `id=automation-(\d+)`。**抓事件一律按 `automation-<数字>` 全串匹配。**

**── 证据 12 ──**
- 🔴 **判自动化"是否派发"只认 `~/.workbuddy/logs/automation.log` 的 `run start:`/`run finished:` 事件对**(09-02 定案): 权威源优先级 = automation.log 事件对 **>** `automation_runs` DB status **>** 会话层锚(edge-sync `CREATE_ENTER`/conversation 数)。DB status 是"调度侧意图"快照, 可长期停在 QUEUED 而实际早已在跑/已饿死/已 CANCELLED; 会话创建数会被在飞运行长期占位而恒为 0, 据此判"中断"必然误报(09-02 下午档实犯, 险些第三次写错同一结论)。
  - **延伸(09-02 21:5x 实锤): 事件对的解读口径 —— `run start` ≠ 开始执行, 只是 session 创建/入队**。并发超发时 START 到 FINISH 的挂钟跨度可达 2~3h, 而实际执行只占最后 1~2min(实测统一巡检中枢: 14:33 START → 17:21 才真跑 80s → 17:24 FINISH)。故: ①**不能**因 START→FINISH 跨度大就判任务卡死/脚本故障, 那是在排队; ②**不能**因某整点档没有新 START 就判"漏派"——上一档未 FINISH 前调度器根本不派下一档, 墙钟档位"消失"是占位不派发。区分"排队中"与"真失联"要看 START 之后有无进展, 不是看档位。
  - **另一路径坑(09-02 实犯)**: 派发日志**不在** `~/.workbuddy/logs/execution/`(该目录不存在, 历次记录写错了), 就是 `~/.workbuddy/logs/automation.log`, 且时间戳为 ISO8601+Z **UTC**, 读时须 +8 换算成北京时间。

**── 证据 13 ──**
- 🔴 **WorkBuddy 调度器 `concurrency=3` 是装饰性的, 不执行限流**(09-02 巡检中枢 run#67 定案): 日志 `enqueue due ... concurrency limit active=N, concurrency=3` 后**必紧跟 `run start`**(37/37), 属超发→互相饿死→90min 硬超时 `[CANCELLED] Run timed out`。在飞峰值逐日攀升 08-29=1 → 09-01=8 → **09-02=19**; 单跑耗时暴涨是**并发争抢**非模型变慢(独占组 p50 全程 0.8–2.1min 稳定, 重叠组 10.3×)。**有效杠杆是降在飞条数, 不是换模型。** 现象层一天内可多次变脸(上午=QUEUED积压, 下午=会话创建归零+任务迟到3h)但真因同一, 遇新现象先回查已有定案文档。
  - **修正(09-02 run#70 实测): 「90min 硬超时」只是名义值, 不是墙钟上限**。把 `run start` 与 `[CANCELLED]` 按 id 配对, 09-02 全天 **26 条**超时的 start→cancel 跨度 = **121.5~323.7min(p50 238)**, 落在 90min 附近 **0/26**; 且随当日拥堵单调放大(09:12起121min → 16:30起324min → 夜间回落168min); 反例: 18:24 起一条跑 167min 仍 `success=true`。→ 90min 计的是「实际执行/无进展」时长, **排队等待不计入**。**据此因果补完: 被饿死的运行占着并发槽位 2~5 小时, 本身就是超发的正反馈一环**(不只是受害者), 这解释了触发量全天稳定 90~106 条仍会拥堵坍塌。**别再把"浪费 90min"当损失口径, 也别用墙钟跨度判超时/卡死。**另: 哨兵的锚点增量口径只能答"有无新增", 问"当日总量"必须另做全量统计(单轮报 7~8 条, 实际 26 条, 低估三倍)。

**── 证据 14 ──**
- 🔴 **在飞/间隔类统计探针必须先自检配对口径**(09-04 实犯): 从 automation.log 统计"在飞条数"时,
  **绝不能把 `run start` 与 `run finished` 按 `(id, 时间戳)` 配对** —— 两者的时间戳本就不同(start 是入队时刻、
  finish 是完成时刻), key 永不相交, 实测输出 **511 条假数**(真值 21 条)。
  正解 = 按 automation id 维护 open 队列(START 入、FINISH 出)。但该法**对历史残留未配对条目无免疫力**,
  会把它当成"最老的在飞"(实测中枢 89 START vs 87 FINISH 的 1 条历史残留, 被误报成"排队 598min")。
  → **硬纪律: 先 `grep -c "run start: id=X"` 与 `grep -c "run finished: id=X"` 做总量配对交叉验证,
  再逐条看明细; 总量差≠当前在飞时, 单条明细一律不可信。**

**── 证据 15 ──**
- 飞书推送卡片化(push_card.py)禁--text降级；改脚本先--dry-run

**── 证据 16 ──**
- **lark-cli 发消息默认身份=user 但缺 `im:message.send_as_user` scope(08-31实锤)**: 直接 `im +messages-send --chat-id` 必报 `missing_scope`；一律显式加 `--as bot`（bot 在目标群已可用）。发送用 `--msg-type interactive --content '<Card2.0 JSON>'`，判成功看 `ok == true`（不是 code==0），回读 `data.message_id`。
  - **延伸(09-02实锤): 发前必先 `im +chat-list --as bot` 核机器人成员资格**——`--as user` 与 `--as bot` 看到的群列表不同。外部群（`external: true` 且 `tenant_key` 与本租户不同，如「管大大's Feishu Assistant」）bot 不在群内，发送必报 `code 230002 Bot/User can NOT be out of the chat`；dry-run 只校验请求形状、**不校验成员资格**，会 `ok:true` 放你过去，必须真发才知道。
  - **兜底路径: `--user-id ou_本人openid --as bot` 发单聊给本人**（私有、不打扰群成员），已验证成功。`im +chat-list --as user` 返回的 `owner_id` 通常就是本人 open_id；也可用 `--as bot` 调 `+messages-send` 返回体里的 `data.chat_id` 拿单聊 chat_id 做回读校验。
  - `-q` 的 jq 表达式不支持 `data.items[] | {...}` 这类管道写法，会报 `function not defined: data/0`；直接用 grep 过滤输出即可。

**── 证据 17 ──**
- 🔴🔴 **诊断纪律(08-11固化, 屡犯): 任何LLM/代理/脚本故障, 必须先抓证据日志再下结论, 禁止脑补根因。** 第一动作=`tail /tmp/proxy-deepseek.stdout.log|stderr.log`(看`Thinking mode injected`/`track=points`/报错类型) + `nc -z 127.0.0.1 9999`；区分`连不上/reasoning-only(THINK_BUDGET注入致content空)/服务端internal error(垃圾token)`三类故障各对应不同修法, 不混谈；**没看到日志实锤前, 不得把"可能是X"的推断当结论抛给用户**。曾因脑补"路由到推理模型"错判辩论降级根因, 经用户两次追问才查日志发现真因=`THINK_BUDGET=high`注入thinking。**延伸(08-29实犯): 拿单样本对比基线同样属脑补——曾拿巡检中枢单样本94s vs hy4的213s断言"慢一倍", 查全时期分布(均值218s/p90=216s)后结论完全反转。凡对比性能, 必先算基线 p50/p90 分布再定性。**延伸(08-30): 基线分布必须按调度周期分层**——把 daily/hourly 任务的"最近运行距今"**混算** p50/p90 是无效基线(混算得 p50=185min), 会把 hourly 漏跑(123min)误判为"优于 p50"导致**漏报**; 正确做法: 按 `FREQ`+`INTERVAL` 分组只在同层内算分布, 跨层对比改用相对倍数(实际间隔÷自身周期), 分层后 **n<5 不得下异常结论**, 且优先用既有护栏阈值(如 180min)而非自造更紧阈值诱发误报。**延伸(09-01): 「间隔/周期」类指标出现**双向**异常(偏小或偏大)时, 先查"在飞进程"再定性——偏小=同一档被双次派发/双次写锚(实测1.3min), 偏大=上一档长耗时越过整点档被并发跳过(实测134.6min: 中枢run#58耗时68min 20:04→21:12越过21:0x档, 下一档顺延22:18); 两者都是调度artifact不是存活信号, 存活判定只看既有硬阈值(180min)。取证: `ps aux | grep -iE "workbuddy.*(automation|task)"` 看session启动时间, 并比对目标memory.md mtime vs 状态锚mtime(memory落后=在飞未落盘, 非漏跑)。**

- 🆕 **代理(9999)给不出 `logprobs` 真值(09-29 实测)**: `/v1/chat/completions` 带 `logprobs+top_logprobs` 时, 被选中 token 的 logprob=0、**其余候选全是 `-9999` 占位** → 拿不到概率分布(用 exp() 换算后会退化成 1.0/0.0 的**假分布**, 看着可用其实没数)。故「读候选 token 概率做选择」(固定答案打分/Jev 式) **在 9999 上做不了**; 本机可行通道 = ollama(`/v1/chat/completions` 给真值) 或 Apple MLX 直读 logits —— 见 skill `fixed-answer-scoring`。
**── 证据 18 ──**
- 🔴 **automation_update 改模型用 camelCase `modelId`(09-02实锤)**: 传 snake_case `model_id` 会返回 `success:true` 但**静默不生效**(DB 值不变), 已两次复现。改完必须回读 `SELECT model_id FROM automations WHERE id=...` 验证, 不能信 success。同理 `modelIsThinking` 走 camelCase。 **09-29 补齐(修 D9 知识库精读三槽时实测)**: `expertId`/`expertMarketplace` 同样走 camelCase —— 槽2/3 由 `deepseek-v4.1-flash`/无专家/无市场 → `hy3`/thinking/`EquityResearchExpert`/`official`, 回读三槽 4 字段完全一致(prompt/rrule/status 全保留)。**故 D9 旧记「automation_update 改不了 model_id/model_is_thinking/expert_id」是错的** —— 拆槽导致的配置重置可**一条 update 修回**, 不是无解的系统性副作用。 另记一条同族判据: **「界面里改好了」不等于改了** —— 复核要用「含 `-wal/-shm` 的快照回读 + 与旧备份逐行 diff」(本次实测 5 天 0 处变化: 用户以为改过, DB 其实没动; 且三槽行 updated_at 与我自己改 prompt 的时刻一一对应)。

**── 证据 19 ──**
- 🔴 **监控/取证/告警类任务不得跑在被观测对象上(08-29固化)**: 新建自动化若默认继承最新最强模型(如刚切换的 hy4-preview), 而该任务本身是用来观测/取证/告警这个模型的, 则被观测模型一旦限流排队, 取证任务自己先挂、保险丝失效。此类"哨兵"任务 model_id 一律显式设为最稳的模型(hy3)。同理适用于探针/看门狗/到期提醒。**延伸(09-02实锤, 时间窗版): 也不得跑在被观测时段之内**——一次性取证/复盘任务统计"某日"须等该日 24:00 后(排次日 00:30+)再跑; 盘中跑会把窗口截断成 62%, 漏掉午后尾峰, 把 1.94× 的劣化判成"擦线正常"(实犯: 8/31 15:30 跑取证→巡检中枢 hy4 p50 截断口径 205s 未越 p90 220.8s 判正常, 全日口径 386s 越线)。**假阴性比漏跑更危险, 因为它关掉后续所有复核。** 若必须在时段内跑, 报告须显式标注"窗口 00:00–HH:MM, 覆盖 X%, 结论仅对窗口有效"。配套两条: ①短周期任务(≤2h)判延迟异常**同时看 p50 与 p90**, p90 ≥ 2× 基线即判异常, 不等中位越线(小时级任务 p90 翻倍=调度降频); ②失败统计须做**同刻聚类**区分"模型故障"与"宿主中断", 中断类要算爆炸半径——单跑拉长→在飞重叠变大→一次宿主中断杀死 1→3 条, 即耗时劣化传导为失败率劣化。

**── 证据 20 ──**
- 🔴 **`source <preamble/shell脚本>` 不得接管道(09-03实犯)**: 写成 `source xxx.sh 2>&1 | tail -20` 会让 source 在**子shell**执行, 其定义的函数/变量随子shell退出全丢, 紧接着调 `run_l3_pre` 等函数必报 `command not found`(一度误判钩子脚本坏了)。一律写 `source xxx.sh >/dev/null 2>&1`(不看输出)或 `source xxx.sh 2>>log; cat log`。自检: `type run_l3_pre >/dev/null 2>&1 && echo hook-ready || echo hook-missing`, 通过再调函数。同源铁律: **报错先查调用形式本身, 别急着怀疑脚本/环境。**

**── 证据 21 ──**
- 🔴 **多层缓存必须按"单次成本升序"排列(09-03实锤): 内存 < 本地DB < 磁盘 < 网络。** 新增缓存层时先确认它插在成本序的正确位置——**插错位置比不加更隐蔽: 功能完全正确(缓存照写)、性能全丢、且不报错**(实犯: QTS 把"本地库优先"插在内存缓存之前, 13541 次调用每次真查库, 内存缓存只写不读; 修正顺序后 85s→12s 快 7×, DB 查询 13541→1231, 结果完全一致)。**唯一能抓到此类的测试形态是"命中次数断言"(`assert mock.call_count == 1`), 只断言"返回正确"抓不到。** 同源推论: 写完缓存/重试/降级类代码后, 回归测试必须覆盖"该层被跳过/未命中"的分支, 不能只测happy path。→ 再次发生 2026-09-27(QTS回测 data_fetcher: 缓存分层顺序插错位置, 内存缓存只写不读, 85s→12s 修复同形)

**── 证据 22 ──**
- 🔴 **写 mock 测试时的两个静默失效源(09-03实锤)**: ①**磁盘缓存泄漏**——被测函数若有 `.cache/xxx.json` 磁盘层, 只 patch `urlopen` 不够, 该代码+参数区间先前被真实跑过就会命中磁盘返回真数据, mock 根本不被调用(实犯: 断言 `len==1` 却拿到 67 条)。必须同时 `patch("...os.path.exists", return_value=False)`; 每一层缓存都要有 patch 或"证明其未被查询"的断言, 依赖"之前没人跑过"的测试不是确定性的。②**构造函数副作用吃掉 mock 队列**——类 `__init__` 自己查库会把有序 `side_effect` 列表消耗光, 被测方法调用时只剩 `StopIteration`, 而 `StopIteration` 的 `str()` 是**空字符串**, 若生产代码 `except Exception as e: log(f"...{e}")` 就得到**空错误消息**(最差的调试信号)。解法: 传参构造绕开构造期 I/O(如 `ReportService(stock_pool=[...])`)+ 用**按SQL内容分发**的函数式 side_effect 而非有序列表; 且须 patch 延迟 import 的**定义处**(`models.database.get_db_session`)而非使用处。**空异常消息 = 高度怀疑被吞掉的 StopIteration, 不是生产代码坏了。**

**── 证据 23 ──**
- 🔴 **静态快照类数据源必须有"刷新脚本+过期告警+备份"三件套(09-03实锤)**: `shared/astock_code_name.json`(5528条股票名称, ST识别的唯一名称源)自 07-17 生成后无任何刷新机制, 7周后**双向失真**——漏网 5 只新戴帽 ST + 误杀 12 只已摘帽(000711 ST京蓝→京蓝科技)。**最危险的是它不报错**: 名称查得到、过滤照跑、日志照写"已排ST", 只是结果全错。铁律: ①任何快照数据必须有刷新脚本(失败保留旧值、原子写、完整性守卫不得少键); ②加载时判 mtime, 超阈值告警(不抛异常——过期影响准确性而非可用性); ③**用名称/标签做规则判断时, 数据源时效性=规则正确性**, 这不是"数据更新"是**正确性依赖**。相关: 腾讯取数域名选择——`qt.gtimg.cn`(批量行情/名称)**无频控**, 而 `ifzq.gtimg.cn`/`web.ifzq.gtimg.cn`(K线)**有WAF频控**(约2000次后501), 批量任务选前者。→ 再次发生 2026-09-27(QTS回测: 名称快照 07-17 后无刷新静默失真 + K线域名 ifzq/web.ifzq 有WAF频控, qt.gtimg 无频控)

**── 证据 24 ──**
- 🔴 **验证 `trap EXIT` 清理必须另起一个 shell 调用(09-03实犯)**: Bash 工具**每个调用是独立 shell**, `trap "rm -f L" EXIT` 注册在当前 shell, **只在该调用结束、shell 退出时才触发**——在同一条命令里 `touch L && trap ... && cmd; ls L` 必然看到文件还在, 据此判"🔴 lock 残留"是**误报**(实犯一次, 差点报故障)。已排除的错误假设: 管道(`| grep`)不是原因——实测子shell/管道/无管道四种组合均如此。同理适用于 atexit、长驻进程里的 finally 等"依赖进程退出才生效"的机制。**验证前先问: 这个动作在什么时候才发生?**

**── 证据 25 ──**
- 🔴🔴 **经验闭环(08-11固化, 用户要求"同类不反复犯"): 处置任何告警/故障后, 必走 incident-triage skill 标准SOP → 写对应项目 `.learnings/`(去重, 带`★升级候选`标记) → 周度自动化 auto-promote-learnings(1786439069962, 每周日22:00托管QTS)自动扫描升级为🔴铁律+skill反模式。** 八项目(Claw/QTS/StockInsight/engineering-audit-kit/marvis_bridge/project-monitor-fusion/wechat_download-api/wechat_api)统一走此机制, 共享铁律在本文🔴段。处置完不写.learnings=没吸取教训。

**── 证据 26 ──**
- 🔴 **单链路日志≠全链路, 禁脑补归因(08-12固化, ≥3次复犯: 08-12/08-14 WB历史对话404 + 08-13 Marvis误归因)**: 故障排查须看**数据链路完整日志**再定性, 不只单守护日志。WorkBuddy UI历史对话消失=云端 `GET /console/as/conversation-sync/conversations` 持续404(本地 `projects/**/*.jsonl` 全文完好, 兜底 `~/.local/bin/wb_history_server.py`:8791); "会话未拉起"类失败优先查外部重启方(Marvis/launchd 的 graceful_restart 日志)而非内存守护; watchdog/巡检归因文案须**读日志实锤**, 不得硬编码"元凶=某守护"(与现状相悖即误导)。**延伸(08-30): 先分清"全量运行日志" vs "条件触发型日志"**——告警日志/错误日志/去重后告警只在产出 alert 时追加, 用它的空档反推"没运行"是**逻辑硬错误**(实犯: `unified_self_heal_log.json` 今日 12 条全为同因告警, 11 点档无条目被差点断为漏跑, 实为 silent_green); 判"是否漏跑"要找**无条件写入**的锚(状态锚 ts / 心跳文件 mtime / 运行计数器), 文件名含 `log` 不等于全量日志。另: **"间隔异常"类判断须先查是否有未记账运行**(实犯: 16:53→19:11 判"连漏两档", 实为中间 18:07 有一次未记账运行, 实际间隔 73.5/64min 正常)。

**── 证据 27 ──**
- 🔴 **双自动化并发操作同一目标须互斥(08-12固化)**: 两自动化并发改同一文件/launchd无协调 → 拉锯/打断致命(巡检bump的sed打断memwatch重启致WB停机5h11m)。单一配置源(参数进plist EnvironmentVariables, 脚本只读逻辑); 写前查2min内目标是否正在重启(护栏防打断); 调参先看目标守护日志实锤; 任何自动化**绝不用 pkill -f 模糊匹配**(防杀sidecar)。

**── 证据 28 ──**
- 🔴 **容器/服务重启须连带重建 daemon 调度器(08-13固化)**: 外部重启(强杀主进程)若只换主进程不换 `daemon-app-server` → 孤儿 daemon(stdio断)致自动化持续"Run did not create a session within 60000ms"无法自愈; 重启本身非致命, **孤儿 daemon 阻断调度**才是。graceful_restart/看门狗须 `wb_killable_procs` 含 `daemon-app-server-entry`(保留 sidecar), 外部重启前自检(树>8500MB或可用<512MB)否则拒绝 → 再次发生 2026-08-18(统一巡检中枢整窗失联4.8h, 同根因二次: orchestrator 重启后中枢专用调度档连续丢档, 须固化"超阈值自动直跑兜底"而非仅靠外部 watchdog 告警)。

**── 证据 29 ──**
- 🔴 **项目脚本目录禁与 stdlib 同名模块(08-14固化)**: `scripts/secrets.py` 与 stdlib `secrets` 同名 → numpy.random `import secrets` 解析到项目文件 → `ImportError: cannot import name randbits`(脚本跑必挂, 单独import过)。新增脚本前 `python -c "import <name>; print(__file__)"` 自查; numpy类ImportError优先怀疑 sys.path 遮蔽非numpy本体; 建议CI grep脚本目录与stdlib同名.py。

**── 证据 30 ──**
- 🔴 **`source xxx.sh | 管道` 会在子shell执行，函数不进父shell(09-02实锤)**: 自动化里写 `source preamble.sh | tail -N` → 后面调 `run_l3_pre` 报 `command not found`(EXIT=127)，护栏被静默跳过。一律 `source xxx.sh > /tmp/x.log 2>&1`，需要看输出再 `cat`。同类：`(source ...)` / `cmd | while read` 都在子shell。

**── 证据 31 ──**
- 🔴 **A股股数必须整手(08-14固化)**: 任何"股数"输出(T仓/买卖量/补仓量/止盈)须 `int(round(x/100))*100` 且≥100, 统一复用 `LOT_SIZE=100` 常量, **禁裸 `round(金额/价)`**(长电30股/华天40股无法成交)。交易执行(cmd_buy)须 fail-closed 拒绝非整手; 调 `//LOT_SIZE*LOT_SIZE` 取整; 全仓卖出保留零股尾仓放行。

**── 证据 32 ──**
- 🔴 **日志成功≠数据落库, 凡写库须 readback(08-13固化)**: contextmanager 资源释放隐式 rollback 是最易误报成功的坑——`get_db_session()` 不自动commit, 调用方漏 `db.commit()` → INSERT 在 session close 回滚(日志"已落库"但表空)。写库路径首跑必回读验证(查表/查PG); code review 逐调用方核对 commit; 新路径首跑前确认无"手动补录"污染基线。**readback 的路径准确性是 readback 有效性的前提(08-30 再次发生: 按错误 key 层级回读 → 误判"状态锚未写入"), 回读前必答"回读三问", 详见🔴段同名条目。**

**── 证据 33 ──**
- 🔴 **容器内定时器(APScheduler)必须单 worker(08-15固化)**: `uvicorn --workers N` + lifespan注册调度器 → N个worker各注册一遍 → 定时任务重复触发(回测日报/周报每日双推)。容器内调度器须 workers=1 或独立进程; Dockerfile 改 workers 后必须 `--build` 重建并 `docker inspect .Config.Cmd` 验证生效; compose 带 `profiles` 的 `up` 须显式 `--profile`(否则报 no such service)。

**── 证据 34 ──**
- 🔴 **第三方 GitHub Action 浮动 tag 会静默弄红 CI(08-12固化)**: `@v2` 被repoint到强制license的新版 → quality-gate 红灯; 关键CI步骤优先用 **commit SHA 或 Docker直调开源引擎**(如 `zricethezav/gitleaks:latest detect`) 避 action 包装器 license/API 依赖; 巡检 dedup 不能只按"CI是否红", 须按 run/根因去重, 否则掩盖新红灯。

**── 证据 35 ──**
- 🔴 **Laravel 迁移禁共享时间戳+跨表外键(08-11固化)**: 两迁移同时间戳(如 `2026_06_14_144729`)→ scandir 顺序不确定 → tasks 内联 `->constrained()` 偶发在 projects 建表前执行 → `relation does not exist` flaky CI; 外键一律放依赖表建好后的独立迁移(恒最后时间戳)。

**── 证据 36 ──**
- 🔴 **策略回测须过带成本全样本+随机对照(08-14固化)**: 轻量/单样本回测通过≠策略级通过, 上线前须 edge≥+5pp 且 Sharpe 占优 + 随机同频次隔离验证; 不为让扫描"看起来有用"注入伪信号维度, 零产出是真实市场结构应如实报🔴。

**── 证据 37 ──**
- 🔴 **板块强弱判断禁单日涨跌幅(08-14固化)**: 板块强弱不能用单日涨跌幅定, 早期转折往往是布局窗口; 止损须感知板块级事件; 误用单日涨跌会错判强弱与买点。

**── 证据 38 ──**
- 🔴 **自动化 refusal/失败集群须先按 code+reset 时间戳聚类定因(08-20 实锤)**: `thread_title` 含 "refusal" ≠ 内容安全拒绝, 可能含 HTTP 429 配额/频率限制(`code:-32003`/`Quota exceeded: 429`); 多个互不相干自动化**同享一个 reset 时间戳**同时失败 = 单一路由当日配额耗尽(系统性), 非任一自动化内容触发; 诊断须取完整 code/message 聚类, 不得凭 "refusal" 臆断为内容策略; 配额耗尽优先推飞书提示切模型/查路由(关联: DeepSeek 直连余额枯竭/路由切换长期未落地)。**再次发生 2026-08-24(第二族)**: refusal/失败须按 code 至少分**三族**——`-32003`=429 配额(等 reset)、`-32603`+`500 internal server error`=**上游服务端瞬时故障**(实锤窗口 16:22–16:30 约 8min, 自愈)、内容策略拒绝(罕见, 须单任务孤立才成立), 禁字面归因; 判上游 vs 本地先看 `nc -z 127.0.0.1 9999` + tail proxy stdout/stderr(代理无错 + `track=points` 计费正常 ⇒ 责任在上游, 别改本地配置); 确认恢复须**主动 curl 探测** `POST 127.0.0.1:9999/v1/chat/completions` 看 HTTP 码, 不能只等下轮自动化运行结果; **"补跑/校验类"自动化自身失败 = 双重故障**(它本身就是漏报检查员, 挂了就没人核对当日产物), 须人工代跑其检查项确认无真实遗漏, 并检查 `claw_lock_*` schedule 锁是否已被占用(锁已占会掩盖补跑机会)。

**── 证据 39 ──**
- 🔴 **自动化模型配置在 workbuddy.db，不搜"混元"(08-29 实锤踩坑)**: 51 个自动化的模型存在 `~/.workbuddy/workbuddy.db` 的 `automations.model_id` 字段，值形如 `hy3`/`hy4-preview`（腾讯混元在 WorkBuddy 的 id 是 `hy*`，**不是** "hunyuan"/"混元"）；用中文名或 hunyuan 全盘 grep 永远搜不到，会误判"没有在用"。查/改口径：只读查询 `sqlite3 file:~/.workbuddy/workbuddy.db?mode=ro` 的 `automations` 表（禁写，写入一律走 automation_update 工具）；改模型 = `automation_update(mode='update', id=..., modelId='xxx')`（modelId 是未公开但合法字段，只传 id+modelId，其它字段保留），改完必须读库 readback 验证。新模型 id 上线前先用一次性探针自动化（trivial prompt，几分钟后跑）实测跑通再批量改，避免 50+ 自动化集体跑挂。当前（08-29）51 个已切 `hy4-preview`（WorkBuddy 限时免费至 2026-09-10 23:59，每日有额度上限、触顶扣积分/排队)；**8 个** deepseek-v4-flash（原先统计为 9，含一条僵尸任务，08-30 已删）+ 2 个 deepseek-v4-pro 未动；另 2 个 hy3 哨兵。**🔴 自动化管理面假成功(08-24 实锤): `automation_update` 传**不带 `automation-` 前缀的裸数字 id**时平台**不报错, 而是静默新建一条影子记录**并把 status 变更写进影子, 真实调度记录完全没被触碰(实犯: PAUSE 两次均返回 `success:true / status:PAUSED`, 真实记录仍 ACTIVE 按 HOURLY 跑到 17:29, DB 出现同名双记录)**。铁律: ①id 一律带 `automation-` 前缀(读写同规则); ②任何 status/rrule/model 变更后**必 readback DB** `SELECT id,status,updated_at FROM automations WHERE id='automation-<x>'` 才算成功; ③**校验工具返回的 `cwds` 等字段是否与目标记录吻合**——不吻合(如返回临时目录 `automation-2026-08-24-13-36-53`)即操作对象错位; `mode=view` 报 not found 而 `mode=update` 却"成功"是危险信号; ④按 `name LIKE` 查询可立刻暴露同名双记录; ⑤影子记录须用工具 delete。**另: 对该类管理面操作, `success:true` 不等于生效。**，迁移到 hy4 省钱动机不成立（占总量 ≈1.4%）；且 hy4 无视觉能力，涉图任务会被平台静默切模型并按正常积分计费。**

**── 证据 40 ──**
- 🔴 **僵尸一次性自动化必须定期清理(08-30 固化)**: `schedule_type='once'` 的计划时间已过期 + `automation_runs` 0 次执行 + `status='ACTIVE'` = 僵尸；它不会自己消失，哪天调度器补跑就会**突然执行一个早已过期的任务**（如验证 8/13 打通的脚本在 8/30 跑）。删除走 automation_update 工具、readback 查 `deleted_at` 置位。扫法：`SELECT a.id,a.name,a.status,a.scheduled_at,(SELECT COUNT(*) FROM automation_runs r WHERE r.automation_id=a.id) FROM automations a WHERE a.deleted_at IS NULL AND a.schedule_type='once'`。⚠️ 坑：**`scheduled_at` 混合格式**——老记录毫秒时间戳字符串、新建的是 ISO `2026-08-31T15:30`，直接 `int()` 会 ValueError，须双路解析。

**── 证据 41 ──**
- 🔴 **hy4-preview 无视觉能力，涉图任务禁挂 hy4(08-30 官方+探针双实锤)**: 官方口径"Hy4 属语言大模型，不具备原生多模态能力，执行图片相关任务时**平台会自动切换其他模型，按正常积分规则计费**"；自建探针（hy4-preview + Read 一张 PNG）输出 `VISUAL_OK` 且内容准确 → 实锤平台有视觉兜底切换。→ **涉 OCR/读图任务挂 hy4 = 不免费 + 切到哪个模型不可控 + 质量不可预测**。换模型前必查 prompt 是否含 OCR/视觉/图片/Read 图；对已切批次也要反向排查（08-30 查过 51 条，仅 2 条提及图片且都明确不 OCR，安全）。另：hy4 有 overthink/over-verify 倾向，与"多轮辩论/多重校验"型 prompt（如午间选股的四大师校验）叠加会显著拉长耗时，此类任务迁移前须先估窗口。

**── 证据 42 ──**
- 🔴 **项目路径落外置SSD/符号链接须防静默失败(08-17 实锤)**: Claw/StockInsight 实际路径在 `/Volumes/ZHITAI/WorkBuddy/...`(经 `/Users/guan/WorkBuddy/...` 软链), macOS 外置卷未挂载时符号链接解析失败 → 硬编码绝对路径的自动化报"文件不存在"静默失败/监控盲区; 自动化须用 `realpath`/直写真实挂载路径 + 入口 `mount|grep zhitai` 自检(盘未挂载显式告警而非静默); 诊断"文件不存在"须先 `git ls-files` + `readlink` 确认是真实删除还是挂载/符号链接时序, 禁一见缺失就当源码丢失去重建。

**── 证据 43 ──**
- 🔴 **数据层/HTTP 调用禁止静默吞非 200 响应(08-19 实锤)**: `data.get("x",[])`/`return []` 类对非 200 的静默兜底会掩盖真因(如 RSS/API `HTTP 401 无效的认证凭证` 被吞成空列表 → 误报"未找到订阅"), 致故障被掩盖数天; 凡 HTTP/数据层函数遇非 200 必须打印状态码+响应体或显式抛错, 不得静默返回默认值; 诊断外部 API 故障先直连 curl 看状态码再查本地凭证, 禁只看上游脚本报错文案。
  - **再次发生 2026-09-01/09-02(第 3/4 次, 跨 QTS+Claw)**: 吞异常已从「非 200 静默兜底」扩散到两型新变体——①**框架吞**: job 函数 `except Exception: logger.warning; return False`, APScheduler 只看是否正常返回 → 日志打 `executed successfully` 而 16 条 SQL 错 5 条; ②**巡检吞**: `check_*` 的 except 分支返 `"ok": True`, 4 个死检查里 3 个如此。统一判据: **异常分支一律 fail-safe 返不通过(或显式计 skip), 禁止返绿**; 验收看实际产出行数/文件 mtime, 不看框架日志措辞。

**── 证据 44 ──**
- 🔴 **CI 红排查须先验"时间相关 flaky"(08-20 实锤)**: 测试依赖 `date.today`/月份/交易时段/节假日等随运行时刻变化的输入(如 `_is_sprint_period` 判定 `day>=20`)→ 产生月度/周期 flaky 误红, 易被误判为代码回归; 含运行时模式判定的测试必须 `patch` 固定(patch `_is_sprint_period`/`date.today`/月份分支), CI 红灯排查 checklist 须含"时间相关 flaky"先验项(先固定时刻重跑验证, 再归因代码)。

**── 证据 45 ──**
- 🔴 **AI 功能"降级"须显式区分 LLM 失败 vs 数据不足(08-21 实锤)**: 数据缺口(源不可用/配额耗尽)与模型失败(真降级)表现相似(都输出 HOLD/观望), 但成因与处置相反——数据不足非模型问题, 须标注 `data_insufficient`/提示修数据源, 不得据此误报"模型降级"或强判; AI 数据链路不得依赖易耗尽配额(如 Wind), 技术面本地化/基本面多源兜底(零配额依赖), 结果须存 `data` 快照以便复盘区分真降级 vs 数据缺失。

**── 证据 46 ──**
- 🔴 **校验/占位符/安全检测必须下沉到被复用的内层函数(08-21 实锤)**: 防御逻辑(如 push_card 占位符检测)若只挂在 CLI 主入口, `import send()` 绕过主路径即失效 → 字面占位符原样推送; 凡校验/占位符/安全检测须下沉到 `build_card` 等被所有调用方共享的内层, 不依赖调用方走特定入口; 数据入口须接受上游可能带后缀的标识(`.SH`/`.SZ` 等), 禁硬编码无后缀匹配致 price=0 静默空跑。

**── 证据 47 ──**
- 🔴 **长耗时扫描/批处理/异步任务须硬性超时+孤儿进程检测+重跑(08-23 实锤)**: 异步 K 线/抓取 future/task 未设硬超时(`asyncio.wait_for`)→ 全源失败时主线程死锁静默 hang(600s 超时零产出, DB 实查 0 行), 属代码健壮性缺陷非单纯上游抖动; 每单元抓取须硬超时, 全源/上游失败须跳过该单元或回退缓存而非阻塞整轮, 扫描级 watchdog 无进度 N 秒须干净中止+部分落盘; 死锁排除: 读 /proc 精确 cmdline kill 孤儿进程(禁 `pkill -f` 误杀 sidecar), 重跑仍失败按真异常告警。**再次发生 2026-09-01(QTS, 第 3 场景)**: 缺**交易时段守卫** —— interval 型作业天然没有"该不该跑"的概念, 24×7 空跑(非交易日/夜间也全量拉数), 既烧配额又放大超时; 须在**任何数据源调用之前**加 `is_trading_day()/is_trading_hours()` 短路, cron 补 `day_of_week="mon-fri"`, 判定口径收进单一真源(`shared/trading_calendar.py`)。**再次发生 2026-08-24(StockInsight 周日扫描, 同源不同场景)**: ①**非交易日/节假日源离线会放大超时**——周日 5 个 K 线源全熔断 × **无单源硬超时** × 外层 600s `timeout` → exit 124 硬 hang + 误报告警; 根治 = 每源 `PER_SOURCE_TIMEOUT=8s` 进程级超时池(⚠️ **`max_workers` 必须 >1**: 初版 `max_workers=1` 导致超时源后台线程占满单 worker, 后续源被串行化, 实测 20s 而非 8s) + 入口 `is_trading_day()` 短路(优先查 `stock_trade_calendar` 表, 表缺失/越界 fallback 内置休市 + `weekday()<5`, **保守设计: 宁可少跳不误跳, 避免交易日被静默漏扫**)。②**部署须确认代码是否在镜像层**——StockInsight MEMORY 记 `.:/app:ro` bind mount 实时可见, 而本次实犯却需 `docker cp` 才生效; 冲突时以 `docker inspect <svc> --format '{{.Mounts}}'` 实测为准, 不凭记忆下结论。

**── 证据 48 ──**
- 🔴 **检测/守护逻辑"静默失效"三坑(08-30 实锤, Claw 统一巡检中枢)**: 无异常、无告警、输出恒为"正常值" ≠ 检测健康。①**扫日志必须合并 stdout+stderr**——`docker logs` 按流分流(容器业务日志多在 stderr), `subprocess.run(capture_output=True)` 只遍历 `r.stdout` 会让检测从建成起恒返回 0(实测 stdout 25807 行含 0 条业务标记, stderr 2101 行含 358 条); 正确写法 `stderr=subprocess.STDOUT` 或手动拼两流。②**"总数 0 / 无需清理"必须先反证再采信**——清理/巡检/对账脚本输出 0 命中时, 先手工 `ls`/查库确认是真 0 还是匹配器错(实犯: `BACKUP_PREFIX="workbuddy.db.bak-"` 连字符 vs 实际命名点号 `workbuddy.db.bak.<ts>` → glob 恒空长期静默 no-op)。③**按条数裁剪的审计窗口会被单一噪声源占满**——`data[-200:]` 式滚动上限遇高频同质告警(单个不可自愈项占 183/185=98.9%)约 12 天即挤出全部真实记录, 须按 action 分档保留或分流存储, 且已标注"不可自愈"的项应降频记录。通则: 对"输出正常值"的检测要**主动造正样本验证链路通**, 不能靠"长期没报过"默认它健康。④**「从未被执行过」的路径返回 0, 与「执行了且没问题」完全同形**(09-06 补): 中枢审计里 4 个 Runbook 的 `execute` 动作**恒为 0**, 实为从未触发过, 不是"无故障"。沿用三步取证: 看 action 分布 → 查 `.runbook_fuse.json` 是否熔断 → 回读 `.bak` 历史判断是否"从来如此"。**只看当周数字必得"没故障"的错误结论**; 根治 = 给 Runbook 各做一次 `--dry-run` 演练, 把"未验证"变成"已验证"。→ 再次发生 2026-09-27(QTS回测: 日志假称"已排ST"而 stock_basic 缺失致 ST 未过滤, 排查被先入为主误导)

**── 证据 49 ──**
- 🔴 **告警价值 = 症状准 × 药方对, 频率须匹配可处置性(08-30 实锤)**: ①**处置建议必须实证验证, 禁"症状→动作"直接映射**——实犯 `isExpired=true → "需扫码重登"` 是未验证的隐含假设, 实为抓取 07-20 停摆、登录 08-23 才过期(**过期是结果不是原因, 因果倒置**), 连续 13 轮推送无效药方, 比漏报更消耗信任; 出 remediation 前必做**时序对齐**(故障起始时点 vs 症状出现时点, 症状晚于故障即非根因)并跨源比对时间戳。②**去重 TTL 须按可处置性分级**——可自愈类(容器 exited/阈值漂移/CI 红)短 TTL 催修, **纯人工处置类**(扫码重登)长 TTL(72h)提醒不轰炸; 统一 24h 会让无自愈路径的告警日复一日挤占告警位形成疲劳。③**配额/日限/熔断类日志须进程内去重**(once flag + 跨周期重置), 禁逐股/逐条裸 warning(实犯: Wind 日限刷屏 40+ 行/天 × 25 天)。附: 注释/docstring 里带具体数值的"实证"结论**会腐烂**(原写"早停 23 天"实算 33 天), 改动相邻逻辑时必须重算同步, 否则后人(含 AI)拿错误数字继续推理。
  - **再次发生 2026-08-31/09-01/09-02(去重键专题, Claw+QTS)**: 去重/缓存/指纹的键必须是**稳定身份**, 不能是呈现文本或含易变数字 —— ①「优化告警文案」这一个善意动作会静默重置 TTL 窗口让降频失效(08-31: 同一根因冒出 4 个去重键); ②新增检查项最易踩, 因为新检查为了可诊断性往往把计数写进文案(09-01)。**量级要与身份分通道**: 身份用于去重、量级做增量判据用于升级; 每次给告警加去重/降频, 都反向问一句「这会让我看不见什么」——去重压掉的是重复不是变化。→ 再次发生 2026-09-27(QTS回测 WF 判读: 二元门 `wf_passed>0` 误判"策略有效", 改比率门+方向门)

**── 证据 50 ──**
- 🔴 **readback 前先答"回读三问", 读错的 readback 比不读更致命(08-30 实锤)**: ①**文件在哪?**——grep 写入方时连 `Xxx_PATH =` 常量一起 grep 定绝对路径(实犯: 按直觉去项目仓读状态锚 → FileNotFoundError, 实际写入方硬编码在 `~/.workbuddy/` 全局区, 不在任何仓内)。②**key 在哪层?**——按写入方 setdefault 链逐层对齐, 禁凭字段名猜嵌套(实犯: `d["monitoring"]["unified_ops_center"]` 取到 `{}` 误判"状态锚未写入", 实际多一层 `["global"]`)。③**判据会不会误伤正常值?**——写异常检测前先拿一个已知正常样本跑判据(正向样例自检); 实犯: 用 `"@" in k` 查 key 污染, 而合法 key 格式就是 `通道@细节` → 把唯一合法 key 报成非法, 真判据须 `re.search(r'@\d{6,}', k)`。补充: 旁证字段须先确认因果(用 X 佐证 Y 前, 先确认 X 会被写 Y 的同一段代码更新), 否则"陈旧时间戳"类旁证会把错误结论钉死; **"发现缺陷"方向的结论怀疑阈值翻倍**, 报缺陷前换一条独立路径读同一数据自证。接口回读前先 `print(json.dumps(d)[:300])` 看真实结构(如 `data.data` 双层、`expireTime` 是 ms 级 int 非 ISO 串)。

**── 证据 51 ──**
- 🔴 **stale/静默失败判定: `next_run_at` 未来即健康, gap 阈值须按频率+BYDAY 分级(08-24 实锤, 每周一必复发)**: `automation_health.py` 对 `FREQ=HOURLY` 用固定 48h 阈值、未识别 `BYDAY=MO-FR` → 周五 23:29→周一 00:28 的 ~49h 周末自然间隔被判 🔴 critical 误推飞书。规则: ①调度器算出的 `next_run_at` 是"是否已正确排期"的**权威证据**, 在未来即跳过 stale 判定(兼覆盖法定节假日/低频任务); ②gap 阈值按 MONTHLY/WEEKLY/HOURLY/BYDAY/once 分级, 仅工作日任务周五→周一至少放宽到 72h, **禁单一固定值**; ③误推的 critical 必须补发 success 纠正卡片, 不在群里留误导信息。

**── 证据 52 ──**
- 🔴 **验证"读起来像查询、实际会写盘"的函数须做三件事(08-30 实锤)**: 适用于 `is_alert_duplicated` / `mark_xxx` / `ensure_xxx` / `get_or_create` 类。①**先读签名再调用**——`inspect.signature(fn)` 或读源码, 禁靠函数名猜参数(实犯: 调 `is_alert_duplicated(key, 72)` 以为第二参是 TTL, 实为 `reason_key`)。②**状态隔离**——把模块级状态路径常量(如 `m.ALERT_DEDUP_STATE`)monkeypatch 到 `tempfile.mkdtemp()` 下的临时文件, **禁直接在真实状态文件上跑验证**(实犯: 污染 `.ops_alerted.json`, 写入非法 key `...@72`)。③**返回值自证**——探针返回值须对照期望断言, 不一致即停(返回 False 而期望 True 本应立刻暴露参数错位)。通则: 验证脚本一律走 `monkeypatch 状态路径 + 临时目录`, 生产状态文件动前先备份。

**── 证据 53 ──**
- 🔴 **MCP 工具"找不到"先查 `~/.workbuddy/mcp.json` 的 `disabled` 标记(08-30 实锤)**: ToolSearch 精确名与关键词搜索均返回 "No matching tools found" 时, **先查配置是否被禁用, 不要先怀疑 Key 失效/网络故障**(实犯: 5 个 wind server 全 `disabled:true` → 工具根本没注册进会话, Key 与后端都正常)。若 disabled: 优先找该厂商 skill 自带的 **CLI 兜底通道**(如 `cd ~/.workbuddy/skills/wind-mcp-skill && node scripts/cli.mjs call stock_data <tool> '<params_json>'`; 返回体在 `content[0].text` 需再解一层 JSON 字符串, 失败为 `{ok:false,code,message}` 信封)。取多标的同类指标前先查契约是否支持**批量参数**(windcode 支持英文逗号单次 ≤50 只), 禁逐只调用浪费每日免费积分。

**── 证据 54 ──**
- 🔴 **框架级「成功」信号 ≠ 真实产出; 巡检/调度代码的 `except` 必须 fail-safe 返不通过(09-06 升级; Claw 08-31/09-01×2 + QTS 09-01/09-02 共 5 次复现)**: ①APScheduler 只看 job 函数是否正常返回 → `except Exception: logger.warning; return False` 后日志打 `executed successfully`, 实际 16 条 SQL 错 5 条; ②巡检 4 个"死检查"中 3 个 except 分支返 `"ok": True`, 检查从建成起恒绿且不可证伪; ③provider 吞异常返空 → 4878 次限流错误全被降级成"空结果", 表现为"数据就是没有"。**还有一类自指检查必然自证**: 任何"系统是否活着"的检查若把自身计入证据(今日锁数含自身锁)就永远为真, 必须排除自身。→ 防复犯: 异常分支一律返不通过或显式计 skip; `passed` 键**缺失算不通过**(`c.get("passed") is True`, 禁 `c.get("passed", True)`); 恒返 ok 的"观测项"要从 ✅ 计数里剥离; 验收看产出行数/文件 mtime 而非框架措辞; 反向验证(把 bug 改回去看测试挂不挂)是唯一能证明"测试有效"的方法。另 10-04 补: Claw `is_trading_day.load_holidays()` 在日历文件缺失/JSON 坏时直接 `sys.exit(2)`, 而 SystemExit 继承 BaseException 非 Exception → 调用侧 `except Exception` 接不住 → 整个中枢进程被带走(本机有该 gitignored 文件故 4 周不暴露); 凡库函数 `sys.exit` 须在调用侧用 `except (Exception, SystemExit)` 或前置存在性校验, 降级路径要问"上游最可能的失败是 Exception 还是 SystemExit"。

**── 证据 55 ──**
- 🔴 **同一语义的值必须单一真源; 「已配置」≠「被读取」(09-06 升级; Claw 08-31 + QTS 09-01/09-02)**: QTS 服务地址散在 **6 处取值点 / 4 种解析方式**, 配置写了三处**无人读取**, 改配置永不生效; Claw 去重键的截断/归一化分散多处 → "看起来写了归一化、实际没生效"。→ 防复犯: ①"改配置不生效"**先 grep 读取点**, 别怀疑注入链路/环境变量; ②默认值注册表与运行时解析分离; ③验收标准 = 「grep 到唯一读取点 + 回读生效值」, 不是"配置写进去了"; ④同一常量/时区/地址出现 ≥2 份实现即抽 `shared/` 单一真源; ⑤**改调度/阈值后须三处同查: rrule(automation view) + prompt 文案 + 脚本常量**, 缺一即幽灵配置。

**── 证据 56 ──**
- 🔴 **聚合值稳定 ≠ 状态稳定: MAX/COUNT/"持平"会抹平组成变化、截断写入与爆炸半径(09-06 升级; Claw 08-31/09-01/09-04/09-06 + QTS 09-02/09-04 共 6 次)**: ①`.workbuddy/scripts/ 未提交 4 项, 与上一轮持平` 连续 12 轮判"无新增", 实为旧项出列新项入列, 两个已修复未入库的改动被漏掉; ②`MAX(trade_date)` 达标掩盖了每日只写入一半标的的**截断**; ③聚合告警串里 1 条文字代表 30 倍爆炸半径。→ 防复犯: 聚合判据**必须落到逐元素/精确时间线** —— 列文件名而非计数、"最新交易日行数 vs 池内只数"硬比对而非 MAX、告警按 `by_category` 展开(alerts 条数 ≠ 受影响自动化条数)。**"与上一轮持平"类结论至少展开一次明细再采信。→ 再次发生 2026-09-27(QTS回测: MAX(trade_date) 达标掩盖每日只写一半标的的截断, 须"记录数≥1000 的末交易日"基准)**

**── 证据 57 ──**
- 🔴 **容器 TZ=UTC + naive `datetime.now()` = 每天 00:00–08:00 落库日期系统性错位一天(09-06 升级; Claw 08-31/09-01 + QTS 09-01/09-02)**: 容器内 `datetime.now()` 与 `utcnow()` **返回同值**(python 完全在 UTC), 存入 `timestamp without time zone` 后, 北京时间凌晨写入的行在库里属于**前一天** —— `index_snapshots` 每 30min 全天写入 48 档/天, 查"今天"丢 16 档、查"昨天"多算 16 档(实测)。→ 防复犯: ①**别假设业务只在交易时段跑**, 定时/采集类作业常 24×7 写入, 影响面按"该表实际写入时段"重算而非业务直觉; ②落库一律显式带时区或用 `Asia/Shanghai` 的 `now()`; ③**调度框架自带时区**(APScheduler `timezone="Asia/Shanghai"`)与容器 TZ 无关, 别据此误判 cron 错位(08-31 差点误报 P0 后自证推翻); ④TEXT 日期列比较须 `::date` 强转; ⑤下游 schema 新增字段后核验要两层 —— 是否被读取 + 判定阈值/文案是否与字段语义一致。

**── 证据 58 ──**
- 🔴 **LLM 逐步编排纯脚本任务 = 把执行时间暴露给 LLM 队列, 拥堵时撞硬超时(09-06 升级; Claw 09-05, 连续 4 天失败)**: 脚本实跑合计仅 **5.7 分钟**, 交给 agent 一步步编排后总耗时 8.6min(09-01 成功) → 36.6min → **90min 硬超时 ×2** → 82.8min terminated, 三个数据产物停更 **73 小时**。根因: agent 每一步(推理+工具调用)都要排 LLM 队列, 队列拥堵时编排开销从 3min 涨到 90min(与 `concurrency=3` 不执行限流同源)。→ 防复犯: **能封成单个 entrypoint 脚本的, 绝不让 agent 逐步编排**; 必须分步时先估"步数 × 单步排队"是否逼近硬超时; 并给下游产物加**停更时长告警**(数据停更 3 天比任务失败本身更致命, 却无任何告警)。

**── 证据 59 ──**
- 🔴 **外部数据接口验收必须「非空 + 字段完整性」双闸, 重试必须带判据(09-06 升级; Claw 09-06 + QTS 09-05)**: Wind 技术面/风险面接口**以约 2/3 概率返回残缺列**(三一重工技术项、招行"波动率_年化"各掉 1 项), 非空检查全部放行。→ 防复犯: ①加 `min_cols` / `expect_substr + min_hits` 判据, **按语义子串计数**(Wind 列名不稳定: `BETA`↔`近1年BETA`、`波动率_年化`↔`近1年年化波动率`), 别硬编码列名; ②命中残缺要 `continue` 重试而非接受 —— **无脑重试 N 次对 2/3 残缺率只有 ~56% 兜住率**, 必须带判据重试; ③同源坑: 探针工具名写错(`get_stock_technicals` 误作 `get_stock_technical`)返回全 None, 属「返回 0/None 先验证探针本身能命中」铁律的复现。

**── 证据 60 ──**
- 🔴 **子进程必须显式锁 `cwd`; 后台派发 + 延迟落盘日志会掩盖失败(09-06 升级; Claw 09-01 + pmf 09-01)**: ①`subprocess.run` 默认继承调用方 cwd → 同一份巡检代码在不同工作目录下语义完全不同, 只读检查变成对生产服务的写/压测(实锤: 巡检中枢每小时在 QTS 仓内替其跑一遍 e2e 测试, 凭空造出恒定 14 条/批的 401); **"规整到反常"(每批条数恒定、接口清单逐条一致、间隔严格跟随调度)就是脚本指纹, 不是人工探活**。②Laravel `runInBackground()` + `appendOutputTo()` 组合, 子进程跑不完则**日志永不变动**, `schedule:test` 显示 `0.43ms DONE` 而真实执行 117ms。→ 防复犯: 巡检/运维脚本所有子进程调用带 `cwd=`; 判作业死活用**日志 mtime** 而非日志内容; 定位"部分作业失效"用**同批次对照实验**(同调度器同分钟的作业互相对照, 差异项即变量)。

**── 证据 61 ──**
- 🔴 **一次性取证判据不得依赖易失源+固定相对窗口, 否则随墙钟静默退化且永不自愈(09-08 实锤, Claw 统一巡检中枢 run#114→#115)**: 用 `docker logs --since 1200h` 固定窗口回溯最后 `[Fetch]` 时点, 证据(07-20)比窗口起点老 57min → `--since 1200h` 命中 0 条、换 `--since 1300h` 命中 358 条, 函数返 None → 判据退到 else 分支输出"扫码重登"误导文案(其 docstring 已自承"会误导"), 且墙钟单向推进使该退化**永不自愈**(run#114 对、run#115 错, 中间零变更)。**任何 `--since`/`--tail`/固定窗口的取证型判据都自带"过期日"——相对窗口 vs 绝对证据时间点必然在某天交叉。** 防复犯: ①一次性取证结论**落盘单调锚点**(取 `max(本次观测, 历史锚点)`, 易失源滚出窗口后判定仍成立; 本仓已有 `.qts_api_auth_401_anchor.json` / `.wechat_last_fetch_anchor.json` 先例); ②"昨天对今天错、中间无变更"现象**第一嫌疑是相对时间窗漂移**, 先换窗口宽度对拍零成本定位, 再找代码变更/外部故障; ③"时间窗吻合+现象同时出现"≠ 因果, 写因果前必须回读实现(本次初判"文案变化→去重键翻转"被代码证伪)。

**── 证据 62 ──**
- 🔴 **数据完整性/新鲜度检查的基准必须来自库外(09-08/09-09/09-10 实锤, QTS回测 ×4 变体)**: 库内自比(`MAX(date)`/`GROUP BY` 排序取最新/行数门槛/完整性阈值)只能答"库里**有什么**", 答不了"库里**缺什么**"——缺的交易日在任何聚合结果里都不出现。判"数据够不够新"一律拿外部基准(交易日历 `is_trading_day` / 权威源)与库内 `DISTINCT date` 做**差集**, 缺 N 个交易日即告警; 这是唯一能抓"整段缺失"的检查。

**── 证据 63 ──**
- 🔴 **上游定时任务失败 → 下游静默产出旧结论, 是本系统最高频事故之一(09-08 实锤, QTS回测)**: 凡"上游灌数/回填"驱动"下游日报/报告"的链路, 下游产物的新鲜度字段必须能**独立于上游的成功/失败而自证**, 不能假设上游一定跑过; 上游失败最常见的产物是"和昨天逐字相同"的旧结论(而非报错), 比报错更隐蔽。处置优先级: 发现数据缺失先补数据再重跑, 远比在旧数据上写免责声明有用。

**── 证据 64 ──**
- 🔴 **行数完整性 ≠ 数值完整性; 按绝对值门槛过滤的池子遇盘中未收盘数据静默缩水(09-10 实锤, QTS回测)**: "今日 N 只记录齐全"只证明写进去了, 证明不了"写进去的是终值"; 盘中 `amount` 仅全日的 ~4/5 → 成交额≥3亿 流动性门槛命中率被压低 → 股票池凭空少 13%, 日志全绿零告警。判据须用「当日 `SUM(amount)` 或 amount 中位数 vs 近 10 日同口径」而非只看行数; 凡按成交额/成交量/市值门槛过滤的池子, 遇盘中数据必然静默缩水, 必须等收盘后取数或加盘中口径守卫。

**── 证据 65 ──**
- 🔴 **同形异因: 告警信号命中后先确认命中的是不是同一条铁律的另一种根因(09-09 实锤, QTS回测)**: 同一告警信号(如"连日回测结果逐字相同")可由相反根因触发——灌库失败(连日 `data_as_of` 不前进) vs 调度时刻早于收盘(连日 `data_as_of` 每天前进但 `report_date` 总快 1 天); 前者要补数据、后者要改调度时刻, 处置相反。直接套旧处置会白跑一轮甚至改错。分流: 连日 `data_as_of` 不前进=灌库挂; 每天都前进但 report_date 总快 1 天=调度早。

**── 证据 66 ──**
- 🔴 **结论字段与得出该结论的证据字段必须一起输出; `dict.get` 静默返回 None 不报错(09-11 实锤, QTS回测)**: 凡加一道判据闸门, 其输入/证据字段必须出现在输出契约里; 只给标签(如 `✅ 可信`)不给证据(如 `wf_return`), 等于把复核能力锁死在生产端, 消费方只能盲信或用错误替代指标(如 `overfit_ratio`)反推。`.get(key)` 拿不到键时静默返 None(与"grep 查不到"同形), 取下游契约字段须先确认该键确在契约内, 缺失按"数据坏了"而非"消费方 bug"处理。

**── 证据 67 ──**
- 🔴 **低样本/过拟合信号下游禁表述为"推荐/买入信号", 只能作统计倾向参考(09-01 实锤, 应升未升补录 2026-09-27)**: 回测摘要凡 `low_sample=true` 或 `wf_overfit_ratio<0`(样本外劣于样本内)或 `win_rate=100%` 且 `total_trades=1`(单笔统计假象), 下游不得表述为"推荐/买入信号", 只能作"策略族统计倾向"; `overfit_ratio` 极大(>5)不是过拟合而是样本内无优势(分母趋零), 读 `wf_return` 才准。凡二元门(`x>0`)用于质量判定, 必改比率门+方向门(同源 08-31 铁律)。

**── 证据 68 ──**
- 🔴 **上游产品公告"已修复" ≠ 我们的链路已修复(09-30 实锤, WeChatRSS 0.9.16)**: 收到厂商修复公告后, 先核**三件事**再决定是否恢复自动化/改判断口径: ①**平台适用性**——公告只修 Windows 客户端, 本机 macOS; 官网运行时配置 `collectorDownloadUrl:"/api/downloads/client/win?channel=web-v2"` 是唯一硬证据(公告中心 7 条全 Windows)。②**我们用的是哪条轨**——我们用云端 API, 与客户端本地扫描是两条独立链路; 直连复测 `GET /api/subscriptions` 仍 `HTTP 401 {"detail":"无效的认证凭证"}`(08-19 起未变), 非限流非超时。③**兜底轨能不能顶上**——本地 5001 `isExpired=true`, 存量 270 篇最新仅 2026-07-20, **比落盘池(08-06)还旧**, 救不了新鲜度。配套处置(可复用): 把断供期 PAUSED 的同步自动化改造成「**恢复哨兵**」——先直连取状态码, 200 → 立即补落盘+推"已恢复"; 非 200 → 转兜底轨; 双轨皆死 → 按日锁降频推 1 条含可执行动作的卡片, 禁止空转刷屏; 凭证失效**不要** record_backoff_fail(会让下次探测更晚)。另: 精读槽 success=true 但产出 0 = 空转, 判据要看产物 mtime(`article_insights.json`), 不看调度 success。

**── 证据 69 ──**
- 🔴 **自动化 session 的 MCP 工具按 connector 白名单注入; 自动化想用 MCP 必须在 UI 勾 connector(10-01 实锤)**: ①**证据法**: 自动化会话日志里 `mcpConfig={"mcpServers":{...}}` + `Indexing deferred tools for server: <name>` 会列出本轮实际注入的 MCP server(实测 09-29 那条只有 agent-mail/connector-proxy/genie-baas/sheetagent/weixinpay, 无 wechatrss), 同日志工具名统计 Read/Bash/Skill 有而 `mcp__` 为 0 → **没挂钩的自动化调不到 MCP**, 不是"模型忘了调"。②**automation_update 改不了该字段**: 传 `connectorIdsJson` 与 `connector_ids` 均返回 `success:true` 但回读 `connector_ids_json` 仍 `[]`(第三个"管理面假成功"实例, 同族: model_id 的 snake_case、界面改好的错觉) → **connector 只能从 UI 勾选**, 别在 API 上耗时间。③**脚本直连 MCP 端点不可行**: 端点需 OAuth Bearer(无凭证 `401 invalid_token` + `www-authenticate: ...resource_metadata=`), token 落在 `~/.workbuddy/connectors/<id>/.credentials.v3.json` 但为 **AES-256-GCM(HKDF) 加密**, 密钥在 app 内部 → 解密这条路不要走。④判据: 想验证"某个 connector 能不能被自动化用", 看日志的 `Indexing deferred tools for server:` 清单即可, 不必跑任务试。
- 🔴 **MCP 直取可跳过"落盘→回填→再精读"三道工序**: 旧链路(落盘 output/wx_articles → backfill 正文 → read_wx_articles 精读)在 MCP 时代是多余搬运; `list_articles(include_body=false)` 拿元数据过滤未读(每轮 ≤8 篇控成本) → `get_article(id)` 直接读正文进上下文 → LLM 出 insight → 脚本幂等落库(新建 `Claw/.workbuddy/scripts/append_insights.py`, 按 source_file+title 双键去重)。**大 JSON 一律交给脚本写**, 不让模型手写。

**── 证据 70 ──**
- 🔴🔴 **401「无效的认证凭证」先穷举认证姿势，别急着判定"凭证吊销/套餐到期"(10-01 实锤, 公众号云轨断供 42 天真因)**: wechatrss 云端 REST 自 08-19 被我们判死("token 吊销/套餐到期", 甚至据此把整条云轨 PAUSED 42 天), 10-01 用户递来 key 一试才发现 **key 根本没变**(前缀 ak_ado 与本地文件逐字一致), 坏的是**认证头用错**: `/api/subscriptions` 只认 `X-API-Key` + `X-API-Secret` **双头**(→200, 18 订阅), 旧代码发的 `Authorization: Bearer <JWT>` → 401「无效的认证凭证」, 而两者同时给也 401(服务端见 Authorization 就走 JWT 分支并失败) → **错的头会掩盖对的头**。方法论: ①**服务端错误文案逐字读**——"只收到 X-API-Key, 还需要 X-API-Secret"(它把正确方案直接写在报错里); ②**同一 endpoint 穷举 5-6 种姿势**(Bearer/X-API-Key/裸 Authorization/query token/query api_key/X-Api-Token)再下结论; ③**先比对新旧凭证是否真的不同**(一行 `key[:6]` 比对即可), "用户给了新 key" ≠ "旧 key 失效"; ④同一服务不同 endpoint 的认证方式可以不同(feed 用 `?token=` query, 订阅列表用双头) → 一个 endpoint 401 不代表全站死。**代价**: 42 天断供 + 停产线改造(MCP/本地兜底)+ 三次错误根因结论。**同族**: 证据 67(公告适用性)、证据 68(connector 白名单) 都是"结论下早了"。
- 🔴 **RSS feed 的 `<description>` 常是完整正文, 逐篇正文接口是多余一跳(10-01 实锤)**: 云端 feed 单篇 description 实测 1.0w~11w 字符、就是正文 HTML(内层还带 `&amp;lt;` 嵌套编码, 需**双重 unescape**); 而独立的 `POST /api/article` 已 401。判据: 落盘前先 `len(description)` 看一眼, >1000 就说明 feed 自带全文 → `_html_to_text()`(br/p/div→换行, 去 script/style, 双层 unescape)直接落盘, 省掉 N 次请求与限流退避。同步脚本只在该字段为空时才回落单篇接口。

**── 证据 71 ──**
- 🔴 **容器健康 ≠ 可重新部署; 重建能力须纳入定期巡检(10-04 升级; Claw 09-28 pmf 实锤)**: `docker compose build` 因 `docker-php-ext-install opcache` 而 `install-modules` 失败(exit 2), 但容器 `Up 12 days (healthy)`、面板照常开、周报一直标"🟢 CI 绿"——"跑着"与"能重新部署"两件事解耦, 无人验证的重建能力会在某天变成装饰。"修 pmf 的 ops 探测要生效必须先重建镜像"才发现构建早已死。→ 防复犯: 带 Dockerfile 项目把 `docker compose build` 纳入月度巡检(慢但足够); 基础镜像刷新会引爆 Dockerfile 陈旧假设(旧镜像跑得好≠还能构建); `cp: can't stat 'modules/*'` + `install-modules` 报错优先怀疑基础镜像已内置(`php -m | grep -i <ext>` 一行验证), 别去调并行度(`-j` 改掉又改回要留痕); 排除法改动须写进 commit/日志。

**── 证据 72 ──**
- 🔴 **CI 红须拆 job 粒度 + `needs:` 上游红静默跳过下游(10-04 升级; Claw 09-28 main CI 连红 4 周实锤)**: "CI 红"是聚合状态不能指导修复, 实测是两个互不相干 job 各自红(Pre-commit `ruff format --check` 33 文件欠账 + `ruff check` 12 条; Security bandit 1 条 MEDIUM B608, bandit 只认 `# nosec` 不认 ruff 的 `# noqa: S608`)。且 `test` job 声明 `needs: lint` → lint 自 09-21 恒红使 Unit Tests **一次没跑**(下游 4 周静默跳过), 修绿后立刻暴雷(exit 2, 517 测试 0 跑)。→ 防复犯: CI 红先拆到 job 粒度; 修上游 job 时**必须预期下游首次暴露问题**, 逐个 job 至少成功跑过一次; 别把"上游变绿"当修完; push.paths 要含 `tests/**` 否则改测试不触发 CI。

**── 证据 73 ──**
- 🔴 **禁写死本机绝对路径 + 本地全绿≠CI 绿(10-04 升级; Claw 09-28 实锤)**: 3 个新测试把路径写成 `/Users/guan/WorkBuddy/Claw/.workbuddy/scripts/*.py` → 本机 100% 绿、CI runner 无 `/Users/guan` → collection 阶段 `FileNotFoundError` 整 job exit 2(**连别的测试都没跑**); 另有 3 处把本机路径传 `_find_project_dir()` 并断言 `"Claw" in result` → 该函数在找不到根时退而求其次返回入参致断言**恒真**(断言常量≠验证行为)。同轮 Unit Tests 真跑起来后又暴露生产代码 `is_trading_day.load_holidays()` 在日历缺失时 `sys.exit(2)` 致中枢进程被带走(`except Exception` 接不住 SystemExit)。→ 防复犯: 测试用 `Path(__file__).resolve().parent.parent` 定位仓库根, 断言解析结果==仓库根; 推送前用 `git clone --local`(同卷防 Cross-device)造仅 tracked 文件的树验证(`pytest`/`ruff` 全跑, CI 缺本机路径与 gitignored 数据文件), 用完 `rm -rf` 避免被多副本审计当第二仓。

---

**── 证据 74 ──**
- 🔴 **比对口径须对齐(算法+粒度+编码), 否则结论会反(2026-10-11 实锤, Claw 2026-10-11-hash-compare-caliber-nearly-inverted)**: 比对哈希差点判反——算法与粒度错一个结论就反。"在用凭据在公开仓"被判成"已轮换"(P0级反向安全结论, 把一个公开仓里的有效凭据判成安全)。三方任一不同比对即无效, 且失败方式是**给出相反结论而非报错**(最危险: 没人复核已绿的结论)。固化成工具(--compare-env)比对算法+粒度+编码, 不靠人记。

**── 证据 75 ──**
- 🔴 **凭据入版本控制防护(2026-10-09 实锤, Claw 2026-10-09-product-repo-git-init-must-exclude-credentials)**: 产物型git仓库(技能库/数据目录/生成物)初始化时 `.gitignore` 必须显式列出凭据模式; "从索引移除文件"≠修好(对象库里仍在), 检查必须落在**对象库**(`git cat-file -e`/`git rev-list --all --objects | grep`)而非索引。轮换后必须复核: 在用值哈希已与所有历史值不同才算真换过。

**── 证据 76 ──**
- 🔴 **检测必须可证伪, 绿灯须能被已知正样本击破(2026-10-11 实锤, Claw rulesless-config-disables-all-detection / cannot-determine-rendered-as-pass 等 6 文件同族)**: ①规则文件为空/默认被替换→全部检测静默关闭(CI密钥扫描空跑68天, 显示绿灯); ②"取不到证"被渲染成"通过"(巡检4个检查同款, 探针数字不能直接当结论); ③检测器自身失效=假绿灯。凡检测类逻辑必须用**已知含目标的对象**试跑, 0命中即检测器失效; 其成功信号必须可被证伪, 否则等于没检测。

## ⚠️ 注入上限：规则层置顶、证据层在文末（09-28 重构）
- 10-05 修复后实测 96849B → 截断 ≈7700B（8.0%，第 85 行）；上限非恒定，取当日实测∩脚本内置。
- 结构：规则层全可见｜证据层在文末｜其余 `grep -n "<词>"` → Read ±30 行。
- 🔴 新铁律一行进规则层、复现进证据库；前段加内容蚕食可见区；自检 `check_memory_visibility.py`。
