# 设计：给 hub-overview 增加「数据新鲜度」判定

状态：**待评审，未实施**
日期：2026-11-26
影响面：`hub-overview-server.py`（生成侧）+ `hub-overview-watch.py`（观察侧）

---

## 1. 要解决的问题

`hub-overview-watch.py` 的 `probe()` 目前验四件事：

1. HTTP 200
2. `generated_at` / `kpi` / `sources` 三字段存在
3. `kpi.today` 非空
4. `sources` 里各源没有 `error` 字段

这已经比"只看状态码"强得多。但它有一个盲区：

> `generated_at` 在 server 第 319 行是 `now().isoformat()`，**每次请求现算**，永远是"刚刚"。
> 所以只要服务活着、源不报错，**数据烂在库里三天也照样是绿灯**。

判据上这叫「验了身份，没验新鲜度」。

## 2. 设计原则

| 原则 | 理由 |
|---|---|
| 年龄在**生成侧**算，观察侧只读 | watch 拿不到数据源的原始时间，只有 server 知道 |
| **只加字段**，不动现有字段 | 不破坏 probe 现有的三字段检查与前端 |
| `launchd` / `git` **明确排除** | 这两个源是实时读的，没有"陈旧"语义，加了只会造假警报 |
| **先观察、后定阈值、再告警** | 拍脑袋定时长 = 造永红告警 |
| 复用现有 `degraded` 通道 | 不新建告警类型，`decide()` 的集合去抖已验证只报变化 |

## 3. 数据可得性（逐源核实，非推测）

| 源 | 现有字段 | 能拿到的时间 | 成本 |
|---|---|---|---|
| `hub.db` | runs / runs_limit / schedules / events_tail | **`runs[0]["created_at"]`**（第 348 行已按 `created_at DESC` 加载到内存） | **零**，不加查询 |
| `rules.json` | agents | 文件 mtime | 一次 stat |
| `QUEUE.md` | todo_blocks | 文件 mtime | 一次 stat |
| `launchd` | com.user | 无（实时枚举） | — 排除 |
| `git` | projects | 无（实时枚举） | — 排除 |

三个源可得，两个排除。**没有任何一个需要新增 SQL 或外部调用。**

## 4. 改动点

### 4.1 server 端（`hub-overview-server.py`）

在三处 dict 里各加一个字段，**不改原有键**：

```
第 354 行附近：
out["sources"]["hub.db"] = {..., "last_run_at": (runs[0]["created_at"] if runs else None)}

QUEUE.md / rules.json 的赋值处：
out["sources"]["QUEUE.md"] = {..., "mtime": <ISO>}
out["sources"]["rules.json"] = {..., "mtime": <ISO>}
```

时间格式与 `generated_at` 统一用 `.isoformat(timespec="seconds")`，避免前端解析分叉。

**必须保持**：`error` 分支不变（出错时仍只写 `{"error": ...}`，不写时间）。

### 4.2 watch 端（`hub-overview-watch.py`）

新增一个纯函数，不改 `probe()`：

```
def stale_sources(d, now_ts, thresholds):
    """返回 [源名] —— 数据年龄超过阈值的源。thresholds 为空时返回 []。"""
```

在主流程里：

```
stale = stale_sources(d, now_ts, THRESHOLDS)
errs = probe_errs + stale        # 并入现有降级集合
notify_needed, kind = decide(prev_state, prev_deg, ok, errs)
```

阈值来自模块级 `THRESHOLDS` dict，**Phase 1 为空**（等于不生效）。

## 5. 三阶段推进

| 阶段 | 做什么 | 验收判据 |
|---|---|---|
| **P1 只观察** | server 加字段；watch 算出 age 并写日志，`THRESHOLDS = {}` | `--json` 里三个源都有时间字段；watch 日志每轮出现 age；**零告警** |
| **P2 定阈值** | 用 P1 满 7 天的日志算每源间隔的 p50 / p90 / max | 输出阈值表并落到本文档附录；**阈值 = max × 1.5**，不留整数取整的随意空间 |
| **P3 开告警** | 填入 `THRESHOLDS`，stale 并入 errs | 见下方反证用例全部通过 |

### P3 必须通过的反证用例

「用例须被反证过才算覆盖」。三个都要做：

