#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wb-ui-guard.py —— GUI 自动化的物理闸门：点之前先看屏幕上是什么。

为什么需要它（2026-11-24，本项目的第四次同类教训）：
    那天为了给时间机器加一块盘，用坐标点击在系统设置里连续点了七八次。中途弹出一个
    「此操作将抹掉 ZHITAI」的对话框——那是删掉 274GB 全部数据的按钮。当时是按 Esc 救回来的，
    也就是说**没出事靠的是临场反应，不是设计**。同一天还有两处：恢复密钥出现在屏幕上被截屏读到；
    让用户执行 pbpaste 命令反而把 key 文件写成了命令本身。

    只写「请注意不要点危险按钮」属于提示词约束，不是闸门。真正的闸门必须满足三条：
      · 挂在必经之路上（不调用它就点不下去）
      · 失败时默认拒绝（读不到屏幕 ≠ 安全）
      · 自己有位断言（status 能证明它接了线，而不是一份躺在仓库里的文件）

三道判据（每条都有故障注入用例）：
    D1 前台应用禁令  系统设置/磁盘工具/钥匙串/授权弹窗 → 任何坐标点击一律拒绝
                     （这一条不依赖读文本，最不容易被绕过）
    D2 危险关键词    模态框里出现「抹掉/抹除/格式化/删除卷/Erase/Wipe」→ 先按 Esc 再拒绝
    D3 机密关键词    出现「恢复密钥/recovery key」→ 拒绝但**绝不按 Esc**
                     （Esc 会关掉密钥的唯一一次显示，等于把用户的救命钥匙丢掉）
    其余情况：模态框存在但看不懂 → 拒绝（fail-closed）；屏幕读不到 → 拒绝。

用法：
    wb-ui-guard.py scan                 # 只判定，不动屏幕
    wb-ui-guard.py forward <args...>    # 过闸门后转发给真 cliclick（interlock 内部用）
    wb-ui-guard.py click X,Y            # 过闸门后左键单击
    wb-ui-guard.py status               # 闸门是否真的接上线（自身位断言）
    wb-ui-guard.py install-interlock    # 替换 /opt/homebrew/bin/cliclick（可逆）
    wb-ui-guard.py remove-interlock     # 还原 brew 软链
    wb-ui-guard.py self-test            # 13 项故障注入

退出码：0 放行 / 2 危险模态(已 Esc) / 3 前台应用被禁 / 4 读不到屏幕 / 5 机密模态(未 Esc)
        / 6 未知模态 / 7 未接线仍被直接调用
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
STATE = HOME / ".local/etc/wb-ui-guard.json"
LOG = HOME / ".local/log/wb-ui-guard.log"
INTERLOCK = Path("/opt/homebrew/bin/cliclick")
CELLAR_GLOB = "/opt/homebrew/Cellar/cliclick/*/bin/cliclick"  # 版本号会变，不能写死


def _newest_cellar():
    """按 Cellar 目录找最新的 cliclick 真身。

    为什么不写死 `/opt/homebrew/Cellar/cliclick/5.1/bin/cliclick`：brew 一升级版本号就变，
    写死会在升级后指向不存在的路径，报"找不到真 cliclick"，容易被误判成没装（审计 P2-3）。
    """
    import glob
    cands = [p for p in glob.glob(CELLAR_GLOB) if Path(p).exists()]
    if not cands:
        return None
    def _ver(path):
        seg = Path(path).parts[-3]
        return tuple(int(x) if x.isdigit() else 0 for x in seg.replace("-", ".").split("."))
    return sorted(cands, key=_ver)[-1]


FALLBACK_REAL = _newest_cellar() or "/opt/homebrew/bin/cliclick"

