window.AcornPaneView = (() => {
  function create({ esc, humanSize }) {
    const paneFormat = image => {
      if (image.containerFormat === "hfe") return "HFE";
      if (image.kind === "mmb") return "MMB";
      if (image.kind === "tape") return "UEF";
      if (image.kind === "rom") return "ROM";
      if (image.kind === "romfs") return "RFS";
      if (image.kind === "dfs") return image.name.toLowerCase().endsWith(".dsd") ? "DSD" : "SSD";
      return "ADFS";
    };

    const capacityMarkup = capacity => {
      if (!capacity?.available || !capacity.total) {
        const reason = capacity?.reason || "Free-space information is loading.";
        return `<span class="capacity unavailable" title="${esc(reason)}" aria-label="${esc(reason)}"><i></i></span>`;
      }
      const usedPercent = Math.max(0, Math.min(100, capacity.used * 100 / capacity.total));
      const level = usedPercent >= 90 ? "critical" : usedPercent >= 70 ? "warning" : "healthy";
      const details = ["slots", "banks"].includes(capacity.unit)
        ? `${capacity.free} empty ${capacity.unit.slice(0, -1)}${capacity.free === 1 ? "" : "s"} of ${capacity.total} · ${capacity.used} populated · ${usedPercent.toFixed(1)}% full`
        : `${humanSize(capacity.free)} free of ${humanSize(capacity.total)} · ${humanSize(capacity.used)} used · ${usedPercent.toFixed(1)}% full`;
      return `<span class="capacity ${level}" role="progressbar" aria-label="${esc(details)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${usedPercent.toFixed(1)}" title="${esc(details)}" style="--capacity-used:${usedPercent}%"><i></i></span>`;
    };

    const crumbs = (path, dfs = false) => {
      if (dfs) {
        if (path === "") return '<span class="crumb current">Catalogues</span>';
        return `<button class="crumb" data-path="">Catalogues</button><span>›</span><span class="crumb current">${esc(path)}</span>`;
      }
      const parts = path.split(".");
      let current = "";
      return parts.map((part, index) => {
        current = index ? `${current}.${part}` : part;
        const klass = index === parts.length - 1 ? "crumb current" : "crumb";
        return `<button class="${klass}" data-path="${esc(current)}">${index ? "› " : ""}${esc(part)}</button>`;
      }).join("");
    };

    const archiveCrumbs = pane => {
      const parts = String(pane.archiveMember || "").split("/").filter(Boolean);
      let member = "";
      const children = parts.map((part, index) => {
        member = member ? `${member}/${part}` : part;
        const current = index === parts.length - 1;
        return `${current ? '<span class="crumb current">' : `<button class="crumb" data-archive-member="${esc(member)}">`}› ${esc(part)}${current ? "</span>" : "</button>"}`;
      }).join("");
      return `<button class="crumb archive-exit" title="Return to the containing filing system">${esc(pane.archiveName || "Archive")}</button>${children}`;
    };

    return { archiveCrumbs, capacityMarkup, crumbs, paneFormat };
  }

  return { create };
})();
