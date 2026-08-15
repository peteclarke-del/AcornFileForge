"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function load(relativePath, exportName) {
  const context = vm.createContext({ window: {} });
  const source = fs.readFileSync(path.join(__dirname, "../..", relativePath), "utf8");
  vm.runInContext(source, context, { filename: relativePath });
  return context.window[exportName];
}

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

const workspace = load("app/static/workspace.js", "AcornWorkspace");
const visuals = load("app/static/file-visuals.js", "AcornFileVisuals");
const imports = load("app/static/import-planning.js", "AcornImportPlanning");
const metadata = load("app/static/acorn-metadata.js", "AcornMetadata");
const help = load("app/static/help.js", "AcornHelp");
const editorWorkspace = load("app/static/editor-workspace.js", "AcornEditorWorkspace");
const identifiers = load("app/static/identifiers.js", "AcornIdentifiers");
const operationUI = load("app/static/operation-ui.js", "AcornOperationUI");
const workspacePersistence = load("app/static/workspace-persistence.js", "AcornWorkspacePersistence");
const paneView = load("app/static/pane-view.js", "AcornPaneView");
const transferPlanning = load("app/static/transfer-planning.js", "AcornTransferPlanning");

test("workspace pane state has one canonical initial shape", () => {
  const pane = workspace.newPaneState({ kind: "mmb", doubleSided: false });
  assert.equal(pane.path, "$");
  assert.equal(pane.menuDetectionPending, true);
  assert.deepEqual(Array.from(pane.selection), []);
});

test("workspace selection helpers preserve unique stable keys", () => {
  const pane = workspace.newPaneState();
  workspace.setSelection(pane, ["3", "3", "4"]);
  assert.deepEqual(Array.from(workspace.selectionKeys(pane)), ["3", "4"]);
  assert.equal(pane.selected, null);
});

test("file visuals classify Acorn content consistently before rendering", () => {
  const pane = workspace.newPaneState({ kind: "dfs" });
  assert.equal(visuals.entryIcon(pane, { name: "!BOOT" }, "file", false, false).kind, "script");
  assert.equal(visuals.entryIcon(pane, { name: "GAME", filetype: "FFB" }, "file", false, false).kind, "basic");
  assert.equal(visuals.entryIcon(pane, { name: "FILES.ZIP" }, "file", true, false).kind, "archive");
});

test("import planning applies filesystem limits without UI state", () => {
  const dfsRule = imports.targetNameRule({ image: { kind: "dfs" } }, "LONG.NAME");
  assert.equal(dfsRule.suggested, "LONG_NA");
  assert.equal(dfsRule.limit, 7);
  const disks = imports.allocateFilesToDfsDisks([
    { name: "ONE", length: 100 },
    { name: "TWO", length: 798 * 256 },
  ], "ssd");
  assert.equal(disks.length, 2);
});

test("host metadata parsing preserves Acorn load and execution addresses", () => {
  assert.deepEqual(
    { ...imports.metadataFromHostFilename("PROGRAM,1900-8023") },
    { targetName: "PROGRAM", load: "0x1900", execute: "0x8023" },
  );
});

test("catalogue metadata presents every address as a full Acorn word", () => {
  assert.deepEqual(
    { ...metadata.entryAddresses({ load: "FFFF1900", exec: 0x8023 }) },
    {
      available: true,
      load: 0xFFFF1900,
      execute: 0x8023,
      loadDisplay: "&FFFF1900",
      executeDisplay: "&00008023",
    },
  );
  assert.equal(metadata.entryAddresses({ name: "README" }).available, false);
  assert.equal(metadata.isRiscOsEncoded({ load: 0xFFF12300, exec: 0 }), false);
  assert.equal(metadata.isRiscOsEncoded({ load: 0xFFF12300, exec: 0 }, true), true);
});

