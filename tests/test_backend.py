#!/usr/bin/env python3
"""Backend API tests — uses a temporary SQLite DB and a real HTTP server."""
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]

# ── patch DB_PATH before importing server ──
_tmp_db = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
_tmp_db.close()
TMP_DB = Path(_tmp_db.name)

import importlib
import server as srv

srv.DB_PATH = TMP_DB

def _find_free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

PORT = _find_free_port()
BASE = f"http://127.0.0.1:{PORT}"

def setUpModule():
    srv.init_db()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), srv.ChineseHelperHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

def tearDownModule():
    TMP_DB.unlink(missing_ok=True)


def api(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())


def _reset_db():
    with sqlite3.connect(TMP_DB) as conn:
        conn.execute("DELETE FROM query_history")
        conn.execute("DELETE FROM dictation_session_state")
        conn.execute("DELETE FROM dictation_session_result")
        conn.execute("DELETE FROM dictation_session")
        conn.execute("DELETE FROM dictation_history")


# ═══════════════════════════════════════════════════════
# 1. Pure function tests
# ═══════════════════════════════════════════════════════

class TestIsHanzi(unittest.TestCase):
    def test_common_characters(self):
        for ch in "小学语文你好中国":
            self.assertTrue(srv.is_hanzi(ch), ch)

    def test_rare_cjk_ext_b(self):
        self.assertTrue(srv.is_hanzi("\U00020000"))  # CJK Ext-B first char

    def test_ascii_rejected(self):
        for ch in "abcABC123 !@#":
            self.assertFalse(srv.is_hanzi(ch), ch)

    def test_japanese_kana_rejected(self):
        for ch in "あアカ":
            self.assertFalse(srv.is_hanzi(ch), ch)

    def test_punctuation_rejected(self):
        for ch in "，。！、？：；""":
            self.assertFalse(srv.is_hanzi(ch), ch)


class TestChineseOnly(unittest.TestCase):
    def test_filters_mixed_input(self):
        self.assertEqual(srv.chinese_only("abc你好def世界"), "你好世界")

    def test_pure_chinese(self):
        self.assertEqual(srv.chinese_only("语文"), "语文")

    def test_empty_and_no_chinese(self):
        self.assertEqual(srv.chinese_only(""), "")
        self.assertEqual(srv.chinese_only("hello 123"), "")

    def test_strips_punctuation(self):
        self.assertEqual(srv.chinese_only("你好，世界！"), "你好世界")

    def test_numbers_and_spaces(self):
        self.assertEqual(srv.chinese_only("第1课 小 学"), "第课小学")


# ═══════════════════════════════════════════════════════
# 2. History API tests
# ═══════════════════════════════════════════════════════