# D1：这些前台应用一律不接坐标点击。判据不读文本，只认应用身份。
# 两套并行：名字给人看，bundle id 给机器判。**只靠名字会漏**—— macOS 26 把
# 「钥匙串访问」改名为「密码」(Passwords)，进程名一变，名字表就整条失效（2026-11-24 实测踩到：
# 前台 Passwords 时 cliclick 仍被放行）。bundle id 由 App 自身声明，升级改名也不变。
DENY_APPS = (
    "System Settings", "系统设置", "System Preferences", "系统偏好设置",
    "Disk Utility", "磁盘工具", "Keychain Access", "钥匙串访问", "Passwords", "密码",
    "SecurityAgent", "securityd", "Installer", "安装器", "Migration Assistant",
)
DENY_BUNDLES = (
    "com.apple.systempreferences", "com.apple.DiskUtility", "com.apple.Passwords",
    "com.apple.keychainaccess", "com.apple.SecurityAgent", "com.apple.Installer",
    "com.apple.MigrateAssistant",
)

# D2：破坏性动作。中文按子串（中文没有词边界问题），英文按词边界（防 formatted 误命中）。
BLOCK_CN = ("抹掉", "抹除", "抹去", "格式化", "初始化", "清除所有", "删除卷", "删除磁盘",
            "移除卷", "抹掉此磁盘", "抹除此磁盘", "全部删除")
BLOCK_EN = ("erase", "format", "initialize", "delete volume", "remove volume", "wipe", "reformat")

# D3：机密。出现这些必须停手，但不能按 Esc。
# 只认「恢复密钥」。曾写成 ("恢复密钥", "密钥")，而"密钥"会把钥匙串口令框、SSH 口令提示
# 一并判成机密态 → 停手等人工（2026-11-24 审计 P2-2）。D3 存在的唯一理由是：Esc 会关掉
# **恢复密钥**的唯一一次显示，其他含"密钥"字样的对话框没有这个性质。
SECRET_CN = ("恢复密钥",)
SECRET_EN = ("recovery key",)

RC_OK, RC_BLOCK, RC_DENY, RC_UNREAD, RC_SECRET, RC_UNKNOWN, RC_UNWIRED = 0, 2, 3, 4, 5, 6, 7

VERDICT_OK = "OK"
VERDICT_BLOCK = "BLOCK"
VERDICT_DENY = "DENY_APP"
VERDICT_UNREAD = "UNREADABLE"
VERDICT_SECRET = "SECRET"
VERDICT_UNKNOWN = "UNKNOWN_MODAL"

RC_OF = {
    VERDICT_OK: RC_OK, VERDICT_BLOCK: RC_BLOCK, VERDICT_DENY: RC_DENY,
    VERDICT_UNREAD: RC_UNREAD, VERDICT_SECRET: RC_SECRET, VERDICT_UNKNOWN: RC_UNKNOWN,
}

