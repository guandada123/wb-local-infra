#!/usr/bin/env python3
"""中台数据备份闸门（2026-11-23）。

为什么要有这个脚本
------------------
`~/.agent-autoloop/hub.db` 是整套自主系统的**唯一数据存储**（26MB：57,982 条 facts、
12,600 条 projection_refs、956 条 projections，以及密钥派生的全部运行历史与卡片账本）。
`master.key`（43 字符，签卡片链接）同样只有一份。2026-11-23 审计实测：

  · 没有任何 launchd / cron / 脚本在备份 hub.db（`backups/` 里只有 rules.json 的 .bak）；
  · `backup/` 下两份是 11-13/11-14 升级前手工快照，已过期 10 天；
  · 上一轮审计盯着 `config.json`（490B），**漏了 26MB 的 db 和 master.key** —— 盯小的、漏大的。

官方本来就带 `agent-autoloop backup/restore`（在线页拷贝 + master.key 形状校验 +
restore 前 quick_check），缺的不是工具，是**调度、异卷落点、可证伪的校验**。本脚本只补这三件，
不重写备份逻辑。

口径与红线
----------
1. **异卷**用物理设备号（`os.stat().st_dev`）判定，不看路径前缀。`~/.agent-autoloop`
   在内置盘（/dev/disk3s1s1），落点必须在外置盘（/dev/disk5s1）才算第二副本；
   同盘不同目录 = 磁盘坏了两份一起没，等于没备份。
2. **不复制凭据到更不安全的地方**：官方备份自带 config.json / master.key，落点权限强制
   0700/0600。⚠️ 外置卷 ZHITAI 未加密（FileVault=Off，卷本身也未加密），而该卷上
   `~/.workbuddy` 本就存着 mcp 凭据 —— 这是既有暴露面，不是本脚本引入的；单一修复口是
   给卷/整机加密，属用户决策，脚本不假装已解决（见 `check` 的 A3 detail）。
3. **官方备份不含 `feishu.json`**（FILES = master.key/config.json/rules.json/secrets.env），
   那是飞书推送凭据，丢了要进控制台重置。本脚本额外补拷，缺失即红（A8）。
4. 行数只做**方向校验**（备份不得多于 live）+ 非空校验；不做相等断言 —— live 在跑，
   相等是假要求，会把正常备份判红。

用法
----
  wb-autoloop-backup.py backup            # 打一份到外置卷 + 补拷 + 校验 + 轮转（保留 8 份）
  wb-autoloop-backup.py check [--json] [--all]
  wb-autoloop-backup.py drill             # 真恢复到临时 AGENT_AUTOLOOP_HOME 并逐表比对
  wb-autoloop-backup.py daily             # launchd 入口：备份→校验→出问题才推飞书
  wb-autoloop-backup.py self-test         # 12 项故障注入（每项必须精确变红）

退出码：0=全部 PASS｜1=有 FAIL｜2=环境/参数错误
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

HOME_DIR = Path(os.path.expanduser(os.environ.get("AGENT_AUTOLOOP_HOME") or "~/.agent-autoloop"))
DEFAULT_VAULT = os.environ.get("WB_VAULT") or "/Volumes/ZHITAI/backups/agent-autoloop"
MAX_AGE_H = 26.0      # 每日一次，留 2h 抖动余量
KEEP = 8              # 保留份数上限（8×27MB ≈ 216MB）
EXTRA_FILES = ["feishu.json"]   # 官方备份不覆盖、但丢了要重置的
KEY_SHAPE_LEN = 43
TS_FMT = "%Y-%m-%dT%H%M"


# ---------------------------------------------------------------- 基础工具
def _log(msg: str) -> None:
    print(msg, flush=True)


def node_bin_dir() -> str | None:
    """launchd 的 PATH 只有 /usr/bin:/bin:/usr/sbin:/sbin，没有 node。

    `~/.local/bin/agent-autoloop` 是 `#!/usr/bin/env -S node ...`，找不到 node 就 127。
    node 目录带版本号（22.22.2-6），升级 WorkBuddy 会变 → 必须 glob，不能写死。
    """
    root = Path.home() / ".workbuddy" / "binaries" / "node" / "versions"
    cands = sorted(root.glob("*/bin/node"), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in cands:
        if os.access(c, os.X_OK):
            return str(c.parent)
    return None


def run_cli(args: list[str], timeout: int = 300) -> tuple[int, str]:
    """调 agent-autoloop；显式补 PATH，避免 launchd 下 127。"""
    env = dict(os.environ)
    nd = node_bin_dir()
    if nd:
        env["PATH"] = nd + ":" + env.get("PATH", "/usr/bin:/bin")
    cli = shutil.which("agent-autoloop", path=env["PATH"]) or str(Path.home() / ".local/bin/agent-autoloop")
    p = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def device_of(p: Path) -> int | None:
    """取最近一个存在的祖先的 st_dev —— 按物理卷取证，不看路径前缀。"""
    p = p.resolve()
    for cur in [p, *p.parents]:
        try:
            return os.stat(cur).st_dev
        except OSError:
            continue
    return None


def db_counts(db: Path, read_only: bool) -> tuple[int, dict[str, int]]:
    """返回 (表数, {表名: 行数})。read_only 用 mode=ro，绝不写 live。"""
    if read_only:
        uri = "file:" + urllib.parse.quote(str(db)) + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
    else:
        conn = sqlite3.connect(str(db), timeout=10)
    try:
        tabs = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        out: dict[str, int] = {}
        for t in tabs:
            try:
                out[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error:
                out[t] = -1
        return len(tabs), out
    finally:
        conn.close()


def quick_check(db: Path) -> tuple[bool, str]:
    """官方同款：不用 integrity_check（要 hub 自建函数），用 quick_check + 表数>0。

    空文件也能过 quick_check（SQLite 视作「没有表」的库），所以表数必须一起看。
    """
    try:
        conn = sqlite3.connect(str(db), timeout=10)
        try:
            res = conn.execute("PRAGMA quick_check").fetchone()
            n = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as e:
        return False, f"打不开：{e}"
    ok = (res is not None and str(res[0]).lower() == "ok" and n > 0)
    return ok, f"quick_check={res[0] if res else 'None'} 表数={n}"


# ---------------------------------------------------------------- 单份校验
def check_snapshot(snap: Path, live_home: Path, vault: Path, max_age_h: float = MAX_AGE_H,
                   dev_fn=None) -> list[dict]:
    """对一份快照跑 A1–A8。返回 [{id, level, msg}]，level ∈ PASS/FAIL/WARN。

    dev_fn 只为自检注入（临时目录里源与落点必然同卷，无法真造两个物理卷）；
    生产路径永远用 device_of。
    """
    dev_fn = dev_fn or device_of
    items: list[dict] = []

    def add(i: str, ok: bool, msg: str, level_if_bad: str = "FAIL") -> None:
        items.append({"id": i, "level": "PASS" if ok else level_if_bad, "msg": msg})

    # A1 快照存在
    exists = snap.is_dir() and (snap / "hub.db").exists()
    add("A1", exists, f"{snap.name} / hub.db {'在' if exists else '缺失'}")
    if not exists:
        return items

    # A2 新鲜度
    age_h = (time.time() - (snap / "hub.db").stat().st_mtime) / 3600
    add("A2", age_h <= max_age_h, f"距今 {age_h:.1f}h（上限 {max_age_h}h）")

    # A3 异卷（按 st_dev）
    d_src, d_dst = dev_fn(live_home), dev_fn(snap)
    off = d_src is not None and d_dst is not None and d_src != d_dst
    add("A3", off,
        f"源 st_dev={d_src} 落点 st_dev={d_dst}"
        + ("" if off else " → 同物理卷，磁盘坏了两份一起没；"
                            "注意落点卷若未加密（FileVault Off），凭据明文落盘属既有暴露面"))

    # A4 完整性
    ok4, msg4 = quick_check(snap / "hub.db")
    add("A4", ok4, msg4)

    # A5 非空（核心表有数据；空库/截断库在此被抓）
    facts = 0
    if ok4:
        _, cnt = db_counts(snap / "hub.db", read_only=False)
        facts = cnt.get("facts", 0)
    add("A5", facts > 0, f"facts 行数={facts}")

    # A6 主密钥形状（43 字符 base64url；官方 restore 也校验这一条）
    kp = snap / "master.key"
    kl = kp.read_text().strip() if kp.exists() else ""
    add("A6", len(kl) == KEY_SHAPE_LEN, f"master.key 长度={len(kl)}（要求 {KEY_SHAPE_LEN}）")

    # A7 权限（目录 0700、文件不含 group/other 位）
    bad_perm = []
    if snap.stat().st_mode & 0o077:
        bad_perm.append(f"{snap.name}={oct(snap.stat().st_mode & 0o777)}")
    for f in sorted(snap.iterdir()):
        if f.is_file() and (f.stat().st_mode & 0o077):
            bad_perm.append(f"{f.name}={oct(f.stat().st_mode & 0o777)}")
    add("A7", not bad_perm, "全部 0600/0700" if not bad_perm else "过宽：" + ", ".join(bad_perm))

    # A11 不得带不可变标志 —— 2026-11-23 实测：feishu.json 源文件带 uchg，
    # shutil.copy2 会把 st_flags 一起复制过去，备份里那份从此 chmod EPERM、
    # 轮转时 rmtree 也删不掉（备份仓变成只增不减）。这条必须先于轮转被抓到。
    FLAG_NAMES = {0x2: "uchg", 0x4: "uappnd", 0x20000: "restricted", 0x80000: "schg"}
    frozen = []
    for f in sorted(snap.iterdir()):
        try:
            fl = f.stat().st_flags
        except OSError:
            continue
        hit = [n for b, n in FLAG_NAMES.items() if fl & b]
        if hit:
            frozen.append(f"{f.name}({'+'.join(hit)})")
    add("A11", not frozen,
        "无不可变标志" if not frozen
        else "带不可变标志，轮转会删不掉：" + ", ".join(frozen))

    # A8 额外文件覆盖（官方 FILES 不含 feishu.json）
    miss = [f for f in EXTRA_FILES if not (snap / f).exists()]
    add("A8", not miss, "额外文件齐全" if not miss else f"缺 {miss}（官方备份不覆盖，丢了要重置）")

    return items


def check_live_vs_backup(snap: Path, live_home: Path) -> list[dict]:
    """A9：备份不得多于 live（防「从别处拷来的旧库冒充新备份」），并报差异供人看。"""
    live_db = live_home / "hub.db"
    items = []
    try:
        n_live, c_live = db_counts(live_db, read_only=True)
        _, c_bk = db_counts(snap / "hub.db", read_only=False)
    except sqlite3.Error as e:
        return [{"id": "A9", "level": "FAIL", "msg": f"live 库不可读：{e}"}]
    over = [f"{t}: 备份{c_bk.get(t)} > live{c_live.get(t)}" for t in c_bk if c_bk.get(t, 0) > c_live.get(t, 0)]
    tabs_missing = sorted(set(c_live) - set(c_bk))
    detail = f"live {n_live} 表 / {sum(c_live.values())} 行"
    if over or tabs_missing:
        detail += f"；异常：{over or ''}{' 缺表' + str(tabs_missing) if tabs_missing else ''}"
    return [{"id": "A9", "level": "FAIL" if (over or tabs_missing) else "PASS", "msg": detail}]


# ---------------------------------------------------------------- backup
def rotate(vault: Path, keep: int) -> list[str]:
    snaps = sorted([d for d in vault.iterdir() if d.is_dir()], key=lambda d: d.name)
    dropped = []
    for d in snaps[:-keep] if len(snaps) > keep else []:
        shutil.rmtree(d)
        dropped.append(d.name)
    return dropped


def cmd_backup(vault: Path, home: Path) -> int:
    if not (home / "hub.db").exists():
        _log(f"❌ 没装好：{home}/hub.db 不存在")
        return 2
    d_src, d_dst = device_of(home), device_of(vault)
    if d_src is not None and d_src == d_dst:
        _log(f"❌ 拒绝：落点与源同物理卷（st_dev={d_src}）→ 不是第二副本。换外置卷或改 WB_VAULT。")
        return 2

    vault.mkdir(parents=True, exist_ok=True)
    snap = vault / time.strftime(TS_FMT)
    if snap.exists():
        # 同一分钟内重跑（launchd 重试 / 手工补跑）不是故障：官方 backup 要求目标目录为空，
        # 所以不覆盖，改为复用已有快照并照常校验。2026-11-23 实测把这里当失败处理 →
        # daily 立刻推了一张假的「备份失败」卡，教训见 .learnings。
        _log(f"⚠️ {snap} 已存在（同一分钟内重跑），复用并校验，不覆盖")
    else:
        _log(f"→ 备份 {home} → {snap}")
        rc, out = run_cli(["backup", str(snap)])
        _log("  " + out.replace("\n", "\n  "))
        if rc != 0 or not (snap / "hub.db").exists():
            _log("❌ 官方 backup 失败")
            return 1

    for name in EXTRA_FILES:              # 官方不拷的，补上（不覆盖已有）
        src = home / name
        if src.exists() and not (snap / name).exists():
            # 必须 copyfile，不能 copy2：copystat 会连 st_flags 一起搬 ——
            # feishu.json 源文件带 uchg，copy2 后备份里那份立刻不可变，
            # chmod EPERM、轮转 rmtree 删不掉（备份仓只增不减）。
            shutil.copyfile(src, snap / name)
            os.chmod(snap / name, 0o600)
            _log(f"  + {name}（官方备份不覆盖；已剥掉源文件标志位）")

    items = check_snapshot(snap, home, vault) + check_live_vs_backup(snap, home)
    bad = [i for i in items if i["level"] == "FAIL"]
    for i in items:
        _log(f"  {i['level']:<4} {i['id']} {i['msg']}")
    if bad:
        _log(f"❌ 新备份未通过校验（{len(bad)} 项），已保留现场供排查，不轮转")
        return 1

    dropped = rotate(vault, KEEP)
    if dropped:
        _log(f"  轮转删除：{', '.join(dropped)}")
    _log(f"✅ 备份完成并通过 {len(items)} 项校验：{snap}")
    return 0


# ---------------------------------------------------------------- check
def cmd_check(vault: Path, home: Path, as_json: bool, check_all: bool) -> int:
    if not vault.is_dir():
        _log(f"❌ 落点不存在：{vault}")
        return 2
    snaps = sorted([d for d in vault.iterdir() if d.is_dir()], key=lambda d: d.name)
    if not snaps:
        _log(f"❌ 落点里没有任何快照：{vault}")
        return 1
    targets = snaps if check_all else snaps[-1:]

    report = []
    worst = 0
    for snap in targets:
        items = check_snapshot(snap, home, vault) + check_live_vs_backup(snap, home)
        report.append({"snapshot": snap.name, "items": items})
        worst = max(worst, 1 if any(i["level"] == "FAIL" for i in items) else 0)

    # A10 轮转份数（只对最新一份报，避免逐份重复）
    n = len(snaps)
    over = n > KEEP
    report[-1]["items"].append(
        {"id": "A10", "level": "FAIL" if over else "PASS", "msg": f"保留 {n} 份（上限 {KEEP}）"})
    if over:
        worst = 1

    if as_json:
        print(json.dumps({"vault": str(vault), "reports": report}, ensure_ascii=False, indent=2))
    else:
        for r in report:
            _log(f"── {r['snapshot']}")
            for i in r["items"]:
                _log(f"  {i['level']:<4} {i['id']} {i['msg']}")
        all_items = [i for r in report for i in r["items"]]
        p = sum(1 for i in all_items if i["level"] == "PASS")
        _log(f"\n{p}/{len(all_items)} 通过" + ("" if not worst else "  ❌ 存在 FAIL"))
    return worst


# ---------------------------------------------------------------- drill
def cmd_drill(vault: Path, home: Path) -> int:
    """真恢复演练：落到临时 AGENT_AUTOLOOP_HOME，逐表比对备份与恢复后的行数。

    不碰本机 home —— AGENT_AUTOLOOP_HOME 是官方的 HOME 覆盖口（host/home.ts:5）。
    """
    snaps = sorted([d for d in vault.iterdir() if d.is_dir()], key=lambda d: d.name)
    if not snaps:
        _log("❌ 没有可演练的快照")
        return 1
    snap = snaps[-1]
    tmp = tempfile.mkdtemp(prefix="autoloop-drill.")
    t0 = time.time()
    try:
        env = dict(os.environ, AGENT_AUTOLOOP_HOME=tmp)
        nd = node_bin_dir()
        if nd:
            env["PATH"] = nd + ":" + env.get("PATH", "/usr/bin:/bin")
        cli = shutil.which("agent-autoloop", path=env["PATH"]) or str(Path.home() / ".local/bin/agent-autoloop")
        p = subprocess.run([cli, "restore", str(snap), "--yes"],
                           capture_output=True, text=True, timeout=300, env=env)
        secs = time.time() - t0
        if p.returncode != 0 or not (Path(tmp) / "hub.db").exists():
            _log(f"❌ 恢复失败 rc={p.returncode}\n{(p.stdout + p.stderr).strip()}")
            return 1
        n_bk, c_bk = db_counts(snap / "hub.db", read_only=False)
        n_dr, c_dr = db_counts(Path(tmp) / "hub.db", read_only=False)
        diff = [f"{t}: 备份{c_bk.get(t)} vs 恢复{c_dr.get(t)}" for t in sorted(set(c_bk) | set(c_dr))
                if c_bk.get(t) != c_dr.get(t)]
        key_ok = len((Path(tmp) / "master.key").read_text().strip()) == KEY_SHAPE_LEN
        _log(f"演练快照 {snap.name}｜恢复耗时 {secs:.1f}s")
        _log(f"  表数 备份={n_bk} 恢复={n_dr}")
        _log(f"  逐表行数{'一致' if not diff else '不一致：' + str(diff)}")
        _log(f"  master.key 形状{'正常' if key_ok else '异常'}")
        ok = not diff and n_bk > 0 and n_dr == n_bk and key_ok
        _log("✅ 演练通过：备份可完整还原" if ok else "❌ 演练失败")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- self-test
def _fake_snapshot(root: Path, rows: int = 5, tables: int = 2) -> Path:
    snap = root / "vault" / time.strftime(TS_FMT)
    snap.mkdir(parents=True)
    os.chmod(snap.parent, 0o700)
    os.chmod(snap, 0o700)
    conn = sqlite3.connect(str(snap / "hub.db"))
    conn.execute("CREATE TABLE facts(x INTEGER)")
    for _ in range(rows):
        conn.execute("INSERT INTO facts VALUES(1)")
    if tables > 1:
        conn.execute("CREATE TABLE projection_refs(x INTEGER)")
    conn.commit()
    conn.close()
    (snap / "master.key").write_text("A" * 43)
    (snap / "config.json").write_text("{}")
    (snap / "rules.json").write_text("{}")
    (snap / "feishu.json").write_text("{}")
    for f in snap.iterdir():
        os.chmod(f, 0o600)
    return snap


def cmd_self_test() -> int:
    """12 项故障注入：每项只破坏一个维度，断言**恰好那一项**变红。

    「全绿」不足以证明闸门有效（见项目纪律：用例须被反证过才算覆盖）。
    """
    cases: list[tuple[str, str, callable]] = []

    def make_live(root: Path) -> Path:
        home = root / "home"
        home.mkdir()
        conn = sqlite3.connect(str(home / "hub.db"))
        conn.execute("CREATE TABLE facts(x INTEGER)")
        for _ in range(50):
            conn.execute("INSERT INTO facts VALUES(1)")
        conn.execute("CREATE TABLE projection_refs(x INTEGER)")
        conn.commit()
        conn.close()
        return home

    def reds(root: Path, dev_fn=None) -> list[str]:
        snap = next((root / "vault").iterdir())
        items = (check_snapshot(snap, root / "home", root / "vault", dev_fn=dev_fn)
                 + check_live_vs_backup(snap, root / "home"))
        return sorted(i["id"] for i in items if i["level"] == "FAIL")

    # 临时目录里源与落点同卷，用「路径含 vault 即另一设备」的假 dev_fn 模拟异卷；
    # 只有「同物理卷」那一例故意给恒定值，用来反证 A3 真会红。
    split_dev = lambda p: 2 if "/vault" in str(p) else 1
    same_dev = lambda p: 1

    def case_ok(root: Path):
        _fake_snapshot(root); make_live(root)
        return reds(root, split_dev)

    def case_missing_key(root: Path):
        s = _fake_snapshot(root); make_live(root); (s / "master.key").unlink()
        return reds(root, split_dev)

    def case_bad_key(root: Path):
        s = _fake_snapshot(root); make_live(root); (s / "master.key").write_text("too-short")
        return reds(root, split_dev)

    def case_empty_db(root: Path):
        s = _fake_snapshot(root); make_live(root); (s / "hub.db").write_bytes(b"")
        return reds(root, split_dev)

    def case_no_tables(root: Path):
        s = _fake_snapshot(root); make_live(root)
        (s / "hub.db").unlink(); sqlite3.connect(str(s / "hub.db")).close()
        os.chmod(s / "hub.db", 0o600)      # 只坏「有无表」，不叠加权限维度
        return reds(root, split_dev)

    def case_stale(root: Path):
        s = _fake_snapshot(root); make_live(root)
        old = time.time() - 100 * 3600
        os.utime(s / "hub.db", (old, old))
        return reds(root, split_dev)

    def case_same_volume(root: Path):
        s = _fake_snapshot(root); make_live(root)
        items = check_snapshot(s, root / "home", root / "vault", dev_fn=same_dev)
        return sorted(i["id"] for i in items if i["level"] == "FAIL")

    def case_perm(root: Path):
        s = _fake_snapshot(root); make_live(root); os.chmod(s / "hub.db", 0o644)
        return reds(root, split_dev)

    def case_frozen(root: Path):
        # 复盘 2026-11-23：feishu.json 带 uchg，copy2 把标志一起搬进备份
        s = _fake_snapshot(root); make_live(root)
        t = s / "feishu.json"
        os.chflags(t, os.stat(t).st_flags | 0x2)
        try:
            return reds(root, split_dev)
        finally:
            os.chflags(t, os.stat(t).st_flags & ~0x2)

    def case_no_extra(root: Path):
        s = _fake_snapshot(root); make_live(root); (s / "feishu.json").unlink()
        return reds(root, split_dev)

    def case_row_overflow(root: Path):
        # 备份比 live 多 → 说明不是这份 live 的备份（旧库冒充/串备份）
        s = _fake_snapshot(root, rows=500); make_live(root)
        return reds(root, split_dev)

    def case_live_unreadable(root: Path):
        _fake_snapshot(root); (root / "home").mkdir()   # 没有 live 库
        return reds(root, split_dev)

    cases = [
        ("裸绿（无破坏）", "case_ok", case_ok, []),
        ("缺 master.key", "case_missing_key", case_missing_key, ["A6"]),
        ("密钥长度错", "case_bad_key", case_bad_key, ["A6"]),
        ("hub.db 0 字节", "case_empty_db", case_empty_db, ["A4", "A5", "A9"]),
        ("空库无表", "case_no_tables", case_no_tables, ["A4", "A5", "A9"]),
        ("超过 26h", "case_stale", case_stale, ["A2"]),
        ("同物理卷", "case_same_volume", case_same_volume, ["A3"]),
        ("权限 0644", "case_perm", case_perm, ["A7"]),
        ("带 uchg 不可变", "case_frozen", case_frozen, ["A11"]),
        ("缺 feishu.json", "case_no_extra", case_no_extra, ["A8"]),
        ("备份行数多于 live", "case_row_overflow", case_row_overflow, ["A9"]),
        ("live 库不可读", "case_live_unreadable", case_live_unreadable, ["A9"]),
    ]

    fail = 0
    for title, _name, fn, expect in cases:
        with tempfile.TemporaryDirectory(prefix="wb-bk-selftest.") as td:
            got = fn(Path(td))
        ok = got == expect
        if not ok:
            fail += 1
        print(f"{'PASS' if ok else 'FAIL'}  {title:<20} 红项={got or '无'} 期望={expect or '无'}")
    print(f"\n{len(cases) - fail}/{len(cases)} 通过")
    return 0 if fail == 0 else 1


# ---------------------------------------------------------------- daily
STATE_FILE = Path(os.path.expanduser("~/.local/etc/wb-autoloop-backup.state.json"))
REMIND_DAYS = 7


def _push(text: str) -> str:
    """走既有飞书出口（autoloop-feishu-push.py --text），不新建通道。

    WB_PUSH_SCRIPT 仅供自检替换成桩，用于验证「告警真的会被调起」而不用刷群。
    """
    pusher = Path(os.environ.get("WB_PUSH_SCRIPT")
                  or (Path.home() / ".local" / "bin" / "autoloop-feishu-push.py"))
    if not pusher.exists():
        return "推送脚本不存在，未发送"
    try:
        p = subprocess.run([sys.executable, str(pusher), "--text", text],
                           capture_output=True, text=True, timeout=120)
        ok = p.returncode == 0
        return "已推送" if ok else f"推送失败 rc={p.returncode} {(p.stdout + p.stderr).strip()[:200]}"
    except Exception as e:                                    # noqa: BLE001
        return f"推送异常：{e}"


def _should_push(state: dict, ok: bool) -> tuple[bool, dict]:
    """状态变化即推；持续失败每 REMIND_DAYS 天提醒一次（否则永久红灯变噪音）。"""
    today = time.strftime("%Y-%m-%d")
    prev_ok = state.get("ok")
    last = state.get("last_push", "")
    if ok:
        if prev_ok is False:                                  # 恢复：报一次
            return True, {"ok": True, "last_push": today}
        return False, {"ok": True, "last_push": last}
    if prev_ok is not False:                                  # 首次失败
        return True, {"ok": False, "last_push": today}
    try:
        gap = (time.mktime(time.strptime(today, "%Y-%m-%d"))
               - time.mktime(time.strptime(last, "%Y-%m-%d"))) / 86400
    except Exception:                                         # noqa: BLE001
        gap = 999
    if gap >= REMIND_DAYS:
        return True, {"ok": False, "last_push": today}
    return False, {"ok": False, "last_push": last}


def cmd_daily(vault: Path, home: Path) -> int:
    """launchd 入口：备份 → 校验 → 只在出问题时推飞书。"""
    rc = cmd_backup(vault, home)
    if rc == 0:
        items = []
        snaps = sorted([d for d in vault.iterdir() if d.is_dir()], key=lambda d: d.name)
        if snaps:
            items = check_snapshot(snaps[-1], home, vault) + check_live_vs_backup(snaps[-1], home)
        fails = [i for i in items if i["level"] == "FAIL"]
        if fails:
            rc = 1
            detail = "\n".join(f"· {i['id']} {i['msg']}" for i in fails)
        else:
            detail = ""
    else:
        detail = "备份命令失败（详见 ~/Library/Logs/wb-autoloop-backup.log）"

    ok = rc == 0
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:                                     # noqa: BLE001
            state = {}
    send, new_state = _should_push(state, ok)
    if not ok and send:
        msg = ("【中台备份告警】\n"
               f"hub.db / master.key 异地备份未完成或未通过校验：\n{detail}\n"
               f"排查：python3 ~/.local/bin/wb-autoloop-backup.py check\n"
               f"落点：{vault}")
        _log("  " + _push(msg))
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(new_state, ensure_ascii=False))
    except OSError as e:
        _log(f"  ⚠️ 状态写入失败：{e}")
    _log(("✅ 每日备份通过" if ok else "❌ 每日备份失败（已按状态变化/7天节奏推送）"))
    return 0 if ok else 1


# ---------------------------------------------------------------- CLI
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="中台数据备份闸门")
    ap.add_argument("cmd", choices=["backup", "check", "drill", "daily", "self-test"])
    ap.add_argument("--vault", default=DEFAULT_VAULT)
    ap.add_argument("--home", default=str(HOME_DIR))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "self-test":
        return cmd_self_test()
    vault, home = Path(a.vault), Path(a.home)
    if a.cmd == "backup":
        return cmd_backup(vault, home)
    if a.cmd == "check":
        return cmd_check(vault, home, a.json, a.all)
    if a.cmd == "daily":
        return cmd_daily(vault, home)
    return cmd_drill(vault, home)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
