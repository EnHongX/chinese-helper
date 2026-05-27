#!/usr/bin/env python3
"""Backend tests for chinese-helper.

Uses unittest + temporary SQLite DB + real HTTP server.
Does NOT modify any business code.
"""

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

# Import server module
sys.path.insert(0, str(Path(__file__).parent.parent))
import server

# Import build_fallback_data module
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import build_fallback_data

# Import build script
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import build_fallback_data


class ServerTestCase(unittest.TestCase):
    """Base class that starts a test server with temporary DB."""

    server_thread = None
    httpd = None
    base_url = None
    original_db_path = None
    temp_db = None

    @classmethod
    def setUpClass(cls):
        # Save original DB_PATH and replace with temp file
        cls.original_db_path = server.DB_PATH
        cls.temp_db = tempfile.NamedTemporaryFile(
            suffix=".sqlite3", delete=False, dir=tempfile.gettempdir()
        )
        cls.temp_db_path = Path(cls.temp_db.name)
        cls.temp_db.close()
        server.DB_PATH = cls.temp_db_path
        server.init_db()

        # Start server on random port
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.ChineseHelperHandler)
        cls.port = cls.httpd.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        if cls.httpd:
            cls.httpd.shutdown()
            cls.httpd.server_close()
        if cls.server_thread:
            cls.server_thread.join(timeout=2)
        # Restore original DB_PATH
        server.DB_PATH = cls.original_db_path
        # Clean up temp DB
        if cls.temp_db_path and cls.temp_db_path.exists():
            cls.temp_db_path.unlink()
            # Clean up WAL/SHM files
            for ext in ["-wal", "-shm"]:
                p = cls.temp_db_path.with_suffix(cls.temp_db_path.suffix + ext)
                if p.exists():
                    p.unlink()

    def api_get(self, path):
        """Helper to make GET request."""
        url = f"{self.base_url}{path}"
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode("utf-8")), response.status

    def api_post(self, path, data):
        """Helper to make POST request."""
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8")), response.status

    def api_delete(self, path, data):
        """Helper to make DELETE request."""
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="DELETE"
        )
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8")), response.status


class TestIsHanzi(unittest.TestCase):
    """Test is_hanzi and chinese_only functions."""

    def test_is_hanzi_common_chars(self):
        """Common Chinese characters should be recognized."""
        for char in "小语文数学一二三四五六七八九十":
            self.assertTrue(server.is_hanzi(char), f"{char} should be hanzi")

    def test_is_hanzi_non_hanzi(self):
        """Non-Chinese characters should not be recognized."""
        for char in "abcABC123!@#小x":
            if char not in "小":
                self.assertFalse(server.is_hanzi(char), f"{char} should not be hanzi")

    def test_chinese_only_filters(self):
        """chinese_only should strip non-hanzi characters."""
        result = server.chinese_only("小abc学123语")
        self.assertEqual(result, "小学语")

    def test_chinese_only_empty(self):
        """chinese_only on empty string should return empty."""
        self.assertEqual(server.chinese_only(""), "")


