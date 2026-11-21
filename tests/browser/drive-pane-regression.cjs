// Drive panes in a real browser: open, ask, format and write-back decisions.
//
// The service supplies the page. /api/health is answered as the Linux desktop
// host so the drive controls appear, and the drive routes are answered here,
// so each state a disk can be in is shown without a Greaseweazle attached.
// Every request to a drive route is recorded, which is how the test proves
// that nothing writes until the user asks.
const { chromium } = require("playwright");

const target = process.env.ACORN_FILE_FORGE_URL || "http://127.0.0.1:8666";
const FORMATS = [
  { id: "dfs-80", label: "DFS 80 track, single sided", suffix: ".ssd", size: 204800, fortyTrack: false },
  { id: "adfs-l", label: "ADFS L, 640 KiB", suffix: ".adl", size: 655360, fortyTrack: false },
];

const binding = unwritten => ({
  drive: "A",
  format: FORMATS[1],
  step: 1,
  missingSectors: 0,
  unwritten,
});

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const calls = [];
  let detection = { status: "unformatted", format: null, step: null, detail: "No sector headers were found.", candidates: [] };

  await page.route("**/api/health", async route => {
    const response = await route.fetch();
    const body = await response.json();
    body.platform = { ...(body.platform || {}), host: "desktop", hostCapabilities: ["physical-floppy-read", "physical-floppy-write"] };
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/desktop/client-state", route => route.fulfill({ json: {} }));
  // The drive routes create a real blank image on the service, so the pane
  // behaves exactly as it would after a real read. Every later response about
  // that image then carries the drive binding the desktop host would add.
  let driveImageId = null;
  let unwritten = false;
  async function createImage(request) {
    const response = await request.post(`${target}/api/images/create`, { data: { format: "adfs-l", title: "Blank" } });
    const { image } = await response.json();
    driveImageId = image.id;
    unwritten = false;
    return { ...image, physicalDrive: binding(false) };
  }
  await page.route("**/api/desktop/drive/**", async route => {
    const url = new URL(route.request().url()).pathname;
    calls.push({ url, body: route.request().postDataJSON() });
    if (url.endsWith("/probe")) return route.fulfill({ json: { detection, formats: FORMATS } });
    if (url.endsWith("/format") || url.endsWith("/open")) {
      return route.fulfill({ json: { image: await createImage(page.request) } });
    }
    return route.fulfill({ status: 404, json: { error: "unexpected" } });
  });
  await page.route("**/api/desktop/images/*/drive/write", async route => {
    calls.push({ url: "write", body: route.request().postDataJSON() });
    unwritten = false;
    const response = await page.request.get(`${target}/api/images/${driveImageId}`);
    const { image } = await response.json();
    await route.fulfill({ json: { result: { verified: true, tracksWritten: 160 }, image: { ...image, physicalDrive: binding(false) } } });
  });
  await page.route("**/api/images/**", async route => {
    const response = await route.fetch();
    const type = response.headers()["content-type"] || "";
    if (!driveImageId || !type.includes("json")) return route.fulfill({ response });
    const body = await response.json();
    if (body?.image?.id === driveImageId) body.image.physicalDrive = binding(unwritten);
    await route.fulfill({ response, json: body });
  });

  await page.goto(target);
  const openButton = page.locator(".pane-drive").first();
  await openButton.waitFor({ state: "visible" });

  // A blank disk: the user is asked, and declining writes nothing.
  await openButton.click();
  await page.locator('#modalContent button[value="probe"]').click();
  await page.waitForSelector("#modalContent h2:has-text('Format this disk?')");
  await page.locator('#modalContent button[value="cancel"]').click();
  assert(!calls.some(call => call.url.endsWith("/format")), "declining format must not format");

  // Accepting needs the confirmation box ticked.
  await openButton.click();
  await page.locator('#modalContent button[value="probe"]').click();
  await page.waitForSelector("#modalContent h2:has-text('Format this disk?')");
  await page.locator('#modalContent select[name="format"]').selectOption("adfs-l");
  await page.locator('#modalContent button[value="format"]').click();
  assert(!calls.some(call => call.url.endsWith("/format")), "format must wait for confirmation");
  await page.locator('#modalContent input[name="confirmed"]').check();
  await page.locator('#modalContent button[value="format"]').click();
  await page.waitForSelector(".drive-badge");
  const formatCall = calls.find(call => call.url.endsWith("/format"));
  assert(formatCall.body.confirm === true && formatCall.body.format === "adfs-l", "format sends the confirmed layout");

  // The pane shows it matches the disk, and writes only when asked.
  assert((await page.locator(".drive-badge").first().textContent()).includes("Matches the disk"), "fresh pane matches disk");
  assert(!calls.some(call => call.url === "write"), "nothing written before Write to disk");
  await page.locator(".drive-write").first().click();
  await page.waitForSelector("#modalContent h2:has-text('Write to the disk in drive A?')");
  await page.locator('#modalContent button[value="cancel"]').click();
  assert(!calls.some(call => call.url === "write"), "cancelling the write dialog writes nothing");
  await page.locator(".drive-write").first().click();
  await page.locator('#modalContent button[value="write"]').click();
  await page.waitForFunction(() => !document.querySelector("#modal").open);
  assert(calls.filter(call => call.url === "write").length === 1, "one write after confirming");

  // An unrecognised disk asks for the format and reads with the choice.
  await page.locator(".file-tools > summary").first().click();
  detection = { status: "unrecognised", format: null, step: null, detail: "Sectors were found.", candidates: ["dfs-80", "adfs-l"] };
  await page.locator(".menu-open-drive").first().click();
  await page.locator('#modalContent button[value="probe"]').click();
  await page.waitForSelector("#modalContent h2:has-text('Which format is this disk?')");
  await page.locator('#modalContent select[name="format"]').selectOption("dfs-80");
  await page.locator('#modalContent button[value="read"]').click();
  await page.waitForFunction(() => !document.querySelector("#modal").open);
  const openCall = calls.filter(call => call.url.endsWith("/open")).pop();
  assert(openCall && openCall.body.format === "dfs-80", "the chosen format is read");

  await browser.close();
  console.log("drive pane regression passed");
})().catch(error => {
  console.error(error);
  process.exit(1);
});
