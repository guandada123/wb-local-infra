# plist live-map（阶段2 台账，2026-11-19 快照口径）

> 依据：plist 引用路径 grep + `~/.agent-autoloop/logs` 近期执行记录（阶段0证据）。

## 与 Claw 仓相关的关键 job（拆仓迁移时的改动面）

| plist | 引用路径 | 调度 | 备注 |
|---|---|---|---|
| com.user.feishu-daily-digest | /Volumes/ZHITAI/WorkBuddy/Claw/scripts/feishu_daily_digest.py | 每日 22:00 | 🔴 直指 ZHITAI 物理路径 |
| com.user.feishu-periodic-digest | /Volumes/ZHITAI/WorkBuddy/Claw/scripts/feishu_daily_digest.py | 每日 23:10 | 🔴 同上 |
| com.user.feishu-ai-triage | /Volumes/ZHITAI/WorkBuddy/Claw/scripts/feishu_ai_triage.py | 10:15/13:15/18:20/20:15 | 🔴 同上 |
| com.user.inspection-to-queue | /Volumes/ZHITAI/WorkBuddy/Claw/scripts/inspection_to_queue.py | 每日 17:15 | 🔴 同上 |
| （autopilot-gate） | Claw/scripts/autopilot_gate_check.py | — | 内盘路径引用 |
| com.user.claw-qts-sync | claw-script-runner.py --script .workbuddy/scripts/sync_claw_to_qts_portfolio.py | — | CLAW_HOME 默认 ZHITAI |
| com.user.qts-daily-backfill | claw-script-runner.py --script .workbuddy/scripts/qts_daily_backfill.py | — | 同上 |

## 真源裁决锚点（阶段0结论）

- `.workbuddy/scripts/`：2 个 live 高置信（qts_daily_backfill / sync_claw_to_qts_portfolio，11-19 00:02 实跑）。
- `scripts/`：4 个独占 live（feishu_daily_digest / feishu_ai_triage / inspection_to_queue / autopilot_gate_check，仅存在于 scripts/ 侧，不在 92 分叉集内）。
- 92 个分叉脚本：90 个无调度证据（73 个 .workbuddy 侧较新 / 17 个 scripts 侧较新）→ 大部分为双份闲置，处置待审批。

## 其他活跃 job 速览

- com.user.wb-heartbeat（10min）｜com.user.wb-liveness / wb-failures（1-2h）｜com.user.lark-cli-sync（09:20）
- com.user.feishu-event-consumer（常驻）｜com.user.feishu-event-bridge（20s）｜com.user.feishu-daily-digest（22:00）
- com.user.inspection-to-queue（17:15）｜com.user.feishu-periodic-digest（23:10）｜com.user.feishu-ai-triage（四时点）

完整清单见 `launchd/` 快照（52 个 plist，全部 plutil -lint 通过、cmp 与源零差异）。
