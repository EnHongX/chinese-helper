// @ts-check
const { test, expect } = require("@playwright/test");

const { spawn } = require("child_process");
const net = require("net");
const fs = require("fs");
const os = require("os");
const path = require("path");

// ── Shared test server (uses temp DB, never touches real data) ──

let serverProc;
let BASE_URL;
let TMP_DB;

function findFreePort() {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, "127.0.0.1", () => {
      const port = s.address().port;
      s.close(() => resolve(port));
    });
  });
}

async function waitForServer(url, timeoutMs = 10000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await fetch(url);
      if (resp.ok) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`Server did not start within ${timeoutMs}ms`);
}

test.beforeAll(async () => {
  TMP_DB = path.join(os.tmpdir(), `ch_fe_test_${Date.now()}.sqlite3`);
  const port = await findFreePort();
  BASE_URL = `http://127.0.0.1:${port}`;
  const projectRoot = path.join(__dirname, "..");

  const wrapper = path.join(os.tmpdir(), `ch_test_srv_${Date.now()}.py`);
  fs.writeFileSync(
    wrapper,
    [
      "import sys",
      `sys.path.insert(0, ${JSON.stringify(projectRoot)})`,
      "import server",
      "from pathlib import Path",
      `server.DB_PATH = Path(${JSON.stringify(TMP_DB)})`,
      "server.init_db()",
      "from http.server import ThreadingHTTPServer",
      `httpd = ThreadingHTTPServer(("127.0.0.1", ${port}), server.ChineseHelperHandler)`,
      'print("READY", flush=True)',
      "httpd.serve_forever()",
    ].join("\n")
  );

  serverProc = spawn("python3", [wrapper], {
    stdio: ["ignore", "pipe", "pipe"],
  });

  await waitForServer(BASE_URL + "/index.html");

  // Sanity: confirm the temp DB is being used
  const stat = fs.statSync(TMP_DB);
  if (!stat.isFile()) throw new Error("Temp DB not created — server may be using real DB");
});

test.afterAll(async () => {
  if (serverProc) serverProc.kill();
  try { fs.unlinkSync(TMP_DB); } catch {}
  // Also clean WAL/SHM
  try { fs.unlinkSync(TMP_DB + "-wal"); } catch {}
  try { fs.unlinkSync(TMP_DB + "-shm"); } catch {}
});