JXA_SCAN = r"""
function run() {
  var out = { front: "", groups: [], err: null };
  function walk(el, d, acc) {
    if (d > 8) return;
    var role = "", nm = "", val = "";
    try { role = String(el.role() || ""); } catch (e) {}
    try { nm = String(el.name() || ""); } catch (e) {}
    if (role === "AXStaticText" || role === "AXButton" || role === "AXHeading" ||
        role === "AXTextField" || role === "AXCheckBox" || role === "AXRadioButton") {
      try { val = String(el.value() || ""); } catch (e) {}
      if (val && val !== "null" && val.length < 300) acc.push(val);
      if (nm && nm !== "null" && nm.length < 300) acc.push(nm);
    }
    var kids = [];
    try { kids = el.uiElements(); } catch (e) { return; }
    for (var i = 0; i < kids.length; i++) walk(kids[i], d + 1, acc);
  }
  function collect(el) { var acc = []; walk(el, 0, acc); return acc; }
  try {
    var se = Application("System Events");
    var front = "";
    try { front = String(se.processes.whose({ frontmost: true })[0].name()); } catch (e0) {
      try {
        var all = se.processes();
        for (var i = 0; i < all.length; i++) {
          var f = false;
          try { f = all[i].frontmost(); } catch (e1) { f = false; }
          if (f) { front = String(all[i].name()); break; }
        }
      } catch (e2) {}
    }
    if (!front) { out.err = "no-frontmost"; return JSON.stringify(out); }
    out.front = front;
    var pf = se.processes.byName(front);
    try { out.bundle = String(pf.bundleIdentifier() || ""); } catch (eb) { out.bundle = ""; }
    // 扫描范围 = 所有可见进程的模态窗口，不只是前台 App。
    // 为什么（2026-11-24 实测）：坐标点击命中的是屏幕最上层的窗口，与「谁在前台」无关。
    // 当时两个对话框浮在最上面，但属主是后台的 System Events，只扫前台时报告「0 个模态」——
    // 等于在最该拦住的位置瞎了。
    function scanProc(p) {
      var pname = "";
      try { pname = String(p.name() || ""); } catch (e) { return; }
      var wins = [];
      try { wins = p.windows(); } catch (e) { return; }
      for (var wi = 0; wi < wins.length; wi++) {
        var w = wins[wi];
        var sheets = [];
        try { sheets = w.sheets(); } catch (e) {}
        for (var si = 0; si < sheets.length; si++) {
          out.groups.push({ kind: "sheet", app: pname, texts: collect(sheets[si]) });
        }
        var sub = "", role = "";
        try { sub = String(w.subrole() || ""); } catch (e) {}
        try { role = String(w.role() || ""); } catch (e) {}
        if (sub === "AXDialog" || role === "AXDialog" || sub === "AXSystemDialog") {
          out.groups.push({ kind: "dialog", app: pname, texts: collect(w) });
        }
      }
    }
    // 两个都不完美，取中间：
    //   只扫前台        → 漏掉后台属主的置顶对话框（实测：System Events 的框浮在最上面却没被看见）
    //   扫全部 87 个进程 → 实测 7.9 秒，每次点击都等 8 秒不可接受
    // 所以扫「前台 + 已知会弹系统对话框的属主」。这些进程都是后台进程（visible=false），
    // 按 visible 过滤恰好会把它们排除，这是第一版扫不到的真正原因。
    var procs = [pf];
    // 注意：不包含 NotificationCenter。它的「对话框」是通知（实测无可点按钮、Esc 关不掉），
    // 当成阻塞项会把闸门变成死锁：一条关不掉的通知就能让所有点击永远被拒（实测 rc=6 挡死）。
    // 通知不会挡住坐标点击的落点，因此不参与判定。
    var extra = ["System Events", "UserNotificationCenter",
                 "UserNotificationCenterHelper", "SecurityAgent", "CoreServicesUIAgent"];
    // 关键性能细节：byName 查「不存在的进程」会卡好几秒（实测 7 次查询把总耗时推到 11 秒）。
    // 先一次性取全部进程名（一次调用），只对确实存在的属主发 windows() 查询。
    var allNames = [];
    try { allNames = se.processes.name(); } catch (e4) {}
    for (var ei = 0; ei < extra.length; ei++) {
      if (extra[ei] === front) continue;
      if (allNames.length && allNames.indexOf(extra[ei]) < 0) continue;
      try { procs.push(se.processes.byName(extra[ei])); } catch (e3) {}
    }
    for (var pi = 0; pi < procs.length; pi++) scanProc(procs[pi]);
  } catch (e) { out.err = String(e); }
  return JSON.stringify(out);
}
"""


_LOG_ENABLED = True


def _log(msg):
    # self-test 期间必须静音：否则 10 项注入会写进真实日志，
    # status 的「历史拦截 N 次」就变成自检噪音，计数彻底失真。
    if not _LOG_ENABLED:
        return
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def _load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def real_cliclick():
    """真身路径：interlock 装过就取 state 里记的，否则现解析。"""
    st = _load_state()
    p = st.get("real_cliclick")
    if p and Path(p).exists():
        return p
    try:
        resolved = str(Path(INTERLOCK).resolve())
        if resolved != str(INTERLOCK):
            return resolved
    except OSError:
        pass
    return FALLBACK_REAL


