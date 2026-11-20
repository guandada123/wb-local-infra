#!/bin/bash
# =============================================================================
# wb-liveness.sh — launchd 侧「零 LLM 成本」存活巡检（2026-10-18）
#
# ⚠️ 本文件是**源**。实际运行的是内置盘副本 ~/.local/bin/wb-liveness.sh，
#    改完必须跑 .workbuddy/deploy/install-wb-liveness.sh 同步（内置盘是为了 SSD 掉线时仍能跑）。
#
#   wb-liveness.sh liveness   2h：DB 心跳探针 + 中枢 540min 完成锚 → 去重 → 飞书
#   wb-liveness.sh failures   3h：automation_failure_watchdog.py（脚本自带 push）
#
# 为什么要这个脚本（背景）
#   存活判断的逻辑**早就在 Python 脚本里**（hub_liveness_probe / ops_center_liveness_watchdog /
#   automation_failure_watchdog），LLM 只做了"读 JSON → 拼字符串 → 推送"这层胶水。
#   但只要挂在 WorkBuddy 自动化上，平台必然拉起 LLM 会话 → 每轮都烧积分。
#   本脚本把同一套判断搬到 launchd，**能力不减、频率不降、成本归零**。
#
# 退出码
#   0 正常（不代表无失联；失联项已推送）/ 1 内部异常 / 2 输入不可读
#   3 推送失败（已入待补发队列）/ 4 依赖缺失（SSD 未挂载 / 脚本不见了）
#
# 五条硬约束（每条在本机都有过真实事故）
#   1. launchd 的 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，**没有 node**；
#      而 lark-cli 是 `#!/usr/bin/env node` → 必须 glob 出 node 目录补进 PATH。
#      node 目录带版本号（…/versions/22.22.2-6/bin），升级 WorkBuddy 后会变，所以不能写死。
#   2. push_feishu.sh / push_card.py 权限是 644（无执行位）→ **禁止用 [ -x ] 判断**，
#      一律 `bash xxx`。`~/.local/bin/wb_health_check.sh` 就是因此 34 次异常、零推送。
#   3. push_feishu.sh 返回 0 可能是"命中 6h 去重"而非送达 → 必须抓 message_id: om_
#      才算送达；否则记 push_verified=false 并入待补发队列。
#   4. 入口脚本必须放在**内置盘**（~/.local/bin）。~/.workbuddy 与 ~/WorkBuddy 都是
#      /Volumes/ZHITAI 的软链，SSD 掉线时脚本本体就消失了。
#   5. 去重键不能带会变的量（age/threshold），否则每轮都是新键 → 重复轰炸。
#      键只取名称；恢复时主动清除，避免 24h 内二次失联被误抑制。
# =============================================================================
set -uo pipefail

MODE="liveness"
DRY_RUN=0
FORCE=0
THRESHOLD_H=""
DEDUPE_TTL_MIN=1440   # 失联重提醒 24h（P0 事件，不能三天只提醒一次）
ERR_TTL_MIN=360       # rc=2 / 依赖错误 6h
NO_NODE_SELFHEAL=0

for arg in "$@"; do
  case "$arg" in
    liveness|failures)   MODE="$arg" ;;
    --dry-run)           DRY_RUN=1 ;;
    --force)             FORCE=1 ;;
    --threshold-hours=*) THRESHOLD_H="${arg#*=}" ;;
    --dedupe-ttl-min=*)  DEDUPE_TTL_MIN="${arg#*=}" ;;
    --no-node-selfheal)  NO_NODE_SELFHEAL=1 ;;
    *) echo "wb-liveness: 未知参数 $arg" >&2; exit 1 ;;
  esac
done

# launchd 不保证注入 HOME（2026-08-12 实测：首跑全误报）→ 显式兜底
export HOME="${HOME:-/Users/guan}"
export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"

