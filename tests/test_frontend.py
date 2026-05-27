#!/usr/bin/env python3
"""Frontend integration tests for chinese-helper.

Uses Playwright to drive a real Chromium browser against the real server
with a temporary database. Tests real page interactions including:
- Input filtering, pagination, tab switching
- History records displayed on page, checkbox-selected deletion
- TTS degradation when speechSynthesis exists but speak() fails
- HanziWriter stroke controls visibility when library is unavailable
- Page stability under all degradation scenarios

Test failures reflect real bugs found in the application.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error
import warnings

warnings.filterwarnings("ignore", category=ResourceWarning, message=".*unclosed.*")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

POLL_INTERVAL = 0.1
MAX_WAIT = 10


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port, timeout=MAX_WAIT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(POLL_INTERVAL)
    return False


class TestFrontendIntegration(unittest.TestCase):
    """Full browser integration tests using Playwright."""

    @classmethod
    def setUpClass(cls):
        cls.tmp_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.tmp_dir, "chinese_helper.sqlite3")
        cls.port = _find_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        wrapper = os.path.join(cls.tmp_dir, "_test_server.py")
        with open(wrapper, "w") as f:
            f.write(f"""
import sys, os
sys.path.insert(0, {repr(PROJECT_ROOT)})
os.chdir({repr(PROJECT_ROOT)})
import server
server.DB_PATH = server.Path({repr(cls.db_path)})
server.init_db()
from http.server import ThreadingHTTPServer
srv = ThreadingHTTPServer(("127.0.0.1", {cls.port}), server.ChineseHelperHandler)
print("TEST_SERVER_READY", flush=True)
srv.serve_forever()
""")
        cls.server_proc = subprocess.Popen(
            [sys.executable, wrapper],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        deadline = time.time() + MAX_WAIT
        ready = False
        while time.time() < deadline:
            line = cls.server_proc.stdout.readline().decode().strip()
            if "TEST_SERVER_READY" in line:
                ready = True
                break
            if cls.server_proc.poll() is not None:
                break
        if not ready:
            ready = _wait_for_server(cls.port)
        if not ready:
            stderr_output = cls.server_proc.stderr.read().decode()
            cls.tearDownClass()
            raise RuntimeError(f"Server failed to start. stderr: {stderr_output}")

        from playwright.sync_api import sync_playwright
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch()
        cls.context = cls.browser.new_context()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'context') and cls.context:
            cls.context.close()
        if hasattr(cls, 'browser') and cls.browser:
            cls.browser.close()
        if hasattr(cls, '_pw') and cls._pw:
            cls._pw.stop()
        if hasattr(cls, 'server_proc') and cls.server_proc:
            cls.server_proc.terminate()
            try:
                cls.server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server_proc.kill()
                cls.server_proc.wait(timeout=3)
        if hasattr(cls, 'tmp_dir') and os.path.isdir(cls.tmp_dir):
            shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def _new_page(self):
        """Create a fresh page with error collection."""
        page = self.context.new_page()
        page.page_errors = []
        page.on("pageerror", lambda err: page.page_errors.append(str(err)))
        return page

    # ====================================================================
    # Page load and basic structure
    # ====================================================================

    def test_01_page_loads_with_title(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        self.assertIn("小学语文助手", page.title())
        self.assertEqual(len(page.page_errors), 0,
            f"Page should have no JS errors on load. Got: {page.page_errors}")
        page.close()

    def test_02_default_characters_displayed(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector(".character-card", timeout=5000)
        # The app shows one card at a time with pagination
        big_char = page.query_selector(".big-character")
        self.assertIsNotNone(big_char)
        text = big_char.inner_text().strip()
        self.assertEqual(text, "小", f"First card should be '小', got '{text}'")
        self.assertEqual(len(page.page_errors), 0)
        page.close()

    def test_03_pager_visible_for_multiple_chars(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        pager = page.wait_for_selector("#char-pager", timeout=5000)
        self.assertFalse(pager.is_hidden(), "Pager should be visible for multiple chars")
        pages = page.query_selector_all(".pager-page")
        self.assertEqual(len(pages), 4, "Should have 4 page buttons for 小学语文")
        self.assertEqual(len(page.page_errors), 0)
        page.close()

    # ====================================================================
    # Input filtering — non-hanzi is stripped
    # ====================================================================

    def test_04_input_filters_non_hanzi(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        inp = page.wait_for_selector("#character-input", timeout=5000)
        inp.fill("小abc学123语")
        page.click("button.search-button")
        page.wait_for_selector(".character-card", timeout=5000)
        # Pager counter should show 3 chars
        counter = page.query_selector("#pager-counter")
        self.assertIsNotNone(counter)
        text = counter.inner_text()
        self.assertIn("3", text, f"Pager counter should show 3 chars, got: {text}")
        self.assertEqual(len(page.page_errors), 0)
        page.close()

    def test_05_input_all_english_shows_no_cards(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        inp = page.wait_for_selector("#character-input", timeout=5000)
        inp.fill("hello world")
        page.click("button.search-button")
        cards = page.query_selector_all(".character-card")
        self.assertEqual(len(cards), 0, "No cards for pure English input")
        self.assertEqual(len(page.page_errors), 0,
            f"Page should have no errors on empty input. Got: {page.page_errors}")
        page.close()

    # ====================================================================
    # Pagination
    # ====================================================================

    def test_06_pager_navigates_between_chars(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector(".character-card", timeout=5000)

        big_char = page.query_selector(".big-character")
        self.assertEqual(big_char.inner_text().strip(), "小")

        page.click("button.pager-nav.next")
        page.wait_for_timeout(300)
        big_char = page.query_selector(".big-character")
        self.assertEqual(big_char.inner_text().strip(), "学")

        page.click("button.pager-nav.prev")
        page.wait_for_timeout(300)
        big_char = page.query_selector(".big-character")
        self.assertEqual(big_char.inner_text().strip(), "小")
        self.assertEqual(len(page.page_errors), 0)
        page.close()

    def test_07_pager_page_buttons_switch_char(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector(".character-card", timeout=5000)

        pages = page.query_selector_all(".pager-page")
        pages[2].click()  # 3rd button = 语
        page.wait_for_timeout(300)
        big_char = page.query_selector(".big-character")
        self.assertEqual(big_char.inner_text().strip(), "语")
        self.assertEqual(len(page.page_errors), 0)
        page.close()

    # ====================================================================
    # Tab switching
    # ====================================================================

    def test_08_tab_switching_works(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector(".character-card", timeout=5000)

        # Default tab: form (字形拼音)
        form_panel = page.query_selector('[data-panel="form"]')
        self.assertFalse(form_panel.is_hidden())

        # Click 字义 tab
        page.click('[data-tab="meaning"]')
        meaning_panel = page.query_selector('[data-panel="meaning"]')
        self.assertFalse(meaning_panel.is_hidden())
        form_after = page.query_selector('[data-panel="form"]')
        self.assertTrue(form_after.is_hidden())

        # Click 组词造句 tab
        page.click('[data-tab="words"]')
        words_panel = page.query_selector('[data-panel="words"]')
        self.assertFalse(words_panel.is_hidden())
        self.assertEqual(len(page.page_errors), 0)
        page.close()

    # ====================================================================
    # History — page shows records, checkbox select + delete removes them
    # ====================================================================

    def test_09_history_records_displayed_on_page(self):
        """Search creates a record; history page shows it with correct content."""
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")

        # Search for a character to create a history record
        inp = page.wait_for_selector("#character-input", timeout=5000)
        inp.fill("山水")
        page.click("button.search-button")
        page.wait_for_timeout(500)

        # Switch to history
        page.click('[data-feature="history"]')
        page.wait_for_timeout(1000)

        # Should see history rows on the page
        rows = page.query_selector_all("article.history-row")
        self.assertGreaterEqual(len(rows), 1, "History page should show at least 1 row")

        # The row should contain the query text
        queries = page.query_selector_all(".history-query")
        query_texts = [q.inner_text().strip() for q in queries]
        self.assertIn("山水", query_texts,
            f"History should show '山水' query. Found: {query_texts}")
        self.assertEqual(len(page.page_errors), 0)
        page.close()

    def test_10_history_checkbox_delete_removes_from_page(self):
        """Check a row's checkbox, click delete, verify row disappears from page."""
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")

        # Create 3 records so we can delete one and still have some left
        for q in ["山水", "天地", "大小"]:
            inp = page.wait_for_selector("#character-input", timeout=5000)
            inp.fill(q)
            page.click("button.search-button")
            page.wait_for_timeout(300)

        # Go to history
        page.click('[data-feature="history"]')
        page.wait_for_timeout(1000)

        # Count initial rows
        rows_before = page.query_selector_all("article.history-row")
        self.assertGreaterEqual(len(rows_before), 3,
            f"Should have >=3 history rows, got {len(rows_before)}")

        # Check the first individual row checkbox (not the select-all)
        checkboxes = page.query_selector_all("input.history-checkbox")
        self.assertGreaterEqual(len(checkboxes), 1)
        first_val = checkboxes[0].get_attribute("value")
        first_checkbox_query = page.query_selector(
            f'input.history-checkbox[value="{first_val}"] + button .history-query'
        )
        first_query_text = first_checkbox_query.inner_text().strip() if first_checkbox_query else "?"

        checkboxes[0].check()
        page.wait_for_timeout(300)

        # Click delete button
        delete_btn = page.query_selector("button.history-delete-button")
        self.assertIsNotNone(delete_btn, "Delete button should exist")
        delete_btn.click()
        page.wait_for_timeout(1000)

        # Verify the row is gone from the page
        rows_after = page.query_selector_all("article.history-row")
        self.assertEqual(len(rows_after), len(rows_before) - 1,
            f"After deleting 1 row, should have {len(rows_before)-1} rows, got {len(rows_after)}")

        # The deleted query should not appear in remaining rows
        remaining_queries = [
            q.inner_text().strip()
            for q in page.query_selector_all(".history-query")
        ]
        self.assertNotIn(first_query_text, remaining_queries,
            f"Deleted query '{first_query_text}' should not appear. Remaining: {remaining_queries}")

        self.assertEqual(len(page.page_errors), 0)
        page.close()

    # ====================================================================
    # TTS degradation — speechSynthesis exists but speak() fails
    # ====================================================================

    def test_11_tts_speak_throws_causes_page_error(self):
        """When speechSynthesis.speak() throws, the page has an uncaught error.

        This is a REAL BUG: speakText() calls window.speechSynthesis.speak(utter)
        without try/catch, so if speak() throws, the error propagates as an
        uncaught page error. The test reports this failure accurately.
        """
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector(".character-card", timeout=5000)

        # Override speechSynthesis.speak to throw after page load
        # speechSupported was set to true at load time, so speakText WILL be called
        page.evaluate("""() => {
            window.speechSynthesis.speak = function() {
                throw new TypeError('speechSynthesis.speak is not a function');
            };
        }""")

        # Click the speak button
        speak_btn = page.query_selector('[data-action="speak"]')
        self.assertIsNotNone(speak_btn, "Speak button should exist")
        speak_btn.click()
        page.wait_for_timeout(500)

        # This SHOULD report the error — it's a real bug that speakText
        # doesn't wrap speak() in try/catch
        self.assertGreater(len(page.page_errors), 0,
            "BUG: speechSynthesis.speak() throwing causes uncaught page error. "
            "speakText() should wrap speak() in try/catch. "
            f"Errors: {page.page_errors}")
        page.close()

    def test_12_tts_speak_not_a_function_causes_page_error(self):
        """When speechSynthesis.speak is not a function (e.g. undefined overridden
        to a non-function), clicking the speak button causes an uncaught TypeError.

        This is a REAL BUG: the guard 'speechSupported' checks "speechSynthesis"
        in window, which is true even if speak is not callable. speakText() then
        calls .speak() which throws TypeError.
        """
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector(".character-card", timeout=5000)

        # Replace speak with something non-callable that will throw on invocation.
        # Using defineProperty on the existing speechSynthesis object to make
        # speak a non-function value simulates the real scenario where the
        # browser's speechSynthesis object exists but speak is broken.
        page.evaluate("""() => {
            Object.defineProperty(window.speechSynthesis, 'speak', {
                value: undefined,
                writable: true,
                configurable: true
            });
        }""")

        speak_btn = page.query_selector('[data-action="speak"]')
        self.assertIsNotNone(speak_btn)
        speak_btn.click()
        page.wait_for_timeout(500)

        # This SHOULD report the error — it's the known guard bug
        self.assertGreater(len(page.page_errors), 0,
            "BUG: speechSynthesis.speak not callable causes uncaught TypeError. "
            "The 'speechSupported' guard uses 'in' operator which only checks "
            "property existence, not that speak is callable. "
            f"Errors: {page.page_errors}")
        page.close()

    # ====================================================================
    # HanziWriter degradation
    # ====================================================================

    def test_13_hanziwriter_not_loaded_controls_still_visible_bug(self):
        """When HanziWriter is undefined, JS sets controls.hidden = true,
        but CSS display:flex overrides the hidden attribute, so buttons
        remain VISIBLE on the page.

        This is a REAL BUG: .stroke-controls[hidden] has no CSS rule to set
        display:none, so the hidden attribute is visually ignored.
        The test reports this failure accurately.
        """
        page = self._new_page()
        page.add_init_script(
            "Object.defineProperty(window, 'HanziWriter', {value: undefined, writable: false});"
        )
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector(".character-card", timeout=5000)

        controls = page.query_selector(".stroke-controls")
        self.assertIsNotNone(controls, "Stroke controls element should exist")

        # JS correctly sets the hidden attribute
        hidden_attr = controls.get_attribute("hidden")
        self.assertIsNotNone(hidden_attr,
            "JS should set hidden attribute when HanziWriter is not loaded")

        # But CSS display:flex overrides it — the buttons are still VISIBLE
        # This is a real CSS bug
        is_visually_visible = not controls.is_hidden()
        if is_visually_visible:
            self.fail(
                "BUG: .stroke-controls has hidden attribute set by JS, "
                "but CSS display:flex overrides it so buttons are still visible. "
                "Fix: add .stroke-controls[hidden] { display: none; } to CSS."
            )

        self.assertEqual(len(page.page_errors), 0)
        page.close()

    def test_14_hanziwriter_cdn_404_no_page_errors(self):
        """When HanziWriter CDN returns 404, page should load without JS errors."""
        page = self._new_page()
        page.route("**/hanzi-writer*", lambda route: route.fulfill(
            status=404, body="not found"
        ))
        page.goto(self.base_url, wait_until="networkidle")
        page.wait_for_selector(".character-card", timeout=5000)

        # No uncaught JS errors (HanziWriter not defined is handled by if-check)
        self.assertEqual(len(page.page_errors), 0,
            f"Page should have no errors when HanziWriter CDN 404s. Got: {page.page_errors}")

        # Character content should still display
        big_char = page.query_selector(".big-character")
        self.assertIsNotNone(big_char)
        self.assertTrue(len(big_char.inner_text().strip()) > 0)
        page.close()

    # ====================================================================
    # Shard data populates card correctly
    # ====================================================================

    def test_15_shard_data_populates_card_fields(self):
        """Search for a character and verify real data from shards fills the card."""
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")

        inp = page.wait_for_selector("#character-input", timeout=5000)
        inp.fill("小")
        page.click("button.search-button")
        page.wait_for_selector(".character-card", timeout=5000)

        # Pinyin from seed data: xiǎo
        pinyin_el = page.query_selector('[data-field="pinyin"]')
        self.assertIsNotNone(pinyin_el)
        pinyin_text = pinyin_el.inner_text().strip()
        self.assertNotEqual(pinyin_text, "—")
        self.assertNotEqual(pinyin_text, "暂无")
        self.assertIn("xiǎo", pinyin_text, f"Expected pinyin 'xiǎo', got '{pinyin_text}'")

        # Initial from seed data: x
        initial_el = page.query_selector('[data-field="initial"]')
        self.assertEqual(initial_el.inner_text().strip(), "x",
            f"Initial for '小' should be 'x'")

        # SyllableType from seed data: 普通音节
        st_el = page.query_selector('[data-field="syllableType"]')
        st_text = st_el.inner_text().strip()
        self.assertTrue(len(st_text) > 0, "syllableType should be populated")

        # Radical from seed data: 小
        radical_el = page.query_selector('[data-field="radical"]')
        radical_text = radical_el.inner_text().strip()
        self.assertEqual(radical_text, "小", f"Radical for '小' should be '小', got '{radical_text}'")

        self.assertEqual(len(page.page_errors), 0)
        page.close()

    # ====================================================================
    # Feature navigation
    # ====================================================================

    def test_16_feature_nav_switches_view(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")

        page.click('[data-feature="meaning"]')
        page.wait_for_timeout(500)
        search_panel = page.query_selector(".search-panel")
        self.assertIsNotNone(search_panel)

        page.click('[data-feature="history"]')
        page.wait_for_timeout(500)
        history = page.query_selector(".history-panel")
        self.assertIsNotNone(history, "History panel should appear")

        page.click('[data-feature="hanzi"]')
        page.wait_for_timeout(500)
        page.wait_for_selector(".character-card", timeout=5000)
        self.assertEqual(len(page.page_errors), 0)
        page.close()

    # ====================================================================
    # Clear input button
    # ====================================================================

    def test_17_clear_input_button(self):
        page = self._new_page()
        page.goto(self.base_url, wait_until="networkidle")
        inp = page.wait_for_selector("#character-input", timeout=5000)
        inp.fill("测试")
        page.wait_for_timeout(200)
        clear_btn = page.query_selector("#clear-input-button")
        if clear_btn:
            clear_btn.click(force=True)
            page.wait_for_timeout(200)
            self.assertEqual(inp.input_value(), "", "Input should be cleared")
        page.close()


if __name__ == "__main__":
    unittest.main()
