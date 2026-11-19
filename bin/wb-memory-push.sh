#!/bin/bash
# =============================================================================
# wb-memory-push.sh — MEMORY.md 远端备份推送入口（bash shim，2026-10-30 P1）
#
# 逻辑本体在 wb-memory-push.py（同目录，安装器一起同步）。shim 只做一件事：
#   用**被 TCC 放行**的 python（~/.workbuddy/binaries，同 wb-liveness 的 PY_BIN）
#   调起 python —— /usr/bin/python3、git、bash 内建在 launchd/cron 上下文里
#   对 /Volumes/ZHITAI 全部 EPERM（2026-10-30 实测，见 deploy/.learnings）。
#
# 用法：wb-memory-push.sh [--dry-run|--test-alert]
# 退出码：0 正常 / 1 故障（已按节流告警）
# =============================================================================
set -uo pipefail
export HOME="${HOME:-/Users/guan}"
PY="$HOME/.workbuddy/binaries/python/envs/default/bin/python"
[ -f "$PY" ] || PY="/usr/bin/python3"
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$PY" "$HERE/wb-memory-push.py" "${1:-run}"
