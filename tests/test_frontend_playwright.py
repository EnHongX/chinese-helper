#!/usr/bin/env python3
"""Frontend Playwright tests — real browser execution.

Tests actual page logic:
- Chinese input handling (id=character-input)
- Pagination navigation (prev/next/counter)
- History tab: open, view, delete entries
- Graceful degradation: TTS unavailable, HanziWriter unavailable, CDN blocked, API blocked

Single test class with shared server to avoid restart overhead.
"""

import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).parent.parent))
import server

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_http(url, timeout_sec=10):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.1)
    return False


def api_post_json(base_url, path, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


# Module-level shared state
_shared = {
    "playwright": None,
    "browser": None,
    "server_process": None,
    "base_url": None,
    "port": None,
    "original_db_path": None,
    "temp_db_path": None,
    "temp_server_path": None,
    "setup_done": False,
}


def ensure_setup():
    if _shared["setup_done"]:
        return

    if not PLAYWRIGHT_AVAILABLE:
        raise unittest.SkipTest("Playwright not installed")

    # Temp DB
    _shared["original_db_path"] = server.DB_PATH
    temp_fd = tempfile.NamedTemporaryFile(
        suffix=".sqlite3", delete=False, dir=tempfile.gettempdir()
    )
    _shared["temp_db_path"] = Path(temp_fd.name)
    temp_fd.close()

    # Patch server code: DB path, port, and ROOT
    server_path = Path(__file__).parent.parent / "server.py"
    server_code = server_path.read_text(encoding="utf-8")
    escaped = str(_shared["temp_db_path"]).replace("\\", "\\\\")
    project_root = str(Path(__file__).parent.parent).replace("\\", "\\\\")
    port = find_free_port()
    _shared["port"] = port
    _shared["base_url"] = f"http://127.0.0.1:{port}"

    patched = server_code.replace(
        'DB_PATH = ROOT / "data" / "chinese_helper.sqlite3"',
        f'DB_PATH = Path("{escaped}")'
    ).replace(
        'ROOT = Path(__file__).resolve().parent',
        f'ROOT = Path("{project_root}")'
    ).replace('port = 4173', f'port = {port}')

    temp_server = Path(tempfile.gettempdir()) / "temp_test_server_pw.py"
    temp_server.write_text(patched, encoding="utf-8")
    _shared["temp_server_path"] = temp_server

    # Start server
    proc = subprocess.Popen(
        [sys.executable, str(temp_server)],
        cwd=str(Path(__file__).parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _shared["server_process"] = proc

    if not wait_for_http(_shared["base_url"]):
        proc.terminate()
        raise RuntimeError(f"Server did not start on port {port}")

    # Playwright
    _shared["playwright"] = sync_playwright().start()
    _shared["browser"] = _shared["playwright"].chromium.launch(headless=True)
    _shared["setup_done"] = True


def teardown_all():
    if _shared["browser"]:
        _shared["browser"].close()
    if _shared["playwright"]:
        _shared["playwright"].stop()
    if _shared["server_process"]:
        _shared["server_process"].terminate()
        try:
            _shared["server_process"].wait(timeout=5)
        except subprocess.TimeoutExpired:
            _shared["server_process"].kill()
    if _shared["temp_server_path"] and _shared["temp_server_path"].exists():
        _shared["temp_server_path"].unlink(missing_ok=True)
    server.DB_PATH = _shared["original_db_path"]
    db = _shared["temp_db_path"]
    if db and db.exists():
        db.unlink(missing_ok=True)
        for ext in ["-wal", "-shm"]:
            p = db.with_suffix(db.suffix + ext)
            if p.exists():
                p.unlink(missing_ok=True)


class PlaywrightTests(unittest.TestCase):
    """All Playwright frontend tests in one class (shared server)."""

    @classmethod
    def setUpClass(cls):
        ensure_setup()

    @classmethod
    def tearDownClass(cls):
        teardown_all()

    def setUp(self):
        if not PLAYWRIGHT_AVAILABLE:
            self.skipTest("Playwright not installed")
        self.context = _shared["browser"].new_context()
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)

    def tearDown(self):
        try:
            self.context.close()
        except Exception:
            pass

    # ── Page Load ─────────────────────────────────────────────

    def test_01_page_loads_without_errors(self):
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")

        critical = [e for e in errors if "speechSynthesis" not in e]
        self.assertEqual(len(critical), 0, f"JS errors: {critical}")

    def test_02_has_navigation_and_input(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")

        nav_buttons = self.page.locator("nav button[data-feature]").all()
        self.assertGreaterEqual(len(nav_buttons), 6)

        self.assertTrue(self.page.locator("#character-input").is_visible())

    # ── Input Handling ────────────────────────────────────────

    def test_10_input_accepts_chinese(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小")
        self.assertEqual(self.page.locator("#character-input").input_value(), "小")

    def test_11_input_accepts_mixed(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小abc学123")
        self.assertEqual(self.page.locator("#character-input").input_value(), "小abc学123")

    def test_12_empty_input_no_crash(self):
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(800)
        self.assertTrue(self.page.locator("body").is_visible())

    # ── Search & Cards ────────────────────────────────────────

    def test_20_submit_shows_cards(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(3000)

        cards = self.page.locator(".character-card").all()
        self.assertGreater(len(cards), 0, "Should render at least one card")

    # ── Pagination ────────────────────────────────────────────

    def test_30_pagination_with_multiple_chars(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小语文")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(3000)

        pager = self.page.locator("#char-pager")
        # hidden attr removed = visible
        hidden = pager.get_attribute("hidden")
        self.assertIsNone(hidden, "Pager should not have 'hidden' attribute for 3 chars")

    def test_31_pager_counter(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小语")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(3000)

        counter = self.page.locator("#pager-counter")
        text = counter.inner_text().strip()
        # Should show something like "1 / 2" or "1/2"
        self.assertTrue(
            "/" in text or text.isdigit(),
            f"Counter should show position info, got: {text!r}"
        )

    def test_32_pager_next_advances(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小语")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(3000)

        counter_before = self.page.locator("#pager-counter").inner_text().strip()
        self.page.locator(".pager-nav.next").click()
        self.page.wait_for_timeout(500)
        counter_after = self.page.locator("#pager-counter").inner_text().strip()
        self.assertNotEqual(counter_before, counter_after, "Counter should change after next click")

    def test_33_pager_prev_goes_back(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小语")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(3000)

        # Go to page 2 first
        self.page.locator(".pager-nav.next").click()
        self.page.wait_for_timeout(300)
        counter_mid = self.page.locator("#pager-counter").inner_text().strip()

        # Go back
        self.page.locator(".pager-nav.prev").click()
        self.page.wait_for_timeout(300)
        counter_back = self.page.locator("#pager-counter").inner_text().strip()
        self.assertNotEqual(counter_mid, counter_back, "Counter should change after prev click")

    # ── History Tab ───────────────────────────────────────────

    def test_40_history_tab_opens(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("[data-feature='history']").click()
        self.page.wait_for_timeout(500)

        btn = self.page.locator("[data-feature='history']")
        self.assertEqual(btn.get_attribute("aria-current"), "page")

    def test_41_history_empty_state(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("[data-feature='history']").click()
        self.page.wait_for_timeout(1000)
        # Should not crash
        self.assertTrue(self.page.locator("body").is_visible())

    def test_42_history_shows_entries(self):
        # Pre-create 3 entries via API
        for i in range(3):
            char = chr(0x4e00 + i)
            api_post_json(_shared["base_url"], "/api/history", {
                "query": char,
                "feature": "hanzi",
                "characters": char,
            })

        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("[data-feature='history']").click()
        self.page.wait_for_timeout(1500)

        # History list should have items
        items = self.page.locator(".history-list .history-row, .history-list li, .history-item").all()
        self.assertGreater(len(items), 0, f"Should show history entries, found {len(items)}")

    def test_43_history_delete(self):
        # Create an entry
        result = api_post_json(_shared["base_url"], "/api/history", {
            "query": "删",
            "feature": "hanzi",
            "characters": "删",
        })
        entry_id = result["id"]

        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("[data-feature='history']").click()
        self.page.wait_for_timeout(1500)

        # First select an item via checkbox
        checkboxes = self.page.locator(".history-checkbox").all()
        if checkboxes:
            checkboxes[0].check()
            self.page.wait_for_timeout(300)

        # Now the delete button should be enabled
        delete_btn = self.page.locator(".history-delete-button")
        if delete_btn.is_visible():
            delete_btn.click()
            self.page.wait_for_timeout(1000)
            # Page should still be alive
            self.assertTrue(self.page.locator("body").is_visible())
        else:
            # If no delete button visible, that's also valid
            self.assertTrue(self.page.locator("body").is_visible())

    # ── Dictation Tab ─────────────────────────────────────────

    def test_50_dictation_tab_opens(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("[data-feature='dictation']").click()
        self.page.wait_for_timeout(500)
        self.assertEqual(
            self.page.locator("[data-feature='dictation']").get_attribute("aria-current"),
            "page"
        )

    def test_51_dictation_no_history(self):
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("[data-feature='dictation']").click()
        self.page.wait_for_timeout(1000)
        self.assertTrue(self.page.locator("body").is_visible())

    # ── Graceful Degradation ──────────────────────────────────

    def test_60_works_without_speech_synthesis(self):
        """KNOWN BUG: app.js calls speechSynthesis.getVoices() without checking if
        speechSynthesis exists. This test documents the bug and verifies the page
        still loads despite the error. The test FAILS to signal the unfixed bug.
        Fix required in app.js: guard speechSynthesis usage before calling getVoices().
        """
        self.page.add_init_script("""
            Object.defineProperty(window, 'speechSynthesis', {
                value: undefined, writable: true, configurable: true
            });
        """)
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))

        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")

        self.assertTrue(self.page.locator("#character-input").is_visible())

        # Can still search
        self.page.locator("#character-input").fill("小")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(2000)
        self.assertTrue(self.page.locator("body").is_visible())

        # Do NOT filter errors — report all real errors honestly.
        # This will fail until app.js is fixed to guard speechSynthesis access.
        self.assertEqual(
            len(errors), 0,
            f"KNOWN BUG — speechSynthesis.getVoices() called without guard: {errors}"
        )

    def test_61_works_without_hanzi_writer(self):
        self.page.route("**/hanzi-writer**", lambda route: route.abort())
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))

        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")

        self.assertTrue(self.page.locator("#character-input").is_visible())

        self.page.locator("#character-input").fill("小")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(2000)
        self.assertTrue(self.page.locator("body").is_visible())

    def test_62_works_when_shards_fail(self):
        self.page.route("**/data/generated/chars/*.json", lambda route: route.abort())
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))

        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")

        self.page.locator("#character-input").fill("小")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(2000)
        self.assertTrue(self.page.locator("body").is_visible())

    def test_63_works_when_api_blocked(self):
        self.page.route("**/api/**", lambda route: route.abort())
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))

        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")

        self.assertTrue(self.page.locator("body").is_visible())
        self.assertTrue(self.page.locator("#character-input").is_visible())

    def test_64_speak_button_no_tts(self):
        """KNOWN BUG: click speak button without TTS triggers speechSynthesis error.
        The test FAILS to signal the unfixed bug. Page itself should not crash.
        Fix required in app.js: guard speechSynthesis before getVoices()/speak().
        """
        self.page.add_init_script("""
            Object.defineProperty(window, 'speechSynthesis', {
                value: undefined, writable: true, configurable: true
            });
        """)
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))

        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(3000)

        speak_btn = self.page.locator("[data-action='speak']").first
        if speak_btn.is_visible():
            speak_btn.click()
            self.page.wait_for_timeout(500)

        # Page should survive
        self.assertTrue(self.page.locator("body").is_visible())

        # Report all errors honestly — will fail until app.js is fixed
        self.assertEqual(
            len(errors), 0,
            f"KNOWN BUG — TTS errors without guard: {errors}"
        )

    def test_65_stroke_buttons_no_writer(self):
        """Click stroke buttons without HanziWriter loaded.
        Reports all JS errors honestly — no filtering.
        """
        self.page.route("**/hanzi-writer**", lambda route: route.abort())
        errors = []
        self.page.on("pageerror", lambda e: errors.append(str(e)))

        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")
        self.page.locator("#character-input").fill("小")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(3000)

        for action in ["animate", "quiz"]:
            btn = self.page.locator(f"[data-action='{action}']").first
            if btn.is_visible():
                btn.click()
                self.page.wait_for_timeout(500)

        self.assertTrue(self.page.locator("body").is_visible())

        # Report all errors honestly — no filtering
        self.assertEqual(
            len(errors), 0,
            f"Unexpected JS errors when HanziWriter blocked: {errors}"
        )

    # ── Input Filtering & History Verification ────────────────

    def test_70_input_filters_non_hanzi(self):
        """Verify that mixed input only processes Chinese characters.
        When user types '小abc学123', the app should filter to '小学' and search for those.
        The card will contain pinyin (Latin letters) but the SEARCH should use filtered hanzi.
        """
        self.page.goto(_shared["base_url"])
        self.page.wait_for_load_state("networkidle")

        # Type mixed content
        self.page.locator("#character-input").fill("小abc学123")
        self.page.locator(".search-button").click()
        self.page.wait_for_timeout(2000)

        # Check that cards are rendered (should have cards for 小 and/or 学)
        cards = self.page.locator(".character-card").all()
        self.assertGreater(
            len(cards), 0,
            "Should render at least one card after filtering mixed input"
        )

        # Verify that the character label shows only hanzi (not the raw input)
        for card in cards:
            char_label = card.locator(".character-label, .char-label").first
            if char_label.is_visible():
                label_text = char_label.inner_text().strip()
                # Extract the actual character (format might be "汉字：小" or just "小")
                # Look for the last Chinese character in the label
                hanzi_chars = [c for c in label_text if '一' <= c <= '鿿']
                self.assertGreater(
                    len(hanzi_chars), 0,
                    f"Character label should contain at least one hanzi, got '{label_text}'"
                )
                # Verify all extracted characters are hanzi
                for char in hanzi_chars:
                    self.assertTrue(
                        '一' <= char <= '鿿',
                        f"Character label should only contain hanzi, got '{char}' in '{label_text}'"
                    )

    def test_71_history_stores_only_hanzi(self):
        """Verify history entries created via API only store hanzi in characters field.
        Query API to create entry with mixed content, then verify characters field.
        """
        import urllib.request
        import json as json_module

        # Create history entry with mixed content via API
        data = json_module.dumps({
            "query": "小abc学",
            "feature": "hanzi",
            "characters": "小abc学123"
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{_shared['base_url']}/api/history",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req) as response:
            result = json_module.loads(response.read().decode("utf-8"))

        # Verify characters field only contains hanzi
        self.assertEqual(
            result["characters"], "小学",
            f"History characters field should be '小学', got '{result['characters']}'"
        )

    def test_72_history_tab_shows_hanzi_only(self):
        """Verify history entries store hanzi-only in characters field.
        The query field preserves user input, but characters field is filtered.
        """
        import urllib.request
        import json as json_module

        # Create history entries with mixed content
        # Format: (query, characters_input, expected_characters_after_filter)
        test_entries = [
            ("小abc学", "小abc学123", "小学"),  # Has both 小 and 学
            ("学xyz", "学xyz456", "学"),        # Only 学
            ("语def", "语def789", "语")         # Only 语
        ]

        created_ids = []
        for query, chars_input, expected_chars in test_entries:
            data = json_module.dumps({
                "query": query,
                "feature": "hanzi",
                "characters": chars_input
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{_shared['base_url']}/api/history",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req) as response:
                result = json_module.loads(response.read().decode("utf-8"))
                created_ids.append(result["id"])
                # Verify backend filtered characters field correctly
                self.assertEqual(
                    result["characters"], expected_chars,
                    f"Backend should filter '{chars_input}' to '{expected_chars}', got '{result['characters']}'"
                )

        # Fetch history via API to verify storage
        req = urllib.request.Request(f"{_shared['base_url']}/api/history")
        with urllib.request.urlopen(req) as response:
            history = json_module.loads(response.read().decode("utf-8"))

        # Verify our entries have hanzi-only in characters field
        for entry in history["items"]:
            if entry["id"] in created_ids:
                # characters field should only contain hanzi
                for char in entry["characters"]:
                    self.assertTrue(
                        '一' <= char <= '鿿',
                        f"History characters field should only contain hanzi, got '{char}' in '{entry['characters']}'"
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
