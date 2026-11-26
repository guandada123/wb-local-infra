"""数据新鲜度判定：Phase 1 的「只观察不告警」契约，以及 UTC 换算。

为什么要单独立测试：sources 里的时间字段有两种格式 —— hub.db 的 last_run_at 是
**带 Z 的 UTC**（见 server 回执段注释），而 rules.json / QUEUE.md 的 mtime 是本地
+08:00。漏掉 Z 换算会让年龄整整差 8 小时，阈值就被判错一个量级。这里把两种格式、
以及「阈值留空必须静默」用断言钉死。

另注：launchd 与 git 是实时枚举、没有年龄语义，本测试从结构上断言它们不在
SOURCE_TIME_FIELDS 里 —— 防止后人「顺手统一下」把它们加进去，造成假告警。
"""

import importlib.util
import pathlib
import sys
import unittest
from datetime import datetime

BASE = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hub_watch", BASE / "bin" / "hub-overview-watch.py"
)
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

REF = datetime(2026, 11, 26, 19, 0, tzinfo=watch.TZ)


class TestAgeHours(unittest.TestCase):
    def test_utc_z_suffix_converts(self):
        # UTC 10:00 相对北京 19:00 应为 1 小时；若得 9.0 说明漏了 Z 换算。
        self.assertEqual(watch.age_hours("2026-11-26T10:00:00Z", ref=REF), 1.0)

    def test_naive_treated_as_local(self):
        self.assertEqual(watch.age_hours("2026-11-26T18:00:00", ref=REF), 1.0)

    def test_missing_returns_none(self):
        # 必须返回 None 而不是 0：0 会被当成「刚更新过」。
        self.assertIsNone(watch.age_hours(None, ref=REF))

    def test_garbage_returns_none(self):
        self.assertIsNone(watch.age_hours("not-a-time", ref=REF))


class TestStaleSources(unittest.TestCase):
    OLD = {"sources": {"QUEUE.md": {"mtime": "2020-01-01T00:00:00+08:00"}}}

    def test_empty_threshold_is_silent(self):
        # Phase 1 契约：阈值留空时，多旧都不许报。
        self.assertEqual(watch.stale_sources(self.OLD), [])

    def test_threshold_detects(self):
        self.assertEqual(
            watch.stale_sources(self.OLD, thresholds={"QUEUE.md": 24}), ["QUEUE.md"]
        )

    def test_fresh_is_quiet(self):
        fresh = {"sources": {"rules.json": {"mtime": REF.isoformat()}}}
        self.assertEqual(
            watch.stale_sources(fresh, ref=REF, thresholds={"rules.json": 24}), []
        )

    def test_missing_field_is_quiet(self):
        # 宁可漏报，不能假报。
        self.assertEqual(
            watch.stale_sources({"sources": {"QUEUE.md": {}}}, thresholds={"QUEUE.md": 24}),
            [],
        )

    def test_realtime_sources_ignored(self):
        # launchd / git 无年龄语义，硬给阈值也必须忽略。
        payload = {"sources": {"launchd": {"x": 1}, "git": {"x": 1}}}
        self.assertEqual(
            watch.stale_sources(payload, thresholds={"launchd": 0.1, "git": 0.1}), []
        )

    def test_no_sources_key(self):
        self.assertEqual(watch.stale_sources({}, thresholds={"QUEUE.md": 24}), [])

    def test_none_payload(self):
        self.assertEqual(watch.stale_sources(None, thresholds={"QUEUE.md": 24}), [])


class TestSourceTimeFieldMap(unittest.TestCase):
    def test_realtime_sources_absent(self):
        # 结构断言：防止后人把实时源加进来。
        self.assertNotIn("launchd", watch.SOURCE_TIME_FIELDS)
        self.assertNotIn("git", watch.SOURCE_TIME_FIELDS)

    def test_expected_entries(self):
        self.assertEqual(
            watch.SOURCE_TIME_FIELDS,
            {"hub.db": "last_run_at", "rules.json": "mtime", "QUEUE.md": "mtime"},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
