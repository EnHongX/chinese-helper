#!/usr/bin/env python3
"""Tests for scripts/build_fallback_data.py.

Tests pinyin parsing, syllable classification, shard key, is_hanzi,
is_word_candidate, normalize_pinyin, AND runs the full build pipeline
in a temp directory to verify actual generated output with exact values.
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
import warnings

warnings.filterwarnings("ignore", category=ResourceWarning, message=".*unclosed.*")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(PROJECT_ROOT, "scripts", "build_fallback_data.py")

spec = importlib.util.spec_from_file_location("build_fallback_data", SCRIPT_PATH)
bfd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bfd)


class TestNormalizePinyin(unittest.TestCase):
    def test_fullwidth_g_replaced(self):
        self.assertEqual(bfd.normalize_pinyin("ɡāo"), "gāo")

    def test_whitespace_stripped(self):
        self.assertEqual(bfd.normalize_pinyin("  xiǎo  "), "xiǎo")

    def test_empty(self):
        self.assertEqual(bfd.normalize_pinyin(""), "")


class TestParsePinyin(unittest.TestCase):

    def test_tone_mark_first_tone(self):
        result = bfd.parse_pinyin("mā")
        self.assertIsNotNone(result)
        self.assertEqual(result["tone"], "ˉ")
        self.assertEqual(result["initial"], "m")
        self.assertEqual(result["final"], "ā")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_tone_mark_second_tone(self):
        result = bfd.parse_pinyin("má")
        self.assertIsNotNone(result)
        self.assertEqual(result["tone"], "ˊ")
        self.assertEqual(result["initial"], "m")
        self.assertEqual(result["final"], "á")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_tone_mark_third_tone(self):
        result = bfd.parse_pinyin("xiǎo")
        self.assertIsNotNone(result)
        self.assertEqual(result["tone"], "ˇ")
        self.assertEqual(result["initial"], "x")
        self.assertEqual(result["final"], "iǎo")
        self.assertEqual(result["syllableType"], "三拼音节")

    def test_tone_mark_fourth_tone(self):
        result = bfd.parse_pinyin("dà")
        self.assertIsNotNone(result)
        self.assertEqual(result["tone"], "ˋ")
        self.assertEqual(result["initial"], "d")
        self.assertEqual(result["final"], "à")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_digit_tone_xiao3(self):
        result = bfd.parse_pinyin("xiao3")
        self.assertIsNotNone(result)
        self.assertEqual(result["tone"], "ˇ")
        self.assertEqual(result["initial"], "x")
        self.assertEqual(result["final"], "iao")
        self.assertEqual(result["syllableType"], "三拼音节")

    def test_digit_tone_ma1(self):
        result = bfd.parse_pinyin("ma1")
        self.assertIsNotNone(result)
        self.assertEqual(result["tone"], "ˉ")
        self.assertEqual(result["initial"], "m")
        self.assertEqual(result["final"], "a")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_digit_tone_tone0(self):
        result = bfd.parse_pinyin("de0")
        self.assertIsNotNone(result)
        self.assertEqual(result["tone"], "")
        self.assertEqual(result["initial"], "d")
        self.assertEqual(result["final"], "e")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_none_for_empty(self):
        self.assertIsNone(bfd.parse_pinyin(""))

    def test_none_for_whitespace(self):
        self.assertIsNone(bfd.parse_pinyin("   "))

    def test_none_for_garbage(self):
        self.assertIsNone(bfd.parse_pinyin("123"))

    def test_whole_reading_syllable(self):
        result = bfd.parse_pinyin("shī")
        self.assertIsNotNone(result)
        self.assertEqual(result["syllableType"], "整体认读音节")
        self.assertEqual(result["initial"], "sh")
        self.assertEqual(result["final"], "ī")

    def test_zero_initial_syllable(self):
        result = bfd.parse_pinyin("ān")
        self.assertIsNotNone(result)
        self.assertEqual(result["syllableType"], "零声母音节")
        self.assertEqual(result["initial"], "（自成音节）")
        self.assertEqual(result["final"], "ān")

    def test_two_part_syllable(self):
        result = bfd.parse_pinyin("mā")
        self.assertIsNotNone(result)
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_three_part_syllable(self):
        result = bfd.parse_pinyin("xiǎo")
        self.assertIsNotNone(result)
        self.assertEqual(result["syllableType"], "三拼音节")

    def test_zh_initial(self):
        result = bfd.parse_pinyin("zhōng")
        self.assertIsNotNone(result)
        self.assertEqual(result["initial"], "zh")
        self.assertEqual(result["final"], "ōng")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_ch_initial(self):
        result = bfd.parse_pinyin("cháng")
        self.assertIsNotNone(result)
        self.assertEqual(result["initial"], "ch")
        self.assertEqual(result["final"], "áng")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_sh_initial(self):
        result = bfd.parse_pinyin("shū")
        self.assertIsNotNone(result)
        self.assertEqual(result["initial"], "sh")
        self.assertEqual(result["final"], "ū")
        self.assertEqual(result["syllableType"], "两拼音节")

    def test_whole_reading_zhi(self):
        """'zhi' is a whole-reading syllable (整体认读音节)."""
        result = bfd.parse_pinyin("zhī")
        self.assertIsNotNone(result)
        self.assertEqual(result["initial"], "zh")
        self.assertEqual(result["syllableType"], "整体认读音节")


class TestShardKey(unittest.TestCase):

    def test_xiao(self):
        self.assertEqual(bfd.shard_key("小"), "0f")

    def test_da(self):
        self.assertEqual(bfd.shard_key("大"), "07")

    def test_format_is_hex(self):
        key = bfd.shard_key("一")
        self.assertRegex(key, r"^[0-9a-f]{2}$")

    def test_all_keys_in_range(self):
        for c in "一二三四五六七八九十百千万":
            key = bfd.shard_key(c)
            self.assertLess(int(key, 16), 32)


class TestIsHanzi(unittest.TestCase):

    def test_basic_hanzi(self):
        self.assertTrue(bfd.is_hanzi("小"))

    def test_extension_a(self):
        self.assertTrue(bfd.is_hanzi("㐀"))

    def test_ascii_rejected(self):
        self.assertFalse(bfd.is_hanzi("a"))

    def test_punctuation_rejected(self):
        self.assertFalse(bfd.is_hanzi("，"))


class TestIsHanziText(unittest.TestCase):

    def test_pure_hanzi(self):
        self.assertTrue(bfd.is_hanzi_text("小学"))

    def test_mixed_rejected(self):
        self.assertFalse(bfd.is_hanzi_text("小a"))

    def test_empty_rejected(self):
        self.assertFalse(bfd.is_hanzi_text(""))


class TestIsWordCandidate(unittest.TestCase):

    def test_valid_two_char(self):
        self.assertTrue(bfd.is_word_candidate("小学"))

    def test_valid_four_char(self):
        self.assertTrue(bfd.is_word_candidate("语文老师"))

    def test_single_char_rejected(self):
        self.assertFalse(bfd.is_word_candidate("小"))

    def test_five_char_rejected(self):
        self.assertFalse(bfd.is_word_candidate("小学语文老师"))

    def test_non_hanzi_rejected(self):
        self.assertFalse(bfd.is_word_candidate("ab"))

    def test_bad_word_part_rejected(self):
        self.assertFalse(bfd.is_word_candidate("嫖娼"))

    def test_bad_word_part_in_compound(self):
        self.assertFalse(bfd.is_word_candidate("妓女"))


class TestFullBuildPipeline(unittest.TestCase):
    """Run the actual build pipeline in a temp directory and verify
    the generated output with exact expected values."""

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp()
        cls.output_dir = os.path.join(cls.tmp_dir, "data", "generated")
        cls.chars_dir = os.path.join(cls.output_dir, "chars")
        vendor_src = os.path.join(PROJECT_ROOT, "data", "vendor", "chinese-xinhua")
        seed_src = os.path.join(PROJECT_ROOT, "data", "seed-characters.json")

        tmp_vendor = os.path.join(cls.tmp_dir, "data", "vendor", "chinese-xinhua")
        os.makedirs(tmp_vendor, exist_ok=True)
        os.makedirs(cls.chars_dir, exist_ok=True)
        shutil.copy2(os.path.join(vendor_src, "word.json"), tmp_vendor)
        shutil.copy2(os.path.join(vendor_src, "ci.json"), tmp_vendor)
        shutil.copy2(seed_src, os.path.join(cls.tmp_dir, "data", "seed-characters.json"))

        # Patch module-level path constants to temp directory
        tmp_root = bfd.Path(cls.tmp_dir)
        cls._originals = {
            "ROOT": bfd.ROOT,
            "VENDOR_DIR": bfd.VENDOR_DIR,
            "GENERATED_DIR": bfd.GENERATED_DIR,
            "SHARD_DIR": bfd.SHARD_DIR,
            "MANIFEST": bfd.MANIFEST,
            "SEED_DATA": bfd.SEED_DATA,
        }
        bfd.ROOT = tmp_root
        bfd.VENDOR_DIR = tmp_root / "data" / "vendor" / "chinese-xinhua"
        bfd.GENERATED_DIR = tmp_root / "data" / "generated"
        bfd.SHARD_DIR = tmp_root / "data" / "generated" / "chars"
        bfd.MANIFEST = tmp_root / "data" / "generated" / "manifest.json"
        bfd.SEED_DATA = tmp_root / "data" / "seed-characters.json"

        try:
            bfd.main()
            cls.build_ok = True
        except Exception as e:
            cls.build_error = str(e)
            cls.build_ok = False

    @classmethod
    def tearDownClass(cls):
        for key, val in cls._originals.items():
            setattr(bfd, key, val)
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def _load_shard(self, char):
        """Load a character's shard file and return its data."""
        key = bfd.shard_key(char)
        path = os.path.join(self.chars_dir, f"{key}.json")
        with open(path) as f:
            return json.load(f), key

    def test_build_succeeded(self):
        self.assertTrue(self.__class__.build_ok,
            f"Build pipeline should succeed. Error: {getattr(self.__class__, 'build_error', 'unknown')}")

    def test_manifest_created(self):
        manifest_path = os.path.join(self.output_dir, "manifest.json")
        self.assertTrue(os.path.isfile(manifest_path))
        with open(manifest_path) as f:
            manifest = json.load(f)
        self.assertEqual(manifest["buckets"], 32)
        self.assertEqual(len(manifest["counts"]), 32)

    def test_32_shard_files_created(self):
        for i in range(32):
            path = os.path.join(self.chars_dir, f"{i:02x}.json")
            self.assertTrue(os.path.isfile(path), f"Missing shard {i:02x}.json")

    def test_shard_char_count_matches_manifest(self):
        manifest_path = os.path.join(self.output_dir, "manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        for key, expected_count in manifest["counts"].items():
            path = os.path.join(self.chars_dir, f"{key}.json")
            with open(path) as f:
                data = json.load(f)
            actual = len(data["characters"])
            self.assertEqual(actual, expected_count,
                f"Shard {key}: manifest={expected_count}, actual={actual}")

    def test_all_characters_in_correct_shard(self):
        for i in range(32):
            path = os.path.join(self.chars_dir, f"{i:02x}.json")
            with open(path) as f:
                data = json.load(f)
            for char in data["characters"]:
                expected = bfd.shard_key(char)
                self.assertEqual(expected, f"{i:02x}",
                    f"'{char}' should be in shard {expected}, not {i:02x}")

    # -- Exact pinyin/field verification for seed characters --

    def test_xiao_exact_fields(self):
        """'小' is a seed character — verify exact merged field values."""
        data, key = self._load_shard("小")
        self.assertEqual(key, "0f")
        self.assertIn("小", data["characters"], "'小' must exist in shard data")
        cd = data["characters"]["小"]
        # Seed override values
        self.assertEqual(cd["pinyin"], "xiǎo", "'小' pinyin must be 'xiǎo'")
        self.assertEqual(cd["tone"], "ˇ", "'小' tone must be 'ˇ'")
        self.assertEqual(cd["initial"], "x", "'小' initial must be 'x'")
        self.assertEqual(cd["final"], "iǎo", "'小' final must be 'iǎo'")
        self.assertEqual(cd["radical"], "小", "'小' radical must be '小'")
        self.assertIn("structure", cd, "'小' must have 'structure' from seed merge")
        self.assertEqual(cd["structure"], "独体字", "'小' structure must be '独体字'")

    def test_xue_exact_fields(self):
        """'学' is a seed character — verify exact fields."""
        data, _ = self._load_shard("学")
        self.assertIn("学", data["characters"])
        cd = data["characters"]["学"]
        self.assertEqual(cd["pinyin"], "xué", "'学' pinyin must be 'xué'")
        self.assertEqual(cd["tone"], "ˊ", "'学' tone must be 'ˊ'")
        self.assertEqual(cd["initial"], "x", "'学' initial must be 'x'")
        self.assertEqual(cd["final"], "ué", "'学' final must be 'ué'")
        self.assertEqual(cd["radical"], "子", "'学' radical must be '子'")
        self.assertEqual(cd["structure"], "上下结构", "'学' structure must be '上下结构'")

    # -- Exact pinyin verification for non-seed characters (shard-computed) --

    def test_tian_exact_pinyin(self):
        """'天' is NOT a seed character — verify shard-computed pinyin."""
        data, _ = self._load_shard("天")
        self.assertIn("天", data["characters"], "'天' must exist in shard data")
        cd = data["characters"]["天"]
        self.assertEqual(cd["initial"], "t", "'天' initial must be 't'")
        self.assertEqual(cd["final"], "iān", "'天' final must be 'iān'")
        self.assertEqual(cd["syllableType"], "三拼音节", "'天' syllableType must be '三拼音节'")

    def test_di_exact_pinyin(self):
        """'地' is NOT a seed character — verify shard-computed pinyin."""
        data, _ = self._load_shard("地")
        self.assertIn("地", data["characters"])
        cd = data["characters"]["地"]
        self.assertEqual(cd["initial"], "d", "'地' initial must be 'd'")
        self.assertEqual(cd["final"], "ì", "'地' final must be 'ì'")
        self.assertEqual(cd["syllableType"], "两拼音节", "'地' syllableType must be '两拼音节'")

    # -- Common words exact verification --

    def test_xiao_common_words_exact(self):
        """'小' commonWords must include specific expected words from COMMON_HINTS."""
        data, _ = self._load_shard("小")
        self.assertIn("小", data.get("commonWords", {}), "'小' must have commonWords")
        words = data["commonWords"]["小"]
        self.assertGreater(len(words), 0, "'小' must have at least 1 common word")
        # '小学' and '大小' are in COMMON_HINTS and should appear
        self.assertIn("小学", words, "'小' commonWords must include '小学'")
        self.assertIn("大小", words, "'小' commonWords must include '大小'")
        for w in words:
            self.assertTrue(2 <= len(w) <= 4, f"Word '{w}' must be 2-4 chars")
            self.assertTrue(bfd.is_hanzi_text(w), f"Word '{w}' must be all hanzi")

    def test_da_common_words_exact(self):
        """'大' commonWords must include '大小' (from COMMON_HINTS with high priority)."""
        data, _ = self._load_shard("大")
        self.assertIn("大", data.get("commonWords", {}))
        words = data["commonWords"]["大"]
        # '大小' is in COMMON_HINTS and should appear with high priority
        self.assertIn("大小", words, "'大' commonWords must include '大小'")
        # Verify all words are valid
        for w in words:
            self.assertTrue(2 <= len(w) <= 4, f"Word '{w}' must be 2-4 chars")
            self.assertTrue(bfd.is_hanzi_text(w), f"Word '{w}' must be all hanzi")

    # -- Bad words filter verification --

    def test_no_bad_words_in_any_shard(self):
        """Scanning ALL 32 shards: no commonWord may contain BAD_WORD_PARTS."""
        found_bad = []
        for i in range(32):
            path = os.path.join(self.chars_dir, f"{i:02x}.json")
            with open(path) as f:
                data = json.load(f)
            for char, words in data.get("commonWords", {}).items():
                for w in words:
                    for part in bfd.BAD_WORD_PARTS:
                        if part in w:
                            found_bad.append(f"char='{char}' word='{w}' bad_part='{part}'")
        self.assertEqual(found_bad, [],
            f"Found {len(found_bad)} bad words in commonWords: {found_bad[:5]}")

    # -- Total character count exact range --

    def test_total_character_count_14809(self):
        """Must generate exactly 14809 characters (known from actual data)."""
        total = 0
        for i in range(32):
            path = os.path.join(self.chars_dir, f"{i:02x}.json")
            with open(path) as f:
                data = json.load(f)
            total += len(data["characters"])
        self.assertEqual(total, 14809,
            f"Expected exactly 14809 characters, got {total}")

    # -- Seed merge verification --

    def test_seed_overrides_structure(self):
        """Seed characters must have 'structure' field after merge
        (raw shard data does not have structure)."""
        seed_path = os.path.join(PROJECT_ROOT, "data", "seed-characters.json")
        with open(seed_path) as f:
            seeds = json.load(f)
        self.assertTrue(len(seeds) > 0, "seed-characters.json should not be empty")

        # Check a known seed character
        first_char = seeds[0]["character"]
        data, _ = self._load_shard(first_char)
        self.assertIn(first_char, data["characters"])
        cd = data["characters"][first_char]
        self.assertIn("structure", cd,
            f"Seed char '{first_char}' must have 'structure' field after merge")
        # Structure value must be a known type, not empty
        self.assertTrue(len(cd["structure"]) > 0,
            f"Seed char '{first_char}' structure must not be empty")

    def test_seed_overrides_strokes(self):
        """Seed characters must have 'strokes' field (only seed data has this)."""
        seed_path = os.path.join(PROJECT_ROOT, "data", "seed-characters.json")
        with open(seed_path) as f:
            seeds = json.load(f)
        first_char = seeds[0]["character"]
        data, _ = self._load_shard(first_char)
        cd = data["characters"][first_char]
        self.assertIn("strokes", cd,
            f"Seed char '{first_char}' must have 'strokes' field after merge")


if __name__ == "__main__":
    unittest.main()
