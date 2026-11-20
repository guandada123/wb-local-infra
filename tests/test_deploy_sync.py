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
        if not self.DEPLOY.is_dir():
            self.skipTest("Claw deploy 目录不存在（跨仓检查在无 Claw 环境下跳过）")
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
        self.assertIn("plist 问题「快照检查自身失败", r.stdout, f"未识别为检查失败\nstdout={r.stdout}")
        self.assertNotIn("OK:", r.stdout, "检查失败却报了 OK（fail-open 回归）")

    def test_missing_tests_dir_is_not_ok(self):
        """tests 目录消失（unittest rc=5，无断言消息）→ 必须报问题而不是 OK。"""
        shutil.rmtree(self.repo / "tests")
        r = self._run()
        self.assertIn("脚本问题「unittest 失败 rc=", r.stdout, f"未识别为检查失败\nstdout={r.stdout}")
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
