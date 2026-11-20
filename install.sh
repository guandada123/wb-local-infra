#!/usr/bin/env bash
# 中台脚本部署器：仓 bin/ → ~/.local/bin（单向部署；仓为唯一源）
#
# 原则：仓是唯一源。改脚本请改仓内 bin/，然后 ./install.sh --apply 部署；
# 直接改 live 会让 tests/test_deploy_sync.py 变红（漂移即闸门）。
#
# 用法：
#   ./install.sh                     # dry-run，只列差异
#   ./install.sh --apply             # 实际部署脚本
#   ./install.sh --plists            # dry-run：按 launchd/active.txt 补装缺失 plist
#   ./install.sh --plists-apply      # 实际补装（只补缺失，绝不覆盖已有 plist）
#   DEST=/tmp/fakebin ./install.sh --apply   # 指定脚本目标目录（演练用）
#   AGENTS=/tmp/fakeagents ./install.sh --plists-apply   # 指定 plist 目标目录（演练用）
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
DEST="${DEST:-$HOME/.local/bin}"
AGENTS="${AGENTS:-$HOME/Library/LaunchAgents}"
APPLY=0
MODE=scripts
case "${1:-}" in
  --apply) APPLY=1 ;;
  --plists) MODE=plists ;;
  --plists-apply) MODE=plists; APPLY=1 ;;
  --snapshot-plists) MODE=snapshot ;;
  --snapshot-plists-apply) MODE=snapshot; APPLY=1 ;;
  "") ;;
  *) echo "未知参数: $1（支持 --apply / --plists / --plists-apply / --snapshot-plists）"; exit 2 ;;
esac

# ---- plist 快照刷新：live → 仓内 launchd/（保持 DR 基线不过期）----
# 场景：改了线上 plist（改调度/加参数）后，快照必须跟着刷新，否则 --plists 会恢复旧配置。
# 安全边界：① 只刷新 active.txt 列出的 job；② 发现 live 有而 active.txt 无的新 job → 提示补清单；
#          ③ dry-run 默认，--snapshot-plists-apply 才落盘。
if [ "$MODE" = "snapshot" ]; then
  # 护栏（2026-11-20 审计 S5b，实证触发过）：AGENTS 被改成非默认目录时禁止落盘——
  # 否则会拿临时目录内容覆盖仓内快照（反证测试时真发生过，22 个快照被写脏）。
  if [ "$APPLY" -eq 1 ] && [ "$AGENTS" != "$HOME/Library/LaunchAgents" ] && [ "${FORCE:-0}" != "1" ]; then
    echo "❌ 拒绝：AGENTS=$AGENTS 非默认目录，写盘会污染仓内快照。"
    echo "   如确实要这么做：FORCE=1 ./install.sh --snapshot-plists-apply"
    exit 3
  fi
  LIST="$REPO/launchd/active.txt"
  [ -f "$LIST" ] || { echo "缺少清单: $LIST"; exit 1; }
  listed="$(grep -v '^#' "$LIST" | sed 's/^\[deploy\] //' | tr -d ' ' | grep -v '^$')"
  changed=0; fresh=0; unlisted=0
  for n in $listed; do
    live="$AGENTS/$n"; snap="$REPO/launchd/$n"
    [ -f "$live" ] || { echo "⚠️  live 不存在（清单过期？）: $n"; continue; }
    if [ -f "$snap" ] && cmp -s "$live" "$snap"; then fresh=$((fresh+1)); continue; fi
    if [ "$APPLY" -eq 1 ]; then cp -p "$live" "$snap" && echo "✅ 刷新快照 $n"; else echo "[dry-run] 将刷新快照 $n"; fi
    changed=$((changed+1))
  done
  for f in "$AGENTS"/com.user.*.plist; do
    [ -f "$f" ] || continue; n="$(basename "$f")"
    printf '%s\n' $listed | grep -qx "$n" || { echo "⚠️  live 有但清单无（请补 active.txt）: $n"; unlisted=$((unlisted+1)); }
  done
  echo "刷新=$changed 已最新=$fresh 未登记=$unlisted"
  exit 0
fi

# ---- plist DR 模式：按 launchd/active.txt 只补缺失，不覆盖现有 ----
# 场景：换机/重装后恢复 22 个无 deploy 源的 ad-hoc launchd job。
# 安全边界：① 只处理 active.txt 列出的 job；② [deploy] 标记的归 Claw deploy 脚本管，不动；
#          ③ 目标已存在一律跳过——绝不覆盖线上 plist。
if [ "$MODE" = "plists" ]; then
  LIST="$REPO/launchd/active.txt"
  [ -f "$LIST" ] || { echo "缺少清单: $LIST"; exit 1; }
  mkdir -p "$AGENTS"
  installed=0; skipped=0; missing=0
  while IFS= read -r line; do
    case "$line" in \#*|"") continue ;; esac
    case "$line" in "[deploy] "*) continue ;; esac
    n="$(printf '%s' "$line" | tr -d ' ')"
    [ -n "$n" ] || continue
    src="$REPO/launchd/$n"; dst="$AGENTS/$n"
    if [ ! -f "$src" ]; then echo "⚠️  快照缺失: $n"; missing=$((missing+1)); continue; fi
    if [ -f "$dst" ]; then skipped=$((skipped+1)); continue; fi
    if [ "$APPLY" -eq 1 ]; then
      cp -p "$src" "$dst" && echo "✅ 补装 $n"
    else
      echo "[dry-run] 将补装 $n"
    fi
    installed=$((installed+1))
  done < "$LIST"
  echo "补装=$installed 已存在跳过=$skipped 快照缺失=$missing"
  if [ "$APPLY" -eq 0 ] && [ "$installed" -gt 0 ]; then
    echo "（dry-run；加 --plists-apply 落盘。补装后需 launchctl bootstrap 才会生效）"
  fi
  exit 0
fi

# 前置校验：python 脚本先过语法
fail=0
for f in "$REPO"/bin/*; do
  case "$f" in
    *.py) python3 -c 'import ast,sys; ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$f" 2>/dev/null || { echo "❌ 语法错误: $f"; fail=1; } ;;
  esac
done
[ "$fail" -eq 1 ] && { echo "部署中止：存在语法错误"; exit 1; }

mkdir -p "$DEST"
changed=0
for f in "$REPO"/bin/*; do
  [ -f "$f" ] || continue
  n="$(basename "$f")"
  d="$DEST/$n"
  if [ -f "$d" ] && cmp -s "$f" "$d"; then
    continue
  fi
  if [ "$APPLY" -eq 1 ]; then
    # 覆盖前备份 live 旧版到隐藏目录（不污染 PATH 目录），保留最近 5 份
    if [ -f "$d" ]; then
      BK="$HOME/.local/bin/.deploy-backups"
      mkdir -p "$BK"
      cp -p "$d" "$BK/$n.$(date +%Y%m%d-%H%M%S)"
      ls -t "$BK/$n".* 2>/dev/null | tail -n +6 | xargs -r rm -f
    fi
    cp -p "$f" "$d"
    echo "✅ 部署 $n"
  else
    echo "[dry-run] 将部署 $n"
  fi
  changed=$((changed + 1))
done

if [ "$changed" -eq 0 ]; then
  echo "无差异：$DEST 已与仓内 bin/ 一致（$(ls "$REPO"/bin | wc -l | tr -d ' ') 个脚本）"
else
  if [ "$APPLY" -eq 0 ]; then
    echo "差异 $changed 个（dry-run；加 --apply 落盘）"
  else
    echo "已部署 $changed 个 → $DEST"
  fi
fi
