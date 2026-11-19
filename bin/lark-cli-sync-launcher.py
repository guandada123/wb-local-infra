#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
"""launchd 启动器：让 lark-cli 一致性巡检继承 TCC 授权。

launchd 后台进程直接执行外置卷上的脚本会被 macOS TCC 拒绝（EPERM，
实测 2026-11-11 22:12 日志）。本文件在内盘、由已授权的 WorkBuddy python
启动，再派生 bash 子进程，子进程继承授权 —— 与
~/.local/bin/feishu-event-consumer.py 同一解法。

用法: lark-cli-sync-launcher.py "<交给 /bin/bash -lc 的命令>"
命令本体仍写在 plist 的第三个参数里，避免两处口径分叉。
"""

import subprocess
import sys


def main():
    if len(sys.argv) < 2:
        print("[ERR] 缺少待执行命令", file=sys.stderr)
        return 2
    return subprocess.run(["/bin/bash", "-lc", sys.argv[1]]).returncode


if __name__ == "__main__":
    sys.exit(main())
