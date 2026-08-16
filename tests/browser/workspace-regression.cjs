const { chromium } = require("playwright");

const target = process.env.ACORN_FILE_FORGE_URL || "http://127.0.0.1:8666";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  try {
    await page.goto(target, { waitUntil: "networkidle" });
    await page.evaluate(() => {
      localStorage.removeItem("acorn-file-forge-dynamic-panes");
      sessionStorage.removeItem("acorn-file-forge-dynamic-panes");
      sessionStorage.removeItem("acorn-file-forge-editor-documents-v1");
    });
    await page.reload({ waitUntil: "networkidle" });

    const panes = page.locator(".pane");
    if (await panes.count() !== 1) throw new Error("Workspace did not start with one pane");
    for (let count = 0; count < 4; count += 1) await page.locator("#addPaneButton").click();
    if (await panes.count() !== 5) throw new Error("Workspace still limits the number of panes");
    if (await page.locator("#addPaneButton").isDisabled()) throw new Error("Add Pane became disabled");

    const fifth = panes.nth(4);
    const initial = await fifth.boundingBox();
    const handle = fifth.locator(".pane-drag-handle");
    await handle.dragTo(page.locator(".panes"), { targetPosition: { x: 6, y: 6 } });
    const snapped = await fifth.boundingBox();
    const workspace = await page.locator(".panes").boundingBox();
    if (Math.abs(snapped.x - workspace.x) > 3 || Math.abs(snapped.width - workspace.width / 2) > 5) {
      throw new Error("Dragging to a workspace corner did not snap the pane");
    }
    if (initial.width === snapped.width && initial.height === snapped.height) throw new Error("Pane geometry did not change");

    await fifth.locator(".minimize-pane").click();
    if (!await fifth.isHidden()) throw new Error("Minimising a pane did not hide its window");
    const taskButton = page.locator("#paneTaskbar [data-restore-pane='4']");
    if (!await taskButton.isVisible()) throw new Error("Minimised pane was not added to the workspace shelf");
    await taskButton.click();
    if (!await fifth.isVisible()) throw new Error("Pane did not restore from the workspace shelf");

    await panes.nth(0).locator(".pane-drag-handle").focus();
    const firstZ = Number(await panes.nth(0).evaluate(element => getComputedStyle(element).zIndex));
    const fifthZ = Number(await fifth.evaluate(element => getComputedStyle(element).zIndex));
    if (firstZ <= fifthZ) throw new Error(`Selecting a stacked pane did not bring it to the front (${firstZ} <= ${fifthZ})`);

    await fifth.locator(".pane-drag-handle").focus();
    await fifth.locator(".close-empty-pane").click();
    if (await panes.count() !== 4) throw new Error("Closing an empty pane failed");

    await panes.nth(3).locator(".pane-drag-handle").focus();
    await panes.nth(3).locator(".minimize-pane").click();
    await page.reload({ waitUntil: "networkidle" });
    if (await page.locator(".pane").count() !== 4) throw new Error("Workspace window count was not restored");
    if (await page.locator(".pane").nth(3).isVisible()) throw new Error("Minimised state was not restored");
    await page.locator("#paneTaskbar [data-restore-pane='3']").click();
    console.log("Workspace window browser regression passed");
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
