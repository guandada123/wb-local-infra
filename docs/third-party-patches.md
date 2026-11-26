# 第三方仓的本地补丁台账

本机有些目录是**别人项目的 git 克隆**（不是我们的仓），为了修本地真问题做了补丁。
它们不在本仓的同步闸门覆盖范围内，**升级/重装可能静默覆盖**，所以在此登记。

规矩：
1. 每个补丁必须写清「改了什么、为什么、怎么撤、上游有没有发」。
2. 补丁只做**最小改动**，不做重构、不加功能。
3. 上游若已修复，优先撤补丁跟随上游，而不是长期分叉。

---

## 1. agent-autoloop（上游 KKKKhazix/agent-autoloop）

- **位置**：`~/.agent-autoloop/app`（工作树 main，基线 `d3a44ca`；本地两笔提交 `13d498c`、`d58ca6f`）
- **文件**：`protocol/validate.ts`（`validLater` / `parseResult`）+ 新增 `tests/later-cancel.test.ts`
- **两个互不相干的原因，同一个错误提示**（这是本补丁真正的价值：让第三个原因不再难查）：

  | 起因 | 回执实际写法 | 旧规则为什么拒 |
  |---|---|---|
  | A（11-23 run 252 / 11-19 #34） | `"cancel": false` | 要求 `cancel === undefined`，`false ≠ undefined` |
  | B（11-24 run 256 / #43） | `"later": {…}` 对象 | `listOf` 要求数组，`Array.isArray` 为假 |

  两次报错都是「later 每一项要有 key，以及带时区的 at 和 about，或者 cancel: true，最多 10 项」，
  **既不说哪条错、也不说错在哪**，只能拿真回执反向复现才能定位。

- **改动**：
  1. `cancel === undefined` → `cancel !== true`（`false` 与「不写」语义相同）
  2. `parseResult` 里 `later` 若是单个对象，归一为 `[对象]`（只安排一项时不必套数组）
  3. 新增 `laterProblem()`：报错改为指位指字段（非数组 / 超 10 项 / 缺 key / 多余字段 /
     `cancel:true` 带 at / at 格式时区 / about 缺失超长）
- **实际损失（取证）**：run 252 想排 11-24 06:30 复查 → 从未排期（未来排期 = 0）；
  run 256 想排 14:10 查 CI → 同样丢失。
- **验证**：
  - 两份真回执（252、256）跑上游自己的 `readMessage`+`resultFrom`：改前均 `problem=该错`、`later` 丢失；改后均 `problem=none`、`later` 保留
  - `tests/later-cancel.test.ts` 5 项（两种宽容 + 报错指位 + 缺 at/缺 key/超 10 项仍拒收）
  - `npm run typecheck` 通过；全量 `tests/!(simulation)`：760 pass / 14 fail，**失败集与改前完全一致**（installer/权限/进程组环境类）
- **可重打的补丁文件**：`patches/agent-autoloop-later-receipt.patch`（含两笔提交与测试）。重装/换机后：
  ```bash
  cd ~/.agent-autoloop/app && git apply /path/to/patches/agent-autoloop-later-receipt.patch
  node --disable-warning=ExperimentalWarning --test tests/later-cancel.test.ts   # 应 5 pass
  ```
  已验证：干净上游 `d3a44ca` 上 `apply --check` 通过、应用后 5 测试全过。
- **怎么撤**：`git revert d58ca6f 13d498c`（或 `git reset --hard d3a44ca` 后重装）
- **上游**：未发 PR。建议发，因为「报错不指位」是通用的可用性问题，不只影响本地。
- **风险**：上游升级若改到同几行会冲突；重装/覆盖安装会丢补丁 → 按上面命令重打并复查

---

## 2. agent-autoloop（同一上游，第二笔补丁：峰谷避让）

- **登记日期**：2026-11-26
- **位置**：`~/.agent-autoloop/app`（基线 = 条目 1 之后的 HEAD `d58ca6f`；本地提交 `c04ecc7`）
- **文件**：`kernel/decide.ts`（新增 `PEAK_WINDOWS` / `peakHold()`，`tick()` 内对到期 timer 判定）
  + `tests/resume-thread.test.ts`（改 2 处时钟、新增 4 条）+ `tests/stops-and-threads.test.ts`（改 1 处时钟）
  ｜本地提交两笔：`c04ecc7`（实现）、`1d8c122`（补 rule-gone 用例）
- **为什么**：DeepSeek 高峰（周一至五 09-12、14-18 北京时间）单价翻倍，其余时段半价。
  中台的「到点复查」不赶时间，撞在峰里等于白付一倍。实测改前 9 轮 ¥0.444/轮、改后 6 轮 ¥0.276/轮。
- **改动**：
  1. `peakHold(now, timezone)` 返回需顺延的毫秒数；窗口 `[09:00,12:00)`、`[14:00,18:00)`，周末返回 null
  2. `tick()` 里对 `event_id is null && at <= now` 的 timer：峰内则 `at = now + hold`（落到 12:00 或 18:00）后 `continue`
  3. 规则已失效的 timer **不顺延**（只发通知、不调模型、不花钱）
  4. 注释声明两处已知边界：时区取自 `rules.timezone`（应保持 Asia/Shanghai）、**不含法定节假日**
- **实际效果（取证）**：11-26 09:00 / 11:10 两个定时器均顺延到 **12:00**，12:00:00 精确起跑 #282/#283；
  12:05 / 12:20 两个非峰 timer 未受影响（对应 #284 / #285 按原点起跑）。
- **验证**：
  - `tsc --noEmit` 通过；`prettier --check` 通过
  - `node --test tests/!(simulation)`：**814 pass / 0 fail / 22 skipped**（改前 810/788）
  - 新增 4 条：09:30 峰内顺延、09:00 整点顺延、12:00 整点不顺延、**规则已失效不被顺延**
  - 既有 3 条时钟从 09:01 推到 13:00，断言一字未改
- **可重打的补丁文件**：`patches/agent-autoloop-offpeak-timer.patch`（`git format-patch d58ca6f..HEAD`，含两笔提交与测试）
  ```bash
  cd ~/.agent-autoloop/app && git apply /path/to/patches/agent-autoloop-offpeak-timer.patch
  node --disable-warning=ExperimentalWarning --test tests/resume-thread.test.ts   # 应含 4 条峰谷用例
  ```
  已验证：在基线 `d58ca6f` 的干净副本上 `git apply --check` 通过、应用后 `peakHold` 在位。
- **怎么撤**：`git revert 1d8c122 c04ecc7`（或 `git reset --hard d58ca6f`）。撤销后 `peakHold` 消失，复查不再避峰。
- **上游**：未发 PR。这一笔是**本地策略**（绕开计费高峰），不是通用 bug 修复，不建议上游。
- **风险**：
  - 周末分支**尚未经生产验证**（下一个周六定时器 11-28 09:00 到期才能验），目前只有单元测试覆盖
  - 法定节假日会白延到 12:00（只慢不亏钱）
  - 所有顺延都落到同一整点（12:00 / 18:00），到期集中时会排队

---

（新增条目请按上面格式追加，并注明日期与基线 commit）
