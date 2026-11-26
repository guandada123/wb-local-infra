"""推送脚本的重试语义：只在「消息肯定没送到」时重试。

为什么单独立测试：2026-11-26 之前 _post 对 TimeoutError 也重试，而读超时时服务端
可能已经把消息发出去了 —— 重试会在飞书群里造成重复日报。改成只重试连接类错误后，
这里用假 urlopen 把两种情形钉死。
"""

import importlib.util
import json
import pathlib
import socket
import sys
import unittest
import urllib.error

BASE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "bin"))

spec = importlib.util.spec_from_file_location("feishu_push", BASE / "bin" / "autoloop-feishu-push.py")
push = importlib.util.module_from_spec(spec)
spec.loader.exec_module(push)


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload


class ConnectOnlyTest(unittest.TestCase):
    def test_connection_reset_counts_as_not_delivered(self):
        self.assertTrue(push._connect_only(ConnectionResetError()))

    def test_timeout_does_not_count_as_not_delivered(self):
        self.assertFalse(push._connect_only(TimeoutError()))

    def test_urlerror_wrapping_gaierror_counts_as_not_delivered(self):
        self.assertTrue(push._connect_only(urllib.error.URLError(socket.gaierror())))

    def test_urlerror_wrapping_timeout_does_not_count(self):
        self.assertFalse(push._connect_only(urllib.error.URLError(TimeoutError())))

    def test_plain_oserror_does_not_count(self):
        self.assertFalse(push._connect_only(OSError()))


class PostRetryTest(unittest.TestCase):
    def setUp(self):
        self._urlopen = push.urllib.request.urlopen
        self._sleep = push.time.sleep
        push.time.sleep = lambda _s: None

    def tearDown(self):
        push.urllib.request.urlopen = self._urlopen
        push.time.sleep = self._sleep

    def test_timeout_is_raised_at_once_so_no_duplicate_message(self):
        calls = []

        def boom(*_a, **_k):
            calls.append(1)
            raise TimeoutError("read timed out")

        push.urllib.request.urlopen = boom
        with self.assertRaises(TimeoutError):
            push._post({"a": 1}, "tok")
        self.assertEqual(len(calls), 1, "读超时不应重试，否则可能重复投递")

    def test_connection_failure_is_retried_then_succeeds(self):
        calls = []

        def flaky(*_a, **_k):
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionResetError("reset by peer")
            return FakeResponse({"code": 0, "data": {"message_id": "om_1"}})

        push.urllib.request.urlopen = flaky
        d = push._post({"a": 1}, "tok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(d["data"]["message_id"], "om_1")

    def test_connection_failure_gives_up_after_attempts(self):
        calls = []

        def always(*_a, **_k):
            calls.append(1)
            raise ConnectionRefusedError("refused")

        push.urllib.request.urlopen = always
        with self.assertRaises(ConnectionRefusedError):
            push._post({"a": 1}, "tok")
        self.assertEqual(len(calls), push.SEND_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
