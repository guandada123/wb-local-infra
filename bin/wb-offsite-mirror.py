#!/usr/bin/env python3
"""wb-offsite-mirror.py —— 把「只此一份、且不在任何 git 里」的数据镜像到另一块物理盘。

为什么需要它（2026-11-24）：
  `~/WorkBuddy` 与 `~/.workbuddy` 都是指向 `/Volumes/ZHITAI` 的软链 —— 也就是说**用户产生的
  全部数据都在这块便携 SSD 上**。其中三块完全没有第二副本，也不在任何 git 仓里：

    · WorkBuddy/Claw/output            4,101 文件 / 714M   报告产物
    · workbuddy_data/projects         28,067 文件 / 5.5G   会话历史
    · 各 workspace 的 .workbuddy/memory  690 文件 /  15M   记忆
    · workbuddy_data/workbuddy.db       261M          自动化配置库（240 条 automations）

  代码不在此列（11 个仓都有 GitHub 远端）；`hub.db` 另由 wb-autoloop-backup.py 覆盖。

为什么不用 Time Machine：
  TM 的目的地卷不会被 TM 自己备份。把 TM 指到 ZHITAI，得到的是内盘那 123G（系统/应用，
  可重装），而真正不可替代的这 6G 恰好落在保护范围之外。内盘还剩 62G，够放下这份镜像 ——
  所以用「靶向镜像」先补上，而不是干等第三块盘。

写之前先过容量闸门（V0，见 capacity_preflight）：这份镜像只增不删，内盘被它写满会连带
把系统拖住（系统更新、临时文件、swap 都要空间），所以「余量不足」必须在开写前拦住，
而不是写一半报 ENOSPC。

判据（V1–V5，每条都有对应的故障注入用例）：
  V1 源与落点必须不同物理卷（按 st_dev，不看路径前缀）
  V2 每一项源必须存在且非空；含通配的项必须至少展开出 1 个目录
     —— 源不可见时不许当「0 项全通过」（这是本项目踩过的最贵的一类坑）
  V3 源里每个 (相对路径, 字节数) 必须原样存在于落点 —— 集合包含，不是数量比对
  V4 抽样 sha256（默认 30 个，`--sample 0` 全量）防同大小内容损坏
  V5 落点上有源已没有的旧文件 → 只 WARN。这是一份备份，不跟随删除
  V6 单文件 sqlite 库（DB_ITEMS）：副本可打开、quick_check 通过、与 sidecar 一致、
     行数被「备份前/备份后」两个源读数夹住（≥26h 未更新 → FAIL）

不做 `--delete`：镜像盘比源多几个旧文件是备份的正常形态；跟随删除等于把备份变成镜像，
一次误删就两边都没有。

用法：
  wb-offsite-mirror.py run            # rsync 增量同步 + 同步后立即 verify
  wb-offsite-mirror.py verify         # 只校验，不动落点
  wb-offsite-mirror.py daily          # launchd 入口：run → 只在出问题时推飞书 + 打卡
  wb-offsite-mirror.py status         # 上次运行结果
  wb-offsite-mirror.py self-test      # 故障注入，每项只破坏一个维度，断言恰好那一项变红
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SRC_ROOT = Path("/Volumes/ZHITAI")
DEST_ROOT = Path(os.path.expanduser("~/Backups/offsite-mirror"))

# 相对 SRC_ROOT 的项；含 * 的按 glob 展开
ITEMS = [
    "WorkBuddy/Claw/output",
    "workbuddy_data/projects",
    "WorkBuddy/*/.workbuddy/memory",
]

STATE_FILE = Path(os.path.expanduser("~/.local/etc/wb-offsite-mirror.state.json"))
PING_CONF = Path(os.path.expanduser("~/.local/etc/wb-offsite-mirror.conf"))

# 单文件 sqlite 库（不在上面任何目录项里，单独走在线快照）。WAL 库直接 copy/rsync 会拿到
# 不一致的页 —— -wal 里还有没落盘的提交，且复制过程中页还在变。只有 sqlite 自己的
# backup API 能给出一个自洽的时间点，所以这类文件不进 rsync 清单。
DB_ITEMS = ["workbuddy_data/workbuddy.db"]
DB_MAX_AGE_H = 26
REMIND_DAYS = 7

# 容量闸门：写完之后内盘至少还要剩这么多。20 GiB 不是拍脑袋 —— 系统更新包、编译临时文件、
# sleepimage 都往系统盘写，写到 0 会连带把不属于备份的工作一起弄坏。
MIN_FREE_AFTER = 20 * 1024**3
GROWTH_SLACK = 1.10            # rsync 落点是「临时文件写完再 rename」，同一份文件会短暂占两份
RSYNC_TMP_ALLOW = 64 * 1024**2  # 并发文件的固定开销


def _log(msg: str) -> None:
    """每行带时间戳。

    为什么：2026-11-24 用 launchd 触发验证时，日志把 4 小时前那次（当时还没配打卡 URL）
    和刚才这次混在一起，出现「同一轮里既未配置打卡、又打卡 200」的错觉，白查了十分钟。
    这个作业每天只跑一次、且可能与手工 run 重叠，没有时间戳就无法把一段输出归给某一次运行。
    """
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def device_of(p: Path) -> int:
    """物理设备号。路径前缀靠不住：软链/绑定挂载都能让两个路径看起来「不同盘」。"""
    return os.stat(p).st_dev


def expand_items(src_root: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for item in ITEMS:
        if "*" in item:
            hits = sorted(src_root.glob(item))
            if not hits:
                out.append((item, src_root / item))     # 展开为空 → 交给 V2 判红
            for h in hits:
                out.append((str(h.relative_to(src_root)), h))
        else:
            out.append((item, src_root / item))
    return out


def walk(root: Path) -> dict[str, int]:
    """相对路径 → 字节数。落点可能不存在/不可读，一律返回空而不抛。"""
    files: dict[str, int] = {}
    if not root.is_dir():
        return files
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = Path(dirpath) / fn
            if fn == ".DS_Store":        # 与 rsync --exclude 同口径，否则自己造出假缺项
                continue
            try:
                if p.is_file() and not p.is_symlink():
                    files[str(p.relative_to(root))] = p.stat().st_size
            except OSError:
                continue
    return files


def _gib(n: float) -> str:
    return f"{n / 1024**3:.1f}G"


def pending_bytes(src: dict[str, int], dst: dict[str, int]) -> int:
    """源里「落点没有、或大小不一致」的字节数。

    用路径集合算，不用「源总量 − 落点总量」：落点留着上一版旧文件时，旧文件会把这笔
    增量抵消掉（甚至算出负数），于是「空间不够」被算成「不用空间」。这条判据最可能
    放过的是「落点积了大量源已删除的旧文件」，对偶用例见 self-test。
    """
    return sum(sz for rel, sz in src.items() if dst.get(rel) != sz)


def capacity_verdict(pending: int, free: int,
                     min_free_after: int = MIN_FREE_AFTER) -> tuple[bool, int, int]:
    """纯算术，便于注入：返回 (是否放行, 需要字节, 写后剩余字节)。"""
    need = int(pending * GROWTH_SLACK) + RSYNC_TMP_ALLOW
    after = free - need
    return after >= min_free_after, need, after


def capacity_preflight(pairs: list[tuple[str, Path]], dest_root: Path,
                       min_free_after: int = MIN_FREE_AFTER, free_fn=None,
                       src_root: Path | None = None,
                       db_items: list[str] | None = None) -> dict:
    """开写前的容量闸门：只读，不改任何文件。返回 ok/msg 与各分项，供日志与 status 用。"""
    probe = dest_root
    try:
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        free = (free_fn or (lambda p: shutil.disk_usage(p).free))(probe)
    except OSError as e:
        return {"ok": False, "pending": 0, "need": 0, "free": 0, "after": 0, "mirror_bytes": 0,
                "msg": f"读不到落点可用空间（{e.__class__.__name__}）—— 宁可拦住也不写"}
    pending = 0
    dst_total = 0
    detail: list[str] = []
    for name, p in pairs:
        dst = walk(dest_root / name)
        dst_total += sum(dst.values())
        nb = pending_bytes(walk(p), dst)
        pending += nb
        if nb:
            detail.append(f"{name} {_gib(nb)}")
    # 单文件库每次都整份重写（backup API 不支持增量），如实按源大小计空间
    if src_root is not None:
        for rel in (DB_ITEMS if db_items is None else db_items):
            s = src_root / rel
            if s.is_file():
                sz = s.stat().st_size
                pending += sz
                dst_total += (dest_root / rel).stat().st_size if (dest_root / rel).is_file() else 0
                detail.append(f"{rel} {_gib(sz)}")
    ok, need, after = capacity_verdict(pending, free, min_free_after)
    msg = (f"容量预检{'通过' if ok else '不通过'}：待写 {_gib(pending)}，含余量需 {_gib(need)}，"
           f"当前余 {_gib(free)}，写后剩 {_gib(after)}，下限 {_gib(min_free_after)}")
    if detail:
        msg += "；增量 " + "、".join(detail[:3]) + ("…" if len(detail) > 3 else "")
    return {"ok": ok, "pending": pending, "need": need, "free": free,
            "after": after, "mirror_bytes": dst_total, "msg": msg}


def sha256_of(p: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _is_prefix(dst: Path, src: Path, n: int) -> bool:
    """dst 的 n 字节是否正好是 src 的开头。只用于「落点比源小」的那几个文件。"""
    try:
        with open(dst, "rb") as fd, open(src, "rb") as fs:
            left = n
            while left > 0:
                a, b = fd.read(min(1 << 20, left)), fs.read(min(1 << 20, left))
                if a != b:
                    return False
                left -= len(a)
                if not a:
                    return False
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- sqlite 在线快照
def _db_uri(p: Path) -> str:
    return "file:" + urllib.parse.quote(p.as_posix(), safe="/:") + "?mode=ro"


def _db_tables(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "select name from sqlite_master where type='table' order by name")]


def _counts(conn) -> dict[str, int]:
    return {t: conn.execute(f'select count(*) from "{t}"').fetchone()[0] for t in _db_tables(conn)}


def _db_stats(p: Path) -> dict[str, int]:
    """只读打开，返回 {表名: 行数}。表名取自 sqlite_master，不是外部输入。"""
    import sqlite3
    c = sqlite3.connect(_db_uri(p), uri=True, timeout=30)
    try:
        return _counts(c)
    finally:
        c.close()


def rows_in_range(copy_counts: dict[str, int], before: dict[str, int],
                  after: dict[str, int]) -> list[str]:
    """副本每张表的行数必须落在「备份前/备份后」两个源读数构成的区间内。

    为什么需要这一步：sidecar 的行数是**从副本自己算出来的**，一个系统性错误的副本
    （拷错了库、只拷了 schema）也能自洽。源是活的、行数会变，所以不能要求相等，只能要求
    被两个真实读数夹住 —— 这是唯一不靠副本自证的口径。
    """
    bad: list[str] = []
    for t in sorted(set(copy_counts) | set(before) | set(after)):
        lo = min(before.get(t, 0), after.get(t, 0))
        hi = max(before.get(t, 0), after.get(t, 0))
        n = copy_counts.get(t, -1)
        if not lo <= n <= hi:
            bad.append(f"{t} 副本 {n} 源区间 [{lo},{hi}]")
    return bad


def db_sidecar(dst: Path) -> Path:
    return dst.with_name(dst.name + ".snapshot.json")


def snapshot_db(src: Path, dst: Path) -> tuple[bool, str]:
    """用 backup API 做在线快照：落 tmp → 原子替换 → 写 sidecar。

    为什么不用 cp/rsync：源是 WAL 库且正被 WorkBuddy 写，文件级复制可能拿到「一半旧页
    一半新页」，而 -wal 里还有没落盘的提交。backup API 由 sqlite 自己在读事务里逐页拷，
    得到的是一个自洽时间点。sidecar 记下字节数与每张表行数，供下次 verify 反查副本有没有
    被改过 —— 只有「能算出正确值又能写回」的判据才不是永红告警。
    """
    import sqlite3
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    junk = [tmp, tmp.with_name(tmp.name + "-wal"), tmp.with_name(tmp.name + "-shm")]
    for p in junk:
        if p.exists():
            p.unlink()
    try:
        s = sqlite3.connect(_db_uri(src), uri=True, timeout=60)
        d = sqlite3.connect(str(tmp))
        try:
            before = _counts(s)                       # 源读数①：备份前
            s.backup(d)
            after = _counts(s)                        # 源读数②：备份后（源是活的，夹住即可）
            d.execute("pragma journal_mode=delete")   # 副本自成一体，不留 -wal/-shm
            d.commit()
        finally:
            d.close()
            s.close()
        if not tmp.is_file() or tmp.stat().st_size == 0:
            return False, "快照文件为空"
        counts = _db_stats(tmp)
        bad = rows_in_range(counts, before, after)
        if bad:
            for p in junk:
                try:
                    p.unlink()
                except OSError:
                    pass
            return False, "副本行数不在源区间内：" + "；".join(bad[:3])
        os.replace(tmp, dst)                          # 原子替换：绝不出现半截副本
    except Exception as e:                            # noqa: BLE001
        for p in junk:
            try:
                p.unlink()
            except OSError:
                pass
        return False, f"快照失败：{e.__class__.__name__}: {e}"
    db_sidecar(dst).write_text(json.dumps(
        {"taken_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "bytes": dst.stat().st_size, "tables": counts,
         "src_before": before, "src_after": after},
        ensure_ascii=False, indent=1) + "\n")
    return True, f"{dst.stat().st_size / 1024**2:.0f}MB / {len(counts)} 表 / {sum(counts.values())} 行"


def db_verify(dst: Path) -> tuple[bool, str]:
    """V6：副本存在 + 完整 + 与 sidecar 一致 + 不过期。"""
    import sqlite3
    if not dst.is_file():
        return False, "副本不存在（这是唯一副本，必须红）"
    side = db_sidecar(dst)
    if not side.is_file():
        return False, "缺 sidecar：不知道这份副本是什么时候、什么内容"
    try:
        meta = json.loads(side.read_text())
        taken = time.mktime(time.strptime(meta["taken_at"], "%Y-%m-%dT%H:%M:%S"))
    except (OSError, ValueError, KeyError) as e:
        return False, f"sidecar 读不出：{e.__class__.__name__}"
    real = dst.stat().st_size
    if real != meta.get("bytes"):
        return False, f"字节数 {real} != 记下的 {meta.get('bytes')}（副本被改过）"
    try:
        c = sqlite3.connect(_db_uri(dst), uri=True, timeout=30)
        try:
            counts = {t: c.execute(f'select count(*) from "{t}"').fetchone()[0]
                      for t in _db_tables(c)}
            qc = c.execute("pragma quick_check").fetchone()[0]
        finally:
            c.close()
    except Exception as e:                            # noqa: BLE001
        return False, f"打不开副本：{e.__class__.__name__}"
    if qc != "ok":
        return False, f"quick_check 不通过：{str(qc)[:80]}"
    claim = meta.get("tables") or {}
    if counts != claim:
        diff = [f"{t} {claim.get(t)}→{counts.get(t)}"
                for t in sorted(set(counts) | set(claim)) if counts.get(t) != claim.get(t)]
        return False, f"行数与 sidecar 不符：{diff[:3]}"
    age_h = (time.time() - taken) / 3600
    if age_h > DB_MAX_AGE_H:
        return False, f"快照已 {age_h:.0f} 小时（上限 {DB_MAX_AGE_H}h）—— 镜像停了，不是源在动"
    return True, f"{len(counts)} 表 / {sum(counts.values())} 行 / {real / 1024**2:.0f}MB / {age_h:.1f}h 前"


def verify(src_root: Path, dest_root: Path, sample: int = 30,
           dev_fn=None, since: float | None = None,
           db_items: list[str] | None = None) -> list[dict]:
    """跑 V1–V6。db_items 传 [] 可跳过 V6（自检里单测 V1–V5 时用）。"""
    dev_fn = dev_fn or device_of
    items: list[dict] = []

    def add(i: str, ok: bool, msg: str, level: str | None = None) -> None:
        lv = level or ("PASS" if ok else "FAIL")
        items.append({"id": i, "level": lv, "msg": msg})

    # V1 异卷
    if not src_root.is_dir():
        add("V1", False, f"源根不存在：{src_root}")
    elif not dest_root.exists():
        add("V1", False, f"落点不存在：{dest_root}（先跑 run）")
    else:
        a, b = dev_fn(src_root), dev_fn(dest_root)
        add("V1", a != b, f"源 st_dev={a} / 落点 st_dev={b}" +
            ("" if a != b else " —— 同一物理卷，等于没有副本"))

    # V2 每项存在且非空
    pairs = expand_items(src_root)
    empty = []
    for name, p in pairs:
        n = len(walk(p))
        if n == 0:
            empty.append(name)
    add("V2", not empty,
        f"{len(pairs)} 项全部非空" if not empty
        else f"空/不可见：{empty[:4]}{' …' if len(empty) > 4 else ''}")

    # V3 集合包含（逐文件比字节数）
    #   源是活的（会话历史随时在追加），三种「不一样」必须分开对待：
    #   · 落点缺文件，但源文件是「上次成功之后」才出现的 → 正常，下次 run 补（WARN）
    #   · 落点缺文件，且源文件早于上次成功 → 复制漏了（FAIL）
    #   · 落点偏短，但源文件在复制后又被写过（mtime 更新）→ 正常增长（WARN）
    #   · 落点偏短而源没再更新 → 复制不完整（FAIL）
    #   · 落点比源大 / 落点 0 字节 → 只可能是坏的（FAIL）
    #   单靠「前缀一致」区分不了增长与截断（截断也是前缀），所以必须加时间判据。
    cap = 0
    missing: list[str] = []
    fresh: list[str] = []
    wrong: list[str] = []
    grown: list[str] = []
    total_files = total_bytes = 0
    dest_map_all: dict[str, dict[str, int]] = {}
    skip_hash: set[tuple[str, str]] = set()

    def _mt(f: Path) -> float:
        try:
            return f.stat().st_mtime
        except OSError:
            return 0.0

    for name, p in pairs:
        s_map = walk(p)
        d_map = walk(dest_root / name)
        dest_map_all[name] = d_map
        total_files += len(s_map)
        total_bytes += sum(s_map.values())
        cap = max(2, int(total_files * 0.005))
        for rel, size in s_map.items():
            if rel not in d_map:
                if since is not None and _mt(p / rel) > since:
                    fresh.append(f"{name}/{rel}")
                else:
                    missing.append(f"{name}/{rel}")
                skip_hash.add((name, rel))
                continue
            dsz = d_map[rel]
            if dsz == size:
                continue
            if dsz > size:
                wrong.append(f"{name}/{rel} 落点更大 {dsz}>{size}")
            elif dsz == 0:
                wrong.append(f"{name}/{rel} 落点 0 字节")
            elif _is_prefix(dest_root / name / rel, p / rel, dsz) and _mt(p / rel) > _mt(dest_root / name / rel) + 1e-6:
                grown.append(f"{name}/{rel}")
                skip_hash.add((name, rel))
            else:
                wrong.append(f"{name}/{rel} 落点偏短且源未再更新（复制不完整 {dsz}≠{size}）")

    age_h = (time.time() - since) / 3600 if since else None
    if missing or wrong:
        bits = []
        if missing:
            bits.append(f"缺 {len(missing)} 个（例：{missing[:3]}）")
        if wrong:
            bits.append(f"不符 {len(wrong)} 个（例：{wrong[:2]}）")
        add("V3", False, "；".join(bits))
    elif fresh and (len(fresh) > cap or (age_h is not None and age_h > 26)):
        add("V3", False,
            f"{len(fresh)} 个文件是上次成功之后新增的（上限 {cap}）；距上次成功 "
            f"{age_h:.1f} 小时 —— 更像镜像停了，而不是源在动")
    elif fresh:
        add("V3", True,
            f"{total_files - len(fresh) - len(grown)} 文件逐一对齐；{len(fresh)} 个是上次成功"
            f"之后新增的（例：{fresh[:2]}），下次 run 补全", level="WARN")
    elif grown:
        if len(grown) > cap:
            add("V3", False, f"{len(grown)}/{total_files} 个文件与源不同（上限 {cap}）—— 太多")
        else:
            add("V3", True,
                f"{total_files - len(grown)} 文件逐一对齐；{len(grown)} 个复制后源又增长"
                f"（前缀一致，下次补全）：{grown[:2]}", level="WARN")
    else:
        add("V3", True, f"{total_files} 文件 / {total_bytes} 字节逐一对齐")

    # V4 抽样 sha256（排除已知的缺失/增长文件，否则会把它们重复算一遍）
    pool = [(n, p, rel) for n, p in pairs for rel in walk(p) if (n, rel) not in skip_hash]
    if sample == 0:
        picks = pool
    else:
        rnd = random.Random(20261124)
        picks = rnd.sample(pool, min(sample, len(pool))) if pool else []
    bad_hash: list[str] = []
    for name, p, rel in picks:
        sp, dp = p / rel, dest_root / name / rel
        try:
            if not dp.is_file() or sha256_of(sp) != sha256_of(dp):
                bad_hash.append(f"{name}/{rel}")
        except OSError as e:
            bad_hash.append(f"{name}/{rel}（{e.__class__.__name__}）")
    add("V4", not bad_hash,
        f"抽样 {len(picks)}/{len(pool)} 个 sha256 一致" if not bad_hash
        else f"{len(bad_hash)} 个内容不一致（例：{bad_hash[:3]}）")

    # V5 落点多余旧文件 → WARN
    stale = 0
    for name, d_map in dest_map_all.items():
        s_map = walk(src_root / name)
        stale += sum(1 for rel in d_map if rel not in s_map)
    add("V5", True,
        f"{stale} 个落点旧文件源已无（备份正常形态，不跟随删除）"
        + ("" if stale else "：无"), level="WARN" if stale else "PASS")

    # V6 单文件 sqlite 库副本（workbuddy.db 这类：不在任何目录项里，且是唯一副本）
    for rel in (DB_ITEMS if db_items is None else db_items):
        ok6, msg6 = db_verify(dest_root / rel)
        add("V6", ok6, f"{rel}：{msg6}")

    return items


# ---------------------------------------------------------------- 同步
def rsync_tree(src: Path, dst: Path) -> tuple[int, str]:
    dst.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsync") is None:
        return 127, "rsync 不存在"
    p = subprocess.run(
        ["rsync", "-a", "--exclude=.DS_Store", str(src) + "/", str(dst) + "/"],
        capture_output=True, text=True, timeout=3600)
    return p.returncode, (p.stdout + p.stderr).strip()


def cmd_run(src_root: Path, dest_root: Path, verbose: bool = True) -> int:
    if not src_root.is_dir():
        _log(f"❌ 源根不存在：{src_root}（外置盘没插？此时绝不能当成功）")
        return 2
    pairs = expand_items(src_root)
    _log(f"→ 镜像 {len(pairs)} 项：{src_root} → {dest_root}")
    cap = capacity_preflight(pairs, dest_root, src_root=src_root)
    _log(f"  {cap['msg']}")
    if not cap["ok"]:
        _save_state(False, [{"id": "V0", "level": "FAIL", "msg": cap["msg"]}],
                    extra={"mirror_bytes": cap["mirror_bytes"]})
        _log("❌ 容量不足，一个文件都没写 —— 写满系统盘会把与备份无关的事一起弄坏")
        return 3
    fails = 0
    for name, p in pairs:
        if not p.is_dir():
            _log(f"  ⚠️ {name} 不存在（源侧缺项，交 verify 判）")
            fails += 1
            continue
        t0 = time.time()
        rc, out = rsync_tree(p, dest_root / name)
        n = len(walk(p))
        flag = "✓" if rc == 0 else "✗"
        _log(f"  {flag} {name}  {n} 文件  {time.time() - t0:.1f}s" +
             ("" if rc == 0 else f"  rc={rc} {out[:200]}"))
        if rc != 0:
            fails += 1
    for rel in DB_ITEMS:
        src_db = src_root / rel
        if not src_db.is_file():
            _log(f"  ⚠️ {rel} 不存在（源侧缺项，交 V6 判）")
            fails += 1
            continue
        t0 = time.time()
        ok_db, msg = snapshot_db(src_db, dest_root / rel)
        _log(f"  {'✓' if ok_db else '✗'} 快照 {rel}  {msg}  {time.time() - t0:.1f}s")
        if not ok_db:
            fails += 1
    items = verify(src_root, dest_root, since=_since_ts())
    for it in items:
        icon = {"PASS": "✓", "WARN": "·", "FAIL": "✗"}[it["level"]]
        _log(f"  {icon} {it['id']} {it['msg']}")
    bad = [it for it in items if it["level"] == "FAIL"]
    ok = not bad and fails == 0
    _save_state(ok, items, extra={"mirror_bytes": cap["mirror_bytes"]})
    _log("✅ 镜像完成且校验通过" if ok else "❌ 镜像有问题（见上）")
    return 0 if ok else 1


def _save_state(ok: bool, items: list[dict], extra: dict | None = None) -> None:
    st = _load_state()
    st["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    st["ok"] = ok
    st["fails"] = [it["id"] for it in items if it["level"] == "FAIL"]
    if extra:
        st.update(extra)
    if ok:
        st["last_ok"] = st["last_run"]
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        _log(f"  ⚠️ 状态写入失败：{e}")


def _since_ts() -> float | None:
    """上次成功的时间戳。给 verify 用：比它新的文件算「新增」而不是「漏拷」。"""
    st = _load_state()
    if not st.get("last_ok"):
        return None
    try:
        return time.mktime(time.strptime(st["last_ok"], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- 外部观测
def _ping_url() -> str | None:
    try:
        for line in PING_CONF.read_text().splitlines():
            line = line.strip()
            if line.startswith("HC_MIRROR_PING_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _ping(kind: str = "", timeout: float = 10) -> str:
    """kind ∈ "", "start", "fail"。永不抛异常、永不影响备份结论。"""
    url = _ping_url()
    if not url:
        return "未配置 HC_MIRROR_PING_URL（外部收不到打卡，check 会一直红）"
    full = url.rstrip("/") + (f"/{kind}" if kind else "")
    try:
        with urllib.request.urlopen(full, timeout=timeout) as r:
            return f"打卡[{kind or 'success'}] HTTP {r.status}"
    except Exception as e:                                  # noqa: BLE001
        host = urllib.parse.urlparse(url).netloc or "?"
        return f"打卡失败（{host}）：{e.__class__.__name__}"


def cmd_daily(src_root: Path, dest_root: Path) -> int:
    _log(_ping("start"))
    rc = cmd_run(src_root, dest_root)
    _log(_ping("" if rc == 0 else "fail"))
    if rc != 0:
        _push(f"【离线镜像告警】{time.strftime('%m-%d %H:%M')}\n"
              f"{src_root} → {dest_root} 校验未通过，详见 "
              f"~/Library/Logs/wb-offsite-mirror.log")
    return rc


def _push(text: str) -> str:
    pusher = Path.home() / ".local" / "bin" / "autoloop-feishu-push.py"
    if not pusher.exists():
        return "推送脚本缺失"
    try:
        p = subprocess.run([sys.executable, str(pusher), "--text", text],
                           capture_output=True, text=True, timeout=60)
        return f"推送 rc={p.returncode}"
    except Exception as e:                                  # noqa: BLE001
        return f"推送异常：{e.__class__.__name__}"


def cmd_status() -> int:
    st = _load_state()
    if not st:
        _log("从未运行")
        return 1
    _log(json.dumps(st, ensure_ascii=False, indent=1))
    _log("打卡配置：" + ("已配置" if _ping_url() else "未配置"))
    if st.get("mirror_bytes"):
        _log(f"镜像体积 {_gib(st['mirror_bytes'])}")
        try:
            _log(f"内盘当前余 {_gib(shutil.disk_usage(DEST_ROOT).free)}（下限 {_gib(MIN_FREE_AFTER)}）")
        except OSError:
            pass
    if st.get("last_ok"):
        t = time.mktime(time.strptime(st["last_ok"], "%Y-%m-%dT%H:%M:%S"))
        _log(f"距上次成功 {(time.time() - t) / 3600:.1f} 小时")
    return 0 if st.get("ok") else 1


# ---------------------------------------------------------------- 故障注入
def cmd_self_test() -> int:
    """故障注入：每项只破坏一个维度，断言**恰好那一项**变红。"""
    import tempfile

    def build(root: Path) -> Path:
        """按真实的相对结构造源树，再整体复制成落点。"""
        src = root / "src"
        files = {
            "WorkBuddy/Claw/output/report.md": b"# r\n" * 50,
            "WorkBuddy/Claw/output/2026/x.json": b'{"a":1}',
            "workbuddy_data/projects/p1/s1.jsonl": b"line\n" * 100,
            "workbuddy_data/projects/p2/s2.jsonl": b"x" * 4096,
            "WorkBuddy/ws1/.workbuddy/memory/m.md": b"m\n" * 20,
        }
        for rel, data in files.items():
            p = src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        dst = root / "dst"
        for name, p in expand_items(src):
            rsync_tree(p, dst / name)
        return src

    # 临时目录里源与落点必然同卷，无法真造两块物理盘 → 注入 dev_fn 假装异卷；
    # 专测「同卷必须红」的那条用例再把两者映射到同一个号。
    def split_dev(p: Path) -> int:
        return 0 if p.name == "src" else 1

    def reds(src: Path, dst: Path, sample: int = 0, since: float | None = None) -> list[str]:
        return sorted(i["id"] for i in verify(src, dst, sample=sample, dev_fn=split_dev,
                                              since=since, db_items=[])
                      if i["level"] == "FAIL")

    def warns(src: Path, dst: Path, since: float | None = None) -> list[str]:
        return sorted(i["id"] for i in verify(src, dst, sample=0, dev_fn=split_dev,
                                              since=since, db_items=[])
                      if i["level"] == "WARN")

    def same_dev(_p: Path) -> int:
        return 42

    def case_ok(root: Path) -> list[str]:
        src = build(root); return reds(src, root / "dst")

    def case_missing_item(root: Path) -> list[str]:
        src = build(root); shutil.rmtree(root / "dst" / "workbuddy_data" / "projects")
        return reds(src, root / "dst")

    def case_missing_file(root: Path) -> list[str]:
        src = build(root); (root / "dst/WorkBuddy/Claw/output/2026/x.json").unlink()
        return reds(src, root / "dst")

    def case_truncated(root: Path) -> list[str]:
        src = build(root)
        p = root / "dst/workbuddy_data/projects/p2/s2.jsonl"
        p.write_bytes(b"x" * 100)                      # 大小不同 → V3 抓
        return reds(src, root / "dst")

    def case_same_size_corrupt(root: Path) -> list[str]:
        src = build(root)
        p = root / "dst/workbuddy_data/projects/p2/s2.jsonl"
        p.write_bytes(b"y" * 4096)                     # 大小相同、内容不同 → 只有 V4 抓
        return reds(src, root / "dst")

    def case_empty_src(root: Path) -> list[str]:
        src = build(root)
        for f in (root / "src/WorkBuddy/ws1/.workbuddy/memory").iterdir():
            f.unlink()
        return reds(src, root / "dst")

    def case_glob_empty(root: Path) -> list[str]:
        src = build(root); shutil.rmtree(root / "src/WorkBuddy/ws1")
        return reds(src, root / "dst")

    def case_same_volume(root: Path) -> list[str]:
        src = build(root)
        return sorted(i["id"] for i in verify(src, root / "dst", sample=0, dev_fn=same_dev,
                                              db_items=[])
                      if i["level"] == "FAIL")

    def case_grown_after_copy(root: Path) -> list[str]:
        """复制后源又长了（会话历史在追加）：落点内容 = 源的前缀 → 只 WARN，且 V4 不得因它变红。"""
        src = build(root)
        with open(root / "src/workbuddy_data/projects/p2/s2.jsonl", "ab") as f:
            f.write(b"appended-later")
        assert reds(src, root / "dst") == [], "前缀一致的增长不该判红"
        assert "V3" in warns(src, root / "dst"), "应报 WARN"
        return []

    def case_dst_bigger(root: Path) -> list[str]:
        """落点比源还大：只可能是串写/损坏，必须红。"""
        src = build(root)
        with open(root / "dst/workbuddy_data/projects/p2/s2.jsonl", "ab") as f:
            f.write(b"garbage")
        return reds(src, root / "dst")

    def case_fresh_since_ok(root: Path) -> list[str]:
        """上次成功之后源新增了文件：算「新增」不算「漏拷」→ 只 WARN。"""
        src = build(root)
        (root / "src/WorkBuddy/Claw/output/just-now.md").write_bytes(b"new")
        since = time.time() - 5
        assert reds(src, root / "dst", since=since) == [], "新增文件不该判红"
        assert "V3" in warns(src, root / "dst", since=since), "应报 WARN"
        return []

    def case_stale_since(root: Path) -> list[str]:
        """但若上次成功已是 48 小时前，同样的「新增」必须判红 —— 那是镜像停了，不是源在动。"""
        src = build(root)
        (root / "src/WorkBuddy/Claw/output/just-now.md").write_bytes(b"new")
        return reds(src, root / "dst", since=time.time() - 48 * 3600)

    def case_stale_ok(root: Path) -> list[str]:
        src = build(root)
        p = root / "dst/workbuddy_data/projects/old.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"stale")
        assert reds(src, root / "dst") == [], "多余旧文件不该判红"
        assert "V5" in warns(src, root / "dst"), "多余旧文件必须报 WARN"
        return []

    # ---- 容量闸门（V0）：纯算术注入，不靠真把内盘写满
    def case_capacity_ok(root: Path) -> list[str]:
        build(root)
        cap = capacity_preflight(expand_items(root / "src"), root / "dst",
                                 free_fn=lambda _p: 1 << 40)
        assert cap["ok"], f"空间充足却拦住：{cap['msg']}"
        assert cap["pending"] == 0, f"落点已齐却算出待写 {cap['pending']} 字节"
        return []

    def case_capacity_short(root: Path) -> list[str]:
        """余量只比下限多一点点，待写量把它吃掉 → 必须拦住。"""
        src = build(root)
        (root / "src/workbuddy_data/projects/p3").mkdir(parents=True)
        (root / "src/workbuddy_data/projects/p3/big.bin").write_bytes(b"z" * (5 << 20))
        cap = capacity_preflight(expand_items(src), root / "dst",
                                 free_fn=lambda _p: MIN_FREE_AFTER + (1 << 20))
        assert not cap["ok"], "待写量会吃掉余量，却放行了"
        return []

    def case_capacity_stale_offset(root: Path) -> list[str]:
        """落点积着大量旧文件：用「源总量−落点总量」会算成负数而放行，必须用路径集合。

        对偶断言（证明这个用例真的有效）：同一组输入下旧口径必须**放行** —— 否则它
        只是又一个所有口径都拦得住的假绿灯。
        """
        src = build(root)
        stale = root / "dst/workbuddy_data/projects/old"
        stale.mkdir(parents=True, exist_ok=True)
        (stale / "junk.bin").write_bytes(b"j" * (50 << 20))      # 50M 源里已删的旧文件
        (root / "src/workbuddy_data/projects/p3").mkdir(parents=True)
        (root / "src/workbuddy_data/projects/p3/big.bin").write_bytes(b"z" * (5 << 20))
        free = MIN_FREE_AFTER + (66 << 20)                       # 只够旧口径蒙过去
        pairs = expand_items(src)
        cap = capacity_preflight(pairs, root / "dst", free_fn=lambda _p: free)
        s_tot = sum(sum(walk(p).values()) for _n, p in pairs)
        d_tot = sum(sum(walk(root / "dst" / n).values()) for n, _p in pairs)
        naive_ok, _, _ = capacity_verdict(max(0, s_tot - d_tot), free)
        assert naive_ok, "对偶前提不成立：旧口径也拦住，这个用例证明不了任何事"
        assert cap["pending"] >= (5 << 20), f"路径口径应看到 5M 待写，实际 {cap['pending']}"
        assert not cap["ok"], "旧文件抵消了增量，被算成放行"
        return []

    def case_capacity_gate_blocks_write(root: Path) -> list[str]:
        """注入「闸门不过」→ cmd_run 必须 rc=3，且一个文件都不写、状态记 V0。"""
        src = build(root)
        shutil.rmtree(root / "dst")
        saved = (globals()["capacity_preflight"], globals()["STATE_FILE"])
        globals()["capacity_preflight"] = lambda *a, **k: {
            "ok": False, "pending": 1, "need": 1, "free": 0, "after": -1,
            "mirror_bytes": 0, "msg": "注入：余量不足"}
        globals()["STATE_FILE"] = root / "state.json"
        try:
            rc = cmd_run(src, root / "dst")
        finally:
            globals()["capacity_preflight"], globals()["STATE_FILE"] = saved
        assert rc == 3, f"闸门不过应 rc=3，实际 {rc}"
        assert not (root / "dst" / "workbuddy_data").exists(), "拦住之后仍写了文件"
        assert json.loads((root / "state.json").read_text())["fails"] == ["V0"], "状态没记 V0"
        return []

    # ---- V6 单文件 sqlite 库：快照 + 反查
    def make_db(p: Path) -> Path:
        import sqlite3
        p.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(p))
        c.execute("create table automations(id integer primary key, name text)")
        c.execute("create table sessions(id integer primary key, body text)")
        c.executemany("insert into automations(name) values (?)", [("a",), ("b",), ("c",)])
        c.executemany("insert into sessions(body) values (?)", [("x",)] * 7)
        c.commit()
        c.close()
        return p

    def db_case(root: Path, mutate=None) -> list[str]:
        """造源库 → 快照 → 可选破坏 → 只跑含 V6 的 verify，返回红项。"""
        src = build(root)
        rel = DB_ITEMS[0]
        make_db(src / rel)
        ok, msg = snapshot_db(src / rel, root / "dst" / rel)
        assert ok, f"快照失败：{msg}"
        if mutate:
            mutate(root / "dst" / rel)
        items = verify(src, root / "dst", sample=0, dev_fn=split_dev, db_items=DB_ITEMS)
        return sorted(i["id"] for i in items if i["level"] == "FAIL")

    def case_db_ok(root: Path) -> list[str]:
        return db_case(root)

    def case_db_missing(root: Path) -> list[str]:
        return db_case(root, lambda d: d.unlink())

    def case_db_no_sidecar(root: Path) -> list[str]:
        return db_case(root, lambda d: db_sidecar(d).unlink())

    def case_db_same_size_corrupt(root: Path) -> list[str]:
        """同大小、内容坏：字节数与 sidecar 一致，只能靠 quick_check/行数抓。"""
        def boom(d: Path) -> None:
            with open(d, "r+b") as f:
                f.seek(4096 * 2)
                f.write(b"\xff" * 512)
        return db_case(root, boom)

    def case_db_rows_tampered(root: Path) -> list[str]:
        def tamper(d: Path) -> None:
            side = db_sidecar(d)
            meta = json.loads(side.read_text())
            meta["tables"]["sessions"] = 999          # 谎报行数，副本实际 7
            side.write_text(json.dumps(meta, ensure_ascii=False))
        return db_case(root, tamper)

    def case_db_stale(root: Path) -> list[str]:
        def age(d: Path) -> None:
            side = db_sidecar(d)
            meta = json.loads(side.read_text())
            meta["taken_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 48 * 3600))
            side.write_text(json.dumps(meta, ensure_ascii=False))
        return db_case(root, age)

    def case_db_range_ok(root: Path) -> list[str]:
        """源在备份期间长了一行：副本行数被两个读数夹住即算过。"""
        assert rows_in_range({"a": 240}, {"a": 240}, {"a": 241}) == []
        return []

    def case_db_range_bad(root: Path) -> list[str]:
        """空副本 / 拷错库：行数落在源区间外，必须抓到（sidecar 自证抓不到这种）。"""
        assert rows_in_range({"a": 0}, {"a": 240}, {"a": 240}) != [], "空副本没被抓到"
        assert rows_in_range({}, {"a": 240}, {"a": 240}) != [], "缺表没被抓到"
        return []

    cases = [
        ("裸绿（无破坏）", case_ok, []),
        ("落点缺一整项", case_missing_item, ["V3"]),
        ("落点缺一个文件", case_missing_file, ["V3"]),
        ("文件被截断", case_truncated, ["V3", "V4"]),
        ("同大小内容不同", case_same_size_corrupt, ["V4"]),
        ("源某项被清空", case_empty_src, ["V2"]),
        ("通配展开为空", case_glob_empty, ["V2"]),
        ("源与落点同卷", case_same_volume, ["V1"]),
        ("复制后源又增长", case_grown_after_copy, []),
        ("落点比源还大", case_dst_bigger, ["V3", "V4"]),
        ("上次成功后新增文件", case_fresh_since_ok, []),
        ("上次成功已 48 小时", case_stale_since, ["V3"]),
        ("落点有多余旧文件", case_stale_ok, []),
        ("容量充足放行", case_capacity_ok, []),
        ("余量被增量吃掉", case_capacity_short, []),
        ("落点旧文件抵消增量", case_capacity_stale_offset, []),
        ("闸门不过则不写一个字节", case_capacity_gate_blocks_write, []),
        ("库快照一致", case_db_ok, []),
        ("库副本丢失", case_db_missing, ["V6"]),
        ("库副本缺 sidecar", case_db_no_sidecar, ["V6"]),
        ("库副本同大小损坏", case_db_same_size_corrupt, ["V6"]),
        ("库行数与 sidecar 不符", case_db_rows_tampered, ["V6"]),
        ("库快照已 48 小时", case_db_stale, ["V6"]),
        ("库行数被源读数夹住", case_db_range_ok, []),
        ("库行数落在源区间外", case_db_range_bad, []),
    ]
    passed = 0
    for title, fn, expect in cases:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "case"
            root.mkdir()
            try:
                got = fn(root)
            except AssertionError as e:
                _log(f"✗ {title}：断言失败 {e}")
                continue
            if got == expect:
                _log(f"✓ {title}：红项={got or '无（如预期）'}")
                passed += 1
            else:
                _log(f"✗ {title}：期望 {expect}，实际 {got}")
    _log(f"\n{passed}/{len(cases)} 通过")
    return 0 if passed == len(cases) else 1


# ---------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="只此一份的数据 → 另一块物理盘")
    ap.add_argument("cmd", choices=["run", "verify", "daily", "status", "self-test"])
    ap.add_argument("--source", default=str(SRC_ROOT))
    ap.add_argument("--dest", default=str(DEST_ROOT))
    ap.add_argument("--sample", type=int, default=30, help="抽样 sha256 个数，0=全量")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    src, dst = Path(a.source), Path(a.dest)
    if a.cmd == "self-test":
        return cmd_self_test()
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "run":
        return cmd_run(src, dst)
    if a.cmd == "daily":
        return cmd_daily(src, dst)

    items = verify(src, dst, sample=a.sample, since=_since_ts())
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
    else:
        for it in items:
            icon = {"PASS": "✓", "WARN": "·", "FAIL": "✗"}[it["level"]]
            _log(f"{icon} {it['id']} {it['msg']}")
    return 0 if not any(i["level"] == "FAIL" for i in items) else 1


if __name__ == "__main__":
    sys.exit(main())
