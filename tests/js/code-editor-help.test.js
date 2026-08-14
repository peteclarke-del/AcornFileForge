"use strict";

const assert = require("node:assert/strict");

global.window = {
  AcornBasicLanguage: require("../../app/static/basic-language.js"),
  AcornAssemblyLanguage: require("../../app/static/assembly-language.js"),
};
window.AcornCallCatalogue = require("../../app/static/acorn-call-catalogue.js");
require("../../app/static/code-editor.js");

function test(name, callback) {
  try { callback(); process.stdout.write(`ok - ${name}\n`); }
  catch (error) { process.stderr.write(`not ok - ${name}\n${error.stack}\n`); process.exitCode = 1; }
}

test("source help interprets compact star command operands", () => {
  const source = "10 *FX200,3";
  const item = window.AcornCodeEditor.contextHelp(source, "basic", 3, 6, "*FX");
  assert.match(item.notes, /OSBYTE reason 200/);
  assert.match(item.notes, /X=3 \(&03\)/);
  assert.match(item.notes, /normal Escape recognition disabled/);
  assert.match(item.notes, /user memory cleared on BREAK/);
});

test("source help interprets OSCLI FX strings", () => {
  const source = '10 OSCLI"FX 21"';
  const item = window.AcornCodeEditor.contextHelp(source, "basic", 3, 8, "OSCLI");
  assert.match(item.notes, /OSBYTE reason 21/);
  assert.match(item.notes, /keyboard input/);
});

test("source help explains constant VDU and COLOUR operands", () => {
  const vdu = window.AcornCodeEditor.contextHelp("10 VDU14", "basic", 3, 6, "VDU");
  const colour = window.AcornCodeEditor.contextHelp("10 COLOUR129", "basic", 3, 9, "COLOUR");
  assert.match(vdu.notes, /paged scrolling/);
  assert.match(colour.notes, /background colour 1/);
});

test("source help decodes a complete VDU 23 cursor sequence", () => {
  const source = "10 VDU23,1,0;0;0;0;0;";
  const item = window.AcornCodeEditor.contextHelp(source, "basic", 3, 6, "VDU");
  assert.match(item.notes, /VDU 23 subcommand=1 \(&01\): sets text-cursor visibility/);
  assert.match(item.notes, /Emitted bytes: 23 \(&17\), 1 \(&01\), 0 \(&00\)/);
  assert.match(item.notes, /text cursor off/);
});

test("source help expands semicolon values and explains direct CRTC cursor control", () => {
  const source = "10 VDU23;8202;0;0;0;";
  const item = window.AcornCodeEditor.contextHelp(source, "basic", 3, 6, "VDU");
  assert.match(item.notes, /23 \(&17\), 0 \(&00\), 10 \(&0A\), 32 \(&20\)/);
  assert.match(item.notes, /writes a 6845 CRTC register/);
  assert.match(item.notes, /CRTC cursor disabled/);
});

test("source help decodes OSCLI FX parameters", () => {
  const source = '10 OSCLI"FX 14,4"';
  const item = window.AcornCodeEditor.contextHelp(source, "basic", 3, 8, "OSCLI");
  assert.match(item.notes, /X=4 \(&04\): vertical sync \/ start of display field/);
  assert.match(item.notes, /vertical sync/);
});

test("dynamic operands retain general help without invented values", () => {
  const item = window.AcornCodeEditor.contextHelp("10 VDU A%", "basic", 3, 6, "VDU");
  assert.doesNotMatch(item.notes || "", /first VDU byte/);
});

test("inline assembler MOS calls decode immediate register setup", () => {
  const source = "10 [LDA #&83:LDX #1:LDY #2:JSR OSBYTE]";
  const start = source.indexOf("OSBYTE");
  const item = window.AcornCodeEditor.contextHelp(source, "6502", start, start + 6, "OSBYTE");
  assert.match(item.notes, /bottom of user memory/);
  assert.doesNotMatch(item.notes, /additional emitted bytes/);
});

test("inline assembler OSBYTE help interprets proven parameters", () => {
  const source = "10 [LDA #200:LDX #3:LDY #0:JSR OSBYTE]";
  const start = source.indexOf("OSBYTE");
  const item = window.AcornCodeEditor.contextHelp(source, "6502", start, start + 6, "OSBYTE");
  assert.match(item.notes, /normal Escape recognition disabled/);
  assert.match(item.notes, /user memory cleared on BREAK/);
});

test("BASIC V SYS help names recognised RISC OS calls", () => {
  const source = '10 SYS "OS_Write0",message%';
  const start = source.indexOf("SYS");
  const item = window.AcornCodeEditor.contextHelp(source, "basic", start, start + 3, "SYS");
  assert.match(item.notes, /zero-terminated string/);
});

test("help warns when a RISC OS call is outside the configured Electron target", () => {
  const source = '10 SYS "OS_Write0",message%';
  const start = source.indexOf("SYS");
  const item = window.AcornCodeEditor.contextHelp(source, "basic", start, start + 3, "SYS", { machine: "electron", targetHardware: "electron-plus3" });
  assert.match(item.notes, /not the configured Acorn Electron target/);
  assert.match(item.notes, /unexpected behaviour/);
});

test("help confirms calls documented for the configured platform", () => {
  const source = "10 VDU23;8202;0;0;0;";
  const item = window.AcornCodeEditor.contextHelp(source, "basic", 3, 6, "VDU", { machine: "bbc-b", targetHardware: "bbc-master" });
  assert.match(item.notes, /configured BBC Micro target is within the documented platform scope/);
});

test("SOUND and ENVELOPE help decode values found in source", () => {
  const sound = window.AcornCodeEditor.contextHelp("10 SOUND1,-15,52,20", "basic", 3, 8, "SOUND", { machine: "electron" });
  const envelope = window.AcornCodeEditor.contextHelp("10 ENVELOPE1,129,1,-2,3,4,5,6,7,-8,9,-10,11,12", "basic", 3, 11, "ENVELOPE", { machine: "bbc-b" });
  assert.match(sound.notes, /channel=1 .*tone channel 1/);
  assert.match(sound.notes, /amplitude\/envelope=-15 \(&F1\)/);
  assert.match(envelope.notes, /T=129 \(&81\).*pitch phases repeat automatically/);
  assert.match(envelope.notes, /PI2=-2 \(&FE\)/);
});

test("compact PRINT TAB is not mistaken for an undimensioned array", () => {
  const source = `10 MODE6
20 PRINTTAB(0,15)"Insert disk"
30 HIMEM=&72B8
40 DIM names$(10)
50 PRINT names$(0)`;
  const issues = window.AcornCodeEditor.diagnostics(source, "basic", "BBC BASIC II");
  assert.equal(issues.some(issue => /PRINTTAB.*array/i.test(issue.message)), false);
  assert.equal(issues.some(issue => /HIMEM.*assigned/i.test(issue.message)), false);
  assert.equal(issues.some(issue => /names\$.*DIM/i.test(issue.message)), false);
});

test("a genuine array reference without DIM is still reported", () => {
  const issues = window.AcornCodeEditor.diagnostics("10 PRINT scores%(1)", "basic", "BBC BASIC II");
  assert.equal(issues.some(issue => /scores%.*array before a preceding DIM/i.test(issue.message)), true);
});

test("BBC BASIC typed names and implicit system state do not create speculative warnings", () => {
  const source = `10 a$="900":A%=0
20 P%=&900:[OPT 2:RTS:]
30 HIMEM=&72B8`;
  assert.deepEqual(window.AcornCodeEditor.diagnostics(source, "basic", "BBC BASIC II"), []);
});
