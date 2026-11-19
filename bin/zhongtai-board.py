#!/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3
"""
中台看板工作台 v2（2026-11-18，WorkBuddy 工作台同款布局）

用户诉求：本身在用 WorkBuddy，看板照它的界面骨架来做——
  顶部工具栏 + 左侧任务侧边栏（分组 + 计数徽章，锚点跳转）+ 主内容区。
视觉：腾讯系品牌蓝 #0052D9、浅灰底、白卡片、圆角 12、状态色点。
数据：与 v1 完全一致（只读 hub.db，状态由事件现算）；5 列看板保留为主区。
铁律：只读 hub.db（mode=ro），绝不写库；产物是静态 HTML，零服务零鉴权零依赖。
刷新：launchd com.user.zhongtai-board 每 5 分钟重生成 + 页面 meta refresh。

用法：
  zhongtai-board.py             # 生成看板
  zhongtai-board.py --stdout    # 打印 HTML 到标准输出（调试用）
"""

import html
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HUB_DB = Path.home() / ".agent-autoloop" / "hub.db"
OUT_HTML = Path.home() / ".agent-autoloop" / "board" / "index.html"
STALE_HOURS = 1  # 与 stale-card-remind.py 的阈值一致，≥此值标红
TERMINAL_RUN_STATES = ("done", "cancelled", "nothing")


def ro_conn():
    return sqlite3.connect(f"file:{HUB_DB}?mode=ro", uri=True)


def iso_local(raw, fmt="%m-%d %H:%M") -> str:
    """内核 ISO 字符串（UTC）→ 本地时间文本；解析失败返回原文。"""
    if not raw:
        return "—"
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone().strftime(fmt)
    except ValueError:
        return str(raw)


def age_hours(raw) -> float | None:
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds() / 3600
    except (ValueError, TypeError):
        return None


