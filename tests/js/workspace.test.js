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
const help = load("app/static/help.js", "AcornHelp");

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

test("help handbook is isolated behind an injected modal boundary", () => {
  const showHelp = help.create({ showModal() {}, modalContent: {} });
  assert.equal(typeof showHelp, "function");
});