// Helper: seed a history record via API so tests don't depend on prior state
async function apiPost(path, body) {
  const resp = await fetch(BASE_URL + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { status: resp.status, data: await resp.json() };
}

// ═══════════════════════════════════════════════════════
// 1. Page loads correctly
// ═══════════════════════════════════════════════════════

test("page loads with title and all 6 nav tabs", async ({ page }) => {
  await page.goto(BASE_URL);
  await expect(page).toHaveTitle("小学语文助手");
  await expect(page.locator("nav.feature-nav .nav-item")).toHaveCount(6);
});

test("default characters 小学语文 are displayed on load", async ({ page }) => {
  await page.goto(BASE_URL);
  await page.waitForSelector(".character-card", { timeout: 5000 });
  const pagerButtons = page.locator("#pager-pages button");
  await expect(pagerButtons).toHaveCount(4);
  const texts = await pagerButtons.allTextContents();
  expect(texts).toEqual(["小", "学", "语", "文"]);
});

// ═══════════════════════════════════════════════════════
// 2. Input filtering — mixed input shows only Chinese chars
// ═══════════════════════════════════════════════════════

test("mixed input shows only the Chinese characters from input", async ({ page }) => {
  await page.goto(BASE_URL);
  await page.locator("#character-input").fill("abc你好def世界");
  await page.locator('.search-button[type="submit"]').click();
  await page.waitForSelector(".character-card", { timeout: 5000 });

  // Pager should show exactly the 4 hanzi from the mixed input
  const pagerButtons = page.locator("#pager-pages button");
  await expect(pagerButtons).toHaveCount(4);
  const texts = await pagerButtons.allTextContents();
  expect(texts).toEqual(["你", "好", "世", "界"]);

  // The visible card should show the first character
  await expect(page.locator(".big-character").first()).toHaveText("你");
});

// ═══════════════════════════════════════════════════════
// 3. Pure ASCII input generates no character cards
// ═══════════════════════════════════════════════════════

test("pure ASCII input produces zero character cards", async ({ page }) => {
  await page.goto(BASE_URL);
  await page.locator("#character-input").fill("hello world 123");
  await page.locator('.search-button[type="submit"]').click();
  await page.waitForTimeout(800);

  // No character cards should be rendered
  const cardCount = await page.locator(".character-card").count();
  expect(cardCount).toBe(0);

  // Pager should be hidden (no pages)
  const pagerBtns = await page.locator("#pager-pages button").count();
  expect(pagerBtns).toBe(0);
});

test("empty submit does not crash", async ({ page }) => {
  await page.goto(BASE_URL);
  await page.locator("#character-input").fill("");
  await page.locator('.search-button[type="submit"]').click();
  await expect(page.locator("h1")).toHaveText("小学语文助手");
});

// ═══════════════════════════════════════════════════════
// 4. Pagination
// ═══════════════════════════════════════════════════════

test("pagination navigates between characters", async ({ page }) => {
  await page.goto(BASE_URL);
  await page.locator("#character-input").fill("你好世界");
  await page.locator('.search-button[type="submit"]').click();
  await page.waitForSelector(".character-card", { timeout: 5000 });

  await expect(page.locator(".big-character").first()).toHaveText("你");

  // Click next
  await page.locator(".pager-nav.next").click();
  await expect(page.locator(".big-character").first()).toHaveText("好");
  await expect(page.locator("#pager-counter")).toContainText("2");

  // Click next again
  await page.locator(".pager-nav.next").click();
  await expect(page.locator(".big-character").first()).toHaveText("世");

  // Click prev
  await page.locator(".pager-nav.prev").click();
  await expect(page.locator(".big-character").first()).toHaveText("好");

  // Click a specific pager button
  await page.locator("#pager-pages button", { hasText: "界" }).click();
  await expect(page.locator(".big-character").first()).toHaveText("界");
});

// ═══════════════════════════════════════════════════════
// 5. Nav tab switching
// ═══════════════════════════════════════════════════════

test("nav tabs switch features", async ({ page }) => {
  await page.goto(BASE_URL);
  await page.waitForSelector(".character-card", { timeout: 5000 });

  await page.locator('.nav-item[data-feature="meaning"]').click();
  await expect(page.locator('.nav-item[data-feature="meaning"]')).toHaveClass(/active/);

  await page.locator('.nav-item[data-feature="history"]').click();
  await expect(page.locator('.nav-item[data-feature="history"]')).toHaveClass(/active/);
});

// ═══════════════════════════════════════════════════════
// 6. History — create, verify, select, delete
// ═══════════════════════════════════════════════════════

test("history: search creates record, record is visible, can select and delete", async ({ page }) => {
  await page.goto(BASE_URL);

  // Step 1: search to create a history record
  await page.locator("#character-input").fill("测试");
  await page.locator('.search-button[type="submit"]').click();
  await page.waitForSelector(".character-card", { timeout: 5000 });

  // Step 2: switch to history tab and verify the record appears
  await page.locator('.nav-item[data-feature="history"]').click();
  await page.waitForSelector(".history-row", { timeout: 5000 });

  const rows = page.locator(".history-row");
  const rowCount = await rows.count();
  expect(rowCount).toBeGreaterThanOrEqual(1);

  // Verify the record content contains "测试"
  const firstRowText = await rows.first().textContent();
  expect(firstRowText).toContain("测试");

  // Step 3: select the record via its checkbox
  const checkbox = page.locator(".history-checkbox").first();
  await checkbox.check();
  await expect(checkbox).toBeChecked();

  // Delete button should now be enabled and show count
  const deleteBtn = page.locator(".history-delete-button");
  await expect(deleteBtn).toBeEnabled();

  // Step 4: click delete
  await deleteBtn.click();
  // Wait for history to reload
  await page.waitForTimeout(1000);

  // Verify the record is gone — either no rows or the "测试" row is gone
  const remainingRows = page.locator(".history-row");
  const remainingCount = await remainingRows.count();
  if (remainingCount > 0) {
    const allText = await remainingRows.allTextContents();
    const stillHasTest = allText.some((t) => t.includes("测试"));
    expect(stillHasTest).toBe(false);
  }
  // If 0 rows, the empty message should show
  else {
    await expect(page.locator(".history-empty")).toBeVisible();
  }
});

test("history: multiple records can be bulk-selected and deleted", async ({ page }) => {
  // Seed two records via API before loading the page
  await apiPost("/api/history", { query: "红色", characters: "红色" });
  await apiPost("/api/history", { query: "蓝色", characters: "蓝色" });

  await page.goto(BASE_URL);
  await page.locator('.nav-item[data-feature="history"]').click();
  await page.waitForSelector(".history-row", { timeout: 5000 });

  // Should see at least 2 rows
  const rows = page.locator(".history-row");
  expect(await rows.count()).toBeGreaterThanOrEqual(2);

  // Use select-all checkbox
  await page.locator("#history-select-all").check();

  // All individual checkboxes should be checked
  const checkboxes = page.locator(".history-checkbox");
  const count = await checkboxes.count();
  for (let i = 0; i < count; i++) {
    await expect(checkboxes.nth(i)).toBeChecked();
  }

  // Delete all
  const deleteBtn = page.locator(".history-delete-button");
  await expect(deleteBtn).toBeEnabled();
  await deleteBtn.click();
  await page.waitForTimeout(1000);

  // After deletion, should show empty state
  await expect(page.locator(".history-empty")).toBeVisible();
});

// ═══════════════════════════════════════════════════════
// 7. HanziWriter CDN blocked — graceful degradation
// ═══════════════════════════════════════════════════════

test("page still works when HanziWriter CDN is blocked", async ({ page }) => {
  await page.route("**/hanzi-writer*", (route) => route.abort());
  await page.goto(BASE_URL);
  await page.waitForSelector(".character-card", { timeout: 8000 });

  // Card renders with the character visible
  await expect(page.locator(".big-character").first()).toBeVisible();

  // Stroke controls have hidden attribute set by JS
  await expect(page.locator(".stroke-controls").first()).toHaveAttribute("hidden", "");
});

// ═══════════════════════════════════════════════════════
// 8. TTS unavailable — graceful degradation
// ═══════════════════════════════════════════════════════

test("page still works when speechSynthesis is unavailable", async ({ page }) => {
  await page.addInitScript(() => {
    delete window.speechSynthesis;
  });
  await page.goto(BASE_URL);
  await page.waitForSelector(".character-card", { timeout: 8000 });

  // Speak button should be disabled
  await expect(page.locator('[data-action="speak"]').first()).toBeDisabled();

  // Page is still functional
  await expect(page.locator("h1")).toHaveText("小学语文助手");
});

// ═══════════════════════════════════════════════════════
// 9. Card tab switching
// ═══════════════════════════════════════════════════════

test("card internal tabs switch panels", async ({ page }) => {
  await page.goto(BASE_URL);
  await page.waitForSelector(".character-card", { timeout: 5000 });

  const meaningTab = page.locator('.card-tab[data-tab="meaning"]').first();
  await meaningTab.click();
  await expect(meaningTab).toHaveAttribute("aria-selected", "true");
  await expect(page.locator('.card-panel[data-panel="meaning"]').first()).toBeVisible();
});

// ═══════════════════════════════════════════════════════
// 10. Dictation tab loads
// ═══════════════════════════════════════════════════════

test("dictation tab loads without fatal JS errors", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (err) => errors.push(err.message));

  await page.goto(BASE_URL);
  await page.locator('.nav-item[data-feature="dictation"]').click();
  await page.waitForTimeout(1000);

  const fatal = errors.filter(
    (e) => !e.includes("getVoices") && !e.includes("speechSynthesis")
  );
  expect(fatal).toHaveLength(0);
});

// ═══════════════════════════════════════════════════════
// 11. Clear input button
// ═══════════════════════════════════════════════════════

test("clear input button clears the field", async ({ page }) => {
  await page.goto(BASE_URL);
  const input = page.locator("#character-input");
  await input.fill("你好");
  await expect(page.locator("#clear-input-button")).toBeVisible();
  await page.locator("#clear-input-button").click();
  await expect(input).toHaveValue("");
});