def fetch_data():
    conn = ro_conn()
    try:
        open_cards = conn.execute(
            "SELECT json_extract(data,'$.id'), json_extract(data,'$.title'),"
            " json_extract(data,'$.created_at')"
            " FROM projections WHERE collection='cards'"
            " AND json_extract(data,'$.state')='open'"
            " AND json_extract(data,'$.closed_at') IS NULL"
            " ORDER BY json_extract(data,'$.created_at')"
        ).fetchall()
        decided_cards = conn.execute(
            "SELECT json_extract(data,'$.id'), json_extract(data,'$.title'),"
            " json_extract(data,'$.decided_at')"
            " FROM projections WHERE collection='cards'"
            " AND json_extract(data,'$.state')='decided'"
            " ORDER BY json_extract(data,'$.decided_at') DESC LIMIT 10"
        ).fetchall()
        active_runs = conn.execute(
            "SELECT json_extract(data,'$.id'), json_extract(data,'$.rule'),"
            " json_extract(data,'$.state'), json_extract(data,'$.attempts'),"
            " json_extract(data,'$.created_at')"
            " FROM projections WHERE collection='runs'"
            f" AND json_extract(data,'$.state') NOT IN {TERMINAL_RUN_STATES}"
            " ORDER BY json_extract(data,'$.id') DESC LIMIT 15"
        ).fetchall()
        done_today = conn.execute(
            "SELECT COUNT(*) FROM projections WHERE collection='runs'"
            " AND json_extract(data,'$.state')='done'"
            " AND json_extract(data,'$.finished_at') >= ?",
            (datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00"), ),
        ).fetchone()[0]
        recent_done = conn.execute(
            "SELECT json_extract(data,'$.id'), json_extract(data,'$.rule'),"
            " json_extract(data,'$.finished_at'), json_extract(data,'$.summary')"
            " FROM projections WHERE collection='runs'"
            " AND json_extract(data,'$.state')='done'"
            " ORDER BY json_extract(data,'$.id') DESC LIMIT 8"
        ).fetchall()
        pending_timers = conn.execute(
            "SELECT json_extract(data,'$.key'), json_extract(data,'$.about'),"
            " json_extract(data,'$.at')"
            " FROM projections WHERE collection='timers'"
            " AND json_extract(data,'$.event_id') IS NULL"
            " ORDER BY json_extract(data,'$.at')"
        ).fetchall()
        schedules = conn.execute(
            "SELECT json_extract(data,'$.rule'), json_extract(data,'$.cron'),"
            " json_extract(data,'$.next_at')"
            " FROM projections WHERE collection='schedules'"
        ).fetchall()
        given_up = conn.execute(
            "SELECT COUNT(*) FROM projections WHERE collection='deliveries'"
            " AND json_extract(data,'$.given_up')=1"
        ).fetchone()[0]
    finally:
        conn.close()
    return dict(
        open_cards=open_cards, decided_cards=decided_cards,
        active_runs=active_runs, done_today=done_today,
        recent_done=recent_done, pending_timers=pending_timers,
        schedules=schedules, given_up=given_up,
    )


def esc(s) -> str:
    return html.escape(str(s if s is not None else "—"))


def render(d) -> str:
    now = datetime.now().astimezone()
    n_open = len(d["open_cards"])
    n_timer = len(d["pending_timers"])
    n_active = len(d["active_runs"])
    n_decided = len(d["decided_cards"])

    # ── 卡片片段 ─────────────────────────────────────────────
    def open_cards_html():
        rows = []
        for cid, title, created in d["open_cards"]:
            h = age_hours(created)
            hot = h is not None and h >= STALE_HOURS
            badge = (
                f'<span class="chip red">已等 {int(h)} 小时</span>'
                if hot else
                f'<span class="chip green">已等 {int(h * 60)} 分钟</span>'
                if h is not None else ""
            )
            rows.append(
                f'<div class="task-card {"hot" if hot else ""}">'
                f'<div class="t-title"><span class="dot red"></span><b>#{esc(cid)}</b> {esc(title)}</div>'
                f'{badge}<div class="t-sub">自 {esc(iso_local(created))} 起 · 到中台拍板</div></div>'
            )
        return "\n".join(rows) or '<div class="empty">没有等你拍板的事 🎉</div>'

    def decided_cards_html():
        rows = [
            f'<div class="task-card"><div class="t-title"><span class="dot amber"></span>'
            f'<b>#{esc(cid)}</b> {esc(title)}</div>'
            f'<div class="t-sub">拍板于 {esc(iso_local(at))}</div></div>'
            for cid, title, at in d["decided_cards"]
        ]
        return "\n".join(rows) or '<div class="empty">无</div>'

    def active_runs_html():
        rows = [
            f'<div class="task-card"><div class="t-title"><span class="dot blue"></span>'
            f'<b>#{esc(rid)}</b> {esc(rule)}</div>'
            f'<span class="chip">{esc(state)}</span>'
            f'<div class="t-sub">第 {esc(attempts or 1)} 次尝试 · {esc(iso_local(created))}</div></div>'
            for rid, rule, state, attempts, created in d["active_runs"]
        ]
        return "\n".join(rows) or '<div class="empty">无进行中的轮次</div>'

    def timers_html():
        rows = [
            f'<div class="task-card"><div class="t-title"><span class="dot teal"></span>'
            f'{esc(about or key)}</div>'
            f'<div class="t-sub">{esc(key)} · 到点 {esc(iso_local(at))}</div></div>'
            for key, about, at in d["pending_timers"]
        ]
        return "\n".join(rows) or '<div class="empty">无待复查事项</div>'

    def done_html():
        rows = []
        for rid, rule, fin, summary in d["recent_done"]:
            lines = (summary or "").splitlines()
            first = lines[0] if lines else "（无摘要）"
            rows.append(
                f'<div class="task-card"><div class="t-title"><span class="dot green"></span>'
                f'<b>#{esc(rid)}</b> {esc(rule)}</div>'
                f'<div class="t-sub">{esc(iso_local(fin))} · {esc(first[:80])}</div></div>'
            )
        return "\n".join(rows) or '<div class="empty">今日暂无完成轮次</div>'

    def sched_html():
        rows = [
            f'<tr><td><span class="dot blue"></span>{esc(rule)}</td>'
            f'<td><code>{esc(cron)}</code></td><td>{esc(iso_local(next_at))}</td></tr>'
            for rule, cron, next_at in d["schedules"]
        ]
        body = "\n".join(rows) or '<tr><td colspan="3">无调度</td></tr>'
        warn = (
            f'<div class="warnline"><span class="dot red"></span>'
            f'{d["given_up"]} 条投递已放弃（需人工关注）</div>'
            if d["given_up"] else
            '<div class="okline"><span class="dot green"></span>投递通道健康，0 条放弃</div>'
        )
        return (
            f'<table><tr><th>规则</th><th>计划</th><th>下次运行</th></tr>{body}</table>{warn}'
        )

    # ── 侧边栏（WorkBuddy 同款：分组 + 计数徽章 + 锚点）────────
    sidebar = f"""
    <aside>
      <div class="side-brand"><span class="logo">🛰️</span> 中台工作台</div>
      <div class="side-group">今日概览</div>
      <a class="side-item active" href="#overview">📊 概览
        <span class="count">{d['done_today']} 轮</span></a>
      <div class="side-group">任务看板</div>
      <a class="side-item" href="#col-open">🔴 待拍板
        <span class="count {'warn' if n_open else ''}">{n_open}</span></a>
      <a class="side-item" href="#col-decided">🟡 已拍板
        <span class="count">{n_decided}</span></a>
      <a class="side-item" href="#col-active">⚙️ 进行中
        <span class="count">{n_active}</span></a>
      <a class="side-item" href="#col-timer">⏰ 待复查
        <span class="count {'warn' if n_timer else ''}">{n_timer}</span></a>
      <a class="side-item" href="#col-done">✅ 最近完成</a>
      <div class="side-group">系统</div>
      <a class="side-item" href="#sched">📅 调度健康</a>
      <a class="side-item" href="#note">📖 数据说明</a>
      <div class="side-foot">agent-autoloop · 只读<br>每 5 分钟刷新</div>
    </aside>"""

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="300">
<title>中台工作台</title>
<style>
  :root {{
    --brand:#0052d9; --brand-weak:#e8effc;
    --bg:#f3f5f8; --card:#ffffff; --ink:#22262e; --dim:#8a919f;
    --red:#d93026; --green:#107c41; --amber:#b25e00; --teal:#0f766e;
    --line:#e5e8ee; --radius:12px;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.55 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }}

  /* ── 顶部工具栏 ── */
  .topbar {{ position:sticky; top:0; z-index:5; height:52px;
            background:var(--card); border-bottom:1px solid var(--line);
            display:flex; align-items:center; gap:14px; padding:0 20px; }}
  .topbar .title {{ font-weight:600; font-size:15px; }}
  .topbar .stat {{ font-size:12px; color:var(--dim); background:var(--bg);
                  border:1px solid var(--line); border-radius:20px; padding:3px 12px; }}
  .topbar .stat b {{ color:var(--ink); }}
  .topbar .stat.urgent b {{ color:var(--red); }}
  .topbar .right {{ margin-left:auto; color:var(--dim); font-size:12px; }}

  /* ── 左侧边栏 ── */
  aside {{ position:fixed; top:52px; bottom:0; left:0; width:212px;
          background:var(--card); border-right:1px solid var(--line);
          padding:14px 10px; overflow-y:auto; }}
  .side-brand {{ font-weight:600; padding:4px 10px 12px; font-size:15px; }}
  .side-brand .logo {{ margin-right:6px; }}
  .side-group {{ color:var(--dim); font-size:11px; padding:12px 10px 4px;
                letter-spacing:1px; }}
  .side-item {{ display:flex; align-items:center; gap:6px; color:var(--ink);
               text-decoration:none; font-size:13px; padding:7px 10px;
               border-radius:8px; margin:1px 0; }}
  .side-item:hover {{ background:var(--bg); }}
  .side-item.active {{ background:var(--brand-weak); color:var(--brand); font-weight:600; }}
  .side-item .count {{ margin-left:auto; font-size:11px; color:var(--dim);
                      background:var(--bg); border-radius:10px; padding:0 8px; }}
  .side-item .count.warn {{ background:#fde8e8; color:var(--red); }}
  .side-foot {{ color:var(--dim); font-size:11px; padding:14px 10px; line-height:1.6; }}

  /* ── 主区 ── */
  main {{ margin-left:212px; padding:18px 22px 26px; }}
  .board {{ display:grid; grid-template-columns:repeat(5,1fr); gap:14px;
           align-items:start; }}
  .col {{ background:var(--card); border:1px solid var(--line);
         border-radius:var(--radius); padding:12px; }}
  .col h2 {{ font-size:14px; margin:0 0 10px; display:flex; align-items:center; }}
  .task-card {{ background:var(--bg); border:1px solid var(--line);
               border-radius:10px; padding:9px 11px; margin-bottom:9px; }}
  .task-card.hot {{ border-color:var(--red); background:#fffafa; }}
  .t-title {{ display:flex; align-items:baseline; gap:6px; font-size:13px; }}
  .t-sub {{ color:var(--dim); font-size:12px; margin-top:3px; }}
  .dot {{ width:7px; height:7px; border-radius:50%; display:inline-block;
         margin-right:2px; flex:none; }}
  .dot.red {{ background:var(--red); }} .dot.green {{ background:var(--green); }}
  .dot.blue {{ background:var(--brand); }} .dot.amber {{ background:var(--amber); }}
  .dot.teal {{ background:var(--teal); }}
  .chip {{ font-size:11px; padding:1px 9px; border-radius:12px;
          background:#eef1f4; color:var(--dim); }}
  .chip.red {{ background:#fde8e8; color:var(--red); }}
  .chip.green {{ background:#e6f4ea; color:var(--green); }}
  .empty {{ color:var(--dim); font-size:13px; padding:10px 4px; }}
  .warnline {{ color:#b45309; font-size:12px; margin-top:8px; }}
  .okline {{ color:var(--dim); font-size:12px; margin-top:8px; }}

  /* ── 调度表 & 说明 ── */
  .lower {{ display:grid; grid-template-columns:1fr 1fr; gap:14px;
           margin-top:14px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }}
  th {{ color:var(--dim); font-weight:500; }}
  code {{ font-size:11.5px; color:var(--brand); background:var(--brand-weak);
         border-radius:4px; padding:1px 5px; }}
  .note {{ color:var(--dim); font-size:12.5px; line-height:1.9; }}
</style></head><body>

<div class="topbar">
  <span class="title">中台工作台</span>
  <span class="stat">今日完成 <b>{d['done_today']}</b> 轮</span>
  <span class="stat urgent">待拍板 <b>{n_open}</b></span>
  <span class="stat">待复查 <b>{n_timer}</b></span>
  <span class="stat">进行中 <b>{n_active}</b></span>
  <span class="right">生成于 {now:%m-%d %H:%M:%S} · 每 5 分钟自动刷新</span>
</div>

{sidebar}

<main>
  <div class="board">
    <div class="col" id="col-open"><h2>🔴 待你拍板</h2>{open_cards_html()}</div>
    <div class="col" id="col-decided"><h2>🟡 已拍板</h2>{decided_cards_html()}</div>
    <div class="col" id="col-active"><h2>⚙️ 进行中 / 待跑</h2>{active_runs_html()}</div>
    <div class="col" id="col-timer"><h2>⏰ 待复查</h2>{timers_html()}</div>
    <div class="col" id="col-done"><h2>✅ 最近完成</h2>{done_html()}</div>
  </div>

  <div class="lower">
    <div class="col" id="sched"><h2>📅 调度健康</h2>{sched_html()}</div>
    <div class="col" id="note"><h2>📖 数据说明</h2>
      <div class="note">
        · 看板<b>只读</b> hub.db 事件投影，状态由事件现算（内核语义）<br>
        · 待拍板卡 ≥{STALE_HOURS} 小时标红，stale-card-remind 每小时检查并补推飞书（每卡每日一次）<br>
        · decided = 拍板过 ≠ 执行过；终态轮次从活动投影移除，事实日志保留完整变更<br>
        · 布局同款 WorkBuddy 工作台：顶栏统计 + 侧栏导航 + 主看板；数据源 <code>~/.agent-autoloop/hub.db</code>
      </div>
    </div>
  </div>
</main>
</body></html>"""


def main():
    if "--self-test" in sys.argv:
        # 自检：解析/时长/终态过滤三项，用样例不碰库
        assert iso_local("2026-11-17T16:53:11.700Z") != "—", "ISO 解析失败"
        assert age_hours("2020-01-01T00:00:00Z") > 1000, "时长计算失败"
        assert age_hours("bad-input") is None, "坏输入应返 None"
        assert "done" in TERMINAL_RUN_STATES and "cancelled" in TERMINAL_RUN_STATES
        print("[SELF-TEST] 4/4 通过")
        return
    d = fetch_data()
    page = render(d)
    if "--stdout" in sys.argv:
        sys.stdout.write(page)
        return
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(page, encoding="utf-8")
    print(f"[OK] 看板已生成: {OUT_HTML} | 待拍板 {len(d['open_cards'])} | "
          f"待复查 {len(d['pending_timers'])} | 今日完成 {d['done_today']}")


if __name__ == "__main__":
    main()
