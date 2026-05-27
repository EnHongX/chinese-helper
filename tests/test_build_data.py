#!/usr/bin/env python3
"""Tests for scripts/build_fallback_data.py — pure functions + full pipeline run in temp dir."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_fallback_data as bfd


# ── Synthetic test data ──
# Small but complete: characters with known pinyin/radical/strokes,
# words (ci) that exercise filtering, scoring, and sharding.

WORD_JSON = [
    {"word": "大", "pinyin": "dà",  "radicals": "大", "strokes": "3",
     "explanation": "1. 指面积、体积等超过一般。大人大话。"},
    {"word": "小", "pinyin": "xiǎo", "radicals": "小", "strokes": "3",
     "explanation": "指面积、体积等不大。小事小心。"},
    {"word": "学", "pinyin": "xué", "radicals": "子", "strokes": "8",
     "explanation": "效法；学习。学而时习之。"},
    {"word": "习", "pinyin": "xí",  "radicals": "乙", "strokes": "3",
     "explanation": "反复练习。温故而知新。"},
    {"word": "花", "pinyin": "huā", "radicals": "艹", "strokes": "7",
     "explanation": "植物的繁殖器官。花朵花园。"},
    {"word": "好", "pinyin": "hǎo", "radicals": "女", "strokes": "6",
     "explanation": "优点多；使人满意。好人好事。"},
    {"word": "中", "pinyin": "zhōng", "radicals": "丨", "strokes": "4",
     "explanation": "跟四周的距离相等。中心中间。"},
    {"word": "国", "pinyin": "guó",  "radicals": "囗", "strokes": "8",
     "explanation": "有土地、人民的政治组织。国家。"},
    # Non-hanzi entry — should be skipped
    {"word": "A",  "pinyin": "A", "radicals": "", "strokes": "0",
     "explanation": "not a character"},
    # Multi-char entry — should be skipped
    {"word": "你好", "pinyin": "nǐhǎo", "radicals": "", "strokes": "",
     "explanation": "greeting"},
]

CI_JSON = [
    {"ci": "大人",   "explanation": "成年人。"},
    {"ci": "大小",   "explanation": "大和小。"},
    {"ci": "大家",   "explanation": "所有的人。"},
    {"ci": "大学",   "explanation": "高等学府。"},
    {"ci": "大学生", "explanation": "在大学上学的学生。"},
    {"ci": "小学",   "explanation": "初等教育学校。"},
    {"ci": "小心",   "explanation": "注意避免出错。"},
    {"ci": "学习",   "explanation": "获取知识。"},
    {"ci": "学校",   "explanation": "教育的场所。"},
    {"ci": "学生",   "explanation": "在学校学习的人。"},
    {"ci": "花园",   "explanation": "种花的园子。"},
    {"ci": "花朵",   "explanation": "花的总称。"},
    {"ci": "鲜花",   "explanation": "新鲜的花。"},
    {"ci": "好人",   "explanation": "品行好的人。"},
    {"ci": "好看",   "explanation": "美观。"},
    {"ci": "中国",   "explanation": "中华人民共和国。"},
    {"ci": "中心",   "explanation": "事物的主要部分。"},
    {"ci": "国家",   "explanation": "拥有主权的政治实体。"},
    # Bad word — should be filtered
    {"ci": "赌博",   "explanation": "用财物作赌注来比输赢。"},
    # Non-hanzi — should be filtered
    {"ci": "hello",  "explanation": "not Chinese"},
    # Single char — should be filtered (too short)
    {"ci": "大",     "explanation": "big"},
    # 5-char — should be filtered (too long)
    {"ci": "大大小小的", "explanation": "various sizes"},
]

SEED_JSON = [
    {"character": "大", "structure": "独体字",
     "words": ["大人", "大小"], "antonyms": ["小"], "synonyms": ["巨"],
     "polyphonic": [{"pinyin": "dài", "explanation": "大夫"}]},
    {"character": "小", "structure": "独体字",
     "words": ["小学", "小心"], "antonyms": ["大"], "synonyms": ["微"]},
]


# ═══════════════════════════════════════════════════════
# 1. parse_pinyin
# ═══════════════════════════════════════════════════════

class TestParsePinyin(unittest.TestCase):
    def test_tone_mark_pinyin(self):
        r = bfd.parse_pinyin("hǎo")
        self.assertIsNotNone(r)
        self.assertEqual(r["tone"], "ˇ")
        self.assertEqual(r["initial"], "h")

    def test_digit_tone_pinyin(self):
        r = bfd.parse_pinyin("hao3")
        self.assertIsNotNone(r)
        self.assertEqual(r["tone"], "ˇ")

    def test_no_tone(self):
        r = bfd.parse_pinyin("de")
        self.assertIsNotNone(r)
        self.assertEqual(r["tone"], "")

    def test_empty_and_none(self):
        self.assertIsNone(bfd.parse_pinyin(""))
        self.assertIsNone(bfd.parse_pinyin(None))

    def test_invalid_chars(self):
        self.assertIsNone(bfd.parse_pinyin("he!!o"))
        self.assertIsNone(bfd.parse_pinyin("123"))

    def test_whole_reading_syllable(self):
        r = bfd.parse_pinyin("zhī")
        self.assertEqual(r["syllableType"], "整体认读音节")

    def test_zero_initial(self):
        r = bfd.parse_pinyin("ā")
        self.assertEqual(r["initial"], "（自成音节）")
        self.assertEqual(r["syllableType"], "零声母音节")

    def test_three_part_syllable(self):
        r = bfd.parse_pinyin("guān")
        self.assertEqual(r["syllableType"], "三拼音节")
        self.assertEqual(r["initial"], "g")

    def test_two_part_syllable(self):
        r = bfd.parse_pinyin("bā")
        self.assertEqual(r["syllableType"], "两拼音节")
        self.assertEqual(r["initial"], "b")

    def test_all_four_tones(self):
        for raw, expected in [("mā", "ˉ"), ("má", "ˊ"), ("mǎ", "ˇ"), ("mà", "ˋ")]:
            with self.subTest(raw=raw):
                self.assertEqual(bfd.parse_pinyin(raw)["tone"], expected)

    def test_u_umlaut(self):
        r = bfd.parse_pinyin("lǚ")
        self.assertIsNotNone(r)
        self.assertEqual(r["initial"], "l")

    def test_long_initials(self):
        for py in ["zhāng", "chī", "shān"]:
            with self.subTest(py=py):
                r = bfd.parse_pinyin(py)
                self.assertIn(r["initial"], ["zh", "ch", "sh"])

    def test_normalize_special_g(self):
        self.assertEqual(bfd.normalize_pinyin("ɡuān"), "guān")


# ═══════════════════════════════════════════════════════
# 2. shard_key
# ═══════════════════════════════════════════════════════

class TestShardKey(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(bfd.shard_key("学"), bfd.shard_key("学"))

    def test_format(self):
        key = bfd.shard_key("中")
        self.assertRegex(key, r"^[0-9a-f]{2}$")

    def test_value(self):
        self.assertEqual(bfd.shard_key("中"), f"{ord('中') % 32:02x}")

    def test_different_chars_can_differ(self):
        keys = {bfd.shard_key(c) for c in "你好学习语文"}
        self.assertGreater(len(keys), 1)


# ═══════════════════════════════════════════════════════
# 3. is_hanzi / is_hanzi_text / is_word_candidate
# ═══════════════════════════════════════════════════════

class TestHanziFilters(unittest.TestCase):
    def test_is_hanzi(self):
        self.assertTrue(bfd.is_hanzi("你"))
        self.assertFalse(bfd.is_hanzi("a"))

    def test_is_hanzi_text(self):
        self.assertTrue(bfd.is_hanzi_text("你好"))
        self.assertFalse(bfd.is_hanzi_text(""))
        self.assertFalse(bfd.is_hanzi_text("hi你"))

    def test_word_candidate_length(self):
        self.assertTrue(bfd.is_word_candidate("学习"))
        self.assertTrue(bfd.is_word_candidate("好朋友"))
        self.assertTrue(bfd.is_word_candidate("好好学习"))
        self.assertFalse(bfd.is_word_candidate("你"))
        self.assertFalse(bfd.is_word_candidate("你好世界真大"))

    def test_word_candidate_bad_words(self):
        self.assertFalse(bfd.is_word_candidate("赌博"))
        self.assertFalse(bfd.is_word_candidate("凶手"))

    def test_word_candidate_non_hanzi(self):
        self.assertFalse(bfd.is_word_candidate("hi"))
        self.assertFalse(bfd.is_word_candidate("你a"))


# ═══════════════════════════════════════════════════════
# 4. word_score
# ═══════════════════════════════════════════════════════

class TestWordScore(unittest.TestCase):
    def test_common_hint_ranked_first(self):
        common = bfd.word_score("学习", "学")
        normal = bfd.word_score("学问", "学")
        self.assertLess(common[0], normal[0])

    def test_starts_with_char_preferred(self):
        starts = bfd.word_score("花园", "花")
        doesnt = bfd.word_score("鲜花", "花")
        self.assertLess(starts[0], doesnt[0])

    def test_shorter_preferred(self):
        two = bfd.word_score("大人", "大")
        three = bfd.word_score("大学生", "大")
        self.assertLess(two[0], three[0])


# ═══════════════════════════════════════════════════════
# 5. short_explanation
# ═══════════════════════════════════════════════════════

class TestShortExplanation(unittest.TestCase):
    def test_truncates_at_sentence_end(self):
        text = "表示大的意思。还可以表示其他含义，比如广阔的。"
        result = bfd.short_explanation(text)
        self.assertTrue(result.endswith("。"))
        self.assertLessEqual(len(result), 90)

    def test_strips_numbering(self):
        text = "1. 表示大的意思"
        result = bfd.short_explanation(text)
        self.assertFalse(result.startswith("1"))

    def test_empty(self):
        self.assertEqual(bfd.short_explanation(""), "")
        self.assertEqual(bfd.short_explanation(None), "")

    def test_long_text_truncated(self):
        text = "这" * 200
        result = bfd.short_explanation(text)
        self.assertLessEqual(len(result), 90)


# ═══════════════════════════════════════════════════════
# 6. build_common_words
# ═══════════════════════════════════════════════════════

class TestBuildCommonWords(unittest.TestCase):
    def test_groups_by_character(self):
        items = [{"ci": "学习"}, {"ci": "学校"}, {"ci": "复习"}]
        result = bfd.build_common_words(items)
        self.assertIn("学", result)
        self.assertIn("学习", result["学"])
        self.assertIn("学校", result["学"])
        self.assertIn("习", result)

    def test_filters_bad_words(self):
        items = [{"ci": "赌博"}, {"ci": "学习"}]
        result = bfd.build_common_words(items)
        for words in result.values():
            self.assertNotIn("赌博", words)

    def test_max_12_words(self):
        items = [{"ci": f"学{chr(0x4e00 + i)}"} for i in range(20)]
        result = bfd.build_common_words(items)
        self.assertLessEqual(len(result.get("学", [])), 12)


# ═══════════════════════════════════════════════════════
# 7. Full pipeline run in temp directory
# ═══════════════════════════════════════════════════════

class TestFullPipeline(unittest.TestCase):
    """Run the entire build pipeline with synthetic data in a temp dir,
    then verify every aspect of the output."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="bfd_test_"))

        vendor = cls.tmpdir / "data" / "vendor" / "chinese-xinhua"
        vendor.mkdir(parents=True)
        (vendor / "word.json").write_text(
            json.dumps(WORD_JSON, ensure_ascii=False), encoding="utf-8")
        (vendor / "ci.json").write_text(
            json.dumps(CI_JSON, ensure_ascii=False), encoding="utf-8")

        seed_path = cls.tmpdir / "data" / "seed-characters.json"
        seed_path.write_text(
            json.dumps(SEED_JSON, ensure_ascii=False), encoding="utf-8")

        cls.generated = cls.tmpdir / "data" / "generated"
        cls.shard_dir = cls.generated / "chars"
        cls.manifest_path = cls.generated / "manifest.json"

        # Patch module-level paths and run the pipeline
        orig_vendor = bfd.VENDOR_DIR
        orig_gen = bfd.GENERATED_DIR
        orig_shard = bfd.SHARD_DIR
        orig_manifest = bfd.MANIFEST
        orig_seed = bfd.SEED_DATA

        bfd.VENDOR_DIR = vendor
        bfd.GENERATED_DIR = cls.generated
        bfd.SHARD_DIR = cls.shard_dir
        bfd.MANIFEST = cls.manifest_path
        bfd.SEED_DATA = seed_path

        try:
            bfd.main()
        finally:
            bfd.VENDOR_DIR = orig_vendor
            bfd.GENERATED_DIR = orig_gen
            bfd.SHARD_DIR = orig_shard
            bfd.MANIFEST = orig_manifest
            bfd.SEED_DATA = orig_seed

        # Load all outputs once
        cls.manifest = json.loads(cls.manifest_path.read_text("utf-8"))
        cls.shards = {}
        for f in cls.shard_dir.glob("*.json"):
            cls.shards[f.stem] = json.loads(f.read_text("utf-8"))
        # Flatten for easy lookup
        cls.all_chars = {}
        cls.all_words = {}
        for data in cls.shards.values():
            cls.all_chars.update(data.get("characters", {}))
            cls.all_words.update(data.get("commonWords", {}))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    # ── manifest ──

    def test_manifest_buckets(self):
        self.assertEqual(self.manifest["buckets"], 32)

    def test_manifest_source(self):
        self.assertEqual(self.manifest["source"], "pwxcoo/chinese-xinhua")

    def test_manifest_counts_match_shard_files(self):
        for key, count in self.manifest["counts"].items():
            self.assertIn(key, self.shards, f"shard file {key}.json missing")
            actual = len(self.shards[key]["characters"])
            self.assertEqual(actual, count,
                             f"shard {key}: manifest says {count}, file has {actual}")

    def test_no_extra_shard_files(self):
        self.assertEqual(set(self.shards.keys()), set(self.manifest["counts"].keys()))

    # ── character records: every valid input char present ──

    def test_valid_chars_all_present(self):
        expected = {"大", "小", "学", "习", "花", "好", "中", "国"}
        self.assertEqual(set(self.all_chars.keys()), expected)

    def test_non_hanzi_excluded(self):
        self.assertNotIn("A", self.all_chars)

    def test_multi_char_entry_excluded(self):
        self.assertNotIn("你好", self.all_chars)

    # ── pinyin correctness for every character ──

    def test_pinyin_da(self):
        self.assertEqual(self.all_chars["大"]["pinyin"], "dà")
        self.assertEqual(self.all_chars["大"]["tone"], "ˋ")
        self.assertEqual(self.all_chars["大"]["initial"], "d")
        self.assertEqual(self.all_chars["大"]["syllableType"], "两拼音节")

    def test_pinyin_xiao(self):
        self.assertEqual(self.all_chars["小"]["pinyin"], "xiǎo")
        self.assertEqual(self.all_chars["小"]["tone"], "ˇ")
        self.assertEqual(self.all_chars["小"]["initial"], "x")

    def test_pinyin_xue(self):
        self.assertEqual(self.all_chars["学"]["pinyin"], "xué")
        self.assertEqual(self.all_chars["学"]["tone"], "ˊ")
        self.assertEqual(self.all_chars["学"]["initial"], "x")

    def test_pinyin_xi(self):
        self.assertEqual(self.all_chars["习"]["pinyin"], "xí")
        self.assertEqual(self.all_chars["习"]["tone"], "ˊ")

    def test_pinyin_hua(self):
        self.assertEqual(self.all_chars["花"]["pinyin"], "huā")
        self.assertEqual(self.all_chars["花"]["tone"], "ˉ")
        self.assertEqual(self.all_chars["花"]["initial"], "h")
        self.assertEqual(self.all_chars["花"]["syllableType"], "三拼音节")

    def test_pinyin_hao(self):
        self.assertEqual(self.all_chars["好"]["pinyin"], "hǎo")
        self.assertEqual(self.all_chars["好"]["tone"], "ˇ")

    def test_pinyin_zhong(self):
        self.assertEqual(self.all_chars["中"]["pinyin"], "zhōng")
        self.assertEqual(self.all_chars["中"]["tone"], "ˉ")
        self.assertEqual(self.all_chars["中"]["initial"], "zh")
        self.assertEqual(self.all_chars["中"]["final"], "ōng")
        self.assertEqual(self.all_chars["中"]["syllableType"], "两拼音节")

    def test_pinyin_guo(self):
        r = self.all_chars["国"]
        self.assertEqual(r["pinyin"], "guó")
        self.assertEqual(r["tone"], "ˊ")
        self.assertEqual(r["initial"], "g")
        self.assertEqual(r["syllableType"], "三拼音节")

    # ── radical and strokeCount ──

    def test_radical_and_strokes(self):
        for char, expected_r, expected_s in [
            ("大", "大", "3"), ("学", "子", "8"), ("花", "艹", "7"),
            ("中", "丨", "4"), ("国", "囗", "8"),
        ]:
            with self.subTest(char=char):
                self.assertEqual(self.all_chars[char]["radical"], expected_r)
                self.assertEqual(self.all_chars[char]["strokeCount"], expected_s)

    # ── meaning (short_explanation applied) ──

    def test_meaning_truncated(self):
        for char in self.all_chars:
            m = self.all_chars[char].get("meaning", "")
            self.assertLessEqual(len(m), 90, f"{char} meaning too long")

    def test_meaning_numbering_stripped(self):
        m = self.all_chars["大"]["meaning"]
        self.assertFalse(m.startswith("1"))

    # ── seed merge ──

    def test_seed_fields_merged(self):
        self.assertEqual(self.all_chars["大"]["structure"], "独体字")
        self.assertEqual(self.all_chars["大"]["antonyms"], ["小"])
        self.assertEqual(self.all_chars["大"]["synonyms"], ["巨"])
        self.assertIn({"pinyin": "dài", "explanation": "大夫"},
                      self.all_chars["大"]["polyphonic"])

    def test_seed_overrides_words(self):
        self.assertEqual(self.all_chars["小"]["words"], ["小学", "小心"])

    def test_seed_preserves_base_fields(self):
        self.assertIn("pinyin", self.all_chars["大"])
        self.assertIn("radical", self.all_chars["大"])

    # ── common words (ci) ──

    def test_words_for_da(self):
        words = self.all_words["大"]
        self.assertIn("大人", words)
        self.assertIn("大小", words)
        self.assertIn("大家", words)
        self.assertIn("大学", words)
        self.assertIn("大学生", words)

    def test_words_for_xue(self):
        words = self.all_words["学"]
        self.assertIn("学习", words)
        self.assertIn("学校", words)
        self.assertIn("学生", words)
        self.assertIn("大学", words)

    def test_words_for_hua(self):
        words = self.all_words["花"]
        self.assertIn("花园", words)
        self.assertIn("花朵", words)
        self.assertIn("鲜花", words)

    def test_words_for_zhong_guo(self):
        self.assertIn("中国", self.all_words["中"])
        self.assertIn("中心", self.all_words["中"])
        self.assertIn("中国", self.all_words["国"])
        self.assertIn("国家", self.all_words["国"])

    def test_bad_word_excluded(self):
        for words in self.all_words.values():
            self.assertNotIn("赌博", words)

    def test_non_hanzi_ci_excluded(self):
        for words in self.all_words.values():
            self.assertNotIn("hello", words)

    def test_single_char_ci_excluded(self):
        for words in self.all_words.values():
            for w in words:
                self.assertGreaterEqual(len(w), 2)

    def test_too_long_ci_excluded(self):
        for words in self.all_words.values():
            for w in words:
                self.assertLessEqual(len(w), 4)

    def test_word_ordering(self):
        words = self.all_words["大"]
        # COMMON_HINTS entries (大小, 大家) should appear before non-hints
        hint_indices = [i for i, w in enumerate(words) if w in bfd.COMMON_HINTS]
        non_hint_indices = [i for i, w in enumerate(words) if w not in bfd.COMMON_HINTS]
        if hint_indices and non_hint_indices:
            self.assertLess(max(hint_indices), max(non_hint_indices))

    # ── sharding correctness ──

    def test_every_char_in_correct_shard(self):
        for key, data in self.shards.items():
            for char in data["characters"]:
                self.assertEqual(bfd.shard_key(char), key,
                                 f"char '{char}' in shard {key} but shard_key() says {bfd.shard_key(char)}")
            for char in data["commonWords"]:
                self.assertEqual(bfd.shard_key(char), key,
                                 f"word key '{char}' in shard {key} but shard_key() says {bfd.shard_key(char)}")

    def test_shard_structure(self):
        for key, data in self.shards.items():
            self.assertIn("characters", data)
            self.assertIn("commonWords", data)

    def test_all_words_reference_valid_hanzi(self):
        for char, words in self.all_words.items():
            self.assertTrue(bfd.is_hanzi(char), f"word key '{char}' is not hanzi")
            for w in words:
                self.assertTrue(bfd.is_hanzi_text(w), f"word '{w}' for '{char}' has non-hanzi")


if __name__ == "__main__":
    unittest.main()
