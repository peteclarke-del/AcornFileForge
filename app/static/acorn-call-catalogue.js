window.AcornCallCatalogue = (() => {
  const EVENTS = Object.freeze({
    0: "output buffer empty", 1: "input buffer full", 2: "character entering an input buffer",
    3: "ADC conversion complete", 4: "vertical sync / start of display field",
    5: "interval timer crossing zero", 6: "Escape detected", 7: "RS423 receive error",
    8: "Econet network error", 9: "user event",
  });
  const BUFFERS = Object.freeze({
    0: "keyboard input", 1: "RS423 input", 2: "RS423 output", 3: "printer output",
    4: "sound channel 0", 5: "sound channel 1", 6: "sound channel 2",
    7: "sound channel 3", 8: "speech output",
  });
  const BAUD_RATES = Object.freeze({
    0: "9600 baud", 1: "75 baud", 2: "150 baud", 3: "300 baud", 4: "1200 baud",
    5: "2400 baud", 6: "4800 baud", 7: "9600 baud", 8: "19200 baud",
  });

  const OSBYTE = Object.freeze({
    0: { summary: "identifies the operating-system version", parameters: [{ name: "X", values: { 0: "raise a BRK carrying the OS version text" }, otherwise: "return the OS type in X instead of raising BRK" }] },
    1: { summary: "reads or changes the application user flag", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask; use 0 to replace or 255 to read" }] },
    2: { summary: "selects the input stream", parameters: [{ name: "X", values: { 0: "keyboard input; RS423 disabled", 1: "RS423 input; RS423 enabled", 2: "keyboard input; RS423 enabled" } }] },
    3: { summary: "selects output streams", parameters: [{ name: "X", bits: [
      { mask: 1, set: "RS423 output enabled", clear: "RS423 output disabled" },
      { mask: 2, set: "VDU output disabled", clear: "VDU output enabled" },
      { mask: 4, set: "printer output disabled", clear: "printer output follows its normal selection" },
      { mask: 8, set: "printer output forced on", clear: "printer output is not forced" },
      { mask: 16, set: "spooled output disabled", clear: "spooled output enabled when a spool file is open" },
      { mask: 64, set: "printer accepts only bytes preceded by VDU 1", clear: "printer uses normal routing" },
    ] }] },
    4: { summary: "sets cursor-key editing behaviour", parameters: [{ name: "X", values: { 0: "cursor keys edit the current line", 1: "cursor keys return character codes", 2: "cursor keys edit inside fields", 3: "cursor keys return codes inside fields" } }] },
    5: { summary: "selects the printer destination", parameters: [{ name: "X", values: { 0: "parallel printer", 1: "serial printer", 2: "user printer routine", 3: "network printer", 4: "user printer routine" }, otherwise: "machine- or ROM-specific printer destination" }] },
    6: { summary: "sets the character ignored by the printer driver", parameters: [{ name: "X", type: "character" }] },
    7: { summary: "sets the RS423 receive baud rate", platforms: ["bbc", "master"], requires: "RS423 hardware", parameters: [{ name: "X", values: BAUD_RATES }] },
    8: { summary: "sets the RS423 transmit baud rate", platforms: ["bbc", "master"], requires: "RS423 hardware", parameters: [{ name: "X", values: BAUD_RATES }] },
    9: { summary: "sets the first flashing-colour period", parameters: [{ name: "X", unit: "fiftieth-of-a-second", meaning: "mark period" }] },
    10: { summary: "sets the second flashing-colour period", parameters: [{ name: "X", unit: "fiftieth-of-a-second", meaning: "space period" }] },
    11: { summary: "sets the keyboard auto-repeat delay", parameters: [{ name: "X", unit: "centisecond", meaning: "delay before repetition starts" }] },
    12: { summary: "sets the keyboard auto-repeat rate", parameters: [{ name: "X", unit: "centisecond", meaning: "interval between repeated characters" }] },
    13: { summary: "disables a MOS event", parameters: [{ name: "X", values: EVENTS, meaning: "event number" }] },
    14: { summary: "enables a MOS event", parameters: [{ name: "X", values: EVENTS, meaning: "event number" }] },
    15: { summary: "flushes a class of buffers", parameters: [{ name: "X", values: { 0: "flush every buffer" }, otherwise: "flush input buffers only" }] },
    16: { summary: "selects how many ADC channels are sampled", parameters: [{ name: "X", range: [0, 4], meaning: "sampled channel count; 0 disables sampling" }] },
    17: { summary: "forces an ADC conversion", parameters: [{ name: "X", range: [0, 4], meaning: "ADC channel" }] },
    18: { summary: "clears all soft-key definitions", parameters: [] },
    19: { summary: "waits for the next vertical-sync / display-field boundary", parameters: [] },
    20: { summary: "changes the amount of RAM reserved for user-defined characters", parameters: [{ name: "X", range: [0, 6], meaning: "number of additional 32-character groups" }] },
    21: { summary: "flushes one specific buffer", parameters: [{ name: "X", values: BUFFERS, meaning: "buffer number" }] },
    124: { summary: "clears the Escape condition", parameters: [] },
    125: { summary: "sets the Escape condition", parameters: [] },
    126: { summary: "acknowledges the Escape condition", parameters: [] },
    127: { summary: "checks an open channel for end of file", parameters: [{ name: "X", meaning: "file channel" }] },
    128: { summary: "reads ADC conversion or buffer status", parameters: [{ name: "X", meaning: "ADC channel or negative buffer selector" }] },
    129: { summary: "reads a key with an optional time limit, or scans the keyboard", parameters: [{ name: "X", meaning: "low byte of time limit or negative key number" }, { name: "Y", meaning: "high byte of time limit or 255 for keyboard scan" }] },
    130: { summary: "reads the machine's high-order address", parameters: [] },
    131: { summary: "reads OSHWM, the bottom of user memory", parameters: [] },
    132: { summary: "reads the top of user memory", parameters: [] },
    133: { summary: "reads the bottom of display memory for a requested mode", parameters: [{ name: "X", meaning: "screen mode" }] },
    134: { summary: "reads the text cursor position", parameters: [] },
    135: { summary: "reads the character at the text cursor", parameters: [] },
    137: { summary: "places one byte into a selected buffer", parameters: [{ name: "X", values: BUFFERS }, { name: "Y", type: "character", meaning: "byte to insert" }] },
    138: { summary: "inserts one byte into a selected input buffer", parameters: [{ name: "X", values: BUFFERS }, { name: "Y", type: "character", meaning: "byte to insert" }] },
    139: { summary: "removes one byte from a selected buffer", parameters: [{ name: "X", values: BUFFERS }] },
    140: { summary: "runs tape filing-system code", parameters: [] },
    141: { summary: "performs ROM filing-system control", parameters: [{ name: "X", meaning: "ROM filing-system operation" }] },
    142: { summary: "enters the selected language ROM", parameters: [{ name: "X", meaning: "language ROM number" }] },
    143: { summary: "issues a sideways-ROM service call", parameters: [{ name: "X", meaning: "service reason" }, { name: "Y", meaning: "service-call parameter" }] },
    145: { summary: "reads the CMOS/RAM filing-system state on supporting machines", parameters: [{ name: "X", meaning: "machine-specific selector" }] },
    156: { summary: "reads or writes the serial ACIA control value", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    163: { summary: "reads or changes RISC OS/extended VDU state on supporting systems", parameters: [{ name: "X", meaning: "sub-reason" }, { name: "Y", meaning: "sub-reason parameter" }] },
    172: { summary: "reads the address of MOS variables on supporting systems", parameters: [{ name: "X", meaning: "variable selector" }] },
    181: { summary: "reads or changes RS423 mode", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    182: { summary: "reads the user-defined-character allocation", parameters: [{ name: "X", meaning: "character number" }] },
    188: { summary: "reads the current ADC channel", parameters: [] },
    189: { summary: "reads the maximum ADC channel", parameters: [] },
    190: { summary: "reads the ADC conversion precision", parameters: [] },
    191: { summary: "reads or changes the RS423-use flag", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    193: { summary: "reads or changes the flashing-colour counter", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    194: { summary: "reads or changes the flashing-colour mark period", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    195: { summary: "reads or changes the flashing-colour space period", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    196: { summary: "reads or changes keyboard auto-repeat delay", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    197: { summary: "reads or changes keyboard auto-repeat rate", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    198: { summary: "reads or changes the active EXEC file handle", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    199: { summary: "reads or changes the active SPOOL file handle", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    200: { summary: "reads or changes Escape and BREAK behaviour", parameters: [{ name: "X", bits: [
      { mask: 1, set: "normal Escape recognition disabled", clear: "normal Escape recognition enabled" },
      { mask: 2, set: "user memory cleared on BREAK", clear: "normal BREAK memory-preservation behaviour retained" },
    ] }, { name: "Y", meaning: "AND mask when reading or modifying the existing state" }] },
    201: { summary: "reads or changes keyboard-disable state", parameters: [{ name: "X", values: { 0: "keyboard scanned normally" }, otherwise: "all keys except BREAK ignored" }] },
    202: { summary: "reads or changes the keyboard status byte", parameters: [{ name: "X", bits: [
      { mask: 8, set: "Shift currently pressed", clear: "Shift not pressed" },
      { mask: 64, set: "Control currently pressed", clear: "Control not pressed" },
      { mask: 128, set: "Shift enabled with a lock key", clear: "normal lock-key Shift behaviour" },
    ] }, { name: "Y", meaning: "AND mask" }] },
    203: { summary: "reads or changes the RS423 handshake threshold", parameters: [{ name: "X", meaning: "free-space threshold" }, { name: "Y", meaning: "AND mask" }] },
    204: { summary: "reads or changes RS423 input suppression", parameters: [{ name: "X", values: { 0: "RS423 input accepted" }, otherwise: "RS423 input ignored" }] },
    205: { summary: "reads or changes cassette/RS423 selection", parameters: [{ name: "X", meaning: "selection state" }, { name: "Y", meaning: "AND mask" }] },
    214: { summary: "reads or changes bell duration", parameters: [{ name: "X", unit: "fiftieth-of-a-second" }, { name: "Y", meaning: "AND mask" }] },
    215: { summary: "reads or changes startup-message behaviour", parameters: [{ name: "X", meaning: "startup flags" }, { name: "Y", meaning: "AND mask" }] },
    216: { summary: "reads or changes remaining soft-key expansion length", parameters: [{ name: "X", meaning: "remaining character count" }, { name: "Y", meaning: "AND mask" }] },
    217: { summary: "reads or changes lines printed since the last page-mode halt", parameters: [{ name: "X", meaning: "line count" }, { name: "Y", meaning: "AND mask" }] },
    218: { summary: "reads or changes the number of bytes awaited by the VDU queue", parameters: [{ name: "X", meaning: "two's-complement pending-byte count; 0 abandons the queue" }, { name: "Y", meaning: "AND mask" }] },
    219: { summary: "reads or changes the character returned by Tab", parameters: [{ name: "X", type: "character" }, { name: "Y", meaning: "AND mask" }] },
    220: { summary: "reads or changes the Escape character", parameters: [{ name: "X", type: "character" }, { name: "Y", meaning: "AND mask" }] },
    225: { summary: "sets function-key interpretation", parameters: [{ name: "X", meaning: "0 ignores, 1 expands a soft key, other values form returned key codes" }, { name: "Y", meaning: "AND mask" }] },
    226: { summary: "sets Shift-function-key interpretation", parameters: [{ name: "X", meaning: "key interpretation base" }, { name: "Y", meaning: "AND mask" }] },
    227: { summary: "sets Control-function-key interpretation", parameters: [{ name: "X", meaning: "key interpretation base" }, { name: "Y", meaning: "AND mask" }] },
    228: { summary: "sets Shift-Control-function-key interpretation", parameters: [{ name: "X", meaning: "key interpretation base" }, { name: "Y", meaning: "AND mask" }] },
    229: { summary: "reads or changes whether Escape acts as Escape or as a character", parameters: [{ name: "X", values: { 0: "selected Escape key causes Escape" }, otherwise: "selected Escape key returns a character code" }, { name: "Y", meaning: "AND mask" }] },
    230: { summary: "reads or changes Escape acknowledgement side effects", parameters: [{ name: "X", values: { 0: "acknowledging Escape clears Escape, closes EXEC, purges buffers and resets paging" }, otherwise: "acknowledging Escape omits those normal side effects" }, { name: "Y", meaning: "AND mask" }] },
    231: { summary: "reads or changes the user-VIA interrupt mask", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    232: { summary: "reads or changes the serial-ACIA interrupt mask", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    233: { summary: "reads or changes the system-VIA interrupt mask", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    242: { summary: "reads the serial-ULA control copy", parameters: [] },
    243: { summary: "reads or changes timer-switch state", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    244: { summary: "reads or changes the soft-key consistency flag", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    245: { summary: "reads or changes the printer-destination flag", parameters: [{ name: "X", meaning: "XOR value" }, { name: "Y", meaning: "AND mask" }] },
    246: { summary: "reads or changes the character ignored by the printer", parameters: [{ name: "X", type: "character" }, { name: "Y", meaning: "AND mask" }] },
    247: { summary: "reads or changes BREAK-intercept byte 1", parameters: [{ name: "X", meaning: "byte value" }, { name: "Y", meaning: "AND mask" }] },
    248: { summary: "reads or changes BREAK-intercept byte 2", parameters: [{ name: "X", meaning: "byte value" }, { name: "Y", meaning: "AND mask" }] },
    249: { summary: "reads or changes BREAK-intercept byte 3", parameters: [{ name: "X", meaning: "byte value" }, { name: "Y", meaning: "AND mask" }] },
    252: { summary: "reads or changes the current language ROM number", parameters: [{ name: "X", meaning: "ROM number" }, { name: "Y", meaning: "AND mask" }] },
    253: { summary: "reads or changes the last BREAK type", parameters: [{ name: "X", meaning: "BREAK type" }, { name: "Y", meaning: "AND mask" }] },
    254: { summary: "reads or changes the available-RAM setting", parameters: [{ name: "X", meaning: "RAM setting" }, { name: "Y", meaning: "AND mask" }] },
    255: { summary: "reads or changes startup options", parameters: [{ name: "X", meaning: "startup option byte" }, { name: "Y", meaning: "AND mask" }] },
  });

  const VDU = Object.freeze({
    0: { summary: "does nothing", parameters: [] }, 1: { summary: "sends the next byte to the printer only", parameters: [{ name: "byte", type: "character" }] },
    2: { summary: "enables printer output", parameters: [] }, 3: { summary: "disables printer output", parameters: [] },
    4: { summary: "selects the text cursor", parameters: [] }, 5: { summary: "selects the graphics cursor", parameters: [] },
    6: { summary: "enables VDU output", parameters: [] }, 7: { summary: "sounds the bell", parameters: [] },
    8: { summary: "moves the text cursor left", parameters: [] }, 9: { summary: "moves the text cursor right", parameters: [] },
    10: { summary: "moves the text cursor down", parameters: [] }, 11: { summary: "moves the text cursor up", parameters: [] },
    12: { summary: "clears the text area", parameters: [] }, 13: { summary: "returns the cursor to the start of its line", parameters: [] },
    14: { summary: "enables paged scrolling", parameters: [] }, 15: { summary: "disables paged scrolling", parameters: [] },
    16: { summary: "clears the graphics area", parameters: [] },
    17: { summary: "selects a logical text colour", parameters: [{ name: "colour", type: "logicalColour" }] },
    18: { summary: "selects a graphics plot action and colour", parameters: [{ name: "action", meaning: "GCOL action" }, { name: "colour", type: "logicalColour" }] },
    19: { summary: "maps a logical colour to a physical colour", parameters: [{ name: "logical colour" }, { name: "physical colour" }, { name: "red" }, { name: "green" }, { name: "blue" }] },
    20: { summary: "restores default logical colours", parameters: [] }, 21: { summary: "disables VDU output", parameters: [] },
    22: { summary: "selects a screen mode", parameters: [{ name: "mode" }] },
    23: { summary: "changes a VDU variable, cursor setting, CRTC register or character definition", variantParameter: 0 },
    24: { summary: "defines the graphics viewport", parameters: [{ name: "left", type: "word" }, { name: "bottom", type: "word" }, { name: "right", type: "word" }, { name: "top", type: "word" }] },
    25: { summary: "performs a graphics plot operation", parameters: [{ name: "plot code" }, { name: "x", type: "word" }, { name: "y", type: "word" }] },
    26: { summary: "restores the default text and graphics windows", parameters: [] }, 27: { summary: "sends Escape to the VDU driver", parameters: [] },
    28: { summary: "defines the text window", parameters: [{ name: "left" }, { name: "bottom" }, { name: "right" }, { name: "top" }] },
    29: { summary: "sets the graphics origin", parameters: [{ name: "x", type: "word" }, { name: "y", type: "word" }] },
    30: { summary: "moves the text cursor home", parameters: [] }, 31: { summary: "moves the text cursor", parameters: [{ name: "column" }, { name: "row" }] },
  });
  const VDU23 = Object.freeze({
    0: { summary: "writes a 6845 CRTC register", platforms: ["bbc", "master"], requires: "6845 CRTC-compatible video hardware", parameters: [{ name: "register" }, { name: "value", dependent: "crtc" }, { name: "padding", count: 6 }] },
    1: { summary: "sets text-cursor visibility and flashing", parameters: [{ name: "cursor mode", values: { 0: "text cursor off", 1: "text cursor on", 2: "steady text cursor", 3: "flashing text cursor" } }, { name: "padding", count: 7 }] },
    6: { summary: "sets the dotted-line pattern", parameters: [{ name: "pattern" }, { name: "padding", count: 7 }] },
    7: { summary: "changes scrolling behaviour", parameters: [{ name: "scroll setting" }, { name: "padding", count: 7 }] },
  });

  const BASIC_CALLS = Object.freeze({
    SOUND: { summary: "queues a sound", platforms: ["bbc", "master", "electron"], requires: "the classic Acorn four-channel sound interface", parameters: [
      { name: "channel", values: { 0: "noise channel", 1: "tone channel 1", 2: "tone channel 2", 3: "tone channel 3" }, otherwise: "channel plus flush/synchronisation flags" },
      { name: "amplitude/envelope", signed: true, meaning: "0 is silent; -1 to -15 select fixed loudness; positive 1 to 4 selects that envelope on classic BBC sound" },
      { name: "pitch", range: [0, 255], meaning: "pitch in quarter-semitone steps; 52 is middle C on classic BBC sound" },
      { name: "duration", unit: "twentieth-of-a-second", meaning: "note duration" },
    ] },
    ENVELOPE: { summary: "defines a 14-parameter sound envelope", platforms: ["bbc", "master", "electron"], requires: "the classic Acorn sound envelope interface", parameters: [
      { name: "N", range: [1, 4], meaning: "envelope number referenced by SOUND" },
      { name: "T", bitValue: { mask: 127, meaning: "centiseconds per pitch step" }, bits: [{ mask: 128, set: "pitch phases repeat automatically", clear: "pitch phases run once" }] },
      { name: "PI1", signed: true, meaning: "pitch change per step in phase 1" },
      { name: "PI2", signed: true, meaning: "pitch change per step in phase 2" },
      { name: "PI3", signed: true, meaning: "pitch change per step in phase 3" },
      { name: "PN1", meaning: "number of pitch steps in phase 1" },
      { name: "PN2", meaning: "number of pitch steps in phase 2" },
      { name: "PN3", meaning: "number of pitch steps in phase 3" },
      { name: "AA", signed: true, meaning: "amplitude change per attack step" },
      { name: "AD", signed: true, meaning: "amplitude change per decay step" },
      { name: "AS", signed: true, meaning: "amplitude change per sustain step" },
      { name: "AR", signed: true, meaning: "amplitude change per release step" },
      { name: "ALA", range: [0, 126], meaning: "target level for the attack phase" },
      { name: "ALD", range: [0, 126], meaning: "target level for the decay phase" },
    ] },
  });

  const printable = value => value >= 32 && value < 127 ? ` ${JSON.stringify(String.fromCharCode(value))}` : "";
  const formatValue = value => {
    const wide = value > 255 || value < -128;
    const encoded = value & (wide ? 0xFFFF : 0xFF);
    return `${value} (&${encoded.toString(16).toUpperCase().padStart(wide ? 4 : 2, "0")})`;
  };

  function parameterText(spec, value, context = {}) {
    if (value == null) return `${spec.name}=dynamic or not supplied`;
    const parts = [`${spec.name}=${formatValue(value)}`];
    const selected = spec.values?.[value] ?? spec.otherwise;
    if (selected) parts.push(selected);
    if (spec.type === "character") parts.push(`character byte${printable(value)}`);
    if (spec.type === "logicalColour") parts.push(value >= 128 ? `logical background colour ${value - 128}` : `logical foreground colour ${value}`);
    if (spec.meaning) parts.push(spec.meaning);
    if (spec.unit) parts.push(`${value} ${spec.unit}${value === 1 ? "" : "s"}`);
    if (spec.range && (value < spec.range[0] || value > spec.range[1])) parts.push(`outside the documented ${spec.range[0]}–${spec.range[1]} range`);
    if (spec.bitValue) parts.push(`${value & spec.bitValue.mask} ${spec.bitValue.meaning}`);
    for (const bit of spec.bits || []) parts.push(value & bit.mask ? bit.set : bit.clear);
    if (spec.dependent === "crtc") {
      if (context.register === 10) parts.push(value & 0x20 ? "CRTC cursor disabled" : "CRTC cursor enabled");
      else parts.push(`value written to CRTC register ${context.register}`);
    }
    return parts.join(": ");
  }

  function explainParameters(specs = [], values = []) {
    const descriptions = [];
    let offset = 0;
    const context = {};
    for (const spec of specs) {
      if (spec.count) {
        const group = values.slice(offset, offset + spec.count);
        if (group.some(value => value != null && value !== 0)) descriptions.push(`${spec.name}: ${group.map(formatValue).join(", ")}`);
        offset += spec.count;
        continue;
      }
      let value;
      if (spec.type === "word") {
        value = values[offset] == null || values[offset + 1] == null ? null : values[offset] | (values[offset + 1] << 8);
        offset += 2;
      } else {
        value = values[offset];
        offset += 1;
      }
      context[spec.name] = value;
      descriptions.push(parameterText(spec, value, context));
    }
    if (values.length > offset) descriptions.push(`additional emitted bytes: ${values.slice(offset).map(formatValue).join(", ")}`);
    return descriptions;
  }

  function explainOsbyte(reason, x, y) {
    const spec = OSBYTE[reason];
    if (!spec) return { summary: "is undocumented here or supplied by the active machine, filing system or ROM", details: [x == null ? "No constant X parameter was proved." : `X=${formatValue(x)}`, y == null ? "No constant Y parameter was proved." : `Y=${formatValue(y)}`], platforms: null, requires: "documentation for the active OS or providing ROM" };
    return { summary: spec.summary, details: explainParameters(spec.parameters, [x, y].slice(0, spec.parameters.length)), platforms: spec.platforms || ["bbc", "master", "electron"], requires: spec.requires || "the documented MOS reason on the target OS" };
  }

  function explainVdu(bytes, complete = true) {
    const reason = bytes[0];
    const base = VDU[reason];
    if (!base) return { summary: "uses a target-specific VDU control", details: [`Emitted bytes: ${bytes.map(formatValue).join(", ")}`] };
    let parameters = bytes.slice(1);
    let spec = base;
    const details = [`Emitted bytes: ${bytes.map(formatValue).join(", ")}${complete ? "" : " (constant prefix only)"}`];
    if (reason === 23 && parameters.length) {
      const selector = parameters.shift();
      spec = VDU23[selector] || (selector >= 32
        ? { summary: `redefines character ${selector}`, parameters: [{ name: "bitmap row", count: 8 }] }
        : { summary: `${base.summary}; subcommand ${selector} is target-specific`, parameters: [] });
      details.push(`VDU 23 subcommand=${formatValue(selector)}: ${spec.summary}`);
    }
    details.push(...explainParameters(spec.parameters, parameters));
    return { summary: base.summary, details, platforms: spec.platforms || base.platforms || ["bbc", "master", "electron", "risc-os"], requires: spec.requires || base.requires || "a compatible VDU driver" };
  }

  function explainBasicCall(name, values) {
    const spec = BASIC_CALLS[String(name || "").toUpperCase()];
    return spec ? { summary: spec.summary, details: explainParameters(spec.parameters, values), platforms: spec.platforms, requires: spec.requires } : null;
  }

  return Object.freeze({ OSBYTE, VDU, BASIC_CALLS, explainOsbyte, explainVdu, explainBasicCall });
})();

if (typeof module !== "undefined") module.exports = window.AcornCallCatalogue;
