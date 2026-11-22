"""verbatim 同步测试：仓内 bin/ 与已部署 ~/.local/bin 必须逐字节一致。

背景（2026-11-20）：中台脚本长期「活源在 ~/.local/bin + 仓内快照」，快照漂移
曾导致两次返工（push_card 注释 / executor resolve 修复后的手工同步）。本测试
把「仓为唯一源」变成可执行闸门：任何一侧改动未同步，测试即红。

用法：
    python3 -m unittest discover -s tests -v
    # 或指定其他部署目录：
    LIVE_BIN=/tmp/fakebin python3 -m unittest discover -s tests -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
LIVE = Path(os.environ.get("LIVE_BIN", str(Path.home() / ".local" / "bin")))


class TestDeploySync(unittest.TestCase):
    def test_bin_dir_not_empty(self):
        files = [f for f in BIN.iterdir() if f.is_file()]
        self.assertGreater(len(files), 20, f"bin/ 源数量异常: {len(files)}")

    def test_all_bin_files_deployed_verbatim(self):
        missing, mismatched = [], []
        for f in sorted(BIN.iterdir()):
            if not f.is_file():
                continue
            live = LIVE / f.name
            if not live.exists():
                missing.append(f.name)
                continue
            if live.read_bytes() != f.read_bytes():
                mismatched.append(f.name)
        self.assertEqual(
            [],
            missing,
            f"未部署到 {LIVE}: {missing}\n修法: ./install.sh --apply",
        )
        self.assertEqual(
            [],
            mismatched,
            f"live 已漂移(仓为唯一源): {mismatched}\n修法: 把 live 改动回迁 bin/ 后提交，或 ./install.sh --apply 以仓覆盖",
        )


class TestClawMirrorSync(unittest.TestCase):
    """Claw .workbuddy/deploy/ 的脚本与 plist 部署版必须与 live 逐字节一致。

    这 14+ 个脚本的真源在 Claw 仓（有 git 历史），live 是部署副本；此前只有
    executor / push_card 两个配了 verbatim 测试，其余漂移无人管（审计 A4）。
    动态扫描 deploy 目录：未来新增的镜像自动纳入，无需改测试。
    """

    CLAW = Path(os.environ.get("CLAW_HOME", str(Path.home() / "WorkBuddy" / "Claw")))
    DEPLOY = CLAW / ".workbuddy" / "deploy"
    AGENTS = Path.home() / "Library" / "LaunchAgents"

    def _live_for_script(self, f: Path):
        for cand in (LIVE / f.name, LIVE / f.stem):
            if cand.exists():
                return cand
        return None

    def test_deploy_artifacts_verbatim(self):
        # 审计 P2-6：原实现 Claw 缺失就 skipTest —— 路径改名/卷未挂载时整类检查静默变绿，
        # 属「失败=安静」。改为默认 fail，只有显式 SKIP_CLAW=1 才允许跳过。
        if not self.DEPLOY.is_dir():
            if os.environ.get("SKIP_CLAW") == "1":
                self.skipTest(f"Claw deploy 不存在且 SKIP_CLAW=1：显式跳过（{self.DEPLOY}）")
            self.fail(
                f"Claw deploy 目录不存在: {self.DEPLOY} —— 跨仓镜像检查无法执行。"
                "若本机确实没有 Claw，用 SKIP_CLAW=1 显式跳过；不要让它静默变绿。"
            )
        missing, mismatched = [], []
        for f in sorted(self.DEPLOY.iterdir()):
            if not f.is_file() or f.suffix == ".template" or f.name.startswith("test_"):
                continue
            if f.suffix == ".plist":
                live = self.AGENTS / f.name
            elif f.suffix == ".py":
                live = self._live_for_script(f)
            else:
                continue
            if live is None or not live.exists():
                missing.append(f.name)
                continue
            if live.read_bytes() != f.read_bytes():
                mismatched.append(f.name)
        self.assertEqual([], missing, f"deploy 有未部署文件: {missing}")
        self.assertEqual([], mismatched, f"已漂移(live≠deploy): {mismatched}\n修法: 以 Claw 仓为源重新部署，或把 live 改动回迁 Claw 后提交")


class TestInstallModes(unittest.TestCase):
    """install.sh 的 plist 两个模式（--plists / --snapshot-plists）必须有闸门。

    2026-11-20 审计 S3：这两个模式只做了手工四向验证，不在 unittest 内，
    而每日 launchd 检查只跑 unittest —— 逻辑退化永远不会被发现。
    全部用 tmpdir（AGENTS 注入），不触碰真实 ~/Library/LaunchAgents。
    """

    REPO = Path(__file__).resolve().parent.parent
    INSTALL = REPO / "install.sh"
    SNAP = REPO / "launchd"
    REAL_AGENTS = Path.home() / "Library" / "LaunchAgents"

    def _expected_plist_names(self):
        """active.txt 里非 [deploy] 的 job（= 本仓负责补装的集合）。"""
        names = []
        for line in (self.SNAP / "active.txt").read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#") or line.startswith("[deploy] "):
                continue
            names.append(line.strip())
        return set(names)

    def _run(self, *flags, agents, extra=None):
        env = {**os.environ, "AGENTS": str(agents)}
        env.update(extra or {})
        return subprocess.run(
            ["/bin/bash", str(self.INSTALL), *flags],
            capture_output=True, text=True, timeout=120, env=env,
        )

    def test_plists_install_missing_only(self):
        expected = self._expected_plist_names()
        self.assertTrue(expected, "active.txt 未解析出任何非 deploy job")
        with tempfile.TemporaryDirectory() as td:
            r = self._run("--plists-apply", agents=td)
            self.assertEqual(0, r.returncode, r.stderr)
            got = {p.name for p in Path(td).glob("*.plist")}
            self.assertEqual(expected, got, f"补装集合不符\nstdout={r.stdout}")
            # 幂等：第二次运行不得再装任何东西（绝不覆盖已有）
            r2 = self._run("--plists-apply", agents=td)
            self.assertIn("补装=0", r2.stdout, f"非幂等\nstdout={r2.stdout}")

    def test_snapshot_detects_drift(self):
        if not self.REAL_AGENTS.is_dir():
            self.skipTest("无 ~/Library/LaunchAgents，跳过漂移探测测试")
        names = self._expected_plist_names()
        with tempfile.TemporaryDirectory() as td:
            copied = 0
            for n in names:
                src = self.REAL_AGENTS / n
                if src.exists():
                    (Path(td) / n).write_bytes(src.read_bytes())
                    copied += 1
            if copied == 0:
                self.skipTest("真实 plist 一个都没拷到，跳过")
            # 全量一致时：刷新数应为 0
            r0 = self._run("--snapshot-plists", agents=td)
            self.assertRegex(r0.stdout, r"刷新=0", f"一致时不应报刷新\nstdout={r0.stdout}")
            # 人为改一个字节：应恰好报 1 个刷新
            victim = sorted(Path(td).glob("*.plist"))[0]
            victim.write_bytes(victim.read_bytes() + b"\n")
            r1 = self._run("--snapshot-plists", agents=td)
            self.assertRegex(r1.stdout, r"刷新=1", f"漂移未被检出\nstdout={r1.stdout}")

    def test_snapshot_apply_refuses_nondefault_agents(self):
        """AGENTS 非默认 + apply → 必须拒绝（否则临时目录会覆盖仓内快照）。"""
        before = {p.name: p.read_bytes() for p in self.SNAP.glob("*.plist")}
        with tempfile.TemporaryDirectory() as td:
            for n in self._expected_plist_names():
                src = self.REAL_AGENTS / n
                if src.exists():
                    (Path(td) / n).write_bytes(src.read_bytes() + b"\n")
            r = self._run("--snapshot-plists-apply", agents=td)
        self.assertNotEqual(0, r.returncode, f"应拒绝但成功了\nstdout={r.stdout}")
        after = {p.name: p.read_bytes() for p in self.SNAP.glob("*.plist")}
        self.assertEqual(before, after, "被拒的 apply 仍改写了仓内快照")


    def _fake_agents(self, td):
        """造 3 个假 job：2 个 ad-hoc + 1 个 deploy 托管。"""
        agents = Path(td) / "agents"
        deploy = Path(td) / "deploy"
        agents.mkdir(); deploy.mkdir()
        for n in ("com.user.fake-a.plist", "com.user.fake-b.plist", "com.user.wb-heartbeat.plist"):
            (agents / n).write_bytes(b"<plist/>")
        (deploy / "com.user.wb-heartbeat.plist").write_bytes(b"<plist/>")
        return agents, deploy

    def test_regen_active_preview_marks_deploy_and_counts(self):
        """清单重建：deploy 项要打标、统计要与内容一致（统计口径 bug 曾使输出恒 0）。"""
        with tempfile.TemporaryDirectory() as td:
            agents, deploy = self._fake_agents(td)
            r = self._run("--regen-active", agents=agents,
                          extra={"CLAW_DEPLOY": str(deploy)})
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn("[deploy] com.user.wb-heartbeat.plist", r.stdout)
            self.assertIn("        com.user.fake-a.plist", r.stdout)
            self.assertIn("deploy=1 ad-hoc=2", r.stdout, f"统计与内容不一致\nstdout={r.stdout}")

    def test_regen_apply_refuses_nondefault_agents(self):
        before = (self.SNAP / "active.txt").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            agents, deploy = self._fake_agents(td)
            r = self._run("--regen-active-apply", agents=agents,
                          extra={"CLAW_DEPLOY": str(deploy)})
        self.assertNotEqual(0, r.returncode, "应拒绝非默认 AGENTS 的落盘")
        self.assertEqual(before, (self.SNAP / "active.txt").read_bytes(), "被拒的 apply 仍改了清单")

    def test_regen_apply_force_writes_target_only(self):
        """FORCE=1 + ACTIVE_OUT 指向临时文件 → 写到临时文件，仓内清单不动。"""
        before = (self.SNAP / "active.txt").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            agents, deploy = self._fake_agents(td)
            out = Path(td) / "active.txt"
            r = self._run("--regen-active-apply", agents=agents,
                          extra={"CLAW_DEPLOY": str(deploy), "ACTIVE_OUT": str(out), "FORCE": "1"})
            self.assertEqual(0, r.returncode, r.stderr)
            written = out.read_text(encoding="utf-8")
            self.assertIn("[deploy] com.user.wb-heartbeat.plist", written)
            self.assertIn("        com.user.fake-b.plist", written)
        self.assertEqual(before, (self.SNAP / "active.txt").read_bytes(), "仓内清单被意外改写")

    def test_snapshot_dry_run_does_not_write_repo(self):
        before = {p.name: p.read_bytes() for p in self.SNAP.glob("*.plist")}
        with tempfile.TemporaryDirectory() as td:
            for n in self._expected_plist_names():
                src = self.REAL_AGENTS / n
                if src.exists():
                    (Path(td) / n).write_bytes(src.read_bytes() + b"\n")  # 故意全部"漂移"
            self._run("--snapshot-plists", agents=td)  # dry-run
        after = {p.name: p.read_bytes() for p in self.SNAP.glob("*.plist")}
        self.assertEqual(before, after, "dry-run 污染了仓内快照（apply 才该落盘）")


if __name__ == "__main__":
    unittest.main(verbosity=2)

class TestCheckFailSafe(unittest.TestCase):
    """每日检查器必须 fail-safe：检查跑不成 ≠ 没问题（审计 P0-1）。

    历史 bug：终判用「reason 文本为空 + stale==0」，于是 unittest 崩溃、active.txt 丢失时
    两处都"空" → 报 OK。删掉 tests/ 目录都能拿到 OK，比没闸门更危险。
    这里用合成小仓（不依赖真环境）注入三种状态，负样本必须绿、故障态必须红。
    """

    REPO = Path(__file__).resolve().parent.parent
    CHECK = REPO / "bin" / "infra-sync-check"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="chk_fail_"))
        repo = self.tmp / "repo"
        for d in ("bin", "tests", "launchd"):
            (repo / d).mkdir(parents=True)
        shutil.copy2(self.REPO / "install.sh", repo / "install.sh")
        (repo / "bin" / "dummy.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
        (repo / "tests" / "test_smoke.py").write_text(
            "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
            encoding="utf-8")
        (repo / "launchd" / "active.txt").write_text("# 空清单\n", encoding="utf-8")
        self.repo = repo
        self.live = self.tmp / "live"
        self.live.mkdir()
        shutil.copy2(repo / "bin" / "dummy.sh", self.live / "dummy.sh")
        self.agents = self.tmp / "agents"
        self.agents.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        env = {**os.environ,
               "REPO_OVERRIDE": str(self.repo),
               "LOG_OVERRIDE": str(self.tmp / "chk.log"),
               "AGENTS": str(self.agents),
               "LIVE_BIN": str(self.live),
               "CLAW_HOME": str(self.tmp / "no-claw"),
               "DRY_RUN": "1"}
        return subprocess.run(["/bin/bash", str(self.CHECK)],
                              capture_output=True, text=True, timeout=120, env=env)

    def test_normal_state_reports_ok(self):
        """负样本（防"测试永远红"）：一切正常时必须报 OK。"""
        r = self._run()
        self.assertIn("OK:", r.stdout, f"正常态未报 OK\nstdout={r.stdout}\nstderr={r.stderr}")

    def test_missing_active_list_is_not_ok(self):
        """active.txt 丢失 → 快照检查失败，必须报问题而不是 OK。"""
        (self.repo / "launchd" / "active.txt").unlink()
        r = self._run()
        # 只断言语义片段，不锁死外层措辞（否则一改文案就假红）
        self.assertIn("快照检查自身失败", r.stdout, f"未识别为检查失败\nstdout={r.stdout}")
        self.assertNotIn("OK:", r.stdout, "检查失败却报了 OK（fail-open 回归）")

    def _install_index_script(self):
        shutil.copy2(self.REPO / "bin" / "archive-index.py", self.repo / "bin" / "archive-index.py")

    def test_stale_archive_index_is_not_ok(self):
        """_archive 变动后索引过期 → 必须报问题（审计建议的第三类检查）。"""
        arc = self.tmp / "archive"
        arc.mkdir()
        (arc / "a.tgz").write_bytes(b"x")
        self._install_index_script()
        env_extra = {"ARCHIVE_DIR": str(arc)}
        # 先建索引（一致状态）
        subprocess.run([sys.executable, str(self.repo / "bin" / "archive-index.py"), "--dir", str(arc)],
                       capture_output=True, text=True, timeout=60)
        r0 = self._run()
        self.assertIn("OK:", r0.stdout, f"一致时应 OK\nstdout={r0.stdout}")
        # 新增文件 → 索引过期
        (arc / "b.tgz").write_bytes(b"y")
        env = {**os.environ, "REPO_OVERRIDE": str(self.repo), "LOG_OVERRIDE": str(self.tmp / "chk.log"),
               "AGENTS": str(self.agents), "LIVE_BIN": str(self.live),
               "CLAW_HOME": str(self.tmp / "no-claw"), "DRY_RUN": "1", **env_extra}
        r1 = subprocess.run(["/bin/bash", str(self.CHECK)], capture_output=True, text=True, timeout=120, env=env)
        self.assertIn("与 _archive 不一致", r1.stdout, f"未识别索引过期\nstdout={r1.stdout}")
        self.assertNotIn("OK:", r1.stdout, "索引过期却报 OK")

    def test_missing_archive_index_is_skipped(self):
        """索引不存在（rc=2）→ 跳过而非报错（新机/未生成过不应天天告警）。"""
        arc = self.tmp / "archive-noidx"
        arc.mkdir()
        (arc / "a.tgz").write_bytes(b"x")
        self._install_index_script()
        env = {**os.environ, "REPO_OVERRIDE": str(self.repo), "LOG_OVERRIDE": str(self.tmp / "chk.log"),
               "AGENTS": str(self.agents), "LIVE_BIN": str(self.live),
               "CLAW_HOME": str(self.tmp / "no-claw"), "DRY_RUN": "1", "ARCHIVE_DIR": str(arc)}
        r = subprocess.run(["/bin/bash", str(self.CHECK)], capture_output=True, text=True, timeout=120, env=env)
        self.assertIn("OK:", r.stdout, f"无索引时应跳过并 OK\nstdout={r.stdout}")


    def test_runs_with_empty_environment(self):
        """launchd 的空环境（无 HOME、PATH 只有系统目录）下必须能跑完。

        实测事故：launchd 下 HOME 未设置 → `set -u` 直接死于 "HOME: unbound variable"，
        每日检查从未真正执行也不报错；node 不在 PATH → 卡片发送失败、告警静默丢失。
        """
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin",   # 故意不继承 os.environ
               "REPO_OVERRIDE": str(self.repo), "LOG_OVERRIDE": str(self.tmp / "chk.log"),
               "AGENTS": str(self.agents), "LIVE_BIN": str(self.live),
               "CLAW_HOME": str(self.tmp / "no-claw"), "DRY_RUN": "1"}
        r = subprocess.run(["/bin/bash", str(self.CHECK)], capture_output=True, text=True,
                           timeout=180, env=env)
        self.assertNotIn("unbound variable", r.stderr, f"环境变量缺失导致崩溃\nstderr={r.stderr}")
        self.assertIn("OK:", r.stdout, f"空环境下未完成检查\nstdout={r.stdout}\nstderr={r.stderr}")


    def test_missing_cwd_anchor_is_not_ok(self):
        """cwd 锚点目录被删 → 必须报（对应 12 条自动化会失联，2026-11-20 踩过）。"""
        anchors = self.repo / "launchd" / "cwd-anchors.txt"
        anchors.write_text("# test\n/tmp/no-such-anchor-dir-xyz  # 测试\n", encoding="utf-8")
        r = self._run()
        self.assertIn("cwd 锚点缺失", r.stdout, f"未识别锚点缺失\nstdout={r.stdout}")
        self.assertNotIn("OK:", r.stdout, "锚点缺失却报 OK")

    def test_present_cwd_anchor_keeps_ok(self):
        """锚点存在 → 不误报（避免天天告警）。"""
        anchors = self.repo / "launchd" / "cwd-anchors.txt"
        anchors.write_text("# test\n" + str(self.tmp) + "  # 存在的目录\n", encoding="utf-8")
        r = self._run()
        self.assertIn("OK:", r.stdout, f"锚点存在却报问题\nstdout={r.stdout}")

    def test_missing_tests_dir_is_not_ok(self):
        """tests 目录消失（unittest rc=5，无断言消息）→ 必须报问题而不是 OK。"""
        shutil.rmtree(self.repo / "tests")
        r = self._run()
        self.assertIn("unittest 失败 rc=", r.stdout, f"未识别为检查失败\nstdout={r.stdout}")
        self.assertNotIn("OK:", r.stdout, "检查失败却报了 OK（fail-open 回归）")


class TestPlistsValidation(unittest.TestCase):
    """--plists-apply 必须拒装非法 plist（审计 P1-3）：坏 plist 进 LaunchAgents 会被 launchd 拒载，
    DR 场景下用户以为已恢复、实际任务不跑（静默失效）。"""

    REPO = Path(__file__).resolve().parent.parent

    def test_invalid_plist_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            for d in ("launchd", "bin"):
                (repo / d).mkdir(parents=True)
            shutil.copy2(self.REPO / "install.sh", repo / "install.sh")
            (repo / "launchd" / "active.txt").write_text(
                "# test\n        com.user.broken.plist\n", encoding="utf-8")
            (repo / "launchd" / "com.user.broken.plist").write_text("not a plist", encoding="utf-8")
            agents = Path(td) / "agents"
            agents.mkdir()
            r = subprocess.run(["/bin/bash", str(repo / "install.sh"), "--plists-apply"],
                               capture_output=True, text=True, timeout=120,
                               env={**os.environ, "AGENTS": str(agents)})
            self.assertNotEqual(0, r.returncode, f"非法 plist 应导致失败\nstdout={r.stdout}")
            self.assertIn("快照非法", r.stdout)
            self.assertEqual([], list(agents.glob("*.plist")), "非法 plist 被装进目标目录了")

class TestArchiveIndex(unittest.TestCase):
    """archive-index.py 冒烟：能扫出文件、标出未分类、不写盘（--print-only）。"""

    SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "archive-index.py"


    def test_same_prefix_new_file_does_not_inherit_facts(self):
        """审计 P1-2：前缀类不能继承某一份文件的取证事实（否则凭错误证据建议删）。"""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "cron-mail-spool-20270101.mbox").write_bytes(b"x")
            r = subprocess.run([sys.executable, str(self.SCRIPT), "--print-only", "--dir", td],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(0, r.returncode, r.stderr)
            row = [ln for ln in r.stdout.splitlines() if "20270101" in ln][0]
            self.assertIn("本文件未核实", row, f"新文件未标未核实\n{row}")
            self.assertNotIn("356,687", row, f"新文件继承了另一份的事实\n{row}")
            self.assertNotIn("建议删", row, f"未核实的文件给出删除建议\n{row}")

    def test_exact_file_keeps_verified_fact(self):
        """对照：已核实的那一份必须保留事实（别把修复做成"全体失忆"）。"""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "cron-mail-spool-20261012.mbox").write_bytes(b"x")
            r = subprocess.run([sys.executable, str(self.SCRIPT), "--print-only", "--dir", td],
                               capture_output=True, text=True, timeout=60)
            row = [ln for ln in r.stdout.splitlines() if "cron-mail-spool-20261012" in ln][0]
            self.assertIn("356,687", row, f"精确名条目丢了取证事实\n{row}")
            self.assertIn("99.99%", row)
            # 只验事实，不锁「已核实/已处置」这类措辞：措辞会随处置进展变化，
            # 锁死会让文案调整变成假红（2026-11-22 踩过）
            self.assertTrue("移入废纸篓" in row or "已核实" in row, f"缺少处置结论\n{row}")

    def test_print_only_lists_and_flags_unclassified(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "known-thing.tgz").write_bytes(b"x" * 100)
            (d / "mystery.dat").write_bytes(b"y" * 50)
            r = subprocess.run([sys.executable, str(self.SCRIPT), "--print-only", "--dir", td],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn("known-thing.tgz", r.stdout)
            self.assertIn("mystery.dat", r.stdout)
            self.assertIn("未分类", r.stdout)
            self.assertNotIn("INDEX.md", r.stdout, "--print-only 不该把 INDEX.md 自身列进去")
            self.assertFalse((d / "INDEX.md").exists(), "--print-only 不得写盘")

class TestMajiuArchiveIndex(unittest.TestCase):
    """majiu-archive-index.py：总册生成器的核心判据。

    重点不是"能跑"，而是三点：① 数字现算（不写死）；② 归档索引读不到时
    显示"未读到"而不是假的"0 项"；③ --check 三态可区分。
    """

    SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "majiu-archive-index.py"

    def _make_home(self, td: Path, ledger_rows: int = 2, with_index: bool = True) -> Path:
        home = td / "WorkBuddy"
        claw = home / "Claw"
        (claw / ".workbuddy").mkdir(parents=True)
        rows = "\n".join(
            f"| {i} | 任务{i} | task | 出栏 | 2026-11-0{i} | 2026-11-0{i} | 产物 | 备注 |"
            for i in range(1, ledger_rows + 1)
        )
        (claw / "STALL_LOG.md").write_text(
            "# 台账\n\n## 栏位记录\n\n| # | 名称 | kind | 状态 | 开始 | 结束 | 产物 | 备注 |\n"
            "|---|---|---|---|---|---|---|---|\n" + rows + "\n\n## 出栏索引\n\n- x\n",
            encoding="utf-8")
        d = claw / ".workbuddy" / "archive" / "2026-11-22-conversation"
        d.mkdir(parents=True)
        (d / "成果档案.md").write_text("# 成果\n", encoding="utf-8")
        if with_index:
            arc = home / "_archive"
            arc.mkdir()
            (arc / "INDEX.md").write_text(
                "# 归档索引\n\n> 由 x 生成 2026-11-22 13:31｜7 项 / **123.5MB**\n", encoding="utf-8")
        return home

    def _run(self, *args, home):
        return subprocess.run([sys.executable, str(self.SCRIPT), "--workbuddy-home", str(home), *args],
                              capture_output=True, text=True, timeout=120)

    def test_counts_come_from_data(self):
        """台账 3 行 → 标题必须是 3；本机档案 1 份 → 3 节写 1 份。"""
        with tempfile.TemporaryDirectory() as td:
            home = self._make_home(Path(td), ledger_rows=3)
            r = self._run(home=home)
            self.assertEqual(0, r.returncode, r.stderr)
            self.assertIn("台账（3 个栏位）", r.stdout)
            self.assertIn("本机原件（1 份）", r.stdout)
            self.assertNotIn("台账（0 个栏位）", r.stdout)

    def test_archive_index_read_from_file(self):
        """归档索引存在 → 条目数与大小须来自文件（7 项 / 124MB 四舍五入）。"""
        with tempfile.TemporaryDirectory() as td:
            home = self._make_home(Path(td))
            r = self._run(home=home)
            self.assertIn("归档区（7 项 / 124MB）", r.stdout, f"stdout={r.stdout}")

    def test_missing_archive_index_is_not_reported_as_zero(self):
        """索引缺失 → 必须写"未读到索引"，不能出现 0 项（假事实）。"""
        with tempfile.TemporaryDirectory() as td:
            home = self._make_home(Path(td), with_index=False)
            r = self._run(home=home)
            self.assertIn("未读到索引", r.stdout, f"stdout={r.stdout}")
            self.assertNotIn("归档区（0 项", r.stdout, "把读不到当成 0 项 = 假事实")

    def test_library_not_requested_is_stated(self):
        """未加 --with-library → 云端小节必须明说未实读，不能静默空表。"""
        with tempfile.TemporaryDirectory() as td:
            home = self._make_home(Path(td))
            r = self._run(home=home)
            self.assertIn("未实读", r.stdout)

    def test_check_three_states(self):
        """--check：文件不存在 2 / 一致 0 / 改一字节 1。"""
        with tempfile.TemporaryDirectory() as td:
            home = self._make_home(Path(td))
            out = Path(td) / "总册.md"
            missing = self._run("--check", str(out), home=home)
            self.assertEqual(2, missing.returncode)
            gen = self._run("--out", str(out), home=home)
            self.assertEqual(0, gen.returncode, gen.stderr)
            same = self._run("--check", str(out), home=home)
            self.assertEqual(0, same.returncode, same.stdout)
            out.write_text(out.read_text(encoding="utf-8") + "\n补一行\n", encoding="utf-8")
            stale = self._run("--check", str(out), home=home)
            self.assertEqual(1, stale.returncode, stale.stdout)