def scan_screen():
    """读前台应用与所有模态框文本。返回 dict(front, groups, err)。"""
    try:
        r = subprocess.run(["osascript", "-l", "JavaScript", "-e", JXA_SCAN],
                           capture_output=True, text=True, timeout=25)
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"front": "", "groups": [], "err": "%s: %s" % (e.__class__.__name__, e)}
    if r.returncode != 0:
        return {"front": "", "groups": [], "err": (r.stderr or "osascript rc=%d" % r.returncode).strip()[:200]}
    try:
        d = json.loads(r.stdout.strip() or "{}")
    except ValueError:
        return {"front": "", "groups": [], "err": "JXA 输出不可解析"}
    d.setdefault("front", "")
    d.setdefault("bundle", "")
    d.setdefault("groups", [])
    return d


def _hit(needles_cn, needles_en, texts):
    out = []
    for t in texts:
        for n in needles_cn:
            if n in t:
                out.append(n)
        low = t.lower()
        for n in needles_en:
            if re.search(r"\b%s\b" % re.escape(n), low):
                out.append(n)
    return sorted(set(out))


def classify(front, groups, read_ok=True, bundle=""):
    """纯函数：不碰屏幕、不按键。self-test 直接注入假数据反证它。"""
    if not read_ok:
        return VERDICT_UNREAD, ["读不到前台窗口"]
    all_texts = [t for g in groups for t in g.get("texts", [])]
    blk = _hit(BLOCK_CN, BLOCK_EN, all_texts)
    if blk:
        return VERDICT_BLOCK, blk
    sec = _hit(SECRET_CN, SECRET_EN, all_texts)
    if sec:
        return VERDICT_SECRET, sec
    # 名字与 bundle 任一命中即拒。名字表会因 App 改名失效（钥匙串访问→密码），
    # bundle id 不会，所以两条都留：名字给人读日志，bundle 给机器兜底。
    if bundle and any(bundle.lower() == b.lower() for b in DENY_BUNDLES):
        return VERDICT_DENY, [front or bundle, bundle]
    if front and any(a == front or a in front for a in DENY_APPS):
        return VERDICT_DENY, [front]
    if groups:
        return VERDICT_UNKNOWN, ["%d 个模态框，无可识别关键词" % len(groups)]
    return VERDICT_OK, []


def press_escape():
    subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 53'],
                   capture_output=True, text=True, timeout=15)


def enforce(what, esc_fn=press_escape, scanner=None):
    """过闸门。返回 rc；0 才允许继续。"""
    s = (scanner or scan_screen)()
    verdict, hits = classify(s.get("front", ""), s.get("groups", []),
                             read_ok=not s.get("err"), bundle=s.get("bundle", ""))
    if verdict == VERDICT_OK:
        return RC_OK
    if verdict == VERDICT_BLOCK:
        esc_fn()
        _log("BLOCK what=%s front=%s hits=%s 已按 Esc" % (what, s.get("front"), hits))
        print("🚫 拦截：屏幕上有破坏性对话框（命中 %s）" % "、".join(hits), file=sys.stderr)
        print("   已按 Esc 取消。前台：%s。不执行：%s" % (s.get("front"), what), file=sys.stderr)
        return RC_BLOCK
    if verdict == VERDICT_SECRET:
        _log("SECRET what=%s front=%s hits=%s 未按 Esc" % (what, s.get("front"), hits))
        print("🔐 拦截：屏幕上是机密内容（命中 %s），**故意没有按 Esc**" % "、".join(hits), file=sys.stderr)
        print("   Esc 会关掉密钥的唯一一次显示。请先把它记下来，再说要做什么。", file=sys.stderr)
        return RC_SECRET
    if verdict == VERDICT_DENY:
        _log("DENY_APP what=%s front=%s" % (what, s.get("front")))
        print("🚫 拦截：前台是「%s」，这类界面禁止坐标点击（见 D1）" % s.get("front"), file=sys.stderr)
        print("   手工点，或改用无坐标的方式。不执行：%s" % what, file=sys.stderr)
        return RC_DENY
    if verdict == VERDICT_UNREAD:
        _log("UNREADABLE what=%s err=%s" % (what, s.get("err")))
        print("🚫 拦截：读不到屏幕（%s）。读不到 ≠ 安全，默认拒绝。" % s.get("err"), file=sys.stderr)
        return RC_UNREAD
    _log("UNKNOWN_MODAL what=%s front=%s n=%d" % (what, s.get("front"), len(s.get("groups") or [])))
    print("🚫 拦截：屏幕上有看不懂的对话框（%d 个），不盲点。不执行：%s"
          % (len(s.get("groups") or []), what), file=sys.stderr)
    return RC_UNKNOWN


