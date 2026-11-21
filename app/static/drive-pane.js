// Panes bound to a disk in a Greaseweazle drive.
//
// Opening a drive reads the disk once into the pane's working image. Every
// edit after that stays in the working image; the disk is written only when
// the user presses "Write to disk", and formatted only after they confirm it.
window.AcornDrivePane = (() => {
  const DRIVES = ["A", "B", "0", "1", "2", "3"];

  function create({ panes, api, esc, showModal, modal, toast, trackedPaneOperation, acceptImage }) {
    const post = (url, body) => api(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const driveOptions = selected => DRIVES
      .map(drive => `<option value="${esc(drive)}"${drive === selected ? " selected" : ""}>Drive ${esc(drive)}</option>`)
      .join("");

    function formatOptions(formats, allowed, selected) {
      const choices = allowed?.length ? formats.filter(item => allowed.includes(item.id)) : formats;
      return choices
        .map(item => `<option value="${esc(item.id)}"${item.id === selected ? " selected" : ""}>${esc(item.label)}</option>`)
        .join("");
    }

    const stepField = step => `<label class="field"><span>Head stepping</span><select name="step">
        <option value="1"${step === 1 ? " selected" : ""}>Single step (80-track disk, or 40-track drive)</option>
        <option value="2"${step === 2 ? " selected" : ""}>Double step (40-track disk in an 80-track drive)</option>
      </select></label>`;

    // Step 1: choose a drive, then probe what is in it.
    function openDrive(index, drive = "A") {
      showModal(`<div class="analysis-dialog physical-floppy-dialog"><header><div><small>FLOPPY DRIVE</small><h2>Open a disk in a drive</h2></div></header>
        <p>The disk is read into this pane and identified automatically. Nothing is written to it until you choose <strong>Write to disk</strong>.</p>
        <label class="field"><span>Greaseweazle drive</span><select name="drive">${driveOptions(drive)}</select></label>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="probe">Read disk</button></div></div>`,
      async form => {
        const chosen = String(form.get("drive"));
        const data = await trackedPaneOperation(
          index,
          `Checking the disk in drive ${chosen}`,
          operationId => post("/api/desktop/drive/probe", { drive: chosen, operationId }),
          { abortMode: "physical" },
        );
        const { detection, formats } = data;
        if (detection.status === "formatted") {
          await readDisk(index, chosen, detection.format.id, detection.step, detection.format.label);
          return;
        }
        if (detection.status === "unformatted") {
          offerFormat(index, chosen, formats, detection.detail);
        } else {
          askFormat(index, chosen, formats, detection);
        }
        return false;
      });
    }

    async function readDisk(index, drive, format, step, label) {
      const data = await trackedPaneOperation(
        index,
        `Reading ${label} from drive ${drive}`,
        operationId => post("/api/desktop/drive/open", { drive, format, step, operationId }),
        { abortMode: "physical" },
      );
      await acceptImage(index, data.image);
      const missing = data.image.physicalDrive?.missingSectors || 0;
      toast(missing
        ? `Disk read with ${missing} unreadable sectors. Check it before writing back.`
        : `Disk in drive ${drive} opened. Changes stay in this pane until you write them.`,
      Boolean(missing));
    }

    // A disk with sectors that match no single Acorn layout.
    function askFormat(index, drive, formats, detection) {
      showModal(`<div class="analysis-dialog physical-floppy-dialog"><header><div><small>FLOPPY DRIVE</small><h2>Which format is this disk?</h2></div></header>
        <p>${esc(detection.detail)}</p>
        <label class="field"><span>Disk format</span><select name="format">${formatOptions(formats, detection.candidates, detection.candidates?.[0])}</select></label>
        ${stepField(2)}
        <div class="help-note"><strong>Reading is safe.</strong> Choosing the wrong format only gives an unreadable pane; the disk is not changed.</div>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="read">Read disk</button></div></div>`,
      async form => {
        const format = String(form.get("format"));
        const label = formats.find(item => item.id === format)?.label || format;
        await readDisk(index, drive, format, Number(form.get("step")), label);
      }, { replace: true });
    }

    // A blank disk: formatting is offered, never assumed.
    function offerFormat(index, drive, formats, detail) {
      showModal(`<div class="analysis-dialog physical-floppy-dialog"><header><div><small>FLOPPY DRIVE</small><h2>Format this disk?</h2></div></header>
        <p>${esc(detail)}</p>
        <label class="field"><span>Format as</span><select name="format">${formatOptions(formats, null, "adfs-l")}</select></label>
        <label class="field"><span>Disk title</span><input name="title" maxlength="12" value="Blank"></label>
        ${stepField(1)}
        <div class="help-warning"><strong>This erases the disk in drive ${esc(drive)}.</strong> Anything on it, including data in a format this tool does not recognise, is lost.</div>
        <label class="check-field physical-floppy-confirm"><input type="checkbox" name="confirmed" required> Format the disk in drive ${esc(drive)}</label>
        <div class="modal-actions"><button class="button ghost" value="cancel">Don't format</button><button class="button danger" value="format">Format disk</button></div></div>`,
      async form => {
        const format = String(form.get("format"));
        const data = await trackedPaneOperation(
          index,
          `Formatting the disk in drive ${drive}`,
          operationId => post("/api/desktop/drive/format", {
            drive,
            format,
            step: Number(form.get("step")),
            title: String(form.get("title") || ""),
            confirm: form.get("confirmed") === "on",
            operationId,
          }),
          { abortMode: "physical" },
        );
        await acceptImage(index, data.image);
        toast(`Disk in drive ${drive} formatted and opened.`);
      }, { replace: true });
    }

    function writeToDisk(index) {
      const pane = panes[index];
      const binding = pane?.image?.physicalDrive;
      if (!binding) return;
      const missing = binding.missingSectors
        ? `<div class="help-warning"><strong>${binding.missingSectors} sectors could not be read</strong> when this disk was opened. Writing makes their zero-filled contents permanent.</div>`
        : "";
      showModal(`<div class="analysis-dialog physical-floppy-dialog"><header><div><small>FLOPPY DRIVE</small><h2>Write to the disk in drive ${esc(binding.drive)}?</h2></div></header>
        <dl class="physical-floppy-summary"><div><dt>Format</dt><dd>${esc(binding.format.label)}</dd></div><div><dt>Stepping</dt><dd>${binding.step === 2 ? "Double" : "Single"}</dd></div></dl>
        <p>${binding.unwritten ? "The pane's changes" : "The pane's contents, which match the disk,"} will be written to every track and read back to verify them.</p>
        ${missing}
        <div class="help-warning"><strong>Check the right disk is in drive ${esc(binding.drive)}.</strong> Its contents will be replaced.</div>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button danger" value="write">Write and verify</button></div></div>`,
      async () => {
        const data = await trackedPaneOperation(
          index,
          `Writing to the disk in drive ${binding.drive}`,
          operationId => post(`/api/desktop/images/${pane.image.id}/drive/write`, { operationId }),
          { abortMode: "physical" },
        );
        await acceptImage(index, data.image);
        toast(data.result.verified ? "Disk written and verified." : "Disk written.", !data.result.verified);
      });
    }

    // Header controls for a drive pane: where it lives and whether it has
    // changes still to write.
    function headerMarkup(pane) {
      const binding = pane.image?.physicalDrive;
      if (!binding) return "";
      const state = binding.unwritten ? "Changes not yet written" : "Matches the disk";
      return `<span class="drive-badge${binding.unwritten ? " unwritten" : ""}" title="${esc(state)}">Drive ${esc(binding.drive)} · ${esc(state)}</span>
        <button class="button ${binding.unwritten ? "primary" : "ghost"} compact drive-write" type="button" title="Write this pane to the disk in drive ${esc(binding.drive)}">Write to disk</button>`;
    }

    function bindHeader(host, index) {
      host.querySelector(".drive-write")?.addEventListener("click", () => writeToDisk(index));
    }

    const unwritten = pane => Boolean(pane?.image?.physicalDrive?.unwritten);

    return { openDrive, writeToDisk, headerMarkup, bindHeader, unwritten };
  }

  return { create };
})();
