#!/usr/bin/env python3
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "data" / "vendor" / "chinese-xinhua"
GENERATED_DIR = ROOT / "data" / "generated"
SHARD_DIR = GENERATED_DIR / "chars"
MANIFEST = GENERATED_DIR / "manifest.json"
SEED_DATA = ROOT / "data" / "seed-characters.json"

SHARD_BUCKETS = 32

COMMON_HINTS = {
    "游戏", "看戏", "唱戏", "戏曲", "戏台", "戏剧", "演戏", "马戏", "大戏",
    "学习", "学校", "学生", "同学", "小学", "大小", "大家", "大人", "大山", "长大",
}

BAD_WORD_PARTS = {
    "嫖", "妓", "娼", "赌", "毒", "尸", "屎", "尿",
    "淫", "奸", "杀", "凶", "狱", "刑", "殡", "丧",
}

TONE_MARKS = {
    "ā": ("a", 1), "á": ("a", 2), "ǎ": ("a", 3), "à": ("a", 4),
    "ē": ("e", 1), "é": ("e", 2), "ě": ("e", 3), "è": ("e", 4),
    "ī": ("i", 1), "í": ("i", 2), "ǐ": ("i", 3), "ì": ("i", 4),
    "ō": ("o", 1), "ó": ("o", 2), "ǒ": ("o", 3), "ò": ("o", 4),
    "ū": ("u", 1), "ú": ("u", 2), "ǔ": ("u", 3), "ù": ("u", 4),
    "ǖ": ("ü", 1), "ǘ": ("ü", 2), "ǚ": ("ü", 3), "ǜ": ("ü", 4),
}

TONE_SYMBOLS = {0: "", 1: "ˉ", 2: "ˊ", 3: "ˇ", 4: "ˋ"}

INITIALS_LONG = ("zh", "ch", "sh")
INITIALS_SHORT = (
    "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h",
    "j", "q", "x", "r", "z", "c", "s", "y", "w",
)

WHOLE_READING_SYLLABLES = {
    "zhi", "chi", "shi", "ri",
    "zi", "ci", "si",
    "yi", "wu", "yu",
    "ye", "yue", "yuan",
    "yin", "yun", "ying",
}

PINYIN_LETTERS = set("abcdefghijklmnopqrstuvwxyzü")

DIGIT_TONE_RE = re.compile(r"^([a-zü]+)([0-5])$")


def normalize_pinyin(raw):
    return raw.replace("ɡ", "g").strip()


def parse_pinyin(raw):
    """Return {pinyin, tone, initial, final, syllableType} or None if unparseable."""
    if not raw:
        return None
    p = normalize_pinyin(raw)
    if not p:
        return None

    digit_match = DIGIT_TONE_RE.match(p)
    if digit_match:
        plain = digit_match.group(1)
        tone_num = int(digit_match.group(2))
        return classify_syllable(plain, tone_num, plain)

    tone = 0
    plain_chars = []
    for ch in p:
        if ch in TONE_MARKS:
            base, t = TONE_MARKS[ch]
            tone = t
            plain_chars.append(base)
        elif ch.lower() in PINYIN_LETTERS:
            plain_chars.append(ch.lower())
        else:
            return None
    plain = "".join(plain_chars)
    if not plain:
        return None
    return classify_syllable(plain, tone, p)


def classify_syllable(plain, tone_num, display):
    initial = ""
    for cand in INITIALS_LONG:
        if plain.startswith(cand):
            initial = cand
            break
    if not initial:
        for cand in INITIALS_SHORT:
            if plain.startswith(cand):
                initial = cand
                break

    plain_final = plain[len(initial):]
    final_display = display[len(initial):] if initial else display

    if plain in WHOLE_READING_SYLLABLES:
        syllable_type = "整体认读音节"
    elif not initial:
        syllable_type = "零声母音节"
    elif plain_final and plain_final[0] in "iuü" and len(plain_final) >= 2:
        syllable_type = "三拼音节"
    else:
        syllable_type = "两拼音节"

    return {
        "pinyin": display,
        "tone": TONE_SYMBOLS.get(tone_num, ""),
        "initial": initial or "（自成音节）",
        "final": final_display,
        "syllableType": syllable_type,
    }


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def is_hanzi_text(value):
    return bool(value) and all(is_hanzi(char) for char in value)


