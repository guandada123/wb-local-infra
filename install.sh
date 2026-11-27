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
# ---- 参数解析（--force 可出现在任意位置；2026-11-27 加）----
# 注意：FORCE 同时是「环境变量开关」（下方闸门提示语就是 `FORCE=1 ./install.sh ...`），
# 所以默认值只能补空、不能无条件覆盖 —— 曾写 `FORCE=0` 把调用方的 FORCE=1 吃掉，
# 导致脚本自己推荐的应急用法失效（test_deploy_sync 的 force 用例翻红）。
FORCE="${FORCE:-0}"
_ARGS=()
for _a in "$@"; do
  if [ "$_a" = "--force" ]; then FORCE=1; else _ARGS+=("$_a"); fi
done
set -- ${_ARGS+"${_ARGS[@]}"}

APPLY=0
MODE=scripts
case "${1:-}" in
  --apply) APPLY=1 ;;
  --plists) MODE=plists ;;
  --plists-apply) MODE=plists; APPLY=1 ;;
  --regen-active) MODE=regen ;;
  --regen-active-apply) MODE=regen; APPLY=1 ;;
  --snapshot-plists) MODE=snapshot ;;
  --snapshot-plists-apply) MODE=snapshot; APPLY=1 ;;
  "") ;;
  *) echo "未知参数: $1（支持 --apply / --plists[-apply] / --snapshot-plists[-apply] / --regen-active[-apply]）"; exit 2 ;;
esac

# ---- active.txt 重建：live → 清单（DR 清单可重复生成，不靠一次性内联脚本）----
# 背景（审计 S6）：初版 active.txt 是内联 python 一次性产物，新 job 出现时只记 INFO 日志，
# 长期会让 DR 漏恢复。此模式把「重建清单」变成一条命令。
# 安全边界：① 只扫 com.user.*.plist；② [deploy] 依 CLAW_DEPLOY 目录自动标注；
#          ③ dry-run 打印完整内容，--regen-active-apply 落盘并先备份旧清单。
if [ "$MODE" = "regen" ]; then
  CLAW_DEPLOY="${CLAW_DEPLOY:-$HOME/WorkBuddy/Claw/.workbuddy/deploy}"
  OUT="${ACTIVE_OUT:-$REPO/launchd/active.txt}"
  if [ "$APPLY" -eq 1 ] && [ "${FORCE:-0}" != "1" ] \
     && { [ "$AGENTS" != "$HOME/Library/LaunchAgents" ] || [ "$OUT" != "$REPO/launchd/active.txt" ]; }; then
    echo "❌ 拒绝：AGENTS=$AGENTS / OUT=$OUT 非默认，写盘会覆盖仓内 active.txt。"
    echo "   如确实要这么做：FORCE=1 ./install.sh --regen-active-apply"
    exit 3
  fi
  tmp="$(mktemp)"
  {
    echo "# 当前活跃 launchd job 清单（$(date '+%F %H:%M') 由 live 重建）"
    echo "# 用途：install.sh --plists 按此清单从 launchd/ 快照恢复（DR 用），只补缺失、不覆盖已有。"
    echo "# 标注 [deploy] 的由 Claw .workbuddy/deploy 部署脚本管理，本清单不负责。"
    echo "# 换机恢复：本机用户名硬编码在 plist 内部（launchd 不支持 ~），恢复前需替换为新用户名。"
    echo "# 重建：./install.sh --regen-active[-apply]（新装/卸载 launchd job 后跑一次）"
    n_deploy=0; n_adhoc=0
    for f in "$AGENTS"/com.user.*.plist; do
      [ -f "$f" ] || continue
      name="$(basename "$f")"
      if [ -f "$CLAW_DEPLOY/$name" ]; then
        echo "[deploy] $name"; n_deploy=$((n_deploy+1))
      else
        echo "        $name"; n_adhoc=$((n_adhoc+1))
      fi
    done
  } > "$tmp"
  # 统计必须在移动/删除 tmp 之前算（踩过：先 mv 再 grep → 文件不存在，统计恒 0）
  n_d="$(grep -c '^\[deploy\]' "$tmp" || true)"; n_a="$(grep -cE '^ +com\.user' "$tmp" || true)"
  if [ "$APPLY" -eq 1 ]; then
    # 不另存 .bak：active.txt 在 git 里，历史可回溯，本地备份只会堆垃圾
    mv "$tmp" "$OUT"; echo "✅ 已重建 $OUT"
  else
    cat "$tmp"; rm -f "$tmp"
  fi
  echo "统计：deploy=${n_d:-0} ad-hoc=${n_a:-0}"
  [ "$APPLY" -eq 0 ] && echo "（dry-run，上面即为将写入的内容；加 --regen-active-apply 落盘）"
  exit 0
