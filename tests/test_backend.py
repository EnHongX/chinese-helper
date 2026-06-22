#!/usr/bin/env python3
"""Backend tests for chinese-helper server.py.

Tests history CRUD, input filtering, dictation lifecycle, and is_hanzi.
Uses a temporary SQLite database — never touches the real data.
No business code was modified for these tests.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import warnings
from types import SimpleNamespace
from unittest.mock import patch

# The server uses `with sqlite3.connect() as conn:` which does not call close()
# on __exit__ (only commit/rollback). This is a known sqlite3 pattern — we
# cannot change business code, so filter the resulting ResourceWarning.
warnings.filterwarnings("ignore", category=ResourceWarning, message=".*unclosed.*")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import server as srv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler():
    """Create a ChineseHelperHandler with mocked I/O for unit testing."""
    handler = object.__new__(srv.ChineseHelperHandler)
    handler._response_body = None
    handler._response_status = None
    handler._request_body = b""

    def mock_send_json(payload, status=None):
        handler._response_body = payload
        handler._response_status = status or 200

    handler.send_json = mock_send_json

    def mock_read_json_body():
        if not handler._request_body:
            return None
        try:
            return json.loads(handler._request_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    handler.read_json_body = mock_read_json_body
    return handler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIsHanzi(unittest.TestCase):

    def test_common_hanzi(self):
        self.assertTrue(srv.is_hanzi("小"))
        self.assertTrue(srv.is_hanzi("学"))
        self.assertTrue(srv.is_hanzi("语"))

    def test_extension_a(self):
        self.assertTrue(srv.is_hanzi("㐀"))
        self.assertTrue(srv.is_hanzi("䶿"))

    def test_cjk_compatibility(self):
        self.assertTrue(srv.is_hanzi("豈"))

    def test_non_hanzi_ascii(self):
        self.assertFalse(srv.is_hanzi("a"))
        self.assertFalse(srv.is_hanzi("1"))
        self.assertFalse(srv.is_hanzi(" "))

    def test_non_hanzi_punctuation(self):
        self.assertFalse(srv.is_hanzi("，"))
        self.assertFalse(srv.is_hanzi("。"))
        self.assertFalse(srv.is_hanzi("！"))

    def test_non_hanzi_kana(self):
        self.assertFalse(srv.is_hanzi("あ"))
        self.assertFalse(srv.is_hanzi("ア"))

    def test_surrogate_pair_hanzi(self):
        self.assertTrue(srv.is_hanzi("\U00020000"))
        self.assertTrue(srv.is_hanzi("\U0002a6df"))


class TestChineseOnly(unittest.TestCase):

    def test_pure_hanzi(self):
        self.assertEqual(srv.chinese_only("小学语文"), "小学语文")

    def test_mixed_input(self):
        self.assertEqual(srv.chinese_only("小abc学123"), "小学")

    def test_with_punctuation(self):
        self.assertEqual(srv.chinese_only("小，学。语！文"), "小学语文")

    def test_empty_string(self):
        self.assertEqual(srv.chinese_only(""), "")

    def test_no_hanzi(self):
        self.assertEqual(srv.chinese_only("hello123"), "")

    def test_with_spaces(self):
        self.assertEqual(srv.chinese_only("小 学 语 文"), "小学语文")


class TestHistoryWithTempDB(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.sqlite3")
        self._patcher = patch.object(srv, "DB_PATH", srv.Path(self.db_path))
        self._patcher.start()
        srv.init_db()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _insert_history(self, feature="hanzi", query="小学", characters="小学"):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO query_history (feature, query, characters) VALUES (?, ?, ?)",
                (feature, query, characters),
            )
            return cursor.lastrowid

    def _make_parsed(self, query_str=""):
        return SimpleNamespace(query=query_str)

    # -- Create --

    def test_history_create_success(self):
        handler = _make_handler()
        handler._request_body = json.dumps({
            "query": "小学语文", "feature": "hanzi", "characters": "小学语文",
        }).encode()
        handler.handle_history_create()
        self.assertEqual(handler._response_status, 201)
        body = handler._response_body
        self.assertIn("id", body)
        self.assertEqual(body["feature"], "hanzi")
        self.assertEqual(body["query"], "小学语文")
        self.assertEqual(body["characters"], "小学语文")

    def test_history_create_filters_non_hanzi(self):
        handler = _make_handler()
        handler._request_body = json.dumps({
            "query": "abc", "feature": "hanzi", "characters": "小abc学",
        }).encode()
        handler.handle_history_create()
        self.assertEqual(handler._response_status, 201)
        self.assertEqual(handler._response_body["characters"], "小学")

    def test_history_create_empty_query_rejected(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"query": "", "characters": "小学"}).encode()
        handler.handle_history_create()
        self.assertEqual(handler._response_status, 400)

    def test_history_create_empty_characters_rejected(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"query": "hello", "characters": "abc"}).encode()
        handler.handle_history_create()
        self.assertEqual(handler._response_status, 400)

    def test_history_create_default_feature(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"query": "大山", "characters": "大山"}).encode()
        handler.handle_history_create()
        self.assertEqual(handler._response_status, 201)
        self.assertEqual(handler._response_body["feature"], "hanzi")

    def test_history_create_invalid_json(self):
        handler = _make_handler()
        handler._request_body = b"not json"
        handler.handle_history_create()
        self.assertEqual(handler._response_status, 400)

    # -- List --

    def test_history_list_empty(self):
        handler = _make_handler()
        handler.handle_history_list(self._make_parsed())
        self.assertEqual(handler._response_body["items"], [])

    def test_history_list_returns_items(self):
        self._insert_history(query="小学", characters="小学")
        self._insert_history(query="语文", characters="语文")
        handler = _make_handler()
        handler.handle_history_list(self._make_parsed())
        self.assertEqual(len(handler._response_body["items"]), 2)

    def test_history_list_respects_limit(self):
        for i in range(10):
            self._insert_history(query=f"字{i}", characters=f"字{i}")
        handler = _make_handler()
        handler.handle_history_list(self._make_parsed("limit=3"))
        self.assertEqual(len(handler._response_body["items"]), 3)

    def test_history_list_ordered_by_id_desc(self):
        id1 = self._insert_history(query="一", characters="一")
        id2 = self._insert_history(query="二", characters="二")
        handler = _make_handler()
        handler.handle_history_list(self._make_parsed())
        items = handler._response_body["items"]
        self.assertEqual(items[0]["id"], id2)
        self.assertEqual(items[1]["id"], id1)

    def test_history_list_invalid_limit_defaults(self):
        self._insert_history(query="一", characters="一")
        handler = _make_handler()
        handler.handle_history_list(self._make_parsed("limit=abc"))
        # Invalid limit should default to 12
        self.assertEqual(handler._response_status, 200)

    # -- Delete --

    def test_history_delete_by_ids(self):
        id1 = self._insert_history(query="一", characters="一")
        id2 = self._insert_history(query="二", characters="二")
        handler = _make_handler()
        handler._request_body = json.dumps({"ids": [id1]}).encode()
        handler.handle_history_delete()
        self.assertEqual(handler._response_body["deleted"], 1)
        with sqlite3.connect(self.db_path) as conn:
            remaining = conn.execute("SELECT id FROM query_history").fetchall()
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0][0], id2)

    def test_history_delete_multiple(self):
        id1 = self._insert_history(query="一", characters="一")
        id2 = self._insert_history(query="二", characters="二")
        id3 = self._insert_history(query="三", characters="三")
        handler = _make_handler()
        handler._request_body = json.dumps({"ids": [id1, id2, id3]}).encode()
        handler.handle_history_delete()
        self.assertEqual(handler._response_body["deleted"], 3)

    def test_history_delete_nonexistent_ids(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"ids": [999, 1000]}).encode()
        handler.handle_history_delete()
        self.assertEqual(handler._response_body["deleted"], 0)

    def test_history_delete_empty_ids(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"ids": []}).encode()
        handler.handle_history_delete()
        self.assertEqual(handler._response_body["deleted"], 0)

    def test_history_delete_non_list_ids(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"ids": "not_a_list"}).encode()
        handler.handle_history_delete()
        self.assertEqual(handler._response_status, 400)

    def test_history_delete_invalid_json(self):
        handler = _make_handler()
        handler._request_body = b"bad"
        handler.handle_history_delete()
        self.assertEqual(handler._response_status, 400)

    def test_history_delete_ignores_non_int_ids(self):
        id1 = self._insert_history(query="一", characters="一")
        handler = _make_handler()
        handler._request_body = json.dumps({"ids": ["abc", id1]}).encode()
        handler.handle_history_delete()
        self.assertEqual(handler._response_body["deleted"], 1)


class TestDictationWithTempDB(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.sqlite3")
        self._patcher = patch.object(srv, "DB_PATH", srv.Path(self.db_path))
        self._patcher.start()
        srv.init_db()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # -- Start --

    def test_dictation_start_success(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        handler.handle_dictation_start()
        self.assertEqual(handler._response_status, 201)
        body = handler._response_body
        self.assertEqual(body["characters"], ["小", "学"])
        self.assertEqual(body["total_count"], 2)
        self.assertEqual(body["current_index"], 0)

    def test_dictation_start_too_few(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"characters": ["小"]}).encode()
        handler.handle_dictation_start()
        self.assertEqual(handler._response_status, 400)

    def test_dictation_start_retry_allows_single(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"characters": ["小"], "retry": True}).encode()
        handler.handle_dictation_start()
        self.assertEqual(handler._response_status, 201)

    def test_dictation_start_too_many(self):
        chars = list("一二三四五六七八九十百千万年前后左右山水火土天地人")[:21]
        self.assertEqual(len(chars), 21)
        handler = _make_handler()
        handler._request_body = json.dumps({"characters": chars}).encode()
        handler.handle_dictation_start()
        self.assertEqual(handler._response_status, 400)

    def test_dictation_start_deduplicates(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"characters": ["小", "小", "学"]}).encode()
        handler.handle_dictation_start()
        self.assertEqual(handler._response_body["characters"], ["小", "学"])
        self.assertEqual(handler._response_body["total_count"], 2)

    def test_dictation_start_filters_non_hanzi(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"characters": ["小", "a", "学"]}).encode()
        handler.handle_dictation_start()
        self.assertEqual(handler._response_body["characters"], ["小", "学"])

    def test_dictation_start_not_a_list(self):
        handler = _make_handler()
        handler._request_body = json.dumps({"characters": "小学"}).encode()
        handler.handle_dictation_start()
        self.assertEqual(handler._response_status, 400)

    def test_dictation_start_clears_previous_session(self):
        h1 = _make_handler()
        h1._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h1.handle_dictation_start()

        h2 = _make_handler()
        h2._request_body = json.dumps({"characters": ["语", "文"]}).encode()
        h2.handle_dictation_start()
        self.assertEqual(h2._response_status, 201)
        self.assertEqual(h2._response_body["characters"], ["语", "文"])

    # -- Answer --

    def test_dictation_answer_correct(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        h2 = _make_handler()
        h2._request_body = json.dumps({"position": 0, "character": "小"}).encode()
        h2.handle_dictation_answer()
        self.assertTrue(h2._response_body["correct"])
        self.assertEqual(h2._response_body["wrong_attempts"], 0)

    def test_dictation_answer_wrong(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        h2 = _make_handler()
        h2._request_body = json.dumps({"position": 0, "character": "大"}).encode()
        h2.handle_dictation_answer()
        self.assertFalse(h2._response_body["correct"])
        self.assertEqual(h2._response_body["wrong_attempts"], 1)

    def test_dictation_answer_wrong_then_correct(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        h2 = _make_handler()
        h2._request_body = json.dumps({"position": 0, "character": "大"}).encode()
        h2.handle_dictation_answer()

        h3 = _make_handler()
        h3._request_body = json.dumps({"position": 0, "character": "小"}).encode()
        h3.handle_dictation_answer()
        self.assertTrue(h3._response_body["correct"])
        self.assertEqual(h3._response_body["wrong_attempts"], 1)

    def test_dictation_answer_no_session(self):
        h = _make_handler()
        h._request_body = json.dumps({"position": 0, "character": "小"}).encode()
        h.handle_dictation_answer()
        self.assertEqual(h._response_status, 404)

    def test_dictation_answer_position_out_of_range(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        h2 = _make_handler()
        h2._request_body = json.dumps({"position": 5, "character": "小"}).encode()
        h2.handle_dictation_answer()
        self.assertEqual(h2._response_status, 400)

    def test_dictation_answer_non_hanzi_character(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        h2 = _make_handler()
        h2._request_body = json.dumps({"position": 0, "character": "a"}).encode()
        h2.handle_dictation_answer()
        self.assertEqual(h2._response_status, 400)

    def test_dictation_answer_invalid_position_type(self):
        h = _make_handler()
        h._request_body = json.dumps({"position": "zero", "character": "小"}).encode()
        h.handle_dictation_answer()
        self.assertEqual(h._response_status, 400)

    # -- Session GET --

    def test_dictation_session_get_no_active(self):
        h = _make_handler()
        h.handle_dictation_session_get()
        self.assertFalse(h._response_body["active"])

    def test_dictation_session_get_active(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        h2 = _make_handler()
        h2.handle_dictation_session_get()
        self.assertTrue(h2._response_body["active"])
        self.assertEqual(h2._response_body["session"]["total_count"], 2)

    def test_dictation_session_auto_complete(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        for i, char in enumerate(["小", "学"]):
            ha = _make_handler()
            ha._request_body = json.dumps({"position": i, "character": char}).encode()
            ha.handle_dictation_answer()

        h2 = _make_handler()
        h2.handle_dictation_session_get()
        self.assertFalse(h2._response_body["active"])
        self.assertTrue(h2._response_body.get("auto_completed"))

    # -- Complete --

    def test_dictation_complete(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        for i, char in enumerate(["小", "学"]):
            ha = _make_handler()
            ha._request_body = json.dumps({"position": i, "character": char}).encode()
            ha.handle_dictation_answer()

        hc = _make_handler()
        hc.handle_dictation_complete()
        body = hc._response_body
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["correct"], 2)
        self.assertEqual(body["accuracy"], 100.0)
        self.assertEqual(body["wrong_characters"], [])

    def test_dictation_complete_no_session(self):
        hc = _make_handler()
        hc.handle_dictation_complete()
        self.assertEqual(hc._response_status, 404)

    def test_dictation_complete_with_wrong_answers(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        ha = _make_handler()
        ha._request_body = json.dumps({"position": 0, "character": "大"}).encode()
        ha.handle_dictation_answer()

        ha2 = _make_handler()
        ha2._request_body = json.dumps({"position": 1, "character": "学"}).encode()
        ha2.handle_dictation_answer()

        hc = _make_handler()
        hc.handle_dictation_complete()
        body = hc._response_body
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["correct"], 1)
        self.assertIn("小", body["wrong_characters"])

    # -- Delete session --

    def test_dictation_session_delete(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()

        hd = _make_handler()
        hd.handle_dictation_session_delete()
        self.assertTrue(hd._response_body["ok"])

        h2 = _make_handler()
        h2.handle_dictation_session_get()
        self.assertFalse(h2._response_body["active"])

    # -- Dictation history --

    def test_dictation_history_list(self):
        h = _make_handler()
        h._request_body = json.dumps({"characters": ["小", "学"]}).encode()
        h.handle_dictation_start()
        for i, char in enumerate(["小", "学"]):
            ha = _make_handler()
            ha._request_body = json.dumps({"position": i, "character": char}).encode()
            ha.handle_dictation_answer()
        hc = _make_handler()
        hc.handle_dictation_complete()

        hh = _make_handler()
        hh.handle_dictation_history_list()
        self.assertEqual(len(hh._response_body["items"]), 1)
        self.assertEqual(hh._response_body["items"][0]["total_count"], 2)

    def test_dictation_history_empty(self):
        hh = _make_handler()
        hh.handle_dictation_history_list()
        self.assertEqual(hh._response_body["items"], [])


class TestInitDB(unittest.TestCase):

    def test_init_db_creates_tables(self):
        tmp_dir = tempfile.mkdtemp()
        db_path = os.path.join(tmp_dir, "test.sqlite3")
        with patch.object(srv, "DB_PATH", srv.Path(db_path)):
            srv.init_db()
        with sqlite3.connect(db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("query_history", tables)
        self.assertIn("dictation_session", tables)
        self.assertIn("dictation_session_result", tables)
        self.assertIn("dictation_history", tables)
        self.assertIn("dictation_session_state", tables)
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
