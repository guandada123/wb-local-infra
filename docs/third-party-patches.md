# 第三方仓的本地补丁台账

本机有些目录是**别人项目的 git 克隆**（不是我们的仓），为了修本地真问题做了补丁。
它们不在本仓的同步闸门覆盖范围内，**升级/重装可能静默覆盖**，所以在此登记。

规矩：
1. 每个补丁必须写清「改了什么、为什么、怎么撤、上游有没有发」。
2. 补丁只做**最小改动**，不做重构、不加功能。
3. 上游若已修复，优先撤补丁跟随上游，而不是长期分叉。

---

## 1. agent-autoloop（上游 KKKKhazix/agent-autoloop）

- **位置**：`~/.agent-autoloop/app`（工作树 main，2026-11-24 时点基线 `d3a44ca`）
- **文件**：`protocol/validate.ts` → `validLater()`
- **改动**（2026-11-24）：
  ```diff
  -    : dateTime(later.at) && text(later.about, 4000) && later.cancel === undefined);
  +    : dateTime(later.at) && text(later.about, 4000) && later.cancel !== true);
  ```
- **为什么**：回执里若写 `"cancel": false`（语义等于"没取消"），旧逻辑要求「不写」
  才放行，于是 `false ≠ undefined` → **整份回执被拒，其中的 later 全部丢失**。
  而报错只说「later 每一项要有 key/at/about」，完全不提 cancel，排查成本极高。
  实测后果：2026-11-23 13:30 那轮（run 252）想安排 11-24 06:30 的复查，回执被拒，
  那次复查**从未被排期**（事后查未来排期 = 0）；同类卡片 11-19（#34）已出现过一次。
- **验证**：
  - 用上游自己的 `readMessage` + `resultFrom` 跑真回执：改前 `problem` 报该错、`later` 丢失；改后 `problem: none`、`later` 保留
  - 新增 `tests/later-cancel.test.ts`（3 项：`cancel:false` 接受 / `cancel:true` 语义不变 / 缺 at、缺 key、超 10 项仍拒收）
  - 全量 `tests/!(simulation).test.ts`：797 项，14 失败；**A/B 对照**——撤掉本补丁同样 14 项失败（均为 installer/权限/进程组的环境类测试），与本改动无关
- **怎么撤**：`cd ~/.agent-autoloop/app && git revert <commit>`（或把那行改回 `later.cancel === undefined`）
- **上游**：未发 PR（补丁由本地判断做的兼容性放宽；若上游接受，撤本地补丁跟随即可）
- **可重打的补丁文件**：`patches/agent-autoloop-later-cancel-false.patch`（含新测试）。重装/换机后：
  ```bash
  cd ~/.agent-autoloop/app && git apply /path/to/patches/agent-autoloop-later-cancel-false.patch
  node --disable-warning=ExperimentalWarning --test tests/later-cancel.test.ts   # 应 3 pass
  ```
  已验证：在干净上游（`d3a44ca`）上 `git apply --check` 通过、应用后 3 项测试全过。
- **风险**：上游升级若改到同一行会冲突；重装/覆盖安装会丢补丁 → 重装后按上面命令重打并复查此行

---

（新增条目请按上面格式追加，并注明日期与基线 commit）