def is_hanzi(char):
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0x2CEB0 <= code <= 0x2EBEF
        or 0x30000 <= code <= 0x3134F
        or 0x31350 <= code <= 0x323AF
    )


def is_word_candidate(value):
    if not is_hanzi_text(value):
        return False
    if not 2 <= len(value) <= 4:
        return False
    return not any(part in value for part in BAD_WORD_PARTS)


def word_score(value, char):
    score = 0
    if value in COMMON_HINTS:
        score -= 100
    if value.startswith(char):
        score -= 10
    if len(value) == 2:
        score -= 6
    elif len(value) == 3:
        score -= 3
    score += len(value)
    return (score, value)


def short_explanation(text):
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"^[\d一二三四五六七八九十]+[.、]\s*", "", cleaned)
    sentence_end = re.search(r"[。；]", cleaned[:120])
    if sentence_end and sentence_end.end() <= 90:
        return cleaned[: sentence_end.end()]
    return cleaned[:90]


def build_characters(words):
    characters = {}
    for item in words:
        char = item.get("word", "")
        if len(char) != 1 or not is_hanzi_text(char):
            continue
        raw_pinyin = item.get("pinyin", "")
        parsed = parse_pinyin(raw_pinyin)
        record = {
            "pinyin": parsed["pinyin"] if parsed else normalize_pinyin(raw_pinyin),
            "radical": item.get("radicals", ""),
            "strokeCount": item.get("strokes", ""),
            "meaning": short_explanation(item.get("explanation", "")),
        }
        if parsed:
            record["tone"] = parsed["tone"]
            record["initial"] = parsed["initial"]
            record["final"] = parsed["final"]
            record["syllableType"] = parsed["syllableType"]
        characters[char] = record
    return characters


def merge_seed_characters(characters):
    if not SEED_DATA.exists():
        return 0

    seeds = load_json(SEED_DATA)
    count = 0
    for record in seeds:
        char = record.get("character", "")
        if len(char) != 1 or not is_hanzi(char):
            continue
        existing = characters.get(char, {})
        characters[char] = {
            **existing,
            **record,
        }
        count += 1
    return count


def build_common_words(ci_items):
    buckets = {}
    for item in ci_items:
        word = item.get("ci", "").strip()
        if not is_word_candidate(word):
            continue
        for char in set(word):
            buckets.setdefault(char, set()).add(word)

    result = {}
    for char, words in buckets.items():
        result[char] = sorted(words, key=lambda value: word_score(value, char))[:12]
    return result


def shard_key(char):
    return f"{ord(char) % SHARD_BUCKETS:02x}"


def write_shards(characters, common_words):
    if SHARD_DIR.exists():
        for old in SHARD_DIR.glob("*.json"):
            old.unlink()
    SHARD_DIR.mkdir(parents=True, exist_ok=True)

    shards = {}
    all_chars = set(characters) | set(common_words)
    for char in all_chars:
        key = shard_key(char)
        bucket = shards.setdefault(key, {"characters": {}, "commonWords": {}})
        if char in characters:
            bucket["characters"][char] = characters[char]
        if char in common_words:
            bucket["commonWords"][char] = common_words[char]

    counts = {}
    for key, data in shards.items():
        path = SHARD_DIR / f"{key}.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        counts[key] = len(data["characters"])

    return counts


def main():
    word_path = VENDOR_DIR / "word.json"
    ci_path = VENDOR_DIR / "ci.json"

    missing = [path for path in [word_path, ci_path] if not path.exists()]
    if missing:
        missing_text = "\n".join(str(path) for path in missing)
        raise SystemExit(
            f"缺少 chinese-xinhua 数据，请先运行 scripts/download_chinese_xinhua.py:\n{missing_text}"
        )

    characters = build_characters(load_json(word_path))
    seed_count = merge_seed_characters(characters)
    common_words = build_common_words(load_json(ci_path))

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    counts = write_shards(characters, common_words)

    manifest = {
        "source": "pwxcoo/chinese-xinhua",
        "buckets": SHARD_BUCKETS,
        "counts": counts,
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    print(f"已生成 {SHARD_DIR}/ 共 {len(counts)} 个分片")
    print(f"汉字：{len(characters)}，精选字覆盖：{seed_count}，组词索引：{len(common_words)}")
    print(f"清单文件：{MANIFEST}")


if __name__ == "__main__":
    main()