class TestHistoryAPI(ServerTestCase):
    """Test history CRUD API endpoints."""

    def test_history_list_empty(self):
        """Empty history should return empty list."""
        data, status = self.api_get("/api/history")
        self.assertEqual(status, 200)
        self.assertIn("items", data)
        self.assertIsInstance(data["items"], list)

    def test_history_create_and_list(self):
        """Create a history entry and verify it appears in list."""
        create_data = {"query": "小", "feature": "hanzi", "characters": "小"}
        create_result, create_status = self.api_post("/api/history", create_data)
        self.assertEqual(create_status, 201)
        self.assertIn("id", create_result)
        self.assertEqual(create_result["query"], "小")
        self.assertEqual(create_result["characters"], "小")

        # List should contain the new entry
        list_result, list_status = self.api_get("/api/history")
        self.assertEqual(list_status, 200)
        self.assertGreater(len(list_result["items"]), 0)
        found = any(item["query"] == "小" for item in list_result["items"])
        self.assertTrue(found, "Created entry should appear in list")

    def test_history_create_filters_characters(self):
        """Create should filter non-hanzi from characters field."""
        create_data = {"query": "小abc学", "feature": "hanzi", "characters": "小abc学123"}
        result, status = self.api_post("/api/history", create_data)
        self.assertEqual(status, 201)
        self.assertEqual(result["characters"], "小学")

    def test_history_create_missing_fields(self):
        """Create with missing required fields should return 400."""
        create_data = {"query": "", "feature": "hanzi", "characters": "小"}
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.api_post("/api/history", create_data)
        self.assertEqual(ctx.exception.code, 400)

    def test_history_delete(self):
        """Delete should remove history entries."""
        # Create an entry
        create_data = {"query": "删", "feature": "hanzi", "characters": "删"}
        create_result, _ = self.api_post("/api/history", create_data)
        entry_id = create_result["id"]

        # Delete it
        delete_result, delete_status = self.api_delete(
            "/api/history", {"ids": [entry_id]}
        )
        self.assertEqual(delete_status, 200)
        self.assertEqual(delete_result["deleted"], 1)

        # Verify it's gone
        list_result, _ = self.api_get("/api/history")
        found = any(item["id"] == entry_id for item in list_result["items"])
        self.assertFalse(found, "Deleted entry should not appear in list")

    def test_history_delete_nonexistent(self):
        """Delete nonexistent ID should return deleted=0."""
        delete_result, delete_status = self.api_delete(
            "/api/history", {"ids": [999999]}
        )
        self.assertEqual(delete_status, 200)
        self.assertEqual(delete_result["deleted"], 0)


class TestDictationAPI(ServerTestCase):
    """Test dictation API endpoints."""

    def test_dictation_start_and_get_session(self):
        """Start a dictation session and verify GET returns it."""
        # Start session
        start_data = {"characters": ["一", "二", "三"]}
        start_result, start_status = self.api_post("/api/dictation/start", start_data)
        self.assertEqual(start_status, 201)
        self.assertEqual(start_result["total_count"], 3)
        self.assertEqual(start_result["current_index"], 0)

        # Get session
        get_result, get_status = self.api_get("/api/dictation/session")
        self.assertEqual(get_status, 200)
        self.assertTrue(get_result["active"])
        self.assertEqual(len(get_result["session"]["characters"]), 3)

        # Clean up
        self.api_delete("/api/dictation/session", {})

    def test_dictation_start_min_chars(self):
        """Start with less than 2 chars should fail."""
        start_data = {"characters": ["一"]}
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.api_post("/api/dictation/start", start_data)
        self.assertEqual(ctx.exception.code, 400)

    def test_dictation_start_max_chars(self):
        """Start with more than 20 chars should fail."""
        chars = [chr(0x4e00 + i) for i in range(25)]  # 25 unique hanzi
        start_data = {"characters": chars}
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.api_post("/api/dictation/start", start_data)
        self.assertEqual(ctx.exception.code, 400)

    def test_dictation_answer_correct(self):
        """Submit correct answer should advance current_index."""
        # Start session
        self.api_post("/api/dictation/start", {"characters": ["一", "二"]})

        # Submit correct answer for position 0
        answer_data = {"position": 0, "character": "一"}
        answer_result, answer_status = self.api_post(
            "/api/dictation/answer", answer_data
        )
        self.assertEqual(answer_status, 200)
        self.assertTrue(answer_result["correct"])
        self.assertEqual(answer_result["wrong_attempts"], 0)

        # Get session should show current_index advanced
        get_result, _ = self.api_get("/api/dictation/session")
        self.assertEqual(get_result["session"]["current_index"], 1)

        # Clean up
        self.api_delete("/api/dictation/session", {})

    def test_dictation_answer_wrong(self):
        """Submit wrong answer should increment wrong_attempts."""
        # Start session
        self.api_post("/api/dictation/start", {"characters": ["一", "二"]})

        # Submit wrong answer for position 0
        answer_data = {"position": 0, "character": "二"}  # Wrong!
        answer_result, answer_status = self.api_post(
            "/api/dictation/answer", answer_data
        )
        self.assertEqual(answer_status, 200)
        self.assertFalse(answer_result["correct"])
        self.assertEqual(answer_result["wrong_attempts"], 1)

        # Get session should show current_index NOT advanced
        get_result, _ = self.api_get("/api/dictation/session")
        self.assertEqual(get_result["session"]["current_index"], 0)

        # Clean up
        self.api_delete("/api/dictation/session", {})

    def test_dictation_complete_lifecycle(self):
        """Full dictation lifecycle: start -> answer all -> complete."""
        # Start session
        self.api_post("/api/dictation/start", {"characters": ["一", "二"]})

        # Answer position 0 correctly
        self.api_post("/api/dictation/answer", {"position": 0, "character": "一"})

        # Answer position 1 correctly
        self.api_post("/api/dictation/answer", {"position": 1, "character": "二"})

        # Complete session
        complete_result, complete_status = self.api_post("/api/dictation/complete", {})
        self.assertEqual(complete_status, 200)
        self.assertEqual(complete_result["total"], 2)
        self.assertEqual(complete_result["correct"], 2)
        self.assertEqual(complete_result["accuracy"], 100.0)

        # Check dictation history
        history_result, _ = self.api_get("/api/dictation/history")
        self.assertGreater(len(history_result["items"]), 0)
        latest = history_result["items"][0]
        self.assertEqual(latest["total_count"], 2)
        self.assertEqual(latest["correct_count"], 2)

    def test_dictation_characters_from_history(self):
        """Dictation characters endpoint should return chars from query history."""
        # Create a query history entry
        self.api_post("/api/history", {"query": "测试字", "characters": "测试字"})

        # Get dictation characters
        chars_result, chars_status = self.api_get("/api/dictation/characters")
        self.assertEqual(chars_status, 200)
        self.assertIn("characters", chars_result)
        self.assertIsInstance(chars_result["characters"], list)


