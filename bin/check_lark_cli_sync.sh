#!/usr/bin/env bash
# check_lark_cli_sync.sh —— 对比 WorkBuddy 托管的 lark-cli 源包与本机副本是否一致
#
# 背景：飞书推送已改用本机副本 ~/.local/lib/lark-cli（不再依赖外置卷）。
#       副本是手工复制来的，WorkBuddy 升级后不会自动同步 → 需要一键对比。
#
# 对比三项（全部一致才算通过）：
#   ① 文件数     源包与副本包内常规文件数量
#   ② 总字节数   源包与副本包内常规文件字节总和
#   ③ --version  源 bin/lark-cli 与副本 bin/lark-cli 的版本输出
#
# 退出码：
#   0 一致 | 1 不一致（打印差异摘要）| 2 前置条件不满足（路径/node 缺失，无法判定）
#
# 用法：bash scripts/check_lark_cli_sync.sh; echo rc=$?
# 可覆盖路径（便于自测）：LARK_SRC_PKG / LARK_SRC_BIN / LARK_DST_PKG / LARK_DST_BIN
# 本脚本只读：不复制、不修改、不删除任何文件。

set -u

WB_DEFAULT="$HOME/.workbuddy/binaries/node/cli-connector-packages"
SRC_PKG="${LARK_SRC_PKG:-$WB_DEFAULT/lib/node_modules/@larksuite/cli}"
SRC_BIN="${LARK_SRC_BIN:-$WB_DEFAULT/bin/lark-cli}"
DST_PKG="${LARK_DST_PKG:-$HOME/.local/lib/lark-cli/@larksuite/cli}"
DST_BIN="${LARK_DST_BIN:-$HOME/.local/lib/lark-cli/bin/lark-cli}"

die_precondition() {
  echo "SKIP  前置条件不满足：$1"
  echo "      无法判定一致性，按非一致处理（rc=2）"
  exit 2
}

[ -d "$SRC_PKG" ] || die_precondition "源包目录不存在: $SRC_PKG"
[ -d "$DST_PKG" ] || die_precondition "副本包目录不存在: ${DST_PKG}（副本未安装或路径已变）"
command -v node >/dev/null 2>&1 || die_precondition "PATH 中没有 node，--version 无法执行"

count_files() { find "$1" -type f 2>/dev/null | wc -l | tr -d ' '; }

total_bytes() {
  if stat -f%z / >/dev/null 2>&1; then
    find "$1" -type f -exec stat -f%z {} + 2>/dev/null | awk '{s+=$1} END {printf "%d", s+0}'
  else
    find "$1" -type f -exec stat -c%s {} + 2>/dev/null | awk '{s+=$1} END {printf "%d", s+0}'
  fi
}

version_of() {
  local bin="$1" out
  [ -x "$bin" ] || { echo "<不可执行: $bin>"; return 0; }
  out=$("$bin" --version 2>/dev/null | tail -n 1 | tr -d '\r' | sed -e 's/[[:space:]]*$//')
  [ -n "$out" ] || out="<无输出: $bin>"
  echo "$out"
}

SRC_N=$(count_files "$SRC_PKG")
DST_N=$(count_files "$DST_PKG")
SRC_B=$(total_bytes "$SRC_PKG")
DST_B=$(total_bytes "$DST_PKG")
SRC_V=$(version_of "$SRC_BIN")
DST_V=$(version_of "$DST_BIN")

print_detail() {
  local a b extra
  a=$(mktemp) ; b=$(mktemp)
  ( cd "$SRC_PKG" && find . -type f | sort ) > "$a" 2>/dev/null
  ( cd "$DST_PKG" && find . -type f | sort ) > "$b" 2>/dev/null
  if diff -q "$a" "$b" >/dev/null 2>&1; then
    echo "      文件清单: 路径集合一致 → 差异来自文件内容/大小"
  else
    echo "      文件清单差异（'-' 仅源包，'+' 仅副本），前 20 行:"
    diff "$a" "$b" | sed -n '1,20p' | sed 's/^/        /'
    extra=$(diff "$a" "$b" | grep -c '^[<>]' || true)
    if [ "${extra:-0}" -gt 20 ]; then
      echo "        ...（其余 $((extra - 20)) 行已省略）"
    fi
  fi
  rm -f "$a" "$b"
  echo "      建议同步命令："
  echo "        ditto \"$SRC_PKG\" \"$DST_PKG\"   # 先备份再覆盖，勿删副本目录"
}

MISMATCH=0

echo "lark-cli 源包 ↔ 本机副本 一致性检查"
echo "  源包  : $SRC_PKG"
echo "  副本包: $DST_PKG"
echo ""

if [ "$SRC_N" != "$DST_N" ]; then
  echo "MISMATCH ① 文件数: 源=$SRC_N 副本=$DST_N"; MISMATCH=1
else
  echo "OK       ① 文件数: $SRC_N"
fi

if [ "$SRC_B" != "$DST_B" ]; then
  echo "MISMATCH ② 总字节: 源=$SRC_B 副本=${DST_B}（副本-源=$((DST_B - SRC_B))）"; MISMATCH=1
else
  echo "OK       ② 总字节: $SRC_B"
fi

if [ "$SRC_V" != "$DST_V" ]; then
  echo "MISMATCH ③ --version: 源=[$SRC_V] 副本=[$DST_V]"; MISMATCH=1
else
  echo "OK       ③ --version: $SRC_V"
fi

echo ""
if [ "$MISMATCH" -eq 1 ]; then
  echo "结果：不一致 —— 本机副本与 WorkBuddy 源包不同步"
  print_detail
  exit 1
fi

echo "结果：一致 —— 文件数 / 总字节 / --version 三项全部相同，副本与源包同步"
exit 0
