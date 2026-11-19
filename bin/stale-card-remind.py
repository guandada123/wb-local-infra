#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
"""
挂起决策卡补推（2026-11-18，对标 Super Agent「检查点卡住 30 分钟补推」实践）

痛点：中台 hub.db 里 state='open' 的决策卡（如「要不要补跑」）等用户拍板，
     若用户没打开工作台，没有任何机制再提醒 —— 卡片可能无限期沉没。
方案：独立只读巡检，open 卡等待超过阈值（默认 6h）→ 推一条紧凑简报到飞书主群。
铁律：只读 hub.db，绝不写库（状态由内核事件现算，外部写入会破坏一致性）。

幂等：每张卡每自然日最多提醒一次（state 文件计数）。
静默：23:00–08:30 不打扰（发不出去的窗口直接跳过，下一小时再查）。

用法：
  stale-card-remind.py             # 正常巡检（launchd 每小时）
  stale-card-remind.py --dry-run   # 只打印将发送的内容，不真发
  stale-card-remind.py --self-test # 内置样例自检，不碰库不发送
  stale-card-remind.py --force     # 忽略幂等重推

退出码：0=成功或正常跳过｜1=配置错｜2=发送失败
"""

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HUB_DB = Path.home() / ".agent-autoloop" / "hub.db"
PUSH_SCRIPT = Path.home() / ".local/bin/autoloop-feishu-push.py"
STATE_DIR = Path.home() / ".agent-autoloop" / "feishu-push-state"
LOG_FILE = Path.home() / ".agent-autoloop" / "logs" / "stale-card-remind.log"

THRESHOLD_HOURS = 1          # open 卡等待多久开始提醒（2026-11-18 用户裁定：6h→1h）
QUIET_START = 23             # 静默时段起点（小时）
QUIET_END = 8.5              # 静默时段终点（08:30）


def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass  # 日志失败不影响主流程


def parse_card_time(raw: str):
    """hub.db 的 created_at 是 ISO 字符串（如 2026-11-17T16:53:11.700Z）。"""
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def is_quiet_hour(now: datetime) -> bool:
    h = now.hour + now.minute / 60.0
    return h >= QUIET_START or h < QUIET_END


def fetch_open_cards(db_path: Path):
    """只读查询 open 卡。返回 [(id, title, created_at_iso), ...]"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT json_extract(data,'$.id'),"
            " json_extract(data,'$.title'),"
            " json_extract(data,'$.created_at')"
            " FROM projections"
            " WHERE collection='cards'"
            " AND json_extract(data,'$.state')='open'"
            " AND json_extract(data,'$.closed_at') IS NULL"
            " AND COALESCE(json_extract(data,'$.quiet'),0) != 1"
            " AND COALESCE(json_extract(data,'$.fyi'),0) != 1"
        ).fetchall()
    finally:
        conn.close()
    return rows


def build_brief(cards) -> str:
    """把超时卡压成一条可决策简报：你读的是简报，不是草稿。"""
    now = datetime.now(timezone.utc)
    lines = [f"【待拍板提醒】有 {len(cards)} 张决策卡已等待超过 {THRESHOLD_HOURS} 小时："]
    for cid, title, created in cards:
        age = now - parse_card_time(created)
        hours = int(age.total_seconds() // 3600)
        lines.append(f"• #{cid} {title}（已等 {hours} 小时，{parse_card_time(created).astimezone():%m-%d %H:%M} 起）")
    lines.append("—— 到工作台中台拍板；此提醒每卡每天最多一次。")
    return "\n".join(lines)


def reminded_today(card_id, now: datetime) -> bool:
    """幂等账本：每卡每自然日一次。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    key = f"stalecard-{card_id}-{now:%Y%m%d}"
    state = STATE_DIR / f"{key}.state"
    if state.exists():
        return True
    state.write_text(now.strftime("%H:%M:%S"))
    return False


def load_push_module():
    """复用 autoloop-feishu-push.py 的 load_conf/get_token/send，单一真源不复制。"""
    spec = importlib.util.spec_from_file_location("feishu_push", PUSH_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def self_test() -> bool:
    """内置样例验证：时间解析/阈值过滤/静默判断/简报构造。"""
    ok = True

    t = parse_card_time("2026-11-17T16:53:11.700Z")
    assert t.year == 2026 and t.month == 11 and t.hour == 16, "ISO 解析失败"

    now = datetime(2026, 11, 18, 4, 0, tzinfo=timezone.utc)  # 北京时间 12:00
    cards = [
        ("26", "11-17 被截断的自动化里，影响明天开盘的 5 项要不要补跑", "2026-11-17T16:53:11.700Z"),
    ]
    brief = build_brief(cards)
    assert "1 张决策卡" in brief and "#26" in brief and "已等" in brief, "简报构造失败"

    assert is_quiet_hour(datetime(2026, 11, 18, 23, 30)), "23:30 应为静默"
    assert is_quiet_hour(datetime(2026, 11, 18, 8, 0)), "08:00 应为静默"
    assert not is_quiet_hour(datetime(2026, 11, 18, 12, 0)), "12:00 不应静默"
    assert not is_quiet_hour(datetime(2026, 11, 18, 22, 59)), "22:59 不应静默"

    # 阈值过滤逻辑
    age = now - parse_card_time(cards[0][2])
    assert age > timedelta(hours=THRESHOLD_HOURS), "阈值判断失败"
    young = now - datetime(2026, 11, 18, 3, 40, tzinfo=timezone.utc)  # 20 分钟前，未超阈值
    assert young < timedelta(hours=THRESHOLD_HOURS), "新卡不应触发"
    print("[SELF-TEST] 5/5 通过（ISO解析/简报构造/静默4例/阈值2向）")
    return ok


def main() -> None:
    args = sys.argv[1:]
    if "--self-test" in args:
        sys.exit(0 if self_test() else 1)

    dry = "--dry-run" in args
    force = "--force" in args
    now = datetime.now(timezone.utc)

    if not HUB_DB.exists():
        log(f"[SKIP] hub.db 不存在: {HUB_DB}")
        sys.exit(0)
    if is_quiet_hour(now.astimezone()):
        log("[SKIP] 静默时段（23:00-08:30），不打扰")
        sys.exit(0)

    all_open = fetch_open_cards(HUB_DB)
    stale = []
    for cid, title, created in all_open:
        try:
            if now - parse_card_time(created) >= timedelta(hours=THRESHOLD_HOURS):
                stale.append((cid, title, created))
        except (ValueError, TypeError):
            log(f"[WARN] 卡 {cid} 时间解析失败: {created!r}")

    if not stale:
        log(f"[OK] open 卡 {len(all_open)} 张，无超时项，无需提醒")
        sys.exit(0)

    if dry:
        # dry-run 不消费幂等账本（否则真发会被跳过）
        text = build_brief(stale)
        print(text)
        log(f"[DRY-RUN] 将提醒 {len(stale)} 张卡，未发送")
        sys.exit(0)

    to_send = [c for c in stale if force or not reminded_today(c[0], now.astimezone())]
    if not to_send:
        log(f"[SKIP] {len(stale)} 张超时卡今日已提醒过（幂等）")
        sys.exit(0)

    text = build_brief(to_send)
    log(f"[SEND] 真发 {len(to_send)} 张卡: ids={[c[0] for c in to_send]}")

    push = load_push_module()
    conf = push.load_conf()
    token = push.get_token(conf)
    push.send(token, conf, text)
    log(f"[OK] 已补推 {len(to_send)} 张挂起卡: ids={[c[0] for c in to_send]}")


if __name__ == "__main__":
    main()
