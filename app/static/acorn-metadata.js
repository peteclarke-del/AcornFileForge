(() => {
  "use strict";

  function firstPresent(entry, keys) {
    for (const key of keys) {
      if (entry?.[key] !== undefined && entry[key] !== null && entry[key] !== "") return entry[key];
    }
    return null;
  }

  function addressValue(entry, kind) {
    return kind === "load"
      ? firstPresent(entry, ["load", "loadHex"])
      : firstPresent(entry, ["exec", "execute", "executeHex"]);
  }

  function parseAddress(value) {
    if (typeof value === "number" && Number.isFinite(value)) return value >>> 0;
    const match = String(value ?? "").trim().match(/^(?:&|0x)?([0-9a-f]{1,8})$/i);
    return match ? Number.parseInt(match[1], 16) >>> 0 : null;
  }

  function formatAddress(value) {
    const parsed = parseAddress(value);
    return parsed === null ? "-" : `&${parsed.toString(16).toUpperCase().padStart(8, "0")}`;
  }

  function entryAddresses(entry) {
    const load = addressValue(entry, "load");
    const execute = addressValue(entry, "execute");
    return {
      available: load !== null || execute !== null,
      load: parseAddress(load),
      execute: parseAddress(execute),
      loadDisplay: formatAddress(load),
      executeDisplay: formatAddress(execute),
    };
  }

  function isRiscOsEncoded(entry) {
    const load = entryAddresses(entry).load;
    return entry?.filetype !== undefined && entry.filetype !== null && entry.filetype !== ""
      || load !== null && ((load & 0xFFF00000) >>> 0) === 0xFFF00000;
  }

  window.AcornMetadata = Object.freeze({
    addressValue,
    entryAddresses,
    formatAddress,
    isRiscOsEncoded,
    parseAddress,
  });
})();
