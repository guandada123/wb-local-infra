#!/bin/bash
# 工作台部署器（仓 → live 单向）
#
# 本仓是源：bin/hub-overview-server.py + share/hub-overview/index.html
# 本脚本把它们装到 live：~/.local/bin/ + ~/.local/share/hub-overview/
#
# 用法：
#   bash workbench/install-hub-overview.sh            # dry-run，只打印要做什么
#   bash workbench/install-hub-overview.sh --apply    # 落盘 + 重启服务 + 探活
#
# 与仓内 install.sh 的分工：install.sh 管 bin/ 全部脚本的有闸门批量部署，
# 本脚本只管工作台这一组（含 share/ 页面与 launchd 重启），可单独跑。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

PY="/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
PORT=3355
LABEL="com.user.hub-overview"
SRC_SERVER="$REPO/bin/hub-overview-server.py"
SRC_PAGE="$REPO/share/hub-overview/index.html"
DST_SERVER="$HOME/.local/bin/hub-overview-server.py"
DST_PAGE="$HOME/.local/share/hub-overview/index.html"

fail(){ echo "[FAIL] $*" >&2; exit 1; }

[ -f "$SRC_SERVER" ] || fail "缺 bin/hub-overview-server.py"
[ -f "$SRC_PAGE" ]   || fail "缺 share/hub-overview/index.html"

# 1) 语法自检：不通过就不部署，别把坏代码推上常驻服务
"$PY" -m py_compile "$SRC_SERVER" || fail "服务端语法错误"

# 2) 差异预演
for pair in "$SRC_SERVER:$DST_SERVER" "$SRC_PAGE:$DST_PAGE"; do
  s="${pair%%:*}"; d="${pair##*:}"
  if [ -f "$d" ] && cmp -s "$s" "$d"; then
    echo "  一致  $(basename "$d")"
  else
    echo "  待装  $(basename "$d")  ← $(basename "$(dirname "$d")")/"
  fi
done

if [ "$APPLY" -eq 0 ]; then
  echo "[dry-run] 加 --apply 才落盘。"
  exit 0
fi

# 3) 落盘
mkdir -p "$(dirname "$DST_SERVER")" "$(dirname "$DST_PAGE")"
cp -f "$SRC_SERVER" "$DST_SERVER" || fail "复制服务端失败"
cp -f "$SRC_PAGE"   "$DST_PAGE"   || fail "复制页面失败"
chmod 755 "$DST_SERVER"

# 4) 重启（launchd KeepAlive；kickstart -k 免等自动拉起）
if launchctl list | awk '{print $3}' | grep -qx "$LABEL"; then
  launchctl kickstart -k "gui/$(id -u)/$LABEL" || fail "kickstart 失败"
else
  launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$LABEL.plist" || fail "bootstrap 失败"
fi

# 5) 探活：非 200 就算失败，不报「应该可以」
code=000
for _ in 1 2 3 4 5 6 7 8; do
  sleep 1
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 5 "http://127.0.0.1:$PORT/api/hub/overview" || echo 000)
  [ "$code" = "200" ] && break
done
[ "$code" = "200" ] || fail "API 未就绪（最后一次 $code），看 ~/Library/Logs/hub-overview.err"

echo "GET /api/hub/overview → $code"
echo "🎯 部署完成：http://127.0.0.1:$PORT"