class TestHistoryAPI(unittest.TestCase):
    def setUp(self):
        _reset_db()

    def test_create_and_list(self):
        code, data = api("POST", "/api/history", {
            "query": "测试", "characters": "测试"
        })
        self.assertEqual(code, 201)
        self.assertEqual(data["characters"], "测试")
        self.assertIn("id", data)

        code, data = api("GET", "/api/history")
        self.assertEqual(code, 200)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["characters"], "测试")

    def test_create_filters_non_chinese(self):
        code, data = api("POST", "/api/history", {
            "query": "hello你好world", "characters": "hello你好world"
        })
        self.assertEqual(code, 201)
        self.assertEqual(data["characters"], "你好")

    def test_create_missing_fields(self):
        code, _ = api("POST", "/api/history", {"query": "", "characters": ""})
        self.assertEqual(code, 400)

        code, _ = api("POST", "/api/history", {"query": "hi", "characters": "abc"})
        self.assertEqual(code, 400)

    def test_create_invalid_json(self):
        url = BASE + "/api/history"
        req = Request(url, data=b"not json", method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req) as resp:
                code = resp.status
        except HTTPError as e:
            code = e.code
        self.assertEqual(code, 400)

    def test_delete_by_ids(self):
        _, d1 = api("POST", "/api/history", {"query": "一", "characters": "一"})
        _, d2 = api("POST", "/api/history", {"query": "二", "characters": "二"})
        _, d3 = api("POST", "/api/history", {"query": "三", "characters": "三"})

        code, data = api("DELETE", "/api/history", {"ids": [d1["id"], d3["id"]]})
        self.assertEqual(code, 200)
        self.assertEqual(data["deleted"], 2)

        _, remaining = api("GET", "/api/history")
        self.assertEqual(len(remaining["items"]), 1)
        self.assertEqual(remaining["items"][0]["characters"], "二")

    def test_delete_nonexistent_ids(self):
        code, data = api("DELETE", "/api/history", {"ids": [99999]})
        self.assertEqual(code, 200)
        self.assertEqual(data["deleted"], 0)

    def test_delete_empty_ids(self):
        code, data = api("DELETE", "/api/history", {"ids": []})
        self.assertEqual(code, 200)
        self.assertEqual(data["deleted"], 0)

    def test_delete_invalid_ids_type(self):
        code, _ = api("DELETE", "/api/history", {"ids": "not a list"})
        self.assertEqual(code, 400)

    def test_list_limit(self):
        for i in range(5):
            api("POST", "/api/history", {"query": f"字{i}", "characters": "字"})
        code, data = api("GET", "/api/history?limit=3")
        self.assertEqual(len(data["items"]), 3)

    def test_list_default_order_desc(self):
        api("POST", "/api/history", {"query": "第一", "characters": "第一"})
        api("POST", "/api/history", {"query": "第二", "characters": "第二"})
        _, data = api("GET", "/api/history")
        self.assertEqual(data["items"][0]["query"], "第二")

    def test_feature_field(self):
        api("POST", "/api/history", {
            "query": "词", "characters": "词", "feature": "words"
        })
        _, data = api("GET", "/api/history")
        self.assertEqual(data["items"][0]["feature"], "words")

    def test_feature_defaults_to_hanzi(self):
        api("POST", "/api/history", {"query": "字", "characters": "字"})
        _, data = api("GET", "/api/history")
        self.assertEqual(data["items"][0]["feature"], "hanzi")


# ═══════════════════════════════════════════════════════
# 3. Dictation API tests
# ═══════════════════════════════════════════════════════

