"use strict";

const assert = require("node:assert/strict");

global.window = {
  AcornBasicLanguage: require("../../app/static/basic-language.js"),
  AcornAssemblyLanguage: require("../../app/static/assembly-language.js"),
};
require("../../app/static/code-editor.js");

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

test("source help interprets compact star command operands", () => {
  const source = "10 *FX200 0";
  const item = window.AcornCodeEditor.contextHelp(source, "basic", 3, 6, "*FX");
  assert.match(item.notes, /OSBYTE reason 200/);
  assert.match(item.notes, /Escape, Break/);
});

test("source help interprets OSCLI FX strings", () => {
  const source = '10 OSCLI"FX 21"';
  const item = window.AcornCodeEditor.contextHelp(source, "basic", 3, 8, "OSCLI");
  assert.match(item.notes, /OSBYTE reason 21/);
  assert.match(item.notes, /keyboard buffer/);
});

test("source help explains constant VDU and COLOUR operands", () => {
  const vdu = window.AcornCodeEditor.contextHelp("10 VDU14", "basic", 3, 6, "VDU");
  const colour = window.AcornCodeEditor.contextHelp("10 COLOUR129", "basic", 3, 9, "COLOUR");
  assert.match(vdu.notes, /paged scrolling/);
  assert.match(colour.notes, /background colour 1/);
});

test("dynamic operands retain general help without invented values", () => {
  const item = window.AcornCodeEditor.contextHelp("10 VDU A%", "basic", 3, 6, "VDU");
  assert.doesNotMatch(item.notes || "", /first VDU byte/);
});
