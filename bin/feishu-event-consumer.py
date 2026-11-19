#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
"""launchd 事件消费者包装器（TCC + stdin 双坑解法）。

1) TCC 按二进制授权且子进程继承：直接由 launchd 拉 node 读外置卷会 EPERM，
   改由已授权的 ~/.workbuddy/binaries python 派生。
2) lark-cli event consume 把 stdin EOF 当退出信号，而 launchd 的 stdin 是 /dev/null。
   这里用 pipe 给子进程当 stdin，父进程持有写端且不关闭，使其永不 EOF。
"""
import os
import subprocess

LARK = "/Users/guan/.workbuddy/binaries/node/cli-connector-packages/bin/lark-cli"
NODE_BIN = "/Users/guan/.workbuddy/binaries/node/versions/22.22.2-6/bin"
OUT = "/Users/guan/files/feishu-events"

env = dict(os.environ)
env["PATH"] = NODE_BIN + ":" + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")

r, w = os.pipe()
proc = subprocess.Popen(
    [LARK, "event", "consume", "im.message.receive_v1",
     "--as", "bot", "--output-dir", OUT],
    stdin=r, env=env,
)
os.close(r)  # 写端 w 留在父进程手里 → 子进程 stdin 永不 EOF
try:
    proc.wait()
finally:
    os.close(w)
    if proc.poll() is None:
        proc.terminate()
