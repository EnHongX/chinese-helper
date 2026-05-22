#!/usr/bin/env python3
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "data" / "vendor" / "chinese-xinhua"
BASE_URL = "https://raw.githubusercontent.com/pwxcoo/chinese-xinhua/master/data"
FILES = ["word.json", "ci.json"]


def main():
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    for filename in FILES:
        target = VENDOR_DIR / filename
        url = f"{BASE_URL}/{filename}"
        print(f"下载 {url}")
        urlretrieve(url, target)
        print(f"已保存 {target}")


if __name__ == "__main__":
    main()
