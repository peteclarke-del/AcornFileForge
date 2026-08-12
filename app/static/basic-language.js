(function initialiseAcornBasicLanguage(globalObject) {
  "use strict";

  const KEYWORDS = new Set((
    "AND DIV EOR MOD OR ERROR LINE OFF STEP SPC TAB ELSE THEN OPENIN PTR PAGE TIME "
    + "LOMEM HIMEM ABS ACS ADVAL ASC ASN ATN BGET COS COUNT DEG ERL ERR EVAL EXP EXT "
    + "FALSE FN GET INKEY INSTR INT LEN LN LOG NOT OPENUP OPENOUT PI POINT POS RAD RND "
    + "SGN SIN SQR TAN TO TRUE USR VAL VPOS CHR$ GET$ INKEY$ LEFT$ MID$ RIGHT$ STR$ "
    + "STRING$ EOF AUTO DELETE LOAD LIST NEW OLD RENUMBER SAVE EDIT BPUT CALL CHAIN CLEAR "
    + "CLOSE CLG CLS DATA DEF DIM DRAW END ENDPROC ENDIF ENDCASE ENDWHILE ENVELOPE FOR GCOL "
    + "GOSUB GOTO IF INPUT LET LOCAL MODE MOVE NEXT ON ORIGIN PLOT PRINT PROC READ REM "
    + "REPEAT REPORT RESTORE RETURN RUN SOUND STOP TRACE UNTIL VDU WIDTH OSCLI CASE WHEN "
    + "OTHERWISE WHILE"
  ).split(/\s+/));

  const DIALECTS = Object.freeze({
    "BBC BASIC I": { id: "basic-i", generation: 1, structured: false, inlineAssembler: true, processor: "6502" },
    "BBC BASIC II": { id: "basic-ii", generation: 2, structured: false, inlineAssembler: true, processor: "6502" },
    "BBC BASIC III": { id: "basic-iii", generation: 3, structured: false, inlineAssembler: true, processor: "6502" },
    "BBC BASIC IV": { id: "basic-iv", generation: 4, structured: true, inlineAssembler: true, processor: "6502/65C02" },
    "BBC BASIC V": { id: "basic-v", generation: 5, structured: true, inlineAssembler: true, processor: "ARM" },
    "BBC BASIC VI": { id: "basic-vi", generation: 6, structured: true, inlineAssembler: true, processor: "ARM with floating point" },
  });

  const KEYWORD_GENERATION = Object.freeze({
    CASE: 5, WHEN: 5, OTHERWISE: 5, ENDCASE: 5,
    WHILE: 5, ENDWHILE: 5, ENDIF: 5,
  });

  const identifierPattern = /^[A-Za-z][A-Za-z0-9_]*(?:[$%])?/;
  const compactKeywordBoundary = character => !character || !/[$%]/.test(character);
  const normaliseKeyword = value => String(value || "").toUpperCase();

  function isTypedIdentifier(value) {
    return /[$%]$/.test(String(value || ""));
  }

  function isKeywordToken(value) {
    const raw = String(value || "");
    return !isTypedIdentifier(raw) && KEYWORDS.has(normaliseKeyword(raw));
  }

  function keywordPrefix(value, candidates) {
    const source = String(value || "");
    const upper = source.toUpperCase();
    return [...candidates]
      .sort((left, right) => right.length - left.length)
      .find(candidate => upper.startsWith(candidate) && compactKeywordBoundary(source[candidate.length])) || "";
  }

  function lexemeAt(value) {
    const source = String(value || "");
    const identifier = source.match(identifierPattern)?.[0] || "";
    if (!identifier) return "";
    const upper = normaliseKeyword(identifier);
    if (KEYWORDS.has(upper)) return identifier;
    const suffix = /[$%]$/.test(identifier) ? identifier.at(-1) : "";
    const base = suffix ? upper.slice(0, -1) : upper;
    // PAGE%, PRINT% and similar names are variables, not compact spellings of
    // the corresponding command. PROCname and FNname are likewise indivisible
    // user symbols. Other joined forms follow BBC BASIC's token grammar, so
    // MODE6, IFI, LENA$ and T%DIV256 expose their leading keyword first.
    if ((suffix && KEYWORDS.has(base)) || /^(?:PROC|FN).+/i.test(identifier)) return identifier;
    const prefix = keywordPrefix(identifier, KEYWORDS);
    return prefix ? identifier.slice(0, prefix.length) : identifier;
  }

  function scanLine(line, lineOffset = 0, state = {}) {
    const tokens = [];
    let offset = 0;
    let inlineAssembler = Boolean(state.inlineAssembler);
    const number = String(line).match(/^\s*(\d+)/);
    if (number) {
      const local = number.index + number[0].lastIndexOf(number[1]);
      tokens.push({ type: "line-number", text: number[1], start: lineOffset + local, end: lineOffset + local + number[1].length });
      offset = number[0].length;
    }
    while (offset < line.length) {
      const character = line[offset];
      if (character === '"') {
        let end = offset + 1;
        while (end < line.length) {
          if (line[end] === '"') {
            if (line[end + 1] === '"') { end += 2; continue; }
            end += 1;
            break;
          }
          end += 1;
        }
        tokens.push({ type: "string", text: line.slice(offset, end), start: lineOffset + offset, end: lineOffset + end });
        offset = end;
        continue;
      }
      if (inlineAssembler && character === "\\") {
        tokens.push({ type: "comment", text: line.slice(offset), start: lineOffset + offset, end: lineOffset + line.length });
        break;
      }
      if (character === "[") inlineAssembler = true;
      if (character === "]") inlineAssembler = false;
      if (character === "*" && /^[A-Za-z]/.test(line[offset + 1] || "")) {
        const command = line.slice(offset + 1).match(identifierPattern)?.[0] || "";
        const text = `*${command}`;
        tokens.push({ type: "star-command", text, name: command.toUpperCase(), start: lineOffset + offset, end: lineOffset + offset + text.length });
        offset += text.length;
        continue;
      }
      const numeric = line.slice(offset).match(/^(?:&[0-9A-Fa-f]+|\d+(?:\.\d+)?)/)?.[0];
      if (numeric) {
        tokens.push({ type: "number", text: numeric, start: lineOffset + offset, end: lineOffset + offset + numeric.length });
        offset += numeric.length;
        continue;
      }
      const identifier = lexemeAt(line.slice(offset));
      if (identifier) {
        const keyword = !inlineAssembler && isKeywordToken(identifier);
        const type = keyword ? "keyword" : "identifier";
        tokens.push({ type, text: identifier, name: identifier.toUpperCase(), start: lineOffset + offset, end: lineOffset + offset + identifier.length });
        offset += identifier.length;
        if (keyword && identifier.toUpperCase() === "REM") {
          if (offset < line.length) tokens.push({ type: "comment", text: line.slice(offset), start: lineOffset + offset, end: lineOffset + line.length });
          break;
        }
        continue;
      }
      offset += 1;
    }
    return { tokens, inlineAssembler };
  }

  function scan(source) {
    const tokens = [];
    let lineOffset = 0;
    let inlineAssembler = false;
    const lines = String(source || "").split("\n");
    lines.forEach((line, index) => {
      const result = scanLine(line, lineOffset, { inlineAssembler });
      tokens.push(...result.tokens.map(token => ({ ...token, line: index + 1 })));
      inlineAssembler = result.inlineAssembler;
      lineOffset += line.length + 1;
    });
    return tokens;
  }

  function splitStatements(body) {
    const source = String(body || "");
    const statements = [];
    let start = 0;
    let quoted = false;
    let assembler = false;
    for (let index = 0; index < source.length; index += 1) {
      const character = source[index];
      if (character === '"') {
        if (quoted && source[index + 1] === '"') { index += 1; continue; }
        quoted = !quoted;
        continue;
      }
      if (quoted) continue;
      if (character === "[") assembler = true;
      if (character === "]") assembler = false;
      if (assembler && character === "\\") break;
      const remainder = source.slice(index);
      if (!assembler && /^REM(?![$%])/i.test(remainder) && (index === 0 || /[^A-Za-z0-9_$%]/.test(source[index - 1]))) break;
      if (!assembler && character === "*" && !source.slice(start, index).trim()) break;
      if (!assembler && character === ":") {
        statements.push({ text: source.slice(start, index).trim(), start, end: index });
        start = index + 1;
      }
    }
    statements.push({ text: source.slice(start).trim(), start, end: source.length });
    return statements.filter(statement => statement.text);
  }

  function maskStringsAndComments(source) {
    const value = String(source || "");
    const mask = [...value];
    let quoted = false;
    for (let index = 0; index < value.length; index += 1) {
      if (value[index] === "\n") { quoted = false; continue; }
      if (value[index] === '"') {
        mask[index] = " ";
        if (quoted && value[index + 1] === '"') { mask[index + 1] = " "; index += 1; continue; }
        quoted = !quoted;
        continue;
      }
      if (quoted) { mask[index] = " "; continue; }
      if (/^REM(?![$%])/i.test(value.slice(index)) && (index === 0 || /[^A-Za-z0-9_$%]/.test(value[index - 1]))) {
        while (index < value.length && value[index] !== "\n") { mask[index] = " "; index += 1; }
        index -= 1;
      }
    }
    return mask.join("");
  }

  function dialectProfile(name) {
    return DIALECTS[name] || DIALECTS["BBC BASIC II"];
  }

  const api = Object.freeze({
    DIALECTS,
    KEYWORDS,
    KEYWORD_GENERATION,
    compactKeywordBoundary,
    dialectProfile,
    isKeywordToken,
    isTypedIdentifier,
    keywordPrefix,
    lexemeAt,
    maskStringsAndComments,
    scan,
    scanLine,
    splitStatements,
  });

  globalObject.AcornBasicLanguage = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