CLAW="$HOME/WorkBuddy/Claw"
SCRIPTS="$CLAW/.workbuddy/scripts"
PROBE="$SCRIPTS/hub_liveness_probe.py"
ANCHOR="$SCRIPTS/ops_center_liveness_watchdog.py"
FAILW="$SCRIPTS/automation_failure_watchdog.py"
PUSH="$SCRIPTS/push_feishu.sh"
PUSH_CARD="$SCRIPTS/push_card.py"
CHAT="oc_9ee5303497f5e0e71666b610d6bdc346"

STATE_DIR="${WB_STATE_DIR:-$HOME/.local/state/wb-liveness}"
LOG="${WB_LOG:-$HOME/Library/Logs/wb-$MODE.log}"
DEDUP="$STATE_DIR/alerted.tsv"
LOCK="$STATE_DIR/.lock-$MODE"
PENDING_DIR="$STATE_DIR/pending"
if [ "$MODE" = "liveness" ]; then STATE_FILE="$STATE_DIR/last_run.json"; else STATE_FILE="$STATE_DIR/failures.json"; fi

mkdir -p "$STATE_DIR" "$PENDING_DIR" 2>/dev/null || { echo "wb-liveness: 无法创建 $STATE_DIR" >&2; exit 4; }

log(){ printf '[%s] [%s] %s\n' "$(date '+%F %T')" "$MODE" "$*" >>"$LOG"; }

# 日志轮转（5MB）
if [ -f "$LOG" ]; then
  sz="$(stat -f%z "$LOG" 2>/dev/null || echo 0)"
  [ "${sz:-0}" -gt 5242880 ] && mv -f "$LOG" "$LOG.1" 2>/dev/null
fi

# 单实例锁（>30min 视为陈旧）
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +30 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null
    mkdir "$LOCK" 2>/dev/null || { log "锁竞争，跳过"; exit 0; }
  else
    log "已有实例在运行，跳过"; exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