class TestDictationAPI(unittest.TestCase):
    def setUp(self):
        _reset_db()

    def test_start_session(self):
        code, data = api("POST", "/api/dictation/start", {
            "characters": ["你", "好"]
        })
        self.assertEqual(code, 201)
        self.assertEqual(data["characters"], ["你", "好"])
        self.assertEqual(data["total_count"], 2)
        self.assertEqual(data["current_index"], 0)

    def test_start_deduplicates(self):
        code, data = api("POST", "/api/dictation/start", {
            "characters": ["你", "你", "好", "好"]
        })
        self.assertEqual(code, 201)
        self.assertEqual(data["characters"], ["你", "好"])

    def test_start_filters_non_hanzi(self):
        code, data = api("POST", "/api/dictation/start", {
            "characters": ["a", "你", "b", "好"]
        })
        self.assertEqual(code, 201)
        self.assertEqual(data["characters"], ["你", "好"])

    def test_start_too_few_chars(self):
        code, _ = api("POST", "/api/dictation/start", {"characters": ["你"]})
        self.assertEqual(code, 400)

    def test_start_too_many_chars(self):
        chars = list("一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾零")
        code, _ = api("POST", "/api/dictation/start", {"characters": chars})
        self.assertEqual(code, 400)

    def test_start_retry_allows_one_char(self):
        code, data = api("POST", "/api/dictation/start", {
            "characters": ["你"], "retry": True
        })
        self.assertEqual(code, 201)
        self.assertEqual(data["total_count"], 1)

    def test_get_session_active(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        code, data = api("GET", "/api/dictation/session")
        self.assertEqual(code, 200)
        self.assertTrue(data["active"])
        self.assertEqual(data["session"]["characters"], ["你", "好"])

    def test_get_session_inactive(self):
        code, data = api("GET", "/api/dictation/session")
        self.assertEqual(code, 200)
        self.assertFalse(data["active"])

    def test_answer_correct(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        code, data = api("POST", "/api/dictation/answer", {
            "position": 0, "character": "你"
        })
        self.assertEqual(code, 200)
        self.assertTrue(data["correct"])
        self.assertEqual(data["wrong_attempts"], 0)

    def test_answer_wrong_then_correct(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        code, data = api("POST", "/api/dictation/answer", {
            "position": 0, "character": "我"
        })
        self.assertFalse(data["correct"])
        self.assertEqual(data["wrong_attempts"], 1)

        code, data = api("POST", "/api/dictation/answer", {
            "position": 0, "character": "你"
        })
        self.assertTrue(data["correct"])
        self.assertEqual(data["wrong_attempts"], 1)

    def test_answer_no_active_session(self):
        code, _ = api("POST", "/api/dictation/answer", {
            "position": 0, "character": "你"
        })
        self.assertEqual(code, 404)

    def test_answer_position_out_of_range(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        code, _ = api("POST", "/api/dictation/answer", {
            "position": 5, "character": "你"
        })
        self.assertEqual(code, 400)

    def test_answer_invalid_character(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        code, _ = api("POST", "/api/dictation/answer", {
            "position": 0, "character": "a"
        })
        self.assertEqual(code, 400)

    def test_complete_session(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        api("POST", "/api/dictation/answer", {"position": 0, "character": "你"})
        api("POST", "/api/dictation/answer", {"position": 1, "character": "好"})
        code, data = api("POST", "/api/dictation/complete")
        self.assertEqual(code, 200)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["correct"], 2)
        self.assertEqual(data["accuracy"], 100.0)
        self.assertEqual(data["wrong_characters"], [])

    def test_complete_with_mistakes(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        api("POST", "/api/dictation/answer", {"position": 0, "character": "我"})
        api("POST", "/api/dictation/answer", {"position": 0, "character": "你"})
        api("POST", "/api/dictation/answer", {"position": 1, "character": "好"})
        code, data = api("POST", "/api/dictation/complete")
        self.assertEqual(data["correct"], 1)
        self.assertIn("你", data["wrong_characters"])
        self.assertLess(data["accuracy"], 100)

    def test_complete_no_session(self):
        code, _ = api("POST", "/api/dictation/complete")
        self.assertEqual(code, 404)

    def test_delete_session(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        code, data = api("DELETE", "/api/dictation/session")
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])
        _, check = api("GET", "/api/dictation/session")
        self.assertFalse(check["active"])

    def test_dictation_history(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        api("POST", "/api/dictation/answer", {"position": 0, "character": "你"})
        api("POST", "/api/dictation/answer", {"position": 1, "character": "好"})
        api("POST", "/api/dictation/complete")

        code, data = api("GET", "/api/dictation/history")
        self.assertEqual(code, 200)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["total_count"], 2)

    def test_dictation_characters_from_history(self):
        api("POST", "/api/history", {"query": "学习", "characters": "学习"})
        code, data = api("GET", "/api/dictation/characters")
        self.assertEqual(code, 200)
        self.assertIn("学", data["characters"])
        self.assertIn("习", data["characters"])

    def test_auto_complete_on_session_get(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        api("POST", "/api/dictation/answer", {"position": 0, "character": "你"})
        api("POST", "/api/dictation/answer", {"position": 1, "character": "好"})
        code, data = api("GET", "/api/dictation/session")
        self.assertFalse(data["active"])
        self.assertTrue(data.get("auto_completed"))

    def test_start_replaces_existing_session(self):
        api("POST", "/api/dictation/start", {"characters": ["你", "好"]})
        api("POST", "/api/dictation/start", {"characters": ["大", "小"]})
        _, data = api("GET", "/api/dictation/session")
        self.assertTrue(data["active"])
        self.assertEqual(data["session"]["characters"], ["大", "小"])


# ═══════════════════════════════════════════════════════
# 4. get_history_characters
# ═══════════════════════════════════════════════════════

class TestGetHistoryCharacters(unittest.TestCase):
    def setUp(self):
        _reset_db()

    def test_returns_unique_chars_in_order(self):
        with sqlite3.connect(TMP_DB) as conn:
            conn.execute("INSERT INTO query_history (query, characters) VALUES ('a', '你好')")
            conn.execute("INSERT INTO query_history (query, characters) VALUES ('b', '好的')")
        chars = srv.get_history_characters()
        self.assertEqual(chars[0], "好")
        self.assertEqual(chars[1], "的")
        self.assertEqual(chars[2], "你")
        self.assertEqual(len(set(chars)), len(chars))


if __name__ == "__main__":
    unittest.main()