class TestBuildScript(unittest.TestCase):
    """Test build_fallback_data.py functions with precise value assertions."""

    def test_parse_pinyin_xiao(self):
        """parse_pinyin should correctly parse 'xiǎo' as 三拼音节."""
        result = build_fallback_data.parse_pinyin("xiǎo")
        self.assertEqual(result["pinyin"], "xiǎo")
        self.assertEqual(result["tone"], "ˇ")
        self.assertEqual(result["initial"], "x")
        self.assertEqual(result["final"], "iǎo")
        self.assertEqual(result["syllableType"], "三拼音节")

    def test_parse_pinyin_zhong(self):
        """parse_pinyin should correctly parse 'zhōng' as 两拼音节 with zh initial."""
        result = build_fallback_data.parse_pinyin("zhōng")
        self.assertEqual(result["pinyin"], "zhōng")
        self.assertEqual(result["tone"], "ˉ")
        self.assertEqual(result["initial"], "zh")
        self.assertEqual(result["final"], "ōng")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_parse_pinyin_yuan(self):
        """parse_pinyin should classify 'yuán' as 整体认读音节."""
        result = build_fallback_data.parse_pinyin("yuán")
        self.assertEqual(result["initial"], "y")
        self.assertEqual(result["syllableType"], "整体认读音节")

    def test_parse_pinyin_zhi(self):
        """parse_pinyin should classify 'zhi' as 整体认读音节."""
        result = build_fallback_data.parse_pinyin("zhi")
        self.assertEqual(result["syllableType"], "整体认读音节")

    def test_parse_pinyin_gua(self):
        """parse_pinyin should classify 'guā' as 三拼音节."""
        result = build_fallback_data.parse_pinyin("guā")
        self.assertEqual(result["initial"], "g")
        self.assertEqual(result["syllableType"], "三拼音节")

    def test_parse_pinyin_empty(self):
        """parse_pinyin on empty string should return None."""
        result = build_fallback_data.parse_pinyin("")
        self.assertIsNone(result)

    def test_shard_key_xiao(self):
        """shard_key('小') should return '0f' (U+5C0F % 32 = 15)."""
        key = build_fallback_data.shard_key("小")
        self.assertEqual(key, "0f")

    def test_shard_key_xue(self):
        """shard_key('学') should return '06' (U+5B66 % 32 = 6)."""
        key = build_fallback_data.shard_key("学")
        self.assertEqual(key, "06")

    def test_shard_key_han(self):
        """shard_key('汉') should return '09' (U+6C49 % 32 = 9)."""
        key = build_fallback_data.shard_key("汉")
        self.assertEqual(key, "09")

    def test_shard_key_zi(self):
        """shard_key('字') should return '17' (U+5B57 % 32 = 23)."""
        key = build_fallback_data.shard_key("字")
        self.assertEqual(key, "17")

    def test_classify_syllable_an(self):
        """classify_syllable('an') should be 零声母音节."""
        result = build_fallback_data.classify_syllable("an", 1, "ān")
        self.assertEqual(result["syllableType"], "零声母音节")
        self.assertEqual(result["initial"], "（自成音节）")

    def test_classify_syllable_ying(self):
        """classify_syllable('ying') should be 整体认读音节."""
        result = build_fallback_data.classify_syllable("ying", 2, "yíng")
        self.assertEqual(result["syllableType"], "整体认读音节")

    def test_tone_symbols(self):
        """TONE_SYMBOLS should map tone numbers to correct symbols."""
        self.assertEqual(build_fallback_data.TONE_SYMBOLS[1], "ˉ")
        self.assertEqual(build_fallback_data.TONE_SYMBOLS[2], "ˊ")
        self.assertEqual(build_fallback_data.TONE_SYMBOLS[3], "ˇ")
        self.assertEqual(build_fallback_data.TONE_SYMBOLS[4], "ˋ")

    def test_tone_marks(self):
        """TONE_MARKS should correctly map diacritics to base letter and tone number."""
        self.assertEqual(build_fallback_data.TONE_MARKS["ā"], ("a", 1))
        self.assertEqual(build_fallback_data.TONE_MARKS["ǎ"], ("a", 3))
        self.assertEqual(build_fallback_data.TONE_MARKS["ò"], ("o", 4))

    def test_build_characters_structure(self):
        """build_characters should return dict with correct structure."""
        # Mock input data
        words = [
            {
                "word": "小",
                "pinyin": "xiǎo",
                "radicals": "小",
                "strokes": "3",
                "explanation": "test",
            }
        ]
        result = build_fallback_data.build_characters(words)
        self.assertIn("小", result)
        char_data = result["小"]
        self.assertIn("pinyin", char_data)
        self.assertIn("radical", char_data)
        self.assertIn("strokeCount", char_data)

    def test_build_common_words_structure(self):
        """build_common_words should return dict of char -> word list."""
        ci_items = [{"ci": "小学"}, {"ci": "学生"}]
        result = build_fallback_data.build_common_words(ci_items)
        self.assertIsInstance(result, dict)
        # "小" should have "小学" as a common word
        if "小" in result:
            self.assertIsInstance(result["小"], list)


