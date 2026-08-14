const { chromium } = require("playwright");

const target = process.env.ACORN_FILE_FORGE_URL || "http://127.0.0.1:8666";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.goto(target, { waitUntil: "networkidle" });
    await page.evaluate(() => {
      sessionStorage.removeItem("acorn-file-forge-dynamic-panes");
      sessionStorage.removeItem("acorn-file-forge-editor-documents-v1");
    });
    await page.reload({ waitUntil: "networkidle" });

    const panes = page.locator(".pane");
    if (await panes.count() !== 1) throw new Error("Workspace did not start with one pane");
    await page.locator("#addPaneButton").click();
    await page.locator("#addPaneButton").click();
    if (await panes.count() !== 3) throw new Error("Workspace did not add panes up to its limit");
    if (!await page.locator("#addPaneButton").isDisabled()) throw new Error("Add Pane remained enabled at three panes");

    const third = panes.nth(2);
    await third.locator(".close-empty-pane").click();
    if (await panes.count() !== 2) throw new Error("Closing an empty pane failed");
    if (await page.locator("#addPaneButton").isDisabled()) throw new Error("Add Pane did not re-enable after close");

    console.log("Workspace pane browser regression passed");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
