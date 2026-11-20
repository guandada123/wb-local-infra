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


if __name__ == "__main__":
    unittest.main(verbosity=2)

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
