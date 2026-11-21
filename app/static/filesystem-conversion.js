// Convert a DFS floppy image to ADFS, or ADFS to DFS.
//
// The user picks a layout and sees what will be renamed or left out before
// anything is created. The converted image opens in another pane, which can
// then be saved, exported or written to a floppy like any other; the source
// pane is never changed.
window.AcornFilesystemConversion = (() => {
  function create({ panes, api, esc, showModal, toast, trackedPaneOperation, addPane, otherPaneIndexes, paneLabel, acceptImage }) {
    const json = (url, body) => api(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const NEW_PANE = "new";

    function preferredTarget(index) {
      // Lots of space suits DFS to ADFS; the larger DFS layout suits ADFS to DFS.
      return panes[index].image.kind === "dfs" ? "adfs-l" : "dfs-80-ds";
    }

    function list(items, render) {
      if (!items.length) return "";
      const shown = items.slice(0, 12).map(render).join("");
      const more = items.length > 12 ? `<li>…and ${items.length - 12} more</li>` : "";
      return `<ul class="conversion-list">${shown}${more}</ul>`;
    }

    function planMarkup(plan) {
      const dropped = plan.dropped.length
        ? `<div class="help-warning"><strong>${plan.dropped.length} file${plan.dropped.length === 1 ? "" : "s"} will not fit</strong> on a ${esc(plan.target.label)} disc.${list(plan.dropped, item => `<li><code>${esc(item.path)}</code>: ${esc(item.reason)}</li>`)}</div>
           <label class="check-field"><input type="checkbox" name="acceptLosses"> Convert without these files</label>`
        : "";
      const renamed = plan.renamed.length
        ? `<details class="conversion-renames"><summary>${plan.renamed.length} name${plan.renamed.length === 1 ? "" : "s"} will change</summary>${list(plan.renamed, item => `<li><code>${esc(item.from)}</code> → <code>${esc(item.to)}</code></li>`)}</details>`
        : "";
      const notes = plan.notes.map(note => `<p class="conversion-note">${esc(note)}</p>`).join("");
      return `<p><strong>${plan.files} file${plan.files === 1 ? "" : "s"}</strong> will be copied with their load and execution addresses, access and the disc's boot option.</p>${notes}${renamed}${dropped}`;
    }

    async function open(index) {
      const pane = panes[index];
      const { targets } = await api(`/api/images/${pane.image.id}/filesystem-conversion`);
      if (!targets.length) return toast("This image cannot be converted to another filesystem.", true);
      const other = pane.image.kind === "dfs" ? "ADFS" : "DFS";
      const destinations = [
        `<option value="${NEW_PANE}" selected>A new pane</option>`,
        ...otherPaneIndexes(index).map(offset => `<option value="${offset}">${esc(paneLabel(offset))}</option>`),
      ].join("");
      showModal(`<div class="analysis-dialog conversion-dialog"><header><div><small>CONVERT</small><h2>Convert ${esc(pane.image.name)} to ${other}</h2></div></header>
        <label class="field"><span>Layout</span><select name="target">${targets.map(item => `<option value="${esc(item.id)}"${item.id === preferredTarget(index) ? " selected" : ""}>${esc(item.label)}</option>`).join("")}</select></label>
        <div class="conversion-plan" aria-live="polite"><p>Checking what fits…</p></div>
        <label class="field"><span>Open converted image in</span><select name="targetPane">${destinations}</select></label>
        <div class="help-note">The converted image is a new working copy. This pane is not changed.</div>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="convert">Convert</button></div></div>`,
      async form => {
        const choice = String(form.get("targetPane"));
        if (choice !== NEW_PANE && panes[Number(choice)]?.image?.dirty
          && !confirm(`Replace ${paneLabel(Number(choice))} without saving its edited image?`)) return false;
        const data = await trackedPaneOperation(
          index,
          `Converting to ${other}`,
          operationId => json(`/api/images/${pane.image.id}/filesystem-conversion`, {
            target: form.get("target"),
            acceptLosses: form.get("acceptLosses") === "on",
            operationId,
          }),
        );
        const targetIndex = choice === NEW_PANE ? addPane() : Number(choice);
        await acceptImage(targetIndex, data.image);
        const left = data.plan.dropped.length;
        toast(`Converted ${data.plan.files} file${data.plan.files === 1 ? "" : "s"} to ${data.plan.target.label}${left ? ` · ${left} left out` : ""}.`);
      });

      const dialog = document.querySelector("#modalContent .conversion-dialog");
      const select = dialog.querySelector('select[name="target"]');
      const holder = dialog.querySelector(".conversion-plan");
      const convertButton = dialog.querySelector('button[value="convert"]');
      let request = 0;
      const refresh = async () => {
        const current = ++request;
        holder.innerHTML = "<p>Checking what fits…</p>";
        convertButton.disabled = true;
        try {
          const { plan } = await api(`/api/images/${pane.image.id}/filesystem-conversion?target=${encodeURIComponent(select.value)}`);
          if (current !== request) return;
          holder.innerHTML = planMarkup(plan);
          const accept = holder.querySelector('input[name="acceptLosses"]');
          convertButton.disabled = Boolean(accept) || plan.files === 0;
          accept?.addEventListener("change", () => { convertButton.disabled = !accept.checked; });
        } catch (error) {
          if (current === request) holder.innerHTML = `<div class="help-warning">${esc(error.message)}</div>`;
        }
      };
      select.addEventListener("change", refresh);
      refresh();
    }

    return { open };
  }

  return { create };
})();
