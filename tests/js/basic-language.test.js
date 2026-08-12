"use strict";

const assert = require("node:assert/strict");
const basic = require("../../app/static/basic-language.js");

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

test("typed variables that resemble commands remain identifiers", () => {
  const names = ["page%", "print%", "load%", "if%", "then%", "else%", "rem%", "goto%", "run%", "for%", "next%", "repeat%", "case%", "while%", "end%"];
  const tokens = basic.scan(`10 ${names.map((name, index) => `${name}=${index}`).join(":")}`);
  assert.deepEqual(tokens.filter(token => token.type === "identifier").map(token => token.text), names);
  assert.equal(tokens.some(token => token.type === "keyword"), false);
  assert.equal(tokens.some(token => token.type === "comment"), false);
});

test("real commands beside typed variables retain keyword identity", () => {
  const tokens = basic.scan('10 page%=1:if page%=1 then print "OK"');
  assert.deepEqual(tokens.filter(token => token.type === "keyword").map(token => token.name), ["IF", "THEN", "PRINT"]);
  assert.deepEqual(tokens.filter(token => token.type === "identifier").map(token => token.text), ["page%", "page%"]);
});

test("star commands retain their leading star and do not become BASIC commands", () => {
  const tokens = basic.scan('10 LOAD "PROGRAM":*LOAD CODE 3000');
  assert.equal(tokens.find(token => token.type === "keyword")?.text, "LOAD");
  assert.deepEqual(tokens.filter(token => token.type === "star-command").map(token => token.text), ["*LOAD"]);
});

test("statement splitting respects strings comments star commands and assembler", () => {
  assert.deepEqual(basic.splitStatements('A=1:PRINT "A:B":REM C:D').map(row => row.text), ["A=1", 'PRINT "A:B"', "REM C:D"]);
  assert.deepEqual(basic.splitStatements('*FX 21:PRINT "NOT EXECUTED HERE"').map(row => row.text), ['*FX 21:PRINT "NOT EXECUTED HERE"']);
  assert.deepEqual(basic.splitStatements('[OPT 2:LDA#1:RTS]:PRINT "DONE"').map(row => row.text), ['[OPT 2:LDA#1:RTS]', 'PRINT "DONE"']);
});

test("masking leaves executable code positions stable", () => {
  const source = '10 PRINT "GOTO 90":REM GOTO 80\n20 GOTO 10';
  const masked = basic.maskStringsAndComments(source);
  assert.equal(masked.length, source.length);
  assert.equal(masked.includes("GOTO 90"), false);
  assert.equal(masked.includes("GOTO 80"), false);
  assert.equal(masked.includes("GOTO 10"), true);
});

test("dialect profiles are explicit and default conservatively", () => {
  assert.equal(basic.dialectProfile("BBC BASIC V").structured, true);
  assert.equal(basic.dialectProfile("unknown").id, "basic-ii");
});