# ── node 自愈（坑 1）───────────────────────────────────────────────────────
# 判据是「node 能否被解析」，而不是「某个 glob 是否命中」：
# 实测 launchd 下 glob 会因 /Volumes 的目录遍历被 TCC 拦而匹配不到，
# 但 plist 的 PATH 里 /opt/homebrew/bin 有 node 且 lark-cli 实际可用 —— 只认 glob 会误报"node 缺失"。
NODE_OK=0
NODE_SRC=""
if [ "$NO_NODE_SELFHEAL" = 0 ]; then
  for n in "$HOME"/.workbuddy/binaries/node/versions/*/bin/node; do
    if [ -f "$n" ]; then
      _node_dir="$(dirname "$n")"
      export PATH="$_node_dir:$PATH"
      NODE_OK=1; NODE_SRC="$n"; break
    fi
  done
fi
export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
if [ "$NODE_OK" = 0 ] && _sys_node="$(command -v node 2>/dev/null)"; then
  NODE_OK=1; NODE_SRC="$_sys_node"
fi
if [ "$NODE_OK" = 1 ]; then
  log "node 可用：${NODE_SRC}"
else
  log "⚠️ node 缺失（glob 与系统 PATH 均未找到）→ lark-cli 无法启动，推送必然失败"
fi

# ── 依赖检查（坑 4：SSD 掉线时这里先报）───────────────────────────────────
SSD_OK=1
for f in "$PROBE" "$PUSH" "$SCRIPTS/push_card.py"; do
  [ -f "$f" ] || { SSD_OK=0; log "⚠️ 依赖缺失：${f}（外置 SSD /Volumes/ZHITAI 未挂载？）"; }
done

PY_BIN="$HOME/.workbuddy/binaries/python/envs/default/bin/python"
[ -f "$PY_BIN" ] || PY_BIN="/usr/bin/python3"
[ -f "$PY_BIN" ] || { log "无 python3 可用"; exit 4; }

PUSH_VERIFIED=""

# ── 推送（坑 2/3：不用 -x；抓 message_id）─────────────────────────────────
# ⚠️ 2026-10-24 修复：原实现 `bash "$PUSH"`（push_feishu.sh 包装）在 launchd 上下文下
#   执行外置 SSD(/Volumes/ZHITAI) 上的 .sh 会触发 `Operation not permitted`(EPERM)，
#   而 python 读 .py 作为数据不受影响 → 所有告警静默入 pending 队列、永不到达飞书。
#   改为**直接调 push_card.py**（launchd 下 python 读 SSD 脚本已被证明可用），
#   彻底绕开 bash 执行外置脚本的 EPERM 门禁。push_feishu.sh 仍保留作交互/兜底入口。
push_card(){  # $1=title $2=body
  local title="$1" body="$2" out rc level
  PUSH_VERIFIED=""
  level="${PUSH_LEVEL:-alert}"   # 旧实现硬编码 PUSH_LEVEL=alert（P0 红卡）；默认值不得降级为 info
  if [ "$DRY_RUN" = 1 ]; then log "DRY-RUN 本应推送：$title"; return 0; fi
  [ -f "$PUSH_CARD" ] || { log "推送失败：push_card.py 不存在"; return 4; }
  out="$(PYTHON="$PY_BIN" FEISHU_CHAT_ID="$CHAT" "$PY_BIN" "$PUSH_CARD" --title "$title" --level "$level" --section "" "$body" --chat-id "$CHAT" 2>&1)"
  rc=$?
  printf '%s\n' "$out" | sed 's/^/    /' >>"$LOG"
  if [ "$rc" -eq 0 ]; then
    if printf '%s' "$out" | grep -q 'message_id: om_'; then
      PUSH_VERIFIED=1; log "✅ 推送送达（message_id 已取证）"
    else
      PUSH_VERIFIED=0; log "⚠️ 推送 rc=0 但无 message_id（去重命中或 markdown 兜底）→ 未确证送达"
    fi
    return 0
  fi
  log "❌ 推送失败 rc=$rc"
  return "$rc"
}

local_notify(){ /usr/bin/osascript -e "display notification \"$1\" with title \"wb-liveness\"" >/dev/null 2>&1 || true; }

queue_pending(){  # $1=title $2=body → 下轮补发
  local f
  f="$PENDING_DIR/$(date +%s)-$$.card"
  printf '%s\n%s\n' "$1" "$2" >"$f" 2>/dev/null && log "已入待补发队列：$f"
}

retry_pending(){
  local f title body
  for f in "$PENDING_DIR"/*.card; do
    [ -f "$f" ] || continue
    title="$(sed -n '1p' "$f")"
    body="$(sed -n '2,$p' "$f")"
    if push_card "$title" "$body"; then rm -f "$f"; log "待补发已送达：$f"
    else log "待补发仍失败，保留：$f"; return 1; fi
  done
  return 0
}

# ── 去重（坑 5：键不带会变的量）──────────────────────────────────────────
dedupe_hit(){  # $1=key [$2=ttl_min]
  local k="$1" ttl="${2:-$DEDUPE_TTL_MIN}" last now
  [ -f "$DEDUP" ] || return 1
  last="$(awk -F'\t' -v k="$k" '$1==k{print $2; exit}' "$DEDUP" 2>/dev/null)"
  [ -n "$last" ] || return 1
  now="$(date +%s)"; [ $((now - last)) -lt $((ttl * 60)) ]
}
dedupe_put(){
  local k="$1" now tmp; now="$(date +%s)"; tmp="$DEDUP.$$"
  awk -F'\t' -v k="$k" '$1!=k' "$DEDUP" 2>/dev/null >"$tmp"
  printf '%s\t%s\n' "$k" "$now" >>"$tmp"; mv -f "$tmp" "$DEDUP"
}
dedupe_clear(){
  local k="$1" tmp; [ -f "$DEDUP" ] || return 0; tmp="$DEDUP.$$"
  awk -F'\t' -v k="$k" '$1!=k' "$DEDUP" >"$tmp" 2>/dev/null && mv -f "$tmp" "$DEDUP"
}
dedupe_prune(){  # 30 天未触达的键清掉
  local tmp; [ -f "$DEDUP" ] || return 0; tmp="$DEDUP.$$"
  awk -F'\t' -v cut="$(( $(date +%s) - 2592000 ))" '$2>=cut' "$DEDUP" >"$tmp" 2>/dev/null && mv -f "$tmp" "$DEDUP"
}

write_state(){  # rc stale_n anchor_gap anchor_over push_rc push_verified pending
  "$PY_BIN" - "$STATE_FILE" "$MODE" "$1" "$2" "$NODE_OK" "$SSD_OK" "$3" "$4" "$5" "$6" "$7" <<'PY'
import datetime, json, os, sys
path, mode, rc, n, node_ok, ssd_ok, gap, over, prc, pver, pend = sys.argv[1:12]
def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None
d = {
    "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    "mode": mode, "rc": int(rc), "stale_count": int(n),
    "node_ok": node_ok == "1", "ssd_ok": ssd_ok == "1",
    "anchor_gap_min": num(gap), "anchor_over": over == "1",
    "push_rc": int(prc) if prc not in ("", "-1") else None,
    "push_verified": (pver == "1") if pver != "" else None,
    "pending": pend == "1", "pid": os.getpid(),
}
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, ensure_ascii=False, indent=2)
os.replace(tmp, path)
PY
}

# ── liveness 主流程 ───────────────────────────────────────────────────────
run_liveness(){
  local rc=0 lines="" stale_n=0 new_body="" new_keys="" body="" prc="" pend=0
  local anchor_json="" anchor_gap="" anchor_over=0 anchor_err="" f

  if [ "$SSD_OK" != 1 ]; then
    body="launchd 存活巡检无法取证：依赖脚本缺失（外置 SSD /Volumes/ZHITAI 未挂载）。这不是健康状态。"
    if push_card "存活巡检依赖缺失" "$body"; then :; else prc=$?; queue_pending "存活巡检依赖缺失" "$body"; pend=1; fi
    write_state 4 0 "" 0 "$prc" "$PUSH_VERIFIED" "$pend"; return 4
  fi

  local -a pargs=(--brief)
  [ -n "$THRESHOLD_H" ] && pargs+=(--threshold-hours "$THRESHOLD_H")
  [ -n "${WB_REGISTRY:-}" ] && pargs+=(--registry "$WB_REGISTRY")

  lines="$("$PY_BIN" "$PROBE" "${pargs[@]}" 2>>"$LOG")"; rc=$?

  if [ "$rc" -ne 0 ]; then
    if [ "$rc" -eq 2 ]; then
      body="hub_liveness_probe rc=2：输入不可读（registry / workbuddy.db 任一不可用）。读不出来 ≠ 没有失联。"
    else
      body="hub_liveness_probe 异常退出 rc=${rc}（脚本崩溃或依赖不可用）。"
    fi
    body="$body"$'\n'"$lines"
    if [ "$FORCE" = 1 ] || ! dedupe_hit "probe:rc$rc" "$ERR_TTL_MIN"; then
      if push_card "存活巡检取不到证据 (rc=$rc)" "$body"; then dedupe_put "probe:rc$rc"
      else prc=$?; queue_pending "存活巡检取不到证据 (rc=$rc)" "$body"; pend=1; fi
    fi
    write_state "$rc" 0 "" 0 "$prc" "$PUSH_VERIFIED" "$pend"; return "$rc"
  fi

  # 中枢「成功收尾」锚：与 DB 心跳是**不同证据源**（派发 vs 收尾），必须都看
  if [ -f "$ANCHOR" ]; then
    anchor_json="$("$PY_BIN" "$ANCHOR" --json 2>>"$LOG")"
    if [ -n "$anchor_json" ]; then
      anchor_gap="$(printf '%s' "$anchor_json" | "$PY_BIN" -c 'import json,sys;d=json.load(sys.stdin);print("" if d.get("gap_min") is None else d["gap_min"])' 2>/dev/null)"
      anchor_over="$(printf '%s' "$anchor_json" | "$PY_BIN" -c 'import json,sys;d=json.load(sys.stdin);print(1 if d.get("over") else 0)' 2>/dev/null)"
      anchor_err="$(printf '%s' "$anchor_json" | "$PY_BIN" -c 'import json,sys;d=json.load(sys.stdin);print(d.get("error") or "")' 2>/dev/null)"
    else
      anchor_err="锚检查脚本无输出"
    fi
  else
    anchor_err="ops_center_liveness_watchdog.py 缺失"
  fi

  stale_n="$(printf '%s\n' "$lines" | grep -c '^\[失联\]')"; [ -n "$stale_n" ] || stale_n=0

  # 逐项去重：键只取名称（去掉"上次…已…h（阈…h）"这段每轮都会变的部分）
  local seen="" key line
  while IFS= read -r line; do
    case "$line" in "[失联]"*) ;; *) continue ;; esac
    key="stale:$(printf '%s' "$line" | sed -e 's/^\[失联\] //' -e 's/ 上次 .*//')"
    seen="$seen$key"$'\n'
    if [ "$FORCE" = 1 ] || ! dedupe_hit "$key"; then
      new_body="$new_body$line"$'\n'; new_keys="$new_keys$key"$'\n'
    fi
  done <<< "$lines"

  # 已恢复的项清除去重键，避免"恢复后 24h 内再次失联"被误抑制
  if [ -f "$DEDUP" ]; then
    while IFS= read -r key; do
      case "$key" in
        stale:*) printf '%s' "$seen" | grep -qxF "$key" || dedupe_clear "$key" ;;
      esac
    done <<< "$(awk -F'\t' '{print $1}' "$DEDUP" 2>/dev/null)"
  fi

  if [ -n "$anchor_err" ] && [ "$anchor_err" != "no_last_ok_ts" ]; then
    if [ "$FORCE" = 1 ] || ! dedupe_hit "anchor:error" "$ERR_TTL_MIN"; then
      new_body="${new_body}[状态锚] 检查异常：$anchor_err"$'\n'
      new_keys="$new_keys""anchor:error"$'\n'
    fi
  fi

  if [ "$anchor_over" = 1 ]; then
    local amsg
    if [ -n "$anchor_gap" ]; then
      amsg="中枢完成信号超时：上次成功收尾 ${anchor_gap} 分钟前（阈 540 分钟）"
    else
      amsg="中枢从未成功收尾（状态锚无 last_ok_ts）"
    fi
    if [ "$FORCE" = 1 ] || ! dedupe_hit "anchor:hub"; then
      new_body="${new_body}[状态锚] $amsg"$'\n'; new_keys="${new_keys}"anchor:hub$'\n'
    fi
  elif [ -z "$anchor_err" ]; then
    dedupe_clear "anchor:hub"
  fi

  if [ -n "$new_body" ]; then
    body="统一巡检中枢存活看门狗（launchd，零 LLM）"$'\n\n'"$new_body"$'\n'"本次 DB 心跳失联 ${stale_n} 项；rc=2 表示输入不可读，绝不等于健康。"
    if push_card "存活巡检告警" "$body"; then
      while IFS= read -r key; do [ -n "$key" ] && dedupe_put "$key"; done <<< "$new_keys"
      write_state 0 "$stale_n" "$anchor_gap" "$anchor_over" 0 "$PUSH_VERIFIED" 0; return 0
    else
      prc=$?; queue_pending "存活巡检告警" "$body"; local_notify "存活巡检推送失败，已入待补发"
      write_state 0 "$stale_n" "$anchor_gap" "$anchor_over" "$prc" "$PUSH_VERIFIED" 1; return 3
    fi
  fi

  log "无新增失联（stale=$stale_n anchor_gap=${anchor_gap:-?} over=${anchor_over}）"
  write_state 0 "$stale_n" "$anchor_gap" "$anchor_over" "" "" 0
  return 0
}

