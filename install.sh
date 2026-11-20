#!/usr/bin/env bash
# 中台脚本部署器：仓 bin/ → ~/.local/bin（单向部署；仓为唯一源）
#
# 原则：仓是唯一源。改脚本请改仓内 bin/，然后 ./install.sh --apply 部署；
# 直接改 live 会让 tests/test_deploy_sync.py 变红（漂移即闸门）。
#
# 用法：
#   ./install.sh                 # dry-run，只列差异
#   ./install.sh --apply         # 实际部署
#   DEST=/tmp/fakebin ./install.sh --apply   # 指定目标目录（演练用）
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
DEST="${DEST:-$HOME/.local/bin}"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

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
