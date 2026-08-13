(function initialiseAcornAssemblyLanguage(globalObject) {
  "use strict";

  const NMOS_6502 = (
    "ADC AND ASL BCC BCS BEQ BIT BMI BNE BPL BRK BVC BVS CLC CLD CLI CLV CMP "
    + "CPX CPY DEC DEX DEY EOR INC INX INY JMP JSR LDA LDX LDY LSR NOP ORA "
    + "PHA PHP PLA PLP ROL ROR RTI RTS SBC SEC SED SEI STA STX STY TAX TAY "
    + "TSX TXA TXS TYA"
  ).split(/\s+/);
  const CMOS_65C02_CORE_ADDITIONS = "BRA DEA INA PHX PHY PLX PLY STP STZ TRB TSB WAI".split(/\s+/);
  const CMOS_65C02_BIT_ADDITIONS = (
    "RMB0 RMB1 RMB2 RMB3 RMB4 RMB5 RMB6 RMB7 SMB0 SMB1 SMB2 SMB3 SMB4 SMB5 SMB6 SMB7 BBR0 BBR1 BBR2 "
    + "BBR3 BBR4 BBR5 BBR6 BBR7 BBS0 BBS1 BBS2 BBS3 BBS4 BBS5 BBS6 BBS7"
  ).split(/\s+/);
  const WDC_65816_ADDITIONS = (
    "BRL COP JML JSL MVN MVP PEA PEI PER PHB PHD PHK PLB PLD REP RTL SEP TCD "
    + "TCS TDC TSC TXY TYX WDM XBA XCE"
  ).split(/\s+/);
  const ARM = (
    "ADC ADD ADR AND ASR B BIC BL BX CMN CMP EOR LDM LDR MLA MOV MUL MVN ORR "
    + "RSB RSC SBC STM STR SUB SWI TEQ TST"
  ).split(/\s+/);
  const M68K = (
    "ABCD ADD ADDA ADDI ADDQ ADDX AND ANDI ASL ASR BCC BCHG BCLR BRA BSET BSR "
    + "BTST CHK CLR CMP CMPA CMPI CMPM DBCC DIVS DIVU EOR EXG EXT JMP JSR LEA "
    + "LINK LSL LSR MOVE MOVEA MOVEM MOVEP MOVEQ MULS MULU NBCD NEG NEGX NOP "
    + "NOT OR ORI PEA RESET ROL ROR ROXL ROXR RTE RTR RTS SBCD SCC STOP SUB "
    + "SUBA SUBI SUBQ SUBX SWAP TAS TRAP TRAPV TST UNLK"
  ).split(/\s+/);

  const unique = values => Object.freeze([...new Set(values)]);
  const CATALOGUES = Object.freeze({
    "6502": unique(NMOS_6502),
    "65c02": unique([...NMOS_6502, ...CMOS_65C02_CORE_ADDITIONS, ...CMOS_65C02_BIT_ADDITIONS]),
    // WDC explicitly excludes the BBR/BBS/RMB/SMB family from W65C816S.
    "65816": unique([...NMOS_6502, ...CMOS_65C02_CORE_ADDITIONS, ...WDC_65816_ADDITIONS]),
    arm: unique(ARM),
    m68k: unique(M68K),
  });
  const SETS = Object.freeze(Object.fromEntries(Object.entries(CATALOGUES).map(([key, values]) => [key, new Set(values)])));
  const mnemonicsFor = architecture => SETS[String(architecture || "6502").toLowerCase()] || SETS["6502"];
  const isMnemonic = (architecture, mnemonic) => mnemonicsFor(architecture).has(String(mnemonic || "").toUpperCase());

  const api = Object.freeze({ CATALOGUES, NMOS_6502, CMOS_65C02_CORE_ADDITIONS, CMOS_65C02_BIT_ADDITIONS, WDC_65816_ADDITIONS, mnemonicsFor, isMnemonic });
  globalObject.AcornAssemblyLanguage = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
