"""探活重试（P1）：单次失败不得直接判宕机。

背景（2026-11-26 复盘）：工作台探针每 600s 打一次 `/api/hub/overview`，而该接口的
采集缓存 `CACHE_TTL=5` 秒、采集里有一串 15s 级阻塞调用且**没有单飞去重**。探针单次
8s 预算撞上采集窄窗就 `TimeoutError`，连续 5 次「10 分钟内自愈」的红卡都是这么来的。

P1 的口径：**判死前先补探一次**（默认 30s 后）。两次都失败才发 🔴；只要有一次成功
就是 up。「补探前状态先不落盘」很关键 —— 否则状态文件被写成 down，下一拍哪怕恢复
也会补发一条 🔴。

本测试把几条行为钉死：①首次失败 + 补探成功 → 不告警且状态仍 up；②两次都失败 →
必须告警 down；③补探本身抛异常 → 按失败处理（fail-closed，不许吞成 up）；
④首次就成功 → 不许补探（不白加 30s 与二次采集负载）。
"""

import importlib.util
import pathlib
import unittest
from unittest import mock

BASE = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hub_watch_retry", BASE / "bin" / "hub-overview-watch.py"
)
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

OK = (True, "ok · 5 源 · 10 KPI", [])
BAD = (False, "TimeoutError: timed out", [])


def _run_main(seq, argv_extra):
    """跑一次 main()，返回 (rc, 发出去的告警, 落盘状态, 探活次数)。"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        state = pathlib.Path(td) / "s"
        state.write_text("up", encoding="utf-8")
        calls = {"n": 0}

        def fake_probe():
            i = calls["n"]
            calls["n"] += 1
            return seq[min(i, len(seq) - 1)]

        sent = []
        argv = ["x", "--state-file", str(state), *argv_extra]
        with mock.patch.object(watch, "probe", fake_probe), \
             mock.patch.object(watch, "notify", lambda t: sent.append(t) or True), \
             mock.patch.object(watch.time, "sleep", lambda _s: None), \
             mock.patch.object(watch.sys, "argv", argv):
            rc = watch.main()
        raw = state.read_text(encoding="utf-8").strip()
        return rc, sent, raw, calls["n"]


class TestProbeWithRetry(unittest.TestCase):
    def _call(self, results, prior_state="up", delay=0.0):
        calls = {"n": 0}

        def fake_probe():
            i = calls["n"]
            calls["n"] += 1
            r = results[min(i, len(results) - 1)]
            if isinstance(r, BaseException):
                raise r
            return r

        slept = []
        with mock.patch.object(watch, "probe", fake_probe), \
             mock.patch.object(watch.time, "sleep", lambda s: slept.append(s)):
            ok, _detail, _errs = watch.probe_with_retry(prior_state=prior_state, retry_delay=delay)
        return ok, calls["n"], slept

    def test_first_fail_retry_ok_is_up_and_silent(self):
        # 核心回归：旧实现（无补探）在这里会发 🔴 —— 这正是 5 次误报的成因。
        ok, attempts, slept = self._call([BAD, OK])
        self.assertTrue(ok, "首次失败、补探成功 → 必须判 up")
        self.assertEqual(attempts, 2, "首次失败后必须真的补探一次")
        self.assertTrue(slept, "补探前应等待 retry_delay（默认 30s）")
        notify, kind = watch.decide("up", [], ok, [])
        self.assertFalse(notify, "恢复态+补探成功不得告警")
        self.assertIsNone(kind)

    def test_both_fail_reports_down(self):
        ok, attempts, _slept = self._call([BAD, BAD])
        self.assertFalse(ok, "两次都失败才判 down")
        self.assertEqual(attempts, 2, "两次都失败意味着补探也跑过")
        notify, kind = watch.decide("up", [], ok, [])
        self.assertTrue(notify)
        self.assertEqual(kind, "down")

    def test_retry_exception_is_treated_as_failure(self):
        # fail-closed：补探抛异常不能被当成成功。
        ok, attempts, _slept = self._call([BAD, RuntimeError("boom")])
        self.assertFalse(ok)
        self.assertEqual(attempts, 2)

    def test_first_ok_no_retry(self):
        ok, attempts, slept = self._call([OK])
        self.assertTrue(ok)
        self.assertEqual(attempts, 1, "首次成功不该多打一次")
        self.assertFalse(slept)

    def test_no_retry_when_recovering_from_down(self):
        # 已经是 down 时再探失败，补探不改变结论，省掉 30s 等待与二次负载。
        ok, attempts, _slept = self._call([BAD], prior_state="down")
        self.assertFalse(ok)
        self.assertEqual(attempts, 1, "down 状态的再次失败 → 不补探")


class TestMainWiring(unittest.TestCase):
    """main 集成：--probe-once 关掉内层补探后，外层仍须「两次才判死」。"""

    def test_main_retry_ok_sends_nothing(self):
        rc, sent, raw, attempts = _run_main([BAD, OK], ["--probe-once", "--probe-retry-delay", "0"])
        self.assertEqual(rc, 0)
        self.assertEqual(sent, [], "补探成功 → 不得发红卡")
        self.assertEqual(watch.read_state()[0] if False else raw.split(":")[0], "up",
                         "补探成功 → 状态必须仍为 up")
        self.assertEqual(attempts, 2)

    def test_main_both_fail_sends_one_red(self):
        rc, sent, raw, attempts = _run_main([BAD, BAD], ["--probe-once", "--probe-retry-delay", "0"])
        self.assertEqual(rc, 1)
        self.assertEqual(len(sent), 1, "两次都失败 → 恰好一条红卡")
        self.assertIn("中台工作台 API 不可用", sent[0])
        self.assertEqual(raw.split(":")[0], "down")
        self.assertEqual(attempts, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
