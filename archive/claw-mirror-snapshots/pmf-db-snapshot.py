#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3.13
"""pmf 数据库任务的 launchd 入口（快照 / 演练共用）。

## 为什么需要这个包装器
脚本本身在 /Volumes/ZHITAI（外置卷）。launchd 直接跑 /bin/bash 会被 TCC 拦：
    /bin/bash: .../db-snapshot.sh: Operation not permitted
（实测日志 ~/.local/log/pmf-db-snapshot.err）

TCC 按**二进制**授权且子进程继承：WorkBuddy 自带的这个 python 已被授权访问
外置卷，由它派生出的 bash / docker 子进程同样放行。

## 用法
不传参 → 跑每日快照（db-snapshot.sh）
传参   → 跑指定脚本（如 db-restore-drill.sh，每月演练用）

## 纪律
· 用绝对路径，不依赖 cwd
· 原样透传退出码 —— 否则 launchd 无法区分成功与自检失败
· stdout/stderr 不吞，交给 launchd 重定向到日志

## 2026-11-01 补：快照必须进 Git，否则备份没闭环
实测（11-01 07:20）：03:00 快照脚本 ✅ 成功、03:30 演练 ✅ 通过，但产物一直躺在
工作区没提交 —— Git 里的最新快照还是昨天的。方案 A 的核心就是「非敏感数据进 Git
才能 diff / 回滚」，只落盘不提交等于备份没闭环（同「日志成功 ≠ 落库」）。
故在此处补自动提交：
· 只有 db-snapshot.sh 跑成功才提交；演练模式不改产物，不提交
· 只 add 三个快照文件，绝不 `git add .`
· 无变化就跳过，不制造空提交
· 提交失败 → 整体退出非零：静默失败比没有备份更危险

## 2026-11-01 再补：提交之后必须推送（异地副本）
只 commit 不 push，副本仍在同一块盘（仓库在外置卷 ZHITAI）—— 卷坏 / 机器丢，
"Git 里有快照"和"文件在本地"一样救不了。故提交后推送 origin/main：
· 推送幂等：已在远端则 git 报 Everything up-to-date，同样算成功
· 失败重试一次（网络抖动很常见），二次仍失败 → 非零退出，暴露"备份没异地"
· 实测：launchd 级最小环境（env -i，仅 PATH/HOME）下 osxkeychain 凭据可用，
  git ls-remote 成功 —— 所以后台推送不需要额外注入 token

## 2026-11-14 补：补跑必须可追溯
调用方（pmf-db-snapshot-catchup.py）注入 `PMF_SNAPSHOT_CATCHUP=1` 时，commit message
追加 `[catchup]`。两条路径原本 message 完全相同，11-08 / 11-09 各产生一对同名提交
（00:34 补跑 与 03:00 准点跑，data.sql 内容不同），事后无法分辨。

⚠️ 已知环境坑：launchd 的 PATH 里没有 ~/.local/bin，而 pre-commit 装在那里，
   钩子会直接跑不起来。钩子含 gitleaks 密钥扫描，**不能 --no-verify 跳过**，
   只能把 PATH 补全（已实测 gitleaks / php 在 /opt/homebrew/bin，可覆盖）。
"""

import os
import subprocess
import sys
import time
from datetime import datetime

REPO = "/Volumes/ZHITAI/WorkBuddy/project-monitor-fusion"
DEFAULT_SCRIPT = f"{REPO}/scripts/db-snapshot.sh"
SNAPSHOT_FILES = ["db/schema.sql", "db/data.sql", "db/last-snapshot.json"]

# 补全 PATH 让 pre-commit（~/.local/bin）在 launchd 下也能跑起来
GIT_ENV = {
    **os.environ,
    "PATH": "/Users/guan/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "/Users/guan",
}


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args], env=GIT_ENV, check=False)


def commit_snapshot():
    git("add", *SNAPSHOT_FILES)
    if git("diff", "--cached", "--quiet").returncode == 0:
        print("ℹ️ 快照无变化，跳过提交")
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    # 补跑与原任务都走这里，message 原本完全相同 —— 11-08 / 11-09 各产生一对同名
    # 提交（00:34 与 03:00，内容不同），事后无法分辨哪条是补跑。由调用方注入标记。
    tag = " [catchup]" if os.environ.get("PMF_SNAPSHOT_CATCHUP") == "1" else ""
    if git("commit", "-m", f"chore(db): 每日快照 {today}{tag}").returncode != 0:
        print(f"❌ 快照已落盘但未进 Git 历史（{today}）—— 需人工检查 pre-commit 钩子")
        return 1

    print("✅ 快照已提交进 Git，最新一条：")
    git("log", "--oneline", "-1")
    return 0


def push_snapshot():
    """把本地提交推到 origin/main。幂等：已同步时 git 返回 Everything up-to-date。"""
    r = git("push", "origin", "HEAD:main")
    if r.returncode == 0:
        print("✅ 快照已推送到 origin/main（异地副本就位）")
        return 0

    print("⚠️ 首次推送失败，3 秒后重试一次")
    time.sleep(3)
    r = git("push", "origin", "HEAD:main")
    if r.returncode == 0:
        print("✅ 重试后推送成功")
        return 0

    print("❌ 快照已提交但未推送 —— 异地副本缺失，需人工排查网络/凭据")
    return 1


if __name__ == "__main__":
    script = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SCRIPT
    rc = subprocess.run(["/bin/bash", script], check=False).returncode
    if rc != 0:
        sys.exit(rc)
    # 演练（传参）不产出提交物，只有每日快照才需要进 Git
    if script != DEFAULT_SCRIPT:
        sys.exit(0)
    rc_commit = commit_snapshot()
    # 提交失败就不推（本地历史都不干净，推上去只会污染远端）
    sys.exit(rc_commit if rc_commit != 0 else push_snapshot())