# ── failures 主流程（脚本自带 push，这里只调度 + 记账）────────────────────
run_failures(){
  local out rc summary critical pushed body prc="" pend=0
  if [ "$SSD_OK" != 1 ]; then
    body="自动化失败扫表无法运行：依赖脚本缺失（外置 SSD 未挂载）。"
    if push_card "失败扫表依赖缺失" "$body"; then :; else prc=$?; queue_pending "失败扫表依赖缺失" "$body"; pend=1; fi
    write_state 4 0 "" 0 "$prc" "$PUSH_VERIFIED" "$pend"; return 4
  fi

  # 2026-11-07：加 --zombie-scan / --open-run-scan。两者都是只读诊断，
  # 只往本函数返回的 $out 里多打几行明细（下方 sed 只取 SUMMARY 行，解析不受影响），
  # 不改 critical 计数、不改推送内容。目的：让每小时日志留下「零活动会话 / 长跑未结束 run」记录，
  # 为 11-06 那次 20 小时停摆类事故提供可回溯证据（事故复盘见 .learnings/2026-11-06-*）。
  out="$("$PY_BIN" "$FAILW" --hours 24 --zombie-scan --open-run-scan 2>&1)"; rc=$?
  printf '%s\n' "$out" | sed 's/^/    /' >>"$LOG"

  summary="$(printf '%s\n' "$out" | sed -n 's/^SUMMARY: //p' | tail -1)"
  critical="$(printf '%s' "$summary" | "$PY_BIN" -c 'import json,sys;print(json.load(sys.stdin).get("critical",0))' 2>/dev/null || echo 0)"
  pushed="$(printf '%s' "$summary" | "$PY_BIN" -c 'import json,sys;print(1 if json.load(sys.stdin).get("pushed") else 0)' 2>/dev/null || echo 0)"

  if [ "$rc" -ne 0 ]; then
    body="automation_failure_watchdog.py 异常退出 rc=${rc}（失败扫表本身失效，意味着无人发现自动化失败）"
    if [ "$FORCE" = 1 ] || ! dedupe_hit "failw:rc$rc" "$ERR_TTL_MIN"; then
      if push_card "失败扫表无法运行" "$body"; then dedupe_put "failw:rc$rc"
      else prc=$?; queue_pending "失败扫表无法运行" "$body"; pend=1; fi
    fi
    write_state "$rc" "${critical:-0}" "" 0 "$prc" "$PUSH_VERIFIED" "$pend"; return "$rc"
  fi

  log "失败扫表完成：critical=${critical:-0} pushed=${pushed:-0}"
  write_state 0 "${critical:-0}" "" 0 "" "" 0
  return 0
}

log "开始（dry_run=$DRY_RUN force=$FORCE threshold=${THRESHOLD_H:-auto} node_ok=$NODE_OK ssd_ok=${SSD_OK}）"
[ "$DRY_RUN" = 0 ] && { retry_pending || true; }
dedupe_prune
case "$MODE" in
  liveness) run_liveness ;;
  failures) run_failures ;;
  *) log "未知模式：$MODE"; exit 1 ;;
esac

# ---- MEMORY.md 远端备份推送（2026-10-30 P1 挂靠） ----
# 为什么挂这里而不是独立 launchd/cron：2026-10-30 实测，新装载的 launchd 任务与
# cron 上下文都被 macOS TCC 静默拒访 /Volumes/ZHITAI（open/getcwd 全 EPERM，
# 见 .learnings/ 20261030-tcc-eperm-zhitai.md），只有**本任务既有的放行上下文**
# 能读写外置卷。push 独立于记忆写入路径，失败只告警不阻塞。
MEMPUSH="$HOME/.local/bin/wb-memory-push.sh"
if [ -f "$MEMPUSH" ]; then
  bash "$MEMPUSH" >/dev/null 2>&1 || log "memory-push 异常（退出码 $?，详见 ~/Library/Logs/wb-memory-push.log）"
fi
