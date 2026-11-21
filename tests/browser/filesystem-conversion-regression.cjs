// DFS to ADFS conversion in a real browser, against the real service.
//
// A DFS image is created with one file, converted from its pane's menu, and
// the converted ADFS image must open in a new pane with the file present,
// leaving the source pane as it was.
const { chromium } = require("playwright");

const target = process.env.ACORN_FILE_FORGE_URL || "http://127.0.0.1:8666";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  try {
    await page.goto(target, { waitUntil: "networkidle" });
    await page.locator(".pane-new").first().click();
    await page.locator('#modalContent select[name="format"]').selectOption("ssd");
    await page.locator('#modalContent input[name="title"]').fill("CONVERT");
    await page.locator('#modalContent button[value="create"]').click();
    await page.waitForSelector(".pane .file-tools");
    const panesBefore = await page.locator(".pane").count();
    const sourceId = await page.evaluate(() => panes.find(pane => pane.image)?.image.id);
    await page.evaluate(async id => {
      const form = new FormData();
      form.append("file", new Blob(["PRINT 1\r"]), "HELLO");
      form.append("destination", "$");
      const response = await fetch(`/api/images/${id}/files`, { method: "POST", body: form });
      if (!response.ok) throw new Error(`upload failed: ${response.status} ${await response.text()}`);
    }, sourceId);

    const sourceIndex = await page.evaluate(id => panes.findIndex(pane => pane.image?.id === id), sourceId);
    const sourcePane = page.locator(".pane").nth(sourceIndex);
    await page.evaluate(index => renderPane(index), sourceIndex);
    await sourcePane.locator(".tool-menu", { has: page.locator(".convert-filesystem") }).locator("summary").click();
    await sourcePane.locator(".convert-filesystem").click();
    await page.waitForSelector("#modalContent h2:has-text('to ADFS')");
    await page.waitForSelector("#modalContent .conversion-plan strong");
    const planText = await page.locator("#modalContent .conversion-plan").textContent();
    assert(planText.includes("1 file"), `the plan names one file: ${planText}`);
    await page.locator('#modalContent select[name="target"]').selectOption("adfs-m");
    await page.waitForSelector("#modalContent .conversion-plan strong");
    await page.locator('#modalContent button[value="convert"]').click();
    await page.waitForFunction(() => !document.querySelector("#modal").open, null, { timeout: 60000 });

    const result = await page.evaluate(id => {
      const converted = panes.find(pane => pane.image && pane.image.id !== id);
      const source = panes.find(pane => pane.image?.id === id);
      return {
        count: panes.length,
        kind: converted?.image.kind,
        name: converted?.image.name,
        entries: (converted?.entries || []).map(entry => entry.name),
        sourceKind: source?.image.kind,
      };
    }, sourceId);
    assert(result.count === panesBefore + 1, "the conversion opens in a new pane");
    assert(result.kind === "adfs" && result.name.endsWith(".adm"), `converted image is ADFS M: ${result.name}`);
    assert(result.entries.includes("HELLO"), `the file was converted: ${result.entries}`);
    assert(result.sourceKind === "dfs", "the source pane is unchanged");
    console.log("Filesystem conversion browser regression passed");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