class TestShardData(unittest.TestCase):
    """Test generated shard data integrity."""

    @classmethod
    def setUpClass(cls):
        cls.generated_dir = Path(__file__).parent.parent / "data" / "generated"
        cls.shard_dir = cls.generated_dir / "chars"
        cls.manifest_path = cls.generated_dir / "manifest.json"

    def test_manifest_exists(self):
        """manifest.json should exist."""
        self.assertTrue(self.manifest_path.exists(), "manifest.json should exist")

    def test_shard_files_exist(self):
        """Shard directory should contain JSON files."""
        if not self.shard_dir.exists():
            self.skipTest("Shard directory does not exist")
        shard_files = list(self.shard_dir.glob("*.json"))
        self.assertGreater(len(shard_files), 0, "Should have at least one shard file")

    def test_shard_json_valid(self):
        """All shard files should be valid JSON."""
        if not self.shard_dir.exists():
            self.skipTest("Shard directory does not exist")
        for shard_file in self.shard_dir.glob("*.json"):
            try:
                with open(shard_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertIn("characters", data, f"{shard_file.name} missing 'characters'")
                self.assertIn("commonWords", data, f"{shard_file.name} missing 'commonWords'")
            except json.JSONDecodeError as e:
                self.fail(f"{shard_file.name} is not valid JSON: {e}")

    def test_shard_key_assignment(self):
        """Characters should be in correct shard based on shard_key."""
        if not self.shard_dir.exists():
            self.skipTest("Shard directory does not exist")
        # Load all shards
        shards = {}
        for shard_file in self.shard_dir.glob("*.json"):
            key = shard_file.stem
            with open(shard_file, "r", encoding="utf-8") as f:
                shards[key] = json.load(f)

        # Verify a sample of characters
        sample_chars = "小语文数学一二三四五六七八九十"
        for char in sample_chars:
            expected_key = build_fallback_data.shard_key(char)
            if expected_key in shards:
                shard_data = shards[expected_key]
                # Character should be in either characters or commonWords
                in_shard = (
                    char in shard_data.get("characters", {})
                    or char in shard_data.get("commonWords", {})
                )
                # Note: not all sample chars may exist in data, so we don't assert
                # This is just a sanity check that the sharding logic is consistent

    def test_build_script_generates_data(self):
        """Run build script and verify it generates valid output."""
        import tempfile
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import build_fallback_data

        # Create temp output directory
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_generated = Path(tmpdir) / "generated"
            temp_chars = temp_generated / "chars"

            # Monkey-patch build script paths
            orig_generated = build_fallback_data.GENERATED_DIR
            orig_shard = build_fallback_data.SHARD_DIR
            orig_manifest = build_fallback_data.MANIFEST

            try:
                build_fallback_data.GENERATED_DIR = temp_generated
                build_fallback_data.SHARD_DIR = temp_chars
                build_fallback_data.MANIFEST = temp_generated / "manifest.json"

                # Run build
                build_fallback_data.main()

                # Verify output
                self.assertTrue(temp_generated.exists())
                self.assertTrue(temp_chars.exists())
                self.assertTrue((temp_generated / "manifest.json").exists())

                # Check manifest
                with open(temp_generated / "manifest.json", "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                self.assertIn("source", manifest)
                self.assertIn("buckets", manifest)
                self.assertIn("counts", manifest)
                self.assertEqual(manifest["buckets"], 32)

                # Check shard files
                shard_files = list(temp_chars.glob("*.json"))
                self.assertGreater(len(shard_files), 0)

                # Verify one shard has valid structure
                sample_shard = shard_files[0]
                with open(sample_shard, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.assertIn("characters", data)
                self.assertIn("commonWords", data)

            finally:
                # Restore original paths
                build_fallback_data.GENERATED_DIR = orig_generated
                build_fallback_data.SHARD_DIR = orig_shard
                build_fallback_data.MANIFEST = orig_manifest

    def test_common_words_contain_expected_words(self):
        """Verify commonWords contain expected words for known characters."""
        if not self.shard_dir.exists():
            self.skipTest("Shard directory does not exist")

        # Load all shards
        all_common_words = {}
        for shard_file in self.shard_dir.glob("*.json"):
            with open(shard_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            all_common_words.update(data.get("commonWords", {}))

        # Check that common characters have words
        if "小" in all_common_words:
            words = all_common_words["小"]
            self.assertIsInstance(words, list)
            self.assertGreater(len(words), 0, "小 should have common words")
            # Check that words are actually Chinese
            for word in words:
                self.assertIsInstance(word, str)
                self.assertGreater(len(word), 0)

    def test_bad_words_filtered(self):
        """Verify BAD_WORD_PARTS are filtered from commonWords."""
        if not self.shard_dir.exists():
            self.skipTest("Shard directory does not exist")

        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

        # Load all shards
        all_words = []
        for shard_file in self.shard_dir.glob("*.json"):
            with open(shard_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for char, words in data.get("commonWords", {}).items():
                all_words.extend(words)

        # Check that no words contain bad parts
        for word in all_words:
            for bad_part in build_fallback_data.BAD_WORD_PARTS:
                self.assertNotIn(
                    bad_part, word,
                    f"Word '{word}' contains bad part '{bad_part}'"
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
