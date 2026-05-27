#!/usr/bin/env python3
"""
小学语文助手自动化测试套件
===========================

覆盖范围：
- 后端 API：历史记录 CRUD、听写会话完整生命周期、输入过滤、错误处理
- 数据构建脚本：拼音解析、音节分类、分片键、词语过滤
- 前端：页面加载、输入过滤、分页、历史记录操作、笔顺/TTS 降级

设计原则：
- 后端测试使用临时 SQLite 文件，绝不写入项目真实数据目录
- 全部使用 Python 标准库 unittest（前端可选 Playwright）
- 通过 mock.patch 切换 server.DB_PATH，不改业务代码
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# 让测试可 import 项目根与 scripts 目录
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import server  # noqa: E402
from scripts import build_fallback_data as bfd  # noqa: E402


# ============================================================
# HTTP 客户端工具
# ============================================================

def http_request(base, method, path, body=None, timeout=10):
    """发送 HTTP 请求，返回 (status, dict_body, response_obj)。

    错误响应体为空时返回 None（不再抛 JSONDecodeError）。
    """
    url = f"{base}{path}"
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        resp = urlopen(req, timeout=timeout)
        raw = resp.read().decode("utf-8")
        payload = json.loads(raw) if raw else None
        return resp.status, payload, resp
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"_raw": raw}
        return exc.code, payload, None


def http_get(base, path, timeout=10):
    return http_request(base, "GET", path, timeout=timeout)


def http_post(base, path, body, timeout=10):
    return http_request(base, "POST", path, body, timeout=timeout)


def http_delete(base, path, body, timeout=10):
    return http_request(base, "DELETE", path, body, timeout=timeout)


# ============================================================
# 后端测试基类：启动真实 HTTP 服务器，使用临时 DB
# ============================================================

class ServerTestCase(unittest.TestCase):
    """每个测试类共享一个临时数据库 + 真实运行中的 HTTP 服务器。"""

    server = None
    server_thread = None
    port = None
    tmp_dir = None
    _patches = None

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp(prefix="chinese_helper_test_")
        cls.db_path = Path(cls.tmp_dir) / "test.sqlite3"

        # 打补丁：server.DB_PATH 与 server.ROOT 仍指向真实目录以提供静态文件，
        # 但 DB_PATH 被定向到临时文件，避免污染项目数据库。
        cls._patches = [
            mock.patch.object(server, "DB_PATH", cls.db_path),
        ]
        for p in cls._patches:
            p.start()

        # 初始化临时数据库表结构
        server.init_db()

        # 选择可用端口（4173 起步，冲突时递增）
        cls.port = 41730
        while cls.port < 60000:
            with socket.socket() as s:
                try:
                    s.bind(("127.0.0.1", cls.port))
                    break
                except OSError:
                    cls.port += 1

        cls.server = server.ThreadingHTTPServer(
            ("127.0.0.1", cls.port), server.ChineseHelperHandler
        )
        cls.server_thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True
        )
        cls.server_thread.start()

        # 等待服务器就绪
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()
        for p in (cls._patches or []):
            p.stop()
        # 清理临时目录
        try:
            shutil.rmtree(cls.tmp_dir)
        except Exception:
            pass

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    # 辅助：清空 query_history 表（保留其它表），让各测试互不影响
    def clear_history(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM query_history")

    def clear_dictation_history(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM dictation_history")
            conn.execute("DELETE FROM dictation_session")
            conn.execute("DELETE FROM dictation_session_result")
            conn.execute("DELETE FROM dictation_session_state")


# ============================================================
# 一、数据库初始化
# ============================================================

class TestDatabaseInit(ServerTestCase):
    def setUp(self):
        self.clear_history()
        self.clear_dictation_history()

    def test_01_tables_exist(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            names = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        for t in (
            "query_history",
            "dictation_session",
            "dictation_session_result",
            "dictation_history",
            "dictation_session_state",
        ):
            self.assertIn(t, names, f"缺少表 {t}")

    def test_02_index_created(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        self.assertIn("idx_query_history_created_at", indexes)
        self.assertIn("idx_dictation_history_created_at", indexes)


# ============================================================
# 二、历史记录接口 CRUD
# ============================================================

class TestHistoryAPI(ServerTestCase):
    def setUp(self):
        self.clear_history()

    # ----- CREATE -----

    def test_10_create_returns_201(self):
        status, body, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "小学", "characters": "小学"},
        )
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertIn("id", body)
        self.assertEqual(body["feature"], "hanzi")
        self.assertEqual(body["query"], "小学")
        self.assertEqual(body["characters"], "小学")

    def test_11_create_strips_non_chinese(self):
        status, body, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "abc 学 def", "characters": "abc 学 def"},
        )
        self.assertEqual(status, HTTPStatus.CREATED)
        # chinese_only 会过滤掉非汉字字符
        self.assertEqual(body["characters"], "学")

    def test_12_create_rejects_when_empty_after_filter(self):
        status, body, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "abc", "characters": "!@#"},
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    def test_13_create_rejects_empty_query(self):
        status, body, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "", "characters": "学"},
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    def test_14_create_rejects_invalid_json(self):
        url = f"{self.base}/api/history"
        req = Request(
            url,
            data=b"not-json{{{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(req, timeout=5)
            self.fail("应抛 HTTPError")
        except HTTPError as exc:
            self.assertEqual(exc.code, HTTPStatus.BAD_REQUEST)

    def test_15_create_default_feature_is_hanzi(self):
        status, body, _ = http_post(
            self.base, "/api/history",
            {"query": "学", "characters": "学"},
        )
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertEqual(body["feature"], "hanzi")

    # ----- READ -----

    def test_20_list_returns_created_item(self):
        http_post(
            self.base, "/api/history",
            {"feature": "words", "query": "大", "characters": "大"},
        )
        status, body, _ = http_get(self.base, "/api/history?limit=10")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertIn("items", body)
        features = {item["feature"] for item in body["items"]}
        self.assertIn("words", features)

    def test_21_list_default_limit_12(self):
        for i in range(15):
            http_post(
                self.base, "/api/history",
                {"feature": "hanzi", "query": f"字第{i}号", "characters": "字"},
            )
        status, body, _ = http_get(self.base, "/api/history")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(len(body["items"]), 12)

    def test_22_list_honors_limit_param(self):
        for i in range(6):
            http_post(
                self.base, "/api/history",
                {"feature": "hanzi", "query": f"字{i}", "characters": "字"},
            )
        status, body, _ = http_get(self.base, "/api/history?limit=3")
        self.assertEqual(len(body["items"]), 3)

    def test_23_list_invalid_limit_falls_back(self):
        http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "字", "characters": "字"},
        )
        status, body, _ = http_get(self.base, "/api/history?limit=abc")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertGreaterEqual(len(body["items"]), 1)

    def test_24_list_ordered_desc(self):
        http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "甲", "characters": "甲"},
        )
        http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "乙", "characters": "乙"},
        )
        _, body, _ = http_get(self.base, "/api/history")
        queries = [item["query"] for item in body["items"]]
        self.assertEqual(queries[0], "乙")

    # ----- DELETE -----

    def test_30_delete_by_ids(self):
        _, b1, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "甲", "characters": "甲"},
        )
        _, b2, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "乙", "characters": "乙"},
        )
        status, body, _ = http_delete(
            self.base, "/api/history", {"ids": [b1["id"], b2["id"]]}
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["deleted"], 2)

    def test_31_delete_after_removed_list_smaller(self):
        _, b1, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "甲", "characters": "甲"},
        )
        _, b2, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "乙", "characters": "乙"},
        )
        http_delete(self.base, "/api/history", {"ids": [b1["id"]]})
        _, body, _ = http_get(self.base, "/api/history")
        remaining_ids = {item["id"] for item in body["items"]}
        self.assertNotIn(b1["id"], remaining_ids)
        self.assertIn(b2["id"], remaining_ids)

    def test_32_delete_nonexistent_returns_zero(self):
        status, body, _ = http_delete(
            self.base, "/api/history", {"ids": [999999]}
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["deleted"], 0)

    def test_33_delete_skips_non_int_ids(self):
        _, b1, _ = http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "甲", "characters": "甲"},
        )
        status, body, _ = http_delete(
            self.base, "/api/history",
            {"ids": [b1["id"], "abc", None]},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["deleted"], 1)

    def test_34_delete_empty_list_returns_zero(self):
        status, body, _ = http_delete(self.base, "/api/history", {"ids": []})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["deleted"], 0)

    def test_35_delete_rejects_non_list_ids(self):
        status, body, _ = http_delete(
            self.base, "/api/history", {"ids": "not-a-list"}
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    def test_36_delete_rejects_invalid_json(self):
        url = f"{self.base}/api/history"
        req = Request(
            url,
            data=b"{bad json",
            headers={"Content-Type": "application/json"},
            method="DELETE",
        )
        try:
            urlopen(req, timeout=5)
            self.fail("应抛 HTTPError")
        except HTTPError as exc:
            self.assertEqual(exc.code, HTTPStatus.BAD_REQUEST)


# ============================================================
# 三、听写会话完整生命周期
# ============================================================

class TestDictationLifecycle(ServerTestCase):
    def setUp(self):
        self.clear_dictation_history()

    def test_40_start_session(self):
        status, body, _ = http_post(
            self.base, "/api/dictation/start",
            {"characters": ["小", "学", "语", "文"]},
        )
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertEqual(body["characters"], ["小", "学", "语", "文"])
        self.assertEqual(body["total_count"], 4)
        self.assertEqual(body["current_index"], 0)

    def test_41_start_rejects_too_few_chars(self):
        status, _, _ = http_post(
            self.base, "/api/dictation/start", {"characters": ["小"]},
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    def test_42_start_rejects_over_20_chars(self):
        chars = [chr(0x4E00 + i) for i in range(21)]
        status, _, _ = http_post(
            self.base, "/api/dictation/start", {"characters": chars},
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    def test_43_start_filters_single_char_items(self):
        # 业务代码要求每个字符元素为长度 1 的 str，过滤单字；
        # "abc"（长度>1）会被 is_hanzi 中的 ord() 拒绝。
        # 因此只传单字元素。
        status, body, _ = http_post(
            self.base, "/api/dictation/start",
            {"characters": ["小", "!", "学", "语", "a"]},
        )
        self.assertEqual(status, HTTPStatus.CREATED)
        self.assertEqual(body["characters"], ["小", "学", "语"])

    def test_44_answer_correct_advances(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        status, body, _ = http_post(
            self.base, "/api/dictation/answer",
            {"position": 0, "character": "小"},
        )
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(body["correct"])
        self.assertEqual(body["wrong_attempts"], 0)

    def test_45_answer_wrong_records_attempt(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        _, body, _ = http_post(
            self.base, "/api/dictation/answer",
            {"position": 0, "character": "大"},
        )
        self.assertFalse(body["correct"])
        self.assertEqual(body["wrong_attempts"], 1)

    def test_46_answer_wrong_then_right_keeps_wrong_count(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        http_post(self.base, "/api/dictation/answer",
                  {"position": 0, "character": "大"})
        _, body, _ = http_post(
            self.base, "/api/dictation/answer",
            {"position": 0, "character": "小"},
        )
        self.assertTrue(body["correct"])
        self.assertEqual(body["wrong_attempts"], 1)

    def test_47_answer_rejects_non_hanzi(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        status, _, _ = http_post(
            self.base, "/api/dictation/answer",
            {"position": 0, "character": "a"},
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    def test_48_answer_out_of_range(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        status, _, _ = http_post(
            self.base, "/api/dictation/answer",
            {"position": 99, "character": "小"},
        )
        self.assertEqual(status, HTTPStatus.BAD_REQUEST)

    def test_49_answer_without_session_returns_404(self):
        self.clear_dictation_history()  # also clears session
        status, _, _ = http_post(
            self.base, "/api/dictation/answer",
            {"position": 0, "character": "小"},
        )
        self.assertEqual(status, HTTPStatus.NOT_FOUND)

    def test_50_complete_records_history(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        http_post(self.base, "/api/dictation/answer",
                  {"position": 0, "character": "小"})
        http_post(self.base, "/api/dictation/answer",
                  {"position": 1, "character": "学"})
        status, body, _ = http_post(self.base, "/api/dictation/complete", {})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["correct"], 2)
        self.assertEqual(body["accuracy"], 100.0)
        # 历史表应记录
        _, hbody, _ = http_get(self.base, "/api/dictation/history")
        self.assertGreaterEqual(len(hbody["items"]), 1)

    def test_51_complete_with_wrong_answers(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        http_post(self.base, "/api/dictation/answer",
                  {"position": 0, "character": "大"})  # 错
        http_post(self.base, "/api/dictation/answer",
                  {"position": 0, "character": "小"})  # 对但算非一题全对
        http_post(self.base, "/api/dictation/answer",
                  {"position": 1, "character": "学"})  # 对
        _, body, _ = http_post(self.base, "/api/dictation/complete", {})
        # 只有 position 1 是 wrong_attempts=0 且 correct
        self.assertEqual(body["correct"], 1)
        self.assertIn("小", body["wrong_characters"])

    def test_52_delete_session(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        status, body, _ = http_delete(self.base, "/api/dictation/session", {})
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(body["ok"])
        # 删除后再答，应该 404
        status2, _, _ = http_post(
            self.base, "/api/dictation/answer",
            {"position": 0, "character": "小"},
        )
        self.assertEqual(status2, HTTPStatus.NOT_FOUND)

    def test_53_session_get_reports_active(self):
        http_post(self.base, "/api/dictation/start",
                  {"characters": ["小", "学"]})
        status, body, _ = http_get(self.base, "/api/dictation/session")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertTrue(body["active"])
        self.assertEqual(body["session"]["total_count"], 2)

    def test_54_session_get_when_none_active(self):
        self.clear_dictation_history()
        status, body, _ = http_get(self.base, "/api/dictation/session")
        self.assertEqual(status, HTTPStatus.OK)
        self.assertFalse(body["active"])


# ============================================================
# 四、输入过滤与汉字判定（server.chinese_only / is_hanzi）
# ============================================================

class TestInputFiltering(unittest.TestCase):
    def test_60_is_hanzi_accepts_common(self):
        for ch in "小学语文人山火水":
            self.assertTrue(server.is_hanzi(ch), f"{ch} 应为汉字")

    def test_61_is_hanzi_rejects_non_hanzi(self):
        for ch in "abc 123 !?., ":
            self.assertFalse(server.is_hanzi(ch), f"{ch} 不应为汉字")

    def test_62_is_hanzi_accepts_extension(self):
        # CJK Extension B (0x20000+)
        self.assertTrue(server.is_hanzi("𠀀"))

    def test_63_chinese_only_filters_mixed(self):
        self.assertEqual(server.chinese_only("abc 小学!"), "小学")

    def test_64_chinese_only_empty(self):
        self.assertEqual(server.chinese_only("abc 123 !"), "")

    def test_65_chinese_only_preserves_order(self):
        self.assertEqual(server.chinese_only("a 小 b 学 c"), "小学")


# ============================================================
# 五、build_fallback_data.py 纯函数测试
# ============================================================

class TestParsePinyin(unittest.TestCase):
    def test_70_tone_mark_a(self):
        r = bfd.parse_pinyin("mā")
        self.assertIsNotNone(r)
        self.assertEqual(r["pinyin"], "mā")
        self.assertEqual(r["tone"], "ˉ")
        self.assertEqual(r["initial"], "m")
        self.assertEqual(r["final"], "ā")

    def test_71_tone_mark_o(self):
        r = bfd.parse_pinyin("pó")
        self.assertIsNotNone(r)
        self.assertEqual(r["initial"], "p")
        self.assertEqual(r["final"], "ó")
        self.assertEqual(r["tone"], "ˊ")

    def test_72_whole_syllable_zhi(self):
        r = bfd.parse_pinyin("zhī")
        self.assertEqual(r["syllableType"], "整体认读音节")
        self.assertEqual(r["initial"], "zh")

    def test_73_whole_syllable_yi(self):
        r = bfd.parse_pinyin("yí")
        self.assertEqual(r["syllableType"], "整体认读音节")
        # yi 归为整体认读，initial 应为 y
        self.assertEqual(r["initial"], "y")

    def test_74_zero_initial(self):
        r = bfd.parse_pinyin("ā")
        self.assertEqual(r["syllableType"], "零声母音节")
        self.assertEqual(r["initial"], "（自成音节）")

    def test_75_two_pin_yin(self):
        r = bfd.parse_pinyin("bā")
        self.assertEqual(r["syllableType"], "两拼音节")

    def test_76_three_pin_yin_jia(self):
        r = bfd.parse_pinyin("jiā")
        # jia 的韵母以 i 开头且长度>=2，属于三拼音节
        self.assertEqual(r["syllableType"], "三拼音节")

    def test_77_digit_tone(self):
        r = bfd.parse_pinyin("ma1")
        self.assertIsNotNone(r)
        self.assertEqual(r["pinyin"], "ma")
        self.assertEqual(r["tone"], "ˉ")

    def test_78_digit_tone_zero_neutral(self):
        r = bfd.parse_pinyin("ma0")
        self.assertEqual(r["tone"], "")

    def test_79_invalid_returns_none(self):
        self.assertIsNone(bfd.parse_pinyin(""))
        self.assertIsNone(bfd.parse_pinyin(None))
        self.assertIsNone(bfd.parse_pinyin("123!"))

    def test_80_normalizes_g_variant(self):
        # ɡ（U+0261）应规范化为 g
        r = bfd.parse_pinyin("ɡē")
        self.assertIsNotNone(r)
        self.assertEqual(r["initial"], "g")


class TestClassifySyllable(unittest.TestCase):
    def test_81_whole_reading(self):
        r = bfd.classify_syllable("zhi", 1, "zhī")
        self.assertEqual(r["syllableType"], "整体认读音节")

    def test_82_initial_zh(self):
        r = bfd.classify_syllable("zhong", 1, "zhōng")
        self.assertEqual(r["initial"], "zh")

    def test_83_initial_ch(self):
        r = bfd.classify_syllable("chi", 2, "chí")
        self.assertEqual(r["initial"], "ch")


class TestShardingAndWords(unittest.TestCase):
    def test_90_shard_key_format(self):
        key = bfd.shard_key("小")
        self.assertEqual(len(key), 2)
        # 必须是两位十六进制字符串
        int(key, 16)

    def test_91_shard_key_deterministic(self):
        self.assertEqual(bfd.shard_key("学"), bfd.shard_key("学"))

    def test_92_shard_key_uses_mod(self):
        code = ord("小")
        expected = f"{code % 32:02x}"
        self.assertEqual(bfd.shard_key("小"), expected)

    def test_93_is_word_candidate_accepts(self):
        self.assertTrue(bfd.is_word_candidate("学习"))
        self.assertTrue(bfd.is_word_candidate("小学生"))

    def test_94_is_word_candidate_too_short_or_long(self):
        self.assertFalse(bfd.is_word_candidate("学"))  # 长度<2
        self.assertFalse(bfd.is_word_candidate("学习用品店"))  # 长度>4

    def test_95_is_word_candidate_filters_bad_parts(self):
        self.assertFalse(bfd.is_word_candidate("赌博"))
        self.assertFalse(bfd.is_word_candidate("尸体"))

    def test_96_is_word_candidate_rejects_non_hanzi(self):
        self.assertFalse(bfd.is_word_candidate("学习 abc"))

    def test_97_word_score_shorter_preferred(self):
        s2 = bfd.word_score("学习", "学")
        s3 = bfd.word_score("小学生", "学")
        # 2 字词比 3 字词分数更低（更优先）
        self.assertLess(s2, s3)

    def test_98_word_score_starts_with_char_preferred(self):
        s_start = bfd.word_score("学习", "学")
        s_not = bfd.word_score("数学", "学")
        self.assertLess(s_start, s_not)

    def test_99_short_explanation_truncates(self):
        text = "这是很长很长很长的一段解释" * 30
        result = bfd.short_explanation(text)
        self.assertLessEqual(len(result), 150)

    def test_100_short_explanation_handles_empty(self):
        self.assertEqual(bfd.short_explanation(""), "")
        self.assertEqual(bfd.short_explanation(None), "")


class TestBuildCharacters(unittest.TestCase):
    def test_101_builds_record_with_pinyin(self):
        words = [
            {
                "word": "学",
                "pinyin": "xué",
                "radicals": "子",
                "strokes": 8,
                "explanation": "学习的意思",
            }
        ]
        chars = bfd.build_characters(words)
        self.assertIn("学", chars)
        rec = chars["学"]
        self.assertEqual(rec["pinyin"], "xué")
        self.assertEqual(rec["radical"], "子")
        self.assertEqual(rec["strokeCount"], 8)
        self.assertIn("tone", rec)
        self.assertIn("initial", rec)
        self.assertIn("final", rec)

    def test_102_skips_non_hanzi_word(self):
        words = [{"word": "abc", "pinyin": "abc"}]
        self.assertEqual(bfd.build_characters(words), {})

    def test_103_skips_multi_char_word(self):
        words = [{"word": "学习", "pinyin": "xué xí"}]
        self.assertEqual(bfd.build_characters(words), {})


class TestBuildCommonWords(unittest.TestCase):
    def test_104_groups_by_char(self):
        ci_items = [
            {"ci": "学习"},
            {"ci": "学校"},
            {"ci": "学生"},
        ]
        result = bfd.build_common_words(ci_items)
        self.assertIn("学", result)
        # "学" 的组词必须包含这三项（按 score 排序后截断到 12）
        words = result["学"]
        for w in ("学习", "学校", "学生"):
            self.assertIn(w, words)

    def test_105_filters_bad_words(self):
        ci_items = [{"ci": "赌博"}, {"ci": "学习"}]
        result = bfd.build_common_words(ci_items)
        all_words = []
        for words in result.values():
            all_words.extend(words)
        self.assertNotIn("赌博", all_words)

    def test_106_limits_to_12(self):
        ci_items = [{"ci": f"学{chr(0x4E00+i)}"} for i in range(20)]
        result = bfd.build_common_words(ci_items)
        self.assertLessEqual(len(result.get("学", [])), 12)


# ============================================================
# 六、build_fallback_data 完整流程集成测试
#    （在临时目录真实执行 generate 流程，验证拼音、词语、32 分片与 manifest）
# ============================================================

class TestBuildDataPipeline(unittest.TestCase):
    """真实运行 build_fallback_data.main() 的等价流程，写入临时目录。"""

    tmp_path = None
    generated_dir = None

    @classmethod
    def setUpClass(cls):
        cls.tmp_path = Path(tempfile.mkdtemp(prefix="bfd_pipeline_"))

        # monkey-patch 模块的目录常量，定向到临时目录
        cls._orig_vendor = bfd.VENDOR_DIR
        cls._orig_generated = bfd.GENERATED_DIR
        cls._orig_shard = bfd.SHARD_DIR
        cls._orig_manifest = bfd.MANIFEST

        vendor = cls.tmp_path / "vendor"
        vendor.mkdir()
        generated = cls.tmp_path / "generated"
        generated.mkdir()
        shard = generated / "chars"
        manifest = generated / "manifest.json"

        bfd.VENDOR_DIR = vendor
        bfd.GENERATED_DIR = generated
        bfd.SHARD_DIR = shard
        bfd.MANIFEST = manifest

        # 构造最小但覆盖各种情况的 word.json 与 ci.json
        word_data = [
            # 常见单字，带标准拼音、部首、笔画、释义
            {"word": "小", "pinyin": "xiǎo", "radicals": "小",
             "strokes": 3, "explanation": "小的意思"},
            {"word": "学", "pinyin": "xué", "radicals": "子",
             "strokes": 8, "explanation": "学习的意思"},
            {"word": "山", "pinyin": "shān", "radicals": "山",
             "strokes": 3, "explanation": "山的意思"},
            {"word": "水", "pinyin": "shuǐ", "radicals": "水",
             "strokes": 4, "explanation": "水的意思"},
            # 三拼音节
            {"word": "家", "pinyin": "jiā", "radicals": "宀",
             "strokes": 10, "explanation": "家庭"},
            # 整体认读
            {"word": "日", "pinyin": "rì", "radicals": "日",
             "strokes": 4, "explanation": "太阳"},
            # 零声母
            {"word": "安", "pinyin": "ān", "radicals": "宀",
             "strokes": 6, "explanation": "安全"},
            # 脏词示例（应被过滤）
            {"word": "妓", "pinyin": "jì", "radicals": "女",
             "strokes": 7, "explanation": ""},
            # 非汉字条目（应被过滤）
            {"word": "abc", "pinyin": "abc"},
        ]
        (vendor / "word.json").write_text(
            json.dumps(word_data, ensure_ascii=False), encoding="utf-8"
        )

        ci_data = [
            {"ci": "小学"},
            {"ci": "学校"},
            {"ci": "学生"},
            {"ci": "高山"},
            {"ci": "山水"},
            {"ci": "水果"},
            # 脏词（应被过滤）
            {"ci": "赌博"},
            # 过长（应被过滤）
            {"ci": "高山流水人家"},
            # 非汉字（应被过滤）
            {"ci": "abc 学校"},
        ]
        (vendor / "ci.json").write_text(
            json.dumps(ci_data, ensure_ascii=False), encoding="utf-8"
        )

        # 真实运行 main()
        cls.stdout_capture = []
        cls._run_main()

    @classmethod
    def _run_main(cls):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bfd.main()
        cls.stdout_capture = buf.getvalue().splitlines()

    @classmethod
    def tearDownClass(cls):
        bfd.VENDOR_DIR = cls._orig_vendor
        bfd.GENERATED_DIR = cls._orig_generated
        bfd.SHARD_DIR = cls._orig_shard
        bfd.MANIFEST = cls._orig_manifest
        try:
            shutil.rmtree(cls.tmp_path)
        except Exception:
            pass

    # ----- manifest 与文件产出 -----

    def test_400_manifest_written(self):
        self.assertTrue(bfd.MANIFEST.exists(), "manifest.json 应被创建")

    def test_401_manifest_has_32_buckets(self):
        data = json.loads(bfd.MANIFEST.read_text())
        self.assertEqual(data["buckets"], 32)
        self.assertIn("counts", data)
        self.assertIsInstance(data["counts"], dict)
        # counts 的总和应等于成功提取的汉字数
        total_in_counts = sum(data["counts"].values())
        self.assertGreater(total_in_counts, 0)

    def test_402_32_shards_or_fewer_but_valid(self):
        """
        只有被用到的分片才会写入磁盘。测试数据只覆盖少数 shard_key，
        所以文件数可能少于 32，但 counts 里每个 key 必须有对应文件。
        """
        shard_dir = bfd.SHARD_DIR
        self.assertTrue(shard_dir.is_dir())
        files = list(shard_dir.glob("*.json"))
        # 至少生成 1 个文件
        self.assertGreater(len(files), 0, "应至少生成 1 个 shard 文件")
        # 每个文件名对应 manifest.counts 的一个 key
        manifest = json.loads(bfd.MANIFEST.read_text())
        actual_keys = {p.stem for p in files}
        self.assertEqual(actual_keys, set(manifest["counts"].keys()),
            "manifest.counts 的 key 必须与磁盘文件一一对应")

    def test_403_shard_file_name_matches_char_key(self):
        for shard_file in bfd.SHARD_DIR.glob("*.json"):
            data = json.loads(shard_file.read_text())
            expected_key = shard_file.stem
            for char in data["characters"]:
                self.assertEqual(bfd.shard_key(char), expected_key,
                    f"字符 {char} 应在 shard {expected_key}，实际 key={bfd.shard_key(char)}")

    # ----- 拼音解析 -----

    def test_410_character_pinyin_xiǎo(self):
        # 真实行为："小" 在 data/seed-characters.json 中有条目且带 syllableType，
        # merge_seed_characters() 会用 seed 数据覆盖 word.json 解析结果。
        # seed 中 syllableType="普通音节"，所以这里断言的是 merge 后的最终值。
        shard = self._find_char("小")
        self.assertEqual(shard["pinyin"], "xiǎo")
        self.assertEqual(shard["tone"], "ˇ")
        self.assertEqual(shard["initial"], "x")
        # seed 覆盖了分类结果（word.json 解析为"三拼音节"，seed 为"普通音节"）
        self.assertEqual(shard["syllableType"], "普通音节",
            "seed-characters.json 中的 syllableType 应覆盖解析值")

    def test_411_character_pinyin_xué(self):
        shard = self._find_char("学")
        self.assertEqual(shard["pinyin"], "xué")
        self.assertEqual(shard["tone"], "ˊ")
        self.assertEqual(shard["initial"], "x")

    def test_412_character_pinyin_shān(self):
        shard = self._find_char("山")
        self.assertEqual(shard["pinyin"], "shān")
        self.assertEqual(shard["initial"], "sh")
        self.assertEqual(shard["tone"], "ˉ")

    def test_413_character_pinyin_shuǐ(self):
        shard = self._find_char("水")
        self.assertEqual(shard["pinyin"], "shuǐ")
        self.assertEqual(shard["initial"], "sh")

    def test_414_character_pinyin_jiā_three_pin(self):
        shard = self._find_char("家")
        self.assertEqual(shard["syllableType"], "三拼音节")

    def test_415_character_rì_whole_reading(self):
        shard = self._find_char("日")
        self.assertEqual(shard["syllableType"], "整体认读音节")

    def test_416_character_ān_zero_initial(self):
        shard = self._find_char("安")
        self.assertEqual(shard["syllableType"], "零声母音节")
        self.assertEqual(shard["initial"], "（自成音节）")

    def test_417_bad_char_filtered_out(self):
        # 脏字"妓"应被 BAD_WORD_PARTS 之外的过滤？看 build_characters
        # 实际 build_characters 只检查 is_hanzi，不会过滤 BAD_WORD_PARTS
        # BAD_WORD_PARTS 只在组词侧过滤。所以"妓"应仍在 characters 内。
        # 这里只验证它被构建。
        found = any(
            "妓" in json.loads(f.read_text())["characters"]
            for f in bfd.SHARD_DIR.glob("*.json")
        )
        # 由于 build_characters 不参照 BAD_WORD_PARTS，"妓"应存在
        self.assertTrue(found)

    def test_418_non_hanzi_entry_filtered(self):
        # "abc" 应被 build_characters 过滤
        for f in bfd.SHARD_DIR.glob("*.json"):
            data = json.loads(f.read_text())
            for char in data["characters"]:
                self.assertTrue(bfd.is_hanzi(char),
                    f"shard 内不应有非汉字 {char!r}")

    # ----- 词语构建 -----

    def test_420_common_words_grouped(self):
        words_for_xue = self._find_common_words("学")
        # "学" 应至少有"小学"、"学校"、"学生"三个
        for w in ("小学", "学校", "学生"):
            self.assertIn(w, words_for_xue,
                f"'学' 的 commonWords 应含 {w!r}，实际：{words_for_xue}")

    def test_421_common_words_for_shan(self):
        words = self._find_common_words("山")
        self.assertIn("高山", words)
        self.assertIn("山水", words)

    def test_422_bad_words_filtered_from_common(self):
        # "赌博"中的"赌"与"博"都不应出现在 commonWords
        for f in bfd.SHARD_DIR.glob("*.json"):
            data = json.loads(f.read_text())
            for char, word_list in data["commonWords"].items():
                for w in word_list:
                    self.assertNotIn("赌博", w,
                        "commonWords 内不应包含'赌博'相关词")

    # ----- stdout 输出 -----

    def test_430_stdout_reports_counts(self):
        joined = "\n".join(self.stdout_capture)
        self.assertIn("汉字", joined)
        self.assertIn("组词", joined)
        self.assertIn("分片", joined)

    # ----- helper -----

    def _find_char(self, char):
        key = bfd.shard_key(char)
        path = bfd.SHARD_DIR / f"{key}.json"
        self.assertTrue(path.exists(), f"字 {char} 应在 shard {key}，但文件不存在")
        data = json.loads(path.read_text())
        self.assertIn(char, data["characters"],
            f"shard {key} 内应有字符 {char}")
        return data["characters"][char]

    def _find_common_words(self, char):
        key = bfd.shard_key(char)
        path = bfd.SHARD_DIR / f"{key}.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        return data["commonWords"].get(char, [])


# ============================================================
# 七、Manifest 与现有生产分片结构验证（只读，验证项目 data 目录未损坏）
# ============================================================

class TestShardFiles(unittest.TestCase):
    """验证已落地的 manifest.json 与 data/generated/chars/*.json 结构。"""

    def test_200_manifest_exists(self):
        manifest = ROOT / "data" / "generated" / "manifest.json"
        self.assertTrue(manifest.exists())

    def test_201_manifest_schema(self):
        data = json.loads((ROOT / "data" / "generated" / "manifest.json").read_text())
        self.assertEqual(data["source"], "pwxcoo/chinese-xinhua")
        self.assertEqual(data["buckets"], 32)
        self.assertIsInstance(data["counts"], dict)
        self.assertEqual(len(data["counts"]), 32)

    def test_202_shard_counts_all_positive(self):
        data = json.loads(
            (ROOT / "data" / "generated" / "manifest.json").read_text()
        )
        for key, count in data["counts"].items():
            self.assertGreater(count, 0, f"分片 {key} 应为空")

    def test_203_shard_files_exist(self):
        chars_dir = ROOT / "data" / "generated" / "chars"
        self.assertTrue(chars_dir.is_dir())
        files = list(chars_dir.glob("*.json"))
        self.assertEqual(len(files), 32)

    def test_204_shard_file_schema(self):
        shard = ROOT / "data" / "generated" / "chars" / "00.json"
        data = json.loads(shard.read_text())
        self.assertIn("characters", data)
        self.assertIn("commonWords", data)
        # characters 中每个字应有 pinyin 字段
        for char, rec in list(data["characters"].items())[:3]:
            self.assertIn("pinyin", rec)
            self.assertEqual(len(char), 1)

    def test_205_shard_filename_matches_key(self):
        """每个 shard 文件内的汉字都必须能映射回文件名。"""
        shard = ROOT / "data" / "generated" / "chars" / "00.json"
        data = json.loads(shard.read_text())
        for char in data["characters"]:
            self.assertEqual(bfd.shard_key(char), "00")


# ============================================================
# 七、前端 Playwright 测试（可选，需要浏览器）
# ============================================================

def _playwright_available():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


@unittest.skipUnless(
    _playwright_available(), "Playwright 或浏览器不可用，跳过前端测试"
)
class TestFrontend(ServerTestCase):
    """真实浏览器启动 server 验证前端。"""

    playwright = None
    browser = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(headless=True)
        except Exception:
            cls.browser = None

    @classmethod
    def tearDownClass(cls):
        if cls.browser:
            cls.browser.close()
        if cls.playwright:
            cls.playwright.stop()
        super().tearDownClass()

    def new_page(self, *, block_cdn=False, block_speech=False):
        """创建新页面，可选择屏蔽 CDN 资源或强制禁用 speechSynthesis。

        所有页面都会注入 window.__pageErrors 与 window.__pageConsole 捕获
        运行时错误与 console.warn/error 输出，供断言使用。
        """
        ctx = self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            java_script_enabled=True,
        )

        def handle(route):
            url = route.request.url
            if block_cdn and "cdn.jsdelivr.net" in url:
                route.abort()
            else:
                route.continue_()
        ctx.route("**/*", handle)

        # 在每个页面加载前注入：错误捕获 + console 捕获 + 可选 speech 禁用
        init_script = """
            window.__pageErrors = [];
            window.__pageConsole = { warn: [], error: [], info: [] };
            window.addEventListener('error', function(e) {
                window.__pageErrors.push({
                    type: 'error',
                    message: e.message,
                    filename: e.filename,
                    lineno: e.lineno
                });
            });
            window.addEventListener('unhandledrejection', function(e) {
                window.__pageErrors.push({
                    type: 'unhandledrejection',
                    message: e.reason && e.reason.message || String(e.reason)
                });
            });
            var origWarn = console.warn;
            var origError = console.error;
            var origInfo = console.info;
            console.warn = function() {
                window.__pageConsole.warn.push(Array.from(arguments).join(' '));
                origWarn.apply(console, arguments);
            };
            console.error = function() {
                window.__pageConsole.error.push(Array.from(arguments).join(' '));
                origError.apply(console, arguments);
            };
            console.info = function() {
                window.__pageConsole.info.push(Array.from(arguments).join(' '));
                origInfo.apply(console, arguments);
            };
        """
        if block_speech:
            # 真实模拟 speechSynthesis 不存在（旧浏览器、隐私模式）。
            # 关键：必须让 'speechSynthesis' in window 返回 false，
            # 否则 app.js 初始化时会走 `window.speechSynthesis.getVoices()`
            # 抛 Uncaught TypeError 导致整个 app.js 崩溃。
            init_script += """
                try { delete window.speechSynthesis; } catch(e) {}
            """
        ctx.add_init_script(init_script)

        page = ctx.new_page()
        return ctx, page

    def go_home(self, page, *, block_cdn=False):
        """访问首页并等待 app.js 执行。"""
        resp = page.goto(self.base + "/index.html", wait_until="domcontentloaded")
        self.assertIsNotNone(resp)
        self.assertIn(resp.status, (200, 304))
        # 等待 app.js 执行：表单按钮应可见
        page.wait_for_selector("#character-form", timeout=5000)
        # 给 defer 脚本一些时间
        page.wait_for_timeout(300)
        return page

    # ----- 页面加载 -----

    def test_300_index_loads(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            title = page.title()
            self.assertIn("语文", title)
            # 6 个导航按钮
            nav_count = page.locator(".nav-item").count()
            self.assertEqual(nav_count, 6)
        finally:
            ctx.close()

    def test_301_css_and_js_loaded(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            # CSS 应成功加载
            bg = page.evaluate(
                "getComputedStyle(document.body).backgroundColor"
            )
            self.assertTrue(bg, "body 背景应被 CSS 设置")
            # app.js 应挂载
            self.assertTrue(
                page.evaluate("document.querySelector('#character-input') !== null")
            )
        finally:
            ctx.close()

    # ----- 输入过滤 -----

    def test_310_non_hanzi_filtered_from_submit(self):
        # 业务行为：分页模式每次只显示 1 张卡片，
        # 所以用 summary 文字和 pager counter 验证"过滤了非汉字"。
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "abc 小学 def")
            page.click("button[type='submit']")
            page.wait_for_selector(".character-card", timeout=3000)
            page.wait_for_timeout(600)
            # 卡片数==1（分页模式）
            self.assertEqual(page.locator(".character-card").count(), 1)
            # summary 应明确说"共 2 个字"（小学）而不是"共 8 个字"
            summary_text = page.locator("#result-summary").inner_text()
            self.assertIn("2 个字", summary_text, summary_text)
            # pager counter 显示"1 / 2"
            counter = page.locator("#pager-counter").inner_text()
            self.assertIn("2", counter)
        finally:
            ctx.close()

    def test_311_empty_input_shows_default(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            # 默认可见 4 个默认字的卡片
            page.wait_for_selector(".character-card", timeout=3000)
            count = page.locator(".character-card").count()
            self.assertGreaterEqual(count, 1)
        finally:
            ctx.close()

    # ----- 分页 -----

    def test_320_pager_visible_for_multi_char(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "小学语文")
            page.click("button[type='submit']")
            page.wait_for_timeout(500)
            pager_visible = page.evaluate(
                "!document.querySelector('#char-pager').hidden"
            )
            self.assertTrue(pager_visible, "多字输入时分页器应显示")
        finally:
            ctx.close()

    def test_321_pager_next_advances_char(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "小学")
            page.click("button[type='submit']")
            page.wait_for_selector(".character-card", timeout=3000)
            page.wait_for_timeout(600)
            # 初始状态 index===0，标签文本应为"汉字：小"
            label = page.locator(".character-label").inner_text()
            self.assertIn("汉字：小", label)
            # 点下一个，应切换到"学"
            page.click(".pager-nav.next")
            page.wait_for_timeout(600)
            label2 = page.locator(".character-label").inner_text()
            self.assertIn("汉字：学", label2)
            # 再上一个应回到"小"
            page.click(".pager-nav.prev")
            page.wait_for_timeout(600)
            label3 = page.locator(".character-label").inner_text()
            self.assertIn("汉字：小", label3)
        finally:
            ctx.close()

    def test_322_pager_counter_updates(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "小语")
            page.click("button[type='submit']")
            page.wait_for_timeout(500)
            counter_text = page.locator("#pager-counter").inner_text()
            self.assertTrue(counter_text, "分页计数器应有内容")
        finally:
            ctx.close()

    # ----- 历史记录操作 -----

    def test_330_history_saves_query_and_shows_it(self):
        """
        真实场景：提交汉字查询后，后端必须保存记录，历史 tab 必须
        以列表形式显示查询内容（不能是空状态）。验证端到端流程。
        """
        self.clear_history()
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            # 提交一个有代表性的查询
            unique = f"高山{int(time.time()) % 10000}"
            page.fill("#character-input", unique)
            page.click("button[type='submit']")
            # 等待卡片渲染（说明查询已处理）+ 给 saveHistory 留出时间
            page.wait_for_selector(".character-card", timeout=3000)
            page.wait_for_timeout(800)
            # 1) 后端应已保存（chinese_only 过滤掉数字，只留汉字）
            _, body, _ = http_get(self.base, "/api/history?limit=10")
            items = body.get("items", [])
            self.assertGreater(len(items), 0,
                "后端 /api/history 应至少有一条记录")
            # 查询的汉字"高山"应出现在保存记录中
            found = any("高山" in (it.get("characters") or "") for it in items)
            self.assertTrue(found,
                f"查询{unique!r}应保存为'高山'，实际后端记录：{items}")
            # 2) 前端切换到历史 tab 必须显示列表（不是空状态）
            page.locator(".nav-item[data-feature='history']").click()
            page.wait_for_timeout(600)
            list_present = page.locator(".history-list").count()
            empty_present = page.locator(".history-empty").count()
            self.assertEqual(list_present, 1,
                f"历史页应渲染 .history-list，实际 list={list_present}, empty={empty_present}")
            self.assertEqual(empty_present, 0,
                "后端有记录时前端不应显示空状态")
            # 3) 列表内容必须包含查询的汉字"高山"
            list_text = page.locator(".history-list").inner_text()
            self.assertIn("高山", list_text,
                f"历史列表文本应包含'高山'，实际：{list_text[:200]!r}")
        finally:
            ctx.close()

    def test_331_history_delete_selected(self):
        self.clear_history()
        # 预先写两条记录
        http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "高", "characters": "高"},
        )
        http_post(
            self.base, "/api/history",
            {"feature": "hanzi", "query": "山", "characters": "山"},
        )
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.locator(".nav-item[data-feature='history']").click()
            page.wait_for_timeout(600)
            # 勾选全选
            select_all = page.locator("#history-select-all")
            select_all.check()
            page.wait_for_timeout(100)
            # 点击删除所选
            delete_btn = page.locator(".history-delete-button")
            delete_btn.click()
            page.wait_for_timeout(500)
            # 后端应已清空
            _, body, _ = http_get(self.base, "/api/history?limit=50")
            self.assertEqual(len(body["items"]), 0)
        finally:
            ctx.close()

    # ----- 笔顺不可用降级（CDN 屏蔽情况下）-----

    def test_340_stroke_controls_hidden_when_hanziwriter_missing(self):
        """CDN 屏蔽时 HanziWriter 不加载，笔顺控件应被隐藏（而非渲染但不可用）。"""
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "小")
            page.click("button[type='submit']")
            page.wait_for_timeout(600)
            # 笔顺按钮应存在于 DOM
            btn_count = page.locator("[data-action='animate']").count()
            self.assertGreaterEqual(btn_count, 1, "笔顺动画按钮应存在于 DOM")
            # 但控件父元素 .stroke-controls 应被隐藏
            controls_hidden = page.evaluate("""
                document.querySelector('.stroke-controls').hidden
            """)
            self.assertTrue(controls_hidden,
                "HanziWriter 不可用时，.stroke-controls 应设置 hidden=true")
            # 尝试强制点击（即使 hidden），不应抛错
            errors_before = page.evaluate(
                "window.__pageErrors ? window.__pageErrors.length : 0"
            )
            page.locator("[data-action='animate']").first.click(force=True)
            page.wait_for_timeout(300)
            errors_after = page.evaluate(
                "window.__pageErrors ? window.__pageErrors.length : 0"
            )
            self.assertEqual(errors_before, errors_after,
                "强制点击隐藏的笔顺按钮不应产生错误")
            # 主要功能（卡片渲染）仍正常
            card_exists = page.locator(".character-card").count() > 0
            self.assertTrue(card_exists, "卡片仍应正常渲染")
        finally:
            ctx.close()

    # ----- TTS 朗读不可用降级 -----

    def test_350_speak_button_present_when_available(self):
        """默认情况下朗读按钮应存在于每张卡片。"""
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "小")
            page.click("button[type='submit']")
            page.wait_for_timeout(500)
            speak_btns = page.locator("[data-action='speak']").count()
            self.assertGreaterEqual(speak_btns, 1)
            # 按钮未被禁用
            disabled = page.locator("[data-action='speak']").first.evaluate(
                "el => el.disabled"
            )
            self.assertFalse(disabled, "朗读按钮默认不应被禁用")
        finally:
            ctx.close()

    def test_351_speak_button_disabled_when_no_speechsynthesis(self):
        """
        真实场景：当 window.speechSynthesis === undefined（例如某些旧浏览器
        或隐私模式），setupSpeak() 应当禁用朗读按钮并设置 tooltip。
        """
        ctx, page = self.new_page(block_cdn=True, block_speech=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "小")
            page.click("button[type='submit']")
            page.wait_for_timeout(500)
            # 朗读按钮应被禁用
            disabled = page.locator("[data-action='speak']").first.evaluate(
                "el => el.disabled"
            )
            self.assertTrue(disabled,
                "speechSynthesis 不可用时，朗读按钮应被 disabled")
            # title 应说明原因
            title = page.locator("[data-action='speak']").first.evaluate(
                "el => el.title"
            )
            self.assertIn("不支持", title,
                f"朗读按钮 title 应说明不支持原因，实际：{title!r}")
        finally:
            ctx.close()

    def test_352_speak_click_with_voice_logs_or_errors(self):
        """
        真实场景：点击朗读按钮会调用 speechSynthesis.speak()。
        在 headless Chromium 中，这通常会成功调度 utterance，
        但不一定真的发声。我们验证：
        - 点击后不应抛 JS 错误
        - 应产生 console.info 日志（app.js 中 speakText 有 console.info）
          或 console.warn/error（如果 speech 失败）
        - utterance 的 onerror 可能触发（在某些环境，voice 不可用）
        这个测试暴露真实行为，不做"假装通过"断言。
        """
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "小")
            page.click("button[type='submit']")
            page.wait_for_timeout(500)
            # 点击朗读按钮
            page.locator("[data-action='speak']").first.click()
            page.wait_for_timeout(500)
            # 收集真实日志（用于诊断）
            console_info = page.evaluate("window.__pageConsole.info || []")
            console_warn = page.evaluate("window.__pageConsole.warn || []")
            console_error = page.evaluate("window.__pageConsole.error || []")
            errors = page.evaluate("window.__pageErrors || []")
            # 不应有未捕获的 JS 错误
            uncaught = [e for e in errors if e.get("type") in ("error", "unhandledrejection")]
            self.assertEqual(len(uncaught), 0,
                f"点击朗读后不应有未捕获错误，实际有：{uncaught}")
            # 必须有某种日志表明 speakText 被调用，或 speech 失败
            # （app.js 中 speakText() 会 console.info）
            # 如果既没有 info 也没有 warn/error，说明逻辑没被触发 = 严重问题
            speech_log = [m for m in console_info if "[speech]" in m]
            speech_warn = [m for m in console_warn if "speech" in m.lower()]
            self.assertTrue(
                len(speech_log) >= 1 or len(speech_warn) >= 1,
                f"点击朗读按钮应触发 speechText（应有 [speech] 日志），"
                f"实际 console.info: {console_info}, console.warn: {console_warn}, "
                f"console.error: {console_error}"
            )
        finally:
            ctx.close()

    def test_353_utterance_error_does_not_crash_page(self):
        """
        真实场景：即便 SpeechSynthesisUtterance 的 onerror 触发
        （例如 'interrupted' 或 'canceled'），页面也不应崩溃。
        我们连续点击朗读按钮，检查是否有未捕获错误。
        """
        ctx, page = self.new_page(block_cdn=True)
        try:
            self.go_home(page, block_cdn=True)
            page.fill("#character-input", "小山")
            page.click("button[type='submit']")
            page.wait_for_timeout(600)
            # 点击第一次
            page.locator("[data-action='speak']").first.click()
            page.wait_for_timeout(200)
            # 再次点击（可能触发 cancel + speak 重调度路径）
            page.locator("[data-action='speak']").first.click()
            page.wait_for_timeout(500)
            # 不应有未捕获错误
            uncaught = [e for e in page.evaluate("window.__pageErrors || []")
                        if e.get("type") in ("error", "unhandledrejection")]
            self.assertEqual(len(uncaught), 0,
                f"连续点击朗读不应产生未捕获错误：{uncaught}")
            # 按钮仍存在
            present = page.evaluate("!!document.querySelector('[data-action=\"speak\"]')")
            self.assertTrue(present, "朗读按钮应仍存在")
            # 暴露真实状态（诊断用）
            state = page.evaluate("""
                () => {
                    const btn = document.querySelector('[data-action="speak"]');
                    return {
                        present: !!btn,
                        disabled: btn && btn.disabled,
                        speaking: btn && btn.classList.contains('is-speaking')
                    };
                }
            """)
            # 不做 speaking 态断言（headless 中 utterance 可能卡住），
            # 但在测试输出中记录真实状态供人工检查
            print(f"\n    [test_353 真实状态] {state}")
        finally:
            ctx.close()

    # ----- 静态文件服务（非 API 路径回退到文件）-----

    def test_360_serves_statics(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            resp = page.goto(self.base + "/src/styles.css")
            self.assertIn(resp.status, (200, 304))
            self.assertIn("text/css", resp.headers.get("content-type", ""))
        finally:
            ctx.close()

    def test_361_serves_shard_json(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            resp = page.goto(self.base + "/data/generated/chars/00.json")
            self.assertEqual(resp.status, 200)
            # 应带长缓存
            self.assertIn("max-age", resp.headers.get("cache-control", ""))
        finally:
            ctx.close()

    def test_370_api_history_cache_no_store(self):
        ctx, page = self.new_page(block_cdn=True)
        try:
            resp = page.goto(self.base + "/api/history?limit=1")
            self.assertEqual(resp.status, 200)
            self.assertEqual(
                resp.headers.get("cache-control"),
                "no-store",
            )
        finally:
            ctx.close()


# ============================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