1. **制造陈旧**：`touch -t` 把 `QUEUE.md` 的 mtime 改到 30 天前 → 下一轮**必须报一次** `degraded`
2. **恢复**：`touch` 回当前时间 → 下一轮**必须报一次** `recovered`
3. **不重复刷**：保持陈旧不动 → 后续若干轮**不得再报**（验证集合去抖）

另加 `self_test()` 用例 3 条（纯函数 `stale_sources` 的边界：空阈值、缺失字段、时间格式非法），全部离线不联网。

## 6. 交易日 / 非交易日

**不引入日历判断**。理由：`hub.db` 的 runs 不只有交易任务（巡检、日报、事件链都在写），用 A 股交易日历会对齐错对象。

改用**数据驱动**：阈值来自 P1 实测的 max × 1.5。如果 7 天后发现周末间隔显著偏大，再在 P2 单独为 `hub.db` 加"周末阈值"，且必须附上间隔分布证据。

### 已实测的硬约束（2026-11-26 19:10，P1 上线当天补）

查 `runs` 与 `events` 两张表，最新一条都停在 `2026-11-26T10:10:00Z`（北京 18:10），
而 `QUEUE.md` 的 mtime 是 18:44。结论：

1. **不是 runs 漏记**。是 hub 轮次本来就稀疏 —— 由 `12:30 / 19:30 / 21:30` 三个日历点驱动，
   中间只有事件触发的零星轮次。
2. **相邻日历点间隔可达 7 小时**（12:30 → 19:30）；某一轮漏跑则达 **9 小时**。
3. **任何小于 10 小时的阈值都会每天误报。** 定阈值前必须先把这条写死，
   否则 P2 一定造出永红告警。
4. `QUEUE.md` 的 mtime 会被非轮次脚本单独改写（18:44 那次不在 runs 里），
   所以**不要用它的 mtime 推断"轮次是否在跑"** —— 两个口径不同，混用会得出相反结论。

## 7. 操作链（与现有闸门对齐）

源与部署副本当前**逐字节一致**（已验证 IDENTICAL），所以必须按序执行：

```
1. 改   ~/WorkBuddy/wb-local-infra/bin/hub-overview-server.py     （源）
2. 改   ~/WorkBuddy/wb-local-infra/bin/hub-overview-watch.py      （源）
3. 跑   wb-local-infra/tests/ 现有用例
4. 装   bash ~/WorkBuddy/wb-local-infra/install.sh
5. 验   ~/.local/bin/infra-sync-check          → 必须「一致」
6. 启   launchctl kickstart -k gui/$(id -u)/com.user.hub-overview
7. 看   curl -s http://127.0.0.1:3355/api/hub/overview | 检查新字段
```

**不许直接改 `~/.local/bin/`** —— 会被 `com.user.infra-sync-check`（每日 10:35）判漂移。

## 8. 风险与回滚

| 风险 | 影响 | 应对 |
|---|---|---|
| server 改动引入异常 | 3355 循环崩，看板全挂 | KeepAlive 会重启但会反复崩；回滚见下；改动只在三处 dict 赋值，不碰请求链路 |
| watch 误报 | 飞书刷群 | P1 阶段阈值空置，物理上不可能告警；P3 前必过反证用例 |
| 阈值定太紧 | 永红告警 | 阈值来自实测 max×1.5，不是估算 |
| 部署不一致 | 10:35 闸门报警 | 必须走 install.sh + infra-sync-check |

**回滚**：
```
git -C ~/WorkBuddy/wb-local-infra revert <commit>
bash ~/WorkBuddy/wb-local-infra/install.sh
launchctl kickstart -k gui/$(id -u)/com.user.hub-overview
```

## 9. 明确不做

- 不改 `probe()` 现有四个判据
- 不新建告警通道或飞书卡片类型
- 不给 `launchd` / `git` 加年龄
- P1 阶段不做任何告警
- 不动 `hub.db` 的表结构，不新增查询

## 10. 工作量与未知

- P1 改动量：server 约 6 行，watch 约 25 行（含函数与日志）
- **P2 需要等 7 天真实数据** —— 这是本设计唯一无法压缩的等待
- 未知：`runs[0]["created_at"]` 的时区格式（`created_at` 是 UTC ISO 带 Z，见 server 第 461 行注释），watch 端解析时必须统一按 UTC 处理，否则会差 8 小时，直接把阈值判错
