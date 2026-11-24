#!/usr/bin/env python3
"""用 healthchecks.io API 建 check 并把 ping URL 接进 wb-autoloop-backup.conf。

安全约束（本脚本存在的理由）：
- key 只从 ~/.local/etc/.hc-key.tmp 读，成功后立刻删除；不进 argv、不进日志、不进输出
- 先读 /api/v3/checks/ 列已有 check，同名存在就复用，不重复建
  （重复建的后果不是多一个 check，是两个各自计时，一个红一个绿，看谁都不准）
- ping URL 只打印 uuid 前 8 位：完整 URL 等于打卡凭据，不该进聊天记录和日志

用法：
  hc-create-check.py list                 # 只列已有 check，不建（先看再决定）
  hc-create-check.py create [--name N] [--timeout 86400] [--grace 7200]
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://healthchecks.io/api/v3"
KEY_FILE = Path(os.path.expanduser("~/.local/etc/.hc-key.tmp"))
CONF = Path(os.path.expanduser("~/.local/etc/wb-autoloop-backup.conf"))
DEFAULT_NAME = "Autoloop 数据备份"


def read_key() -> str:
    if not KEY_FILE.is_file():
        sys.exit(f"缺少 key 文件：{KEY_FILE}")
    raw = KEY_FILE.read_text().strip()
    if len(raw) < 20:
        sys.exit(f"key 文件内容过短（{len(raw)} 字符），可能没粘全")
    return raw


def call(method: str, path: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API + path, method=method, data=data,
        headers={"X-Api-Key": key, "Content-Type": "application/json"},
    )
    last = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read()[:400].decode("utf-8", "replace")
            # 401/403 是权限问题，重试没意义
            if e.code in (401, 403):
                sys.exit(f"HTTP {e.code}：key 无效或权限不足（需 Full access key）—— {detail}")
            last = f"HTTP {e.code}: {detail}"
        except Exception as e:                                   # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if attempt < 2:
            print(f"  重试 {attempt + 1}/2：{last}")
    sys.exit(f"API 调用失败（{method} {path}）：{last}")


def uuid_of(ping_url: str) -> str:
    tail = ping_url.rstrip("/").split("/")[-1]
    # Normal: https://hc-ping.com/<uuid>；旧式带 channel 时取第一段
    return tail.split("?")[0][:8]


def cmd_list(key: str) -> int:
    data = call("GET", "/checks/", key)
    checks = data.get("checks") or []
    print(f"账号内 check 共 {len(checks)} 个：\n")
    print(f"{'name':<28}{'status':<10}{'period':>9}{'grace':>8}  {'last_ping':<20}{'uuid8':<9}")
    for c in sorted(checks, key=lambda x: x.get("name", "")):
        period = c.get("timeout") or 0
        print(f"{c.get('name',''):<28}{c.get('status',''):<10}"
              f"{(str(period // 3600) + 'h') if period else '-':>9}"
              f"{(str((c.get('grace') or 0) // 60) + 'm'):>8}  "
              f"{str(c.get('last_ping') or 'never')[:19]:<20}{uuid_of(c.get('ping_url','')):<9}")
    return 0


def cmd_create(key: str, name: str, timeout: int, grace: int) -> int:
    # 1. 先查重
    existing = [c for c in (call("GET", "/checks/", key).get("checks") or [])
                if (c.get("name") or "").strip() == name]
    if len(existing) > 1:
        sys.exit(f"同名 check 已有 {len(existing)} 个，先手工清理再建（否则各自计时互相遮蔽）")

    if existing:
        chk = existing[0]
        print(f"复用已存在 check：{name}（uuid {uuid_of(chk['ping_url'])}）")
        if chk.get("timeout") != timeout or chk.get("grace") != grace:
            print(f"  参数不符（period={chk.get('timeout')} grace={chk.get('grace')}），改为目标值")
            chk = call("POST", f"/checks/{chk['id']}", key,
                       {"name": name, "timeout": timeout, "grace": grace})
    else:
        body = {"name": name, "timeout": timeout, "grace": grace, "channels": "*"}
        try:
            chk = call("POST", "/checks/", key, body)
        except SystemExit:
            # channels="*" 在部分套餐/版本上不被接受；退化为不指定，再单独提醒去点集成
            print("  channels=\"*\" 被拒，退化为不挂集成创建")
            body.pop("channels")
            chk = call("POST", "/checks/", key, body)
            print("  ⚠️ 该 check 未挂通知集成 —— 不勾的话它红了也不会发信")
        print(f"已创建 check：{name}（uuid {uuid_of(chk['ping_url'])}）")

    ping_url = chk["ping_url"]
    # 2. 写 conf（0600，保留原有其它键）
    lines = []
    if CONF.is_file():
        lines = [ln for ln in CONF.read_text().splitlines()
                 if not ln.strip().startswith("HC_BACKUP_PING_URL=")]
    lines.append(f"HC_BACKUP_PING_URL={ping_url}")
    CONF.write_text("\n".join(lines).strip() + "\n")
    os.chmod(CONF, 0o600)
    print(f"已写入 {CONF}（0600）")

    # 3. 立刻打一发 + 回读，证明链路真通（而不是"我写了配置所以应该通"）
    from urllib.request import urlopen
    for suffix, label in (("/start", "start"), ("", "success")):
        try:
            with urlopen(ping_url + suffix, timeout=20) as r:
                print(f"  打卡 {label}: HTTP {r.status}")
        except Exception as e:                                   # noqa: BLE001
            print(f"  打卡 {label} 失败: {type(e).__name__}")
    back = call("GET", f"/checks/{chk['id']}", key)
    lp = back.get("last_ping") or "never"
    print(f"回读 last_ping={lp}  status={back.get('status')}  "
          f"period={back.get('timeout')}s grace={back.get('grace')}s")
    if lp == "never":
        sys.exit("回读仍为 never：打卡没到服务器，别信上面的配置")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    cmd, rest = args[0], args[1:]
    key = read_key()
    try:
        if cmd == "list":
            return cmd_list(key)
        if cmd == "create":
            name, timeout, grace = DEFAULT_NAME, 86400, 7200
            i = 0
            while i < len(rest):
                if rest[i] == "--name":
                    name = rest[i + 1]; i += 2
                elif rest[i] == "--timeout":
                    timeout = int(rest[i + 1]); i += 2
                elif rest[i] == "--grace":
                    grace = int(rest[i + 1]); i += 2
                else:
                    sys.exit(f"未知参数 {rest[i]}")
            return cmd_create(key, name, timeout, grace)
        sys.exit(f"未知子命令 {cmd}")
    finally:
        # 无论成败都烧掉 key：它的唯一用途已完成
        try:
            KEY_FILE.unlink()
            print("已删除临时 key 文件")
        except OSError as e:
            print(f"⚠️ key 文件删除失败：{e}")


if __name__ == "__main__":
    sys.exit(main())
