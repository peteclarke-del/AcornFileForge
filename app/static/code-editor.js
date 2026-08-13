window.AcornCodeEditor = (() => {
  const BASIC_LANGUAGE = window.AcornBasicLanguage;
  const ASSEMBLY_LANGUAGE = window.AcornAssemblyLanguage;
  const CALL_CATALOGUE = window.AcornCallCatalogue;
  const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[character]));

  const help = (summary, syntax, requirements = "None beyond the active language or filing system.", notes = "") => ({
    summary, syntax, requirements, notes,
  });

  const BASIC_HELP = {
    AND: help("Combines two integer values bit by bit using logical AND.", "expression AND expression", "Operands are converted to BBC BASIC integers before the bitwise operation."),
    DIV: help("Returns the integer quotient after division, discarding any remainder.", "integer DIV integer", "The divisor must not be zero."),
    EOR: help("Combines two integer values bit by bit using exclusive OR.", "expression EOR expression", "Operands are converted to BBC BASIC integers before the bitwise operation."),
    MOD: help("Returns the integer remainder after division.", "integer MOD integer", "The divisor must not be zero."),
    OR: help("Combines two integer values bit by bit using logical OR.", "expression OR expression", "Inside IF conditions, zero is false and a non-zero result is true."),
    NOT: help("Inverts every bit of an integer value.", "NOT expression", "The expression is converted to a BBC BASIC integer before inversion."),
    CHAIN: help("Loads and starts a tokenised BASIC program, replacing the current program.", 'CHAIN "filename"', "The target must be a tokenised BASIC program visible through the current filing system.", "Use *EXEC for an unnumbered command script such as a conventional !BOOT file."),
    CALL: help("Transfers control to machine code and returns when that code executes RTS.", "CALL address[,parameter…]", "The address must contain code for the current processor and machine environment.", "Incorrect addresses, PAGE or processor assumptions can crash the machine."),
    OSCLI: help("Passes a string to the current filing system or operating system command interpreter.", "OSCLI command$", "The command and filing system must be available on the target machine.", "DFS abbreviations such as R. and L. can be ambiguous after moving software to ADFS."),
    GOTO: help("Continues execution at a numbered BASIC line.", "GOTO line", "The destination line must exist in the current program."),
    GOSUB: help("Calls a numbered BASIC subroutine; RETURN resumes after the GOSUB.", "GOSUB line", "The destination line must exist and every completed path should reach RETURN."),
    RETURN: help("Returns from the most recent GOSUB.", "RETURN", "A matching active GOSUB is required."),
    PROC: help("Calls a named BBC BASIC procedure.", "PROCname(parameter…)", "A matching DEF PROCname definition must be present or installed by an overlay."),
    FN: help("Calls a named BBC BASIC function and returns its value.", "FNname(parameter…)", "A matching DEF FNname definition must be present."),
    DEF: help("Begins a named procedure or function definition.", "DEF PROCname(...) or DEF FNname(...)", "Procedure definitions normally finish with ENDPROC; functions return an expression with =."),
    ENDPROC: help("Returns from the current procedure.", "ENDPROC", "Execution must currently be inside a PROC called by BBC BASIC."),
    FOR: help("Starts a counted loop and assigns its control variable.", "FOR variable = start TO limit [STEP amount]", "A matching NEXT should complete the loop."),
    NEXT: help("Advances one or more active FOR loops.", "NEXT [variable[,variable…]]", "The named variable must belong to an active FOR loop."),
    REPEAT: help("Starts a post-tested loop.", "REPEAT", "A matching UNTIL expression should terminate the loop."),
    UNTIL: help("Repeats the matching REPEAT block until its expression is true.", "UNTIL condition", "A matching active REPEAT is required."),
    IF: help("Conditionally executes the remainder of a statement or branches to another line.", "IF condition THEN statement [ELSE statement]", "THEN and ELSE branches must use syntax supported by the target BASIC version."),
    ON: help("Selects a numbered branch or installs error/event handling.", "ON expression GOTO/GOSUB list; ON ERROR ...", "Branch destinations must exist. Error handlers should avoid recursively raising the same error."),
    ERROR: help("Raises a BBC BASIC error with a numeric code and message.", 'ERROR number, "message"', "Use an application-appropriate error number; the active ON ERROR handler may intercept it."),
    DIM: help("Reserves memory for arrays or raw byte storage.", "DIM array(dimensions) or DIM block size", "HIMEM and available memory must leave enough space for the allocation."),
    PAGE: help("Reads or changes the address at which BBC BASIC stores the program.", "PAGE or PAGE=&address", "Changing PAGE clears or relocates the program and must respect filing-system workspace and Tube configuration.", "Prefer the PAGE value detected from the original image unless the target setup is understood."),
    HIMEM: help("Reads or sets the upper boundary of BASIC workspace.", "HIMEM or HIMEM=&address", "The value must not overlap the program, variables, filing-system workspace or machine code."),
    LOMEM: help("Reads or sets the start of BASIC dynamic variable storage.", "LOMEM or LOMEM=&address", "It normally follows the tokenised program and must remain below HIMEM."),
    OPENIN: help("Opens an existing file for input and returns a channel number, or zero if it cannot be opened.", 'channel%=OPENIN("filename")', "The filing system must be active and the file must exist."),
    OPENOUT: help("Creates or replaces a file and returns an output channel.", 'channel%=OPENOUT("filename")', "The medium must be writable and the filename valid for the active filing system."),
    OPENUP: help("Opens an existing file for update and returns a channel.", 'channel%=OPENUP("filename")', "The filing system and medium must support writable random access."),
    CLOSE: help("Closes one channel, or all channels when used as CLOSE#0.", "CLOSE#channel", "The channel must have been opened by BASIC or the operating system."),
    BGET: help("Reads one byte from an open channel.", "value=BGET#channel", "The channel must be open for input; check EOF# before reading beyond the file."),
    BPUT: help("Writes one byte to an open channel.", "BPUT#channel,value", "The channel must be open for output or update and the medium writable."),
    INPUT: help("Reads values from the keyboard or an open file channel.", "INPUT [#channel,] variable…", "File input requires a valid open channel and data in a compatible textual form."),
    PRINT: help("Writes formatted values to the screen, printer stream or an open channel.", "PRINT [#channel,] expression…", "File output requires a valid writable channel."),
    LOAD: help("Loads a BASIC program without starting it.", 'LOAD "filename"', "The target must be a tokenised BASIC program visible through the active filing system."),
    SAVE: help("Saves the current tokenised BASIC program.", 'SAVE "filename"', "The destination medium must be writable and the filename valid."),
    RUN: help("Starts the current BASIC program, or loads and starts a named BASIC program.", 'RUN ["filename"]', "A named target must be a tokenised BASIC program."),
    COLOUR: help("Selects the logical text foreground or background colour.", "COLOUR logical-colour", "The available logical colours depend on the current display mode.", "Values from 128 select the text background colour; flashing and tint behaviour vary by machine and BASIC version."),
    MODE: help("Changes the display mode and normally clears the screen.", "MODE number", "The selected mode must exist on the target machine and leave enough memory for the program."),
    VDU: help("Sends one or more bytes directly to the VDU driver.", "VDU value[,value…]", "Sequences and mode capabilities vary across BBC, Electron and RISC OS targets."),
    SYS: help("Calls a RISC OS software interrupt by name or number.", 'SYS "SWI_Name"[,input…] [TO output…]', "BBC BASIC V or later and the named SWI must be available on the target RISC OS system.", "Register arguments are positional. Check the SWI contract before passing pointers or writable buffers."),
    SOUND: help("Queues a sound using the four BBC sound parameters.", "SOUND channel,amplitude,pitch,duration", "Sound hardware and envelope behaviour vary by target."),
    ENVELOPE: help("Defines a numbered sound envelope.", "ENVELOPE number,step,pitch…,amplitude…", "The envelope number is later referenced through a negative SOUND amplitude."),
    REM: help("Introduces a comment; the rest of the BASIC line is not executed.", "REM comment", "None."),
    DATA: help("Stores constant values for sequential access by READ.", "DATA value[,value…]", "READ variables must be compatible with the stored values."),
    READ: help("Reads the next value from the program's DATA stream.", "READ variable[,variable…]", "Enough DATA values must remain; RESTORE can reposition the stream."),
    RESTORE: help("Moves the DATA read pointer to the beginning or to a numbered line.", "RESTORE [line]", "A specified destination line must exist and should contain or precede DATA."),
    ENDIF: help("Closes a multi-line IF block.", "IF condition THEN ... ENDIF", "Requires a BBC BASIC version that supports structured multi-line IF blocks."),
    CASE: help("Starts a structured CASE selection block.", "CASE expression OF", "Requires a BBC BASIC version that supports CASE, WHEN and ENDCASE."),
    WHEN: help("Introduces one or more matching values inside a CASE block.", "WHEN value[,value…]: statements", "Must appear inside a CASE block."),
    OTHERWISE: help("Introduces the fallback branch inside a CASE block.", "OTHERWISE statements", "Must appear inside a CASE block and should follow all WHEN branches."),
    ENDCASE: help("Closes a structured CASE block.", "ENDCASE", "A matching CASE block is required."),
    WHILE: help("Starts a pre-tested structured loop.", "WHILE condition", "Requires a BBC BASIC version that supports WHILE and ENDWHILE."),
    ENDWHILE: help("Returns to the matching WHILE test.", "ENDWHILE", "A matching active WHILE block is required."),
  };

  const SCRIPT_HELP = {
    ACCESS: help("Changes a file's public and owner access attributes.", "*ACCESS filespec [letters]", "The active filing system must support access attributes and the object must be writable."),
    BACKUP: help("Copies an entire filing-system volume or disk.", "*BACKUP source-drive destination-drive", "Requires a filing system that provides BACKUP and distinct source and destination media."),
    BASIC: help("Selects the BBC BASIC language ROM.", "*BASIC", "A compatible BASIC ROM must be installed and discoverable by the operating system."),
    CAT: help("Displays the current filing-system catalogue.", "*CAT [filespec]", "A filing system and readable medium must be active."),
    CDIR: help("Creates a directory on filing systems that support hierarchical directories.", "*CDIR directory [size]", "ADFS or another directory-capable filing system must be active."),
    COMPACT: help("Compacts free space on a filing-system volume.", "*COMPACT", "The filing system and medium must support compaction and be writable."),
    COPY: help("Copies one or more filing-system objects.", "*COPY source destination", "Source objects must be readable and the destination writable."),
    DIR: help("Changes the current directory or DFS catalogue prefix.", "*DIR directory", "ADFS requires the directory to exist; DFS normally accepts a single-character catalogue prefix."),
    LIB: help("Selects the filing-system library directory.", "*LIB directory", "The filing system must support a library and the directory must exist."),
    DRIVE: help("Selects a drive or MMFS/MMB slot where supported.", "*DRIVE number", "The active filing system must implement drive selection and the target must be available."),
    DISMOUNT: help("Dismounts the current volume so cached metadata is flushed safely.", "*DISMOUNT [drive]", "The active filing system must provide dismounting."),
    EXEC: help("Reads operating-system commands from a text file as though they were typed.", "*EXEC filename", "The file must contain command text, not tokenised BASIC.", "This is the usual action for a command-script !BOOT file."),
    RUN: help("Loads a machine-code file at its load address and calls its execution address.", "*RUN filename [parameters]", "The file needs valid load and execution metadata and compatible machine code."),
    LOAD: help("Loads a file at its catalogue load address or an explicitly supplied address.", "*LOAD filename [address]", "Enough memory must be free and the address suitable for the target machine."),
    SAVE: help("Saves a memory range to a file with load and execution metadata.", "*SAVE filename start end [exec [reload]]", "The medium must be writable and the memory range valid."),
    DELETE: help("Deletes a filing-system object.", "*DELETE filename", "The object and medium must be writable; directories may need to be empty."),
    RENAME: help("Renames a filing-system object.", "*RENAME old new", "Both names must be valid for the active filing system and the destination must not clash."),
    TYPE: help("Displays a text file without executing it.", "*TYPE filename", "The file must be readable; binary files can produce control characters."),
    DUMP: help("Displays a file as hexadecimal bytes and text.", "*DUMP filename", "The command must be provided by the active filing system or utilities ROM."),
    FX: help("Invokes OSBYTE with a decimal reason code and parameters.", "*FX number[,X[,Y]]", "The reason code must be supported by the target OS and hardware."),
    HELP: help("Lists operating-system, filing-system and service-ROM help topics.", "*HELP [topic]", "Available topics depend on the installed ROMs."),
    INFO: help("Displays catalogue metadata for matching filing-system objects.", "*INFO filespec", "The active filing system must provide INFO."),
    OPT: help("Changes filing-system options, including boot behaviour on many Acorn systems.", "*OPT number[,value]", "Meanings are filing-system-specific. *OPT 4 controls boot options on common DFS/ADFS systems."),
    BOOT: help("Runs the medium's boot sequence where the filing system provides this command.", "*BOOT", "A boot option and suitable !BOOT file must be present."),
    MOUNT: help("Mounts a named ADFS volume or supported device.", "*MOUNT [volume]", "ADFS or a compatible filing system must be active and the volume available."),
    MMFS: help("Selects or enters MMFS on supported hardware.", "*MMFS", "A compatible MMFS ROM and storage interface must be installed."),
    ROMS: help("Lists installed sideways ROMs where the operating system or utility ROM provides it.", "*ROMS", "Requires a ROM-management command with this name."),
    SPOOL: help("Copies subsequent screen output to a file; *SPOOL with no name closes it.", "*SPOOL [filename]", "The destination must be writable. Close the spool before removing the medium."),
    TITLE: help("Changes the current disk or volume title.", "*TITLE title", "The active filing system must support writable volume titles."),
    WIPE: help("Deletes matching filing-system objects, normally after confirmation.", "*WIPE filespec", "The objects and medium must be writable; behaviour is filing-system-specific."),
  };

  const MOS_HELP = {
    OSRDRM: help("Reads one byte from the currently selected sideways ROM at &FFB9.", "JSR OSRDRM", "Y contains the ROM number and the address is supplied using the documented MOS register convention."),
    VDUCHR: help("Sends the byte in A through the VDU system at &FFBC.", "JSR VDUCHR", "A contains a printable character or VDU control byte."),
    OSEVEN: help("Generates a MOS event at &FFBF.", "JSR OSEVEN", "A and Y identify the event and event-specific value; enabled-event state applies."),
    GSINIT: help("Initialises MOS command-line parsing at &FFC2.", "JSR GSINIT", "XY points into a command string using the MOS general-string parser convention."),
    GSREAD: help("Reads the next item through the MOS command-line parser at &FFC5.", "JSR GSREAD", "Call GSINIT first and observe the returned flags and updated string position."),
    NVRDCH: help("Reads from the currently selected input stream at &FFC8.", "JSR NVRDCH", "The active input stream must be available; returned flags can report errors or Escape."),
    NVWRCH: help("Writes to the currently selected output stream at &FFCB.", "JSR NVWRCH", "A contains the byte and the configured output stream must accept it."),
    OSFIND: help("MOS file open/close entry point at &FFCE.", "JSR OSFIND", "A selects open/close operation; XY points to the filename when opening. The returned channel is in A."),
    OSGBPB: help("MOS block filing operation entry point at &FFD1.", "JSR OSGBPB", "A selects the operation and XY points to a control block with channel, address, count and file pointer."),
    OSBPUT: help("Writes the byte in A to the channel in Y at &FFD4.", "JSR OSBPUT", "Y must contain a writable open channel."),
    OSBGET: help("Reads a byte from the channel in Y at &FFD7.", "JSR OSBGET", "Y must contain a readable channel; carry reports end-of-file on common MOS versions."),
    OSARGS: help("Reads or changes channel/file-system arguments at &FFDA.", "JSR OSARGS", "A selects the operation, Y is usually the channel, and XY may point to a control block."),
    OSFILE: help("Performs whole-file operations through a parameter block at &FFDD.", "JSR OSFILE", "A selects save, load, catalogue or metadata action; XY points to an OSFILE control block."),
    OSRDCH: help("Reads one character from the current input stream at &FFE0.", "JSR OSRDCH", "Returns the character in A; escape and input errors must be handled."),
    OSASCI: help("Writes A, expanding carriage return to the configured newline sequence, at &FFE3.", "JSR OSASCI", "A contains the character."),
    OSNEWL: help("Writes the configured newline sequence at &FFE7.", "JSR OSNEWL", "The current output stream must accept characters."),
    OSWRCH: help("Writes the character in A to the current output stream at &FFEE.", "JSR OSWRCH", "A contains a character or VDU byte; multi-byte VDU commands require successive calls."),
    OSWORD: help("Performs a parameter-block MOS operation at &FFF1.", "JSR OSWORD", "A is the OSWORD reason code and XY points to the reason-specific parameter block."),
    OSBYTE: help("Performs a register-based MOS operation at &FFF4.", "JSR OSBYTE", "A is the OSBYTE reason code; X and Y carry reason-specific input and output values."),
    OSCLI: help("Executes a MOS command line at &FFF7.", "JSR OSCLI", "XY points to a carriage-return-terminated command string."),
  };

  const BASIC_KEYWORDS = BASIC_LANGUAGE?.KEYWORDS || new Set();
  const SCRIPT_COMMANDS = new Set([...Object.keys(SCRIPT_HELP), ...BASIC_KEYWORDS]);
  const ASM_HELP = {
    JSR: help("Calls a subroutine and places a return address on the processor stack.", "JSR address", "The destination must contain compatible code that eventually returns with RTS."),
    JMP: help("Transfers execution to another address without creating a return address.", "JMP address", "The destination must contain executable code; indirect JMP behaviour depends on the processor."),
    RTS: help("Returns from a subroutine called with JSR.", "RTS", "The processor stack must contain a valid JSR return address."),
    BRK: help("Invokes the 6502 BRK/error mechanism.", "BRK", "On BBC MOS, inline error number and text normally follow BRK when raising a language error."),
    LDA: help("Loads the accumulator and updates zero and negative flags.", "LDA operand", "The addressing mode must be valid for the selected processor."),
    STA: help("Stores the accumulator without changing it.", "STA destination", "The destination must be writable; hardware registers can have side effects."),
    CMP: help("Compares the accumulator with an operand by setting flags without retaining the subtraction.", "CMP operand", "A following conditional branch normally interprets carry, zero or negative flags."),
    BNE: help("Branches when the zero flag is clear.", "BNE target", "The target must be within the branch range on 6502."),
    BEQ: help("Branches when the zero flag is set.", "BEQ target", "The target must be within the branch range on 6502."),
  };

  const INLINE_ASSEMBLER_HELP = {
    OPT: help("Sets BBC BASIC inline-assembler listing, error and pass options.", "OPT value", "Used only between [ and ]. The option bits and accepted range depend on the BASIC version."),
    EQUB: help("Emits one or more byte values at the current assembly address.", "EQUB value[,value…]", "P% must point at writable assembly output space."),
    EQUW: help("Emits one or more 16-bit words at the current assembly address.", "EQUW value[,value…]", "Words use the byte order of the target assembler."),
    EQUD: help("Emits one or more 32-bit values at the current assembly address.", "EQUD value[,value…]", "Availability depends on the BBC BASIC version and target processor."),
    EQUS: help("Emits the bytes of a string at the current assembly address.", 'EQUS "text"', "A terminator is only emitted if it is included explicitly."),
    ALIGN: help("Advances the assembly address to the next required alignment boundary.", "ALIGN", "Common in ARM BBC BASIC; exact alignment follows the target assembler."),
  };

  const MOS_ADDRESS_HELP = new Map([
    [0xFFB9, "OSRDRM"], [0xFFBC, "VDUCHR"], [0xFFBF, "OSEVEN"], [0xFFC2, "GSINIT"],
    [0xFFC5, "GSREAD"], [0xFFC8, "NVRDCH"], [0xFFCB, "NVWRCH"],
    [0xFFCE, "OSFIND"], [0xFFD1, "OSGBPB"], [0xFFD4, "OSBPUT"], [0xFFD7, "OSBGET"],
    [0xFFDA, "OSARGS"], [0xFFDD, "OSFILE"], [0xFFE0, "OSRDCH"], [0xFFE3, "OSASCI"],
    [0xFFE7, "OSNEWL"], [0xFFEE, "OSWRCH"], [0xFFF1, "OSWORD"], [0xFFF4, "OSBYTE"],
    [0xFFF7, "OSCLI"],
  ]);

  const isStarHelpKey = value => /^\s*\*/.test(String(value || ""));
  const normaliseHelpKey = value => String(value || "").trim().replace(/^\*/, "").replace(/[^A-Za-z0-9$_.]/g, "").toUpperCase();
  const starCommandPrefix = value => {
    const source = String(value || "").replace(/^\*/, "").toUpperCase();
    return Object.keys(SCRIPT_HELP).sort((left, right) => right.length - left.length).find(command => source.startsWith(command)) || "";
  };
  const COMMAND_CASE = Object.freeze({ basic: "upper", script: "upper", "6502": "upper", "65c02": "upper", "65816": "upper", arm: "lower", m68k: "upper" });
  const dictionary = language => language === "basic" ? { ...BASIC_HELP, ...INLINE_ASSEMBLER_HELP, ...ASM_HELP, ...MOS_HELP } : language === "script" ? { ...SCRIPT_HELP, ...BASIC_HELP } : { ...INLINE_ASSEMBLER_HELP, ...ASM_HELP, ...MOS_HELP };
  const lookup = (language, key) => {
    const normal = normaliseHelpKey(key);
    if (isStarHelpKey(key)) {
      const starCommand = SCRIPT_HELP[normal];
      return starCommand
        ? { key: `*${normal}`, ...starCommand }
        : { key: `*${normal}`, ...help("Operating-system or service-ROM star command.", `*${normal} [parameters]`, "Availability and syntax depend on the active filing system and installed ROMs.") };
    }
    const found = dictionary(language)[normal];
    if (found) return { key: normal, ...found };
    if (language === "basic" && BASIC_KEYWORDS.has(normal)) return { key: normal, ...help("BBC BASIC keyword.", normal, "Syntax and availability depend on the target BBC BASIC version.") };
    if (ASSEMBLY_LANGUAGE?.isMnemonic(language, normal)) return { key: normal, ...help(`${language.toUpperCase()} processor instruction.`, normal, "Operands and addressing modes must be valid for the selected processor variant.") };
    if (["6502", "65c02", "65816", "arm", "m68k"].includes(language) && /^[A-Z][A-Z0-9.]*$/.test(normal)) {
      return { key: normal, ...help(`${language.toUpperCase()} instruction or assembler pseudo-operation.`, normal, "The decoded operands, processor variant and execution context determine its exact effect.") };
    }
    return null;
  };

  const FX_REASON_HELP = Object.freeze(Object.fromEntries(Object.entries(CALL_CATALOGUE?.OSBYTE || {}).map(([reason, spec]) => [reason, spec.summary])));
  const VDU_REASON_HELP = Object.freeze(Object.fromEntries(Object.entries(CALL_CATALOGUE?.VDU || {}).map(([reason, spec]) => [reason, spec.summary])));

  const OSWORD_REASON_HELP = Object.freeze({
    0: "read an edited input line", 1: "read the system clock", 2: "write the system clock",
    3: "read the interval timer", 4: "write the interval timer", 5: "read a byte from I/O memory",
    6: "write a byte to I/O memory", 7: "perform a SOUND command", 8: "define an ENVELOPE",
    9: "read a pixel colour", 10: "read a character definition",
  });
  const RISC_OS_SWI_HELP = Object.freeze({
    "OS_WRITEC": "write the character in R0", "OS_WRITE0": "write the zero-terminated string addressed by R0",
    "OS_NEWLINE": "write a newline", "OS_READC": "read a character", "OS_CLI": "execute the command string addressed by R0",
    "OS_BYTE": "perform a register-based operating-system operation", "OS_WORD": "perform a parameter-block operating-system operation",
    "OS_FILE": "perform a whole-file operation", "OS_FIND": "open or close a file", "OS_GBPB": "transfer blocks or enumerate filing-system objects",
    "OS_ARGS": "read or change filing-system arguments", "OS_BGET": "read a byte from an open file", "OS_BPUT": "write a byte to an open file",
    "OS_GETENV": "read the command tail, time and memory limit", "OS_EXIT": "terminate the current application",
    "WIMP_INITIALISE": "register a desktop task with the Window Manager", "WIMP_POLL": "wait for the next Window Manager event",
  });

  const sourceNumber = value => {
    const match = String(value || "").trim().match(/^(-?)(?:&([0-9a-f]+)|0x([0-9a-f]+)|(\d+))/i);
    if (!match) return null;
    const number = Number.parseInt(match[2] || match[3] || match[4], match[2] || match[3] ? 16 : 10);
    return match[1] ? -number : number;
  };

  function constantNumbers(value) {
    const numbers = [];
    let remaining = String(value || "").trim();
    while (remaining) {
      const match = remaining.match(/^(-?(?:&[0-9a-f]+|0x[0-9a-f]+|\d+))/i);
      if (!match) break;
      numbers.push(sourceNumber(match[1]));
      const separator = remaining.slice(match[0].length).match(/^(\s*,\s*|\s+)/);
      if (!separator) break;
      remaining = remaining.slice(match[0].length + separator[0].length);
    }
    return numbers;
  }

  function vduBytes(value) {
    const bytes = [];
    let remaining = String(value || "").trim();
    let complete = true;
    while (remaining) {
      const match = remaining.match(/^(-?(?:&[0-9a-f]+|0x[0-9a-f]+|\d+))/i);
      if (!match) { complete = false; break; }
      const number = sourceNumber(match[1]);
      remaining = remaining.slice(match[0].length);
      const separator = remaining.match(/^\s*([,;])/);
      const delimiter = separator?.[1] || "";
      bytes.push(number & 0xFF);
      if (delimiter === ";") bytes.push((number >>> 8) & 0xFF);
      if (!separator) {
        if (remaining.trim()) complete = false;
        break;
      }
      remaining = remaining.slice(separator[0].length).trimStart();
    }
    return { bytes, complete };
  }

  function preceding6502Registers(line, relativeStart) {
    const registers = {};
    const prefix = line.slice(0, relativeStart);
    for (const match of prefix.matchAll(/\bLD([AXY])\s*#\s*(&[0-9a-f]+|0x[0-9a-f]+|\d+)/gi)) registers[match[1].toUpperCase()] = sourceNumber(match[2]);
    return registers;
  }

  const PLATFORM_NAMES = Object.freeze({ bbc: "BBC Micro", master: "BBC Master", electron: "Acorn Electron", "risc-os": "Archimedes / RISC OS" });

  function configuredPlatform(profile = {}) {
    const machine = String(profile.machine || "").toLowerCase();
    if (/risc[ -]?os|archimedes|a3\d\d\d|a4\d\d|a5\d\d\d/.test(machine)) return "risc-os";
    if (/electron|plus\s*3/.test(machine)) return "electron";
    if (/master/.test(machine)) return "master";
    if (/bbc|beeb/.test(machine)) return "bbc";
    const description = String(profile.targetHardware || "").toLowerCase();
    if (/risc[ -]?os|archimedes|a3\d\d\d|a4\d\d|a5\d\d\d/.test(description)) return "risc-os";
    if (/electron|plus\s*3/.test(description)) return "electron";
    if (/master/.test(description)) return "master";
    if (/bbc|beeb/.test(description)) return "bbc";
    return "auto";
  }

  function platformHelp(result, profile = {}) {
    const platform = configuredPlatform(profile);
    const targetName = platform === "auto" ? "the automatic target" : PLATFORM_NAMES[platform];
    const documented = result?.platforms || [];
    const requirements = result?.requires ? ` Requirements: ${result.requires}.` : "";
    if (platform === "auto") return `The workbench target is automatic, so compatibility cannot be confirmed.${requirements}`;
    if (!documented.length) return `The catalogue cannot prove that this machine-specific operation is supported by the configured ${targetName} target.${requirements}`;
    if (!documented.includes(platform)) {
      const designedFor = documented.map(item => PLATFORM_NAMES[item] || item).join(", ");
      return `Target warning: this operation is documented for ${designedFor}, not the configured ${targetName} target. It was not designed for the current platform and, if accepted at all, may cause unexpected behaviour.${requirements}`;
    }
    return `The configured ${targetName} target is within the documented platform scope.${requirements}`;
  }

  function catalogueText(result, profile) {
    if (!result) return "";
    const detail = (result.details || []).filter(Boolean).join(". ");
    return `${result.summary}.${detail ? ` ${detail}.` : ""} ${platformHelp(result, profile)}`;
  }

  function sourceContextHelp(source, language, start, end, key, targetProfile = {}) {
    const base = lookup(language, key);
    if (!base) return base;
    const lineStart = source.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    const lineEnd = source.indexOf("\n", end);
    const line = source.slice(lineStart, lineEnd < 0 ? source.length : lineEnd);
    const relativeStart = start - lineStart;
    const relativeEnd = end - lineStart;
    const tail = line.slice(relativeEnd);
    const normal = normaliseHelpKey(key);
    const additions = [];
    if ((isStarHelpKey(key) && normal === "FX") || (normal === "OSCLI" && ["basic", "script"].includes(language))) {
      const command = normal === "OSCLI" ? tail.match(/^\s*"([^\"]*)"/)?.[1] : tail;
      const fxArguments = command == null ? [] : constantNumbers(normal === "OSCLI" ? command.replace(/^\s*FX\s*/i, "") : command);
      const [reason, suppliedX, suppliedY] = fxArguments;
      // The MOS *FX command syntax supplies zero for omitted numeric operands.
      // Direct OSBYTE assembly calls are handled separately because their
      // register contents must never be guessed.
      const x = reason == null ? null : suppliedX ?? 0;
      const y = reason == null ? null : suppliedY ?? 0;
      if (reason != null) additions.push(`This call uses OSBYTE reason ${reason}: ${catalogueText(CALL_CATALOGUE?.explainOsbyte(reason, x, y), targetProfile)}`);
    }
    if (normal === "OSCLI" && ["basic", "script"].includes(language)) {
      const command = tail.match(/^\s*"([^"]*)"/)?.[1];
      if (command) additions.push(`This call executes the MOS command ${JSON.stringify(command)}.`);
    }
    if (normal === "VDU") {
      const statement = tail.split(":", 1)[0];
      const parsed = vduBytes(statement);
      const reason = parsed.bytes[0];
      if (reason != null) {
        additions.push(`The first VDU byte is ${reason}: ${catalogueText(CALL_CATALOGUE?.explainVdu(parsed.bytes, parsed.complete), targetProfile)}`);
      }
    }
    if (["SOUND", "ENVELOPE"].includes(normal) && language === "basic") {
      const statement = tail.split(":", 1)[0];
      const decoded = CALL_CATALOGUE?.explainBasicCall(normal, constantNumbers(statement));
      if (decoded) additions.push(catalogueText(decoded, targetProfile));
    }
    if (normal === "MODE") {
      const mode = Number(tail.match(/^\s*([0-9]+)/)?.[1]);
      if (Number.isFinite(mode)) additions.push(`This selects MODE ${mode}; confirm its resolution, colour depth and memory use against the active hardware profile.`);
    }
    if (normal === "COLOUR") {
      const colour = Number(tail.match(/^\s*([0-9]+)/)?.[1]);
      if (Number.isFinite(colour)) additions.push(colour >= 128
        ? `Value ${colour} selects logical background colour ${colour - 128} on classic BBC VDU drivers.`
        : `Value ${colour} selects logical foreground colour ${colour} on classic BBC VDU drivers.`);
    }
    if (["OSBYTE", "OSWORD", "OSCLI", "OSWRCH", "VDUCHR"].includes(normal) && ["6502", "65c02", "65816"].includes(language)) {
      const registers = preceding6502Registers(line, relativeStart);
      if (normal === "OSBYTE" && registers.A != null) additions.push(`A=&${registers.A.toString(16).toUpperCase().padStart(2, "0")} selects OSBYTE reason ${registers.A}: ${catalogueText(CALL_CATALOGUE?.explainOsbyte(registers.A, registers.X, registers.Y), targetProfile)}`);
      if (normal === "OSWORD" && registers.A != null) additions.push(`A=&${registers.A.toString(16).toUpperCase().padStart(2, "0")} selects ${OSWORD_REASON_HELP[registers.A] || "a filing-system or machine-specific OSWORD reason"}; the parameter block pointer is ${registers.X == null || registers.Y == null ? "not provable" : `&${((registers.Y << 8) | registers.X).toString(16).toUpperCase().padStart(4, "0")}`} in XY.`);
      if (normal === "OSCLI") additions.push(registers.X == null || registers.Y == null ? "The command-string pointer in XY is not provable from immediate loads on this source line." : `XY points to command string address &${((registers.Y << 8) | registers.X).toString(16).toUpperCase().padStart(4, "0")}.`);
      if (["OSWRCH", "VDUCHR"].includes(normal) && registers.A != null) additions.push(`A=&${registers.A.toString(16).toUpperCase().padStart(2, "0")} is ${VDU_REASON_HELP[registers.A] ? `VDU ${registers.A}: ${VDU_REASON_HELP[registers.A]}` : registers.A >= 32 && registers.A < 127 ? `the character ${JSON.stringify(String.fromCharCode(registers.A))}` : "a raw VDU byte"}.`);
    }
    if (normal === "SYS" && language === "basic") {
      const argument = tail.match(/^\s*(?:"([^"]+)"|(&[0-9a-f]+|0x[0-9a-f]+|\d+))/i);
      if (argument?.[1]) {
        const swi = argument[1].toUpperCase();
        additions.push(`${argument[1]} will ${RISC_OS_SWI_HELP[swi] || "invoke a module or operating-system SWI whose register contract should be checked"}.`);
      } else if (argument?.[2]) additions.push(`This calls SWI &${sourceNumber(argument[2]).toString(16).toUpperCase()}; use a symbolic SWI name when possible so its contract remains visible.`);
      additions.push(platformHelp({ platforms: ["risc-os"], requires: "RISC OS and the named SWI or module" }, targetProfile));
    }
    if (!additions.length) return base;
    return { ...base, notes: [base.notes, ...additions].filter(Boolean).join(" ") };
  }

  function disassemblyInstructionHelp(row, architecture) {
    const mnemonic = normaliseHelpKey(row?.mnemonic || "DATA") || "DATA";
    const operand = String(row?.operand || "").trim();
    const known = lookup(architecture, mnemonic);
    let summary = known?.summary || `${architecture.toUpperCase()} decoded operation.`;
    if (["6502", "65c02", "65816"].includes(architecture) && !ASM_HELP[mnemonic] && !INLINE_ASSEMBLER_HELP[mnemonic]) {
      if (/^LD[AXY]$/.test(mnemonic)) summary = `Loads the ${mnemonic.at(-1)} register and updates zero and negative flags.`;
      else if (/^ST[AXYZ]$/.test(mnemonic)) summary = `Stores the ${mnemonic.at(-1)} register to the destination without changing it.`;
      else if (/^(ADC|SBC)$/.test(mnemonic)) summary = `${mnemonic === "ADC" ? "Adds" : "Subtracts"} the operand with the carry flag and updates arithmetic flags.`;
      else if (/^(CMP|CPX|CPY)$/.test(mnemonic)) summary = "Compares a register with the operand by updating flags without retaining the subtraction.";
      else if (/^(AND|ORA|EOR|BIT|TRB|TSB)$/.test(mnemonic)) summary = "Performs a bitwise or bit-test operation and updates the applicable processor flags.";
      else if (/^(ASL|LSR|ROL|ROR)$/.test(mnemonic)) summary = "Shifts or rotates the accumulator or memory operand through the carry flag.";
      else if (/^(B(?:CC|CS|EQ|MI|NE|PL|VC|VS|RA|RL)|BBR[0-7]|BBS[0-7])$/.test(mnemonic)) summary = "Branches to the decoded target when its processor condition is satisfied.";
      else if (/^(INC|DEC|IN[AXY]|DE[AXY])$/.test(mnemonic)) summary = "Increments or decrements a register or memory value and updates status flags.";
      else if (/^(TAX|TAY|TSX|TXA|TXS|TYA|TCD|TCS|TDC|TSC|TXY|TYX)$/.test(mnemonic)) summary = "Transfers a value between processor registers.";
      else if (/^(PHA|PHP|PHX|PHY|PHB|PHD|PHK|PLA|PLP|PLX|PLY|PLB|PLD|PEA|PEI|PER)$/.test(mnemonic)) summary = "Pushes to or pulls from the processor stack.";
      else if (/^(CLC|CLD|CLI|CLV|SEC|SED|SEI|REP|SEP)$/.test(mnemonic)) summary = "Changes processor status flags that affect subsequent instructions.";
      else if (/^(JSR|JSL)$/.test(mnemonic)) summary = "Calls the decoded subroutine and records a return address on the stack.";
      else if (/^(JMP|JML)$/.test(mnemonic)) summary = "Transfers execution to the decoded destination without a normal fall-through.";
      else if (/^(RTS|RTI|RTL)$/.test(mnemonic)) summary = "Returns using state previously saved on the processor stack.";
    } else if (architecture === "arm" && !ASM_HELP[mnemonic] && !INLINE_ASSEMBLER_HELP[mnemonic]) {
      const base = mnemonic.replace(/(?:EQ|NE|CS|HS|CC|LO|MI|PL|VS|VC|HI|LS|GE|LT|GT|LE|AL)$/, "").replace(/S$/, "");
      if (/^(LDR|LDRB|LDRH|LDRSB|LDRSH)$/.test(base)) summary = "Loads a register from the decoded memory address.";
      else if (/^(STR|STRB|STRH)$/.test(base)) summary = "Stores a register to the decoded memory address.";
      else if (/^(LDM|STM)/.test(base)) summary = "Transfers a register list to or from consecutive memory locations.";
      else if (/^(B|BL|BLX|BX)$/.test(base)) summary = base === "B" ? "Branches to the decoded destination." : "Changes control flow using the decoded target or register.";
      else if (/^(CMP|CMN|TST|TEQ)$/.test(base)) summary = "Tests or compares operands and updates condition flags without keeping a result.";
      else if (/^(ADD|ADC|SUB|SBC|RSB|RSC|MUL|MLA|UMULL|SMULL)$/.test(base)) summary = "Performs an arithmetic operation on the decoded registers or immediate operand.";
      else if (/^(AND|EOR|ORR|BIC|MOV|MVN)$/.test(base)) summary = "Performs a data-processing operation and writes the decoded destination register.";
      else if (/^(SWI|SVC)$/.test(base)) summary = "Requests an operating-system or supervisor service using the decoded reason value.";
    } else if (architecture === "m68k" && !ASM_HELP[mnemonic] && !INLINE_ASSEMBLER_HELP[mnemonic]) {
      const base = mnemonic.replace(/\.(?:B|W|L|S)$/, "");
      if (/^MOVE/.test(base)) summary = "Moves the decoded source value to the destination register or memory location.";
      else if (/^(ADD|SUB|MUL|DIV|NEG|CMP)/.test(base)) summary = "Performs an arithmetic or comparison operation using the decoded size and operands.";
      else if (/^(AND|OR|EOR|NOT|BTST|BSET|BCLR|BCHG)/.test(base)) summary = "Performs a logical or bit operation on the decoded destination.";
      else if (/^(AS|LS|RO|ROX)/.test(base)) summary = "Shifts or rotates the decoded register or memory operand.";
      else if (/^(B|DB|S)(?:RA|SR|CC|CS|EQ|GE|GT|HI|LE|LS|LT|MI|NE|PL|VC|VS)/.test(base)) summary = "Applies the encoded condition to branch, loop or set a result byte.";
      else if (/^(JMP|JSR|RTS|RTE|RTR|LINK|UNLK)$/.test(base)) summary = "Changes control flow or manages a subroutine stack frame.";
      else if (/^(TRAP|TRAPV|CHK|STOP|RESET)$/.test(base)) summary = "Invokes a processor exception or privileged control operation.";
    }
    let addressing = "No explicit operand; the operation uses implied processor state.";
    if (operand) {
      if (operand.startsWith("#")) addressing = `Immediate operand ${operand}.`;
      else if (["6502", "65c02", "65816"].includes(architecture) && /^\(.*\)(?:,[XY])?$/i.test(operand)) addressing = `Indirect ${architecture.toUpperCase()} addressing through ${operand}.`;
      else if (["6502", "65c02", "65816"].includes(architecture) && /,[XY]$/i.test(operand)) addressing = `Indexed ${architecture.toUpperCase()} addressing using ${operand.at(-1).toUpperCase()}.`;
      else if (architecture === "arm" && operand.includes("[")) addressing = `ARM register-indirect memory operand ${operand}.`;
      else if (architecture === "arm" && operand.includes("{")) addressing = `ARM register-list operand ${operand}.`;
      else if (architecture === "m68k" && /\([^)]*A\d[^)]*\)/i.test(operand)) addressing = `68000 address-register memory operand ${operand}.`;
      else addressing = `Decoded operand: ${operand}.`;
    }
    const context = [addressing];
    if (row?.comment) context.push(`Analysis: ${row.comment}.`);
    if (Array.isArray(row?.references) && row.references.length) context.push(`Referenced from ${row.references.map(value => `&${Number(value).toString(16).toUpperCase()}`).join(", ")}.`);
    if (row?.bytes) context.push(`Encoding: ${row.bytes}.`);
    return {
      key: mnemonic,
      summary,
      syntax: `${mnemonic}${operand ? ` ${operand}` : ""}`,
      requirements: known?.requirements || `Valid ${architecture.toUpperCase()} code for the selected processor variant.`,
      notes: [known?.notes, ...context].filter(Boolean).join(" "),
    };
  }

  const token = (type, text, start, helpKey = "", helpLanguage = "") => ({ type, text, start, end: start + text.length, helpKey, helpLanguage });

  // Help keys deliberately discard punctuation, but BBC BASIC's trailing `%`
  // is semantic: it marks an integer variable. Keep lexical classification
  // separate so names such as page%, load% and print% cannot be mistaken for
  // the PAGE, LOAD and PRINT commands during highlighting or refactoring.
  const isBasicKeywordToken = (raw, key) => BASIC_LANGUAGE?.isKeywordToken(raw) ?? (!/%$/.test(raw) && BASIC_KEYWORDS.has(key));

  function inlineMnemonic(raw, architecture) {
    const key = normaliseHelpKey(raw);
    if (architecture === "arm") {
      if (ASSEMBLY_LANGUAGE.isMnemonic("arm", key)) return key;
      const withoutCondition = key.replace(/(?:EQ|NE|CS|HS|CC|LO|MI|PL|VS|VC|HI|LS|GE|LT|GT|LE|AL)$/, "").replace(/S$/, "");
      return ASSEMBLY_LANGUAGE.isMnemonic("arm", withoutCondition) ? withoutCondition : "";
    }
    if (architecture === "m68k") {
      const base = key.replace(/\.(?:B|W|L|S)$/, "");
      return ASSEMBLY_LANGUAGE.isMnemonic("m68k", key) || ASSEMBLY_LANGUAGE.isMnemonic("m68k", base) ? key : "";
    }
    return ASSEMBLY_LANGUAGE.isMnemonic(architecture, key) ? key : "";
  }

  function sourceTokens(text, language, inlineAssemblyLanguage = "6502") {
    const tokens = [];
    let lineStart = 0;
    let inlineAssembler = false;
    for (const line of String(text).split("\n")) {
      let offset = 0;
      let assemblerStatementStart = inlineAssembler;
      const number = language === "basic" ? line.match(/^\s*(\d+)/) : null;
      if (number) tokens.push(token("line-number", number[1], lineStart + number.index + number[0].lastIndexOf(number[1])));
      while (offset < line.length) {
        if (language === "basic" && line[offset] === "[") { inlineAssembler = true; assemblerStatementStart = true; offset += 1; continue; }
        if (language === "basic" && inlineAssembler && line[offset] === "]") { inlineAssembler = false; assemblerStatementStart = false; offset += 1; continue; }
        if (language === "basic" && inlineAssembler && line[offset] === "\\") {
          tokens.push(token("comment", line.slice(offset), lineStart + offset));
          break;
        }
        if (line[offset] === '"') {
          let end = offset + 1;
          while (end < line.length) {
            if (line[end] === '"') { end += 1; break; }
            end += 1;
          }
          tokens.push(token("string", line.slice(offset, end), lineStart + offset));
          offset = end;
          continue;
        }
        const remainder = line.slice(offset);
        const compactStar = language === "basic" && !inlineAssembler && remainder.startsWith("*") ? starCommandPrefix(remainder) : "";
        const basicLexeme = language === "basic" && !inlineAssembler && /^[A-Za-z]/.test(remainder)
          ? BASIC_LANGUAGE?.lexemeAt(remainder)
          : "";
        const word = compactStar ? [`*${compactStar}`] : basicLexeme ? [basicLexeme] : remainder.match(/^(?:\*?[A-Za-z][A-Za-z0-9_$%]*|&[0-9A-Fa-f]+|\d+(?:\.\d+)?)/);
        if (!word) {
          if (inlineAssembler && line[offset] === ":") assemblerStatementStart = true;
          offset += 1;
          continue;
        }
        const raw = word[0];
        const key = normaliseHelpKey(raw);
        if (language === "basic" && !inlineAssembler && key === "REM" && isBasicKeywordToken(raw, key)) {
          tokens.push(token("comment", line.slice(offset), lineStart + offset, "REM"));
          break;
        }
        const isNumber = /^\d|^&/.test(raw);
        if (language === "basic" && inlineAssembler) {
          const mnemonic = /^[A-Za-z]+$/.test(raw) && line[offset - 1] !== "." ? inlineMnemonic(raw, inlineAssemblyLanguage) : "";
          const api = /^[A-Za-z]+$/.test(raw) && MOS_HELP[key] ? key : (/^&[0-9A-F]+$/i.test(raw) ? MOS_ADDRESS_HELP.get(Number.parseInt(raw.slice(1), 16)) : "");
          if (api && inlineAssemblyLanguage === "6502") tokens.push(token("api", raw, lineStart + offset, api, "6502"));
          else if (mnemonic) { tokens.push(token("keyword", raw, lineStart + offset, mnemonic, inlineAssemblyLanguage)); assemblerStatementStart = false; }
          else if (INLINE_ASSEMBLER_HELP[key]) { tokens.push(token("keyword", raw, lineStart + offset, key, inlineAssemblyLanguage)); assemblerStatementStart = false; }
          else if (assemblerStatementStart && /^[A-Za-z]+$/.test(raw) && line[offset - 1] !== ".") {
            tokens.push(token("keyword", raw, lineStart + offset, key, inlineAssemblyLanguage));
            assemblerStatementStart = false;
          }
          else if (isNumber) tokens.push(token("number", raw, lineStart + offset));
          if (/[$%]$/.test(raw) && /^\s*=/.test(line.slice(offset + raw.length))) assemblerStatementStart = false;
          offset += raw.length;
          continue;
        }
        const starHelpKey = raw.startsWith("*") ? `*${key}` : "";
        const isKeyword = language === "basic" ? (isBasicKeywordToken(raw, key) || Boolean(starHelpKey)) : language === "script" ? (SCRIPT_COMMANDS.has(key) || (offset === (line.match(/^\s*/)?.[0].length || 0) && raw.startsWith("*"))) : false;
        if (isNumber) tokens.push(token("number", raw, lineStart + offset));
        else if (isKeyword) tokens.push(token("keyword", raw, lineStart + offset, starHelpKey || key));
        else if (/^(?:PROC|FN)/i.test(raw)) tokens.push(token("symbol", raw, lineStart + offset, raw.match(/^(PROC|FN)/i)?.[1]));
        offset += raw.length;
      }
      lineStart += line.length + 1;
    }
    return tokens.sort((left, right) => left.start - right.start || right.end - left.end);
  }

  function highlightedHtml(text, tokens) {
    let cursor = 0;
    const output = [];
    for (const item of tokens) {
      if (item.start < cursor) continue;
      output.push(esc(text.slice(cursor, item.start)));
      const helpAttributes = item.helpKey ? ` data-help-key="${esc(item.helpKey)}"${item.helpLanguage ? ` data-help-language="${esc(item.helpLanguage)}"` : ""} data-token-start="${item.start}" data-token-end="${item.end}"` : "";
      output.push(`<span class="code-token code-token-${item.type}${item.helpKey ? " code-help-token" : ""}"${helpAttributes}>${esc(item.text)}</span>`);
      cursor = item.end;
    }
    output.push(esc(text.slice(cursor)));
    return `${output.join("")}${text.endsWith("\n") ? "\n" : ""}`;
  }

  function highlightedSourceLines(lines, language, inlineAssemblyLanguage) {
    const source = lines.join("\n");
    const tokens = sourceTokens(source, language, inlineAssemblyLanguage);
    let offset = 0;
    return lines.map(line => {
      const end = offset + line.length;
      const local = tokens.filter(item => item.start >= offset && item.end <= end).map(item => ({
        ...item, start: item.start - offset, end: item.end - offset,
      }));
      const markup = highlightedHtml(line, local);
      offset = end + 1;
      return markup;
    });
  }

  function basicInlineAssemblerLines(text) {
    let inside = false;
    return String(text).split("\n").map(line => {
      let flagged = inside;
      let quoted = false;
      for (let index = 0; index < line.length; index += 1) {
        if (line[index] === '"') {
          if (quoted && line[index + 1] === '"') { index += 1; continue; }
          quoted = !quoted;
          continue;
        }
        if (quoted) continue;
        if (!inside && /^REM(?![$%])/i.test(line.slice(index)) && (index === 0 || /[^A-Za-z0-9_$%]/.test(line[index - 1]))) break;
        if (inside && line[index] === "\\") break;
        if (line[index] === "[") { inside = true; flagged = true; }
        else if (inside && line[index] === "]") { flagged = true; inside = false; }
      }
      return flagged;
    });
  }

  function diagnostics(text, language, dialect = "BBC BASIC II") {
    const issues = [];
    const add = (severity, line, message, offset = 0) => issues.push({ severity, line, message, offset });
    const lines = String(text).split("\n");
    const lineOffsets = [];
    lines.reduce((offset, line) => { lineOffsets.push(offset); return offset + line.length + 1; }, 0);
    lines.forEach((line, index) => {
      const quotes = (line.match(/"/g) || []).length;
      if (quotes % 2) add("error", index + 1, "String quotation mark is not closed.", lineOffsets[index] + line.indexOf('"'));
      if (language === "script" && /(^|:)\s*[RL]\./i.test(line)) add("warning", index + 1, "R. or L. is filing-system dependent; use RUN or LOAD when moving this script to ADFS.", lineOffsets[index]);
      if (language === "script" && /\bCHAIN\s*"!?BOOT"/i.test(line)) add("warning", index + 1, "CHAIN expects tokenised BASIC. A command-script !BOOT normally needs *EXEC.", lineOffsets[index]);
    });
    if (language !== "basic") return issues;
    const numbered = [];
    const lineSet = new Set();
    lines.forEach((line, index) => {
      if (!line.trim()) return;
      const match = line.match(/^\s*(\d+)\s/);
      if (!match) return add("error", index + 1, "BBC BASIC source lines require a line number followed by a space.", lineOffsets[index]);
      const value = Number(match[1]);
      if (lineSet.has(value)) add("error", index + 1, `Line number ${value} is duplicated.`, lineOffsets[index]);
      lineSet.add(value);
      if (numbered.length && value <= numbered.at(-1).value) add("error", index + 1, `Line ${value} is not greater than the preceding line number.`, lineOffsets[index]);
      numbered.push({ value, index: index + 1, text: line, offset: lineOffsets[index] });
    });
    numbered.forEach(row => {
      for (const match of row.text.matchAll(/\b(?:GOTO|GOSUB|RESTORE)\s+(\d+)/gi)) {
        if (!lineSet.has(Number(match[1]))) add("error", row.index, `Referenced line ${match[1]} does not exist.`, row.offset + match.index);
      }
    });
    const definitions = new Set([...text.matchAll(/\bDEF\s*PROC([A-Za-z][A-Za-z0-9_]*)/gi)].map(match => match[1].toUpperCase()));
    for (const match of text.matchAll(/\bPROC([A-Za-z][A-Za-z0-9_]*)/gi)) {
      if (text.slice(Math.max(0, match.index - 5), match.index).match(/DEF\s*$/i)) continue;
      if (!definitions.has(match[1].toUpperCase())) add("warning", text.slice(0, match.index).split("\n").length, `Procedure ${match[1]} has no DEF PROC definition in this file.`, match.index);
    }
    const masked = sourceMask(text, language);
    for (const match of text.matchAll(/\bDEF\s*(PROC|FN)([A-Za-z][A-Za-z0-9_]*)/gi)) {
      const name = `${match[1]}${match[2]}`;
      const calls = [...masked.matchAll(new RegExp(`\\b${name}\\b`, "gi"))].filter(call => call.index !== match.index);
      if (!calls.length) add("info", text.slice(0, match.index).split("\n").length, `${name.toUpperCase()} is defined but not called in this file.`, match.index);
    }
    const procedureDefinitions = [...masked.matchAll(/\bDEF\s*PROC[A-Za-z][A-Za-z0-9_]*/gi)].length;
    const procedureEnds = [...masked.matchAll(/\bENDPROC\b/gi)].length;
    if (procedureDefinitions !== procedureEnds) add("warning", 1, `${procedureDefinitions} DEF PROC definition${procedureDefinitions === 1 ? "" : "s"} but ${procedureEnds} ENDPROC command${procedureEnds === 1 ? "" : "s"} were found.`, 0);
    numbered.forEach((row, index) => {
      if (!/\b(?:END|STOP|GOTO\s*\d+)\s*$/i.test(row.text)) return;
      const next = numbered[index + 1];
      if (next && ![...masked.matchAll(/\b(?:GOTO|GOSUB|RESTORE|THEN)\s*(\d+)/gi)].some(match => Number(match[1]) === next.value)) {
        add("info", next.index, `Line ${next.value} may be unreachable after an unconditional transfer.`, next.offset);
      }
    });
    if (BASIC_LANGUAGE) {
      issues.push(...advancedBasicDiagnostics(text));
      const profile = BASIC_LANGUAGE.dialectProfile(dialect);
      BASIC_LANGUAGE.scan(text).filter(token => token.type === "keyword").forEach(token => {
        const required = Number(BASIC_LANGUAGE.KEYWORD_GENERATION[token.name] || 1);
        if (required > Number(profile.generation || 2)) issues.push({
          severity: "warning", line: token.line, offset: token.start,
          message: `${token.name} requires BBC BASIC ${required === 5 ? "V or later" : required}; this file is ${dialect}.`,
        });
      });
    }
    return issues;
  }

  function advancedBasicDiagnostics(text) {
    const issues = [];
    const scannedTokens = BASIC_LANGUAGE.scan(text);
    const masked = BASIC_LANGUAGE.maskStringsAndComments(text);
    const dimmed = new Set();
    const forStack = [];
    const lineOffsets = [];
    text.split("\n").reduce((offset, line) => { lineOffsets.push(offset); return offset + line.length + 1; }, 0);
    text.split("\n").forEach((line, index) => {
      const lineOffset = lineOffsets[index];
      const code = masked.slice(lineOffset, lineOffset + line.length).replace(/^\s*\d+\s*/, "");
      const lineEnd = lineOffset + line.length;
      const lineTokens = scannedTokens.filter(token => token.start >= lineOffset && token.start < lineEnd);
      for (const [tokenIndex, token] of lineTokens.entries()) {
        if (token.type !== "identifier" || !/^\s*\(/.test(masked.slice(token.end, lineEnd))) continue;
        const name = token.text.toUpperCase();
        const previous = lineTokens[tokenIndex - 1];
        const followsDim = previous?.type === "keyword" && previous.name === "DIM";
        // PROCname(...) and FNname(...) are indivisible user symbols in the
        // scanner, not arrays. Built-in functions such as TAB(...) are keyword
        // tokens, which also prevents compact PRINTTAB(...) being mistaken for
        // an array reference.
        if (followsDim) dimmed.add(name);
        else if (!/^(?:PROC|FN).+/i.test(token.text) && !dimmed.has(name)) {
          issues.push({ severity: "warning", line: index + 1, offset: token.start, message: `${token.text} is used as an array before a preceding DIM was found.` });
        }
      }
      for (const match of code.matchAll(/\bFOR\s*([A-Za-z][A-Za-z0-9_]*[$%]?)/gi)) forStack.push({ name: match[1].toUpperCase(), line: index + 1 });
      for (const match of code.matchAll(/\bNEXT\s*([A-Za-z][A-Za-z0-9_]*[$%]?)/gi)) {
        const active = forStack.pop();
        if (active && active.name !== match[1].toUpperCase()) issues.push({ severity: "warning", line: index + 1, offset: lineOffset + match.index, message: `NEXT ${match[1]} closes the active FOR ${active.name} from line ${active.line}.` });
      }
    });
    // A, A% and A$ are deliberately distinct variables in BBC BASIC, so
    // sharing a base name across types is not itself suspicious. Likewise, do
    // not report apparently unused assignments. BBC BASIC exposes state
    // through pseudo-variables such as HIMEM, PAGE, PTR and TIME; A%, X%, Y%,
    // P% and O% also have implicit CALL, USR and assembler meanings. Programs
    // can pass any global to chained overlays or machine code, so absence of a
    // later textual read is not evidence of a defect.
    return issues.slice(0, 500);
  }

  function symbols(text, language) {
    const rows = [];
    if (language === "basic") {
      for (const match of text.matchAll(/^\s*(\d+)\s/gm)) rows.push({ name: `Line ${match[1]}`, kind: "line", offset: match.index });
      for (const match of text.matchAll(/\bDEF\s*(PROC|FN)([A-Za-z][A-Za-z0-9_]*)/gi)) rows.push({ name: `${match[1].toUpperCase()}${match[2]}`, kind: "definition", offset: match.index });
    } else if (language === "script") {
      for (const match of text.matchAll(/^\s*\*?(DIR|LIB|DRIVE|EXEC|RUN|LOAD|CHAIN)\s+([^:\r\n]+)/gim)) rows.push({ name: `${match[1].toUpperCase()} ${match[2].trim()}`, kind: "command", offset: match.index });
    }
    return rows.slice(0, 500);
  }

  function identifierAt(text, offset, language) {
    const allowed = language === "basic" ? /[A-Za-z0-9_$%]/ : /[A-Za-z0-9_.$]/;
    let start = Math.max(0, Math.min(offset, text.length));
    let end = start;
    while (start > 0 && allowed.test(text[start - 1])) start -= 1;
    while (end < text.length && allowed.test(text[end])) end += 1;
    const name = text.slice(start, end);
    return /^[A-Za-z_.][A-Za-z0-9_.$%]*$/.test(name) ? { name, start, end } : null;
  }

  function sourceMask(text, language) {
    if (language === "basic" && BASIC_LANGUAGE) return BASIC_LANGUAGE.maskStringsAndComments(text);
    const mask = [...text].map(character => character === "\n" ? "\n" : character);
    let quoted = false;
    for (let index = 0; index < text.length; index += 1) {
      if (text[index] === "\n") { quoted = false; continue; }
      if (text[index] === '"') { mask[index] = " "; quoted = !quoted; continue; }
      if (quoted) { mask[index] = " "; continue; }
      const rest = text.slice(index);
      if ((language === "basic" && /^REM(?![$%])/i.test(rest)) ||
          (language === "script" && /^\|/.test(rest))) {
        while (index < text.length && text[index] !== "\n") { mask[index] = " "; index += 1; }
        index -= 1;
      }
    }
    return mask.join("");
  }

  function symbolReferences(text, offset, language) {
    const selected = identifierAt(text, offset, language);
    if (!selected) return { name: "", rows: [] };
    const masked = sourceMask(text, language);
    const escaped = selected.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(`(?<![A-Za-z0-9_.$%])${escaped}(?![A-Za-z0-9_.$%])`, "giu");
    const rows = [...masked.matchAll(pattern)].map(match => ({
      offset: match.index,
      line: text.slice(0, match.index).split("\n").length,
      context: text.slice(text.lastIndexOf("\n", match.index - 1) + 1, text.indexOf("\n", match.index) < 0 ? text.length : text.indexOf("\n", match.index)).trim(),
    }));
    return { name: selected.name, rows };
  }

  function basicStructureRows(text) {
    let assembler = false;
    return String(text).split("\n").map(line => {
      const masked = [...line];
      let quoted = false;
      for (let index = 0; index < line.length; index += 1) {
        const character = line[index];
        if (assembler) {
          masked[index] = " ";
          if (character === "\\") { masked.fill(" ", index); break; }
          if (character === "]") assembler = false;
          continue;
        }
        if (character === '"') {
          masked[index] = " ";
          if (quoted && line[index + 1] === '"') { masked[index + 1] = " "; index += 1; continue; }
          quoted = !quoted;
          continue;
        }
        if (quoted) { masked[index] = " "; continue; }
        if (character === "[") { masked[index] = " "; assembler = true; continue; }
        if (/^REM(?![$%])/i.test(line.slice(index)) && (index === 0 || /[^A-Za-z0-9_$%]/.test(line[index - 1]))) {
          masked.fill(" ", index);
          break;
        }
      }
      const code = masked.join("").replace(/^\s*\d+\s*/, "");
      const events = [];
      code.split(":").forEach((part, statementIndex) => {
        const statement = part.trim();
        if (!statement) return;
        const event = { leading: statementIndex === 0, statement };
        let match = statement.match(/^DEF\s*PROC([A-Za-z][A-Za-z0-9_]*)/i);
        if (match) return events.push({ ...event, kind: "open", type: "procedure", label: `PROC${match[1]}` });
        match = statement.match(/^DEF\s*FN([A-Za-z][A-Za-z0-9_]*)/i);
        if (match) {
          const remainder = statement.slice(match[0].length);
          if (!remainder.includes("=")) events.push({ ...event, kind: "open", type: "function", label: `FN${match[1]}` });
          return;
        }
        if (/^ENDPROC(?![$%])/i.test(statement)) return events.push({ ...event, kind: "close", type: "procedure" });
        if (/^=/.test(statement)) return events.push({ ...event, kind: "close", type: "function" });
        match = statement.match(/^FOR\s*([A-Za-z][A-Za-z0-9_$%]*)(?=\s*=)/i);
        if (match) return events.push({ ...event, kind: "open", type: "for", label: `${match[1]} loop` });
        if (/^NEXT(?![$%])(?:\b|(?=[A-Za-z]))/i.test(statement)) return events.push({ ...event, kind: "close", type: "for" });
        if (/^REPEAT(?![$%])/i.test(statement)) return events.push({ ...event, kind: "open", type: "repeat", label: "REPEAT loop" });
        if (/^UNTIL(?![$%])(?:\b|(?=[A-Za-z]))/i.test(statement)) return events.push({ ...event, kind: "close", type: "repeat" });
        if (/^IF(?![$%])(?:\b|(?=[A-Za-z]))/i.test(statement) && /\bTHEN\s*$/i.test(statement)) return events.push({ ...event, kind: "open", type: "if", label: "IF block" });
        if (/^ELSE(?![$%])/i.test(statement)) return events.push({ ...event, kind: "branch", type: "if" });
        if (/^ENDIF(?![$%])/i.test(statement)) return events.push({ ...event, kind: "close", type: "if" });
        if (/^CASE(?![$%])(?:\b|(?=[A-Za-z]))/i.test(statement)) return events.push({ ...event, kind: "open", type: "case", label: "CASE block" });
        if (/^(?:WHEN(?![$%])(?=\b|[A-Za-z0-9_&])|OTHERWISE(?![$%]))/i.test(statement)) return events.push({ ...event, kind: "branch", type: "case" });
        if (/^ENDCASE(?![$%])/i.test(statement)) return events.push({ ...event, kind: "close", type: "case" });
        if (/^WHILE(?![$%])(?:\b|(?=[A-Za-z]))/i.test(statement)) return events.push({ ...event, kind: "open", type: "while", label: "WHILE loop" });
        if (/^ENDWHILE(?![$%])/i.test(statement)) events.push({ ...event, kind: "close", type: "while" });
      });
      return { line, events };
    });
  }

  function foldBlocks(text, language) {
    if (language !== "basic") return [];
    const rows = basicStructureRows(text);
    const offsets = [];
    rows.reduce((offset, row) => { offsets.push(offset); return offset + row.line.length + 1; }, 0);
    const stack = [];
    const blocks = [];
    rows.forEach((row, lineIndex) => row.events.forEach(event => {
      if (event.kind === "open") { stack.push({ ...event, startLine: lineIndex }); return; }
      if (event.kind !== "close") return;
      const stackIndex = stack.findLastIndex(item => item.type === event.type);
      if (stackIndex < 0) return;
      const opener = stack[stackIndex];
      stack.splice(stackIndex);
      if (lineIndex <= opener.startLine) return;
      blocks.push({
        id: `${opener.type}:${opener.startLine}:${lineIndex}`,
        type: opener.type,
        label: opener.label,
        startLine: opener.startLine,
        endLine: lineIndex,
        start: offsets[opener.startLine],
        end: offsets[lineIndex] + rows[lineIndex].line.length,
      });
    }));
    return blocks.sort((left, right) => left.startLine - right.startLine || right.endLine - left.endLine);
  }

  function basicStatements(body) {
    const normal = String(body)
      .replace(/^IF(?![$%])(?=\S)/i, "$& ")
      .replace(/\bTHEN(?![$%])(?=\d)/gi, "$& ")
      .replace(/(\d)ELSE(?![$%])(?=\S)/gi, "$1 ELSE ")
      .replace(/\bELSE(?![$%])(?=[A-Za-z])/gi, "$& ");
    const statements = BASIC_LANGUAGE
      ? BASIC_LANGUAGE.splitStatements(normal).map(statement => statement.text)
      : [normal.trim()].filter(Boolean);
    return statements.map(statement => statement
      .replace(/^IF(?![$%])(?=\S)/i, "$& ")
      .replace(/\bTHEN(?![$%])(?=\S)/gi, "$& ")
      .replace(/(\d)ELSE(?![$%])(?=\S)/gi, "$1 ELSE "));
  }

  function keywordOutsideQuotes(text, keyword, from = 0) {
    let quoted = false;
    const upper = String(text).toUpperCase();
    for (let index = from; index <= text.length - keyword.length; index += 1) {
      if (text[index] === '"') quoted = !quoted;
      if (quoted || upper.slice(index, index + keyword.length) !== keyword) continue;
      const before = index === 0 ? " " : text[index - 1];
      const after = text[index + keyword.length] || " ";
      if (!/[A-Z0-9_$%]/i.test(before) && !/[A-Z0-9_$%]/i.test(after)) return index;
    }
    return -1;
  }

  function inlineIfElseChain(body, nextNumber) {
    if (nextNumber == null || !/^\s*IF(?![$%])/i.test(body)) return null;
    const branches = [];
    let remaining = String(body).trim();
    while (/^IF(?![$%])/i.test(remaining)) {
      const thenAt = keywordOutsideQuotes(remaining, "THEN", 2);
      const elseAt = keywordOutsideQuotes(remaining, "ELSE", thenAt >= 0 ? thenAt + 4 : 2);
      if (elseAt < 0) return null;
      let condition;
      let action;
      if (thenAt >= 0) {
        condition = remaining.slice(2, thenAt).trim();
        action = remaining.slice(thenAt + 4, elseAt).trim();
      } else {
        const beforeElse = remaining.slice(2, elseAt).trim();
        const falseBranch = remaining.slice(elseAt + 4).trim();
        const assignment = falseBranch.match(/^([A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?)\s*=/);
        let actionAt = null;
        if (assignment) {
          actionAt = [...beforeElse.matchAll(/(?:^|\s)([A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?)\s*=/g)].at(-1) || null;
        } else {
          actionAt = [...beforeElse.matchAll(/(?:^|\s)(PRINT|OSCLI|CALL|VDU|CHAIN|GOTO|GOSUB|RETURN|PROC[A-Za-z0-9_]*|RUN|MODE|SOUND|ENVELOPE|PLOT|DRAW|MOVE|GCOL|CLS|CLG|INPUT|READ|RESTORE|ERROR|STOP|END|BPUT)\b/gi)].at(-1) || null;
        }
        if (!actionAt) return null;
        const leadingSpace = /^\s/.test(actionAt[0]) ? 1 : 0;
        const boundary = actionAt.index + leadingSpace;
        condition = beforeElse.slice(0, boundary).trim();
        action = beforeElse.slice(boundary).trim();
      }
      if (!condition || !action || /^IF(?![$%])/i.test(action)) return null;
      branches.push({ condition, action });
      remaining = remaining.slice(elseAt + 4).trim();
    }
    if (!branches.length || !remaining) return null;
    const actions = branches.map(branch => basicStatements(branch.action));
    const finalActions = basicStatements(remaining);
    if (actions.some(items => !items.length) || !finalActions.length) return null;
    const starts = [];
    let nextStart = 0;
    actions.forEach(items => {
      starts.push(nextStart);
      nextStart += 1 + items.length + 1;
    });
    const finalStart = nextStart;
    const statements = [];
    branches.forEach(({ condition }, index) => {
      statements.push(`IF NOT(${condition}) THEN {{SELF:${starts[index + 1] ?? finalStart}}}`);
      statements.push(...actions[index]);
      statements.push("GOTO {{END}}");
    });
    statements.push(...finalActions);
    return statements;
  }

  function basicStartsStatement(text) {
    const value = String(text).trimStart();
    if (!value) return false;
    if (value.startsWith("*")) return true;
    if (/^[A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?\s*=/.test(value)) return true;
    // Tokenised BBC BASIC listings commonly omit the space between a command
    // and its first argument: PROCmove, VDU7, COLOUR129, CHAINf$ and so on.
    // These are statements, not computed line-number expressions after THEN.
    return /^(?:BPUT|CALL|CASE|CHAIN|CLEAR|CLG|CLOSE|CLS|COLOUR|DATA|DIM|DRAW|ENDCASE|ENDIF|ENDPROC|ENDWHILE|END|ENVELOPE|ERROR|FOR|GCOL|GOSUB|GOTO|IF|INPUT|LET|LOCAL|MODE|MOVE|NEXT|ON|ORIGIN|OSCLI|OTHERWISE|PLOT|PRINT|PROC[A-Za-z0-9_]*|READ|REM|REPEAT|REPORT|RESTORE|RETURN|RUN|SOUND|STOP|TRACE|UNTIL|VDU|WHEN|WHILE|WIDTH)/i.test(value);
  }

  function inlineIfExpansion(statements, nextNumber) {
    const ifIndex = statements.findIndex(statement => /^IF(?![$%])/i.test(statement));
    if (ifIndex < 0) return statements;
    const statement = statements[ifIndex];
    const prefix = statements.slice(0, ifIndex);
    const tail = statements.slice(ifIndex + 1);
    const directElse = statement.match(/^IF(?![$%])\s*(.*?)\s+THEN\s*(\d+)\s+ELSE\s*(.+)$/i);
    if (directElse) {
      const falseAction = /^\d+\s*$/.test(directElse[3]) ? `GOTO ${directElse[3].trim()}` : directElse[3];
      return [...prefix, `IF ${directElse[1]} THEN ${directElse[2]}`, falseAction, ...tail];
    }
    if (nextNumber == null || /\bELSE\b/i.test(statement)) return null;
    let condition = "";
    let action = "";
    const withThen = statement.match(/^IF(?![$%])\s*(.*?)\s+THEN\s*(.+)$/i);
    if (withThen) {
      [, condition, action] = withThen;
    } else {
      // BBC BASIC permits THEN to be omitted. Only split when the beginning of
      // the consequent is a proven statement command; guessing where an
      // arbitrary assignment starts could change the condition.
      const actionAt = [...statement.matchAll(/\s+/g)]
        .map(space => space.index + space[0].length)
        .find(index => basicStartsStatement(statement.slice(index)));
      if (actionAt != null) {
        condition = statement.slice(2, actionAt).trim();
        action = statement.slice(actionAt).trim();
      } else {
        const assignments = [...statement.matchAll(/\s+([A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?)\s*=/g)];
        const assignment = assignments.at(-1);
        if (!assignment) return null;
        const boundary = assignment.index + 1;
        condition = statement.slice(2, boundary).trim();
        action = statement.slice(boundary).trim();
      }
    }
    if (!condition || !action) return null;
    // A bare number after THEN is a destination, not an executable statement
    // that can be moved onto its own line.
    if (/^\d+\s*$/.test(action)) return null;
    return [...prefix, `IF NOT(${condition}) THEN ${nextNumber}`, action, ...tail];
  }

  function tangledBasicLine(line, nextNumber = null) {
    const match = String(line).match(/^\s*(\d+)\s+(.*)$/);
    if (!match) return null;
    // BBC BASIC does not accept an empty numbered source line. A colon by
    // itself is the executable no-op used for visual separators, so preserve
    // it exactly instead of producing an invalid blank line.
    if (/^\s*:+\s*$/.test(match[2])) {
      return null;
    }
    // ON ERROR owns the remainder of its physical line. Split it by installing
    // an explicit handler target and a normal-flow jump over the extracted
    // handler; simply putting its colon-separated actions on following lines
    // would execute them immediately and change the program.
    const onError = match[2].trim().match(/^ON\s*ERROR(.*)$/i);
    if (onError) {
      const handler = basicStatements(onError[1]);
      if (nextNumber == null || handler.length < 2) return null;
      return {
        number: Number(match[1]),
        body: match[2],
        statements: ["ON ERROR GOTO {{SELF:2}}", "GOTO {{END}}", ...handler],
      };
    }
    const ifAt = keywordOutsideQuotes(match[2], "IF");
    const prefixText = ifAt > 0 ? match[2].slice(0, ifAt).replace(/:\s*$/, "") : "";
    const prefix = prefixText && !/\bREM(?![$%])/i.test(prefixText) ? basicStatements(prefixText) : [];
    const conditionalChain = ifAt >= 0
      ? inlineIfElseChain(match[2].slice(ifAt), nextNumber)
      : null;
    if (conditionalChain) {
      const shiftedChain = conditionalChain.map(statement => statement.replace(
        /\{\{SELF:(\d+)\}\}/g,
        (_whole, index) => `{{SELF:${Number(index) + prefix.length}}}`,
      ));
      return { number: Number(match[1]), body: match[2], statements: [...prefix, ...shiftedChain] };
    }
    const statements = basicStatements(match[2]);
    if (statements.length < 2 && !/^IF(?![$%])/i.test(statements[0] || "")) return null;
    const expanded = inlineIfExpansion(statements, nextNumber);
    if (!expanded) return null;
    if (statements.length < 2 && expanded.length === statements.length && expanded.every((statement, index) => statement === statements[index])) return null;
    return { number: Number(match[1]), body: match[2], statements: expanded };
  }

  function nextBasicLineNumber(lines, index) {
    for (let following = index + 1; following < lines.length; following += 1) {
      const number = lines[following].match(/^\s*(\d+)\s+/)?.[1];
      if (number != null) return Number(number);
    }
    return null;
  }

  function maskedBasicCode(text) {
    const value = String(text);
    const mask = [...value];
    let quoted = false;
    for (let index = 0; index < value.length; index += 1) {
      if (value[index] === '"') { quoted = !quoted; mask[index] = " "; continue; }
      if (quoted) mask[index] = " ";
    }
    const comment = mask.join("").search(/\bREM(?![$%])/i);
    if (comment >= 0) mask.fill(" ", comment);
    return mask.join("");
  }

  function basicDestinations(text) {
    const mask = maskedBasicCode(text);
    const matches = [];
    const positions = new Set();
    const add = (start, digits) => {
      if (positions.has(start)) return;
      positions.add(start);
      matches.push({ start, end: start + digits.length, target: Number(digits) });
    };
    for (const match of mask.matchAll(/\b(?:GOTO|GOSUB|RESTORE|THEN|RUN)(?![$%])\s*(\d+)\b/gi)) {
      const digits = match[1];
      add(match.index + match[0].lastIndexOf(digits), digits);
    }
    for (const match of mask.matchAll(/\b(?:GOTO|GOSUB)(?![$%])\s+(\d+(?:\s*,\s*\d+)+)/gi)) {
      const listAt = match.index + match[0].indexOf(match[1]);
      for (const number of match[1].matchAll(/\d+/g)) add(listAt + number.index, number[0]);
    }
    return matches.sort((left, right) => left.start - right.start);
  }

  function rewriteBasicDestinations(text, numbers) {
    let updated = String(text);
    basicDestinations(updated).reverse().forEach(match => {
      const replacement = String(numbers.get(match.target) ?? match.target);
      updated = `${updated.slice(0, match.start)}${replacement}${updated.slice(match.end)}`;
    });
    return updated;
  }

  function basicHasDynamicDestination(text) {
    const mask = maskedBasicCode(text);
    for (const match of mask.matchAll(/\b(GOTO|GOSUB|RESTORE|RUN)(?![$%])/gi)) {
      const remainder = mask.slice(match.index + match[0].length).split(":", 1)[0].trimStart();
      if (!remainder && /^(RESTORE|RUN)$/i.test(match[1])) continue;
      if (!/^\d+\b/.test(remainder)) return true;
    }
    for (const match of mask.matchAll(/\bTHEN(?![$%])/gi)) {
      const remainder = mask.slice(match.index + match[0].length).split(/\bELSE\b|:/i, 1)[0].trim();
      if (!remainder || /^\d+\b/.test(remainder)) continue;
      if (basicStartsStatement(remainder)) continue;
      if (/^[A-Za-z][A-Za-z0-9_]*[$%]?(?:\([^)]*\))?\s*=/.test(remainder)) continue;
      return true;
    }
    return false;
  }

  function basicHasSemanticErl(text) {
    const code = maskedBasicCode(text);
    if (!/\bERL(?![$%])/i.test(code)) return false;
    // Merely printing ERL reports the newly assigned physical line number and
    // remains correct after a refactor. Assignments, comparisons and other
    // uses can make program behaviour depend on the old number and must keep
    // the conservative safety stop.
    return basicStatements(code).some(statement => (
      /\bERL(?![$%])/i.test(statement)
      && !/^\s*PRINT(?=\s|['";,(]|$)/i.test(statement)
    ));
  }

  function basicCondenseBoundaryBefore(body) {
    return /^\s*(?:ELSE|WHEN|OTHERWISE|ENDIF|ENDCASE|ENDWHILE)(?![$%])/i.test(maskedBasicCode(body));
  }

  function basicCondenseBoundaryAfter(body) {
    const mask = maskedBasicCode(body);
    if (/\bIF(?![$%])/i.test(mask) || /^\s*ON\s+ERROR(?![$%])/i.test(mask)) return true;
    if (String(body).replace(/"(?:[^"]|"")*"/g, "").match(/\bREM(?![$%])/i)) return true;
    if (/(^|:)\s*\*/.test(mask)) return true;
    const finalStatement = basicStatements(body).at(-1) || "";
    return /^(?:GOTO|RETURN|END|STOP|ENDPROC|CHAIN|RUN|ERROR)(?![$%])/i.test(finalStatement);
  }

  function rebuildBasic(lines, expansions, { startAt = null, fromIndex = 0, step = 10 } = {}) {
    const sourceRows = lines.map((line, index) => {
      const match = line.match(/^\s*(\d+)\s+(.*)$/);
      return match ? { index, old: Number(match[1]), bodies: expansions.get(index) || [match[2]] } : { index, old: null, bodies: [line] };
    });
    const map = new Map();
    let next = startAt;
    for (const row of sourceRows) {
      if (row.old == null) continue;
      const assigned = next == null || row.index < fromIndex ? row.old : next;
      map.set(row.old, assigned);
      if (next != null && row.index >= fromIndex) next += row.bodies.length * step;
    }
    return sourceRows.flatMap(row => {
      if (row.old == null) return row.bodies;
      let number = map.get(row.old);
      return row.bodies.map((body, bodyIndex) => {
        const rewritten = rewriteBasicDestinations(body, map)
          .replace(/\{\{SELF:(\d+)\}\}/g, (_whole, index) => String(map.get(row.old) + Number(index) * step))
          .replace(/\{\{END\}\}/g, () => String(map.get(nextBasicLineNumber(lines, row.index))));
        const result = `${number} ${rewritten}`;
        number += step;
        return result;
      });
    });
  }

  function normaliseBasicControlSpacing(line) {
    const match = String(line).match(/^(\s*\d+\s+)(.*)$/);
    if (!match || /^\s*:+\s*$/.test(match[2])) return line;
    // Detokenised listings often join a structural keyword directly to its
    // expression or loop variable. At statement start these forms are
    // unambiguous and a separating space materially improves readability.
    const body = match[2].replace(/^\s*(IF|FOR|NEXT|UNTIL|WHILE|CASE|WHEN)(?![$%])(?=\S)/i, (_whole, keyword) => `${keyword} `);
    return `${match[1]}${body}`;
  }

  const languageName = language => ({ basic: "BBC BASIC", script: "Acorn command script", text: "plain text", "6502": "6502 assembly", "65c02": "65C02 assembly", "65816": "65816 assembly", arm: "ARM assembly", m68k: "68000 assembly" }[language] || language);

  function helpMarkup(item) {
    if (!item) return '<p class="code-empty-message">No built-in help is available for that token.</p>';
    return `<article class="code-help-detail"><h3>${esc(item.key)}</h3><p>${esc(item.summary)}</p><dl><dt>Syntax</dt><dd><code>${esc(item.syntax)}</code></dd><dt>Requirements</dt><dd>${esc(item.requirements)}</dd>${item.notes ? `<dt>Watch for</dt><dd>${esc(item.notes)}</dd>` : ""}</dl></article>`;
  }

  let hoverHelpRequest = 0;
  let lastHoverPointerMove = 0;
  let hoverHelpListenersInstalled = false;

  function dismissHoverHelp(owner = document) {
    hoverHelpRequest += 1;
    owner.querySelectorAll(".code-hover-help").forEach(node => node.remove());
    owner.querySelectorAll('[aria-describedby^="code-help-"]').forEach(node => node.removeAttribute("aria-describedby"));
  }

  function installHoverHelpDismissal(owner = document) {
    if (hoverHelpListenersInstalled) return;
    hoverHelpListenersInstalled = true;
    owner.addEventListener("pointermove", () => { lastHoverPointerMove = performance.now(); }, { passive: true });
    owner.addEventListener("pointerdown", () => dismissHoverHelp(owner), true);
    owner.addEventListener("scroll", () => dismissHoverHelp(owner), { capture: true, passive: true });
    owner.addEventListener("keydown", event => { if (event.key === "Escape") dismissHoverHelp(owner); }, true);
    owner.addEventListener("visibilitychange", () => dismissHoverHelp(owner));
    window.addEventListener("blur", () => dismissHoverHelp(owner));
  }

  function attachTooltip(root, language, element, key, suppliedItem = null) {
    const item = suppliedItem || lookup(language, key);
    if (!item) return;
    installHoverHelpDismissal(element.ownerDocument);
    let tooltip = null;
    let showTimer = null;
    const hide = () => {
      clearTimeout(showTimer);
      showTimer = null;
      tooltip?.remove();
      tooltip = null;
      element.removeAttribute("aria-describedby");
    };
    element.addEventListener("mouseenter", () => {
      const owner = element.ownerDocument;
      dismissHoverHelp(owner);
      const request = hoverHelpRequest;
      showTimer = setTimeout(() => {
        if (request !== hoverHelpRequest || !element.isConnected || !element.matches(":hover")) return;
        // Replacing highlighted source beneath a stationary pointer must not
        // manufacture a tooltip. A recent real pointer movement identifies a
        // deliberate hover over the token.
        if (performance.now() - lastHoverPointerMove > 750) return;
        tooltip = owner.createElement("div");
        tooltip.className = "code-hover-help";
        tooltip.id = `code-help-${Math.random().toString(36).slice(2)}`;
        tooltip.setAttribute("role", "tooltip");
        tooltip.innerHTML = `<strong>${esc(item.key)}</strong><span>${esc(item.summary)}</span><dl><dt>Syntax</dt><dd><code>${esc(item.syntax)}</code></dd><dt>Requirements</dt><dd>${esc(item.requirements)}</dd>${item.notes ? `<dt>Watch for</dt><dd>${esc(item.notes)}</dd>` : ""}</dl>`;
        // Native dialogs occupy the browser's top layer. Keep the tooltip in
        // the active dialog so it is painted above the editor.
        (root.closest("dialog") || owner.body).append(tooltip);
        const tokenRect = element.getBoundingClientRect();
        const tipRect = tooltip.getBoundingClientRect();
        tooltip.style.left = `${Math.max(8, Math.min(tokenRect.left, window.innerWidth - tipRect.width - 8))}px`;
        tooltip.style.top = `${tokenRect.bottom + tipRect.height + 8 < window.innerHeight ? tokenRect.bottom + 7 : Math.max(8, tokenRect.top - tipRect.height - 7)}px`;
        element.setAttribute("aria-describedby", tooltip.id);
      }, 300);
    });
    element.addEventListener("mouseleave", () => { hide(); dismissHoverHelp(element.ownerDocument); });
    element.addEventListener("focusout", () => { hide(); dismissHoverHelp(element.ownerDocument); });
    root.addEventListener("code-editor-destroy", hide, { once: true });
  }

  function enhance({ textarea, root, language = "text", dialect = "BBC BASIC II", inlineAssemblyLanguage = "6502", validateBasic = null, packBasic = null, initialHistory = [], targetProfile = {} }) {
    if (!textarea || !root || textarea.closest(".code-editor-surface")) return null;
    const surface = document.createElement("div");
    surface.className = "code-editor-surface";
    const visual = document.createElement("div");
    visual.className = "code-highlight-layer";
    visual.setAttribute("aria-hidden", "true");
    visual.innerHTML = "<pre></pre>";
    const hit = document.createElement("div");
    hit.className = "code-hit-layer";
    hit.setAttribute("aria-hidden", "true");
    hit.innerHTML = "<pre></pre>";
    const guides = document.createElement("div");
    guides.className = "code-structure-guides";
    guides.setAttribute("aria-hidden", "true");
    const gutter = document.createElement("div");
    gutter.className = "code-fold-gutter";
    gutter.setAttribute("aria-label", "Code folding controls");
    const foldView = document.createElement("div");
    foldView.className = "code-fold-view";
    foldView.hidden = true;
    foldView.setAttribute("aria-label", "Collapsed code outline. Double-click a visible line to expand all blocks and edit it.");
    textarea.before(surface);
    surface.append(gutter, guides, visual, textarea, hit, foldView);
    const drawer = document.createElement("section");
    drawer.className = "code-intelligence-drawer";
    drawer.hidden = true;
    root.insertBefore(drawer, root.querySelector(".editor-status"));
    let state = { tokens: [], issues: [], symbols: [], blocks: [] };
    const collapsedBlocks = new Set();
    let structureGuides = language === "basic" ? { size: 4 } : null;
    let refactorPlan = null;
    let timer = null;
    const refactorUndo = [];
    const refactorRedo = [];
    const editorHistory = Array.isArray(initialHistory) ? initialHistory.slice(-200) : [];
    const pendingHistory = [];

    const historyEntry = (action, detail = "") => {
      const entry = { time: new Date().toISOString(), action, detail };
      editorHistory.push(entry);
      pendingHistory.push(entry);
      if (editorHistory.length > 200) editorHistory.shift();
    };

    const syncScroll = () => {
      for (const layer of [visual, hit, gutter, guides]) {
        layer.scrollTop = textarea.scrollTop;
        layer.scrollLeft = textarea.scrollLeft;
      }
    };
    const foldButtonMarkup = block => `<button type="button" class="code-fold-toggle" data-fold-id="${esc(block.id)}" aria-expanded="${collapsedBlocks.has(block.id) ? "false" : "true"}" title="${collapsedBlocks.has(block.id) ? "Expand" : "Collapse"} ${esc(block.label)}">${collapsedBlocks.has(block.id) ? "+" : "−"}</button>`;
    const blockStartingOn = lineIndex => state.blocks.find(block => block.startLine === lineIndex);
    const bindFoldButtons = host => host.querySelectorAll("[data-fold-id]").forEach(button => {
      button.onclick = event => {
        event.stopPropagation();
        const id = button.dataset.foldId;
        if (collapsedBlocks.has(id)) collapsedBlocks.delete(id);
        else collapsedBlocks.add(id);
        renderFolds();
      };
    });
    const renderFolds = () => {
      dismissHoverHelp(textarea.ownerDocument);
      if (refactorPlan) {
        const rendered = refactorPlan.preview;
        const renderedMarkup = highlightedSourceLines(rendered, language, inlineAssemblyLanguage);
        const original = refactorPlan.before || [];
        const originalMarkup = highlightedSourceLines(original, language, inlineAssemblyLanguage);
        surface.classList.add("code-editor-folded");
        foldView.hidden = false;
        gutter.innerHTML = "";
        const operation = refactorPlan.mode === "condense" ? "condensation" : "refactor";
        const maximum = Math.max(original.length, rendered.length);
        const reviewRows = Array.from({ length: maximum }, (_unused, index) => {
          const before = original[index] ?? "";
          const after = rendered[index] ?? "";
          const changed = before !== after;
          return `<div class="code-transform-row${changed ? " changed" : ""}"><span>${index + 1}</span><pre>${originalMarkup[index] || " "}</pre><pre>${renderedMarkup[index] || " "}</pre></div>`;
        }).join("");
        const verification = refactorPlan.verification;
        foldView.innerHTML = `<section class="code-transform-review"><header><div><strong>Original</strong><small>${original.length} lines</small></div><div><strong>Proposed ${operation}</strong><small>${rendered.length} lines</small></div><div class="code-transform-actions"><button type="button" class="code-untangle-cancel" title="Cancel without changing the program">Cancel</button><button type="button" class="code-untangle-commit" title="Accept the proposed ${operation}">Accept</button></div></header>${verification ? `<p class="code-transform-verification ${verification.roundTripExact ? "pass" : "warn"}">${verification.roundTripExact ? "✓ Exact BASIC token round trip" : "! Round-trip warning"} · ${Number(verification.byteLength || 0).toLocaleString()} tokenised bytes · ${Number(verification.lineCount || 0).toLocaleString()} lines</p>` : ""}<div class="code-transform-columns"><span></span><strong>Before</strong><strong>After</strong></div>${reviewRows}</section>`;
        foldView.querySelector(".code-untangle-commit").onclick = () => commitRefactor();
        foldView.querySelector(".code-untangle-cancel").onclick = () => cancelRefactor();
        return;
      }
      const validIds = new Set(state.blocks.map(block => block.id));
      [...collapsedBlocks].forEach(id => { if (!validIds.has(id)) collapsedBlocks.delete(id); });
      const canFold = state.blocks.length > 0;
      const foldAll = root.querySelector('[data-editor-action="fold-toggle-all"]');
      if (foldAll) {
        foldAll.disabled = !canFold;
        foldAll.querySelector("span").textContent = collapsedBlocks.size ? "Expand all blocks" : "Collapse all blocks";
      }
      const guideToggle = root.querySelector('[data-editor-action="structure-guides"] span');
      if (guideToggle) guideToggle.textContent = structureGuides ? "Hide structure guides" : "Show structure guides";
      const lines = textarea.value.split("\n");
      const displayLines = lines;
      const displayMarkup = highlightedSourceLines(displayLines, language, inlineAssemblyLanguage);
      gutter.innerHTML = `<div>${lines.map((_line, index) => `<span>${blockStartingOn(index) ? foldButtonMarkup(blockStartingOn(index)) : ""}</span>`).join("")}</div>`;
      bindFoldButtons(gutter);
      const outlined = collapsedBlocks.size > 0;
      surface.classList.toggle("code-editor-folded", outlined);
      foldView.hidden = !outlined;
      if (!outlined) return;
      const offsets = [];
      lines.reduce((offset, line) => { offsets.push(offset); return offset + line.length + 1; }, 0);
      const visibleRows = [];
      lines.forEach((line, lineIndex) => {
        const hidingBlock = state.blocks.find(block => collapsedBlocks.has(block.id) && lineIndex > block.startLine && lineIndex <= block.endLine);
        if (hidingBlock) return;
        const block = blockStartingOn(lineIndex);
        const hiddenCount = block && collapsedBlocks.has(block.id) ? block.endLine - block.startLine : 0;
        const displayLine = displayLines[lineIndex] ?? line;
        visibleRows.push(`<div class="code-fold-row" data-code-offset="${offsets[lineIndex]}"><span class="code-fold-row-gutter">${block ? foldButtonMarkup(block) : ""}</span><pre>${displayMarkup[lineIndex]}</pre>${hiddenCount ? `<small>${hiddenCount.toLocaleString()} line${hiddenCount === 1 ? "" : "s"} folded</small>` : ""}</div>`);
      });
      foldView.innerHTML = visibleRows.join("");
      bindFoldButtons(foldView);
      foldView.querySelectorAll(".code-help-token").forEach(element => attachTooltip(root, element.dataset.helpLanguage || language, element, element.dataset.helpKey));
      foldView.querySelectorAll(".code-fold-row").forEach(row => row.ondblclick = event => {
        if (event.target.closest("button")) return;
        const offset = Number(row.dataset.codeOffset);
        showOriginalView();
        goTo(offset);
      });
      foldView.scrollTop = Math.min(foldView.scrollHeight, textarea.scrollTop);
    };
    const expandAll = () => {
      if (!collapsedBlocks.size) return;
      collapsedBlocks.clear();
      renderFolds();
      textarea.focus();
    };
    const collapseAll = () => {
      state.blocks.forEach(block => collapsedBlocks.add(block.id));
      renderFolds();
    };
    const toggleAll = () => collapsedBlocks.size ? expandAll() : collapseAll();
    const renderStructureGuides = () => {
      if (!structureGuides || language !== "basic") {
        guides.replaceChildren();
        guides.hidden = true;
        return;
      }
      guides.hidden = false;
      const lines = textarea.value.split("\n");
      const cursorLine = textarea.value.slice(0, textarea.selectionStart).split("\n").length - 1;
      const active = state.blocks
        .filter(block => cursorLine >= block.startLine && cursorLine <= block.endLine)
        .sort((left, right) => (left.endLine - left.startLine) - (right.endLine - right.startLine))[0];
      const size = [2, 4, 8].includes(Number(structureGuides.size)) ? Number(structureGuides.size) : 4;
      const guideWidth = Math.max(textarea.scrollWidth, textarea.clientWidth);
      guides.style.setProperty("--structure-guide-step", `${size}ch`);
      guides.innerHTML = lines.map((_line, lineIndex) => {
        const depth = state.blocks.filter(block => lineIndex > block.startLine && lineIndex <= block.endLine).length;
        const activeLine = active && lineIndex >= active.startLine && lineIndex <= active.endLine;
        const bars = Array.from({ length: depth }, (_unused, index) => `<i style="--guide-index:${index}"></i>`).join("");
        return `<span class="${activeLine ? "active" : ""}" style="width:${guideWidth}px">${bars}</span>`;
      }).join("");
      guides.scrollTop = textarea.scrollTop;
      guides.scrollLeft = textarea.scrollLeft;
    };
    const toggleStructureGuides = size => {
      structureGuides = structureGuides ? null : { size: Number(size) };
      renderStructureGuides();
      renderFolds();
    };
    const setStructureGuideSize = size => {
      if (!structureGuides) structureGuides = { size: Number(size) };
      else structureGuides.size = Number(size);
      renderStructureGuides();
    };
    const showOriginalView = () => {
      refactorPlan = null;
      collapsedBlocks.clear();
      renderFolds();
      textarea.focus();
    };
    const goTo = offset => {
      if (collapsedBlocks.size) {
        collapsedBlocks.clear();
        renderFolds();
      }
      textarea.focus();
      textarea.setSelectionRange(offset, offset);
      const before = textarea.value.slice(0, offset).split("\n");
      textarea.scrollTop = Math.max(0, (before.length - 3) * parseFloat(getComputedStyle(textarea).lineHeight || "16"));
      syncScroll();
      textarea.dispatchEvent(new Event("click", { bubbles: true }));
    };
    const closeDrawer = () => { drawer.hidden = true; };
    const renderDrawer = (title, body) => {
      drawer.hidden = false;
      drawer.innerHTML = `<header><div><small>CODE-AWARE HELP</small><h3>${esc(title)}</h3></div><button type="button" class="code-drawer-close" aria-label="Close code help">×</button></header><div class="code-drawer-body">${body}</div>`;
      drawer.querySelector(".code-drawer-close").onclick = closeDrawer;
      drawer.querySelectorAll("[data-code-offset]").forEach(button => button.onclick = () => goTo(Number(button.dataset.codeOffset)));
      drawer.querySelectorAll("[data-code-help]").forEach(button => button.onclick = () => renderDrawer(button.dataset.codeHelp, helpMarkup(lookup(language, button.dataset.codeHelp))));
      drawer.querySelectorAll("[data-code-completion]").forEach(button => button.onclick = () => {
        const selected = identifierAt(textarea.value, textarea.selectionStart, language);
        const start = selected?.start ?? textarea.selectionStart;
        const end = selected?.end ?? textarea.selectionEnd;
        const value = button.dataset.codeCompletion;
        textarea.setRangeText(value, start, end, "end");
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        closeDrawer();
        textarea.focus();
      });
      drawer.querySelectorAll("[data-code-snippet]").forEach(button => button.onclick = () => {
        const value = button.dataset.codeSnippet;
        textarea.setRangeText(value, textarea.selectionStart, textarea.selectionEnd, "end");
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        closeDrawer();
        textarea.focus();
      });
      const filter = drawer.querySelector("[data-code-reference-filter]");
      if (filter) filter.oninput = () => drawer.querySelectorAll("[data-code-help]").forEach(button => button.hidden = !button.textContent.toLowerCase().includes(filter.value.toLowerCase()));
    };
    const showCustom = (title, body) => renderDrawer(title, body);
    const overview = () => {
      const recognised = [...new Set(state.tokens.map(item => item.helpKey).filter(Boolean))];
      const profile = BASIC_LANGUAGE?.dialectProfile(dialect);
      renderDrawer(`${languageName(language)} overview`, `<div class="code-overview"><p>This file contains <strong>${textarea.value.split("\n").length.toLocaleString()} lines</strong>, <strong>${state.symbols.length.toLocaleString()} navigable symbols</strong> and <strong>${state.issues.length.toLocaleString()} diagnostics</strong>.</p><p>${language === "basic" ? `Detected dialect: <strong>${esc(dialect)}</strong>. Numbered source is tokenised when saved. ${profile ? `Its inline assembler targets ${esc(profile.processor)} and ${profile.structured ? "supports" : "predates"} structured CASE/WHILE syntax.` : ""} Line destinations and local procedure definitions are checked while you type.` : language === "script" ? "Commands are executed in order by *EXEC or the boot process. Filing-system dependencies and ambiguous DFS abbreviations are highlighted." : "Readable text is preserved as Latin-1. Syntax-specific checks are intentionally not imposed."}</p>${recognised.length ? `<h4>Commands used in this file</h4><div class="code-command-chips">${recognised.map(key => `<button type="button" data-code-help="${esc(key)}">${esc(key)}</button>`).join("")}</div>` : ""}</div>`);
    };
    const helpAtCursor = () => {
      const offset = textarea.selectionStart;
      const lineStart = textarea.value.lastIndexOf("\n", Math.max(0, offset - 1)) + 1;
      const found = state.tokens.find(item => item.start <= offset && item.end >= offset && item.helpKey)
        || state.tokens.filter(item => item.start >= lineStart && item.end <= offset && item.helpKey).at(-1);
      const item = found ? sourceContextHelp(textarea.value, found.helpLanguage || language, found.start, found.end, found.helpKey, targetProfile) : null;
      renderDrawer(item?.key || "Help at cursor", helpMarkup(item));
    };
    const showProblems = () => renderDrawer("Problems", state.issues.length ? `<div class="code-problem-list">${state.issues.map(item => `<button type="button" data-code-offset="${item.offset}"><b class="${esc(item.severity)}">${esc(item.severity)}</b><span>Line ${item.line}: ${esc(item.message)}</span></button>`).join("")}</div>` : '<p class="code-empty-message">No problems were found by the live checks.</p>');
    const showSymbols = () => renderDrawer("Document symbols", state.symbols.length ? `<div class="code-symbol-list">${state.symbols.map(item => `<button type="button" data-code-offset="${item.offset}"><b>${esc(item.kind)}</b><span>${esc(item.name)}</span></button>`).join("")}</div>` : '<p class="code-empty-message">No navigable symbols were found in this file.</p>');
    const showCompletions = () => {
      const selected = identifierAt(textarea.value, textarea.selectionStart, language);
      const prefix = String(selected?.name || "").toUpperCase();
      const identifiers = language === "basic" && BASIC_LANGUAGE
        ? BASIC_LANGUAGE.scan(textarea.value).filter(item => item.type === "identifier").map(item => item.text)
        : [];
      const commands = language === "basic" ? [...BASIC_KEYWORDS] : language === "script" ? [...SCRIPT_COMMANDS].map(item => `*${item}`) : [];
      const candidates = [...new Set([...commands, ...identifiers, ...state.symbols.map(item => item.name.replace(/^Line\s+/, ""))])]
        .filter(value => !prefix || value.toUpperCase().startsWith(prefix))
        .sort((left, right) => left.localeCompare(right)).slice(0, 200);
      const snippets = language === "basic" ? [
        ["FOR loop", "FOR I%=1 TO 10:NEXT"], ["REPEAT loop", "REPEAT:UNTIL condition"],
        ["Conditional", "IF condition THEN statement"], ["Procedure", "DEFPROCname:ENDPROC"],
      ] : language === "script" ? [
        ["Execute boot script", "*EXEC !BOOT"], ["Run machine code", "*RUN filename"],
        ["Select directory", "*DIR directory"], ["Start BASIC", "*BASIC"],
      ] : [];
      renderDrawer("Completion and snippets", `<p class="code-empty-message">${prefix ? `Candidates beginning with ${esc(prefix)}.` : "Choose a known command, identifier or template."}</p><div class="code-completion-list">${candidates.map(value => `<button type="button" data-code-completion="${esc(value)}">${esc(value)}</button>`).join("") || "<small>No matching candidates.</small>"}</div>${snippets.length ? `<h4 class="code-drawer-section-title">Templates</h4><div class="code-snippet-list">${snippets.map(([label, value]) => `<button type="button" data-code-snippet="${esc(value)}"><b>${esc(label)}</b><code>${esc(value)}</code></button>`).join("")}</div>` : ""}`);
    };
    const formatCode = async () => {
      if (textarea.readOnly) return false;
      const hasSelection = textarea.selectionStart !== textarea.selectionEnd;
      const lineStart = textarea.value.lastIndexOf("\n", Math.max(0, textarea.selectionStart - 1)) + 1;
      const lineEndAt = textarea.value.indexOf("\n", textarea.selectionEnd);
      const rangeStart = hasSelection ? lineStart : 0;
      const rangeEnd = hasSelection ? (lineEndAt < 0 ? textarea.value.length : lineEndAt) : textarea.value.length;
      const original = textarea.value.slice(rangeStart, rangeEnd);
      const formatted = original.split("\n").map(line => {
        let updated = line.replace(/[ \t]+$/g, "");
        if (language === "basic") updated = normaliseBasicControlSpacing(updated.replace(/^\s*(\d+)\s*/, "$1 "));
        if (language === "script") updated = updated.replace(/^\s*\*\s*/, "*");
        return updated;
      }).join("\n");
      if (formatted === original) {
        showCustom("Format source", '<p class="code-empty-message">The selected source already follows the conservative formatter rules.</p>');
        return false;
      }
      const candidate = `${textarea.value.slice(0, rangeStart)}${formatted}${textarea.value.slice(rangeEnd)}`;
      if (language === "basic" && validateBasic) {
        const check = await validateBasic(candidate, textarea.value);
        if (!check.roundTrip) {
          showCustom("Format source", `<p class="code-empty-message">Formatting was not applied because the BASIC token round trip failed: ${esc(check.message || "unknown error")}</p>`);
          return false;
        }
      }
      if (!window.confirm(`Apply conservative whitespace formatting to ${hasSelection ? "the selected lines" : "the complete file"}?`)) return false;
      const before = documentSnapshot();
      const selectionEnd = rangeStart + formatted.length;
      const after = { value: candidate, selectionStart: rangeStart, selectionEnd, scrollTop: textarea.scrollTop, scrollLeft: textarea.scrollLeft };
      refactorUndo.push({ before, after });
      refactorRedo.length = 0;
      applyDocumentSnapshot(after);
      historyEntry("Formatted source", hasSelection ? "Selected lines" : "Complete file");
      return true;
    };
    const findReferences = () => {
      const result = symbolReferences(textarea.value, textarea.selectionStart, language);
      renderDrawer(result.name ? `References to ${result.name}` : "Find all references", result.rows.length
        ? `<p>${result.rows.length.toLocaleString()} code occurrence${result.rows.length === 1 ? "" : "s"}; strings and comments are excluded.</p><div class="code-reference-results">${result.rows.map(row => `<button type="button" data-code-offset="${row.offset}"><b>Line ${row.line}</b><code>${esc(row.context)}</code></button>`).join("")}</div>`
        : '<p class="code-empty-message">Place the cursor on a symbol or variable to find its references.</p>');
    };
    const renameSymbol = () => {
      if (textarea.readOnly) return;
      const result = symbolReferences(textarea.value, textarea.selectionStart, language);
      if (!result.name || !result.rows.length) return window.alert("Place the cursor on a symbol or variable first.");
      if (language === "basic" && BASIC_KEYWORDS.has(result.name.toUpperCase())) return window.alert("BBC BASIC commands cannot be renamed.");
      const replacement = window.prompt(`Rename ${result.rows.length} code occurrence${result.rows.length === 1 ? "" : "s"} of ${result.name} to:`, result.name);
      if (!replacement || replacement === result.name || !/^[A-Za-z_.][A-Za-z0-9_.$%]*$/.test(replacement)) return;
      if (!window.confirm(`Rename ${result.rows.length} code occurrence${result.rows.length === 1 ? "" : "s"} of ${result.name} to ${replacement}? Text inside strings and comments will not change.`)) return;
      const before = documentSnapshot();
      let updated = textarea.value;
      [...result.rows].reverse().forEach(row => { updated = `${updated.slice(0, row.offset)}${replacement}${updated.slice(row.offset + result.name.length)}`; });
      const cursor = Math.min(updated.length, textarea.selectionStart + replacement.length - result.name.length);
      const after = { value: updated, selectionStart: cursor, selectionEnd: cursor, scrollTop: textarea.scrollTop, scrollLeft: textarea.scrollLeft };
      refactorUndo.push({ before, after });
      refactorRedo.length = 0;
      applyDocumentSnapshot(after);
      historyEntry("Renamed symbol", `${result.name} → ${replacement}; ${result.rows.length} references`);
    };
    const showOutline = () => {
      if (language !== "basic") return showSymbols();
      const definitions = [...textarea.value.matchAll(/\bDEF\s*(PROC|FN)([A-Za-z][A-Za-z0-9_]*)/gi)].map(match => ({
        name: `${match[1].toUpperCase()}${match[2]}`, offset: match.index,
        calls: [...sourceMask(textarea.value, language).matchAll(new RegExp(`\\b${match[1]}${match[2]}\\b`, "gi"))].filter(call => call.index !== match.index),
      }));
      renderDrawer("Program outline and call graph", definitions.length
        ? `<div class="code-outline-list">${definitions.map(item => `<article><button type="button" data-code-offset="${item.offset}"><b>${esc(item.name)}</b><span>${item.calls.length} call${item.calls.length === 1 ? "" : "s"}</span></button>${item.calls.map(call => `<button type="button" data-code-offset="${call.index}">Called at physical line ${textarea.value.slice(0, call.index).split("\n").length}</button>`).join("")}</article>`).join("")}</div>`
        : '<p class="code-empty-message">No procedures or functions were defined in this file.</p>');
    };
    const showHistory = () => renderDrawer("Editor history", editorHistory.length
      ? `<div class="code-history-list">${[...editorHistory].reverse().map(item => `<article><time>${esc(new Date(item.time).toLocaleTimeString())}</time><b>${esc(item.action)}</b><span>${esc(item.detail)}</span></article>`).join("")}</div>`
      : '<p class="code-empty-message">No transformations or symbol changes have been made in this editor window.</p>');
    const compareWith = baseline => {
      const before = String(baseline || "").split("\n");
      const after = textarea.value.split("\n");
      const maximum = Math.max(before.length, after.length);
      const rows = Array.from({ length: maximum }, (_unused, index) => ({ before: before[index] ?? "", after: after[index] ?? "" }))
        .map((row, index) => `<div class="code-inline-diff-row${row.before === row.after ? "" : " changed"}"><span>${index + 1}</span><pre>${esc(row.before) || " "}</pre><pre>${esc(row.after) || " "}</pre></div>`).join("");
      renderDrawer("Current source compared with saved file", `<div class="code-inline-diff"><header><span></span><b>Saved</b><b>Current</b></header>${rows}</div>`);
    };
    const verifyRoundTrip = async () => {
      if (!validateBasic) return;
      try {
        const result = await validateBasic(textarea.value, textarea.dataset.savedValue || "");
        renderDrawer("BASIC round-trip verification", `<div class="code-verification"><p class="${result.roundTripExact ? "pass" : "warn"}"><strong>${result.roundTripExact ? "Exact token round trip" : "Review required"}</strong></p><dl><dt>Lines</dt><dd>${Number(result.lineCount || 0).toLocaleString()}</dd><dt>Tokenised size</dt><dd>${Number(result.byteLength || 0).toLocaleString()} bytes</dd><dt>Destinations</dt><dd>${(result.destinations || []).length.toLocaleString()}</dd></dl>${(result.warnings || []).map(message => `<p>${esc(message)}</p>`).join("") || "<p>The listing tokenises, detokenises and reproduces identical token bytes.</p>"}</div>`);
        return result;
      } catch (error) { window.alert(error.message || String(error)); return null; }
    };
    const reference = () => {
      const keys = [...new Set([...Object.keys(dictionary(language)), ...(language === "basic" ? [...BASIC_KEYWORDS] : [])])].sort();
      renderDrawer(`${languageName(language)} reference`, `<label class="code-reference-filter">Filter commands<input type="search" data-code-reference-filter placeholder="Type a command name"></label><div class="code-reference-list">${keys.map(key => `<button type="button" data-code-help="${esc(key)}">${esc(key)}</button>`).join("")}</div>`);
      drawer.querySelector("[data-code-reference-filter]")?.focus();
    };
    const goToLine = () => {
      const requested = prompt(language === "basic" ? "Go to BBC BASIC line number or physical editor line:" : "Go to editor line:");
      if (requested == null || !requested.trim()) return;
      const number = Number.parseInt(requested, 10);
      if (!Number.isInteger(number) || number < 1) return;
      let offset = null;
      if (language === "basic") {
        const match = [...textarea.value.matchAll(/^\s*(\d+)\s/gm)].find(item => Number(item[1]) === number);
        if (match) offset = match.index;
      }
      if (offset == null) {
        const lines = textarea.value.split("\n");
        if (number > lines.length) return;
        offset = lines.slice(0, number - 1).reduce((total, line) => total + line.length + 1, 0);
      }
      goTo(offset);
    };
    const normaliseCommands = () => {
      const convention = COMMAND_CASE[language];
      if (!convention) return;
      showOriginalView();
      const convert = value => convention === "lower" ? value.toLowerCase() : value.toUpperCase();
      const replacements = state.tokens.filter(item => item.type === "keyword" && item.text !== convert(item.text)).reverse();
      if (!replacements.length) return;
      const selectionStart = textarea.selectionStart;
      const selectionEnd = textarea.selectionEnd;
      let updated = textarea.value;
      replacements.forEach(item => { updated = `${updated.slice(0, item.start)}${convert(item.text)}${updated.slice(item.end)}`; });
      textarea.setRangeText(updated, 0, textarea.value.length, "end");
      textarea.setSelectionRange(selectionStart, selectionEnd);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.focus();
      historyEntry("Normalised commands", `${replacements.length} recognised token${replacements.length === 1 ? "" : "s"}`);
    };
    const currentPhysicalLines = () => {
      const start = textarea.value.lastIndexOf("\n", Math.max(0, textarea.selectionStart - 1)) + 1;
      const endBreak = textarea.value.indexOf("\n", textarea.selectionEnd);
      const end = endBreak < 0 ? textarea.value.length : endBreak;
      const first = textarea.value.slice(0, start).split("\n").length - 1;
      const last = first + textarea.value.slice(start, end).split("\n").length - 1;
      return { first, last };
    };
    const lineOperation = action => {
      if (textarea.readOnly) return false;
      showOriginalView();
      const range = currentPhysicalLines();
      const lines = textarea.value.split("\n");
      const selected = lines.slice(range.first, range.last + 1);
      if (!selected.length) return false;
      const before = documentSnapshot();
      let first = range.first;
      if (action === "delete") lines.splice(range.first, selected.length);
      else if (action === "duplicate") { lines.splice(range.last + 1, 0, ...selected); first = range.last + 1; }
      else if (action === "move-up" && range.first > 0) {
        const previous = lines.splice(range.first - 1, 1)[0];
        lines.splice(range.last, 0, previous);
        first -= 1;
      } else if (action === "move-down" && range.last < lines.length - 1) {
        const following = lines.splice(range.last + 1, 1)[0];
        lines.splice(range.first, 0, following);
        first += 1;
      } else if (action === "join" && language !== "basic") {
        lines.splice(range.first, selected.length, selected.map(line => line.trim()).join(" "));
      } else return false;
      const updated = lines.join("\n");
      const start = lines.slice(0, first).reduce((total, line) => total + line.length + 1, 0);
      const count = action === "duplicate" ? selected.length : action === "join" ? 1 : action === "delete" ? 0 : selected.length;
      const end = count ? start + lines.slice(first, first + count).join("\n").length : start;
      const after = { value: updated, selectionStart: start, selectionEnd: end, scrollTop: textarea.scrollTop, scrollLeft: textarea.scrollLeft };
      refactorUndo.push({ before, after });
      refactorRedo.length = 0;
      applyDocumentSnapshot(after);
      historyEntry(`${action.replace("-", " ")} lines`, `${selected.length} line${selected.length === 1 ? "" : "s"}`);
      return true;
    };
    const sourcePosition = offset => {
      const rows = textarea.value.slice(0, Math.max(0, offset)).split("\n");
      return { line: rows.length - 1, column: rows.at(-1).length };
    };
    const rebuiltPosition = (position, lines, expansions, rebuiltLines) => {
      const sourceLine = Math.min(position.line, Math.max(0, lines.length - 1));
      let targetLine = 0;
      for (let index = 0; index < sourceLine; index += 1) {
        targetLine += expansions.get(index)?.length || 1;
      }
      targetLine = Math.min(targetLine, Math.max(0, rebuiltLines.length - 1));
      const column = Math.min(position.column, rebuiltLines[targetLine]?.length || 0);
      return rebuiltLines.slice(0, targetLine).reduce((total, line) => total + line.length + 1, 0) + column;
    };
    const documentSnapshot = () => ({
      value: textarea.value,
      selectionStart: textarea.selectionStart,
      selectionEnd: textarea.selectionEnd,
      scrollTop: textarea.scrollTop,
      scrollLeft: textarea.scrollLeft,
    });
    const applyDocumentSnapshot = snapshot => {
      textarea.focus();
      textarea.value = snapshot.value;
      textarea.setSelectionRange(snapshot.selectionStart, snapshot.selectionEnd);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      const restoreView = () => {
        textarea.scrollTop = snapshot.scrollTop;
        textarea.scrollLeft = snapshot.scrollLeft;
        syncScroll();
      };
      restoreView();
      requestAnimationFrame(restoreView);
      setTimeout(restoreView, 0);
      setTimeout(restoreView, 100);
    };
    const recordRefactor = after => {
      refactorUndo.push({ before: documentSnapshot(), after });
      refactorRedo.length = 0;
      applyDocumentSnapshot(after);
      clearTimeout(timer);
      render();
      historyEntry("Accepted transformation", `${after.value.split("\n").length} lines`);
    };
    const undo = () => {
      const transaction = refactorUndo.at(-1);
      if (!transaction || textarea.value !== transaction.after.value) return false;
      refactorUndo.pop();
      refactorRedo.push(transaction);
      applyDocumentSnapshot(transaction.before);
      clearTimeout(timer);
      render();
      return true;
    };
    const redo = () => {
      const transaction = refactorRedo.at(-1);
      if (!transaction || textarea.value !== transaction.before.value) return false;
      refactorRedo.pop();
      refactorUndo.push(transaction);
      applyDocumentSnapshot(transaction.after);
      clearTimeout(timer);
      render();
      return true;
    };
    const cancelRefactor = () => {
      refactorPlan = null;
      renderFolds();
      textarea.focus();
    };
    const commitRefactor = () => {
      if (!refactorPlan) return;
      const condensing = refactorPlan.mode === "condense";
      const message = condensing
        ? "Accept this condensation? The reviewed proposal will replace the selected code as one undoable operation. Safe adjacent statements will share physical lines; surviving line numbers and all explicit destinations are preserved."
        : "Accept this refactor? The reviewed proposal will now replace the program as one undoable operation. Lines will be renumbered and direct GOTO, GOSUB, RESTORE, THEN and ON GOTO/GOSUB destinations will be updated. Dynamic line-number expressions cannot be rewritten automatically.";
      if (!window.confirm(message)) return;
      const after = refactorPlan.after;
      refactorPlan = null;
      recordRefactor(after);
      renderFolds();
    };
    const refactor = async () => {
      if (language !== "basic" || textarea.readOnly) return;
      const range = currentPhysicalLines();
      const noSelection = textarea.selectionStart === textarea.selectionEnd;
      const lines = textarea.value.split("\n");
      const selectionStart = sourcePosition(textarea.selectionStart);
      const selectionEnd = sourcePosition(textarea.selectionEnd);
      const scrollTop = textarea.scrollTop;
      const scrollLeft = textarea.scrollLeft;
      const first = noSelection ? 0 : range.first;
      const last = noSelection ? lines.length - 1 : range.last;
      const assemblerLines = basicInlineAssemblerLines(textarea.value);
      const numberedBodies = lines.map(line => line.match(/^\s*\d+\s+(.*)$/)?.[1]).filter(body => body != null);
      if (numberedBodies.some(basicHasDynamicDestination) || numberedBodies.some(basicHasSemanticErl)) {
        window.alert("This program uses a computed line destination or uses ERL in program logic. Refactoring would require renumbering physical lines and could change its behaviour, so the program has been left untouched.");
        return;
      }
      const expansions = new Map();
      for (let index = first; index <= last; index += 1) {
        if (assemblerLines[index]) continue;
        const tangled = tangledBasicLine(lines[index], nextBasicLineNumber(lines, index));
        if (tangled) expansions.set(index, tangled.statements);
      }
      const rawRebuiltLines = rebuildBasic(lines, expansions, { startAt: 10, step: 10 });
      const rebuiltAssemblerLines = basicInlineAssemblerLines(rawRebuiltLines.join("\n"));
      const rebuiltLines = rawRebuiltLines
        .map((line, index) => rebuiltAssemblerLines[index] ? line : normaliseBasicControlSpacing(line));
      const rebuilt = rebuiltLines.join("\n");
      if (rebuiltLines.some(line => Number(line.match(/^\s*(\d+)/)?.[1] || 0) > 32767)) {
        window.alert("This program is too long to renumber in steps of 10 without exceeding line 32767.");
        return;
      }
      const tokens = sourceTokens(rebuilt, language, inlineAssemblyLanguage).filter(item => item.type === "keyword").reverse();
      let normalised = rebuilt;
      tokens.forEach(item => { normalised = `${normalised.slice(0, item.start)}${item.text.toUpperCase()}${normalised.slice(item.end)}`; });
      let verification = null;
      if (validateBasic) {
        try { verification = await validateBasic(normalised, textarea.value); }
        catch (error) { window.alert(error.message || String(error)); return; }
      }
      const newStart = rebuiltPosition(selectionStart, lines, expansions, rebuiltLines);
      const newEnd = rebuiltPosition(selectionEnd, lines, expansions, rebuiltLines);
      refactorPlan = {
        mode: "refactor",
        before: textarea.value.split("\n"),
        preview: normalised.split("\n"),
        verification,
        after: { value: normalised, selectionStart: newStart, selectionEnd: newEnd, scrollTop, scrollLeft },
      };
      renderFolds();
    };
    const condense = async () => {
      if (language !== "basic" || textarea.readOnly || !packBasic) return;
      const lines = textarea.value.split("\n");
      const parsed = lines.map((line, index) => {
        const match = line.match(/^\s*(\d+)(?:\s+(.*))?$/);
        return match ? { index, number: Number(match[1]), body: match[2] || "", line } : null;
      });
      if (parsed.some((row, index) => lines[index].trim() && !row)) {
        window.alert("Condense needs a complete numbered BBC BASIC listing. Correct the unnumbered source lines first.");
        return;
      }
      const numbered = parsed.filter(Boolean);
      const assemblerLines = basicInlineAssemblerLines(textarea.value);
      if (new Set(numbered.map(row => row.number)).size !== numbered.length) {
        window.alert("Condense cannot safely operate while BASIC line numbers are duplicated.");
        return;
      }
      if (numbered.some(row => basicHasDynamicDestination(row.body)) || numbered.some(row => basicHasSemanticErl(row.body))) {
        window.alert("This program uses a computed line destination or uses ERL in program logic. Removing physical line numbers could change its behaviour, so condensation has been left for manual review.");
        return;
      }
      const range = currentPhysicalLines();
      const noSelection = textarea.selectionStart === textarea.selectionEnd;
      const first = noSelection ? 0 : range.first;
      const last = noSelection ? lines.length - 1 : range.last;
      const targets = new Set(numbered.flatMap(row => basicDestinations(row.body).map(item => item.target)));
      const runs = [];
      const pieces = [];
      let index = 0;
      while (index < lines.length) {
        const row = parsed[index];
        if (index < first || index > last || !row || assemblerLines[index]) {
          pieces.push({ kind: "fixed", entries: [{ index, line: lines[index] }] });
          index += 1;
          continue;
        }
        if (!row.body.trim() && !targets.has(row.number)) { index += 1; continue; }
        const entries = [];
        while (index <= last) {
          const candidate = parsed[index];
          if (!candidate || assemblerLines[index]) break;
          if (!candidate.body.trim() && !targets.has(candidate.number)) { index += 1; continue; }
          if (entries.length && (targets.has(candidate.number) || basicCondenseBoundaryBefore(candidate.body))) break;
          entries.push(candidate);
          index += 1;
          if (basicCondenseBoundaryAfter(candidate.body)) break;
        }
        if (!entries.length) continue;
        const runIndex = runs.length;
        runs.push(entries.map(entry => entry.body));
        pieces.push({ kind: "run", runIndex, entries });
      }
      let packed;
      try { packed = await packBasic(runs); }
      catch (error) { window.alert(error.message || String(error)); return; }
      if (!Array.isArray(packed) || packed.length !== runs.length) {
        window.alert("The BASIC line packer returned an incomplete result.");
        return;
      }
      const output = [];
      const sourceMap = new Map();
      pieces.forEach(piece => {
        if (piece.kind === "fixed") {
          const outIndex = output.length;
          output.push(piece.entries[0].line);
          sourceMap.set(piece.entries[0].index, { outIndex, baseColumn: 0, sourceBodyStart: 0 });
          return;
        }
        let cursor = 0;
        for (const count of packed[piece.runIndex]) {
          const entries = piece.entries.slice(cursor, cursor + Number(count));
          if (!entries.length) continue;
          const numberPrefix = `${entries[0].number} `;
          const outIndex = output.length;
          output.push(`${numberPrefix}${entries.map(entry => entry.body).join(":")}`);
          let bodyOffset = 0;
          entries.forEach(entry => {
            const sourceBodyStart = entry.line.indexOf(entry.body);
            sourceMap.set(entry.index, { outIndex, baseColumn: numberPrefix.length + bodyOffset, sourceBodyStart });
            bodyOffset += entry.body.length + 1;
          });
          cursor += Number(count);
        }
      });
      const value = output.join("\n");
      if (value === textarea.value) {
        window.alert("No safely condensable physical lines were found in that selection.");
        return;
      }
      let verification = null;
      if (validateBasic) {
        try { verification = await validateBasic(value, textarea.value); }
        catch (error) { window.alert(error.message || String(error)); return; }
      }
      const mapPosition = position => {
        let mapping = sourceMap.get(position.line);
        if (!mapping) {
          const nearest = [...sourceMap.entries()].sort((left, right) => Math.abs(left[0] - position.line) - Math.abs(right[0] - position.line))[0];
          mapping = nearest?.[1] || { outIndex: 0, baseColumn: 0, sourceBodyStart: 0 };
        }
        const lineOffset = output.slice(0, mapping.outIndex).reduce((total, line) => total + line.length + 1, 0);
        const column = mapping.baseColumn + Math.max(0, position.column - mapping.sourceBodyStart);
        return lineOffset + Math.min(column, output[mapping.outIndex]?.length || 0);
      };
      const selectionStart = sourcePosition(textarea.selectionStart);
      const selectionEnd = sourcePosition(textarea.selectionEnd);
      refactorPlan = {
        mode: "condense",
        before: textarea.value.split("\n"),
        preview: output,
        verification,
        after: {
          value,
          selectionStart: mapPosition(selectionStart),
          selectionEnd: mapPosition(selectionEnd),
          scrollTop: textarea.scrollTop,
          scrollLeft: textarea.scrollLeft,
        },
      };
      renderFolds();
    };
    const toggleComment = () => {
      if (language !== "basic" || textarea.readOnly) return;
      showOriginalView();
      const start = textarea.value.lastIndexOf("\n", Math.max(0, textarea.selectionStart - 1)) + 1;
      const followingBreak = textarea.value.indexOf("\n", textarea.selectionEnd);
      const end = followingBreak < 0 ? textarea.value.length : followingBreak;
      const selectedLines = textarea.value.slice(start, end).split("\n");
      const nonEmpty = selectedLines.filter(line => line.trim());
      const remove = nonEmpty.length > 0 && nonEmpty.every(line => /^\s*\d+\s+REM(?:\s|$)/i.test(line));
      const replacement = selectedLines.map(line => {
        if (!line.trim()) return line;
        if (remove) return line.replace(/^(\s*\d+\s+)REM\s?/i, "$1");
        return line.replace(/^(\s*\d+\s+)/, "$1REM ");
      }).join("\n");
      textarea.setRangeText(replacement, start, end, "select");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.focus();
      historyEntry(remove ? "Removed comments" : "Added comments", `${selectedLines.length} line${selectedLines.length === 1 ? "" : "s"}`);
    };
    const updateMenus = () => {
      root.querySelector('[data-editor-action="help-problems"] span')?.replaceChildren(document.createTextNode(`Problems (${state.issues.length})`));
      root.querySelector('[data-editor-action="help-symbols"] span')?.replaceChildren(document.createTextNode(`Document symbols (${state.symbols.length})`));
    };
    const render = () => {
      dismissHoverHelp(textarea.ownerDocument);
      state = { tokens: sourceTokens(textarea.value, language, inlineAssemblyLanguage), issues: diagnostics(textarea.value, language, dialect), symbols: symbols(textarea.value, language), blocks: foldBlocks(textarea.value, language) };
      const html = highlightedHtml(textarea.value, state.tokens);
      visual.querySelector("pre").innerHTML = html;
      hit.querySelector("pre").innerHTML = html;
      hit.querySelectorAll(".code-help-token").forEach(element => {
        const tokenLanguage = element.dataset.helpLanguage || language;
        const tokenStart = Number(element.dataset.tokenStart);
        const tokenEnd = Number(element.dataset.tokenEnd);
        const contextualHelp = sourceContextHelp(textarea.value, tokenLanguage, tokenStart, tokenEnd, element.dataset.helpKey, targetProfile);
        attachTooltip(root, tokenLanguage, element, element.dataset.helpKey, contextualHelp);
        element.addEventListener("pointerdown", event => {
          event.preventDefault();
          textarea.focus();
          textarea.setSelectionRange(tokenStart, tokenEnd);
          textarea.dispatchEvent(new Event("click", { bubbles: true }));
        });
      });
      syncScroll();
      updateMenus();
      renderStructureGuides();
      renderFolds();
    };
    const schedule = () => { clearTimeout(timer); timer = setTimeout(render, 80); };
    textarea.addEventListener("input", schedule);
    textarea.addEventListener("scroll", syncScroll, { passive: true });
    const updateCursorContext = () => { updateMenus(); renderStructureGuides(); };
    textarea.addEventListener("selectionchange", updateCursorContext);
    textarea.addEventListener("select", updateCursorContext);
    textarea.addEventListener("click", updateCursorContext);
    textarea.addEventListener("keyup", updateCursorContext);
    textarea.addEventListener("keydown", event => {
      if (event.key === "F1") { event.preventDefault(); helpAtCursor(); }
      else if (event.key === " " && (event.ctrlKey || event.metaKey)) { event.preventDefault(); showCompletions(); }
    });
    render();
    return { overview, helpAtCursor, showProblems, showSymbols, showCompletions, showCustom, findReferences, renameSymbol, showOutline, showHistory, compareWith, verifyRoundTrip, reference, goToLine, normaliseCommands, toggleComment, lineOperation, formatCode, condense, refactor, undo, redo, expandAll, collapseAll, toggleAll, toggleStructureGuides, setStructureGuideSize, showOriginalView, closeDrawer, refresh: render, recordHistory: historyEntry, state: () => state, history: () => pendingHistory };
  }

  function enhanceDisassembly({ root, report }) {
    if (!root) return null;
    const language = report.architecture || "6502";
    const drawer = document.createElement("section");
    drawer.className = "code-intelligence-drawer";
    drawer.hidden = true;
    root.insertBefore(drawer, root.querySelector(".editor-status"));
    const labelElements = [...root.querySelectorAll(".disassembly-label")];
    const labels = labelElements.map(element => ({ name: element.querySelector("span:last-child")?.textContent.replace(/:$/, "") || "Label", offset: Number(element.nextElementSibling?.dataset.offset || 0) }));
    const foldedLabels = new Set();
    const foldBlocks = labelElements.map((element, index) => {
      const rows = [];
      let sibling = element.nextElementSibling;
      while (sibling && !sibling.classList.contains("disassembly-label")) {
        if (sibling.classList.contains("disassembly-source-line")) rows.push(sibling);
        sibling = sibling.nextElementSibling;
      }
      return { id: String(index), element, rows, label: labels[index].name };
    }).filter(block => block.rows.length > 0);
    const renderFolds = () => {
      dismissHoverHelp(root.ownerDocument);
      const canFold = foldBlocks.length > 0;
      const foldAll = root.querySelector('[data-disassembly-action="fold-toggle-all"]');
      if (foldAll) {
        foldAll.disabled = !canFold;
        foldAll.querySelector("span").textContent = foldedLabels.size ? "Expand all labelled blocks" : "Collapse all labelled blocks";
      }
      foldBlocks.forEach(block => {
        const collapsed = foldedLabels.has(block.id);
        const cell = block.element.querySelector(".disassembly-fold-cell");
        cell.innerHTML = `<button type="button" class="code-fold-toggle" aria-expanded="${collapsed ? "false" : "true"}" title="${collapsed ? "Expand" : "Collapse"} ${esc(block.label)}">${collapsed ? "+" : "−"}</button>`;
        cell.querySelector("button").onclick = () => {
          if (collapsed) foldedLabels.delete(block.id);
          else foldedLabels.add(block.id);
          renderFolds();
        };
        block.element.classList.toggle("fold-collapsed", collapsed);
        block.rows.forEach(row => { row.hidden = collapsed; });
      });
    };
    const expandAll = () => { foldedLabels.clear(); renderFolds(); };
    const collapseAll = () => { foldBlocks.forEach(block => foldedLabels.add(block.id)); renderFolds(); };
    const toggleAll = () => foldedLabels.size ? expandAll() : collapseAll();
    const commands = new Set();
    const commandHelp = new Map();
    root.querySelectorAll(".disassembly-instruction").forEach((element, index) => {
      const row = report.rows[index] || { mnemonic: element.textContent.split(/\s+/)[0], operand: element.textContent.replace(/^\S+\s*/, "") };
      const mnemonic = normaliseHelpKey(row.mnemonic) || "DATA";
      const contextualHelp = disassemblyInstructionHelp(row, language);
      commands.add(mnemonic);
      if (!commandHelp.has(mnemonic)) commandHelp.set(mnemonic, contextualHelp);
      element.classList.add("code-help-token", "code-token-keyword");
      element.dataset.helpKey = mnemonic;
      element.setAttribute("aria-label", element.getAttribute("title") || element.textContent);
      element.removeAttribute("title");
      attachTooltip(root, language, element, mnemonic, contextualHelp);
    });
    root.querySelectorAll(".disassembly-comment").forEach(element => {
      const text = element.textContent;
      const pattern = new RegExp(`\\b(${Object.keys(MOS_HELP).join("|")})\\b`, "g");
      let cursor = 0;
      const chunks = [];
      for (const match of text.matchAll(pattern)) {
        chunks.push(esc(text.slice(cursor, match.index)), `<span class="code-help-token code-token-api" data-help-key="${match[1]}">${match[1]}</span>`);
        commands.add(match[1]);
        cursor = match.index + match[1].length;
      }
      if (!chunks.length) return;
      chunks.push(esc(text.slice(cursor)));
      element.innerHTML = chunks.join("");
      element.removeAttribute("title");
      element.querySelectorAll("[data-help-key]").forEach(tokenElement => attachTooltip(root, language, tokenElement, tokenElement.dataset.helpKey));
    });
    renderFolds();
    const show = (title, body) => {
      drawer.hidden = false;
      drawer.innerHTML = `<header><div><small>CODE-AWARE HELP</small><h3>${esc(title)}</h3></div><button type="button" class="code-drawer-close" aria-label="Close code help">×</button></header><div class="code-drawer-body">${body}</div>`;
      drawer.querySelector(".code-drawer-close").onclick = () => { drawer.hidden = true; };
      drawer.querySelectorAll("[data-code-help]").forEach(button => button.onclick = () => show(button.dataset.codeHelp, helpMarkup(commandHelp.get(button.dataset.codeHelp) || lookup(language, button.dataset.codeHelp))));
      drawer.querySelectorAll("[data-disassembly-offset]").forEach(button => button.onclick = () => root.querySelector(`.disassembly-source-line[data-offset="${button.dataset.disassemblyOffset}"]`)?.scrollIntoView({ block: "center" }));
    };
    const overview = () => show(`${languageName(language)} overview`, `<div class="code-overview"><p>This view contains <strong>${report.rows.length.toLocaleString()} decoded instructions or data records</strong>, <strong>${labels.length.toLocaleString()} labels</strong> and <strong>${report.strings.length.toLocaleString()} readable strings</strong>.</p><p>Hover a highlighted mnemonic or MOS routine for syntax, processor requirements and calling conventions. Disassembly remains read-only because data can resemble valid instructions.</p><h4>Recognised operations</h4><div class="code-command-chips">${[...commands].sort().map(key => `<button type="button" data-code-help="${key}">${key}</button>`).join("")}</div></div>`);
    const reference = () => show(`${languageName(language)} reference`, `<div class="code-reference-list">${[...new Set([...commands, ...Object.keys(INLINE_ASSEMBLER_HELP), ...Object.keys(ASM_HELP), ...Object.keys(MOS_HELP)])].sort().map(key => `<button type="button" data-code-help="${key}">${key}</button>`).join("")}</div>`);
    const showSymbols = () => show("Disassembly symbols", labels.length ? `<div class="code-symbol-list">${labels.map(item => `<button type="button" data-disassembly-offset="${item.offset}"><b>label</b><span>${esc(item.name)}</span></button>`).join("")}</div>` : '<p class="code-empty-message">No labels were discovered in this range.</p>');
    return { overview, reference, showSymbols, showCustom: show, expandAll, collapseAll, toggleAll, helpAtCursor: overview, showProblems: () => show("Disassembly cautions", '<p class="code-empty-message">No writable source diagnostics apply. Treat unknown opcodes, unreachable regions and embedded data as cautions rather than automatic errors.</p>') };
  }

  return { enhance, enhanceDisassembly, lookup, contextHelp: sourceContextHelp, diagnostics };
})();