fi

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
  # || true：空清单时 grep -v 返回 1，set -e 会让整个脚本静默退出（rc=1 无输出）
  # [deploy] 项由 Claw .workbuddy/deploy 部署脚本管理，本清单不负责 —— 必须整行排除。
  # 2026-11-25 修：原写法 sed 's/^\[deploy\] //' 把标记剥掉后当普通项处理，
  # 与 active.txt 的注释意图、以及测试的期望（_expected_plist_names 跳过 [deploy]）都相反。
  # 后果：真实环境会与本仓重复管理同一批 plist；测试环境报一堆「live 不存在」假警告。
  listed="$(grep -v '^#' "$LIST" | grep -v '^\[deploy\]' | tr -d ' ' | grep -v '^$' || true)"
  # 反向检查（live 有但清单无）必须认全部条目，含 [deploy] —— 它们确实登记在清单里，
  # 只是由 Claw 部署脚本负责。用 listed 比对会把它们全报成「未登记」（实测 12 个假警告）。
  all_listed="$(grep -v '^#' "$LIST" | sed 's/^\[deploy\] //' | tr -d ' ' | grep -v '^$' || true)"
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
    printf '%s\n' $all_listed | grep -qx "$n" || { echo "⚠️  live 有但清单无（请补 active.txt）: $n"; unlisted=$((unlisted+1)); }
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
  installed=0; skipped=0; missing=0; invalid=0
  NEW_PLISTS=""
  while IFS= read -r line; do
    case "$line" in \#*|"") continue ;; esac
    case "$line" in "[deploy] "*) continue ;; esac
    n="$(printf '%s' "$line" | tr -d ' ')"
    [ -n "$n" ] || continue
    src="$REPO/launchd/$n"; dst="$AGENTS/$n"
    if [ ! -f "$src" ]; then echo "⚠️  快照缺失: $n"; missing=$((missing+1)); continue; fi
    # P1-3：装之前必须过 plutil —— 坏 plist 装进 LaunchAgents 会被 launchd 拒载，
    # 而且 DR 场景下用户以为已恢复，实际任务不跑（静默失效）。
    if ! plutil -lint "$src" >/dev/null 2>&1; then
      echo "❌ 快照非法（plutil 校验失败，未安装）: $n"
      invalid=$((invalid+1)); continue
    fi
    if [ -f "$dst" ]; then skipped=$((skipped+1)); continue; fi
    if [ "$APPLY" -eq 1 ]; then
      cp -p "$src" "$dst" && echo "✅ 补装 $n" && NEW_PLISTS="$NEW_PLISTS $n"
    else
      echo "[dry-run] 将补装 $n"
    fi
    installed=$((installed+1))
  done < "$LIST"
  echo "补装=$installed 已存在跳过=$skipped 快照缺失=$missing 非法跳过=$invalid"
  # P1-4：装完不等于生效，必须 bootstrap
  if [ "$APPLY" -eq 1 ] && [ -n "$NEW_PLISTS" ]; then
    echo "⚠️  以上 plist 尚未加载，执行以下命令才生效："
    for n in $NEW_PLISTS; do
      echo "  launchctl bootstrap gui/\$(id -u) \"$AGENTS/$n\""
    done
  elif [ "$APPLY" -eq 0 ] && [ "$installed" -gt 0 ]; then
    echo "（dry-run；加 --plists-apply 落盘）"
  fi
  if [ "$invalid" -gt 0 ]; then echo "⚠️  有 $invalid 个快照非法，需先修再装"; exit 1; fi
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
drift=""
for f in "$REPO"/bin/*; do
  [ -f "$f" ] || continue
  n="$(basename "$f")"
  d="$DEST/$n"
  if [ -f "$d" ] && cmp -s "$f" "$d"; then
    continue
  fi
  # 🔴 新者优先保护（2026-11-27 事故）：线上比仓内新 → 拒绝覆盖。
  # 事故经过：线上已热修（含当日新功能），仓内还是旧版；部署器直接覆盖，线上新功能
  # 被静默回退、且自检仍"绿"（旧版自检也过）。备份只是事后凭证，挡不住回退。
  # 正确动作：把线上改动提交回仓 bin/ 再部署；确需覆盖加 --force（仍会先备份）。
  if [ -f "$d" ] && [ "$d" -nt "$f" ] && [ "$FORCE" -eq 0 ]; then
    echo "🛑 拒绝覆盖 ${n}：线上比仓内新（线上 $(date -r "$d" '+%m-%d %H:%M') > 仓内 $(date -r "$f" '+%m-%d %H:%M')）"
    drift="$drift $n"
    continue
  fi
  if [ "$APPLY" -eq 1 ]; then
    # 覆盖前备份 live 旧版到隐藏目录（不污染 PATH 目录），保留最近 5 份
    if [ -f "$d" ]; then
      # 备份目录跟随 DEST（2026-11-27 修）：原写死 $HOME/.local/bin，用 DEST=/tmp/... 演练时
      # 会把测试假文件写进真实备份目录，污染取证链（实测留下一份 20261127-115737 假备份）。
      BK="$DEST/.deploy-backups"
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

if [ -n "$drift" ]; then
  _cnt="$(echo $drift | wc -w | tr -d ' ')"
  echo ""
  echo "⚠️  有 ${_cnt} 个脚本被跳过（线上比仓内新）：$drift"
  echo "   处理：把线上改动提交回仓 bin/ 并 git commit，再重新部署（仓是唯一源）；"
  echo "   应急覆盖：./install.sh --apply --force（会先备份到 .deploy-backups/）"
  exit 1
fi

if [ "$changed" -eq 0 ]; then
  # 计数必须只数普通文件：ls 会把 __pycache__ 等目录也算进去（曾显示 28 vs 实际 27）
  n_files="$(find "$REPO/bin" -maxdepth 1 -type f | wc -l | tr -d ' ')"
  echo "无差异：$DEST 已与仓内 bin/ 一致（${n_files} 个脚本）"
else
  if [ "$APPLY" -eq 0 ]; then
    echo "差异 $changed 个（dry-run；加 --apply 落盘）"
  else
    echo "已部署 $changed 个 → $DEST"
  fi
fi
