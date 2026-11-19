#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wb_404_watcher.py — 实时监听 edge-sync.log 新增 404 (B 链路: 事件驱动)
- 轮询最新 edge-sync.log 尾部, 出现新的 "LIST failed.*404" 立即:
    1) 生成历史会话静态快照 ~/wb_history_snapshot.html (双重兜底: 8791 服务挂了也有文件可看)
    2) 飞书告警 (含快照路径 + 8791 查看器地址)
- 每日保新: 快照超过 24h 未刷新则后台自动重生成, 保证随时可用
- 零依赖(Python stdlib), launchd KeepAlive 常驻
- 2026-08-14: 移除 Marvis Bridge 派发(用户已停用 marvis_bridge); 新增快照兜底
"""
import os, re, sys, time, subprocess, glob, datetime

HOME = os.path.expanduser("~")
LOG_DIR = os.path.join(HOME, ".workbuddy/logs")
CARD = os.path.join(HOME, "WorkBuddy/Claw/.workbuddy/scripts/push_card.py")
# 显式 python 路径: 避免 launchd 环境下 sys.executable 解析到软链真实路径
PY = "/Users/guan/.workbuddy/binaries/python/versions/3.13.12/bin/python3"
SNAPSHOT_SCRIPT = "/Users/guan/.local/bin/wb_history_snapshot.py"
SNAPSHOT_OUT = os.path.join(HOME, "wb_history_snapshot.html")
STATE = os.path.join(HOME, ".local/etc/wb_health/last404_watch")
MYLOG = os.path.join(HOME, "Library/Logs/wb_404_watcher.log")
COOLDOWN = 1800          # 30min 内不重复告警同一轮 404
SNAPSHOT_TTL = 24 * 3600 # 快照每日保新阈值
SNAPSHOT_TIMEOUT = 180   # 快照生成超时(秒)
SNAPSHOT_MIN_INTERVAL = 1800  # 404 触发时若快照 30min 内刚生成过则跳过重算(防风暴)
# 按行匹配, 不依赖 chunk 边界/conversation-sync 字样 (2026-08-15 修复: 旧条件漏报)
RE_404 = re.compile(r"§3\.2 LIST failed.*HTTP 404|LIST failed.*404")

def log(msg):
    line = f"[{datetime.datetime.now():%F %T}] {msg}"
    with open(MYLOG, "a") as f:
        f.write(line + "\n")

def latest_edge_sync_log():
    dirs = sorted(glob.glob(os.path.join(LOG_DIR, "2026-*/")), reverse=True)
    for d in dirs:
        f = os.path.join(d, "edge-sync.log")
        if os.path.exists(f):
            return f
    return None

def make_snapshot():
    """生成静态快照, 返回 (ok, info)。失败不抛异常, 仅返回 False 由调用方记日志。"""
    try:
        proc = subprocess.run(
            [PY, SNAPSHOT_SCRIPT, "--full", "150"],
            capture_output=True, text=True, timeout=SNAPSHOT_TIMEOUT)
        if proc.returncode != 0:
            return False, f"快照脚本退出码 {proc.returncode}: {(proc.stderr or proc.stdout)[-300:]}"
        if not os.path.exists(SNAPSHOT_OUT):
            return False, "快照文件未生成"
        size_mb = os.path.getsize(SNAPSHOT_OUT) / 1024 / 1024
        return True, f"{size_mb:.1f}MB · {proc.stdout.strip()}"
    except subprocess.TimeoutExpired:
        return False, f"快照生成超时({SNAPSHOT_TIMEOUT}s)"
    except Exception as e:
        return False, f"快照生成异常: {e}"

def snapshot_fresh():
    """快照是否在 MIN_INTERVAL 内刚生成(用于 404 触发节流)"""
    try:
        return (time.time() - os.path.getmtime(SNAPSHOT_OUT)) < SNAPSHOT_MIN_INTERVAL
    except Exception:
        return False

def snapshot_stale():
    """快照是否超过 TTL 未刷新"""
    try:
        return (time.time() - os.path.getmtime(SNAPSHOT_OUT)) > SNAPSHOT_TTL
    except Exception:
        return True

def push(title, sections):
    if not os.path.exists(CARD):
        return
    args = [PY, CARD, "--title", title, "--level", "warn",
            "--chat-id", "oc_9ee5303497f5e0e71666b610d6bdc346"]
    for k, v in sections:
        args += ["--section", k, v]
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log(f"告警推送失败: {e}")

def main():
    log("watcher 启动 (快照兜底已启用)")
    last_size = 0
    last_stale_check = 0
    while True:
        # ---- 每日保新: 每 10 分钟检查一次快照新鲜度 ----
        now = time.time()
        if now - last_stale_check > 600 and snapshot_stale():
            last_stale_check = now
            ok, info = make_snapshot()
            log(f"[保新] 快照过期触发重生成: {'OK ' + info if ok else 'FAIL ' + info}")

        f = latest_edge_sync_log()
        if f:
            size = os.path.getsize(f)
            if size < last_size:  # 日志轮转
                last_size = 0
            if size > last_size:
                with open(f, "rb") as fh:
                    fh.seek(last_size)
                    chunk = fh.read(size - last_size).decode("utf-8", errors="ignore")
                last_size = size
                # 按行匹配 404 (2026-08-15: 旧 chunk 三关键词逻辑漏报, 改为逐行正则)
                hit = any(RE_404.search(ln) for ln in chunk.splitlines())
                if hit:
                    last = 0
                    if os.path.exists(STATE):
                        try: last = float(open(STATE).read())
                        except Exception: pass
                    if now - last > COOLDOWN:
                        with open(STATE, "w") as sf:
                            sf.write(str(now))
                        # 1) 快照兜底: 30min 内刚生成过则跳过重算, 仅告警
                        if snapshot_fresh():
                            snap_msg = "快照 30min 内已刷新, 跳过重算"
                            log(f"!! 检测到新 404 记录 → {snap_msg}")
                        else:
                            ok, info = make_snapshot()
                            snap_msg = f"已刷新 {info}" if ok else f"刷新失败: {info}"
                            log(f"!! 检测到新 404 记录 → {snap_msg}")
                        # 2) 飞书告警
                        push("⚠️ WorkBuddy 历史列表接口 404 新出现",
                             [("检测结果", "edge-sync.log 新增 EdgeSync LIST failed 404"),
                              ("影响", "UI 侧边栏历史对话列表无法加载(数据本身在本地完好)"),
                              ("快照兜底", f"已生成静态快照 {SNAPSHOT_OUT} ({snap_msg})"),
                              ("查看方式", f"①快照文件直接打开 ②本地查看器 http://127.0.0.1:8791/"),
                              ("备注", "404 属服务端列表接口问题, 本地数据完好, 建议反馈官方")])
        time.sleep(10)

if __name__ == "__main__":
    main()
