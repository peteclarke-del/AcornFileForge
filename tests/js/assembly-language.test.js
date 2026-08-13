"use strict";

const assert = require("node:assert/strict");
const assembly = require("../../app/static/assembly-language.js");

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

test("NMOS 6502 catalogue contains every official mnemonic exactly once", () => {
  assert.equal(assembly.CATALOGUES["6502"].length, 56);
  assert.equal(new Set(assembly.CATALOGUES["6502"]).size, 56);
  for (const mnemonic of ["ADC", "BRK", "JSR", "LDA", "RTI", "STY", "TYA"]) assert.ok(assembly.isMnemonic("6502", mnemonic));
});

test("processor variants inherit only applicable mnemonic sets", () => {
  assert.ok(assembly.isMnemonic("65c02", "STZ"));
  assert.ok(assembly.isMnemonic("65816", "STZ"));
  assert.ok(assembly.isMnemonic("65816", "JSL"));
  assert.equal(assembly.isMnemonic("6502", "STZ"), false);
  assert.equal(assembly.isMnemonic("65c02", "JSL"), false);
  assert.equal(assembly.isMnemonic("65816", "BBR0"), false);
});
