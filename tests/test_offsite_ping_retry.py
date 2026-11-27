"""离线镜像的心跳打卡必须重试 —— 否则一次网络抖动 = 一条「镜像失联」假告警。

案发（2026-11-27 03:22 日志）：

    03:22:04 ✅ 镜像完成且校验通过
    03:22:14 打卡失败（hc-ping.com）：URLError

镜像**成功了**，只有打卡那一步失败，healthchecks 于是判 down 并在 05:21 推告警。
打卡是幂等 GET，重试没有副作用；不重试则把「网络抖一下」变成「半夜叫醒人」。
"""

import importlib.util
import pathlib
import sys
import unittest
import urllib.error

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "bin"))

spec = importlib.util.spec_from_file_location("offsite", BASE / "bin" / "wb-offsite-mirror.py")
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


class FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestPingRetry(unittest.TestCase):
    def setUp(self):
        # 不真的 sleep：重试语义与等待时长无关
        self._orig_sleep = mirror.time.sleep
        mirror.time.sleep = lambda *_a, **_k: None
        self._orig_url = mirror._ping_url
        mirror._ping_url = lambda: "https://hc-ping.example/abc"

    def tearDown(self):
        mirror.time.sleep = self._orig_sleep
        mirror._ping_url = self._orig_url

    def test_retries_until_success(self):
        """连续失败两次、第三次成功 → 返回成功，且注明是第几次。"""
        calls = []

        def fake_urlopen(url, timeout=10):  # noqa: ARG001
            calls.append(url)
            if len(calls) < 3:
                raise urllib.error.URLError("temporary")
            return FakeResp()

        orig = mirror.urllib.request.urlopen
        mirror.urllib.request.urlopen = fake_urlopen
        try:
            out = mirror._ping("")
        finally:
            mirror.urllib.request.urlopen = orig

        self.assertIn("HTTP 200", out)
        self.assertIn("第 3 次成功", out)
        self.assertEqual(len(calls), 3)

    def test_all_attempts_fail_reports_count(self):
        """全失败 → 不抛异常，且明确写出重试了几次。"""
        def always_fail(url, timeout=10):  # noqa: ARG001
            raise urllib.error.URLError("down")

        orig = mirror.urllib.request.urlopen
        mirror.urllib.request.urlopen = always_fail
        try:
            out = mirror._ping("")
        finally:
            mirror.urllib.request.urlopen = orig

        self.assertIn(mirror.PING_ATTEMPTS.__str__(), out)
        self.assertIn("打卡失败", out)

    def test_first_attempt_success_has_no_retry_note(self):
        """一次就成时不要写「第 1 次成功」—— 日志要能一眼区分有没有靠重试。"""
        orig = mirror.urllib.request.urlopen
        mirror.urllib.request.urlopen = lambda url, timeout=10: FakeResp()
        try:
            out = mirror._ping("")
        finally:
            mirror.urllib.request.urlopen = orig

        self.assertIn("HTTP 200", out)
        self.assertNotIn("次成功", out)


if __name__ == "__main__":
    unittest.main()
