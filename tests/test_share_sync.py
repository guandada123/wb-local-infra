"""share/ 与 live 的逐字节同步闸门（2026-11-23 建立）。

为什么需要这一层：`~/.local/share/hub-overview/index.html` 是工作台页面，
它曾经只存在于 WorkBuddy 会话工作区与 live 两份、没有任何版本控制，
2026-11-23 会话工作区被平台生命周期清理后几乎全丢。

同步闸门与 bin/ 那套同型：本仓 share/ 是源，live 是部署副本，二者必须逐字节一致。
live 有漂移（被手改过）就红，防止「改了没回迁」悄悄滋生。

跑法：
    python3 -m unittest tests.test_share_sync -v
    LIVE_SHARE=/tmp/fake python3 -m unittest tests.test_share_sync -v   # 隔离环境
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHARE = REPO / "share"
LIVE_SHARE = Path(os.environ.get("LIVE_SHARE", str(Path.home() / ".local" / "share")))


def compare(src_root: Path, dst_root: Path) -> list[str]:
    """返回差异描述列表；空列表 = 全部一致。找不到对应的 live 文件也算差异。"""
    problems: list[str] = []
    if not src_root.is_dir():
        return [f"源目录不存在: {src_root}"]
    for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        if not dst.exists():
            problems.append(f"未部署: share/{rel}")
        elif dst.read_bytes() != src.read_bytes():
            problems.append(f"已漂移(live≠仓): share/{rel}")
    return problems


class TestShareSync(unittest.TestCase):
    def test_every_repo_file_is_deployed(self):
        missing = [
            str(p.relative_to(SHARE))
            for p in SHARE.rglob("*")
            if p.is_file() and not (LIVE_SHARE / p.relative_to(SHARE)).exists()
        ]
        self.assertEqual(missing, [], f"这些文件在仓里但没装到 {LIVE_SHARE}: {missing}")

    def test_no_drift(self):
        problems = compare(SHARE, LIVE_SHARE)
        self.assertEqual(
            problems,
            [],
            "share/ 与 live 不一致。改页面改仓内 share/，再跑 "
            "bash workbench/install-hub-overview.sh --apply；禁止只改 live。\n"
            + "\n".join(problems),
        )

    def test_gate_can_turn_red(self):
        """负控：闸门自己必须能被正样本击破，否则它只是装饰。"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src"
            dst = Path(td) / "dst"
            (src / "a").mkdir(parents=True)
            (dst / "a").mkdir(parents=True)
            (src / "a" / "x.html").write_bytes(b"one")
            (dst / "a" / "x.html").write_bytes(b"one")
            self.assertEqual(compare(src, dst), [], "一致时应无差异")

            (dst / "a" / "x.html").write_bytes(b"two")   # 只改 live 一个字节
            self.assertTrue(compare(src, dst), "live 漂移时闸门必须报红")

            shutil.copyfile(src / "a" / "x.html", dst / "a" / "x.html")
            self.assertEqual(compare(src, dst), [], "恢复后应重新变绿")

            (dst / "a" / "x.html").unlink()              # 整个文件缺失
            self.assertTrue(compare(src, dst), "文件缺失时闸门必须报红")


if __name__ == "__main__":
    unittest.main()