test("help handbook is isolated behind an injected modal boundary", () => {
  const showHelp = help.create({ showModal() {}, modalContent: {} });
  assert.equal(typeof showHelp, "function");
});

test("editor workspace persistence validates, limits and restores documents", () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  const manager = editorWorkspace.create({ storage, key: "editors", maxDocuments: 2, maxDraftBytes: 4, maxPanes: 3 });
  manager.state.documents.set("one", { key: "one", imageId: "a".repeat(32), index: 0, path: "$.ONE", name: "ONE", draft: "123456" });
  manager.state.documents.set("two", { key: "two", imageId: "b".repeat(32), index: 1, path: "$.TWO", name: "TWO" });
  manager.state.active = "one";
  manager.persist();

  const restored = editorWorkspace.create({ storage, key: "editors", maxDocuments: 2, maxDraftBytes: 4, maxPanes: 3 });
  restored.restore();
  assert.equal(restored.state.documents.get("one").draft, "1234");
  assert.equal(restored.state.restoreCandidate, "one");
});

test("operation lifecycle is isolated behind an injected pane controller", () => {
  const controller = operationUI.create({
    panes: [], api() {}, setLoading() {}, renderPane() {},
    modal: { open: false }, setModalAbort() {}, setModalProgress() {},
    newUuid: () => "00000000-0000-4000-8000-000000000000",
  });
  assert.equal(typeof controller.guardedPaneAction, "function");
  assert.equal(typeof controller.trackedPaneOperation, "function");
});

test("operation identifiers use the browser UUID implementation when available", () => {
  assert.equal(identifiers.newUuid({ randomUUID: () => "native-uuid" }), "native-uuid");
});

test("operation identifiers remain available on non-secure HTTP origins", () => {
  const cryptoSource = {
    getRandomValues(bytes) {
      bytes.fill(0);
      return bytes;
    },
  };
  assert.equal(identifiers.newUuid(cryptoSource), "00000000-0000-4000-8000-000000000000");
});

test("operation identifiers fail explicitly on obsolete browsers without Web Crypto", () => {
  assert.throws(
    () => identifiers.newUuid({}),
    /cannot create secure operation identifiers/i,
  );
});

test("workspace recovery is isolated behind an injected persistence controller", () => {
  const controller = workspacePersistence.create({
    panes: [], storage: { getItem() { return null; }, setItem() {} },
    storageKey: "workspace", maxPanes: 3, newPaneState() { return {}; },
    restoredDfsPath() { return "$"; }, api() {}, rebuildPaneHosts() {},
    renderPane() {}, acceptImage() {}, loadDirectory() {},
    editorWorkspace: { state: {} }, activateEditorDocument() {}, toast() {},
  });
  assert.equal(typeof controller.remember, "function");
  assert.equal(typeof controller.restore, "function");
  assert.deepEqual(Array.from(controller.stored()), []);
});

test("pane presentation formats images and capacity through one component", () => {
  const view = paneView.create({
    esc: value => String(value),
    humanSize: value => `${value} B`,
  });
  assert.equal(view.paneFormat({ kind: "dfs", name: "demo.dsd" }), "DSD");
  assert.match(view.capacityMarkup({ available: true, total: 100, used: 75, free: 25, unit: "bytes" }), /capacity warning/);
  assert.match(view.crumbs("$.Games"), /data-path="\$"/);
});

test("folder transfer planning preserves ADFS trees and resolves collisions", () => {
  const planning = transferPlanning.create({
    targetNameRule: (_pane, name) => ({ suggested: name.slice(0, 10), limit: 10 }),
  });
  const result = planning.folderTargetPlans(
    { image: { kind: "adfs" } },
    [{ relativePath: "Pack/LongFilename" }, { relativePath: "Pack/LongFilename2" }],
    "preserve",
  );
  assert.deepEqual(Array.from(result.plans, item => item.targetPath), ["Pack/LongFilena", "Pack/LongFilen1"]);
});
