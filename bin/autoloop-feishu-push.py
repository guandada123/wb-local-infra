#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
"""
中台巡检日报 → 飞书主群推送（Q-12 落地件，2026-11-11）

职责：读当日 output/inspection-daily/<date>.md，推送到主群（盘面信息）。
- 幂等：当日已推送（state 文件存在且内容 hash 一致）则静默退出 rc=0
- 产物未生成：rc=0 退出（留给下一次 launchd 日程重试），不告警（告警由巡检链路自己负责）
- 凭据：~/.agent-autoloop/feishu.json（独立应用，不复用 WorkBuddy 连接器）

用法：
  autoloop-feishu-push.py              # 推今天的日报
  autoloop-feishu-push.py --date 2026-11-11
  autoloop-feishu-push.py --text "任意文本"   # 自检/手动
  autoloop-feishu-push.py --text "..." --post  # 报告类：渲染成 post 富文本（表格转列表）
  autoloop-feishu-push.py --force      # 忽略幂等重推

退出码：0=成功或幂等跳过｜1=配置/凭据错｜2=发送失败
"""

import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from feishu_post import post_content  # noqa: E402

CONF = Path.home() / ".agent-autoloop" / "feishu.json"
STATE_DIR = Path.home() / ".agent-autoloop" / "feishu-push-state"
REPORT_DIR = Path("/Users/guan/WorkBuddy/Claw/output/inspection-daily")
API_BASE = "https://open.feishu.cn/open-apis"
SEND_ATTEMPTS = 3
REQUEST_TIMEOUT = 30


def load_conf():
    if not CONF.exists():
        print(f"[ERR] 配置不存在: {CONF}", file=sys.stderr)
        sys.exit(1)
    return json.loads(CONF.read_text())


def get_token(conf):
    req = urllib.request.Request(
        f"{API_BASE}/auth/v3/tenant_access_token/internal",
        data=json.dumps(
            {"app_id": conf["app_id"], "app_secret": conf["app_secret"]}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if d.get("code") != 0 or not d.get("tenant_access_token"):
        print(f"[ERR] token 获取失败: {d}", file=sys.stderr)
        sys.exit(1)
    return d["tenant_access_token"]


def _connect_only(e) -> bool:
    """这次失败是否发生在「消息肯定没送到」的阶段。

    连接被拒/域名解析失败/连接被重置 —— 请求没到服务端，重试安全。
    读超时**不算**：服务端可能已经把消息发出去了，只是响应没回来，重试会造成重复投递。
    """
    if isinstance(e, (ConnectionError, socket.gaierror)):
        return True
    if isinstance(e, urllib.error.URLError):
        return isinstance(getattr(e, "reason", None), (ConnectionError, socket.gaierror))
    return False


def _post(payload, token):
    """发一次请求；只在连接阶段失败时重试。

    2026-11-26：11-20 的日报曾因一次 TimeoutError 永久静默 —— 见 mark_pushed 的注释。
    重试只覆盖「连接失败」，读超时直接失败退出，由日程的第二个时点（18:40 / 19:20，幂等）兜底，
    这样既不会丢一天，也不会因为重试在群里出现两条相同的日报。
    """
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for attempt in range(1, SEND_ATTEMPTS + 1):
        req = urllib.request.Request(
            f"{API_BASE}/im/v1/messages?receive_id_type=chat_id", data=body, headers=headers
        )
        try:
            return json.loads(urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT).read())
        except (OSError, urllib.error.URLError) as e:
            if not _connect_only(e) or attempt == SEND_ATTEMPTS:
                raise
            wait = 2 * attempt
            print(
                f"[WARN] 连接失败（第 {attempt}/{SEND_ATTEMPTS} 次）: {type(e).__name__}: {e}；{wait}s 后重试",
                file=sys.stderr,
            )
            time.sleep(wait)


def send(token, conf, text, post=False):
    """post 模式发富文本；飞书拒收时自动降级纯文本，保证消息不丢。"""
    payload = {
        "receive_id": conf["chat_id"],
        "msg_type": "post" if post else "text",
        "content": post_content(text) if post else json.dumps({"text": text}, ensure_ascii=False),
    }
    d = _post(payload, token)
    if d.get("code") != 0:
        if post:
            print(f"[WARN] post 发送失败 {d.get('code')}，降级纯文本", file=sys.stderr)
            return send(token, conf, text, post=False)
        print(f"[ERR] 发送失败: {d}", file=sys.stderr)
        sys.exit(2)
    return (d.get("data") or {}).get("message_id", "")


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def already_pushed(key, content):
    """这份内容是否已成功推送过。只读，不落账 —— 落账交给 mark_pushed。"""
    state = STATE_DIR / f"{key}.state"
    return state.exists() and state.read_text().strip() == _digest(content)


def mark_pushed(key, content):
    """推送成功之后才记账。

    2026-11-26 修复：原实现在推送前就写 state，一次 TimeoutError 之后每天都被判定
    「已推送过（内容未变）」而静默跳过 —— 11-20 的巡检日报就是这样永久漏推的。
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{key}.state").write_text(_digest(content))


def main():
    args = sys.argv[1:]
    force = "--force" in args
    if force:
        args.remove("--force")
    post = "--post" in args
    if post:
        args.remove("--post")

    conf = load_conf()

    if "--text" in args:
        text = args[args.index("--text") + 1]
        key = f"manual-{datetime.now():%Y%m%d-%H%M%S}"
        content = text
    else:
        date = (
            args[args.index("--date") + 1]
            if "--date" in args
            else datetime.now().strftime("%Y-%m-%d")
        )
        report = REPORT_DIR / f"{date}.md"
        if not report.exists():
            print(f"[SKIP] 日报尚未生成: {report}（留待下次日程重试）")
            sys.exit(0)
        content = report.read_text(encoding="utf-8")
        text = f"【自动化巡检日报 {date}】\n\n{content}\n\n—— 推送: agent-autoloop 中台（Q-12 独立应用）"
        key = f"daily-{date}"
        if not force and already_pushed(key, content):
            print(f"[SKIP] {date} 日报已推送过（内容未变）")
            sys.exit(0)

    token = get_token(conf)
    mid = send(token, conf, text, post=post)
    if key.startswith("daily-"):
        # 2026-11-26：日报曾在 18:26 被一个查不到调用方的进程推走，且它的 stdout 不落在
        # launchd 的 StandardOutPath 里。留一行审计，下次再出现能直接认出是谁。
        print(
            f"[AUDIT] key={key} ppid={os.getppid()} cwd={os.getcwd()} argv={' '.join(sys.argv)}",
            flush=True,
        )
        mark_pushed(key, content)
    print(f"[OK] 已推送 -> {conf.get('chat_name')} | "
          f"msg_type={'post' if post else 'text'} | message_id={mid} | key={key}")


if __name__ == "__main__":
    main()