def cmd_scan(_args):
    s = scan_screen()
    verdict, hits = classify(s.get("front", ""), s.get("groups", []), read_ok=not s.get("err"))
    print("前台: %s" % (s.get("front") or "(读不到)"))
    print("模态: %d 个" % len(s.get("groups", [])))
    for g in s.get("groups", []):
        print("  [%s] %s" % (g.get("kind"), " / ".join(g.get("texts", [])[:6])))
    print("判定: %s %s" % (verdict, hits or ""))
    return RC_OF[verdict]


def cmd_forward(args):
    if not args:
        print("用法: forward <cliclick 参数...>", file=sys.stderr)
        return 1
    rc = enforce("cliclick " + " ".join(args))
    if rc != RC_OK:
        return rc
    real = real_cliclick()
    if not Path(real).exists():
        print("❌ 找不到真 cliclick：%s" % real, file=sys.stderr)
        return RC_UNWIRED
    os.execv(real, [real] + args)
    return 1


def cmd_click(args):
    if len(args) != 1:
        print("用法: click X,Y", file=sys.stderr)
        return 1
    return cmd_forward(["c:%s" % args[0]])


def cmd_status(_args):
    print("闸门: %s" % Path(__file__).resolve())
    wired = False
    try:
        body = INTERLOCK.read_text(encoding="utf-8", errors="replace")
        wired = "wb-ui-guard" in body
    except OSError:
        body = ""
    print("interlock: %s" % ("已接线（%s → 本闸门）" % INTERLOCK if wired
                             else "未接线（裸 cliclick 可绕过，见 install-interlock）"))
    which = shutil.which("cliclick")
    print("PATH 解析: %s" % (which or "(无)"))
    print("真身: %s" % real_cliclick())
    blocks = 0
    if LOG.exists():
        try:
            blocks = sum(1 for ln in LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                         if " BLOCK " in ln or " DENY_APP " in ln)
        except OSError:
            pass
    print("历史拦截: %d 次（%s）" % (blocks, LOG))
    if not wired:
        print("\n⚠️  自身位断言失败：闸门没接在必经之路上，现在它只是一份文件。", file=sys.stderr)
        return RC_UNWIRED
    return RC_OK


SHIM_BODY = """#!/bin/sh
# 由 wb-ui-guard.py install-interlock 生成 —— 先过闸门，再转发真 cliclick。
# 还原：wb-ui-guard.py remove-interlock
# 解释器：优先用系统 python3 的绝对路径。裸写 python3 依赖 PATH，在最小 PATH（某些 cron /
# launchd）下会 exec 失败，连带 cliclick 整个不可用（审计 P2-4）。
if [ -x /usr/bin/python3 ]; then PY=/usr/bin/python3; else PY=python3; fi
exec "$PY" "$HOME/.local/bin/wb-ui-guard.py" forward "$@"
"""


