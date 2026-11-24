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

（新增条目请按上面格式追加，并注明日期与基线 commit）
