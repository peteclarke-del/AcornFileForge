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

test("compact loader syntax exposes every embedded BASIC keyword", () => {
  const source = `10 MODE6:VDU23;8202;0;0;0;:OSCLI"LOAD "+$&9F0+" 2200"
20 MODE3:VDU23;8202;0;0;0;:*LOAD CODE8
30 T%=&2200:?&70=T%MOD256:?&71=T%DIV256:VDU14
40 IF ?&70<>126 PRINT'STRING$(76,CHR$(45))':CALL&900:VDU15
50 PRINT'STRING$(76,CHR$(45))''SPC(15)"PRESS";:OSCLI"FX 21":I=GET
60 IFI=80 OR I=112 THEN OSCLI"FX 5 1":VDU2:GOTO50
70 CHAIN"HAVEN"`;
  const names = basic.scan(source).filter(token => token.type === "keyword").map(token => token.name);
  for (const keyword of ["MODE", "VDU", "MOD", "DIV", "IF", "OR", "THEN", "GOTO", "CHAIN"]) {
    assert.ok(names.includes(keyword), `${keyword} was not recognised in compact source`);
  }
  assert.equal(names.filter(name => name === "IF").length, 2);
});

test("compact commands remain distinct from typed command-like variables", () => {
  const tokens = basic.scan("10 page%=1:print%=2:IFI=80:IFLENA$>0 PRINTA$");
  assert.deepEqual(tokens.filter(token => token.type === "identifier").map(token => token.text), ["page%", "print%", "I", "A$", "A$"]);
  assert.deepEqual(tokens.filter(token => token.type === "keyword").map(token => token.name), ["IF", "IF", "LEN", "PRINT"]);
});

test("compact IF branches recognise COLOUR and their following commands", () => {
  const source = `570 IFcheck$="+" THEN text%=1
580 IFf$="$.CHEAT" THEN COLOUR129:COLOUR0:CLS:CHAINf$
590 IFtext%=0 THEN MODE6:VDU23;8202;0;0;0;:CHAINf$`;
  const names = basic.scan(source).filter(token => token.type === "keyword").map(token => token.name);
  assert.deepEqual(names, ["IF", "THEN", "IF", "THEN", "COLOUR", "COLOUR", "CLS", "CHAIN", "IF", "THEN", "MODE", "VDU", "CHAIN"]);
});

test("every BBC BASIC II token-table keyword is recognised", () => {
  for (const keyword of basic.BBC_BASIC_II_KEYWORDS) {
    const token = basic.scan(`10 ${keyword}`).find(item => item.start > 2);
    assert.equal(token?.type, "keyword", `${keyword} was not recognised as a BASIC keyword`);
    assert.equal(token?.name, keyword, `${keyword} was recognised under the wrong name`);
  }
});

test("conditional keyword prefixes do not split ordinary identifiers", () => {
  const names = basic.scan("10 ending%=2:page%=3:countdown%=4").filter(token => token.type === "identifier").map(token => token.text);
  assert.deepEqual(names, ["ending%", "page%", "countdown%"]);
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