def _verify_interlock(real, runner=None, scanner=None):
    """接线自检：只验证「真身能跑」，**不经过 shim**。

    为什么改（2026-11-24 审计 P1-1）：早期用 `cliclick p` 验证，而此刻 cliclick 已指向 shim
    → 自检要过闸门自己。前台是受禁应用、或屏幕上有任意模态时，结论取决于瞬时界面状态；
    实测出现过「同一前台单独 cliclick 被拒 rc=3，而安装却报成功」的矛盾，且全程无日志可查。
    改成直调真身绝对路径后，自检与闸门解耦；同时把 front/rc/out 交给调用方写日志。
    """
    s = (scanner or scan_screen)()
    detail = {"front": s.get("front", ""), "bundle": s.get("bundle", ""), "err": s.get("err")}
    run = runner or subprocess.run
    try:
        r = run([real, "p"], capture_output=True, text=True, timeout=30)
        out = (getattr(r, "stdout", "") or "").strip()
        detail["rc"] = getattr(r, "returncode", "?")
        detail["out"] = out[:60]
        return bool(re.match(r"^\s*\d+\s*,\s*\d+\s*$", out)), detail
    except (subprocess.TimeoutExpired, OSError) as e:
        detail["rc"] = "exc"
        detail["out"] = "%s: %s" % (e.__class__.__name__, e)
        return False, detail


def cmd_install(_args):
    if not INTERLOCK.exists() and not INTERLOCK.is_symlink():
        print("❌ %s 不存在，不动" % INTERLOCK, file=sys.stderr)
        return 1
    try:
        if "wb-ui-guard" in INTERLOCK.read_text(encoding="utf-8", errors="replace"):
            print("已接线，无需重复")
            return RC_OK
    except OSError:
        pass
    real = str(Path(INTERLOCK).resolve())
    if real == str(INTERLOCK) or not Path(real).exists():
        print("❌ %s 不是指向已存在文件的软链，状态未知，不动" % INTERLOCK, file=sys.stderr)
        return 1
    st = _load_state()
    st["real_cliclick"] = real
    st["installed_at"] = subprocess.run(["date", "+%Y-%m-%dT%H:%M:%S"],
                                        capture_output=True, text=True).stdout.strip()
    _save_state(st)
    INTERLOCK.unlink()
    INTERLOCK.write_text(SHIM_BODY, encoding="utf-8")
    INTERLOCK.chmod(0o755)
    # 自检调真身绝对路径（不经 shim），并把现场写进日志 —— 见 _verify_interlock 的说明。
    passed, detail = _verify_interlock(real)
    _log("install-interlock 自检 front=%s bundle=%s rc=%s passed=%s out=%r"
         % (detail.get("front"), detail.get("bundle"), detail.get("rc"), passed, detail.get("out")))
    if not passed:
        print("⚠️ 接线自检失败（真身 %s）rc=%s out=%r，正在还原"
              % (real, detail.get("rc"), detail.get("out")), file=sys.stderr)
        cmd_remove([])
        return 1
    print("✅ 已接线：%s 现在先过闸门（真身 %s）" % (INTERLOCK, real))
    print("   还原：wb-ui-guard.py remove-interlock")
    return RC_OK


def cmd_remove(_args):
    st = _load_state()
    real = st.get("real_cliclick") or FALLBACK_REAL
    if INTERLOCK.exists() and not INTERLOCK.is_symlink():
        try:
            body = INTERLOCK.read_text(encoding="utf-8", errors="replace")
        except OSError:
            body = ""
        if "wb-ui-guard" not in body:
            print("❌ %s 不是本闸门装的，不动" % INTERLOCK, file=sys.stderr)
            return 1
        INTERLOCK.unlink()
    if not INTERLOCK.exists():
        os.symlink(real, INTERLOCK)
    print("✅ 已还原软链：%s → %s" % (INTERLOCK, real))
    return RC_OK


def _mk(front, texts, kind="sheet", bundle=""):
    groups = [{"kind": kind, "texts": texts}] if texts is not None else []
    return {"front": front, "groups": groups, "err": None, "bundle": bundle}


