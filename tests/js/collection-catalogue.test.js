"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const context = vm.createContext({ window: {} });
const source = fs.readFileSync(path.join(__dirname, "../../app/static/collection-catalogue.js"), "utf8");
vm.runInContext(source, context, { filename: "collection-catalogue.js" });
const catalogue = context.window.AcornCollectionCatalogue;

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

const manifest = (name, hash, title) => ({
  image: { id: `session-${name}`, name, kind: "mmb", size: 100 },
  fingerprint: hash.repeat(64),
  revision: `100-${hash}`,
  records: [{ recordType: "slot", slot: 1, formatted: true, diskTitle: title, sha256: hash.repeat(64) }],
  menus: [{ type: "universal", entries: [{ title, publisher: "Acornsoft" }] }],
});

test("collection entries retain deterministic identity and decoded titles", () => {
  const entry = catalogue.catalogueEntry(
    manifest("games.mmb", "a", "Arcadians"),
    { location: "SD card 1", machines: ["BBC B"] },
    null,
    () => "2026-08-17T12:00:00Z",
    () => "entry-1",
  );
  assert.equal(entry.id, "entry-1");
  assert.equal(entry.location, "SD card 1");
  assert.equal(entry.titles[0].key, "arcadians");
  assert.equal(entry.stale, false);
});

test("collection reports span closed-image manifests by hash and title", () => {
  const first = catalogue.catalogueEntry(manifest("one.mmb", "b", "Repton 2"), {}, null, () => "now", () => "one");
  const second = catalogue.catalogueEntry(manifest("two.mmb", "b", "REPTON-2"), {}, null, () => "now", () => "two");
  const report = catalogue.collectionReport([first, second], ["Repton 2", "Elite"]);
  assert.equal(report.exactDuplicates.length, 1);
  assert.equal(report.titleVariants.length, 1);
  assert.deepEqual(Array.from(report.missingTitles), ["Elite"]);
});

test("collection backup validation rejects unversioned input", () => {
  assert.throws(() => catalogue.validateBackup({ images: [] }), /version 1/);
  assert.equal(catalogue.validateBackup({
    format: catalogue.BACKUP_FORMAT,
    version: catalogue.BACKUP_VERSION,
    images: [{ id: "one", records: [], menus: [] }],
  }).images.length, 1);
});
