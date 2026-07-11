#!/usr/bin/env python3
"""Layer-level backend tests for repository/service refactor.

These tests verify behavior below the HTTP handler so the refactor does not
only preserve endpoint smoke tests, but also gives future features stable
backend seams to build on.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.database import initialize_database
from backend.repositories import DictationRepository, HistoryRepository
from backend.services import DictationService, HistoryService


class BackendLayerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.sqlite3")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


class TestDatabaseMigration(BackendLayerTestCase):
    def test_initialize_database_creates_expected_tables_and_indexes(self):
        initialize_database(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }

        self.assertIn("query_history", tables)
        self.assertIn("dictation_session", tables)
        self.assertIn("dictation_session_result", tables)
        self.assertIn("dictation_history", tables)
        self.assertIn("dictation_session_state", tables)
        self.assertIn("idx_query_history_created_at", indexes)
        self.assertIn("idx_dictation_history_created_at", indexes)

    def test_initialize_database_migrates_old_history_table_without_losing_rows(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE query_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    characters TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
            conn.execute(
                "INSERT INTO query_history (query, characters) VALUES (?, ?)",
                ("小学", "小学"),
            )

        initialize_database(self.db_path)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, feature, query, characters FROM query_history"
            ).fetchone()
            columns = {
                item[1] for item in conn.execute("PRAGMA table_info(query_history)")
            }

        self.assertIn("feature", columns)
        self.assertEqual(dict(row), {
            "id": 1,
            "feature": "hanzi",
            "query": "小学",
            "characters": "小学",
        })


class TestHistoryService(BackendLayerTestCase):
    def setUp(self):
        super().setUp()
        initialize_database(self.db_path)
        self.service = HistoryService(HistoryRepository(self.db_path))

    def test_history_service_filters_characters_and_lists_newest_first(self):
        first = self.service.create("小学", "hanzi", "小abc学")
        second = self.service.create("语文", "words", "语1文")

        self.assertEqual(first["characters"], "小学")
        self.assertEqual(second["characters"], "语文")

        items = self.service.list(limit=10)
        self.assertEqual([item["id"] for item in items], [second["id"], first["id"]])
        self.assertEqual(items[0]["feature"], "words")

    def test_history_service_rejects_empty_query_or_no_hanzi(self):
        with self.assertRaises(ValueError):
            self.service.create("", "hanzi", "小学")
        with self.assertRaises(ValueError):
            self.service.create("abc", "hanzi", "abc")

    def test_history_service_deletes_only_valid_ids(self):
        keep = self.service.create("一", "hanzi", "一")
        remove = self.service.create("二", "hanzi", "二")

        deleted = self.service.delete(["bad", remove["id"]])

        self.assertEqual(deleted, 1)
        self.assertEqual([item["id"] for item in self.service.list()], [keep["id"]])


class TestDictationService(BackendLayerTestCase):
    def setUp(self):
        super().setUp()
        initialize_database(self.db_path)
        self.service = DictationService(DictationRepository(self.db_path))

    def test_dictation_service_lifecycle_and_history_summary(self):
        started = self.service.start(["小", "a", "小", "学"])
        self.assertEqual(started["characters"], ["小", "学"])

        wrong = self.service.answer(0, "大")
        correct_after_retry = self.service.answer(0, "小")
        second = self.service.answer(1, "学")
        completed = self.service.complete()
        history = self.service.history()

        self.assertFalse(wrong["correct"])
        self.assertEqual(correct_after_retry["wrong_attempts"], 1)
        self.assertTrue(second["correct"])
        self.assertEqual(completed["total"], 2)
        self.assertEqual(completed["correct"], 1)
        self.assertEqual(completed["wrong_characters"], ["小"])
        self.assertEqual(history[0]["wrong_characters"], "小")

    def test_dictation_service_restores_active_session(self):
        self.service.start(["语", "文"])
        self.service.answer(0, "语")

        restored = self.service.get_session()

        self.assertTrue(restored["active"])
        self.assertEqual(restored["session"]["current_index"], 1)
        self.assertEqual(restored["session"]["characters"], ["语", "文"])


if __name__ == "__main__":
    unittest.main()