def self_test():
    """13 项故障注入：每项只注入一个条件，断言判定与「是否按 Esc」都对。"""
    global _LOG_ENABLED
    _LOG_ENABLED = False
    calls = {"esc": 0}

    def esc():
        calls["esc"] += 1

    def run_case(name, scanner, want_verdict, want_esc, extra=None):
        calls["esc"] = 0
        rc = enforce("case", esc_fn=esc, scanner=scanner)
        got_esc = calls["esc"]
        ok = (rc == RC_OF[want_verdict]) and (got_esc == want_esc)
        if extra is not None and ok:
            ok = extra(rc)
        print("%s %-38s rc=%s esc=%d 期望 %s/%d" % (
            "✅" if ok else "❌", name, rc, got_esc, want_verdict, want_esc))
        return ok

    cases = [
        ("干净，无模态", lambda: _mk("Finder", None), VERDICT_OK, 0),
        ("抹掉 ZHITAI 确认框", lambda: _mk("System Settings", ["此操作将抹掉“ZHITAI”上的所有数据。"]),
         VERDICT_BLOCK, 1),
        ("English erase 对话框", lambda: _mk("Terminal", ["Erase \"ZHITAI\"?"]), VERDICT_BLOCK, 1),
        ("删除卷", lambda: _mk("Terminal", ["要删除卷“TMBackup”吗？"]), VERDICT_BLOCK, 1),
        ("恢复密钥（不许按 Esc）", lambda: _mk("System Settings", ["恢复密钥 3JM2-XVAD-GQGQ"]),
         VERDICT_SECRET, 0),
        ("未知模态", lambda: _mk("Terminal", ["确定要继续吗？"]), VERDICT_UNKNOWN, 0),
        ("前台是系统设置", lambda: _mk("系统设置", None), VERDICT_DENY, 0),
        ("读不到屏幕", lambda: {"front": "", "groups": [], "err": "osascript rc=1"},
         VERDICT_UNREAD, 0),
        ("关键词只在标题不在模态", lambda: _mk("Terminal", None), VERDICT_OK, 0),
        # "formatted" 不应命中 \bformat\b；命中就会误报，且按 Esc 会打断正常流程
        ("formatted 不误命中 format", lambda: _mk("Disk Utility", ["磁盘已 formatted"]),
         VERDICT_DENY, 0),
        # macOS 26 把「钥匙串访问」改名「密码」→ 进程名变 Passwords，名字表曾整套失效
        ("改名后 Passwords 仍被拦", lambda: _mk("Passwords", None, bundle="com.apple.Passwords"),
         VERDICT_DENY, 0),
        # 名字不在表内、只有 bundle 命中 —— 删掉 bundle 判据这一项必须变红
        ("只靠 bundle 命中", lambda: _mk("SomeApp", None, bundle="com.apple.Passwords"),
         VERDICT_DENY, 0),
        # 对偶用例：含"密钥"但不是恢复密钥 → 只能判 UNKNOWN（停手但不按 Esc），
        # 不得判 SECRET。把 SECRET_CN 改回 ("恢复密钥","密钥") 时这一项必须变红。
        ("普通密钥提示不算机密态", lambda: _mk("Finder", ["请输入密钥以访问该磁盘"]),
         VERDICT_UNKNOWN, 0),
    ]
    passed = sum(1 for c in cases if run_case(*c))
    total = len(cases)
    print("\n%d/%d 通过" % (passed, total))
    return passed == total


def main(argv):
    ap = argparse.ArgumentParser(add_help=True)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("scan").set_defaults(fn=cmd_scan)
    sub.add_parser("forward").set_defaults(fn=cmd_forward)
    sub.add_parser("click").set_defaults(fn=cmd_click)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("install-interlock").set_defaults(fn=cmd_install)
    sub.add_parser("remove-interlock").set_defaults(fn=cmd_remove)
    sub.add_parser("self-test").set_defaults(fn=lambda _a: 0 if self_test() else 1)
    ns, rest = ap.parse_known_args(argv)
    if not getattr(ns, "fn", None):
        ap.print_help()
        return 1
    return ns.fn(rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
