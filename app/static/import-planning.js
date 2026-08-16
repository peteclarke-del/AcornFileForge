(() => {
  "use strict";

  function targetNameRule(pane, original) {
    if (pane.image?.kind === "rom") return { valid: true, suggested: original, limit: 180, label: "ROM bank", adjusted: false, truncated: false };
    if (pane.image?.kind === "romfs") {
      const raw = String(original || "");
      const suggested = raw.normalize("NFKD").replace(/[^\x20-\xff]/g, "_").slice(0, 10) || "FILE";
      return {
        valid: raw.length > 0 && raw.length <= 10 && !/[\x00-\x1f]/.test(raw),
        suggested, limit: 10, label: "ROMFS", adjusted: raw !== suggested, truncated: raw.length > 10,
      };
    }
    const isDfs = pane.image?.kind === "dfs" || (pane.image?.kind === "mmb" && pane.slot !== null);
    const limit = isDfs ? 7 : Number(pane.image?.filesystemCapabilities?.nameLimit || 10);
    const label = isDfs ? "DFS" : "ADFS";
    const raw = String(original || "").split(/[/:]/).pop();
    let suggested = raw.normalize("NFKD").replace(/[^\x20-\x7e]/g, "").replace(/[.:*#/]/g, "_").slice(0, limit);
    if (!suggested) suggested = "FILE";
    const valid = raw.length > 0 && raw.length <= limit && !/[.:*#/\x00-\x1f]/.test(raw);
    return { valid, suggested, limit, label, adjusted: !valid || raw !== suggested, truncated: raw.length > limit };
  }

  function ignoredFolderFile(name) {
    const parts = String(name).replace(/\\/g, "/").split("/");
    const leaf = parts.at(-1).toLowerCase();
    return leaf === ".ds_store" || leaf === "thumbs.db" || leaf === "desktop.ini"
      || parts.some(part => part === "__MACOSX");
  }

  function normaliseHostAddress(value) {
    const match = String(value || "").trim().match(/^(?:0x|&)?([0-9a-f]{1,8})$/i);
    return match ? `0x${match[1].toUpperCase()}` : "";
  }

  function metadataFromHostFilename(filename) {
    const match = String(filename).match(/^(.*?),(?:0x|&)?([0-9a-f]{4,8})(?:-(?:0x|&)?([0-9a-f]{4,8}))?$/i);
    if (!match) return {};
    return {
      targetName: match[1],
      load: normaliseHostAddress(match[2]),
      execute: normaliseHostAddress(match[3] || match[2]),
    };
  }

  function allocateFilesToDfsDisks(items, diskFormat) {
    const sidesPerDisk = diskFormat === "dsd" ? 2 : 1;
    const disks = [];
    let disk = null;
    let side = 0;
    let sideFiles = 0;
    let sideSectors = 0;
    for (const item of items) {
      const sectors = Math.max(1, Math.ceil(Number(item.length || 0) / 256));
      if (sectors > 798) throw new Error(`${item.name} is too large for one DFS disk side.`);
      if (!disk || sideFiles >= 31 || sideSectors + sectors > 798) {
        if (disk && side + 1 < sidesPerDisk) side += 1;
        else {
          disk = { files: [] };
          disks.push(disk);
          side = 0;
        }
        sideFiles = 0;
        sideSectors = 0;
      }
      disk.files.push({ ...item, targetSide: side === 1 ? 2 : 0 });
      sideFiles += 1;
      sideSectors += sectors;
    }
    return disks;
  }

  function uniqueDfsNames(items) {
    const used = new Set();
    return items.map(item => {
      const rule = targetNameRule({ image: { kind: "dfs" } }, item.name);
      let proposed = rule.suggested;
      let suffix = 1;
      while (used.has(proposed.toLowerCase())) {
        const tail = String(suffix++);
        proposed = `${rule.suggested.slice(0, Math.max(1, 7 - tail.length))}${tail}`;
      }
      used.add(proposed.toLowerCase());
      const first = String(item.path || "").split(".")[0].toUpperCase();
      return { ...item, targetName: proposed, prefix: /^[A-Z$]$/.test(first) ? first : "$" };
    });
  }

  window.AcornImportPlanning = Object.freeze({
    allocateFilesToDfsDisks,
    ignoredFolderFile,
    metadataFromHostFilename,
    normaliseHostAddress,
    targetNameRule,
    uniqueDfsNames,
  });
})();
