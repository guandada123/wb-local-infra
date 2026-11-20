#!/bin/bash
# =============================================================================
# wb-heartbeat.sh — 向外部心跳服务「打卡」（2026-10-18，2026-11-18 加一次快速重试）
#
# ⚠️ 本文件是**源**。实际运行的是 ~/.local/bin/wb-heartbeat.sh，
#    改完跑 bash .workbuddy/deploy/install-wb-liveness.sh 同步（同一安装器）。
#
# 它解决的问题：本机所有监控（launchd 巡检、中枢、失败扫表）都跑在同一台 Mac 上，
#   Mac 关机 / 断电 / 断网 / 系统挂死时，**没有任何人会报警** —— 报警器也在屋里。
#
# 本脚本只做一件事：每隔 N 分钟向 heatchchecks.io 的 ping 地址发一个 HTTP 请求。
#   打卡 = 「我还活着」；停止打卡 = 外面那台机器判定失联 → 直接调飞书机器人发消息。
#
# 为什么用外部服务而不是自建：
#   · 它必须在**另一个故障域**，否则 Mac 一死它也死（等于没做）
#   · 免费（healthchecks.io 免费版 20 个 check，够用）
#   · 它的 webhook 支持自定义 body，能直接按飞书机器人格式发，不需要中间转发
#
# 配置：~/.local/etc/wb-heartbeat.conf 一行
#   HC_PING_URL=https://hc-ping.com/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
# 未配置时脚本**正常退出并记一行日志**（不报错、不刷屏），这样装完可控。
#
# 2026-11-18 加「失败后 5s 快速重试一次」（依据：T-INS-a356da1cdd49）
#   起因：11-16 16:27 这一拍 curl 报 rc=35（TLS 握手失败），launchd 记 last exit code=1，
#   16:28 巡检据此推了「🟡 launchd 异常」告警；但 16:37 下一拍就打卡成功（+606s）。
#   全量日志复核：3 周 4186 拍里 14 次同类瞬时失败（13 次 rc=35 / 1 次 rc=28 超时），
#   14/14 都在下一拍自愈 —— 属网络侧抖动，不是脚本或配置故障。
#   加固后：同一拍内重试一次，抖动被挡在 exit 1 之外；真断网时两次都失败 → 仍 exit 1，
#   **失联语义不变**（外部看的是"打卡是否到达"，与退出码无关）。
#
# 退出码：0 已打卡（含重试后成功）或未配置 / 1 重试后仍打卡失败（网络问题，下轮会重试）
# =============================================================================
set -uo pipefail

export HOME="${HOME:-/Users/guan}"
CONF="${WB_HEARTBEAT_CONF:-$HOME/.local/etc/wb-heartbeat.conf}"
LOG="${WB_HEARTBEAT_LOG:-$HOME/Library/Logs/wb-heartbeat.log}"

mkdir -p "$(dirname "$LOG")" 2>/dev/null

# 日志轮转（1MB，打卡日志增长慢）
if [ -f "$LOG" ]; then
  sz="$(stat -f%z "$LOG" 2>/dev/null || echo 0)"
  [ "${sz:-0}" -gt 1048576 ] && mv -f "$LOG" "$LOG.1" 2>/dev/null
fi

log(){ printf '[%s] %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }

URL=""
if [ -f "$CONF" ]; then
  # 只取 HC_PING_URL= 这一行，忽略注释与空行
  URL="$(sed -n 's/^[[:space:]]*HC_PING_URL[[:space:]]*=[[:space:]]*//p' "$CONF" | tr -d '"'"'"' \r' | head -1)"
fi

if [ -z "$URL" ]; then
  log "未配置 HC_PING_URL（${CONF}）→ 跳过打卡。配好后本任务即可生效，无需重启 launchd。"
  exit 0
fi

case "$URL" in
  https://hc-ping.com/*|https://healthchecks.io/*) ;;
  *)
    log "⚠️ HC_PING_URL 不像 healthchecks 地址（应以 https://hc-ping.com/ 开头），仍尝试打卡：${URL:0:32}…"
    ;;
esac

# 打卡：超时 20s，失败不堆积（下一轮 10 分钟后自然重试，避免堆积）
# 单次打卡尝试：把 http 码放 stdout，curl 的 stderr 追加进日志
ping_once(){ /usr/bin/curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$1" 2>>"$LOG"; }

CODE="$(ping_once "$URL")"
RC=$?

# 失败后 5s 快速重试一次（2026-11-18）：挡掉 TLS/网络瞬时抖动导致的 last exit code=1
if [ "$RC" -ne 0 ] || [ "$CODE" != "200" ]; then
  sleep 5
  CODE2="$(ping_once "$URL")"
  RC2=$?
  log "↻ 首次未成功（rc=$RC http=${CODE:-none}）→ 5s 后重试：rc=$RC2 http=${CODE2:-none}"
  CODE="$CODE2"
  RC="$RC2"
fi

if [ "$RC" -eq 0 ] && [ "$CODE" = "200" ]; then
  log "打卡成功（HTTP ${CODE}）check…${URL: -8}"
  exit 0
fi

log "❌ 打卡失败 rc=$RC http=${CODE:-none} check…${URL: -8} —— 若连续失败，外部会判失联并报警（这正是我们要的）"
exit 1
