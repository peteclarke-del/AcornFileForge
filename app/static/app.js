function newPaneState(image = null) {
  return {
    image,
    slot: null,
    side: image?.doubleSided ? 0 : null,
    slotName: "",
    path: image?.kind === "dfs" ? "" : "$",
    entries: [],
    capacity: null,
    selected: null,
    selection: [],
    selectionAnchor: null,
    loading: Boolean(image),
    requestToken: 0,
    menuDetected: false,
    menuDetectionPending: Boolean(image?.kind === "mmb")
  };
}

function isDfsPane(pane) {
  return pane?.image?.kind === "dfs" || (pane?.image?.kind === "mmb" && pane.slot !== null);
}

function restoredDfsPath(saved) {
  if (saved?.pathModel === "dfs-prefixes") return typeof saved.path === "string" ? saved.path : "";
  return saved?.path === "$" || typeof saved?.path !== "string" ? "" : saved.path;
}

const MAX_PANES = 3;
const panes = [newPaneState()];

const {
  api: rawApi,
  uploadApi: rawUploadApi,
  esc,
  humanSize,
  modal,
  modalContent,
  setModalAbort,
  setModalProgress,
  showModal,
  toast,
} = window.AcornUI;
const formats = window.AcornFormats;
const OPEN_PANES_STORAGE_KEY = "acorn-file-forge-dynamic-panes";
let workspacePersistenceReady = false;
let workspaceClipboard = null;
let clipboardMutationInProgress = false;

function clearWorkspaceClipboard(message = "", rerender = true) {
  if (!workspaceClipboard) return;
  workspaceClipboard = null;
  document.querySelectorAll(".clipboard-cut").forEach(row => row.classList.remove("clipboard-cut"));
  if (rerender) panes.forEach((_pane, index) => renderPane(index, true));
  if (message) toast(message);
}

function api(url, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  if (!["GET", "HEAD"].includes(method) && workspaceClipboard && !clipboardMutationInProgress) {
    clearWorkspaceClipboard("Clipboard cleared because another change was started.");
  }
  return rawApi(url, options);
}

function uploadApi(url, formData, options = {}) {
  if (workspaceClipboard && !clipboardMutationInProgress) {
    clearWorkspaceClipboard("Clipboard cleared because another change was started.");
  }
  return rawUploadApi(url, formData, options);
}

const PANE_ICONS = {
  newImage: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4V20.5H6z"/><path d="M14 3.5v4h4M9 14h6M12 11v6"/></svg>',
  loadImage: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.5 19.5V5.5h6l2 2h8v3"/><path d="M3.5 19.5 6 10.5h15l-2.5 9z"/></svg>',
  saveImage: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 3.5h13l3 3v14H4z"/><path d="M7 3.5v6h9v-6M7.5 20.5v-7h9v7"/></svg>',
  refreshView: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 8.5A8 8 0 1 0 20 15"/><path d="M19.5 3.5v5h-5"/></svg>',
  closePane: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6.5 6.5 11 11M17.5 6.5l-11 11"/></svg>',
};

function normalisePage(value) {
  const cleaned = String(value || "").trim().replace(/^&/, "").toUpperCase();
  return cleaned.replace(/^0+(?=[0-9A-F])/, "") || "0";
}

function keepFocusInside(container, event) {
  if (event.key !== "Tab") return;
  const controls = [...container.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')]
    .filter(control => !control.hidden && control.getClientRects().length);
  if (!controls.length) return event.preventDefault();
  const first = controls[0];
  const last = controls[controls.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function confirmPageOverride(defaultPage, chosenPage, subjects = []) {
  if (Array.isArray(defaultPage)) {
    const overrides = defaultPage.filter(item => item?.defaultPage && item?.chosenPage);
    if (!overrides.length) return Promise.resolve(true);
    return new Promise(resolve => {
      const overlay = document.createElement("div");
      overlay.className = "page-warning-overlay";
      overlay.setAttribute("role", "alertdialog");
      overlay.setAttribute("aria-modal", "true");
      overlay.setAttribute("aria-labelledby", "page-warning-title");
      overlay.innerHTML = `<div class="page-warning-card">
        <span class="page-warning-icon" aria-hidden="true">!</span>
        <h2 id="page-warning-title">Use ${overrides.length} changed PAGE ${overrides.length === 1 ? "value" : "values"}?</h2>
        <p>These values differ from the launchers in the actual disk images.</p>
        <div class="page-warning-list">${overrides.slice(0, 8).map(item =>
          `<span><b>${esc(item.title)}</b><small>&amp;${esc(normalisePage(item.defaultPage))} recommended → &amp;${esc(normalisePage(item.chosenPage))} entered</small></span>`
        ).join("")}${overrides.length > 8 ? `<em>and ${overrides.length - 8} more…</em>` : ""}</div>
        <div class="help-warning"><strong>Risk:</strong> the wrong PAGE can overwrite filing-system workspace or loader data, corrupt BASIC, hang, or crash on real hardware.</div>
        <div class="modal-actions"><button type="button" class="button ghost" data-page-cancel>Cancel</button><button type="button" class="button primary" data-page-confirm>Yes, use changed values</button></div>
      </div>`;
      const previouslyFocused = document.activeElement;
      const finish = result => { overlay.remove(); previouslyFocused?.focus(); resolve(result); };
      overlay.querySelector("[data-page-cancel]").onclick = () => finish(false);
      overlay.querySelector("[data-page-confirm]").onclick = () => finish(true);
      overlay.onkeydown = event => { if (event.key === "Escape") finish(false); else keepFocusInside(overlay, event); };
      document.body.append(overlay);
      overlay.querySelector("[data-page-cancel]").focus();
    });
  }
  if (!defaultPage || normalisePage(defaultPage) === normalisePage(chosenPage)) {
    return Promise.resolve(true);
  }
  const labels = Array.isArray(subjects) ? subjects.filter(Boolean) : [subjects].filter(Boolean);
  return new Promise(resolve => {
    const overlay = document.createElement("div");
    overlay.className = "page-warning-overlay";
    overlay.setAttribute("role", "alertdialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "page-warning-title");
    overlay.innerHTML = `<div class="page-warning-card">
      <span class="page-warning-icon" aria-hidden="true">!</span>
      <h2 id="page-warning-title">Use a different PAGE value?</h2>
      <p>The actual launcher in the disk image indicates <strong>&amp;${esc(normalisePage(defaultPage))}</strong>, but you entered <strong>&amp;${esc(normalisePage(chosenPage))}</strong>.</p>
      ${labels.length ? `<p class="page-warning-subject">${esc(labels.slice(0, 4).join(", "))}${labels.length > 4 ? ` and ${labels.length - 4} more` : ""}</p>` : ""}
      <div class="help-warning"><strong>Risk:</strong> the wrong PAGE can overwrite filing-system workspace or loader data, corrupt BASIC, hang, or crash on real hardware.</div>
      <div class="modal-actions"><button type="button" class="button ghost" data-page-cancel>Cancel</button><button type="button" class="button primary" data-page-confirm>Yes, use &amp;${esc(normalisePage(chosenPage))}</button></div>
    </div>`;
    const previouslyFocused = document.activeElement;
    const finish = result => {
      overlay.remove();
      previouslyFocused?.focus();
      resolve(result);
    };
    overlay.querySelector("[data-page-cancel]").onclick = () => finish(false);
    overlay.querySelector("[data-page-confirm]").onclick = () => finish(true);
    overlay.onkeydown = event => {
      if (event.key === "Escape") finish(false);
      else keepFocusInside(overlay, event);
    };
    document.body.append(overlay);
    overlay.querySelector("[data-page-cancel]").focus();
  });
}

async function mmbRecommendedPage(imageId, slot, filename, action) {
  return api(`/api/images/${imageId}/metadata/page`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slot, filename, action })
  });
}

function rememberOpenPanes() {
  if (!workspacePersistenceReady) return;
  const snapshot = panes.map(pane => pane.image ? {
    imageId: pane.image.id,
    slot: pane.slot,
    side: pane.side,
    path: pane.path,
    pathModel: isDfsPane(pane) ? "dfs-prefixes" : "hierarchical",
  } : null);
  try {
    localStorage.setItem(OPEN_PANES_STORAGE_KEY, JSON.stringify(snapshot));
  } catch (_error) {
    // Recovery remains available from the server when browser storage is unavailable.
  }
}

function storedOpenPanes() {
  try {
    const saved = JSON.parse(localStorage.getItem(OPEN_PANES_STORAGE_KEY) || "[]");
    return Array.isArray(saved) ? saved.slice(0, MAX_PANES) : [];
  } catch (_error) {
    return [];
  }
}

function hasStoredOpenPanes() {
  try {
    return localStorage.getItem(OPEN_PANES_STORAGE_KEY) !== null;
  } catch (_error) {
    return true;
  }
}

async function restoreOpenPanes() {
  let savedPanes = storedOpenPanes();
  if (!hasStoredOpenPanes()) {
    try {
      const recoverable = await api("/api/images/recoverable");
      const newest = recoverable.images?.[0];
      if (newest) savedPanes = [{ imageId: newest.id, slot: null, side: null, path: "$" }];
    } catch (_error) {
      // Leave the normal empty workspace available if recovery is unavailable.
    }
  }
  const restoredPaneCount = Math.max(1, Math.min(MAX_PANES, savedPanes.length || 1));
  while (panes.length < restoredPaneCount) panes.push(newPaneState());
  rebuildPaneHosts();
  for (const [index, saved] of savedPanes.entries()) {
    if (!saved || !/^[0-9a-f]{32}$/.test(String(saved.imageId || ""))) continue;
    panes[index].loading = true;
    panes[index].loadingMessage = "Restoring your open image…";
    renderPane(index);
    try {
      const data = await api(`/api/images/${encodeURIComponent(saved.imageId)}`);
      await acceptImage(index, data.image);
      const pane = panes[index];
      pane.side = saved.side === 2 ? 2 : data.image.doubleSided ? 0 : null;
      if (data.image.kind === "mmb" && Number.isInteger(saved.slot)) {
        const disk = pane.entries.find(entry => entry.slot === saved.slot && entry.formatted);
        if (disk) {
          pane.slot = saved.slot;
          pane.slotName = disk.name;
          pane.path = restoredDfsPath(saved);
          await loadDirectory(index);
        }
      } else if (
        data.image.kind !== "mmb"
        && typeof saved.path === "string"
        && (
          (data.image.kind === "dfs" && restoredDfsPath(saved) !== "")
          || (data.image.kind !== "dfs" && saved.path !== "$")
          || pane.side !== (data.image.doubleSided ? 0 : null)
        )
      ) {
        pane.path = data.image.kind === "dfs" ? restoredDfsPath(saved) : saved.path;
        await loadDirectory(index);
      }
    } catch (error) {
      panes[index] = newPaneState();
      renderPane(index);
      if (error.status !== 404) toast(`Could not restore an open pane: ${error.message}`, true);
    }
  }
  workspacePersistenceReady = true;
  rememberOpenPanes();
  panes.forEach((_pane, index) => renderPane(index));
}

function updateAddPaneButton() {
  const button = document.querySelector("#addPaneButton");
  if (!button) return;
  button.disabled = panes.length >= MAX_PANES;
  button.title = button.disabled ? "Maximum of three panes open" : "Add another work pane";
  button.setAttribute("aria-label", button.title);
}

function rebuildPaneHosts() {
  const host = document.querySelector(".panes");
  host.dataset.count = String(panes.length);
  host.style.setProperty("--pane-count", String(Math.max(1, panes.length)));
  host.innerHTML = panes.map((_pane, index) =>
    `<article class="pane" data-pane="${index}"></article>`
  ).join("");
  panes.forEach((_pane, index) => renderPane(index));
  updateAddPaneButton();
}

function addPane() {
  if (panes.length >= MAX_PANES) return;
  panes.push(newPaneState());
  rebuildPaneHosts();
  rememberOpenPanes();
}

function otherPaneIndexes(index) {
  return panes.map((_pane, offset) => offset).filter(offset => offset !== index);
}

function preferredDestinationPane(index) {
  return otherPaneIndexes(index).find(offset => !panes[offset].image)
    ?? otherPaneIndexes(index)[0];
}

function paneLabel(index) {
  return `Pane ${index + 1}${panes[index].image ? ` · ${panes[index].image.name}` : " · Empty"}`;
}

function openDiskPaneSource(index) {
  const pane = panes[index];
  if (!pane?.image) return null;
  if (pane.image.kind === "dfs") {
    return {
      image: pane.image.id,
      slot: null,
      name: pane.image.name,
      label: pane.image.name,
      compatible: true,
    };
  }
  if (pane.image.kind === "mmb" && pane.slot !== null) {
    return {
      image: pane.image.id,
      slot: pane.slot,
      name: pane.slotName || `Slot ${pane.slot}`,
      label: `${pane.image.name} · slot ${pane.slot} · ${pane.slotName || "Untitled disk"}`,
      compatible: true,
    };
  }
  return {
    image: pane.image.id,
    slot: null,
    name: pane.image.name,
    label: pane.image.name,
    compatible: false,
    reason: pane.image.kind === "mmb"
      ? "Open a disk inside this MMB first"
      : "MMB slots accept DFS disks only",
  };
}

function openDiskImportMarkup(targetIndex) {
  const emptySlotSelected = Boolean(selectedEntry(targetIndex)?.empty);
  const sources = otherPaneIndexes(targetIndex)
    .map(sourceIndex => ({ sourceIndex, source: openDiskPaneSource(sourceIndex) }))
    .filter(item => item.source);
  if (!sources.length) {
    return '<button class="menu-command import-open-disk" disabled><b>↥</b><span>Import from open… <small>No other image is open</small></span></button>';
  }
  return sources.map(({ sourceIndex, source }) => {
    const disabled = !emptySlotSelected || !source.compatible;
    const reason = !emptySlotSelected
      ? "Select one empty destination slot"
      : source.reason || "";
    return `<button class="menu-command import-open-disk" data-source-pane="${sourceIndex}" ${disabled ? "disabled" : ""} title="${esc(reason || `Import ${source.label} into the selected slot`)}"><b>↥</b><span>Import from open ${esc(source.label)}${reason ? ` <small>${esc(reason)}</small>` : ""}</span></button>`;
  }).join("");
}

function refreshOpenDiskImportMenu(targetIndex, menu) {
  const host = menu.querySelector(".open-disk-imports");
  if (!host) return;
  host.innerHTML = openDiskImportMarkup(targetIndex);
  host.querySelectorAll(".import-open-disk[data-source-pane]").forEach(button => {
    button.onclick = () => {
      if (button.disabled) return;
      const targetSlot = selectedEntry(targetIndex)?.slot;
      const source = openDiskPaneSource(Number(button.dataset.sourcePane));
      menu.removeAttribute("open");
      if (targetSlot == null || !selectedEntry(targetIndex)?.empty) {
        return toast("Select one empty MMB slot first.", true);
      }
      if (!source?.compatible) {
        return toast(source?.reason || "That pane does not contain an MMB-compatible disk image.", true);
      }
      guardedPaneAction(targetIndex, () => insertSessionIntoSlot(targetIndex, targetSlot, source));
    };
  });
}

function paneDragHandle(index) {
  return `<button class="pane-drag-handle" type="button" draggable="true" title="Drag to swap, or press Alt+Left / Alt+Right" aria-label="Reorder pane ${index + 1}. Drag it, or press Alt plus Left or Right"><b>⠿</b><small>${index + 1}</small></button>`;
}

function wirePaneDragHandle(host, index) {
  const handle = host.querySelector(".pane-drag-handle");
  if (!handle) return;
  handle.draggable = !panes[index].loading && !panes[index].actionPending;
  handle.ondragstart = event => {
    event.stopPropagation();
    if (!handle.draggable) return event.preventDefault();
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-acorn-pane", String(index));
    event.dataTransfer.setData("text/plain", `Move pane ${index + 1}`);
    host.classList.add("pane-moving");
  };
  handle.ondragend = () => {
    document.querySelectorAll(".pane").forEach(pane =>
      pane.classList.remove("pane-moving", "pane-swap-target")
    );
  };
  handle.onkeydown = event => {
    if (!event.altKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const targetIndex = index + (event.key === "ArrowLeft" ? -1 : 1);
    if (targetIndex < 0 || targetIndex >= panes.length) return;
    event.preventDefault();
    swapPanes(index, targetIndex);
    document.querySelector(`.pane[data-pane="${targetIndex}"] .pane-drag-handle`)?.focus();
    toast(`Pane moved to position ${targetIndex + 1}`);
  };
}

function swapPanes(sourceIndex, targetIndex) {
  if (sourceIndex === targetIndex || !panes[sourceIndex] || !panes[targetIndex]) return;
  if ([panes[sourceIndex], panes[targetIndex]].some(pane => pane.loading || pane.actionPending)) {
    return toast("Wait for both pane operations to finish before swapping them.", true);
  }
  const sourceScroll = document.querySelector(`.pane[data-pane="${sourceIndex}"] .list-wrap`)?.scrollTop || 0;
  const targetScroll = document.querySelector(`.pane[data-pane="${targetIndex}"] .list-wrap`)?.scrollTop || 0;
  [panes[sourceIndex], panes[targetIndex]] = [panes[targetIndex], panes[sourceIndex]];
  renderPane(sourceIndex);
  renderPane(targetIndex);
  const sourceList = document.querySelector(`.pane[data-pane="${sourceIndex}"] .list-wrap`);
  const targetList = document.querySelector(`.pane[data-pane="${targetIndex}"] .list-wrap`);
  if (sourceList) sourceList.scrollTop = targetScroll;
  if (targetList) targetList.scrollTop = sourceScroll;
  rememberOpenPanes();
}

function setLoading(index, value, message = "Reading disk…") {
  const displayMessage = typeof message === "object"
    ? (message.message || message.title || "Working…")
    : message;
  panes[index].loading = value;
  panes[index].loadingMessage = displayMessage;
  if (value && modal.open) setModalProgress(message);
  renderPane(index);
}

async function paneOperation(index, message, operation) {
  const pane = panes[index];
  setLoading(index, true, message);
  try {
    return await operation();
  } finally {
    if (panes[index] === pane) {
      pane.loading = false;
      pane.loadingMessage = "";
      renderPane(index);
    }
  }
}

async function trackedPaneOperation(index, message, operation) {
  const pane = panes[index];
  const operationId = crypto.randomUUID();
  let polling = true;
  let abortRequested = false;
  setLoading(index, true, message);
  if (modal.open) {
    setModalAbort(async () => {
      abortRequested = true;
      setModalProgress({
        title: "Stopping operation safely",
        message: "Finishing the current atomic disk command. No further disks or files will be started.",
        details: [
          { label: "Safety", value: "The current image write will complete or be cleaned up before stopping" },
          { label: "Completed work", value: "Previously completed batch items will be preserved" }
        ]
      });
      await api(`/api/operations/${operationId}/cancel`, { method: "POST" });
    });
  }
  const poll = async () => {
    try {
      const data = await api(`/api/operations/${operationId}`);
      if (!polling || panes[index] !== pane) return;
      const progress = data.operation;
      if (progress.state === "cancelling") {
        pane.loadingMessage = progress.message;
        if (modal.open) {
          setModalProgress({
            title: "Stopping operation safely",
            message: "Finishing the current atomic disk command. No further disks or files will be started.",
            details: [
              { label: "Safety", value: "The current image write will complete or be cleaned up before stopping" },
              { label: "Completed work", value: "Previously completed batch items will be preserved" }
            ]
          });
        }
        renderPane(index);
        return;
      }
      const count = progress.total != null
        ? ` (${progress.current ?? 0} of ${progress.total})`
        : "";
      const nextMessage = `${progress.message}${count}`;
      if (
        pane.loadingMessage !== nextMessage
        || pane.progressCurrent !== progress.current
        || pane.progressTotal !== progress.total
      ) {
        pane.loadingMessage = nextMessage;
        pane.progressCurrent = progress.current;
        pane.progressTotal = progress.total;
        if (modal.open) {
          setModalProgress({
            title: message,
            message: progress.message,
            details: progress.total != null ? [
              { label: "Progress", value: `${Math.round(100 * Number(progress.current || 0) / Number(progress.total || 1))}% complete` }
            ] : []
          }, progress.current, progress.total);
        }
        renderPane(index);
      }
    } catch {
      // The first poll can arrive before the POST has registered the operation.
    }
  };
  const timer = setInterval(poll, 300);
  try {
    return await operation(operationId);
  } catch (error) {
    if (abortRequested) {
      const aborted = new Error("Operation aborted safely. Completed items were preserved.");
      aborted.data = error.data;
      throw aborted;
    }
    throw error;
  } finally {
    setModalAbort(null);
    polling = false;
    clearInterval(timer);
    if (panes[index] === pane) {
      pane.loading = false;
      pane.loadingMessage = "";
      pane.progressCurrent = null;
      pane.progressTotal = null;
      renderPane(index);
    }
  }
}

async function guardedPaneAction(index, action) {
  const pane = panes[index];
  if (!pane || pane.loading || pane.actionPending) return;
  pane.actionPending = true;
  renderPane(index);
  try {
    await action();
    if (modal.open) {
      await new Promise(resolve => {
        modal.addEventListener("close", resolve, { once: true });
      });
    }
  } finally {
    if (panes[index] === pane) {
      pane.actionPending = false;
      renderPane(index);
    }
  }
}

async function openHexEditor(index) {
  const pane = panes[index];
  const host = document.querySelector(`.pane[data-pane="${index}"]`);
  if (!pane?.image || !host || !window.AcornHexEditor) {
    return toast("The hex editor could not be opened.", true);
  }
  await window.AcornHexEditor.open({
    host,
    image: { ...pane.image },
    request: api,
    notify: toast,
    onSaved: updatedImage => {
      if (panes[index] === pane) {
        pane.image = updatedImage;
        rememberOpenPanes();
      }
    },
  });
  if (panes[index] === pane) await refreshCurrentView(index);
}

function paneFormat(image) {
  if (image.containerFormat === "hfe") return "HFE";
  if (image.kind === "mmb") return "MMB";
  if (image.kind === "tape") return "UEF";
  if (image.kind === "dfs") return image.name.toLowerCase().endsWith(".dsd") ? "DSD" : "SSD";
  return "ADFS";
}

function capacityMarkup(capacity) {
  if (!capacity?.available || !capacity.total) {
    const reason = capacity?.reason || "Free-space information is loading.";
    return `<span class="capacity unavailable" title="${esc(reason)}" aria-label="${esc(reason)}"><i></i></span>`;
  }
  const usedPercent = Math.max(0, Math.min(100, capacity.used * 100 / capacity.total));
  const level = usedPercent >= 90 ? "critical" : usedPercent >= 70 ? "warning" : "healthy";
  const details = capacity.unit === "slots"
    ? `${capacity.free} free slot${capacity.free === 1 ? "" : "s"} of ${capacity.total} · ${capacity.used} used · ${usedPercent.toFixed(1)}% full`
    : `${humanSize(capacity.free)} free of ${humanSize(capacity.total)} · ${humanSize(capacity.used)} used · ${usedPercent.toFixed(1)}% full`;
  return `<span class="capacity ${level}" role="progressbar" aria-label="${esc(details)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${usedPercent.toFixed(1)}" title="${esc(details)}" style="--capacity-used:${usedPercent}%"><i></i></span>`;
}

async function fetchCapacity(imageId, slot = null) {
  const query = new URLSearchParams();
  if (slot !== null) query.set("slot", slot);
  const encoded = query.toString();
  const suffix = encoded ? `?${encoded}` : "";
  try {
    return (await api(`/api/images/${imageId}/capacity${suffix}`)).capacity;
  } catch (_error) {
    return null;
  }
}

function fullPath(directory, name) {
  if (directory === "") return name;
  return directory === "$" ? `$.${name}` : `${directory}.${name}`;
}

function targetNameRule(pane, original) {
  const isDfs = pane.image?.kind === "dfs" || (pane.image?.kind === "mmb" && pane.slot !== null);
  const limit = isDfs ? 7 : 10;
  const label = isDfs ? "DFS" : "ADFS";
  const raw = String(original || "").split(/[/:]/).pop();
  let suggested = raw.normalize("NFKD").replace(/[^\x20-\x7e]/g, "").replace(/[.:*#/]/g, "_").slice(0, limit);
  if (!suggested) suggested = "FILE";
  const valid = raw.length > 0 && raw.length <= limit && !/[.:*#/\x00-\x1f]/.test(raw);
  return {
    valid,
    suggested,
    limit,
    label,
    adjusted: !valid || raw !== suggested,
    truncated: raw.length > limit
  };
}

function parentPath(path) {
  if (path === "") return "";
  if (path === "$") return "$";
  const parts = path.split(".");
  parts.pop();
  return parts.join(".") || "";
}

function crumbs(path, dfs = false) {
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
}

function selectionKeys(pane) {
  if (Array.isArray(pane.selection) && pane.selection.length) return pane.selection.map(String);
  return pane.selected == null ? [] : [String(pane.selected)];
}

function setSelection(pane, keys, anchor = null) {
  pane.selection = [...new Set(keys.map(String))];
  pane.selected = pane.selection.length === 1 ? pane.selection[0] : null;
  pane.selectionAnchor = anchor ?? pane.selection.at(-1) ?? null;
}

function selectedEntries(index) {
  const pane = panes[index];
  const keys = new Set(selectionKeys(pane));
  return pane.entries.filter(entry => keys.has(String(entry.slot ?? entry.name)));
}

function selectedEntry(index) {
  const entries = selectedEntries(index);
  return entries.length === 1 ? entries[0] : null;
}

function clipboardItemsForPane(index) {
  const pane = panes[index];
  if (!pane?.image) return [];
  const isSlots = pane.image.kind === "mmb" && pane.slot === null;
  if (isSlots) {
    return selectedEntries(index)
      .filter(entry => entry.type === "disk" && entry.formatted)
      .map(entry => ({
        pane: index,
        image: pane.image.id,
        slot: Number(entry.slot),
        name: entry.name,
      }));
  }
  return selectedEntries(index)
    .filter(entry => !entry.virtual && entry.type !== "disk")
    .map(entry => ({
      pane: index,
      image: pane.image.id,
      slot: pane.slot,
      side: pane.side,
      path: fullPath(pane.path, entry.name),
      name: entry.name,
      length: Number(entry.length || 0),
      recursive: entry.type === "dir" || entry.type === "directory",
    }));
}

function rowIsPendingCut(pane, entry) {
  if (!workspaceClipboard || workspaceClipboard.mode !== "cut") return false;
  if (pane.image.kind === "mmb" && pane.slot === null) {
    return workspaceClipboard.kind === "mmb-slots"
      && workspaceClipboard.items.some(item =>
        item.image === pane.image.id && Number(item.slot) === Number(entry.slot)
      );
  }
  const path = fullPath(pane.path, entry.name).toLowerCase();
  return workspaceClipboard.kind === "files"
    && workspaceClipboard.items.some(item =>
      item.image === pane.image.id
      && item.slot === pane.slot
      && item.side === pane.side
      && String(item.path).toLowerCase() === path
    );
}

function canPasteIntoPane(pane) {
  if (!workspaceClipboard || !pane?.image || pane.image.readOnly || pane.image.kind === "tape") return false;
  const isSlots = pane.image.kind === "mmb" && pane.slot === null;
  if (workspaceClipboard.kind === "mmb-slots") return isSlots || pane.image.kind === "adfs";
  if (isSlots) return true;
  return !(isDfsPane(pane) && pane.path === "");
}

function selectRow(index, key, { toggle = false, range = false } = {}) {
  const pane = panes[index];
  const rowKeys = pane.entries.map(entry => String(entry.slot ?? entry.name));
  const current = new Set(selectionKeys(pane));
  if (range && pane.selectionAnchor != null && rowKeys.includes(String(pane.selectionAnchor))) {
    const start = rowKeys.indexOf(String(pane.selectionAnchor));
    const end = rowKeys.indexOf(String(key));
    const keys = rowKeys.slice(Math.min(start, end), Math.max(start, end) + 1);
    setSelection(pane, toggle ? [...current, ...keys] : keys, pane.selectionAnchor);
    return;
  }
  if (toggle) {
    if (current.has(String(key))) current.delete(String(key)); else current.add(String(key));
    setSelection(pane, [...current], key);
    return;
  }
  setSelection(pane, [key], key);
}

function emptyMarkup() {
  return document.querySelector("#emptyPane").innerHTML;
}

function loadingMarkup(pane) {
  if (!pane.loading) return "";
  const determinate = pane.progressTotal > 0;
  const progress = determinate
    ? Math.min(100, Math.round(100 * (pane.progressCurrent || 0) / pane.progressTotal))
    : 0;
  return `<div class="loading" role="status" aria-live="polite">
    <span>${esc(pane.loadingMessage || "Reading disk…")}</span>
    <span class="progress${determinate ? " determinate" : ""}" ${determinate ? `style="--operation-progress:${progress}%"` : ""}><i></i></span>
  </div>`;
}

function renderPane(index, preserveScroll = false) {
  const pane = panes[index];
  const host = document.querySelector(`.pane[data-pane="${index}"]`);
  const previousScrollTop = preserveScroll ? (host.querySelector(".list-wrap")?.scrollTop || 0) : 0;
  if (!pane.image) {
    host.className = "pane";
    host.innerHTML = `${paneDragHandle(index)}${emptyMarkup()}${loadingMarkup(pane)}`;
    host.querySelector(".pane-open").onclick = () => chooseImage(index);
    host.querySelector(".pane-new").onclick = () => showCreateImageModal(index);
    host.querySelector(".pane-recover").onclick = () => recoverPreviousSession(index);
    host.querySelector(".close-empty-pane").onclick = () => closePane(index);
    if (pane.loading) {
      host.querySelectorAll("button").forEach(button => {
        button.disabled = true;
      });
    }
    wireDropZone(host, index);
    wirePaneDragHandle(host, index);
    rememberOpenPanes();
    return;
  }

  const selected = selectedEntry(index);
  const selectedKeys = new Set(selectionKeys(pane));
  const isSlots = pane.image.kind === "mmb" && pane.slot === null;
  const isTape = pane.image.kind === "tape";
  const isDfs = isDfsPane(pane);
  const isDfsRoot = isDfs && pane.path === "";
  const supportsFolders = pane.image.kind === "adfs" && !isSlots && !isTape;
  const canFolder = supportsFolders && !pane.image.readOnly;
  const canEdit = !isSlots && !isTape && !pane.image.readOnly;
  const canEditFiles = canEdit && !isDfsRoot;
  const isDsd = pane.image.doubleSided;
  const kind = pane.image.kind === "mmb" && pane.slot !== null ? "dfs" : pane.image.kind;
  const location = isSlots
    ? "MMB disk index"
    : isTape
      ? "Cassette tape"
      : pane.slot !== null
        ? `Slot ${pane.slot} · ${pane.slotName}${isDfsRoot ? " · DFS catalogues" : ` · ${pane.path}`}`
        : isDsd
          ? `DFS side ${pane.side === 2 ? 2 : 0}${isDfsRoot ? " · catalogues" : ` · ${pane.path}`}`
          : isDfs
            ? isDfsRoot ? "DFS catalogues" : `DFS catalogue ${pane.path}`
            : "Root filing system";
  const hasParentEntry = !isSlots && !isTape && (
    pane.slot !== null || (isDfs ? pane.path !== "" : pane.path !== "$")
  );
  const parentRow = hasParentEntry ? `<tr class="file-row parent-row" aria-label="Parent directory" tabindex="0" draggable="false" data-parent="1" data-key=".." data-name=".." data-type="dir" data-slot="" data-empty="0">
    <td class="file-name-cell"><div class="file-name-wrap"><span class="file-icon dir">↰</span><strong>..</strong></div></td>
    <td class="meta">Parent directory</td>
    <td class="meta">-</td>
    <td><span class="pill">-</span></td>
  </tr>` : "";
  const rows = pane.entries.map(entry => {
    const entryType = entry.type === "directory" ? "dir" : entry.type;
    const isDir = entryType === "dir";
    const isVirtual = Boolean(entry.virtual);
    const icon = entryType === "disk" ? "▣" : isDir ? "↳" : "F";
    const size = entryType === "disk" ? `#${entry.slot}` : isVirtual ? "Catalogue group" : isDir ? `${entry.length || 0} items` : humanSize(entry.length);
    const detail = entryType === "disk"
      ? entry.formatted ? (entry.writable ? "Read/write" : "Protected") : "Unformatted"
      : entry.filetype || (entry.load !== "" && entry.load != null ? `&${Number(entry.load).toString(16).toUpperCase()}` : "-");
    const attr = entryType === "disk"
      ? (entry.formatted ? (entry.writable ? "RW" : "RO") : "-")
      : entry.attr || "";
    const entryKey = String(entry.slot ?? entry.name);
    const rowActionable = !isVirtual && !pane.image.readOnly && !isTape && (isSlots ? entry.formatted : canEdit);
    const accessActionable = rowActionable;
    const multiSelection = selectedKeys.size > 1;
    const hideGroupAction = multiSelection && !selectedKeys.has(entryKey);
    const actionName = isSlots ? `disk ${entry.slot} · ${entry.name}` : entry.name;
    const rowActions = rowActionable ? `<span class="row-actions">
      <button class="row-action row-rename" type="button" draggable="false" title="Rename ${esc(actionName)}" aria-label="Rename ${esc(actionName)}" ${multiSelection ? "hidden" : ""}>✎</button>
      <button class="row-action delete row-delete" type="button" draggable="false" title="${isSlots ? "Eject" : "Delete"} ${esc(actionName)}" aria-label="${isSlots ? "Eject" : "Delete"} ${esc(actionName)}" ${hideGroupAction ? "hidden" : ""}>×</button>
    </span>` : "";
    const accessCell = `<td class="access-cell"><span class="pill">${esc(attr || detail)}</span>${accessActionable ? `<span class="access-actions" ${hideGroupAction ? "hidden" : ""}>
      <button class="row-action row-read-write" type="button" draggable="false" title="Mark ${esc(actionName)} read / write" aria-label="Mark ${esc(actionName)} read / write">◇</button>
      <button class="row-action row-read-only" type="button" draggable="false" title="Mark ${esc(actionName)} read-only" aria-label="Mark ${esc(actionName)} read-only">◆</button>
    </span>` : ""}</td>`;
    const cells = isSlots
      ? `<td class="meta slot-number">${entry.slot}</td>
      <td class="file-name-cell"><div class="file-name-wrap"><span class="file-icon ${entryType}">${icon}</span><strong>${esc(entry.name)}</strong>${rowActions}</div></td>
      <td class="meta">${esc(entry.formatted ? "DFS disk" : "Empty")}</td>
      ${accessCell}`
      : `<td class="file-name-cell"><div class="file-name-wrap"><span class="file-icon ${entryType}">${icon}</span><strong>${esc(entry.name)}</strong>
        ${rowActions}
      </div></td>
      <td class="meta">${esc(isVirtual ? "DFS catalogue" : isDir ? "Directory" : "File")}</td>
      <td class="meta">${esc(size)}</td>
      ${accessCell}`;
    return `<tr class="file-row${selectedKeys.has(entryKey) ? " selected" : ""}${entry.empty ? " empty-slot" : ""}${isVirtual ? " virtual-catalogue-row" : ""}${rowIsPendingCut(pane, entry) ? " clipboard-cut" : ""}"
      aria-selected="${selectedKeys.has(entryKey)}"
      tabindex="0" draggable="${!isVirtual && entry.formatted !== false}" data-key="${esc(entryKey)}" data-name="${esc(entry.name)}" data-type="${entryType}" data-slot="${entry.slot ?? ""}" data-empty="${entry.empty ? "1" : "0"}" data-virtual="${isVirtual ? "1" : "0"}">
      ${cells}
    </tr>`;
  }).join("");
  const selectedEmptySlot = Boolean(selected && selected.type === "disk" && selected.empty);
  const clipboardSelection = clipboardItemsForPane(index);
  const clipboardTools = `<details class="tool-menu edit-tools">
    <summary class="tool"><b>✎</b><span>Edit</span></summary>
    <div class="tool-menu-panel">
      <button class="menu-command clipboard-cut-action" ${clipboardSelection.length && !pane.image.readOnly && !isTape ? "" : "disabled"} title="Cut selected items"><b>✂</b><span>Cut <small>Ctrl/Cmd+X</small></span></button>
      <button class="menu-command clipboard-copy-action" ${clipboardSelection.length ? "" : "disabled"} title="Copy selected items"><b>⧉</b><span>Copy <small>Ctrl/Cmd+C</small></span></button>
      <button class="menu-command clipboard-paste-action" ${canPasteIntoPane(pane) ? "" : "disabled"} title="Paste once into this location"><b>▣</b><span>Paste <small>Ctrl/Cmd+V</small></span></button>
      ${pane.image.readOnly || isTape ? "" : `<span class="menu-separator" role="separator"></span>
        <button class="menu-command undo-image" ${pane.image.checkpoints?.canUndo ? "" : "disabled"}><b>↶</b><span>Undo last change</span></button>
        <button class="menu-command manage-checkpoints"><b>◉</b><span>Checkpoints…</span></button>`}
    </div>
  </details>`;
  const fileTools = `<details class="tool-menu file-tools${isSlots ? " add-disk-tools" : ""}">
    <summary class="tool"><b>▤</b><span>File</span></summary>
    <div class="tool-menu-panel">
      <button class="menu-command menu-new-image"><b>＋</b><span>New blank image…</span></button>
      <button class="menu-command menu-load-image"><b>▤</b><span>Open image…</span></button>
      <button class="menu-command menu-save-image"><b>⇩</b><span>Save image</span></button>
      ${isTape || pane.image.readOnly ? "" : `<span class="menu-separator" role="separator"></span>`}
      ${isSlots ? `<div class="open-disk-imports">${openDiskImportMarkup(index)}</div>
        <button class="menu-command insert-disk" ${selectedEmptySlot ? "" : "disabled"}><b>↥</b><span>Insert SSD / DSD / HFE / ZIP…</span></button>
        <button class="menu-command import-folder" ${pane.entries.some(entry => entry.empty) ? "" : "disabled"}><b>▣</b><span>Insert folder of disk images…</span></button>
        <button class="menu-command create-blank-ssd" ${selectedEmptySlot ? "" : "disabled"}><b>○</b><span>Create blank SSD here</span></button>
        <button class="menu-command create-blank-dsd" ${selectedEmptySlot ? "" : "disabled"}><b>◎</b><span>Create blank DSD here</span></button>`
        : !isTape && !pane.image.readOnly ? `<button class="menu-command import-file" ${canEditFiles ? "" : 'disabled title="Open $ or another DFS catalogue group before adding files."'}><b>＋</b><span>Add file…</span></button>
          <button class="menu-command import-folder" ${canEditFiles ? "" : 'disabled title="Open $ or another DFS catalogue group before adding files."'}><b>▣</b><span>Add folder…</span></button>
          ${isDfs
            ? `<button class="menu-command new-dfs-catalogue"><b>▢</b><span>New catalogue group…</span></button>`
            : `<button class="menu-command new-folder" ${canFolder ? "" : 'disabled title="This format cannot store directories."'}><b>▢</b><span>New folder…</span></button>`}` : ""}
      <span class="menu-separator" role="separator"></span>
      <button class="menu-command menu-close-pane"><b>×</b><span>Close pane</span></button>
    </div>
  </details>`;
  const viewTools = `<details class="tool-menu view-tools">
    <summary class="tool"><b>◫</b><span>View</span></summary>
    <div class="tool-menu-panel">
      <button class="menu-command view-refresh"><b>↻</b><span>Refresh current view</span></button>
      ${pane.slot !== null ? '<button class="menu-command view-all-disks"><b>▦</b><span>Return to all MMB disks</span></button>' : ""}
      ${isDsd ? `<button class="menu-command switch-side"><b>⇄</b><span>Switch to side ${pane.side === 2 ? "0" : "2"}</span></button>` : ""}
    </div>
  </details>`;
  const libraryTools = isTape || pane.image.readOnly ? "" : `<details class="tool-menu library-tools">
    <summary class="tool"><b>⌕</b><span>Library</span></summary>
    <div class="tool-menu-panel">
      <button class="menu-command online-library" ${!isSlots && isDfsRoot ? 'disabled title="Open a DFS catalogue group before installing files."' : ""}><b>⌕</b><span>${isSlots ? "Find disks online…" : "Find software online…"}</span></button>
    </div>
  </details>`;
  const menuTools = pane.image.kind === "mmb"
    ? `<details class="tool-menu">
        <summary class="tool"><b>☰</b><span>Menu</span></summary>
        <div class="tool-menu-panel">
          <button class="menu-command setup-menu"><b>▤</b><span>Create / manage menu</span></button>
          ${isSlots ? `<button class="menu-command menu-entry" ${selected?.formatted ? "" : "disabled"}><b>＋</b><span>Add selected disk</span></button>` : ""}
          <button class="menu-command preview-menu"><b>▣</b><span>Preview installed menu</span></button>
          <button class="menu-command audit-menu-pages"><b>✓</b><span>Audit launch PAGE values</span></button>
          <button class="menu-command backup-menu-slot"><b>⧉</b><span>Backup menu slot</span></button>
          <button class="menu-command restore-menu-slot"><b>↶</b><span>Restore menu backup</span></button>
        </div>
      </details>`
    : pane.image.kind === "adfs"
      ? `<details class="tool-menu">
          <summary class="tool"><b>☰</b><span>Menu</span></summary>
          <div class="tool-menu-panel">
            <button class="menu-command build-adfs-menu"><b>＋</b><span>Create / update menu here</span></button>
            <button class="menu-command preview-menu"><b>▣</b><span>Preview installed menu</span></button>
            <button class="menu-command audit-adfs-menu-pages"><b>✓</b><span>Audit launch PAGE values</span></button>
          </div>
        </details>`
      : "";
  const analysisTools = `<details class="tool-menu">
    <summary class="tool"><b>⌁</b><span>Analyse</span></summary>
    <div class="tool-menu-panel tool-menu-panel-right">
      <button class="menu-command health-dashboard"><b>♥</b><span>Image health dashboard</span></button>
      <button class="menu-command preflight-selection"><b>◫</b><span>Dry-run selected items</span></button>
      ${!isSlots && selected && selected.type !== "dir" && selected.type !== "directory" ? '<button class="menu-command inspect-file"><b>⌕</b><span>Inspect selected file</span></button><button class="menu-command inspect-dependencies"><b>⛓</b><span>Check loader dependencies</span></button>' : ""}
      ${["mmb", "adfs"].includes(pane.image.kind) ? `<button class="menu-command test-menu-entries" ${(
        pane.image.kind === "mmb"
          ? pane.menuDetected && !pane.menuDetectionPending
          : ["!BOOT", "GAMDATA", "GAMINDX", "PUBDATA", "PUBINDX", "UNIMENU"].every(name => pane.entries.some(entry => String(entry.name).toUpperCase() === name))
      ) ? "" : "disabled"}><b>▶</b><span>Test menu entries</span></button>` : ""}
      <button class="menu-command find-duplicates"><b>≡</b><span>${isSlots ? "Check for duplicate games" : "Find duplicates / variants"}</span></button>
      <button class="menu-command export-manifest"><b>⇩</b><span>Export collection manifest</span></button>
    </div>
  </details>`;
  const utilityTools = `<details class="tool-menu">
    <summary class="tool"><b>⋯</b><span>Tools</span></summary>
    <div class="tool-menu-panel tool-menu-panel-right">
      <button class="menu-command open-hex-editor"><b>0x</b><span>Hex editor…</span></button>
      ${isSlots ? "" : '<button class="menu-command validate-image"><b>✓</b><span>Check filesystem</span></button>'}
      ${isSlots || isTape ? (isTape ? '<button class="menu-command convert-tape"><b>⇥</b><span>Convert tape to disk</span></button>' : "") : pane.image.readOnly ? "" : '<button class="menu-command compact-image"><b>≋</b><span>Compact filesystem</span></button>'}
    </div>
  </details>`;
  const toolbarMarkup = `${fileTools}${clipboardTools}${viewTools}${libraryTools}
      ${pane.image.readOnly ? "" : menuTools}
      ${analysisTools}
      ${utilityTools}
      ${isSlots ? '<span class="toolbar-hint">Drag selected disks to cut and paste slots</span>' : ""}
      <span class="tool-spacer"></span>`;

  host.className = `pane${pane.image.dirty ? " dirty" : ""}`;
  host.innerHTML = `
    <header class="pane-head">
      ${paneDragHandle(index)}
      <span class="format-icon ${kind}">${paneFormat(pane.image)}</span>
      <div class="image-name"><strong class="image-title" role="button" tabindex="0" title="Click to rename ${esc(pane.image.name)}">${esc(pane.image.name)}</strong><small>${esc(location)} · ${humanSize(pane.image.size)}</small></div>
      <span class="dirty-dot" role="img" aria-label="Changes made" title="Changes made · save before closing"></span>
      <div class="pane-head-actions" aria-label="Image actions">
        <button class="icon-button new-image" title="New Blank Image" aria-label="New Blank Image">${PANE_ICONS.newImage}</button>
        <button class="icon-button replace-image" title="Load New Image" aria-label="Load New Image">${PANE_ICONS.loadImage}</button>
        <button class="icon-button save-image" title="Save Image" aria-label="Save Image">${PANE_ICONS.saveImage}</button>
        <button class="icon-button refresh-image" title="Refresh View" aria-label="Refresh View">${PANE_ICONS.refreshView}</button>
        <button class="icon-button close-image" title="Close Pane" aria-label="Close Pane">${PANE_ICONS.closePane}</button>
      </div>
    </header>
    <nav class="toolbar" aria-label="Pane menus">
      ${toolbarMarkup}
    </nav>
    <div class="breadcrumbs">${isSlots ? '<span class="crumb current">All disks</span>' : pane.slot !== null ? `<button class="crumb mmb-home">All disks</button><span>›</span>${crumbs(pane.path, isDfs)}` : crumbs(pane.path, isDfs)}</div>
    <div class="list-wrap">
      ${loadingMarkup(pane)}
      ${(parentRow || rows) ? `<table class="file-list${isSlots ? " mmb-slot-list" : ""}" role="grid" aria-label="${isSlots ? "MMB disk slots" : "Files in " + esc(location)}"><thead><tr>${isSlots ? "<th>Slot</th><th>Name</th><th>Kind</th><th>Access</th>" : "<th>Name</th><th>Kind</th><th>Size</th><th>Access</th>"}</tr></thead><tbody>${parentRow}${rows}</tbody></table>` : '<div class="empty-list">Nothing here yet.<br>Drop a host file into this pane to add it.</div>'}
    </div>
    <footer class="pane-foot"><span>${pane.image.readOnly ? "Read-only safe view · " : ""}${selectedKeys.size ? `${selectedKeys.size} selected · ` : ""}${pane.entries.length} ${isSlots ? "formatted or named slots" : "objects"} · ${esc(pane.description || "")}</span>${capacityMarkup(pane.capacity)}</footer>`;

  if (pane.loading || pane.actionPending) {
    host.querySelectorAll("button").forEach(button => {
      button.disabled = true;
    });
  }
  host.querySelector(".replace-image").onclick = () => chooseImage(index);
  host.querySelector(".new-image").onclick = () => guardedPaneAction(index, () => showCreateImageModal(index));
  const imageTitle = host.querySelector(".image-title");
  imageTitle.onclick = () => beginImageRename(index);
  imageTitle.onkeydown = event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      beginImageRename(index);
    }
  };
  host.querySelector(".refresh-image").onclick = () => refreshCurrentView(index);
  host.querySelector(".menu-new-image")?.addEventListener("click", () => guardedPaneAction(index, () => showCreateImageModal(index)));
  host.querySelector(".menu-load-image")?.addEventListener("click", () => chooseImage(index));
  host.querySelector(".menu-save-image")?.addEventListener("click", () => guardedPaneAction(index, () => saveImage(index)));
  host.querySelector(".menu-close-pane")?.addEventListener("click", () => closePane(index));
  host.querySelector(".view-refresh")?.addEventListener("click", () => refreshCurrentView(index));
  host.querySelector(".view-all-disks")?.addEventListener("click", () => returnToMmb(index));
  host.querySelector(".clipboard-cut-action")?.addEventListener("click", () => setWorkspaceClipboard(index, "cut"));
  host.querySelector(".clipboard-copy-action")?.addEventListener("click", () => setWorkspaceClipboard(index, "copy"));
  host.querySelector(".clipboard-paste-action")?.addEventListener("click", () => pasteWorkspaceClipboard(index));
  host.querySelector(".close-image").onclick = () => closePane(index);
  host.querySelector(".mmb-home")?.addEventListener("click", () => returnToMmb(index));
  host.querySelector(".import-file")?.addEventListener("click", () => guardedPaneAction(index, () => chooseHostFile(index)));
  host.querySelector(".import-folder")?.addEventListener("click", () => guardedPaneAction(index, () => chooseHostFolder(index)));
  host.querySelector(".new-folder")?.addEventListener("click", () => guardedPaneAction(index, () => createFolder(index)));
  host.querySelector(".new-dfs-catalogue")?.addEventListener("click", () => guardedPaneAction(index, () => createDfsCatalogue(index)));
  host.querySelector(".switch-side")?.addEventListener("click", () => switchDsdSide(index));
  host.querySelector(".insert-disk")?.addEventListener("click", () => guardedPaneAction(index, () => chooseSlotImage(index)));
  host.querySelector(".online-library")?.addEventListener("click", () => guardedPaneAction(index, () => showOnlineLibrary(index)));
  host.querySelector(".create-blank-ssd")?.addEventListener("click", () => guardedPaneAction(index, () => createBlankMmbDisk(index, "ssd")));
  host.querySelector(".create-blank-dsd")?.addEventListener("click", () => guardedPaneAction(index, () => createBlankMmbDisk(index, "dsd")));
  host.querySelector(".menu-entry")?.addEventListener("click", () => guardedPaneAction(index, () => scanMenuEntry(index)));
  host.querySelector(".setup-menu")?.addEventListener("click", () => guardedPaneAction(index, () => setupMmbMenu(index)));
  host.querySelector(".validate-image")?.addEventListener("click", () => guardedPaneAction(index, () => validateImage(index)));
  host.querySelector(".open-hex-editor")?.addEventListener("click", () => guardedPaneAction(index, () => openHexEditor(index)));
  host.querySelector(".convert-tape")?.addEventListener("click", () => guardedPaneAction(index, () => convertTape(index)));
  host.querySelector(".preview-menu")?.addEventListener("click", () => guardedPaneAction(index, () => showMenuPreview(index)));
  host.querySelector(".audit-menu-pages")?.addEventListener("click", () => guardedPaneAction(index, () => auditMmbMenuPages(index)));
  host.querySelector(".backup-menu-slot")?.addEventListener("click", () => guardedPaneAction(index, () => backupMmbMenuSlot(index)));
  host.querySelector(".restore-menu-slot")?.addEventListener("click", () => guardedPaneAction(index, () => restoreMmbMenuSlot(index)));
  host.querySelector(".audit-adfs-menu-pages")?.addEventListener("click", () => guardedPaneAction(index, () => auditAdfsMenuPages(index)));
  host.querySelector(".build-adfs-menu")?.addEventListener("click", () => guardedPaneAction(index, () => buildAdfsMenu(index)));
  host.querySelector(".compact-image")?.addEventListener("click", () => guardedPaneAction(index, () => compactImage(index)));
  host.querySelector(".undo-image")?.addEventListener("click", () => guardedPaneAction(index, () => undoLastChange(index)));
  host.querySelector(".manage-checkpoints")?.addEventListener("click", () => guardedPaneAction(index, () => showCheckpointManager(index)));
  host.querySelector(".health-dashboard")?.addEventListener("click", () => guardedPaneAction(index, () => showHealthDashboard(index)));
  host.querySelector(".preflight-selection")?.addEventListener("click", () => guardedPaneAction(index, () => showSelectionPreflight(index)));
  host.querySelector(".inspect-file")?.addEventListener("click", () => guardedPaneAction(index, () => showFileInspector(index)));
  host.querySelector(".inspect-dependencies")?.addEventListener("click", () => guardedPaneAction(index, () => showDependencyReport(index)));
  host.querySelector(".test-menu-entries")?.addEventListener("click", () => guardedPaneAction(index, () => showMenuTests(index)));
  host.querySelector(".find-duplicates")?.addEventListener("click", () => guardedPaneAction(index, () => (
    pane.image.kind === "mmb" && pane.slot === null
      ? showMmbDuplicateCheck(index)
      : showDuplicateReport(index)
  )));
  host.querySelector(".export-manifest")?.addEventListener("click", () => showManifestExport(index));
  host.querySelector(".save-image").onclick = () => guardedPaneAction(index, () => saveImage(index));
  host.querySelectorAll(".tool-menu").forEach(menu => {
    menu.addEventListener("toggle", () => {
      if (!menu.open) return;
      if (menu.classList.contains("add-disk-tools")) refreshOpenDiskImportMenu(index, menu);
      host.querySelectorAll(".tool-menu[open]").forEach(other => {
        if (other !== menu) other.removeAttribute("open");
      });
    });
    menu.querySelectorAll(".menu-command").forEach(command => {
      command.addEventListener("click", () => menu.removeAttribute("open"));
    });
  });
  host.querySelectorAll(".crumb[data-path]").forEach(button => button.onclick = () => navigate(index, button.dataset.path));
  host.querySelectorAll(".file-row").forEach(row => wireRow(row, index));
  if ((pane.image.kind === "dfs") || (pane.image.kind === "mmb" && pane.slot !== null)) {
    const header = host.querySelector(".pane-head");
    header.draggable = true;
    header.ondragstart = event => {
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData("application/x-beeb-disk", JSON.stringify({
        image: pane.image.id, slot: pane.slot, name: pane.slotName || pane.image.name
      }));
    };
  }
  wireDropZone(host, index);
  wirePaneDragHandle(host, index);
  const listWrap = host.querySelector(".list-wrap");
  if (preserveScroll) listWrap.scrollTop = previousScrollTop;
  if (isSlots) {
    if (!preserveScroll && pane.mmbScrollTop) listWrap.scrollTop = pane.mmbScrollTop;
    listWrap.addEventListener("scroll", () => {
      pane.mmbScrollTop = listWrap.scrollTop;
    }, { passive: true });
  }
  rememberOpenPanes();
}

function wireRow(row, index) {
  if (row.dataset.parent === "1") {
    row.ondblclick = event => {
      event.stopPropagation();
      openEntry(index, row);
    };
    row.onkeydown = event => {
      if (event.key === "Enter") openEntry(index, row);
    };
    return;
  }
  if (row.dataset.virtual === "1") {
    row.ondblclick = event => {
      event.stopPropagation();
      openEntry(index, row);
    };
    row.onkeydown = event => {
      if (event.key === "Enter") openEntry(index, row);
    };
    row.ondragover = event => {
      const hasInternalFiles = event.dataTransfer.types.includes("application/x-acorn-files");
      if (!hasInternalFiles && !event.dataTransfer.types.includes("Files")) return;
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("folder-drop-target");
    };
    row.ondragleave = () => row.classList.remove("folder-drop-target");
    row.ondrop = async event => {
      event.preventDefault();
      event.stopPropagation();
      row.classList.remove("folder-drop-target");
      const destination = row.dataset.name;
      const encoded = event.dataTransfer.getData("application/x-acorn-files");
      if (encoded) return transferFiles(index, JSON.parse(encoded), destination);
      const dropped = await collectDroppedHostFiles(event.dataTransfer);
      const files = dropped.map(item => item.file);
      if (!files.length) return;
      await navigate(index, destination);
      if (dropped.some(item => item.relativePath.includes("/"))) await addSelectedHostFolder(index, dropped);
      else await addSelectedHostFiles(index, files);
    };
    return;
  }
  const selectForAction = preserveSelectedGroup => {
    const pane = panes[index];
    if (
      preserveSelectedGroup
      && selectionKeys(pane).length > 1
      && selectionKeys(pane).includes(row.dataset.key)
    ) return;
    setSelection(panes[index], [row.dataset.key], row.dataset.key);
    refreshSelectionDisplay(index);
  };
  row.querySelector(".row-rename")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(false);
    guardedPaneAction(index, () => renameSelected(index));
  });
  row.querySelector(".row-delete")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(true);
    guardedPaneAction(index, () => deleteSelected(index));
  });
  row.querySelector(".row-read-write")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(true);
    guardedPaneAction(index, () => setSelectedAccess(index, true));
  });
  row.querySelector(".row-read-only")?.addEventListener("click", event => {
    event.preventDefault();
    event.stopPropagation();
    selectForAction(true);
    guardedPaneAction(index, () => setSelectedAccess(index, false));
  });
  row.onclick = event => {
    event.stopPropagation();
    if (event.detail !== 1) return;
    const toggle = event.ctrlKey || event.metaKey;
    const range = event.shiftKey;
    selectRow(index, row.dataset.key, { toggle, range });
    refreshSelectionDisplay(index);
  };
  row.ondblclick = event => {
    event.stopPropagation();
    openEntry(index, row);
  };
  row.onkeydown = event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      const keys = panes[index].entries
        .filter(entry => entry.type !== "disk" || entry.formatted)
        .map(entry => String(entry.slot ?? entry.name));
      setSelection(panes[index], keys, row.dataset.key);
      refreshSelectionDisplay(index);
      return;
    }
    if (event.key === "Enter") openEntry(index, row);
    if (event.key === "Delete") deleteSelected(index);
  };
  row.ondragstart = event => {
    const pane = panes[index];
    if (row.dataset.type === "disk") {
      if (row.dataset.empty === "1") return event.preventDefault();
      if (!selectionKeys(pane).includes(row.dataset.key)) {
        setSelection(pane, [row.dataset.key], row.dataset.key);
      }
      const slots = selectedEntries(index)
        .filter(entry => entry.type === "disk" && entry.formatted)
        .map(entry => ({
          pane: index,
          image: pane.image.id,
          slot: Number(entry.slot),
          name: entry.name
        }));
      event.dataTransfer.effectAllowed = "copyMove";
      event.dataTransfer.setData("application/x-acorn-mmb-slots", JSON.stringify(slots));
      event.dataTransfer.setData("application/x-beeb-mmb-slot", JSON.stringify(slots[0]));
      event.dataTransfer.setData("text/plain", slots.length === 1 ? slots[0].name : `${slots.length} MMB disks`);
      document.querySelectorAll(`.pane[data-pane="${index}"] .file-row.selected`).forEach(item => {
        if (item.dataset.empty !== "1") item.classList.add("dragging");
      });
      return;
    }
    if (!selectionKeys(pane).includes(row.dataset.key)) {
      setSelection(pane, [row.dataset.key], row.dataset.key);
      document.querySelectorAll(`.pane[data-pane="${index}"] .file-row`).forEach(item => {
        const selected = item === row;
        item.classList.toggle("selected", selected);
        item.setAttribute("aria-selected", String(selected));
      });
    }
    const sources = selectedEntries(index)
      .filter(entry => entry.type !== "disk")
      .map(entry => ({
        pane: index,
        image: pane.image.id,
        slot: pane.slot,
        side: pane.side,
        path: fullPath(pane.path, entry.name),
        name: entry.name,
        recursive: entry.type === "dir" || entry.type === "directory"
      }));
    document.querySelectorAll(`.pane[data-pane="${index}"] .file-row.selected`).forEach(item => {
      item.classList.add("dragging");
    });
    event.dataTransfer.effectAllowed = "copyMove";
    event.dataTransfer.setData("application/x-acorn-files", JSON.stringify(sources));
    event.dataTransfer.setData("application/x-beeb-file", JSON.stringify(sources[0]));
    event.dataTransfer.setData("text/plain", sources.length === 1 ? sources[0].name : `${sources.length} Acorn files`);
  };
  if (panes[index].image.kind === "mmb" && panes[index].slot === null) {
    row.ondragover = event => {
      const slotDrag = event.dataTransfer.types.includes("application/x-beeb-mmb-slot")
        || event.dataTransfer.types.includes("application/x-acorn-mmb-slots");
      if (row.dataset.empty !== "1" && !slotDrag) return;
      event.preventDefault();
      event.stopPropagation();
    };
    row.ondrop = async event => {
      event.preventDefault();
      event.stopPropagation();
      const slotBatch = event.dataTransfer.getData("application/x-acorn-mmb-slots");
      if (slotBatch) {
        const sources = JSON.parse(slotBatch);
        if (sources.length && sources.every(source => source.image === panes[index].image.id)) {
          return moveMmbSlotsByDrag(index, Number(row.dataset.slot), sources);
        }
        if (sources.length > 1) {
          if (row.dataset.empty !== "1") return toast("Drop multiple disks onto an empty destination slot.", true);
          return transferMmbSlots(index, Number(row.dataset.slot), sources);
        }
      }
      const slotData = event.dataTransfer.getData("application/x-beeb-mmb-slot");
      if (slotData) {
        const source = JSON.parse(slotData);
        if (row.dataset.empty === "1") {
          return insertSessionIntoSlot(index, Number(row.dataset.slot), { image: source.image, slot: source.slot });
        }
        return toast("Copy an MMB disk into an empty destination slot.", true);
      }
      if (row.dataset.empty !== "1") return;
      const disk = event.dataTransfer.getData("application/x-beeb-disk");
      if (disk) return insertSessionIntoSlot(index, Number(row.dataset.slot), JSON.parse(disk));
      const dropped = await collectDroppedHostFiles(event.dataTransfer);
      if (dropped.some(item => item.relativePath.includes("/"))) {
        return addSelectedHostFolder(index, dropped, Number(row.dataset.slot));
      }
      const files = dropped.map(item => item.file).filter(item => formats.isDfsImage(item.name));
      if (files.length) return insertFilesIntoSlots(index, Number(row.dataset.slot), files);
      toast("Drop an SSD, DSD, DFS-formatted HFE, or ZIP into an empty slot.", true);
    };
  } else if (
    panes[index].image.kind === "adfs"
    && row.dataset.type === "dir"
  ) {
    row.ondragover = event => {
      if (!event.dataTransfer.types.includes("application/x-acorn-files")) return;
      event.preventDefault();
      event.stopPropagation();
      row.classList.add("folder-drop-target");
    };
    row.ondragleave = event => {
      if (!row.contains(event.relatedTarget)) {
        row.classList.remove("folder-drop-target");
      }
    };
    row.ondrop = event => {
      const encoded = event.dataTransfer.getData("application/x-acorn-files");
      if (!encoded) return;
      event.preventDefault();
      event.stopPropagation();
      row.classList.remove("folder-drop-target");
      transferFiles(
        index,
        JSON.parse(encoded),
        fullPath(panes[index].path, row.dataset.name),
      );
    };
  }
  row.ondragend = () => {
    document.querySelectorAll(`.pane[data-pane="${index}"] .file-row.dragging`).forEach(item => {
      item.classList.remove("dragging");
    });
  };
}

function refreshSelectionDisplay(index) {
  const pane = panes[index];
  const host = document.querySelector(`.pane[data-pane="${index}"]`);
  const selectedKeys = new Set(selectionKeys(pane));
  const selected = selectedEntry(index);
  const isSlots = pane.image?.kind === "mmb" && pane.slot === null;

  host.querySelectorAll(".file-row").forEach(row => {
    const isSelected = selectedKeys.has(row.dataset.key);
    row.classList.toggle("selected", isSelected);
    row.setAttribute("aria-selected", String(isSelected));
    const multiSelection = selectedKeys.size > 1;
    const rename = row.querySelector(".row-rename");
    const remove = row.querySelector(".row-delete");
    const accessActions = row.querySelector(".access-actions");
    if (rename) rename.hidden = multiSelection;
    if (remove) remove.hidden = multiSelection && !isSelected;
    if (accessActions) accessActions.hidden = multiSelection && !isSelected;
  });
  const disable = (selector, disabled) => {
    const control = host.querySelector(selector);
    if (control) control.disabled = disabled;
  };
  disable(".insert-disk", !selected?.empty);
  disable(".create-blank-ssd", !selected?.empty);
  disable(".create-blank-dsd", !selected?.empty);
  disable(".menu-entry", !selected?.formatted);
  const clipboardSelection = clipboardItemsForPane(index);
  disable(".clipboard-cut-action", !clipboardSelection.length || pane.image.readOnly || pane.image.kind === "tape");
  disable(".clipboard-copy-action", !clipboardSelection.length);
  disable(".clipboard-paste-action", !canPasteIntoPane(pane));

  const footer = host.querySelector(".pane-foot > span:first-child");
  if (footer) {
    footer.textContent =
      `${selectedKeys.size ? `${selectedKeys.size} selected · ` : ""}`
      + `${pane.entries.length} ${isSlots ? "formatted or named slots" : "objects"}`
      + ` · ${pane.description || ""}`;
  }
}

async function moveMmbSlotsByDrag(index, targetSlot, sources) {
  const pane = panes[index];
  const clipboard = {
    mode: "cut",
    kind: "mmb-slots",
    items: sources,
    sourceImage: pane.image.id,
    sourceName: pane.image.name,
    createdAt: Date.now(),
  };
  try {
    return await pasteMmbSlots(index, clipboard, targetSlot);
  } catch (error) {
    toast(error.message, true);
    return false;
  }
}

async function transferMmbSlots(index, startSlot, sources) {
  const pane = panes[index];
  const destinationSlots = pane.entries
    .filter(entry => entry.slot >= startSlot && entry.empty)
    .slice(0, sources.length)
    .map(entry => entry.slot);
  if (destinationSlots.length < sources.length) {
    return toast(`There are not ${sources.length} empty slots available from slot ${startSlot}.`, true);
  }
  const movingWithinImage = sources.every(source => source.image === pane.image.id);
  const metadataItems = [];
  setLoading(index, true, `${movingWithinImage ? "Moving" : "Copying"} 1 of ${sources.length} MMB disks…`);
  try {
    for (const [offset, source] of sources.entries()) {
      pane.loadingMessage = `${movingWithinImage ? "Moving" : "Copying"} ${offset + 1} of ${sources.length}: ${source.name}…`;
      pane.progressCurrent = offset;
      pane.progressTotal = sources.length;
      renderPane(index);
      const data = movingWithinImage
        ? await api(`/api/images/${pane.image.id}/slots/move`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sourceSlot: source.slot, targetSlot: destinationSlots[offset] })
        })
        : await api(`/api/images/${pane.image.id}/slots/insert-from-image`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            targetSlot: destinationSlots[offset],
            sourceImage: source.image,
            sourceSlot: source.slot
          })
        });
      pane.image = data.image;
      if (data.metadata) metadataItems.push(data.metadata);
      (data.warnings || []).forEach(message => toast(message, true));
    }
    pane.progressCurrent = null;
    pane.progressTotal = null;
    await acceptImage(index, pane.image);
    setSelection(panes[index], destinationSlots.map(String), String(destinationSlots[0]));
    renderPane(index);
    document.querySelector(`.pane[data-pane="${index}"] .file-row.selected`)?.scrollIntoView({ block: "center" });
    toast(`${sources.length} MMB disks ${movingWithinImage ? "moved" : "copied"}`);
    if (metadataItems.length) queueMenuReviews(index, metadataItems);
  } catch (error) {
    pane.loading = false;
    pane.progressCurrent = null;
    pane.progressTotal = null;
    renderPane(index);
    toast(error.message, true);
  }
}

function wireDropZone(host, index) {
  host.ondragover = event => {
    if (event.dataTransfer.types.includes("application/x-acorn-pane")) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      host.classList.add("pane-swap-target");
      return;
    }
    event.preventDefault();
    host.classList.add("drag-target");
    event.dataTransfer.dropEffect = "copy";
  };
  host.ondragleave = event => {
    if (!host.contains(event.relatedTarget)) host.classList.remove("drag-target", "pane-swap-target");
  };
  host.ondrop = async event => {
    event.preventDefault();
    host.classList.remove("drag-target", "pane-swap-target");
    const paneSource = event.dataTransfer.getData("application/x-acorn-pane");
    if (paneSource !== "") {
      event.stopPropagation();
      return swapPanes(Number(paneSource), index);
    }
    if (panes[index].loading || panes[index].actionPending) {
      return toast("Wait for the current operation to finish.", true);
    }
    const mmbSlot = event.dataTransfer.getData("application/x-beeb-mmb-slot");
    const mmbSlots = event.dataTransfer.getData("application/x-acorn-mmb-slots");
    const openDisk = event.dataTransfer.getData("application/x-beeb-disk");
    const diskSources = mmbSlots ? JSON.parse(mmbSlots) : [];
    const diskSource = diskSources[0] || (mmbSlot ? JSON.parse(mmbSlot) : (openDisk ? JSON.parse(openDisk) : null));
    if (diskSource && panes[index].image?.kind === "adfs") {
      if (diskSource.image === panes[index].image.id) {
        return toast("Choose a different ADFS image as the destination.", true);
      }
      return diskSources.length > 1
        ? copyMmbSlotsToAdfs(index, diskSources)
        : diskSource.slot != null
        ? copyMmbSlotToAdfs(index, diskSource)
        : copyDiskImageToAdfs(index, diskSource);
    }
    const internalBatch = event.dataTransfer.getData("application/x-acorn-files");
    if ((internalBatch || event.dataTransfer.getData("application/x-beeb-file"))
      && isDfsPane(panes[index]) && panes[index].path === "") {
      return toast("Drop files onto $, A-Z, or open a DFS catalogue group first.", true);
    }
    if (internalBatch) return transferFiles(index, JSON.parse(internalBatch));
    const internal = event.dataTransfer.getData("application/x-beeb-file");
    if (internal) return transferFiles(index, [JSON.parse(internal)]);
    const dropped = await collectDroppedHostFiles(event.dataTransfer);
    const files = dropped.map(item => item.file);
    if (!files.length) return;
    if (dropped.some(item => item.relativePath.includes("/")) && panes[index].image) {
      return addSelectedHostFolder(index, dropped);
    }
    const images = files.filter(file => formats.isImportableImage(file.name) || formats.isDescriptor(file.name));
    if (!panes[index].image) return openFiles(index, files);
    if (images.length && panes[index].image.kind === "adfs") {
      for (const file of files.filter(item => !formats.isDescriptor(item.name))) {
        await importHostFile(index, file);
      }
      return;
    }
    if (images.length) return openFiles(index, files);
    if (isDfsPane(panes[index]) && panes[index].path === "") {
      return toast("Drop files onto $, A-Z, or open a DFS catalogue group first.", true);
    }
    for (const file of files) await importHostFile(index, file);
  };
}

function copyMmbSlotToAdfs(index, source, afterCopy = null) {
  const target = panes[index];
  if (target.image.name.toLowerCase().endsWith(".dat") && !target.image.hasDescriptor) {
    return toast("Reopen this BeebSCSI DAT with its matching DSC file before copying disks into it.", true);
  }
  const rule = targetNameRule(target, source.name || `DISK${source.slot}`);
  return new Promise(resolve => {
    let submitted = false;
    const closed = showModal(`
    <h2>Copy MMB disk to ADFS</h2>
    <p>${rule.valid ? "A child directory will be created and the complete DFS catalogue copied into it." : `“${esc(source.name)}” is not a legal ADFS directory name, so a safe replacement has been suggested.`}</p>
    <div class="field"><label>Directory name · max ${rule.limit} characters</label>
      <input name="directoryName" maxlength="${rule.limit}" value="${esc(rule.suggested)}" required></div>
    <label class="check-field"><input type="checkbox" name="addMenu" value="yes"> Offer this directory as an ADFS menu entry</label>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="copy">Copy disk contents</button></div>`,
    async form => {
      submitted = true;
      await performMmbSlotToAdfsCopy(
        index,
        source,
        form.get("directoryName"),
        form.get("addMenu") === "yes"
      );
      if (afterCopy) await afterCopy([source]);
      resolve(true);
      return true;
    });
    closed.then(() => { if (!submitted) resolve(false); });
  });
}

function copyMmbSlotsToAdfs(index, sources, afterCopy = null) {
  const target = panes[index];
  const savedRecipes = storedCollection(RECIPE_STORAGE_KEY, []);
  const initialRecipe = savedRecipes[0] || { naming: "source", groupPrefix: "DISCS", addMenu: false, online: true, compatibility: true };
  let chosenRecipe = initialRecipe;
  if (target.image.name.toLowerCase().endsWith(".dat") && !target.image.hasDescriptor) {
    return toast("Reopen this BeebSCSI DAT with its matching DSC file before copying disks into it.", true);
  }
  const adfsDirectoryLimit = 47;
  const availableEntries = Math.max(0, adfsDirectoryLimit - target.entries.length);
  const grouped = sources.length > availableEntries;
  const groupCount = grouped ? Math.ceil(sources.length / adfsDirectoryLimit) : 0;
  if (groupCount > availableEntries) {
    return toast(
      `This ADFS directory has ${availableEntries} free entries, but ${groupCount} group directories are needed. Choose an emptier destination directory.`,
      true
    );
  }
  const usedNames = new Set(target.entries.map(entry => String(entry.name).toLowerCase()));
  const groupNames = [];
  for (let offset = 1; offset <= groupCount; offset += 1) {
    let suffix = offset;
    let candidate;
    do {
      candidate = `${initialRecipe.groupPrefix || "DISCS"}${suffix}`.slice(0, 10);
      suffix += groupCount;
    } while (usedNames.has(candidate.toLowerCase()));
    usedNames.add(candidate.toLowerCase());
    groupNames.push(candidate);
  }
  const items = sources.map((source, offset) => ({
    source,
    offset,
    group: grouped ? Math.floor(offset / adfsDirectoryLimit) : null,
    rule: targetNameRule(target, source.name || `DISK${source.slot}`)
  }));
  const proposedByLocation = new Map();
  const collisionOffsets = new Set();
  for (const item of items) {
    const location = item.group == null ? "root" : `group:${item.group}`;
    const key = `${location}:${item.rule.suggested.toLowerCase()}`;
    const previous = proposedByLocation.get(key);
    if (previous) {
      collisionOffsets.add(previous.offset);
      collisionOffsets.add(item.offset);
    } else {
      proposedByLocation.set(key, item);
    }
    if (
      item.group == null
      && item.rule.adjusted
      && usedNames.has(item.rule.suggested.toLowerCase())
    ) {
      collisionOffsets.add(item.offset);
    }
  }
  const hasNameCollisions = collisionOffsets.size > 0;
  const initialNamingStrategy = hasNameCollisions || initialRecipe.naming === "generic" ? "generic" : "review";
  const genericNames = new Map();
  const genericUsedByLocation = new Map();
  let genericNumber = 0;
  for (const item of items) {
    const location = item.group == null ? "root" : `group:${item.group}`;
    if (!genericUsedByLocation.has(location)) {
      genericUsedByLocation.set(
        location,
        item.group == null ? new Set(usedNames) : new Set()
      );
    }
    const used = genericUsedByLocation.get(location);
    let candidate;
    do {
      candidate = `DISC-${String(genericNumber).padStart(4, "0")}`;
      genericNumber += 1;
    } while (used.has(candidate.toLowerCase()));
    used.add(candidate.toLowerCase());
    genericNames.set(item.offset, candidate);
  }
  const completedItems = new Set();
  const skippedItems = new Map();
  const replaceItems = new Set();
  const collectedMetadata = [];
  let submitted = false;
  const closed = showModal(`
    <div class="bulk-copy-planner">
      <header class="bulk-planner-heading">
        <div><small>MMB → ADFS BULK IMPORT</small><h2>Review the copy plan</h2></div>
        <div class="bulk-summary">
          <span><b>${items.length}</b> disks</span>
          <span><b>${grouped ? groupCount : 0}</b> parent groups</span>
          <span title="${esc(target.path)}"><b>${esc(target.path)}</b> destination</span>
        </div>
      </header>
      ${hasNameCollisions ? `<div class="bulk-alert">
        <b>${collisionOffsets.size} shortened names clash.</b>
        Generic unique names have been selected. Choose “Use disk titles” to review the highlighted rows manually.
      </div>` : ""}
      <div class="bulk-planner-body">
        <aside class="bulk-planner-options">
          ${savedRecipes.length ? `<section><small>IMPORT RECIPE</small><select name="importRecipe"><option value="">Custom choices</option>${savedRecipes.map((recipe, index) => `<option value="${index}" ${index === 0 ? "selected" : ""}>${esc(recipe.name)}</option>`).join("")}</select></section>` : ""}
          <section>
            <small>1 · DIRECTORY NAMES</small>
            <label class="bulk-choice">
              <input type="radio" name="namingStrategy" value="generic" ${initialNamingStrategy === "generic" ? "checked" : ""}>
              <span><b>Use generic unique names</b><em>DISC-0000, DISC-0001…</em></span>
            </label>
            <label class="bulk-choice">
              <input type="radio" name="namingStrategy" value="review" ${initialNamingStrategy === "review" ? "checked" : ""}>
              <span><b>Use disk titles</b><em>Shorten titles to ADFS limits</em></span>
            </label>
            <p>Original MMB titles and menu metadata are retained whichever directory style you choose.</p>
          </section>
          ${grouped ? `<section>
            <small>2 · PARENT GROUPS</small>
            <p>Old ADFS directories hold ${adfsDirectoryLimit} entries. Rename these containers if required.</p>
            <div class="bulk-group-fields">
              ${groupNames.map((name, offset) => `<label>
                <span>Group ${offset + 1}</span>
                <input name="groupName${offset}" maxlength="10" value="${esc(name)}" required>
              </label>`).join("")}
            </div>
          </section>` : ""}
          <section>
            <small>${grouped ? "3" : "2"} · MENU</small>
            <label class="bulk-menu-choice">
              <input type="checkbox" name="addMenu" value="yes" ${initialRecipe.addMenu ? "checked" : ""}>
              <span><b>Add copied titles to the ADFS menu</b><em>Known MMB menu records are reused first.</em></span>
            </label>
          </section>
        </aside>
        <section class="bulk-disk-plan">
          <header>
            <div><b>Disk directories</b><small>Edit only the names that need attention.</small></div>
            <span>${items.length} rows</span>
          </header>
          <div class="bulk-disk-table-wrap">
            <table class="bulk-disk-table" aria-label="MMB disks planned for ADFS import">
              <thead><tr><th>Slot</th><th>MMB title</th>${grouped ? "<th>Group</th>" : ""}<th>ADFS directory</th></tr></thead>
              <tbody>
                ${items.map(item => `<tr data-collision="${collisionOffsets.has(item.offset) ? "1" : "0"}">
                  <td>${item.source.slot}</td>
                  <td title="${esc(item.source.name)}">${esc(item.source.name)}</td>
                  ${grouped ? `<td>${item.group + 1}</td>` : ""}
                  <td><input name="directoryName${item.offset}" maxlength="${item.rule.limit}"
                    aria-label="ADFS directory for slot ${item.source.slot}"
                    data-proposed="${esc(item.rule.suggested)}"
                    data-generic="${esc(genericNames.get(item.offset))}"
                    data-collision="${collisionOffsets.has(item.offset) ? "1" : "0"}"
                    value="${esc(initialNamingStrategy === "generic" ? genericNames.get(item.offset) : item.rule.suggested)}" required></td>
                </tr>`).join("")}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <footer class="bulk-planner-actions">
        <p>${grouped
          ? `${items.length} disks will be distributed across ${groupCount} editable parent groups.`
          : "Each non-empty disk becomes one child directory."}</p>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="copy">Copy ${items.length} disks</button></div>
      </footer>
    </div>`,
  async form => {
    submitted = true;
    const preparedItems = items.map(item => ({
      source: item.source,
      directoryName: form.get(`directoryName${item.offset}`),
      groupName: item.group == null ? null : form.get(`groupName${item.group}`)
    }));
    const submittedNames = new Map();
    for (const [offset, item] of preparedItems.entries()) {
      const groupName = item.groupName;
      if (groupName) {
        const groupRule = targetNameRule(target, groupName);
        if (!groupRule.valid) {
          throw new Error(
            `“${groupName}” is not a legal ADFS parent directory name. `
            + `Use no more than ${groupRule.limit} valid characters.`
          );
        }
      }
      const rule = targetNameRule(target, item.directoryName);
      if (!rule.valid) {
        throw new Error(
          `“${item.directoryName}” is not a legal ADFS directory name for `
          + `slot ${item.source.slot}.`
        );
      }
      const location = (groupName || target.path).toLowerCase();
      const key = `${location}:${item.directoryName.toLowerCase()}`;
      const previous = submittedNames.get(key);
      if (previous) {
        throw new Error(
          `Slots ${previous.source.slot} · ${previous.source.name} and `
          + `${item.source.slot} · ${item.source.name} would both use `
          + `“${item.directoryName}”. Give them different directory names.`
        );
      }
      submittedNames.set(key, item);
      preparedItems[offset].directoryName = rule.suggested;
    }
    const result = await performMmbSlotsToAdfsCopy(
      index,
      preparedItems,
      form.get("addMenu") === "yes",
      completedItems,
      skippedItems,
      replaceItems,
      collectedMetadata,
      { onlineMetadata: chosenRecipe.online !== false, compatibility: chosenRecipe.compatibility !== false }
    );
    if (result && afterCopy) {
      const copied = sources.filter(source => result.completedSlots.includes(Number(source.slot)));
      if (copied.length) await afterCopy(copied);
    }
    return result;
  });
  const applyNamingStrategy = strategy => {
    modalContent.querySelectorAll('[name^="directoryName"]').forEach(input => {
      input.value = strategy === "generic"
        ? input.dataset.generic
        : input.dataset.proposed;
      input.classList.toggle(
        "name-collision",
        strategy === "review" && input.dataset.collision === "1"
      );
    });
    modalContent.querySelectorAll(".bulk-disk-table tbody tr").forEach(row => {
      row.classList.toggle(
        "name-collision",
        strategy === "review" && row.dataset.collision === "1"
      );
    });
  };
  modalContent.querySelectorAll('[name="namingStrategy"]').forEach(option => {
    option.addEventListener("change", () => applyNamingStrategy(option.value));
  });
  modalContent.querySelector('[name="importRecipe"]')?.addEventListener("change", event => {
    const recipe = savedRecipes[Number(event.target.value)];
    if (!recipe) return;
    chosenRecipe = recipe;
    const strategy = recipe.naming === "generic" ? "generic" : "review";
    const radio = modalContent.querySelector(`[name="namingStrategy"][value="${strategy}"]`);
    if (radio) radio.checked = true;
    applyNamingStrategy(strategy);
    modalContent.querySelector('[name="addMenu"]').checked = recipe.addMenu !== false;
    modalContent.querySelectorAll('[name^="groupName"]').forEach((input, offset) => {
      input.value = `${recipe.groupPrefix || "DISCS"}${offset + 1}`.slice(0, 10);
    });
  });
  applyNamingStrategy(initialNamingStrategy);
  return new Promise(resolve => {
    closed.then(() => resolve(submitted));
  });
}

async function performMmbSlotsToAdfsCopy(
  index,
  items,
  addMenu,
  completedItems = new Set(),
  skippedItems = new Map(),
  replaceItems = new Set(),
  collectedMetadata = [],
  options = { onlineMetadata: true, compatibility: true }
) {
  const target = panes[index];
  const menuRoot = target.path;
  const collectMetadata = metadataItems => {
    const known = new Set(collectedMetadata.map(item => JSON.stringify([
      item.skipMenu ? "continuation" : "entry",
      item.sourceSlot ?? item.slot ?? "",
      item.path || item.diskTitle || "",
      item.title || item.continuationTitle || "",
      item.filename || "",
    ])));
    for (const item of metadataItems || []) {
      const key = JSON.stringify([
        item.skipMenu ? "continuation" : "entry",
        item.sourceSlot ?? item.slot ?? "",
        item.path || item.diskTitle || "",
        item.title || item.continuationTitle || "",
        item.filename || "",
      ]);
      if (known.has(key)) continue;
      known.add(key);
      collectedMetadata.push(item);
    }
  };
  try {
    const pendingItems = items.filter(item => {
      const key = `${item.source.image}:${item.source.slot}`;
      return !completedItems.has(key) && !skippedItems.has(key);
    });
    if (pendingItems.length) {
      const sourceImages = new Set(pendingItems.map(item => item.source.image));
      if (sourceImages.size !== 1) {
        throw new Error("Accelerated bulk copy requires the selected MMB slots to come from one image.");
      }
      const data = await trackedPaneOperation(
        index,
        `Accelerated copy of ${pendingItems.length} MMB disks into ADFS…`,
        operationId => api("/api/transfer-mmb-batch-to-adfs", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sourceImage: pendingItems[0].source.image,
            targetImage: target.image.id,
            items: pendingItems.map(item => ({
              sourceSlot: item.source.slot,
              sourceName: item.source.name,
              targetPath: item.groupName
                ? fullPath(target.path, item.groupName)
                : target.path,
              directoryName: item.directoryName,
              replaceExisting: replaceItems.has(
                `${item.source.image}:${item.source.slot}`
              )
            })),
            addMenu,
            stopOnEmpty: true,
            stopOnConflict: true,
            onlineMetadata: options.onlineMetadata !== false,
            compatibility: options.compatibility !== false,
            operationId
          })
        })
      );
      target.image = data.image;
      for (const result of data.completed || []) {
        completedItems.add(`${pendingItems[0].source.image}:${result.sourceSlot}`);
      }
      for (const result of data.skipped || []) {
        skippedItems.set(`${pendingItems[0].source.image}:${result.sourceSlot}`, result);
      }
      collectMetadata(data.metadata);
    }
    await loadDirectory(index);
    toast(
      `${completedItems.size} MMB disk${completedItems.size === 1 ? "" : "s"} copied`
      + (skippedItems.size ? `; ${skippedItems.size} skipped` : "")
    );
    setTimeout(async () => {
      if (skippedItems.size) {
        await showSkippedEmptyDisks([...skippedItems.values()], completedItems.size);
      }
      if (addMenu && collectedMetadata.length) {
        await queueAdfsMenuEntries(index, menuRoot, collectedMetadata);
      }
    }, 0);
    return {
      completedSlots: [...completedItems].map(key => Number(key.split(":").at(-1))),
      skippedSlots: [...skippedItems.values()].map(item => Number(item.sourceSlot)),
    };
  } catch (error) {
    if (error.data?.image) target.image = error.data.image;
    collectMetadata(error.data?.metadata);
    const sourceImage = items[0]?.source.image;
    for (const result of error.data?.completed || []) {
      completedItems.add(`${sourceImage}:${result.sourceSlot}`);
    }
    for (const result of error.data?.skipped || []) {
      skippedItems.set(`${sourceImage}:${result.sourceSlot}`, result);
    }
    await loadDirectory(index);
    const blankDisk = error.data?.blankDisk;
    if (blankDisk && error.data?.decisionRequired === "skip-or-abort") {
      const decision = await askBlankDiskDecision(
        blankDisk,
        completedItems.size,
        items.length
      );
      if (decision === "skip") {
        skippedItems.set(`${sourceImage}:${blankDisk.sourceSlot}`, blankDisk);
        modal.classList.add("busy");
        setModalProgress({
          title: "Continuing bulk copy",
          message: `Skipping slot ${blankDisk.sourceSlot} · ${blankDisk.sourceName} and continuing with the remaining disks.`,
          details: [
            { label: "Copied", value: String(completedItems.size) },
            { label: "Empty disks skipped", value: String(skippedItems.size) }
          ]
        });
        return performMmbSlotsToAdfsCopy(
          index,
          items,
          addMenu,
          completedItems,
          skippedItems,
          replaceItems,
          collectedMetadata,
          options
        );
      }
      toast(
        `Bulk copy aborted at slot ${blankDisk.sourceSlot} · ${blankDisk.sourceName}. `
        + `${completedItems.size} disk${completedItems.size === 1 ? "" : "s"} copied safely.`,
        true
      );
      modal.close();
      if (addMenu && collectedMetadata.length) {
        setTimeout(() => queueAdfsMenuEntries(index, menuRoot, collectedMetadata), 0);
      }
      return false;
    }
    const destinationConflict = error.data?.destinationConflict;
    if (
      destinationConflict
      && error.data?.decisionRequired === "keep-replace-or-abort"
    ) {
      const conflictKey = `${sourceImage}:${destinationConflict.sourceSlot}`;
      const decision = await askDestinationConflictDecision(
        destinationConflict,
        completedItems.size,
        items.length
      );
      if (decision === "keep") {
        skippedItems.set(conflictKey, {
          ...destinationConflict,
          reason: "Existing destination kept unchanged"
        });
      } else if (decision === "replace") {
        replaceItems.add(conflictKey);
      } else {
        toast(
          `Bulk copy aborted at slot ${destinationConflict.sourceSlot} · `
          + `${destinationConflict.sourceName}. ${completedItems.size} disk`
          + `${completedItems.size === 1 ? "" : "s"} copied safely.`,
          true
        );
        modal.close();
        if (addMenu && collectedMetadata.length) {
          setTimeout(() => queueAdfsMenuEntries(index, menuRoot, collectedMetadata), 0);
        }
        return false;
      }
      modal.classList.add("busy");
      setModalProgress({
        title: "Continuing bulk copy",
        message: decision === "replace"
          ? `Replacing ${destinationConflict.destination}, then continuing.`
          : `Keeping ${destinationConflict.destination} unchanged, then continuing.`,
        details: [
          { label: "Copied", value: String(completedItems.size) },
          { label: "Skipped", value: String(skippedItems.size) }
        ]
      });
      return performMmbSlotsToAdfsCopy(
        index,
        items,
        addMenu,
        completedItems,
        skippedItems,
        replaceItems,
        collectedMetadata,
        options
      );
    }
    const failure = new Error(
      `${completedItems.size} of ${items.length} disks have been copied`
      + (skippedItems.size ? ` and ${skippedItems.size} items skipped` : "")
      + `. ${error.message} Use Copy again to continue with the remaining disks.`
    );
    failure.data = {
      ...(error.data || {}),
      completed: [...completedItems].map(key => ({ key })),
      skipped: [...skippedItems.values()]
    };
    throw failure;
  }
}

function askBlankDiskDecision(blankDisk, copiedCount, totalCount) {
  modal.classList.remove("busy", "failed");
  modalContent.innerHTML = `
    <div class="blank-disk-decision">
      <span class="modal-error-icon" aria-hidden="true">!</span>
      <h2>Empty disk found</h2>
      <p><strong>Slot ${blankDisk.sourceSlot} · ${esc(blankDisk.sourceName)}</strong> has an empty DFS catalogue. An empty directory will not be created on the ADFS destination.</p>
      <div class="modal-progress-details">
        <span><b>Copied safely: </b>${copiedCount} of ${totalCount} disks</span>
        <span><b>If skipped: </b>Copying continues with the next remaining disk</span>
        <span><b>If aborted: </b>Completed directories are kept and no further disks are started</span>
      </div>
      <div class="modal-actions">
        <button class="button danger abort-blank-copy" type="button">Abort bulk copy</button>
        <button class="button primary skip-blank-copy" type="button">Skip this disk and continue</button>
      </div>
    </div>`;
  return new Promise(resolve => {
    let settled = false;
    const decide = choice => {
      if (settled) return;
      settled = true;
      resolve(choice);
    };
    modalContent.querySelector(".skip-blank-copy").onclick = () => decide("skip");
    modalContent.querySelector(".abort-blank-copy").onclick = () => decide("abort");
    modal.addEventListener("close", () => decide("abort"), { once: true });
    modalContent.querySelector(".skip-blank-copy").focus();
  });
}

function askDestinationConflictDecision(conflict, copiedCount, totalCount) {
  modal.classList.remove("busy", "failed");
  modalContent.innerHTML = `
    <div class="blank-disk-decision destination-conflict-decision">
      <span class="modal-error-icon" aria-hidden="true">!</span>
      <h2>Destination directory already exists</h2>
      <p><strong>Slot ${conflict.sourceSlot} · ${esc(conflict.sourceName)}</strong> was going to be copied to <code>${esc(conflict.destination)}</code>, but that directory is already present.</p>
      <div class="modal-progress-details">
        <span><b>Copied safely: </b>${copiedCount} of ${totalCount} disks</span>
        <span><b>Keep existing: </b>Leave that directory untouched and continue with the next disk</span>
        <span><b>Replace: </b>Delete that directory, recopy this disk, then continue</span>
        <span><b>Abort: </b>Keep all completed work and start no further disks</span>
      </div>
      <div class="modal-actions conflict-actions">
        <button class="button danger abort-conflict-copy" type="button">Abort bulk copy</button>
        <button class="button keep-conflict-copy" type="button">Keep existing and continue</button>
        <button class="button primary replace-conflict-copy" type="button">Replace and continue</button>
      </div>
    </div>`;
  return new Promise(resolve => {
    let settled = false;
    const decide = choice => {
      if (settled) return;
      settled = true;
      resolve(choice);
    };
    modalContent.querySelector(".keep-conflict-copy").onclick = () => decide("keep");
    modalContent.querySelector(".replace-conflict-copy").onclick = () => decide("replace");
    modalContent.querySelector(".abort-conflict-copy").onclick = () => decide("abort");
    modal.addEventListener("close", () => decide("abort"), { once: true });
    modalContent.querySelector(".keep-conflict-copy").focus();
  });
}

async function showSkippedEmptyDisks(skipped, copiedCount) {
  showModal(`
    <h2>Bulk copy completed with warnings</h2>
    <p>${copiedCount} disk${copiedCount === 1 ? "" : "s"} copied. The items below were skipped at your request. Empty disks do not create directories; existing destinations were left unchanged.</p>
    <div class="scan-notes">
      ${skipped.map(item => `<span>Slot ${item.sourceSlot} · ${esc(item.sourceName || item.directoryName || item.destination)} · ${esc(item.reason)}</span>`).join("")}
    </div>
    <div class="modal-actions"><button class="button primary" value="cancel">Continue</button></div>`);
  await new Promise(resolve => modal.addEventListener("close", resolve, { once: true }));
}

async function queueAdfsMenuEntries(index, menuRoot, metadataItems) {
  let refreshNeeded = false;
  let previewHighlight = "";
  const continuations = metadataItems.filter(metadata => metadata.skipMenu);
  const menuCandidates = metadataItems.filter(metadata => !metadata.skipMenu);
  const obvious = menuCandidates.filter(hasObviousLaunchCandidate);
  const ambiguous = menuCandidates.filter(metadata => !hasObviousLaunchCandidate(metadata));
  if (continuations.length) {
    const examples = continuations
      .slice(0, 3)
      .map(item => `${item.sourceName || item.diskTitle} → ${item.continuationTitle}`)
      .join(", ");
    toast(
      `${continuations.length} continuation disk${continuations.length === 1 ? "" : "s"} kept off-menu`
      + `${examples ? `: ${examples}${continuations.length > 3 ? "…" : ""}` : ""}`
    );
  }
  if (obvious.length) {
    try {
      await saveDetectedAdfsMenuEntries(index, menuRoot, obvious, false);
      refreshNeeded = true;
      previewHighlight = obvious.at(-1)?.path || obvious.at(-1)?.title || "";
    } catch (error) {
      toast(`Could not update the ADFS menu: ${error.message}`, true);
    }
  }
  const reviewBatch = { acceptAll: false, current: 0, total: ambiguous.length };
  for (const [offset, metadata] of ambiguous.entries()) {
    reviewBatch.current = offset + 1;
    const shown = await reviewAdfsMenuMetadata(index, menuRoot, metadata, false, reviewBatch);
    if (shown && modal.open) {
      await new Promise(resolve => modal.addEventListener("close", resolve, { once: true }));
    }
    previewHighlight = metadata.path || metadata.title || previewHighlight;
  }
  if (refreshNeeded) await loadDirectory(index);
  if (obvious.length || ambiguous.length) await showMenuPreview(index, previewHighlight);
}

async function performMmbSlotToAdfsCopy(index, source, directoryName, addMenu = false) {
  const target = panes[index];
  const menuRoot = target.path;
  const data = await trackedPaneOperation(index, `Preparing slot ${source.slot}…`, operationId =>
    api("/api/transfer-slot-to-directory", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceImage: source.image,
        sourceSlot: source.slot,
        targetImage: target.image.id,
        targetPath: target.path,
        directoryName,
        addMenu,
        operationId
      })
    }));
  target.image = data.image;
  await loadDirectory(index);
  toast(`Slot ${source.slot} copied into ${data.path}`);
  const menuEntries = data.metadataEntries?.length
    ? data.metadataEntries
    : data.metadata
      ? [data.metadata]
      : [];
  if (addMenu && menuEntries.length) {
    setTimeout(() => queueAdfsMenuEntries(index, menuRoot, menuEntries), 0);
  }
}

async function copyDiskImageToAdfs(index, source) {
  const target = panes[index];
  const rule = targetNameRule(target, formats.stem(source.name));
  const preview = await paneOperation(
    index,
    `Reading ${source.name} contents…`,
    () => api(`/api/images/${source.image}/preview`)
  );
  return showImageExtractionPlan(index, {
    heading: `Copy ${source.name} into ADFS`,
    sourceName: source.name,
    preview,
    suggestedName: rule.suggested,
    allowRaw: false,
    submitLabel: "Copy image contents",
    onExtract: plan => performDiskImageToAdfsCopy(index, source, plan),
  });
}

async function performDiskImageToAdfsCopy(index, source, plan) {
  const target = panes[index];
  const menuRoot = target.path;
  const destinationLabel = plan.createDirectory ? plan.directoryName : plan.targetPath;
  const data = await trackedPaneOperation(index, `Copying ${source.name} into ${destinationLabel}…`, operationId =>
    api("/api/transfer-image-to-directory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceImage: source.image,
        targetImage: target.image.id,
        targetPath: plan.targetPath,
        directoryName: plan.directoryName,
        createDirectory: plan.createDirectory,
        addMenu: plan.addMenu,
        operationId
      })
    }));
  target.image = data.image;
  await loadDirectory(index);
  toast(`${source.name} contents copied into ${data.path}`);
  if (plan.addMenu && data.metadata) {
    setTimeout(() => offerAdfsMenuEntry(index, menuRoot, data.metadata), 0);
  }
}

async function openEntry(index, row) {
  const pane = panes[index];
  if (row.dataset.parent === "1") {
    if (pane.slot !== null && pane.path === "") await returnToMmb(index);
    else await navigate(index, isDfsPane(pane) && pane.path.length === 1 ? "" : parentPath(pane.path));
  } else if (row.dataset.type === "disk") {
    const entry = pane.entries.find(item => item.slot === Number(row.dataset.slot));
    if (!entry?.formatted) return toast("That MMB slot is not formatted.", true);
    pane.slot = Number(row.dataset.slot);
    pane.slotName = entry.name;
    pane.path = "";
    await loadDirectory(index);
  } else if (row.dataset.type === "dir") {
    await navigate(index, fullPath(pane.path, row.dataset.name));
  } else {
    downloadFile(index, row.dataset.name);
  }
}

async function returnToMmb(index) {
  const pane = panes[index];
  const previousSlot = pane.slot;
  const requestToken = (pane.requestToken || 0) + 1;
  pane.requestToken = requestToken;
  pane.slot = null;
  pane.slotName = "";
  pane.path = "$";
  setSelection(pane, [String(previousSlot)], String(previousSlot));
  pane.loading = true;
  renderPane(index);
  try {
    const data = await api(`/api/images/${pane.image.id}/slots`);
    if (panes[index] !== pane || pane.requestToken !== requestToken || pane.slot !== null) return;
    pane.entries = data.slots;
    pane.capacity = await fetchCapacity(pane.image.id);
    pane.description = "Select a disk to browse its DFS catalogue";
  } catch (error) {
    if (panes[index] === pane && pane.requestToken === requestToken) toast(error.message, true);
  } finally {
    if (panes[index] !== pane || pane.requestToken !== requestToken || pane.slot !== null) return;
    pane.loading = false;
    renderPane(index);
    document.querySelector(`.pane[data-pane="${index}"] .file-row.selected`)?.scrollIntoView({ block: "center" });
  }
}

async function refreshCurrentView(index) {
  const pane = panes[index];
  if (!pane.image) return;
  if (pane.image.kind === "mmb" && pane.slot === null) {
    const selected = selectionKeys(pane);
    const selectionAnchor = pane.selectionAnchor;
    const requestToken = (pane.requestToken || 0) + 1;
    pane.requestToken = requestToken;
    pane.loading = true;
    pane.loadingMessage = "Refreshing MMB index…";
    renderPane(index);
    try {
      const [data, menu] = await Promise.all([
        api(`/api/images/${pane.image.id}/slots`),
        api(`/api/images/${pane.image.id}/menu/detected`).catch(() => ({ detected: false })),
      ]);
      if (panes[index] !== pane || pane.requestToken !== requestToken) return;
      pane.entries = data.slots;
      pane.capacity = await fetchCapacity(pane.image.id);
      pane.menuDetected = Boolean(menu.detected);
      pane.menuDetectionPending = false;
      setSelection(pane, selected, selectionAnchor);
      pane.description = "Select a disk to browse its DFS catalogue";
      toast("MMB index refreshed");
    } catch (error) {
      if (panes[index] === pane && pane.requestToken === requestToken) toast(error.message, true);
    } finally {
      if (panes[index] !== pane || pane.requestToken !== requestToken) return;
      pane.loading = false;
      renderPane(index);
    }
    return;
  }
  pane.loadingMessage = "Refreshing current directory…";
  await loadDirectory(index, true);
  toast("Current view refreshed");
}

async function reloadImageAfterRestore(image) {
  const affected = panes
    .map((pane, index) => pane.image?.id === image.id ? index : -1)
    .filter(index => index >= 0);
  for (const index of affected) {
    await acceptImage(index, image);
  }
  rememberOpenPanes();
}

function undoLastChange(index) {
  const pane = panes[index];
  if (!pane.image?.checkpoints?.canUndo) {
    return toast("There is no change to undo yet.", true);
  }
  showModal(`
    <h2>Undo the last change?</h2>
    <p>The image will return to its state immediately before the most recent image-changing operation.</p>
    <div class="help-note"><strong>Named checkpoints are kept.</strong> Undo consumes only the latest automatic restore point. Any other pane showing this image will refresh too.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="undo">Undo last change</button></div>`,
  async () => {
    const data = await api(`/api/images/${pane.image.id}/undo`, { method: "POST" });
    await reloadImageAfterRestore(data.image);
    toast(`Undone: ${data.checkpoint.reason}`);
  });
}

async function showCheckpointManager(index) {
  const pane = panes[index];
  const data = await api(`/api/images/${pane.image.id}/checkpoints`);
  pane.image = data.image;
  const rows = data.checkpoints.map(checkpoint => {
    const created = new Date(checkpoint.created).toLocaleString();
    return `<li class="checkpoint-row" data-checkpoint="${esc(checkpoint.id)}">
      <span class="checkpoint-kind ${checkpoint.automatic ? "automatic" : "named"}" aria-hidden="true">${checkpoint.automatic ? "↶" : "●"}</span>
      <span class="checkpoint-details"><strong>${esc(checkpoint.name)}</strong><small>${checkpoint.automatic ? "Automatic undo point" : "Named checkpoint"} · ${esc(created)} · ${humanSize(checkpoint.size)}</small></span>
      <button class="row-action checkpoint-restore" type="button" title="Restore ${esc(checkpoint.name)}" aria-label="Restore ${esc(checkpoint.name)}">↶</button>
      <button class="row-action delete checkpoint-delete" type="button" title="Delete ${esc(checkpoint.name)}" aria-label="Delete ${esc(checkpoint.name)}">×</button>
    </li>`;
  }).join("");
  showModal(`
    <div class="checkpoint-heading"><div><small>IMAGE HISTORY</small><h2>Checkpoints</h2></div><span>${data.checkpoints.length} saved</span></div>
    <p>Create a permanent named checkpoint before a larger experiment, or restore any recent automatic undo point.</p>
    <div class="field"><label>New checkpoint name · max 60 characters</label><input name="name" maxlength="60" placeholder="Before reorganising Games" required></div>
    <ul class="checkpoint-list">${rows || '<li class="checkpoint-empty">No checkpoints yet. Image-changing operations will add automatic undo points here.</li>'}</ul>
    <div class="help-note"><strong>Storage:</strong> checkpoints stay inside this browser-owned working session. Large images use fast copy-on-write clones where available, with a sparse safe-copy fallback for zero-filled HDD capacity.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Close</button><button class="button primary" value="create">Create named checkpoint</button></div>`,
  async form => {
    const result = await api(`/api/images/${pane.image.id}/checkpoints`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: form.get("name") })
    });
    pane.image = result.image;
    renderPane(index, true);
    toast(`Checkpoint “${result.checkpoint.name}” created`);
    setTimeout(() => showCheckpointManager(index), 0);
  });
  modalContent.querySelectorAll(".checkpoint-restore").forEach(button => {
    button.onclick = async () => {
      const row = button.closest("[data-checkpoint]");
      const checkpoint = data.checkpoints.find(item => item.id === row.dataset.checkpoint);
      if (!checkpoint || !confirm(`Restore “${checkpoint.name}”? The current state will be kept as an automatic undo point.`)) return;
      modal.close();
      try {
        const result = await paneOperation(index, `Restoring ${checkpoint.name}…`, () => api(
          `/api/images/${pane.image.id}/checkpoints/${checkpoint.id}/restore`,
          { method: "POST" }
        ));
        await reloadImageAfterRestore(result.image);
        toast(`Restored “${checkpoint.name}”`);
      } catch (error) {
        toast(`Could not restore checkpoint: ${error.message}`, true);
      }
    };
  });
  modalContent.querySelectorAll(".checkpoint-delete").forEach(button => {
    button.onclick = async () => {
      const row = button.closest("[data-checkpoint]");
      const checkpoint = data.checkpoints.find(item => item.id === row.dataset.checkpoint);
      if (!checkpoint || !confirm(`Delete checkpoint “${checkpoint.name}”?`)) return;
      button.disabled = true;
      try {
        const result = await api(
          `/api/images/${pane.image.id}/checkpoints/${checkpoint.id}`,
          { method: "DELETE" }
        );
        pane.image = result.image;
        modal.close();
        renderPane(index, true);
        toast(`Checkpoint “${checkpoint.name}” deleted`);
        setTimeout(() => showCheckpointManager(index), 0);
      } catch (error) {
        button.disabled = false;
        toast(`Could not delete checkpoint: ${error.message}`, true);
      }
    };
  });
}

function trackFileInput(input, summary) {
  const state = { files: [] };
  const render = files => {
    state.files = [...files];
    summary.replaceChildren();
    if (!state.files.length) {
      const empty = document.createElement("span");
      empty.className = "file-selection-empty";
      empty.textContent = "No files selected yet · files can also be dropped here";
      summary.append(empty);
    } else {
      for (const file of state.files) {
        const row = document.createElement("span");
        const name = document.createElement("strong");
        name.textContent = file.name;
        row.append(name, document.createTextNode(` · ${humanSize(file.size)}`));
        summary.append(row);
      }
    }
    summary.classList.toggle("has-files", Boolean(state.files.length));
    summary.classList.remove("chooser-failed");
    summary.dispatchEvent(new CustomEvent("selectionchange"));
  };
  state.setFiles = render;
  const sync = () => render(input.files);
  input.addEventListener("change", sync);
  input.addEventListener("input", sync);
  input.addEventListener("click", () => {
    window.addEventListener("focus", () => {
      setTimeout(() => {
        if (input.files.length || state.files.length) return;
        summary.replaceChildren();
        const warning = document.createElement("span");
        warning.className = "file-selection-empty";
        warning.textContent = "Firefox returned no file. Try dropping the file here instead.";
        summary.append(warning);
        summary.classList.add("chooser-failed");
      }, 300);
    }, { once: true });
  });
  render([]);
  return state;
}

function acceptFileDrop(zone, onFiles) {
  zone.addEventListener("dragover", event => {
    if (!event.dataTransfer?.types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    zone.classList.add("drop-target");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("drop-target"));
  zone.addEventListener("drop", event => {
    zone.classList.remove("drop-target");
    const files = [...(event.dataTransfer?.files || [])];
    if (!files.length) return;
    event.preventDefault();
    onFiles(files);
  });
}

function chooseImage(index) {
  const pane = panes[index];
  if (pane.loading) return;
  let selection = { files: [] };
  showModal(`
    <h2>Open a disk image</h2>
    <p>Choose one or more matching files, such as a DAT with its DSC descriptor. ZIP distributions are also supported.</p>
    <div class="field"><label>Image file</label>
      <input type="file" name="images" accept="${esc(formats.accept)}" multiple>
      <div class="file-selection-summary" data-selected-files aria-live="polite"></div>
    </div>
    <div class="field"><label>ADFS target hardware</label>
      <select name="targetHardware">
        <option value="auto">Auto / inspect only</option>
        <option value="beebscsi">BeebSCSI DAT + DSC · Electron / BBC / Master</option>
        <option value="electron-plus3">Electron Plus 3 · normal ADFS</option>
        <option value="bbc-master">BBC / Master · normal 8-bit ADFS</option>
        <option value="risc-os">Archimedes / RISC OS</option>
      </select>
      <small>Used for ADFS validation and hardware-safe repairs. It is ignored for DFS, MMB and UEF images.</small>
    </div>
    <div class="modal-actions">
      <button class="button ghost" value="cancel">Cancel</button>
      <button class="button primary" value="open" data-open-selection disabled>Open selected image</button>
    </div>`,
  form => {
    const files = selection.files;
    if (!files.length) throw new Error("Choose a disk image to open.");
    // Let showModal finish closing this dialog before a DAT/DSC pairing
    // dialog is opened. Opening the replacement synchronously here lets the
    // first dialog's promise handler close the new one as well.
    const targetHardware = form.get("targetHardware") || "auto";
    setTimeout(() => openFiles(index, files, targetHardware), 0);
  });
  const selectionSummary = modalContent.querySelector("[data-selected-files]");
  const openSelection = modalContent.querySelector("[data-open-selection]");
  selection = trackFileInput(
    modalContent.querySelector('input[name="images"]'),
    selectionSummary
  );
  acceptFileDrop(selectionSummary, files => selection.setFiles(files));
  selectionSummary.addEventListener("selectionchange", () => {
    openSelection.disabled = !selection.files.length;
  });
}

function promptAdfsTargetHardware(index, files) {
  const closed = showModal(`
    <h2>Choose ADFS target hardware</h2>
    <p>The selected hardware profile controls filesystem validation and repairs. Choose the machine that will use the finished image.</p>
    <div class="field"><label>Target hardware</label>
      <select name="targetHardware">
        <option value="beebscsi">BeebSCSI DAT + DSC · Electron / BBC / Master</option>
        <option value="electron-plus3">Electron Plus 3 · normal ADFS</option>
        <option value="bbc-master">BBC / Master · normal 8-bit ADFS</option>
        <option value="risc-os">Archimedes / RISC OS</option>
        <option value="auto">Auto / inspect only</option>
      </select>
    </div>
    <div class="help-note"><strong>Normal ADFS vs BeebSCSI:</strong> choose the machine profile for a normal ADFS disk. Choose BeebSCSI for a DAT/DSC hard drive; it works with Electron, BBC and Master hosts and also enforces the official BeebSCSI file layout.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="open">Validate and open</button></div>`,
  form => {
    const targetHardware = form.get("targetHardware") || "auto";
    setTimeout(() => openFiles(index, files, targetHardware), 0);
  });
}

function promptBeebScsiPair(
  index,
  image = null,
  descriptor = null,
  warning = "",
  targetHardware = "auto"
) {
  panes[index].loading = false;
  panes[index].loadingMessage = "";
  renderPane(index);
  let imageSelection = { files: [] };
  let descriptorSelection = { files: [] };
  showModal(`
    <h2>Open the DAT and DSC together</h2>
    <p>BeebSCSI DAT images store their drive geometry in a companion DSC file. The file you already selected has been retained; choose only its missing companion.</p>
    ${warning ? `<div class="scan-notes"><span>${esc(warning)}</span></div>` : ""}
    <div class="pair-file-drop" data-pair-drop>Drop the matching DAT and DSC here together</div>
    <div class="field"><label>DAT image${image ? " · selected" : ""}</label>
      ${image ? `<small class="prefilled-file">${esc(image.name)} · ${humanSize(image.size)}</small>` : ""}
      <input type="file" name="image" accept=".dat">
      <div class="file-selection-summary compact" data-selected-dat aria-live="polite"></div>
      ${image ? "<small>Optional: choose a different DAT to replace the retained file.</small>" : ""}
    </div>
    <div class="field"><label>Matching DSC descriptor${descriptor ? " · selected" : ""}</label>
      ${descriptor ? `<small class="prefilled-file">${esc(descriptor.name)} · ${humanSize(descriptor.size)}</small>` : ""}
      <input type="file" name="descriptor" accept=".dsc">
      <div class="file-selection-summary compact" data-selected-dsc aria-live="polite"></div>
      ${descriptor ? "<small>Optional: choose a different DSC to replace the retained file.</small>" : ""}
    </div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="open" data-open-pair disabled>Open DAT + DSC</button></div>`,
  async () => {
    const chosenImage = imageSelection.files[0]
      ? imageSelection.files[0]
      : image;
    const chosenDescriptor = descriptorSelection.files[0]
      ? descriptorSelection.files[0]
      : descriptor;
    if (!(chosenImage instanceof File) || !chosenImage.name.toLowerCase().endsWith(".dat")) {
      throw new Error("Choose the BeebSCSI DAT image.");
    }
    if (!(chosenDescriptor instanceof File) || !chosenDescriptor.name.toLowerCase().endsWith(".dsc")) {
      throw new Error("Choose the matching DSC file.");
    }
    if (formats.stem(chosenDescriptor.name).toLowerCase() !== formats.stem(chosenImage.name).toLowerCase()) {
      throw new Error(`Choose ${formats.stem(chosenImage.name)}.dsc for this DAT image.`);
    }
    await openFiles(index, [chosenImage, chosenDescriptor], targetHardware);
  });
  const pairButton = modalContent.querySelector("[data-open-pair]");
  const updatePairButton = () => {
    pairButton.disabled = !(imageSelection.files[0] || image)
      || !(descriptorSelection.files[0] || descriptor);
  };
  const datSummary = modalContent.querySelector("[data-selected-dat]");
  const dscSummary = modalContent.querySelector("[data-selected-dsc]");
  imageSelection = trackFileInput(
    modalContent.querySelector('input[name="image"]'),
    datSummary
  );
  descriptorSelection = trackFileInput(
    modalContent.querySelector('input[name="descriptor"]'),
    dscSummary
  );
  acceptFileDrop(datSummary, files => {
    const selected = files.find(file => file.name.toLowerCase().endsWith(".dat"));
    if (selected) imageSelection.setFiles([selected]);
  });
  acceptFileDrop(dscSummary, files => {
    const selected = files.find(file => file.name.toLowerCase().endsWith(".dsc"));
    if (selected) descriptorSelection.setFiles([selected]);
  });
  acceptFileDrop(modalContent.querySelector("[data-pair-drop]"), files => {
    const selectedImage = files.find(file => file.name.toLowerCase().endsWith(".dat"));
    const selectedDescriptor = files.find(file => file.name.toLowerCase().endsWith(".dsc"));
    if (selectedImage) imageSelection.setFiles([selectedImage]);
    if (selectedDescriptor) descriptorSelection.setFiles([selectedDescriptor]);
  });
  datSummary.addEventListener("selectionchange", updatePairButton);
  dscSummary.addEventListener("selectionchange", updatePairButton);
  updatePairButton();
}

async function openFiles(index, files, targetHardware = null) {
  if (!files.length) return;
  let image = files.find(file => !formats.isDescriptor(file.name));
  const descriptor = files.find(file => formats.isDescriptor(file.name));
  if (!image) {
    if (descriptor) {
      promptBeebScsiPair(index, null, descriptor, "", targetHardware || "auto");
      return;
    }
    return;
  }
  if (targetHardware === null && formats.isPotentialAdfsImage(image.name)) {
    return promptAdfsTargetHardware(index, files);
  }
  targetHardware ||= "auto";
  if (
    image.name.toLowerCase().endsWith(".dat")
    && descriptor
    && formats.stem(descriptor.name).toLowerCase() !== formats.stem(image.name).toLowerCase()
  ) {
    promptBeebScsiPair(
      index,
      image,
      descriptor,
      `${image.name} and ${descriptor.name} do not have matching base names. Replace the incorrect file.`,
      targetHardware
    );
    return;
  }
  if (image.name.toLowerCase().endsWith(".dat") && !descriptor) {
    promptBeebScsiPair(index, image, null, "", targetHardware);
    return;
  }
  const form = new FormData();
  form.append("image", image);
  if (descriptor) form.append("descriptor", descriptor);
  form.append("targetHardware", targetHardware);
  setLoading(index, true, `Uploading and opening ${image.name}…`);
  try {
    const data = await uploadApi("/api/images", form, {
      onProgress: (loaded, total) => {
        const progress = total
          ? ` · ${Math.min(100, Math.round(loaded * 100 / total))}%`
          : ` · ${humanSize(loaded)}`;
        setLoading(index, true, `Uploading ${image.name}${progress}`);
      },
      onProcessing: () => setLoading(
        index,
        true,
        `Upload complete · opening ${image.name}…`
      )
    });
    await acceptImage(index, data.image);
    toast(`${data.image.name} opened`);
  } catch (error) {
    panes[index].loading = false;
    panes[index].loadingMessage = "";
    renderPane(index);
    toast(error.message, true);
  }
}

async function acceptImage(index, image) {
  const currentPane = panes[index];
  const preserveMmbRoot = Boolean(
    currentPane?.image?.id === image.id
    && currentPane.image.kind === "mmb"
    && currentPane.slot === null
  );
  const preservedSelection = preserveMmbRoot ? selectionKeys(currentPane) : [];
  const preservedAnchor = preserveMmbRoot ? currentPane.selectionAnchor : null;
  const preservedScrollTop = preserveMmbRoot
    ? document.querySelector(`.pane[data-pane="${index}"] .list-wrap`)?.scrollTop || 0
    : 0;
  panes[index] = newPaneState(image);
  const pane = panes[index];
  if (preserveMmbRoot) pane.mmbScrollTop = preservedScrollTop;
  const requestToken = ++pane.requestToken;
  renderPane(index);
  if (image.kind === "mmb") {
    const [data, menu, capacity] = await Promise.all([
      api(`/api/images/${image.id}/slots`),
      api(`/api/images/${image.id}/menu/detected`).catch(() => ({ detected: false })),
      fetchCapacity(image.id),
    ]);
    if (panes[index] !== pane || pane.requestToken !== requestToken) return;
    pane.entries = data.slots;
    pane.capacity = capacity;
    pane.menuDetected = Boolean(menu.detected);
    pane.menuDetectionPending = false;
    pane.description = "Select a disk to browse its DFS catalogue";
    pane.loading = false;
    if (preserveMmbRoot) {
      const available = new Set(pane.entries.map(entry => String(entry.slot)));
      setSelection(pane, preservedSelection.filter(key => available.has(key)), preservedAnchor);
    }
    renderPane(index);
    if (preserveMmbRoot) {
      const list = document.querySelector(`.pane[data-pane="${index}"] .list-wrap`);
      if (list) list.scrollTop = preservedScrollTop;
    }
  } else {
    await loadDirectory(index);
  }
  if (image.warnings?.length) toast(image.warnings.join(" "), true);
}

async function loadDirectory(index, preserveSelection = false) {
  const pane = panes[index];
  const requestToken = (pane.requestToken || 0) + 1;
  pane.requestToken = requestToken;
  const requested = {
    image: pane.image.id,
    slot: pane.slot,
    side: pane.side,
    path: pane.path
  };
  const selected = selectionKeys(pane);
  const selectionAnchor = pane.selectionAnchor;
  pane.loading = true;
  pane.loadingMessage = pane.loadingMessage || "Reading disk…";
  if (!preserveSelection) setSelection(pane, []);
  renderPane(index);
  try {
    const query = new URLSearchParams({ path: pane.path });
    if (pane.slot !== null) query.set("slot", pane.slot);
    if (pane.side !== null) query.set("side", pane.side);
    const data = await api(`/api/images/${pane.image.id}/tree?${query}`);
    if (
      panes[index] !== pane || pane.requestToken !== requestToken ||
      pane.image.id !== requested.image || pane.slot !== requested.slot ||
      pane.side !== requested.side || pane.path !== requested.path
    ) return;
    pane.entries = data.entries;
    pane.capacity = data.capacity || pane.capacity;
    pane.description = data.description;
    if (preserveSelection) setSelection(pane, selected, selectionAnchor);
  } catch (error) {
    if (panes[index] === pane && pane.requestToken === requestToken) toast(error.message, true);
  } finally {
    if (panes[index] !== pane || pane.requestToken !== requestToken) return;
    pane.loading = false;
    pane.loadingMessage = "";
    renderPane(index);
  }
}

function navigate(index, path) {
  panes[index].path = path;
  return loadDirectory(index);
}

function removePane(index) {
  const pane = panes[index];
  if (!pane) return;
  const imageName = pane.image?.name;
  panes.splice(index, 1);
  rebuildPaneHosts();
  rememberOpenPanes();
  if (imageName) toast(`${imageName} closed · its working copy remains available in Recovery.`);
}

async function closePane(index) {
  const pane = panes[index];
  if (!pane) return;
  if (panes.some(item => item.loading || item.actionPending)) {
    return toast("Wait for current pane operations to finish before closing a pane.", true);
  }
  if (!pane.image?.dirty) {
    removePane(index);
    return;
  }
  let closeAction = "save";
  showModal(`
    <h2>Save ${esc(pane.image.name)} before closing?</h2>
    <p>This working image contains changes. Save a timestamped image and README ZIP now, discard the download, or cancel and keep the pane open.</p>
    <div class="help-note"><strong>Recovery remains available:</strong> closing a pane does not delete its private server-side working copy.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button danger" data-close-without-saving value="discard">Close without saving</button><button class="button primary" value="save">Save and close</button></div>`,
  async () => {
    if (closeAction === "discard") {
      removePane(index);
      return;
    }
    if (!await saveImage(index)) return false;
    removePane(index);
  });
  modalContent.querySelector("[data-close-without-saving]").onclick = () => {
    closeAction = "discard";
  };
}

function beginImageRename(index) {
  const pane = panes[index];
  if (!pane.image || pane.loading || pane.actionPending) return;
  const host = document.querySelector(`.pane[data-pane="${index}"]`);
  const title = host.querySelector(".image-title");
  if (!title) return;

  const input = document.createElement("input");
  input.className = "image-title-input";
  input.type = "text";
  input.maxLength = 180;
  input.value = pane.image.name;
  input.setAttribute("aria-label", "Image filename");
  title.replaceWith(input);
  input.focus();
  const extensionAt = input.value.lastIndexOf(".");
  input.setSelectionRange(0, extensionAt > 0 ? extensionAt : input.value.length);

  let finished = false;
  const cancel = () => {
    if (finished) return;
    finished = true;
    renderPane(index, true);
  };
  const commit = async () => {
    if (finished) return;
    const name = input.value.trim();
    if (!name || name === pane.image.name) {
      cancel();
      return;
    }
    finished = true;
    try {
      const data = await paneOperation(index, "Renaming image…", () => api(`/api/images/${pane.image.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
      }));
      pane.image = data.image;
      renderPane(index, true);
      toast(`Image renamed to ${data.image.name}`);
    } catch (error) {
      renderPane(index, true);
      toast(`Could not rename image: ${error.message}`, true);
    }
  };
  input.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  });
  input.addEventListener("blur", commit);
}

function renameSelected(index) {
  const pane = panes[index];
  const entry = selectedEntry(index);
  if (!entry) return;
  const isSlot = pane.image.kind === "mmb" && pane.slot === null;
  const oldPath = isSlot ? entry.name : fullPath(pane.path, entry.name);
  const nameLimit = pane.image.kind === "adfs" ? 10 : isDfsPane(pane) ? 7 : 12;
  showModal(`
    <h2>${isSlot ? "Rename MMB disk" : `Rename ${esc(entry.name)}`}</h2>
    <p>${isSlot ? "The slot number and disk contents stay unchanged." : "The item stays in its current directory. Drag it onto another directory to move it."}</p>
    <div class="field"><label>${isSlot ? "Disk title" : "New name"} · max ${nameLimit} characters</label>
      <input name="destination" maxlength="${nameLimit}" value="${esc(entry.name)}" required></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="ok">Rename</button></div>`,
  async form => {
    const body = { slot: isSlot ? entry.slot : pane.slot, side: pane.side };
    if (isSlot) body.slotTitle = form.get("destination");
    else {
      body.source = oldPath;
      body.destination = fullPath(pane.path, form.get("destination"));
    }
    const data = await api(`/api/images/${pane.image.id}/rename`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    });
    if (isSlot) {
      pane.image = data.image;
      await acceptImage(index, pane.image);
    } else if (pane.image.kind === "adfs") {
      await refreshSharedAdfsPanes(pane.image.id, data.image, data.moved);
    } else {
      pane.image = data.image;
      await loadDirectory(index);
    }
    toast(
      `Name updated${data.menuEntriesUpdated
        ? `; ${data.menuEntriesUpdated} menu ${data.menuEntriesUpdated === 1 ? "entry" : "entries"} updated`
        : ""}`,
    );
  });
}

function deleteSelected(index) {
  const pane = panes[index];
  const isSlot = pane.image.kind === "mmb" && pane.slot === null;
  const entries = selectedEntries(index).filter(item =>
    isSlot ? item.type === "disk" && item.formatted : true
  );
  if (!entries.length) return;
  const single = entries.length === 1 ? entries[0] : null;
  const selectionLabel = isSlot
    ? single ? `disk ${single.slot} · ${esc(single.name)}` : `${entries.length} selected disks`
    : single ? esc(single.name) : `${entries.length} selected items`;
  const contentsWarning = !isSlot && entries.some(
    item => item.type === "dir" || item.type === "directory"
  ) ? " Selected directories and everything inside them will be removed." : "";
  showModal(`
    <h2>${isSlot ? "Eject" : "Delete"} ${selectionLabel}?</h2>
    <p>${isSlot ? "Each selected slot catalogue entry and its 200 KiB disk data will be cleared." : `This removes ${single ? "the selected item" : "all selected items"} from the working image.${contentsWarning}`} Associated installed-menu entries are removed together in the same operation. Your original image remains untouched.</p>
    <div class="modal-actions"><button class="button ghost" value="cancel">Keep ${entries.length === 1 ? "it" : "them"}</button><button class="button danger" value="delete">${isSlot ? "Eject" : "Delete"} ${entries.length} ${isSlot ? `disk${entries.length === 1 ? "" : "s"}` : `item${entries.length === 1 ? "" : "s"}`}</button></div>`,
  async () => {
    const endpoint = isSlot ? `/api/images/${pane.image.id}/slots/clear` : `/api/images/${pane.image.id}/delete`;
    const body = isSlot
      ? { slots: entries.map(item => item.slot) }
      : {
          slot: pane.slot,
          side: pane.side,
          items: entries.map(item => ({
            path: fullPath(pane.path, item.name),
            recursive: item.type === "dir" || item.type === "directory",
          })),
        };
    const data = await api(endpoint, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    if (isSlot) {
      pane.image = data.image;
      await acceptImage(index, pane.image);
    } else if (pane.image.kind === "adfs") {
      await refreshSharedAdfsPanes(
        pane.image.id,
        data.image,
        [],
        data.deletedItems || [{ path: data.deletedPath, isDirectory: data.deletedDirectory }],
      );
    } else {
      pane.image = data.image;
      await loadDirectory(index);
    }
    toast(isSlot
      ? `${data.slots.length === 1 ? `Slot ${data.slots[0]} is` : `Slots ${data.slots.join(", ")} are`} now empty${data.menuEntriesRemoved
        ? `; ${data.menuEntriesRemoved} associated menu ${data.menuEntriesRemoved === 1 ? "entry" : "entries"} removed`
        : ""}`
      : `${single ? single.name : `${entries.length} items`} deleted${data.menuEntriesRemoved
        ? `; ${data.menuEntriesRemoved} menu ${data.menuEntriesRemoved === 1 ? "entry" : "entries"} removed`
        : ""}`);
  });
}

function createDfsCatalogue(index) {
  const pane = panes[index];
  const existing = new Set(
    pane.path === ""
      ? pane.entries.filter(entry => entry.virtual).map(entry => String(entry.name).toUpperCase())
      : [],
  );
  const prefixes = ["$", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
  const suggested = prefixes.find(prefix => !existing.has(prefix)) || "$";
  showModal(`
    <h2>Choose a DFS catalogue group</h2>
    <p>DFS stores a one-character prefix on each filename rather than a real directory. An empty group cannot be written to disk, so choose the first file that will use it.</p>
    <div class="field"><label>Catalogue prefix</label><select name="prefix">
      ${prefixes.map(prefix => `<option value="${prefix}" ${prefix === suggested ? "selected" : ""}>${prefix}${existing.has(prefix) ? " · already in use" : ""}</option>`).join("")}
    </select></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="create">Choose file</button></div>`,
  async form => {
    const prefix = String(form.get("prefix") || "").toUpperCase();
    if (!/^[$A-Z]$/.test(prefix)) throw new Error("Choose $ or one letter from A to Z.");
    await navigate(index, prefix);
    setTimeout(() => chooseHostFile(index), 0);
  });
}

function createFolder(index) {
  const pane = panes[index];
  showModal(`
    <h2>New ADFS folder</h2><p>Create a directory in <code>${esc(pane.path)}</code>. ADFS names can contain up to ten characters on this image format.</p>
    <div class="field"><label>Folder name</label><input name="name" maxlength="10" required></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="create">Create folder</button></div>`,
  async form => {
    const data = await paneOperation(index, "Creating ADFS folder…", () => api(`/api/images/${pane.image.id}/mkdir`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot: pane.slot, side: pane.side, path: fullPath(pane.path, form.get("name")) })
    }));
    pane.image = data.image;
    await loadDirectory(index);
    toast("Folder created");
  });
}

function chooseHostFile(index) {
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.onchange = () => addSelectedHostFiles(index, [...input.files]);
  input.click();
}

function chooseHostFolder(index) {
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.setAttribute("webkitdirectory", "");
  input.setAttribute("directory", "");
  if (panes[index].image?.kind === "mmb" && panes[index].slot === null) {
    input.accept = ".ssd,.dsd,.hfe,.zip";
  }
  input.onchange = () => {
    const files = [...input.files];
    if (!files.length) return;
    addSelectedHostFolder(index, files.map(file => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
    })));
  };
  input.click();
}

function readDroppedDirectory(entry) {
  const reader = entry.createReader();
  const children = [];
  return new Promise((resolve, reject) => {
    const readBatch = () => reader.readEntries(batch => {
      if (!batch.length) return resolve(children);
      children.push(...batch);
      readBatch();
    }, reject);
    readBatch();
  });
}

async function collectDroppedEntry(entry, parentPath, output) {
  const path = parentPath ? `${parentPath}/${entry.name}` : entry.name;
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    output.push({ file, relativePath: path });
    return;
  }
  if (!entry.isDirectory) return;
  for (const child of await readDroppedDirectory(entry)) {
    await collectDroppedEntry(child, path, output);
  }
}

async function collectDroppedHostFiles(dataTransfer) {
  const entries = [...(dataTransfer.items || [])]
    .filter(item => item.kind === "file")
    .map(item => item.webkitGetAsEntry?.())
    .filter(Boolean);
  if (entries.some(entry => entry.isDirectory)) {
    const output = [];
    for (const entry of entries) await collectDroppedEntry(entry, "", output);
    return output;
  }
  return [...dataTransfer.files].map(file => ({
    file,
    relativePath: file.webkitRelativePath || file.name,
  }));
}

function folderTargetPlans(pane, records, mode) {
  const preserve = mode === "preserve" && pane.image.kind === "adfs";
  const componentNames = new Map();
  const usedByParent = new Map();
  const changes = [];
  const allocate = (parent, original, identity = "") => {
    const mapKey = `${parent}\u0000${original}\u0000${identity}`;
    if (componentNames.has(mapKey)) return componentNames.get(mapKey);
    const rule = targetNameRule(pane, original);
    const used = usedByParent.get(parent) || new Set();
    let candidate = rule.suggested;
    let suffix = 1;
    while (used.has(candidate.toLowerCase())) {
      const tail = String(suffix++);
      candidate = `${rule.suggested.slice(0, rule.limit - tail.length)}${tail}`;
    }
    used.add(candidate.toLowerCase());
    usedByParent.set(parent, used);
    componentNames.set(mapKey, candidate);
    if (candidate !== original) changes.push(`${original} → ${candidate}`);
    return candidate;
  };
  return {
    changes,
    plans: records.map(item => {
      const sourceParts = item.relativePath.replace(/\\/g, "/").split("/").filter(Boolean);
      if (item.metadata?.targetName) sourceParts[sourceParts.length - 1] = item.metadata.targetName;
      const keptParts = preserve ? sourceParts : sourceParts.slice(-1);
      const targetParts = [];
      for (const [partIndex, part] of keptParts.entries()) {
        const parent = targetParts.join("/").toLowerCase();
        const identity = !preserve && partIndex === keptParts.length - 1 ? item.relativePath : "";
        targetParts.push(allocate(parent, part, identity));
      }
      return { ...item, targetPath: targetParts.join("/") };
    }),
  };
}

function ignoredFolderFile(name) {
  const parts = String(name).replace(/\\/g, "/").split("/");
  const leaf = parts.at(-1).toLowerCase();
  return leaf === ".ds_store" || leaf === "thumbs.db" || leaf === "desktop.ini"
    || parts.some(part => part === "__MACOSX");
}

async function prepareHostFolderMetadata(records) {
  const sidecars = new Map();
  for (const item of records.filter(row => /\.inf$/i.test(row.relativePath))) {
    const key = item.relativePath.replace(/\.inf$/i, "").toLowerCase();
    const fields = (await item.file.text()).trim().match(/"[^"]*"|\S+/g) || [];
    sidecars.set(key, {
      targetName: String(fields[0] || "").replace(/^"|"$/g, "").split(".").at(-1),
      load: normaliseHostAddress(fields[1]),
      execute: normaliseHostAddress(fields[2]),
    });
  }
  return records.filter(item => !/\.inf$/i.test(item.relativePath)).map(item => ({
    ...item,
    metadata: {
      ...metadataFromHostFilename(item.file.name),
      ...(sidecars.get(item.relativePath.toLowerCase()) || {}),
    },
  }));
}

async function addSelectedHostFolder(index, records, requestedSlot = null) {
  const pane = panes[index];
  if (!records.length || !pane.image) return;
  const isMmbRoot = pane.image.kind === "mmb" && pane.slot === null;
  const reviewedRecords = isMmbRoot ? records : await prepareHostFolderMetadata(records);
  const relevant = reviewedRecords.filter(item => !ignoredFolderFile(item.relativePath)
    && (!isMmbRoot || formats.isDfsImage(item.file.name)));
  const ignoredCount = records.length - relevant.length;
  if (!relevant.length) {
    return toast(isMmbRoot
      ? "That folder contains no SSD, DSD, HFE or ZIP disk images."
      : "That folder contains no importable files.", true);
  }
  if (isMmbRoot) {
    const selected = selectedEntries(index).find(entry => entry.empty);
    const firstEmpty = pane.entries.find(entry => entry.empty);
    const startSlot = Number.isInteger(requestedSlot) ? requestedSlot : (selected?.slot ?? firstEmpty?.slot);
    if (!Number.isInteger(startSlot)) return toast("This MMB has no empty slot available.", true);
    return showModal(`
      <h2>Insert disk images from folders</h2>
      <p>Acorn File Forge found <strong>${relevant.length}</strong> supported disk image${relevant.length === 1 ? "" : "s"}. They will be flattened from every selected folder and inserted from slot ${startSlot}, using the next suitable empty slots.</p>
      <div class="folder-import-preview">${relevant.slice(0, 12).map(item => `<code>${esc(item.relativePath)}</code>`).join("")}${relevant.length > 12 ? `<small>…and ${relevant.length - 12} more</small>` : ""}</div>
      ${ignoredCount ? `<div class="help-note">${ignoredCount} unrelated, metadata, or unsupported file${ignoredCount === 1 ? "" : "s"} will be ignored.</div>` : ""}
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="import">Insert ${relevant.length} image${relevant.length === 1 ? "" : "s"}</button></div>`,
    () => insertFilesIntoSlots(index, startSlot, relevant.map(item => item.file)));
  }

  const canPreserve = pane.image.kind === "adfs";
  const initialMode = canPreserve ? "preserve" : "flatten";
  const roots = new Set(relevant.map(item => item.relativePath.replace(/\\/g, "/").split("/")[0]));
  const initial = folderTargetPlans(pane, relevant, initialMode);
  const closed = showModal(`
    <h2>Import ${roots.size} folder${roots.size === 1 ? "" : "s"}</h2>
    <p>${relevant.length} file${relevant.length === 1 ? "" : "s"} will be imported into <code>${esc(pane.path)}</code>. Review how host folders should map to the target filing system.</p>
    ${canPreserve ? `<div class="choice-grid folder-import-modes">
      <label><input type="radio" name="folderMode" value="preserve" checked><span><b>Preserve folder structure</b><small>Create the selected folder tree under the current ADFS directory.</small></span></label>
      <label><input type="radio" name="folderMode" value="flatten"><span><b>Import all files here</b><small>Ignore host folders and place every file in the current directory.</small></span></label>
    </div>` : `<input type="hidden" name="folderMode" value="flatten"><div class="help-note">DFS has a flat catalogue. Files from all selected folders will be imported into <strong>${esc(pane.path)}</strong>.</div>`}
    <div class="folder-import-preview" data-folder-preview>${initial.plans.slice(0, 12).map(item => `<code>${esc(item.relativePath)} → ${esc(item.targetPath)}</code>`).join("")}</div>
    ${ignoredCount ? `<div class="help-note">${ignoredCount} metadata sidecar or operating-system housekeeping file${ignoredCount === 1 ? "" : "s"} will not be stored as a separate file.</div>` : ""}
    <label class="check-field"><input type="checkbox" name="replace" value="yes"> Replace ordinary files that already have the same target path</label>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="import">Import ${relevant.length} file${relevant.length === 1 ? "" : "s"}</button></div>`,
  async formValues => {
    const mode = String(formValues.get("folderMode") || initialMode);
    const plan = folderTargetPlans(pane, relevant, mode);
    const form = new FormData();
    plan.plans.forEach(item => form.append("files", item.file));
    form.append("targetPaths", JSON.stringify(plan.plans.map(item => item.targetPath)));
    form.append("metadata", JSON.stringify(plan.plans.map(item => item.metadata || {})));
    form.append("destination", pane.path);
    form.append("mode", mode);
    form.append("replace", formValues.get("replace") === "yes" ? "true" : "false");
    if (pane.slot !== null) form.append("slot", pane.slot);
    if (pane.side !== null) form.append("side", pane.side);
    const data = await paneOperation(index, `Importing ${relevant.length} folder file${relevant.length === 1 ? "" : "s"}…`, () =>
      api(`/api/images/${pane.image.id}/folder-import`, { method: "POST", body: form }));
    if (data.conflicts?.length) {
      throw new Error(`${data.conflicts.length} target file${data.conflicts.length === 1 ? " already exists" : "s already exist"}. Tick “Replace ordinary files” to overwrite: ${data.conflicts.slice(0, 4).join(", ")}${data.conflicts.length > 4 ? "…" : ""}`);
    }
    pane.image = data.image;
    await loadDirectory(index);
    toast(`${data.imported.length} file${data.imported.length === 1 ? "" : "s"} imported`);
  });
  if (canPreserve) {
    modalContent.querySelectorAll('input[name="folderMode"]').forEach(input => {
      input.onchange = () => {
        const plan = folderTargetPlans(pane, relevant, input.value);
        modalContent.querySelector("[data-folder-preview]").innerHTML = plan.plans.slice(0, 12)
          .map(item => `<code>${esc(item.relativePath)} → ${esc(item.targetPath)}</code>`).join("");
      };
    });
  }
  return closed;
}

async function addSelectedHostFiles(index, files) {
  if (!files.length) return;
  const pane = panes[index];
  const preparedFiles = await prepareHostFileMetadata(files);
  if (!preparedFiles.length) return toast("The selection contained metadata sidecars but no data files.", true);
  const batch = { current: 0, total: preparedFiles.length, acceptAll: false, currentMetadata: null };
  pane.actionPending = true;
  renderPane(index);
  try {
    for (const [offset, item] of preparedFiles.entries()) {
      batch.current = offset + 1;
      batch.currentMetadata = item.metadata;
      await importHostFile(index, item.file, false, batch);
      // A raw-image choice replaces its extraction dialog on the next task.
      // Give that replacement time to open and wait for it as part of the
      // current file before moving on to the next selection.
      await new Promise(resolve => setTimeout(resolve, 0));
      if (modal.open) {
        await new Promise(resolve => {
          modal.addEventListener("close", resolve, { once: true });
        });
      }
    }
  } finally {
    if (panes[index] === pane) {
      pane.actionPending = false;
      renderPane(index);
    }
  }
  if (batch.adfsMenuMetadata?.length) {
    await queueAdfsMenuEntries(index, pane.path, batch.adfsMenuMetadata);
  }
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

async function prepareHostFileMetadata(files) {
  const sidecars = new Map();
  for (const file of files.filter(item => /\.inf$/i.test(item.name))) {
    const key = file.name.replace(/\.inf$/i, "").toLowerCase();
    const fields = (await file.text()).trim().match(/"[^"]*"|\S+/g) || [];
    const catalogueName = String(fields[0] || "").replace(/^"|"$/g, "").split(".").at(-1);
    sidecars.set(key, {
      targetName: catalogueName || file.name.replace(/\.inf$/i, ""),
      load: normaliseHostAddress(fields[1]),
      execute: normaliseHostAddress(fields[2]),
    });
  }
  return files.filter(file => !/\.inf$/i.test(file.name)).map(file => ({
    file,
    metadata: {
      ...metadataFromHostFilename(file.name),
      ...(sidecars.get(file.name.toLowerCase()) || {}),
    },
  }));
}

async function importHostFile(index, file, forceRaw = false, batch = null) {
  const pane = panes[index];
  if (!pane.image || (pane.image.kind === "mmb" && pane.slot === null)) return toast("Open a disk first.", true);
  if (!forceRaw && pane.image.kind === "adfs" && formats.isImportableImage(file.name)) {
    return promptImageExtraction(index, file, batch);
  }
  const detected = batch?.currentMetadata || metadataFromHostFilename(file.name);
  const nameRule = targetNameRule(pane, detected.targetName || file.name);
  if (batch?.acceptAll) {
    return addHostFileWithPlan(index, file, {
      targetName: nameRule.suggested,
      load: detected.load,
      execute: detected.execute,
      filetype: detected.filetype,
    });
  }
  const batchLabel = batch?.total > 1
    ? `<p class="batch-position">Selected file ${batch.current} of ${batch.total}</p>`
    : "";
  const canApplyAll = batch?.total > batch?.current;
  const closed = showModal(`
    <h2>Add ${esc(file.name)}</h2>${batchLabel}<p>${nameRule.valid ? "Choose the target filename and optional Acorn metadata." : `${esc(file.name)} is not a legal ${nameRule.label} filename, so a safe replacement has been suggested.`}</p>
    <div class="field"><label>Target filename · max ${nameRule.limit} characters</label>
      <input name="targetName" maxlength="${nameRule.limit}" value="${esc(nameRule.suggested)}" required></div>
    <div class="field"><label>Load address (for example 0x1900)</label><input name="load" value="${esc(detected.load || "")}" placeholder="0xFFFF"></div>
    <div class="field"><label>Execute address</label><input name="execute" value="${esc(detected.execute || "")}" placeholder="0xFFFF"></div>
    ${pane.image.kind === "adfs" ? '<div class="field"><label>RISC OS filetype</label><input name="filetype" placeholder="Text or 0xFFF"></div>' : ""}
    <input type="hidden" name="applyRemaining" value="no">
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button>${canApplyAll ? '<button class="button ghost apply-import-all" value="add">Add and apply to all remaining</button>' : ""}<button class="button primary" value="add">Add file</button></div>`,
  async formValues => {
    const plan = Object.fromEntries(["targetName", "load", "execute", "filetype"]
      .map(key => [key, formValues.get(key)]));
    if (batch && formValues.get("applyRemaining") === "yes") {
      batch.acceptAll = true;
    }
    return addHostFileWithPlan(index, file, plan);
  });
  modalContent.querySelector(".apply-import-all")?.addEventListener("click", () => {
    modalContent.querySelector('[name="applyRemaining"]').value = "yes";
  });
  return closed;
}

async function addHostFileWithPlan(index, file, plan) {
  const pane = panes[index];
  const form = new FormData();
  form.append("file", file);
  form.append("destination", pane.path);
  form.append("targetName", plan.targetName);
  if (pane.slot !== null) form.append("slot", pane.slot);
  if (pane.side !== null) form.append("side", pane.side);
  for (const key of ["load", "execute", "filetype"]) if (plan[key]) form.append(key, plan[key]);
  const data = await paneOperation(index, "Adding file to image…", () =>
    api(`/api/images/${pane.image.id}/files`, { method: "POST", body: form }));
  pane.image = data.image;
  await loadDirectory(index);
  toast(`${file.name} added`);
}

async function promptImageExtraction(index, file, batch = null) {
  const pane = panes[index];
  const upload = new FormData();
  upload.append("image", file);
  upload.append("targetHardware", "auto");
  setLoading(index, true, `Uploading ${file.name} for preview…`);
  let prepared;
  try {
    const opened = await uploadApi("/api/images", upload, {
      onProgress: (loaded, total) => setLoading(
        index,
        true,
        `Uploading ${file.name} for preview${total ? ` · ${Math.round(loaded * 100 / total)}%` : ""}`
      ),
      onProcessing: () => setLoading(index, true, `Reading ${file.name} contents…`),
    });
    prepared = opened.image;
    const preview = await api(`/api/images/${prepared.id}/preview`);
    const rule = targetNameRule(pane, formats.stem(file.name));
    let sourceConsumed = false;
    if (batch?.acceptAll) {
      const stored = batch.imagePlan || { storageMethod: "extract", targetPath: pane.path, createDirectory: false, addMenu: false };
      if (stored.storageMethod === "raw") {
        await api(`/api/images/${prepared.id}`, { method: "DELETE" });
        sourceConsumed = true;
        return addHostFileWithPlan(index, file, { targetName: targetNameRule(pane, file.name).suggested });
      }
      const plan = {
        targetPath: stored.targetPath || pane.path,
        createDirectory: Boolean(stored.createDirectory),
        directoryName: stored.createDirectory ? rule.suggested : null,
        addMenu: Boolean(stored.addMenu),
      };
      const result = await extractPreparedHostImage(index, prepared, file.name, plan, batch);
      await api(`/api/images/${prepared.id}`, { method: "DELETE" });
      sourceConsumed = true;
      return result;
    }
    const closed = showImageExtractionPlan(index, {
      heading: `Import ${file.name}`,
      sourceName: file.name,
      preview,
      suggestedName: rule.suggested,
      allowRaw: true,
      batch,
      submitLabel: "Continue",
      onRaw: async choice => {
        if (batch && choice?.applyAll) {
          batch.acceptAll = true;
          batch.imagePlan = { storageMethod: "raw" };
        }
        await api(`/api/images/${prepared.id}`, { method: "DELETE" });
        sourceConsumed = true;
        if (choice?.applyAll) {
          return addHostFileWithPlan(index, file, { targetName: targetNameRule(pane, file.name).suggested });
        }
        setTimeout(() => importHostFile(index, file, true, batch), 0);
      },
      onExtract: async plan => {
        if (batch && plan.applyAll) {
          batch.acceptAll = true;
          batch.imagePlan = { ...plan, storageMethod: "extract", directoryName: null, applyAll: undefined };
        }
        const result = await extractPreparedHostImage(index, prepared, file.name, plan, batch);
        await api(`/api/images/${prepared.id}`, { method: "DELETE" })
          .then(() => { sourceConsumed = true; })
          .catch(() => {});
        return result;
      },
    });
    closed.then(() => {
      if (!sourceConsumed) api(`/api/images/${prepared.id}`, { method: "DELETE" }).catch(() => {});
    });
    return closed;
  } catch (error) {
    if (prepared) await api(`/api/images/${prepared.id}`, { method: "DELETE" }).catch(() => {});
    toast(`Could not preview ${file.name}: ${error.message}`, true);
  } finally {
    pane.loading = false;
    pane.loadingMessage = "";
    renderPane(index);
  }
}

function extractionPreviewMarkup(preview) {
  const rows = preview.entries || [];
  return `
    <div class="image-import-preview">
      <div class="image-import-preview-head"><strong>Image contents</strong><span>${esc(preview.summary || `${rows.length} item(s)`)}</span></div>
      <div class="image-import-preview-list">
        ${rows.length ? rows.map(item => `
          <div class="image-import-preview-row">
            <span class="preview-kind">${item.type === "dir" ? "▣" : item.type === "disk" ? "▤" : "□"}</span>
            <span><b>${esc(item.name)}</b><small>${esc(item.path || "$")}${item.detail ? ` · ${esc(item.detail)}` : ""}</small></span>
            <em>${item.size == null ? "" : humanSize(item.size)}</em>
          </div>`).join("") : '<p class="muted">No files were found in this image.</p>'}
      </div>
      ${preview.truncated ? '<small class="preview-truncated">Preview limited to the first 500 objects.</small>' : ""}
    </div>`;
}

function showImageExtractionPlan(index, options) {
  const pane = panes[index];
  const batchLabel = options.batch?.total > 1
    ? `<p class="batch-position">Selected file ${options.batch.current} of ${options.batch.total}</p>`
    : "";
  const canApplyAll = options.batch?.total > options.batch?.current;
  const closed = showModal(`
    <h2>${esc(options.heading)}</h2>
    ${batchLabel}
    <p>Review the source, then choose where its contents should go. Extraction defaults to the directory currently shown in the pane.</p>
    ${extractionPreviewMarkup(options.preview)}
    ${options.allowRaw ? `<div class="field"><label>Import as</label><select name="storageMethod">
      <option value="extract">Extract the image contents</option>
      <option value="raw">Store the original image as an ordinary file</option>
    </select></div>` : '<input type="hidden" name="storageMethod" value="extract">'}
    <div data-extraction-options>
      <div class="selected-destination"><small>DESTINATION</small><code data-selected-destination>${esc(pane.path)}</code></div>
      <label class="check-field"><input type="checkbox" name="pickDestination" value="yes"> Choose a different existing directory</label>
      <input type="hidden" name="targetPath" value="${esc(pane.path)}">
      <div class="adfs-directory-picker" data-directory-picker hidden>
        <div class="directory-picker-head"><button type="button" class="button ghost picker-up">Up</button><code data-picker-path>${esc(pane.path)}</code></div>
        <div class="directory-picker-list" data-picker-list></div>
      </div>
      <label class="check-field"><input type="checkbox" name="createDirectory" value="yes"> Create a new child directory before extracting</label>
      <div class="field" data-extracted-directory hidden><label>New directory name · max 10 characters</label>
        <input name="directoryName" maxlength="10" value="${esc(options.suggestedName)}" disabled></div>
      <div class="help-note">Existing names are never overwritten. A failed or aborted direct extraction restores the working image.</div>
      <label class="check-field" data-menu-offer><input type="checkbox" name="addMenu" value="yes"> Offer the imported program as an ADFS menu entry</label>
    </div>
    <input type="hidden" name="applyRemaining" value="no">
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button>${canApplyAll ? '<button class="button ghost apply-import-all" value="continue">Continue and apply to all remaining</button>' : ""}<button class="button primary" value="continue">${esc(options.submitLabel)}</button></div>`,
  async form => {
    const applyAll = form.get("applyRemaining") === "yes";
    if (form.get("storageMethod") === "raw") return options.onRaw?.({ applyAll });
    return options.onExtract({
      targetPath: form.get("pickDestination") === "yes" ? form.get("targetPath") : pane.path,
      createDirectory: form.get("createDirectory") === "yes",
      directoryName: form.get("directoryName"),
      addMenu: form.get("addMenu") === "yes",
      applyAll,
    });
  });
  bindImageExtractionPlan(index, Boolean(options.allowRaw));
  modalContent.querySelector(".apply-import-all")?.addEventListener("click", () => {
    modalContent.querySelector('[name="applyRemaining"]').value = "yes";
  });
  return closed;
}

function bindImageExtractionPlan(index, allowRaw) {
  const pane = panes[index];
  const storageMethod = modalContent.querySelector('select[name="storageMethod"]');
  const extractionOptions = modalContent.querySelector("[data-extraction-options]");
  const pickDestination = modalContent.querySelector('input[name="pickDestination"]');
  const targetPath = modalContent.querySelector('input[name="targetPath"]');
  const selectedDestination = modalContent.querySelector("[data-selected-destination]");
  const picker = modalContent.querySelector("[data-directory-picker]");
  const pickerPath = modalContent.querySelector("[data-picker-path]");
  const pickerList = modalContent.querySelector("[data-picker-list]");
  const createDirectory = modalContent.querySelector('input[name="createDirectory"]');
  const directoryField = modalContent.querySelector("[data-extracted-directory]");
  const directoryName = modalContent.querySelector('input[name="directoryName"]');

  const showDirectory = () => {
    directoryField.hidden = !createDirectory.checked;
    directoryName.disabled = !createDirectory.checked;
    directoryName.required = createDirectory.checked;
  };
  const parentOf = path => path === "$" ? "$" : path.slice(0, path.lastIndexOf(".")) || "$";
  const loadPicker = async path => {
    pickerList.innerHTML = '<span class="muted">Reading directories…</span>';
    try {
      const data = await api(`/api/images/${pane.image.id}/tree?path=${encodeURIComponent(path)}`);
      if (!modal.open) return;
      targetPath.value = path;
      selectedDestination.textContent = path;
      pickerPath.textContent = path;
      const directories = data.entries.filter(item => item.type === "dir");
      pickerList.innerHTML = directories.length
        ? directories.map(item => `<button type="button" data-directory-name="${esc(item.name)}"><b>▣</b><span>${esc(item.name)}</span></button>`).join("")
        : '<span class="muted">No child directories here.</span>';
      pickerList.querySelectorAll("[data-directory-name]").forEach(button => {
        button.onclick = () => loadPicker(fullPath(path, button.dataset.directoryName));
      });
    } catch (error) {
      pickerList.innerHTML = `<span class="error-text">${esc(error.message)}</span>`;
    }
  };
  pickDestination.onchange = () => {
    picker.hidden = !pickDestination.checked;
    if (pickDestination.checked) loadPicker(targetPath.value || pane.path);
    else {
      targetPath.value = pane.path;
      selectedDestination.textContent = pane.path;
    }
  };
  modalContent.querySelector(".picker-up").onclick = () => loadPicker(parentOf(targetPath.value));
  createDirectory.onchange = showDirectory;
  if (allowRaw && storageMethod) {
    storageMethod.onchange = () => {
      extractionOptions.hidden = storageMethod.value === "raw";
    };
  }
  showDirectory();
}

async function extractPreparedHostImage(index, sourceImage, sourceName, plan, batch = null) {
  const pane = panes[index];
  const menuRoot = pane.path;
  const destinationLabel = plan.createDirectory ? plan.directoryName : plan.targetPath;
  const data = await trackedPaneOperation(index, `Extracting ${sourceName} into ${destinationLabel}…`, operationId =>
    api("/api/transfer-image-to-directory", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sourceImage: sourceImage.id,
        targetImage: pane.image.id,
        targetPath: plan.targetPath,
        directoryName: plan.directoryName,
        createDirectory: plan.createDirectory,
        addMenu: plan.addMenu,
        operationId,
      }),
    }));
  pane.image = data.image;
  await loadDirectory(index);
  toast(`${sourceName} contents extracted into ${data.path}`);
  if (plan.addMenu && data.metadata) {
    if (batch) (batch.adfsMenuMetadata ||= []).push(data.metadata);
    else setTimeout(() => offerAdfsMenuEntry(index, menuRoot, data.metadata), 0);
  }
}

function selectedLaunchCandidateIndex(metadata) {
  const launchCandidates = metadata.launchCandidates || [];
  let selected = launchCandidates.findIndex(item =>
    item.name.toLowerCase() === String(metadata.filename || "").toLowerCase()
    && item.path === metadata.path);
  if (selected < 0) {
    selected = launchCandidates.findIndex(item =>
      item.name.toLowerCase() === String(metadata.filename || "").toLowerCase());
  }
  return selected < 0 && launchCandidates.length === 1 ? 0 : selected;
}

function launchCandidateOptions(metadata) {
  const launchCandidates = metadata.launchCandidates || [];
  const selected = selectedLaunchCandidateIndex(metadata);
  return `
    <option value="">Choose a file…</option>
    ${launchCandidates.map((item, offset) =>
      `<option value="${offset}" ${offset === selected ? "selected" : ""}>${esc(item.path === metadata.path ? item.name : `${item.path} · ${item.name}`)}</option>`
    ).join("")}`;
}

function hasObviousLaunchCandidate(metadata) {
  return metadata.launchObvious === true && selectedLaunchCandidateIndex(metadata) >= 0;
}

function retryableMenuWrite(index, url, body, progress) {
  return api(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    networkRetries: 3,
    onNetworkRetry: (attempt, total) => {
      const message = `Connection interrupted. Reconnecting before retry ${attempt} of ${total}…`;
      const pane = panes[index];
      pane.loadingMessage = message;
      renderPane(index);
      if (modal.open) {
        setModalProgress({
          ...progress,
          message,
          details: [
            ...(progress.details || []),
            {
              label: "Connection recovery",
              value: `Safe menu retry ${attempt} of ${total}; an existing entry will be replaced, not duplicated`
            }
          ]
        });
      }
    }
  });
}

async function saveAdfsMenuEntry(index, menuRoot, entry, refresh = true) {
  const pane = panes[index];
  const action = { "": "CHAIN", R: "RUN", E: "EXEC", L: "LOAD" }[entry.action] || entry.action;
  const progress = {
    title: `Updating the ADFS menu in ${menuRoot}`,
    message: `Adding “${entry.title}” and rebuilding the menu databases and indexes.`,
    details: [
      { label: "Menu location", value: menuRoot },
      { label: "Program directory", value: entry.path },
      { label: "Launch command", value: `*${action} ${entry.filename}` },
      { label: "Current stage", value: "Writing title and publisher records" }
    ]
  };
  const data = await paneOperation(index, progress, () =>
    retryableMenuWrite(
      index,
      `/api/images/${pane.image.id}/adfs-menu/entry`,
      { root: menuRoot, metadata: entry },
      progress
    ));
  pane.image = data.image;
  if (refresh) await loadDirectory(index);
  toast(`${entry.title} added to the ADFS menu`);
}

async function addDetectedAdfsMenuEntry(index, menuRoot, metadata, refresh = true) {
  const entry = detectedAdfsMenuEntry(metadata);
  if (!entry) {
    reviewAdfsMenuMetadata(index, menuRoot, metadata);
    return;
  }
  await saveAdfsMenuEntry(index, menuRoot, entry, refresh);
}

function detectedAdfsMenuEntry(metadata) {
  const candidate = (metadata.launchCandidates || [])[selectedLaunchCandidateIndex(metadata)];
  if (!candidate) return null;
  return {
    title: metadata.title,
    publisher: metadata.publisher,
    filename: candidate.name,
    action: metadata.action,
    page: metadata.page || "1900",
    path: candidate.path,
    system: "H"
  };
}

async function saveDetectedAdfsMenuEntries(index, menuRoot, metadataItems, refresh = true) {
  const pane = panes[index];
  const entries = metadataItems.map(detectedAdfsMenuEntry).filter(Boolean);
  if (!entries.length) return;
  const progress = {
    title: `Updating the ADFS menu in ${menuRoot}`,
    message: `Writing ${entries.length} entries in one batch and rebuilding each menu database once.`,
    details: [
      { label: "Menu location", value: menuRoot },
      { label: "Entries", value: String(entries.length) },
      { label: "Optimisation", value: "One title and publisher index rebuild for the complete batch" }
    ]
  };
  const data = await paneOperation(index, progress, () =>
    retryableMenuWrite(
      index,
      `/api/images/${pane.image.id}/adfs-menu/entries`,
      { root: menuRoot, metadata: entries },
      progress
    ));
  pane.image = data.image;
  if (refresh) await loadDirectory(index);
  toast(`${entries.length} entries added to the ADFS menu`);
}

async function offerAdfsMenuEntry(index, menuRoot, metadata) {
  try {
    if (hasObviousLaunchCandidate(metadata)) {
      await addDetectedAdfsMenuEntry(index, menuRoot, metadata);
      await showMenuPreview(index, metadata.path || metadata.title);
      return;
    }
    reviewAdfsMenuMetadata(index, menuRoot, metadata);
  } catch (error) {
    toast(`Could not update the ADFS menu: ${error.message}`, true);
  }
}

async function reviewAdfsMenuMetadata(index, menuRoot, metadata, previewAfter = true, batch = null) {
  const matches = metadata.matches || [];
  const evidence = [...(metadata.evidence || []), ...(metadata.warnings || [])];
  const launchCandidates = metadata.launchCandidates || [];
  let recommendedPage = metadata.page;
  if (batch?.acceptAll) {
    const entry = detectedAdfsMenuEntry(metadata);
    if (entry) {
      await saveAdfsMenuEntry(index, menuRoot, entry, false);
      return false;
    }
  }
  const canApplyAll = batch?.total > batch?.current;
  const closed = showModal(`
    <h2>Add directory to ADFS menu</h2>
    <p>Review the extracted program’s launch details before the menu in ${esc(menuRoot)} is updated. Confidence: ${metadata.confidence}%.</p>
    ${matches.length ? `<div class="field"><label>Online matches</label><select name="match">
      <option value="">Keep the detected values</option>
      ${matches.map((item, offset) => `<option value="${offset}">${esc(item.title)}${item.publisher ? ` · ${esc(item.publisher)}` : ""}</option>`).join("")}
    </select></div>` : ""}
    <div class="field"><label>Display title</label><input name="title" value="${esc(metadata.title)}" required></div>
    <div class="field"><label>Publisher</label><input name="publisher" value="${esc(metadata.publisher)}"></div>
    <div class="menu-fields">
      <div class="field"><label>Launch file</label><select name="launchCandidate" required>
        ${launchCandidateOptions(metadata)}
      </select></div>
      <div class="field"><label>Action</label><select name="action">
        <option value="" ${metadata.action === "" ? "selected" : ""}>CHAIN</option>
        <option value="R" ${metadata.action === "R" ? "selected" : ""}>RUN</option>
        <option value="E" ${metadata.action === "E" ? "selected" : ""}>EXEC</option>
        <option value="L" ${metadata.action === "L" ? "selected" : ""}>LOAD</option>
      </select></div>
      <div class="field"><label>PAGE</label><input name="page" maxlength="4" value="${esc(metadata.page || "1900")}" required></div>
    </div>
    <div class="field"><label>ADFS directory</label><input name="path" value="${esc(metadata.path)}" readonly></div>
    ${evidence.length ? `<div class="scan-notes">${evidence.map(item => `<span>${esc(item)}</span>`).join("")}</div>` : ""}
    <input type="hidden" name="applyRemaining" value="no">
    <div class="modal-actions"><button class="button ghost" value="cancel">Keep off-menu</button>${canApplyAll ? '<button class="button ghost apply-menu-all" value="save">Update and accept all remaining</button>' : ""}<button class="button primary" value="save">Update menu</button></div>`,
  async form => {
    const matchValue = form.get("match");
    const selectedMatch = matchValue === "" || matchValue === null ? null : matches[Number(matchValue)];
    const candidate = launchCandidates[Number(form.get("launchCandidate"))];
    if (!candidate) throw new Error("Choose a launch file before updating the menu.");
    if (!await confirmPageOverride(recommendedPage, form.get("page"), metadata.title)) return false;
    const entry = {
      title: selectedMatch?.title || form.get("title"),
      publisher: selectedMatch?.publisher || form.get("publisher"),
      filename: candidate.name,
      action: form.get("action"),
      page: form.get("page"),
      path: candidate.path,
      system: "H"
    };
    if (batch && form.get("applyRemaining") === "yes") batch.acceptAll = true;
    await saveAdfsMenuEntry(index, menuRoot, entry);
    if (previewAfter) previewMenuAfterCurrentDialog(index, entry.path || entry.title);
  });
  modalContent.querySelector(".apply-menu-all")?.addEventListener("click", () => {
    modalContent.querySelector('[name="applyRemaining"]').value = "yes";
  });
  const matchSelect = modalContent.querySelector('[name="match"]');
  const candidateSelect = modalContent.querySelector('[name="launchCandidate"]');
  candidateSelect?.addEventListener("change", () => {
    const candidate = launchCandidates[Number(candidateSelect.value)];
    if (!candidate?.page) return;
    recommendedPage = candidate.page;
    const pageInput = modalContent.querySelector('[name="page"]');
    pageInput.value = candidate.page;
    pageInput.title = `Recommended from ${candidate.path}.${candidate.name} in the image`;
  });
  matchSelect?.addEventListener("change", () => {
    if (matchSelect.value === "") return;
    const selected = matches[Number(matchSelect.value)];
    modalContent.querySelector('[name="title"]').value = selected.title;
    modalContent.querySelector('[name="publisher"]').value = selected.publisher;
  });
  return Boolean(closed);
}

function setWorkspaceClipboard(index, mode) {
  const pane = panes[index];
  const items = clipboardItemsForPane(index);
  if (!items.length) return toast("Select one or more files, directories, or formatted MMB slots first.", true);
  clearWorkspaceClipboard("", false);
  workspaceClipboard = {
    mode,
    kind: pane.image.kind === "mmb" && pane.slot === null ? "mmb-slots" : "files",
    items,
    sourceImage: pane.image.id,
    sourceName: pane.image.name,
    createdAt: Date.now(),
  };
  panes.forEach((_item, paneIndex) => renderPane(paneIndex, true));
  toast(`${items.length} item${items.length === 1 ? "" : "s"} ${mode === "cut" ? "cut" : "copied"}. Choose a destination and paste.`);
}

async function refreshClipboardImages(imageIds) {
  for (let index = 0; index < panes.length; index += 1) {
    if (!imageIds.has(panes[index].image?.id)) continue;
    await refreshCurrentView(index, true);
  }
}

function mmbPasteConflictDecision(conflicts) {
  return new Promise(resolve => {
    let submitted = false;
    const closed = showModal(`
      <h2>Replace occupied MMB slots?</h2>
      <p>${conflicts.length} destination slot${conflicts.length === 1 ? " is" : "s are"} already occupied. Replacing removes those complete disk images and their menu records.</p>
      <div class="clipboard-conflicts">${conflicts.map(item => `<span><b>Slot ${item.slot}</b>${esc(item.name)}</span>`).join("")}</div>
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel paste</button><button class="button danger" value="replace">Replace and paste</button></div>`,
    () => { submitted = true; resolve(true); });
    closed.then(() => { if (!submitted) resolve(false); });
  });
}

async function pasteMmbSlots(index, clipboard, targetSlot = null) {
  const pane = panes[index];
  const destination = targetSlot === null
    ? selectedEntry(index)
    : pane.entries.find(entry => entry.type === "disk" && Number(entry.slot) === Number(targetSlot));
  if (!destination) {
    toast("Select the first destination MMB slot, then choose Paste.", true);
    return false;
  }
  const request = async replace => api(`/api/images/${pane.image.id}/slots/paste`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sourceImage: clipboard.sourceImage,
      sourceSlots: clipboard.items.map(item => item.slot),
      targetStart: Number(destination.slot),
      cut: clipboard.mode === "cut",
      replace,
    }),
  });
  let data = await request(false);
  if (data.noChange) {
    toast("Those slots are already at that position.");
    return false;
  }
  if (!data.pasted && data.conflicts?.length) {
    const replace = await mmbPasteConflictDecision(data.conflicts);
    if (!replace) return false;
    data = await request(true);
  }
  if (!data.pasted) return false;
  pane.image = data.image;
  const affected = new Set([pane.image.id, clipboard.sourceImage]);
  await refreshClipboardImages(affected);
  setSelection(panes[index], data.targetSlots.map(String), String(data.targetSlots[0]));
  renderPane(index, true);
  toast(`${data.targetSlots.length} MMB disk${data.targetSlots.length === 1 ? "" : "s"} ${clipboard.mode === "cut" ? "moved" : "copied"}`);
  return true;
}

async function deleteCutFileSources(clipboard) {
  const first = clipboard.items[0];
  const data = await api(`/api/images/${first.image}/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      slot: first.slot,
      side: first.side,
      items: clipboard.items.map(item => ({ path: item.path, recursive: item.recursive })),
    }),
  });
  await refreshClipboardImages(new Set([first.image]));
  return data;
}

async function ejectCutMmbSources(clipboard, copiedSources) {
  if (!copiedSources.length) return;
  const slots = copiedSources.map(source => Number(source.slot));
  await api(`/api/images/${clipboard.sourceImage}/slots/clear`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slots }),
  });
  await refreshClipboardImages(new Set([clipboard.sourceImage]));
  toast(`${slots.length} source MMB slot${slots.length === 1 ? "" : "s"} ejected after extraction.`);
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
      if (disk && side + 1 < sidesPerDisk) {
        side += 1;
      } else {
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

function buildMmbDisksFromClipboard(index, clipboard) {
  const pane = panes[index];
  const destination = selectedEntry(index);
  if (!destination || destination.type !== "disk" || !destination.empty) {
    toast("Select the first empty MMB slot for the generated disk or disks.", true);
    return false;
  }
  if (clipboard.items.some(item => item.recursive)) {
    toast("DFS disks cannot contain folders. Open the folder and copy its files instead.", true);
    return false;
  }
  const prepared = uniqueDfsNames(clipboard.items);
  const prefixes = ["$", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ"];
  let initialPlan;
  try {
    initialPlan = allocateFilesToDfsDisks(prepared, "ssd");
  } catch (error) {
    toast(error.message, true);
    return false;
  }
  return new Promise(resolve => {
    let submitted = false;
    const closed = showModal(`
      <div class="dfs-build-planner">
        <h2>Build DFS disks in the MMB</h2>
        <p>Loose files must first be assembled into complete DFS images. Files are packed in order, with no more than 31 catalogue entries or 798 data sectors on each side.</p>
        <div class="field"><label>Disk format</label><select name="diskFormat"><option value="ssd">SSD · one 200 KiB side per slot</option><option value="dsd">DSD · two sides across two slots</option></select></div>
        <div class="field"><label>Disk title prefix · max 8 characters</label><input name="titlePrefix" maxlength="8" value="FILES" required></div>
        <div class="dfs-build-summary" aria-live="polite"><b>${initialPlan.length} SSD disk${initialPlan.length === 1 ? "" : "s"}</b><span>Starting at slot ${destination.slot}</span></div>
        <div class="transfer-name-list">
          ${prepared.map((item, itemIndex) => `<div class="dfs-build-row" data-build-row="${itemIndex}">
            <label title="${esc(item.path)}">${esc(item.name)}<small class="dfs-build-allocation"></small></label>
            <select name="prefix${itemIndex}" aria-label="DFS catalogue group for ${esc(item.name)}">${prefixes.map(prefix => `<option value="${prefix}" ${prefix === item.prefix ? "selected" : ""}>${prefix}</option>`).join("")}</select>
            <input name="targetName${itemIndex}" maxlength="7" value="${esc(item.targetName)}" aria-label="DFS filename for ${esc(item.name)}" required>
          </div>`).join("")}
        </div>
        <div class="help-note"><strong>DFS naming:</strong> the one-character group and seven-character filename are editable. ADFS directories are not copied because DFS is flat.</div>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="build">Build and paste</button></div>
      </div>`,
    async form => {
      submitted = true;
      const diskFormat = form.get("diskFormat");
      const namedItems = prepared.map((item, itemIndex) => ({
        ...item,
        prefix: form.get(`prefix${itemIndex}`),
        targetName: form.get(`targetName${itemIndex}`),
      }));
      const disks = allocateFilesToDfsDisks(namedItems, diskFormat);
      const titlePrefix = String(form.get("titlePrefix") || "FILES").trim();
      const data = await api(`/api/images/${pane.image.id}/slots/build-from-files`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceImage: clipboard.sourceImage,
          sourceSlot: clipboard.items[0].slot,
          sourceSide: clipboard.items[0].side,
          targetStart: Number(destination.slot),
          format: diskFormat,
          disks: disks.map((disk, diskIndex) => ({
            title: `${titlePrefix}${diskIndex + 1}`.slice(0, 12),
            files: disk.files.map(item => ({
              sourcePath: item.path,
              targetName: item.targetName,
              prefix: item.prefix,
              targetSide: item.targetSide,
            })),
          })),
        }),
      });
      pane.image = data.image;
      await refreshClipboardImages(new Set([pane.image.id]));
      if (clipboard.mode === "cut") await deleteCutFileSources(clipboard);
      setSelection(panes[index], data.slots.map(String), String(data.slots[0]));
      renderPane(index, true);
      toast(`${disks.length} DFS disk image${disks.length === 1 ? "" : "s"} built in ${data.slots.length} MMB slot${data.slots.length === 1 ? "" : "s"}`);
      resolve(true);
      return true;
    });
    const updatePlan = () => {
      const format = modalContent.querySelector('[name="diskFormat"]').value;
      try {
        const plan = allocateFilesToDfsDisks(prepared, format);
        const slotsNeeded = plan.length * (format === "dsd" ? 2 : 1);
        modalContent.querySelector(".dfs-build-summary").innerHTML = `<b>${plan.length} ${format.toUpperCase()} disk${plan.length === 1 ? "" : "s"}</b><span>Slots ${destination.slot} to ${Number(destination.slot) + slotsNeeded - 1}</span>`;
        plan.forEach((disk, diskIndex) => disk.files.forEach(item => {
          const itemIndex = prepared.findIndex(candidate => candidate.path === item.path);
          const side = format === "dsd" ? ` · side ${item.targetSide === 2 ? 2 : 0}` : "";
          modalContent.querySelector(`[data-build-row="${itemIndex}"] .dfs-build-allocation`).textContent = `Disk ${diskIndex + 1}${side}`;
        }));
      } catch (error) {
        modalContent.querySelector(".dfs-build-summary").textContent = error.message;
      }
    };
    modalContent.querySelector('[name="diskFormat"]').addEventListener("change", updatePlan);
    updatePlan();
    closed.then(() => { if (!submitted) resolve(false); });
  });
}

async function pasteFileItems(index, clipboard) {
  const pane = panes[index];
  if (pane.image.kind === "mmb" && pane.slot === null) {
    return buildMmbDisksFromClipboard(index, clipboard);
  }
  if (isDfsPane(pane) && pane.path === "") {
    toast("Open $, A-Z, or another DFS catalogue group before pasting files.", true);
    return false;
  }
  if (isDfsPane(pane) && clipboard.items.some(item => item.recursive)) {
    toast("DFS cannot contain directories. Open the source directory and copy its files instead.", true);
    return false;
  }
  const sameImage = clipboard.items.every(item => item.image === pane.image.id);
  const success = await transferFiles(index, clipboard.items);
  if (!success) return false;
  const movedInternally = sameImage && (
    pane.image.kind === "adfs" || (isDfsPane(pane) && clipboard.items.every(item => !item.recursive))
  );
  if (clipboard.mode === "cut" && !movedInternally) {
    await deleteCutFileSources(clipboard);
    toast(`${clipboard.items.length} source item${clipboard.items.length === 1 ? "" : "s"} removed after paste.`);
  }
  return true;
}

async function pasteWorkspaceClipboard(index) {
  if (!workspaceClipboard) return;
  const clipboard = workspaceClipboard;
  clipboardMutationInProgress = true;
  try {
    let success = false;
    const pane = panes[index];
    if (clipboard.kind === "mmb-slots") {
      if (pane.image.kind === "mmb" && pane.slot === null) {
        success = await pasteMmbSlots(index, clipboard);
      } else if (pane.image.kind === "adfs") {
        const afterCopy = clipboard.mode === "cut"
          ? copied => ejectCutMmbSources(clipboard, copied)
          : null;
        success = Boolean(await (clipboard.items.length > 1
          ? copyMmbSlotsToAdfs(index, clipboard.items, afterCopy)
          : copyMmbSlotToAdfs(index, clipboard.items[0], afterCopy)));
      } else {
        toast("Complete MMB disks can be pasted into an MMB or extracted into ADFS.", true);
      }
    } else {
      success = await pasteFileItems(index, clipboard);
    }
    return success;
  } catch (error) {
    toast(error.message, true);
    return false;
  } finally {
    clipboardMutationInProgress = false;
    clearWorkspaceClipboard("", true);
  }
}

async function transferFiles(targetIndex, sources, targetPath = null) {
  const target = panes[targetIndex];
  if (!target.image || (target.image.kind === "mmb" && target.slot === null)) return toast("Open a destination disk first.", true);
  if (!Array.isArray(sources) || !sources.length) return;
  const destination = targetPath || target.path;
  const movingWithinAdfs = target.image.kind === "adfs"
    && sources.every(source => source.image === target.image.id);
  if (movingWithinAdfs) {
    return performAdfsMoves(targetIndex, sources, destination);
  }
  const movingWithinDfs = isDfsPane(target)
    && destination !== ""
    && sources.every(source => source.image === target.image.id && !source.recursive);
  if (movingWithinDfs) {
    return performDfsMoves(targetIndex, sources, destination);
  }
  if (sources.some(source => source.pane === targetIndex)) {
    return toast("Files can only be moved within the same ADFS image.", true);
  }
  const transfers = sources.map((source, index) => ({
    source,
    index,
    rule: targetNameRule(target, source.name)
  }));
  if (transfers.some(item => !item.rule.valid)) {
    return new Promise(resolve => {
      let submitted = false;
      const closed = showModal(`
      <div class="transfer-batch">
        <h2>Check destination names</h2>
        <p>Names must follow the destination filesystem’s rules. Suggested replacements are ready for any incompatible names.</p>
        <div class="transfer-name-list">
          ${transfers.map(item => `<div class="field">
            <label>${esc(item.source.name)} · max ${item.rule.limit} characters</label>
            <input name="targetName${item.index}" maxlength="${item.rule.limit}" value="${esc(item.rule.valid ? item.source.name : item.rule.suggested)}" required>
          </div>`).join("")}
        </div>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="copy">Copy ${transfers.length} item${transfers.length === 1 ? "" : "s"}</button></div>
      </div>`,
      async form => {
        submitted = true;
        const result = await performTransfers(targetIndex, transfers.map(item => ({
          ...item.source,
          targetName: form.get(`targetName${item.index}`)
        })), destination);
        resolve(result);
        return result;
      });
      closed.then(() => { if (!submitted) resolve(false); });
    });
  }
  return performTransfers(
    targetIndex,
    sources.map(source => ({ ...source, targetName: source.name })),
    destination,
  );
}

async function performDfsMoves(targetIndex, sources, destination) {
  const target = panes[targetIndex];
  const items = sources
    .map(source => ({
      source: source.path,
      destination: fullPath(destination, source.name),
    }))
    .filter(item => item.source.toLowerCase() !== item.destination.toLowerCase());
  if (!items.length) { toast("Those files are already in this catalogue group."); return false; }
  try {
    const data = await paneOperation(
      targetIndex,
      items.length === 1 ? `Moving ${sources[0].name}…` : `Moving ${items.length} DFS files…`,
      () => api(`/api/images/${target.image.id}/move-dfs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot: target.slot, side: target.side, items }),
      }),
    );
    for (let index = 0; index < panes.length; index += 1) {
      if (panes[index].image?.id !== target.image.id) continue;
      panes[index].image = data.image;
      await loadDirectory(index);
    }
    toast(`${items.length} file${items.length === 1 ? "" : "s"} moved to catalogue ${destination}`);
    return true;
  } catch (error) {
    toast(error.message, true);
    return false;
  }
}

async function performAdfsMoves(targetIndex, sources, destination) {
  const target = panes[targetIndex];
  const items = sources
    .map(source => ({
      source: source.path,
      destination: fullPath(destination, source.name),
    }))
    .filter(item => item.source.toLowerCase() !== item.destination.toLowerCase());
  if (!items.length) { toast("Those items are already in this directory."); return false; }
  setLoading(
    targetIndex,
    true,
    items.length === 1
      ? `Moving ${sources[0].name}…`
      : `Moving ${items.length} selected items…`,
  );
  try {
    const data = await api(`/api/images/${target.image.id}/move`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });
    await refreshSharedAdfsPanes(target.image.id, data.image, data.moved);
    const menuMessage = data.menuEntriesUpdated
      ? `; ${data.menuEntriesUpdated} menu ${data.menuEntriesUpdated === 1 ? "entry" : "entries"} updated`
      : "";
    toast(`${items.length} item${items.length === 1 ? "" : "s"} moved${menuMessage}`);
    return true;
  } catch (error) {
    target.loading = false;
    renderPane(targetIndex);
    toast(error.message, true);
    return false;
  }
}

async function refreshSharedAdfsPanes(imageId, image, moves = [], deleted = null) {
  const directoryMoves = [...moves]
    .filter(move => move.isDirectory)
    .sort((left, right) => right.source.length - left.source.length);
  for (let index = 0; index < panes.length; index += 1) {
    const pane = panes[index];
    if (pane.image?.id !== imageId) continue;
    for (const move of directoryMoves) {
      if (pane.path.toLowerCase() === move.source.toLowerCase()) {
        pane.path = move.destination;
        break;
      }
      if (pane.path.toLowerCase().startsWith(`${move.source}.`.toLowerCase())) {
        pane.path = move.destination + pane.path.slice(move.source.length);
        break;
      }
    }
    const deletedItems = Array.isArray(deleted) ? deleted : deleted ? [deleted] : [];
    const deletedAncestor = deletedItems.find(item =>
      item.isDirectory
      && (
        pane.path.toLowerCase() === item.path.toLowerCase()
        || pane.path.toLowerCase().startsWith(`${item.path}.`.toLowerCase())
      )
    );
    if (deletedAncestor) {
      pane.path = parentPath(deletedAncestor.path);
    }
    pane.image = image;
    await loadDirectory(index);
  }
}

async function performTransfers(targetIndex, transfers, destination = null) {
  const target = panes[targetIndex];
  const targetDirectory = destination || target.path;
  setLoading(targetIndex, true, transfers.length === 1 ? "Copying between images…" : `Copying 1 of ${transfers.length}…`);
  try {
    for (const [index, transfer] of transfers.entries()) {
      target.loadingMessage = transfers.length === 1
        ? `Copying ${transfer.name}…`
        : `Copying ${index + 1} of ${transfers.length}: ${transfer.name}…`;
      target.progressCurrent = index;
      target.progressTotal = transfers.length;
      renderPane(targetIndex);
      const data = await api("/api/transfer", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceImage: transfer.image, sourceSlot: transfer.slot, sourcePath: transfer.path,
          sourceSide: transfer.side,
          targetImage: target.image.id, targetSlot: target.slot, targetSide: target.side,
          targetPath: fullPath(targetDirectory, transfer.targetName),
          recursive: transfer.recursive
        })
      });
      target.image = data.image;
      target.progressCurrent = index + 1;
    }
    target.progressCurrent = null;
    target.progressTotal = null;
    await loadDirectory(targetIndex);
    toast(transfers.length === 1
      ? `${transfers[0].name} copied as ${transfers[0].targetName}`
      : `${transfers.length} items copied`);
    return true;
  } catch (error) {
    target.loading = false;
    target.progressCurrent = null;
    target.progressTotal = null;
    renderPane(targetIndex);
    toast(error.message, true);
    return false;
  }
}

async function setSelectedAccess(index, writable) {
  const pane = panes[index];
  if (pane.image.kind === "mmb" && pane.slot === null) {
    return setSelectedSlotsWritable(index, writable);
  }
  const entries = selectedEntries(index);
  if (!entries.length) return toast("Select one or more files or directories.", true);
  const paths = entries.map(entry => fullPath(pane.path, entry.name));
  try {
    const data = await paneOperation(index, `Marking ${entries.length} item${entries.length === 1 ? "" : "s"} ${writable ? "read / write" : "read-only"}…`, () => api(`/api/images/${pane.image.id}/lock`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot: pane.slot, side: pane.side, paths, unlock: writable })
    }));
    pane.image = data.image;
    await loadDirectory(index, true);
    toast(`${entries.length} item${entries.length === 1 ? "" : "s"} marked ${writable ? "read / write" : "read-only"}`);
  } catch (error) { toast(error.message, true); }
}

async function validateImage(index) {
  const pane = panes[index];
  if (pane.image.kind === "mmb" && pane.slot === null) return toast("Select an MMB disk to check.");
  try {
    const data = await paneOperation(index, "Checking filesystem structure…", () => api(`/api/images/${pane.image.id}/validate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot: pane.slot })
    }));
    toast(data.message);
  } catch (error) { toast(error.message, true); }
}

function triggerImageDownload(url) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  link.hidden = true;
  document.body.append(link);
  link.click();
  setTimeout(() => link.remove(), 1000);
}

function showDownloadReady(image, url) {
  modal.classList.remove("busy", "failed");
  showModal(`
    <div class="modal-heading"><span class="modal-kicker">SAVE IMAGE</span><h2>Your download is ready</h2></div>
    <p>The timestamped ZIP contains <strong>${esc(image.name)}</strong>, its matching DSC file when required, and a technical README.</p>
    <div class="help-note"><strong>Did the automatic download not appear?</strong> Select Download ZIP below. This direct link remains available until you close this message.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Close</button><a class="button primary download-ready-link" href="${esc(url)}" download>Download ZIP</a></div>
  `, null, { replace: modal.open });
  modalContent.querySelector(".download-ready-link").onclick = () => {
    toast("Download requested. Check the browser download list if it does not appear immediately.");
  };
}

function applySavedImageSummary(image) {
  panes.forEach((candidate, candidateIndex) => {
    if (candidate.image?.id !== image.id) return;
    candidate.image = image;
    renderPane(candidateIndex, true);
  });
}

async function saveImage(index) {
  const pane = panes[index];
  const existingDialog = modal.open;
  try {
    if (!existingDialog) {
      showModal('<div class="analysis-loading"><span class="modal-progress-icon">↻</span><h2>Preparing download</h2></div>');
      modal.classList.add("busy");
      setModalProgress({
        title: pane.image.hasDescriptor ? "Preparing DAT + DSC download" : "Preparing image download",
        message: "Starting hardware and filesystem checks…",
        details: [
          { label: "Stages", value: "Validate, checksum, catalogue, then build the complete ZIP" },
          { label: "Ready means ready", value: "The download starts only after the ZIP has finished building" },
        ],
      }, 0, 100);
    }
    const data = await trackedPaneOperation(
      index,
      pane.image.hasDescriptor ? "Validating DAT + DSC before download…" : "Validating image before download…",
      operationId => api(`/api/images/${pane.image.id}/download/prepare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operationId }),
      })
    );
    if (!existingDialog && modal.open) {
      setModalProgress({
        title: "Download ZIP complete",
        message: "The complete timestamped ZIP is ready for the browser.",
        details: [{ label: "Status", value: "Checksums, README and every image file are included" }]
      }, 100, 100);
      await new Promise(resolve => setTimeout(resolve, 250));
    }
    applySavedImageSummary(data.image);
    const downloadUrl = `/api/images/${pane.image.id}/download`;
    triggerImageDownload(downloadUrl);
    if (!existingDialog) showDownloadReady(pane.image, downloadUrl);
    toast("Complete timestamped image and README ZIP download started.");
    return true;
  } catch (error) {
    if (!existingDialog && modal.open) modal.close();
    toast(`Could not save ${pane.image.name}: ${error.message}`, true);
    return false;
  }
}

async function recoverPreviousSession(index) {
  try {
    const data = await api("/api/images/recoverable");
    const openIds = new Set(panes.map(pane => pane.image?.id).filter(Boolean));
    const recoverable = data.images.filter(image => !openIds.has(image.id));
    const options = recoverable.map((image, position) => {
      const modified = new Date(image.modified).toLocaleString();
      const pair = image.hasDescriptor ? " · DAT + DSC" : "";
      const selected = position === 0 ? " selected" : "";
      return `<option value="${esc(image.id)}"${selected}>${esc(image.name)} · ${esc(humanSize(image.size))}${pair} · ${esc(modified)}</option>`;
    }).join("");
    const emptyMessage = recoverable.length
      ? ""
      : '<div class="help-note no-recovery-sessions">No previous sessions belonging to this browser are currently available.</div>';
    const modalClosed = showModal(`
      <h2>Recover previous session</h2>
      <p>Only working images owned by this browser are shown. The newest available session is selected first.</p>
      ${emptyMessage}
      <div class="field"><label>Saved working session</label><select name="imageId" ${recoverable.length ? "" : "disabled"}>${options}</select></div>
      <div class="modal-actions recovery-actions">
        <button class="button danger clear-selected-session" type="button" ${recoverable.length ? "" : "disabled"}>Clear selected</button>
        <button class="button danger clear-all-sessions" type="button" ${recoverable.length ? "" : "disabled"}>Clear all previous</button>
      </div>
      <div class="help-note">Recovery reopens the server-side working copy with all completed changes. Clearing permanently deletes only the selected browser-owned working copies, never your original host files.</div>
      <div class="modal-actions"><button class="button" value="cancel">Cancel</button><button class="button primary recover-session" value="recover" ${recoverable.length ? "" : "disabled"}>Recover session</button></div>
    `, async form => {
      const imageId = form.get("imageId");
      const restored = await api(`/api/images/${encodeURIComponent(imageId)}`);
      await acceptImage(index, restored.image);
      toast(`${restored.image.name} recovered with its working changes.`);
    });
    const sessionSelect = modalContent.querySelector('select[name="imageId"]');
    const recoverButton = modalContent.querySelector(".recover-session");
    const clearSelected = modalContent.querySelector(".clear-selected-session");
    const clearAll = modalContent.querySelector(".clear-all-sessions");
    const updateRecoveryControls = () => {
      const hasSessions = sessionSelect.options.length > 0;
      sessionSelect.disabled = !hasSessions;
      recoverButton.disabled = !hasSessions;
      clearSelected.disabled = !hasSessions;
      clearAll.disabled = !hasSessions;
      modalContent.querySelector(".no-recovery-sessions")?.toggleAttribute("hidden", hasSessions);
    };
    clearSelected.addEventListener("click", async () => {
      const option = sessionSelect.selectedOptions[0];
      if (!option || !confirm(`Permanently clear the working copy “${option.textContent}”?`)) return;
      clearSelected.disabled = true;
      try {
        await api("/api/images/recoverable", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ imageIds: [option.value] })
        });
        option.remove();
        updateRecoveryControls();
        toast("Previous working session cleared.");
      } catch (error) {
        toast(`Could not clear the session: ${error.message}`, true);
        updateRecoveryControls();
      }
    });
    clearAll.addEventListener("click", async () => {
      const imageIds = [...sessionSelect.options].map(option => option.value);
      if (!imageIds.length || !confirm(`Permanently clear all ${imageIds.length} previous working session${imageIds.length === 1 ? "" : "s"} shown here?`)) return;
      clearAll.disabled = true;
      try {
        const result = await api("/api/images/recoverable", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ imageIds })
        });
        sessionSelect.replaceChildren();
        updateRecoveryControls();
        toast(`${result.removed} previous working session${result.removed === 1 ? "" : "s"} cleared.`);
      } catch (error) {
        toast(`Could not clear the sessions: ${error.message}`, true);
        updateRecoveryControls();
      }
    });
    await modalClosed;
  } catch (error) {
    toast(`Could not recover a session: ${error.message}`, true);
  }
}

function downloadFile(index, name) {
  const pane = panes[index];
  const query = new URLSearchParams({ path: fullPath(pane.path, name), bundle: "metadata" });
  if (pane.slot !== null) query.set("slot", pane.slot);
  if (pane.side !== null) query.set("side", pane.side);
  window.location.href = `/api/images/${pane.image.id}/file?${query}`;
}

async function switchDsdSide(index) {
  const pane = panes[index];
  pane.side = pane.side === 2 ? 0 : 2;
  pane.path = "";
  await loadDirectory(index);
}

function chooseSlotImage(index) {
  const entry = selectedEntry(index);
  if (!entry) return;
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.accept = ".ssd,.dsd,.zip";
  input.onchange = () => input.files.length && insertFilesIntoSlots(index, entry.slot, [...input.files]);
  input.click();
}

function createBlankMmbDisk(index, diskFormat) {
  const pane = panes[index];
  const entry = selectedEntry(index);
  if (!entry?.empty) return toast("Select an empty MMB slot first.", true);
  const sideDescription = diskFormat === "dsd"
    ? "A DSD occupies this slot and the next adjacent slot."
    : "An SSD occupies one MMB slot.";
  showModal(`
    <h2>Create blank ${diskFormat.toUpperCase()} in slot ${entry.slot}</h2>
    <p>${sideDescription} The disk is formatted immediately and can be left writable for software that saves progress or user data.</p>
    <div class="field"><label>Disk title</label><input name="title" maxlength="12" value="BLANK" required></div>
    <label class="check-row"><input name="writable" type="checkbox" checked> Mark the inserted disk read / write</label>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="create">Create and insert</button></div>`,
  async form => {
    const data = await api(`/api/images/${pane.image.id}/slots/create-blank`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        targetSlot: entry.slot,
        format: diskFormat,
        title: form.get("title"),
        writable: form.has("writable")
      })
    });
    pane.image = data.image;
    await acceptImage(index, pane.image);
    setSelection(
      panes[index],
      data.slots.map(String),
      String(data.slots[0])
    );
    refreshSelectionDisplay(index);
    toast(`Blank ${diskFormat.toUpperCase()} inserted into slot${data.slots.length > 1 ? "s" : ""} ${data.slots.join(" and ")}`);
    (data.warnings || []).forEach(message => toast(message, true));
    if (data.metadata) maybeReviewInsertedMenu(index, data.metadata);
  });
}

async function setSelectedSlotsWritable(index, writable) {
  const pane = panes[index];
  const slots = selectedEntries(index)
    .filter(entry => entry.type === "disk" && entry.formatted)
    .map(entry => entry.slot);
  if (!slots.length) return toast("Select one or more formatted MMB slots.", true);
  const data = await paneOperation(
    index,
    `Marking ${slots.length} disk${slots.length === 1 ? "" : "s"} ${writable ? "read / write" : "read-only"}…`,
    () => api(`/api/images/${pane.image.id}/slots/protect-many`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slots, writable })
    })
  );
  pane.image = data.image;
  await acceptImage(index, pane.image);
  setSelection(panes[index], slots.map(String), String(slots[0]));
  refreshSelectionDisplay(index);
  toast(`${slots.length} MMB disk${slots.length === 1 ? "" : "s"} marked ${writable ? "read / write" : "read-only"}`);
}

async function insertFilesIntoSlots(index, slot, files) {
  const pane = panes[index];
  const form = new FormData();
  form.append("slot", slot);
  files.forEach(file => form.append("images", file));
  setLoading(index, true, `Inserting ${files.length} disk image${files.length === 1 ? "" : "s"}…`);
  try {
    const data = await api(`/api/images/${pane.image.id}/slots/insert-many`, { method: "POST", body: form });
    pane.image = data.image;
    await acceptImage(index, pane.image);
    const successes = data.items.filter(item => !item.error);
    const failures = data.items.filter(item => item.error);
    if (successes.length) {
      const allocation = successes.map(item => `${item.filename} → ${item.slots.join("/")}`).join(", ");
      toast(`${successes.length} disk image${successes.length === 1 ? "" : "s"} inserted: ${allocation}`);
    }
    failures.forEach(item => toast(`${item.filename}: ${item.error}`, true));
    const reviews = successes.map(item => item.metadata).filter(Boolean);
    if (reviews.length) queueMenuReviews(index, reviews);
  } catch (error) {
    pane.loading = false;
    renderPane(index);
    toast(error.message, true);
  }
}

async function queueMenuReviews(index, metadataItems) {
  const batch = { acceptAll: false, current: 0, total: metadataItems.length };
  for (const [offset, metadata] of metadataItems.entries()) {
    batch.current = offset + 1;
    const shown = await reviewMenuMetadata(index, metadata, false, batch);
    if (shown && modal.open) {
      await new Promise(resolve => modal.addEventListener("close", resolve, { once: true }));
    }
  }
  await showMenuPreview(index, metadataItems.at(-1)?.diskTitle || "");
}

const ONLINE_MACHINES = [
  ["all", "All compatible machines"], ["bbc-b", "BBC Micro Model B"],
  ["bbc-b-plus", "BBC Micro B+"], ["master", "BBC Master"],
  ["electron", "Acorn Electron"], ["archimedes", "Acorn Archimedes"],
  ["risc-os", "RISC OS"]
];
const ONLINE_MACHINE_STORAGE_KEY = "acorn-file-forge-online-machine";
const ACTIVE_PROFILE_STORAGE_KEY = "acorn-file-forge-active-hardware-profile";

function storedOnlineMachine() {
  try {
    const value = localStorage.getItem(ONLINE_MACHINE_STORAGE_KEY) || "";
    return ONLINE_MACHINES.some(([machine]) => machine === value) ? value : "";
  } catch (_error) {
    return "";
  }
}

function rememberOnlineMachine(value) {
  if (ONLINE_MACHINES.some(([machine]) => machine === value)) {
    localStorage.setItem(ONLINE_MACHINE_STORAGE_KEY, value);
  }
}

function onlineMachineFromProfile(profile = {}) {
  const configured = String(profile.catalogMachine || "").toLowerCase();
  if (ONLINE_MACHINES.some(([value]) => value === configured)) return configured;
  const profileMachine = String(profile.machine || "").toLowerCase();
  if (profileMachine.includes("electron")) return "electron";
  if (profileMachine.includes("archimedes")) return "archimedes";
  if (profileMachine.includes("risc os")) return "risc-os";
  if (profileMachine.includes("master") && !profileMachine.includes("bbc")) return "master";
  if (profileMachine.includes("b+")) return "bbc-b-plus";
  if (profileMachine.includes("bbc")) return "bbc-b";
  return "";
}

function activeWorkbenchProfile(profiles = storedCollection(PROFILE_STORAGE_KEY, BUILTIN_PROFILES)) {
  const requested = Number.parseInt(localStorage.getItem(ACTIVE_PROFILE_STORAGE_KEY) || "0", 10);
  const index = Number.isInteger(requested) && requested >= 0 && requested < profiles.length
    ? requested
    : 0;
  return { index, profile: profiles[index] || BUILTIN_PROFILES[0] };
}

function setActiveWorkbenchProfile(index, profile) {
  localStorage.setItem(ACTIVE_PROFILE_STORAGE_KEY, String(index));
  rememberOnlineMachine(onlineMachineFromProfile(profile) || "all");
}

function defaultOnlineMachine(pane) {
  const profileMachine = onlineMachineFromProfile(pane.image?.hardwareProfile);
  if (profileMachine) return profileMachine;
  const workbenchProfileMachine = onlineMachineFromProfile(activeWorkbenchProfile().profile);
  if (workbenchProfileMachine) return workbenchProfileMachine;
  const workbenchMachine = storedOnlineMachine();
  if (workbenchMachine) return workbenchMachine;
  const hardware = String(pane.image?.targetHardware || "").toLowerCase();
  if (hardware.includes("electron")) return "electron";
  if (hardware.includes("risc")) return "risc-os";
  if (hardware.includes("archimedes")) return "archimedes";
  if (hardware.includes("master")) return "master";
  return pane.image?.kind === "adfs" ? "all" : "bbc-b";
}

async function showOnlineSources(index) {
  const data = await api("/api/catalog/sources");
  const rows = data.sources.map((source, offset) => `<fieldset class="online-source-row" data-source="${offset}">
    <label class="check"><input type="checkbox" name="enabled-${offset}" ${source.enabled ? "checked" : ""}> Enabled</label>
    <label>Name<input name="name-${offset}" value="${esc(source.name)}" required></label>
    <label>Catalogue URL<input name="url-${offset}" type="url" value="${esc(source.url)}" required></label>
    <label>Machines<input name="machines-${offset}" value="${esc(source.machines.join(","))}" placeholder="bbc-b,electron"></label>
    <label class="online-provider-options">Provider settings (JSON)<textarea name="options-${offset}" rows="5">${esc(JSON.stringify(source.options || {}, null, 2))}</textarea></label>
    <input type="hidden" name="id-${offset}" value="${esc(source.id)}"><input type="hidden" name="type-${offset}" value="${esc(source.type)}">
    <input type="hidden" name="direct-${offset}" value="${source.direct ? "1" : "0"}">
  </fieldset>`).join("");
  const closed = showModal(`<div class="modal-heading"><span class="modal-kicker">ONLINE LIBRARY</span><h2>Catalogue sources</h2><p>Enable, disable or relocate a provider. Provider settings contain its query templates, categories and machine IDs, so site changes can be handled without changing application code.</p></div>
    <div class="online-source-list">${rows}</div>
    <fieldset class="online-new-source"><legend>Add a compatible provider</legend><label>Name<input name="newName" placeholder="My Acorn archive"></label><label>URL<input name="newUrl" type="url" placeholder="https://…"></label><label>Loading strategy<select name="newLoader"><option value="page">Single page</option><option value="category-crawl">Category crawl</option><option value="machine-index">Machine indexes</option></select></label><label>Page layout<select name="newParser"><option value="thumbnail-cards">Thumbnail cards</option><option value="section-catalogue">Section catalogue</option><option value="function-calls">Function-call records</option><option value="item-rows">Linked item rows</option><option value="query-media-tiles">Media links in query parameters</option><option value="html-cards">Configurable HTML cards</option><option value="zip-links">ZIP download links</option><option value="package-paragraphs">Package paragraphs</option><option value="links">Plain links</option></select></label><label>Machines<input name="newMachines" placeholder="bbc-b,electron"></label><label class="online-provider-options">Provider settings (JSON)<textarea name="newOptions" rows="5">{}</textarea></label></fieldset>
    <div class="modal-actions"><button class="button" type="button" data-back-library>Back</button><button class="button primary" type="submit">Save sources</button></div>`, async form => {
      const sources = data.sources.map((source, offset) => ({
        id: form.get(`id-${offset}`), name: form.get(`name-${offset}`), url: form.get(`url-${offset}`),
        type: form.get(`type-${offset}`), machines: String(form.get(`machines-${offset}`) || "").split(",").map(value => value.trim()).filter(Boolean),
        direct: form.get(`direct-${offset}`) === "1", enabled: form.has(`enabled-${offset}`),
        options: JSON.parse(String(form.get(`options-${offset}`) || "{}"))
      }));
      if (form.get("newName") && form.get("newUrl")) sources.push({
        id: String(form.get("newName")).toLowerCase().replace(/[^a-z0-9]+/g, "-"), name: form.get("newName"),
        url: form.get("newUrl"), type: "configured", direct: true, enabled: true,
        machines: String(form.get("newMachines") || "all").split(",").map(value => value.trim()).filter(Boolean),
        options: { ...JSON.parse(String(form.get("newOptions") || "{}")), loader: form.get("newLoader"), parser: form.get("newParser") }
      });
      await api("/api/catalog/sources", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sources }) });
      toast("Online catalogue sources saved");
    }, { replace: true });
  modalContent.querySelector("[data-back-library]").onclick = () => {
    modal.close();
    setTimeout(() => showOnlineLibrary(index), 0);
  };
  return closed;
}

async function showOnlineLibrary(index) {
  const pane = panes[index];
  const isMmbRoot = pane.image.kind === "mmb" && pane.slot === null;
  const selectedEmpty = isMmbRoot
    ? selectedEntries(index).filter(entry => entry.empty).map(entry => entry.slot)
    : [];
  const firstEmpty = isMmbRoot ? pane.entries.find(entry => entry.empty)?.slot ?? 0 : 0;
  const machine = defaultOnlineMachine(pane);
  const machineOptions = ONLINE_MACHINES.map(([value, label]) => `<option value="${value}" ${value === machine ? "selected" : ""}>${label}</option>`).join("");
  showModal(`<div class="modal-heading online-library-heading"><span class="modal-kicker">ONLINE LIBRARY</span><h2>${isMmbRoot ? "Find disk images" : "Find software to install"}</h2><p>Search trusted Acorn archives, select several results, then install them through the same checked workflow as local files.</p></div>
    <div class="online-search-bar"><label>Machine<select name="machine">${machineOptions}</select></label><label class="online-query">Title, publisher or keyword<input name="query" type="search" placeholder="Leave blank to browse"></label><label>Show<select name="scope"><option value="missing">Not already present</option><option value="all">All results</option></select></label><button class="button online-search" type="button">Search</button><button class="button ghost online-sources" type="button">Sources…</button></div>
    <div class="online-status">Choose a machine and search the configured catalogues.</div>
    <div class="online-results" aria-live="polite"></div>
    <div class="online-install-options">
      ${isMmbRoot ? `<label>Start at slot<input name="startSlot" type="number" min="0" max="510" value="${selectedEmpty[0] ?? firstEmpty}"></label><span class="field-note">${selectedEmpty.length ? `${selectedEmpty.length} selected empty slot${selectedEmpty.length === 1 ? "" : "s"} will be preferred.` : "The next suitable empty slots will be used."}</span><label class="check"><input type="checkbox" name="addToMenu" checked> Offer installed disks to the detected menu</label>` : ""}
      ${pane.image.kind === "adfs" ? '<label class="check"><input type="checkbox" name="createDirectory"> Create a folder for each downloaded disk</label><span class="field-note">By default, files are extracted into the current directory.</span>' : ""}
    </div>
    <div class="modal-actions"><button class="button" value="cancel">Cancel</button><button class="button primary online-install" type="submit" disabled>${isMmbRoot ? "Insert selected disks" : "Install selected"}</button></div>`, async form => {
      const itemIds = form.getAll("catalogItem");
      if (!itemIds.length) { toast("Select one or more downloadable items first.", true); return false; }
      const titles = new Map([...modalContent.querySelectorAll('[name="catalogItem"]')].map(input => [input.value, input.closest("tr")?.querySelector("strong")?.textContent || input.value]));
      const results = [];
      let abortRequested = false;
      setModalAbort(async () => { abortRequested = true; setModalProgress({ title: "Stopping Online Library install", message: "The current item will finish safely, then no further downloads will start." }, results.length, itemIds.length); });
      for (let offset = 0; offset < itemIds.length; offset += 1) {
        if (abortRequested) break;
        const itemId = itemIds[offset];
        setModalProgress({ title: "Installing online software", message: `Downloading and checking ${titles.get(itemId)}…`, details: [{ label: "Destination", value: isMmbRoot ? pane.image.name : pane.path }] }, offset, itemIds.length);
        try {
          const result = await api(`/api/images/${pane.image.id}/catalog/install`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ itemIds: [itemId], slots: selectedEmpty.slice(offset), startSlot: selectedEmpty[offset] ?? (Number(form.get("startSlot") || firstEmpty) + offset), path: pane.path, slot: pane.slot, side: pane.side, addToMenu: form.has("addToMenu"), createDirectory: form.has("createDirectory") })
          });
          pane.image = result.image;
          results.push(...result.items);
        } catch (error) {
          results.push({ id: itemId, title: titles.get(itemId), error: error.message });
        }
      }
      await acceptImage(index, pane.image);
      const successes = results.filter(item => !item.error);
      const failures = results.filter(item => item.error);
      toast(`${successes.length} online item${successes.length === 1 ? "" : "s"} installed${abortRequested ? " before the operation was stopped" : ""}`);
      failures.forEach(item => toast(`${item.title}: ${item.error}`, true));
      const reviews = successes.map(item => item.metadata).filter(Boolean);
      if (reviews.length) setTimeout(() => queueMenuReviews(index, reviews), 80);
    });

  const searchButton = modalContent.querySelector(".online-search");
  const installButton = modalContent.querySelector(".online-install");
  const resultHost = modalContent.querySelector(".online-results");
  const status = modalContent.querySelector(".online-status");
  let resultItems = [];
  let resultFailures = [];
  let resultSort = { key: "title", direction: "asc" };
  const renderOnlineResults = () => {
    const selected = new Set([...resultHost.querySelectorAll('[name="catalogItem"]:checked')].map(input => input.value));
    const direction = resultSort.direction === "asc" ? 1 : -1;
    const items = [...resultItems].sort((left, right) => {
      const compared = String(left[resultSort.key] || "").localeCompare(String(right[resultSort.key] || ""), undefined, { numeric: true, sensitivity: "base" });
      return compared * direction || String(left.title || "").localeCompare(String(right.title || ""), undefined, { sensitivity: "base" });
    });
    const heading = (label, key) => {
      const active = resultSort.key === key;
      const arrow = active ? (resultSort.direction === "asc" ? "↑" : "↓") : "";
      const ariaSort = active ? (resultSort.direction === "asc" ? "ascending" : "descending") : "none";
      return `<th aria-sort="${ariaSort}"><button class="online-sort" type="button" data-sort="${key}">${label}<span aria-hidden="true">${arrow}</span></button></th>`;
    };
    resultHost.innerHTML = items.length ? `<table class="online-result-table" aria-label="Downloadable Acorn software"><thead><tr><th></th>${heading("Title", "title")}${heading("Publisher", "publisher")}${heading("Year", "year")}${heading("Source", "sourceName")}<th></th></tr></thead><tbody>${items.map(item => `<tr class="${item.installed ? "already-installed" : ""}"><td><input type="checkbox" name="catalogItem" value="${esc(item.id)}" aria-label="Select ${esc(item.title)}" ${selected.has(item.id) ? "checked" : ""}></td><td><strong>${esc(item.title)}</strong>${item.version ? `<small>Version ${esc(item.version)}</small>` : ""}${item.description ? `<small>${esc(item.description)}</small>` : ""}</td><td>${esc(item.publisher || "Unknown")}</td><td>${esc(item.year || "-")}</td><td><span class="pill">${esc(item.sourceName)}</span>${item.installed ? '<small class="installed-label">Already present</small>' : ""}</td><td><a class="button tiny" href="${esc(item.pageUrl)}" target="_blank" rel="noopener">Details</a></td></tr>`).join("")}</tbody></table>` : '<div class="empty-list">No matching downloadable items were found. Try All results, another machine, or a broader search.</div>';
    if (resultFailures.length) resultHost.insertAdjacentHTML("beforeend", `<details class="online-failures"><summary>Unavailable sources</summary>${resultFailures.map(item => `<p><b>${esc(item.source)}</b>: ${esc(item.error)}</p>`).join("")}</details>`);
    resultHost.querySelectorAll("[data-sort]").forEach(button => button.onclick = () => {
      const key = button.dataset.sort;
      resultSort = { key, direction: resultSort.key === key && resultSort.direction === "asc" ? "desc" : "asc" };
      renderOnlineResults();
    });
    resultHost.querySelectorAll('[name="catalogItem"]').forEach(input => input.onchange = () => { installButton.disabled = !resultHost.querySelector('[name="catalogItem"]:checked'); });
    installButton.disabled = !resultHost.querySelector('[name="catalogItem"]:checked');
  };
  const runSearch = async (requestedMachine = null) => {
    searchButton.disabled = true; installButton.disabled = true;
    status.textContent = "Contacting enabled catalogues…";
    resultHost.innerHTML = '<div class="online-loading">Searching the Online Library…</div>';
    try {
      const parameters = new URLSearchParams({ q: modalContent.querySelector('[name="query"]').value, machine: requestedMachine || modalContent.querySelector('[name="machine"]').value, scope: modalContent.querySelector('[name="scope"]').value, path: pane.path });
      if (pane.slot !== null) parameters.set("slot", pane.slot);
      const data = await api(`/api/images/${pane.image.id}/catalog/search?${parameters}`);
      resultItems = data.items.filter(item => item.downloadable);
      resultFailures = data.failures;
      resultSort = { key: "title", direction: "asc" };
      status.textContent = `${resultItems.length} result${resultItems.length === 1 ? "" : "s"}${data.failures.length ? ` · ${data.failures.length} source${data.failures.length === 1 ? "" : "s"} unavailable` : ""}`;
      renderOnlineResults();
    } catch (error) {
      status.textContent = "Search failed"; resultHost.innerHTML = `<div class="help-warning">${esc(error.message)}</div>`;
    } finally { searchButton.disabled = false; }
  };
  searchButton.onclick = () => runSearch();
  modalContent.querySelector(".online-sources").onclick = () => showOnlineSources(index);
  modalContent.querySelector('[name="query"]').onkeydown = event => { if (event.key === "Enter") { event.preventDefault(); runSearch(); } };
  runSearch(machine);
}

async function insertSessionIntoSlot(index, slot, source) {
  const pane = panes[index];
  try {
    const data = await paneOperation(index, "Copying disk into MMB slot…", () => api(`/api/images/${pane.image.id}/slots/insert-from-image`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targetSlot: slot, sourceImage: source.image, sourceSlot: source.slot })
    }));
    pane.image = data.image;
    await acceptImage(index, pane.image);
    toast(`Disk inserted into slot${data.slots.length > 1 ? "s" : ""} ${data.slots.join(" and ")}`);
    (data.warnings || []).forEach(message => toast(message, true));
    if (data.metadata) maybeReviewInsertedMenu(index, data.metadata);
  } catch (error) { toast(error.message, true); }
}

async function maybeReviewInsertedMenu(index, metadata) {
  try {
    const menu = await api(`/api/images/${panes[index].image.id}/menu`);
    if (menu.configured) reviewMenuMetadata(index, metadata);
    else toast("Disk kept off-menu. Use Create menu when you want an MMB menu.");
  } catch (error) { toast(error.message, true); }
}

function previewMenuAfterCurrentDialog(index, highlight = "") {
  if (!modal.open) {
    showMenuPreview(index, highlight);
    return;
  }
  modal.addEventListener("close", () => {
    setTimeout(() => showMenuPreview(index, highlight), 0);
  }, { once: true });
}

async function showMenuPreview(index, highlight = "") {
  const pane = panes[index];
  try {
    const query = pane.image.kind === "adfs"
      ? `?${new URLSearchParams({ root: pane.path })}`
      : "";
    const data = await paneOperation(index, "Reading the installed menu databases…", () =>
      api(`/api/images/${pane.image.id}/menu/preview${query}`));
    let entries = data.entries || [];
    const menuIdentity = entry => JSON.stringify([
      entry.diskTitle || "",
      entry.title || "",
      entry.publisher || "",
      entry.filename || "",
      entry.action || "",
      entry.page || "",
    ]);
    const installedOrder = entries.map(menuIdentity);
    const canReorder = data.kind === "adfs";
    const canEdit = data.kind === "mmb" && ["universal", "universal-4r", "spi-game-menu"].includes(data.menuType);
    const canScanMissing = data.kind === "mmb" && ["universal", "universal-4r", "spi-game-menu"].includes(data.menuType);
    const interpretation = data.interpretation || { supported: false };
    const spiMenu = data.menuType === "spi-game-menu";
    const pageSize = Number(interpretation.entries?.pageSize) || 26;
    let pageNumber = 0;
    let selectedIndex = Math.max(0, entries.findIndex(entry =>
      [entry.diskTitle, entry.title].some(value =>
        String(value || "").toLocaleLowerCase() === String(highlight || "").toLocaleLowerCase()
      )
    ));
    let filter = "";
    let draggedIndex = null;
    let orderDescription = "Installed GAMDATA order";
    const orderChanged = () => entries.some(
      (entry, offset) => menuIdentity(entry) !== installedOrder[offset]
    );
    showModal(`
      <div class="installed-menu-preview ${interpretation.supported ? "interpreted" : "database-only"}">
        <div class="menu-preview-heading">
          <div><small>${interpretation.supported ? "INTERPRETED INSTALLED MENU" : "MENU DATABASE PREVIEW"}</small><h2>${esc(data.kind === "mmb" ? menuTypeLabel(data.menuType) : "ADFS Directory Menu")}</h2></div>
          <span>${esc(data.location)} · ${entries.length} ${entries.length === 1 ? "entry" : "entries"}</span>
        </div>
        ${interpretation.supported ? `
          <div class="menu-interpretation-note"><strong>${esc(interpretation.program)}</strong> · BBC MODE ${esc(interpretation.mode)} · ${esc(interpretation.columns)}×${esc(interpretation.rows)} characters · program ${esc(interpretation.programSha256.slice(0, 12))}</div>` : `
          <div class="help-warning"><strong>The installed program could not be interpreted.</strong> ${esc(interpretation.reason || "Only its database records are shown; the hardware screen is not being imitated.")}</div>`}
        <div class="menu-preview-tools">
          <input name="previewSearch" type="search" placeholder="Find title, publisher, disk or directory…" aria-label="Search installed menu">
          ${canReorder ? `
            <label class="menu-preview-sort">
              <span>Order</span>
              <select name="previewOrder" aria-label="Menu item order">
                <option value="installed">Installed order</option>
                <option value="title-asc">Name A-Z</option>
                <option value="title-desc">Name Z-A</option>
                <option value="manual">Manual drag order</option>
              </select>
            </label>` : ""}
          <span class="menu-preview-order">${canReorder ? "Installed GAMDATA order" : "Actual GAMDATA order"}</span>
        </div>
        <div class="menu-preview-layout">
          <section class="menu-preview-monitor" aria-label="Installed menu page interpreted from ${esc(interpretation.program || "database records")}">
            <div class="menu-preview-screen" style="--bbc-bg:${esc(interpretation.palette?.[0] || "#000000")};--bbc-title:${esc(interpretation.palette?.[interpretation.title?.colour] || "#00ff00")};--bbc-entry:${esc(interpretation.palette?.[interpretation.entries?.titleColour] || "#00ff00")};--bbc-detail:${esc(interpretation.palette?.[interpretation.entries?.publisherColour] || "#00ffff")}">
              <div class="bbc-menu-title"></div>
              <div class="bbc-menu-banner"></div>
              <div class="bbc-menu-status"></div>
              <div class="menu-preview-entries"></div>
            </div>
            <div class="menu-preview-page-controls">
              <button class="preview-previous" type="button">◀ Previous</button>
              <span class="preview-page"></span>
              <button class="preview-next" type="button">Next ▶</button>
            </div>
          </section>
          <aside class="menu-preview-inspector">
            <small>SELECTED ENTRY</small>
            <div class="menu-preview-detail"></div>
            ${canEdit ? `<div class="menu-preview-entry-actions">
              <button class="button ghost edit-menu-entry" type="button">Edit entry</button>
              <button class="button ghost clone-menu-entry" type="button">Clone entry</button>
              <button class="button danger remove-menu-entry" type="button">Remove</button>
            </div>` : ""}
          </aside>
        </div>
        <div class="modal-actions">
          <button class="button ghost" value="cancel">Close preview</button>
          ${canEdit ? '<button class="button ghost bulk-edit-menu" type="button">Bulk edit entries</button>' : ""}
          ${canScanMissing ? '<button class="button ghost scan-missing-menu" type="button">Add missing disks</button>' : ""}
          ${canReorder ? '<button class="button primary save-menu-order" value="save" disabled>Save order</button>' : ""}
        </div>
      </div>`, async () => {
        if (!canReorder || !orderChanged()) return;
        const result = await api(`/api/images/${pane.image.id}/adfs-menu/reorder`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            root: data.root,
            order: entries.map(entry => ({
              diskTitle: entry.diskTitle,
              title: entry.title,
              publisher: entry.publisher,
              filename: entry.filename,
              action: entry.action,
              page: entry.page,
            }))
          })
        });
        pane.image = result.image;
        toast(`Saved menu order for ${result.entries} entries`);
      });

    const normalise = value => String(value || "").toLocaleLowerCase();
    modalContent.querySelector(".scan-missing-menu")?.addEventListener("click", () => {
      modal.close();
      setTimeout(() => scanMmbMenu(index, "missing"), 0);
    });
    modalContent.querySelector(".bulk-edit-menu")?.addEventListener("click", () => {
      modal.close();
      setTimeout(() => showMmbBulkMenuEditor(index, data, entries), 0);
    });
    const compareTitle = (left, right) =>
      String(left.title || "").localeCompare(String(right.title || ""), undefined, {
        sensitivity: "base",
        numeric: true
      }) || String(left.publisher || "").localeCompare(String(right.publisher || ""), undefined, {
        sensitivity: "base",
        numeric: true
      });
    const updateOrderControls = () => {
      if (!canReorder) return;
      const changed = orderChanged();
      modalContent.querySelector(".save-menu-order").disabled = !changed;
      modalContent.querySelector(".menu-preview-order").textContent =
        `${orderDescription}${changed ? " · Unsaved" : ""}`;
    };
    const selectEntry = entry => {
      selectedIndex = Math.max(0, entries.indexOf(entry));
    };
    const applyOrder = mode => {
      const selected = entries[selectedIndex];
      if (mode === "installed") {
        const positions = new Map(installedOrder.map((identity, offset) => [identity, offset]));
        entries.sort((left, right) =>
          positions.get(menuIdentity(left)) - positions.get(menuIdentity(right))
        );
        orderDescription = "Installed GAMDATA order";
      } else if (mode === "title-asc") {
        entries.sort(compareTitle);
        orderDescription = "Name ascending";
      } else if (mode === "title-desc") {
        entries.sort((left, right) => compareTitle(right, left));
        orderDescription = "Name descending";
      } else {
        orderDescription = "Manual drag order";
      }
      selectEntry(selected);
      pageNumber = Math.floor(selectedIndex / pageSize);
      render();
    };
    const visibleEntries = () => entries
      .map((entry, originalIndex) => ({ entry, originalIndex }))
      .filter(({ entry }) => !filter || [
        entry.title,
        entry.publisher,
        entry.diskTitle,
        entry.filename
      ].some(value => normalise(value).includes(filter)));
    const launchCommand = entry => {
      if (spiMenu) return `*DIN 0 ${entry.diskTitle} · *EXEC !BOOT`;
      const action = { "": "CHAIN", R: "RUN", E: "EXEC", L: "LOAD" }[entry.action] || entry.action;
      return `*${action} ${entry.filename}`;
    };
    const renderDetail = entry => {
      modalContent.querySelector(".menu-preview-detail").innerHTML = entry ? `
        <strong>${esc(entry.title)}</strong>
        <dl>
          <dt>Publisher</dt><dd>${esc(entry.publisher || "Not specified")}</dd>
          <dt>Launch</dt><dd>${esc(launchCommand(entry))}</dd>
          ${spiMenu ? "" : `<dt>PAGE</dt><dd>&amp;${esc(entry.page || "1900")}</dd>`}
          <dt>${data.kind === "mmb" ? "Disk title" : "Directory"}</dt><dd>${esc(entry.diskTitle)}</dd>
        </dl>` : "<p>No matching menu entry.</p>";
    };
    const render = () => {
      const filtered = visibleEntries();
      const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
      pageNumber = Math.min(pageNumber, totalPages - 1);
      const pageEntries = filtered.slice(pageNumber * pageSize, (pageNumber + 1) * pageSize);
      if (pageEntries.length && !pageEntries.some(item => item.originalIndex === selectedIndex)) {
        selectedIndex = pageEntries[0].originalIndex;
      }
      const screenTitle = modalContent.querySelector(".bbc-menu-title");
      const screenBanner = modalContent.querySelector(".bbc-menu-banner");
      const screenStatus = modalContent.querySelector(".bbc-menu-status");
      screenTitle.textContent = interpretation.supported
        ? `${" ".repeat(Math.max(0, Number(interpretation.title?.x) || 0))}${interpretation.title?.text || "Universal Menu"}`
        : "MENU DATABASE RECORDS";
      screenBanner.textContent = interpretation.supported
        ? interpretation.banner?.text || ""
        : "Installed program display unavailable";
      screenStatus.textContent = interpretation.supported
        ? interpretation.status?.visible === false ? "" : String(interpretation.status?.template || "{screens} Screens. At:{page}")
          .replace("{screens}", String(totalPages))
          .replace("{page}", String(pageNumber + 1))
        : `${entries.length} parsed records`;
      modalContent.querySelector(".menu-preview-entries").innerHTML = pageEntries.length
        ? pageEntries.map(({ entry, originalIndex }, screenIndex) => `
          <button type="button" data-preview-index="${originalIndex}" class="${originalIndex === selectedIndex ? "selected" : ""}"
            ${canReorder && !filter ? 'draggable="true" title="Drag to reorder this menu item"' : ""}>
            <b>${esc(String.fromCharCode(65 + screenIndex))}-</b><span>${esc(entry.title || "Untitled")}</span><i>,${esc(entry.publisher || "")}</i>
          </button>`).join("")
        : '<p class="menu-preview-empty">NO MATCHING PROGRAMS</p>';
      modalContent.querySelector(".preview-page").textContent =
        `Page ${pageNumber + 1} of ${totalPages} · ${filtered.length} entries`;
      modalContent.querySelector(".preview-previous").disabled = pageNumber === 0;
      modalContent.querySelector(".preview-next").disabled = pageNumber >= totalPages - 1;
      renderDetail(entries[selectedIndex]);
      if (canEdit) {
        const selectedEntry = entries[selectedIndex];
        const editButton = modalContent.querySelector(".edit-menu-entry");
        const cloneButton = modalContent.querySelector(".clone-menu-entry");
        const removeButton = modalContent.querySelector(".remove-menu-entry");
        editButton.disabled = !selectedEntry;
        cloneButton.disabled = !selectedEntry;
        removeButton.disabled = !selectedEntry;
        editButton.onclick = () => showMmbMenuEntryEditor(index, data, selectedEntry, entries);
        cloneButton.onclick = () => showMmbMenuEntryEditor(index, data, selectedEntry, entries, true);
        removeButton.onclick = () => removeMmbMenuEntry(index, data, selectedEntry, entries);
      }
      updateOrderControls();
      modalContent.querySelectorAll("[data-preview-index]").forEach(button => {
        button.onclick = () => {
          selectedIndex = Number(button.dataset.previewIndex);
          render();
        };
        if (!canReorder || filter) return;
        button.ondragstart = event => {
          draggedIndex = Number(button.dataset.previewIndex);
          button.classList.add("dragging");
          event.dataTransfer.effectAllowed = "move";
          event.dataTransfer.setData("text/plain", String(draggedIndex));
        };
        button.ondragend = () => {
          draggedIndex = null;
          modalContent.querySelectorAll(".menu-preview-entries > button").forEach(row =>
            row.classList.remove("dragging", "drop-before", "drop-after")
          );
        };
        button.ondragover = event => {
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
          const after = event.clientY > button.getBoundingClientRect().top + button.offsetHeight / 2;
          button.classList.toggle("drop-before", !after);
          button.classList.toggle("drop-after", after);
        };
        button.ondragleave = () => button.classList.remove("drop-before", "drop-after");
        button.ondrop = event => {
          event.preventDefault();
          const from = draggedIndex ?? Number(event.dataTransfer.getData("text/plain"));
          const target = Number(button.dataset.previewIndex);
          const after = event.clientY > button.getBoundingClientRect().top + button.offsetHeight / 2;
          if (!Number.isInteger(from) || from === target) return;
          const [moved] = entries.splice(from, 1);
          let insertion = target - (from < target ? 1 : 0) + (after ? 1 : 0);
          insertion = Math.max(0, Math.min(entries.length, insertion));
          entries.splice(insertion, 0, moved);
          selectedIndex = insertion;
          pageNumber = Math.floor(insertion / pageSize);
          orderDescription = "Manual drag order";
          modalContent.querySelector('[name="previewOrder"]').value = "manual";
          render();
        };
      });
    };
    modalContent.querySelector('[name="previewSearch"]').oninput = event => {
      filter = normalise(event.target.value);
      pageNumber = 0;
      render();
    };
    modalContent.querySelector('[name="previewOrder"]')?.addEventListener("change", event => {
      applyOrder(event.target.value);
    });
    modalContent.querySelector(".preview-previous").onclick = () => {
      pageNumber -= 1;
      render();
    };
    modalContent.querySelector(".preview-next").onclick = () => {
      pageNumber += 1;
      render();
    };
    render();
    if (highlight && selectedIndex >= 0) {
      pageNumber = Math.max(
        0,
        Math.floor(visibleEntries().findIndex(item => item.originalIndex === selectedIndex) / pageSize)
      );
      render();
    }
  } catch (error) {
    toast(error.message, true);
  }
}

async function saveMmbMenuEntries(index, expectedEntries, entries, message) {
  const pane = panes[index];
  const result = await paneOperation(index, message, () => api(`/api/images/${pane.image.id}/mmb-menu/entries`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expectedEntries, entries })
  }));
  pane.image = result.image;
  await acceptImage(index, pane.image);
  return result;
}

async function showMmbBulkMenuEditor(index, menu, installedEntries) {
  const pane = panes[index];
  const spiMenu = menu.menuType === "spi-game-menu";
  const expectedEntries = installedEntries.map(entry => ({ ...entry }));
  let entries = installedEntries.map((entry, offset) => ({
    ...entry, _key: `entry-${offset}`, _defaultPage: entry.page
  }));
  let filter = "";
  let draggedKey = null;
  const catalogueCache = new Map();
  modal.close();
  try {
    const slotData = await paneOperation(index, "Reading MMB disk titles…", () =>
      api(`/api/images/${pane.image.id}/slots`));
    const slots = slotData.slots.filter(item => item.formatted && item.slot !== menu.menuSlot);
    const slotByTitle = new Map(slots.map(slot => [String(slot.name).toLocaleLowerCase(), slot]));
    const diskOptions = selected => slots.map(slot =>
      `<option value="${esc(slot.name)}" ${String(slot.name).toLocaleLowerCase() === String(selected).toLocaleLowerCase() ? "selected" : ""}>Slot ${slot.slot} · ${esc(slot.name)}</option>`
    ).join("");

    showModal(`
      <div class="bulk-menu-editor">
        <div class="menu-preview-heading">
          <div><small>CSV-STYLE MENU EDITOR</small><h2>Bulk edit ${esc(menuTypeLabel(menu.menuType))}</h2></div>
          <span class="bulk-menu-count"></span>
        </div>
        <p>Edit several records before saving once. Drag rows to reorder them, clone compilation titles, or remove records without changing their MMB disks.</p>
        <div class="bulk-menu-tools">
          <input name="bulkMenuSearch" type="search" placeholder="Filter title, publisher, disk or launcher…" aria-label="Filter menu records">
          <button class="button ghost sort-menu-ascending" type="button">Name A-Z</button>
          <button class="button ghost add-menu-row" type="button">Add row</button>
        </div>
        <div class="bulk-menu-table-wrap">
          <table class="bulk-menu-table" aria-label="Editable menu records">
            <thead><tr><th aria-label="Order">#</th><th>Name</th><th>Publisher</th><th>MMB disk</th>${spiMenu ? "" : "<th>Launch file</th><th>Action</th><th>PAGE</th>"}<th aria-label="Row actions"></th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
        <div class="help-note bulk-menu-note"><strong>One safe write:</strong> nothing is changed until Save all edits. Changed launchers are checked against their selected disk catalogues before all menu database files are replaced together.</div>
        <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="save">Save all edits</button></div>
      </div>`,
    async () => {
      const overrides = entries.filter(entry =>
        !spiMenu && entry._defaultPage
        && normalisePage(entry.page) !== normalisePage(entry._defaultPage));
      if (overrides.length && !await confirmPageOverride(overrides.map(entry => ({
        title: entry.title,
        defaultPage: entry._defaultPage,
        chosenPage: entry.page
      })))) return false;
      const edited = entries.map(({ _key, _defaultPage, ...entry }) => entry);
      const result = await saveMmbMenuEntries(index, expectedEntries, edited, `Validating and saving ${edited.length} menu entries…`);
      toast(`Saved ${result.entries} menu entries in one update`);
      previewMenuAfterCurrentDialog(index);
    });

    const tableBody = modalContent.querySelector(".bulk-menu-table tbody");
    const matchesFilter = entry => !filter || [entry.title, entry.publisher, entry.diskTitle, entry.filename]
      .some(value => String(value || "").toLocaleLowerCase().includes(filter));
    const syncField = event => {
      const row = event.target.closest("tr[data-entry-key]");
      const entry = entries.find(item => item._key === row?.dataset.entryKey);
      if (!entry || !event.target.name) return;
      entry[event.target.name] = event.target.value;
    };
    const loadCatalogue = async input => {
      const row = input.closest("tr[data-entry-key]");
      const entry = entries.find(item => item._key === row?.dataset.entryKey);
      const slot = slotByTitle.get(String(entry?.diskTitle || "").toLocaleLowerCase());
      if (!entry || !slot) return;
      if (!catalogueCache.has(slot.slot)) {
        input.setAttribute("placeholder", "Reading catalogue…");
        try {
          const query = new URLSearchParams({ path: "$", slot: slot.slot });
          const listing = await api(`/api/images/${pane.image.id}/tree?${query}`);
          catalogueCache.set(slot.slot, listing.entries
            .filter(item => !["dir", "directory"].includes(item.type))
            .map(item => item.name));
        } catch (error) {
          toast(error.message, true);
          return;
        } finally {
          input.removeAttribute("placeholder");
        }
      }
      const list = row.querySelector("datalist");
      list.innerHTML = catalogueCache.get(slot.slot).map(name => `<option value="${esc(name)}"></option>`).join("");
      input.setAttribute("list", list.id);
      input.showPicker?.();
    };
    const updateEntryPage = async row => {
      if (spiMenu) return;
      const entry = entries.find(item => item._key === row?.dataset.entryKey);
      const slot = slotByTitle.get(String(entry?.diskTitle || "").toLocaleLowerCase());
      if (!entry || !slot || !entry.filename) return;
      try {
        const result = await mmbRecommendedPage(
          pane.image.id, slot.slot, entry.filename, entry.action
        );
        if (!result.page) {
          entry._defaultPage = null;
          row.querySelector('[name="page"]')?.setAttribute("title", result.evidence);
          return;
        }
        entry._defaultPage = result.page;
        entry.page = result.page;
        const pageInput = row.querySelector('[name="page"]');
        if (pageInput) {
          pageInput.value = result.page;
          pageInput.title = `Recommended from disk image: ${result.evidence}`;
        }
      } catch (error) {
        toast(`Could not inspect PAGE: ${error.message}`, true);
      }
    };
    const render = () => {
      const visible = entries.filter(matchesFilter);
      modalContent.querySelector(".bulk-menu-count").textContent = `${visible.length} of ${entries.length} entries`;
      tableBody.innerHTML = visible.length ? visible.map((entry, visibleOffset) => {
        const offset = entries.indexOf(entry);
        const listId = `menu-launch-${entry._key}`;
        return `<tr data-entry-key="${esc(entry._key)}" draggable="${filter ? "false" : "true"}">
          <td class="bulk-menu-order" title="Drag to reorder"><span>☰</span><small>${offset + 1}</small></td>
          <td><input name="title" value="${esc(entry.title || "")}" required aria-label="Title row ${offset + 1}"></td>
          <td><input name="publisher" value="${esc(entry.publisher || "")}" aria-label="Publisher row ${offset + 1}"></td>
          <td><select name="diskTitle" required aria-label="MMB disk row ${offset + 1}">${diskOptions(entry.diskTitle)}</select></td>
          ${spiMenu ? "" : `<td><input class="bulk-launch-file" name="filename" value="${esc(entry.filename || "")}" maxlength="7" autocomplete="off" required aria-label="Launch file row ${offset + 1}"><datalist id="${listId}"></datalist></td>
          <td><select name="action" aria-label="Action row ${offset + 1}">
            <option value="" ${entry.action === "" ? "selected" : ""}>CHAIN</option><option value="R" ${entry.action === "R" ? "selected" : ""}>RUN</option><option value="E" ${entry.action === "E" ? "selected" : ""}>EXEC</option><option value="L" ${entry.action === "L" ? "selected" : ""}>LOAD</option>
          </select></td>
          <td><input name="page" value="${esc(entry.page || "1900")}" maxlength="4" pattern="[0-9A-Fa-f]{1,4}" required aria-label="PAGE row ${offset + 1}"></td>`}
          <td class="bulk-menu-row-actions"><button type="button" data-clone title="Clone this entry" aria-label="Clone ${esc(entry.title)}">⧉</button><button type="button" data-delete title="Remove this menu entry" aria-label="Remove ${esc(entry.title)}">×</button></td>
        </tr>`;
      }).join("") : '<tr><td class="bulk-menu-empty" colspan="8">No matching menu entries</td></tr>';
      tableBody.querySelectorAll("input, select").forEach(control => {
        control.addEventListener("input", syncField);
        control.addEventListener("change", event => {
          syncField(event);
          if (event.target.name === "diskTitle") {
            const row = event.target.closest("tr");
            const launch = row.querySelector(".bulk-launch-file");
            if (launch) {
              launch.removeAttribute("list");
              row.querySelector("datalist").innerHTML = "";
              loadCatalogue(launch);
            }
          }
          if (["diskTitle", "filename", "action"].includes(event.target.name)) {
            updateEntryPage(event.target.closest("tr"));
          }
        });
      });
      tableBody.querySelectorAll(".bulk-launch-file").forEach(input => {
        input.addEventListener("focus", () => loadCatalogue(input));
      });
      tableBody.querySelectorAll("tr[data-entry-key]").forEach(row => {
        row.querySelector("[data-clone]").onclick = () => {
          const offset = entries.findIndex(item => item._key === row.dataset.entryKey);
          const source = entries[offset];
          entries.splice(offset + 1, 0, { ...source, title: `${source.title} 2`, _key: crypto.randomUUID() });
          render();
        };
        row.querySelector("[data-delete]").onclick = () => {
          entries = entries.filter(item => item._key !== row.dataset.entryKey);
          render();
        };
        row.ondragstart = event => {
          if (filter) return event.preventDefault();
          draggedKey = row.dataset.entryKey;
          row.classList.add("dragging");
          event.dataTransfer.effectAllowed = "move";
        };
        row.ondragend = () => {
          draggedKey = null;
          tableBody.querySelectorAll("tr").forEach(item => item.classList.remove("dragging", "drop-before"));
        };
        row.ondragover = event => {
          if (!draggedKey || draggedKey === row.dataset.entryKey) return;
          event.preventDefault();
          row.classList.add("drop-before");
        };
        row.ondragleave = () => row.classList.remove("drop-before");
        row.ondrop = event => {
          event.preventDefault();
          const from = entries.findIndex(item => item._key === draggedKey);
          let to = entries.findIndex(item => item._key === row.dataset.entryKey);
          if (from < 0 || to < 0 || from === to) return;
          const [moved] = entries.splice(from, 1);
          if (from < to) to -= 1;
          entries.splice(to, 0, moved);
          render();
        };
      });
    };
    modalContent.querySelector('[name="bulkMenuSearch"]').oninput = event => {
      filter = event.target.value.toLocaleLowerCase();
      render();
    };
    modalContent.querySelector(".sort-menu-ascending").onclick = () => {
      entries.sort((left, right) => String(left.title || "").localeCompare(String(right.title || ""), undefined, { sensitivity: "base", numeric: true }));
      render();
    };
    modalContent.querySelector(".add-menu-row").onclick = () => {
      const firstSlot = slots[0];
      if (!firstSlot) return toast("The MMB has no software disks available for a menu entry.", true);
      entries.push({
        title: "New title", publisher: "", diskTitle: firstSlot.name,
        filename: spiMenu ? "!BOOT" : "", action: spiMenu ? "E" : "", page: spiMenu ? "1900" : "",
        _defaultPage: spiMenu ? "1900" : null,
        _key: crypto.randomUUID()
      });
      filter = "";
      modalContent.querySelector('[name="bulkMenuSearch"]').value = "";
      render();
      tableBody.lastElementChild?.scrollIntoView({ block: "center" });
    };
    render();
  } catch (error) {
    toast(error.message, true);
  }
}

async function showMmbMenuEntryEditor(index, menu, entry, installedEntries, clone = false) {
  const pane = panes[index];
  const entryIndex = installedEntries.indexOf(entry);
  if (entryIndex < 0) return;
  const spiMenu = menu.menuType === "spi-game-menu";
  const initialTitle = clone ? `${entry.title} 2` : entry.title;
  let recommendedPage = entry.page;
  modal.close();
  try {
    const slotData = await paneOperation(index, "Reading MMB disk titles…", () =>
      api(`/api/images/${pane.image.id}/slots`));
    const slots = slotData.slots.filter(item => item.formatted && item.slot !== menu.menuSlot);
    const matchingSlot = () => slots.find(item =>
      String(item.name).toLocaleLowerCase() === String(diskSelect.value).toLocaleLowerCase());
    const loadLaunchers = async () => {
      if (spiMenu) return;
      const slot = matchingSlot();
      launchSelect.innerHTML = '<option value="">Reading catalogue…</option>';
      launchSelect.disabled = true;
      if (!slot) {
        launchSelect.innerHTML = '<option value="">Choose a valid MMB disk</option>';
        return;
      }
      try {
        const query = new URLSearchParams({ path: "$", slot: slot.slot });
        const listing = await api(`/api/images/${pane.image.id}/tree?${query}`);
        const names = listing.entries
          .filter(item => !["dir", "directory"].includes(item.type))
          .map(item => item.name);
        if (entry.filename && !names.some(name => name.toLocaleLowerCase() === entry.filename.toLocaleLowerCase())) {
          names.unshift(entry.filename);
        }
        launchSelect.innerHTML = names.length
          ? names.map(name => `<option value="${esc(name)}" ${name.toLocaleLowerCase() === entry.filename.toLocaleLowerCase() ? "selected" : ""}>${esc(name)}</option>`).join("")
          : '<option value="">This disk has no files</option>';
        launchSelect.disabled = !names.length;
        await updateRecommendedPage();
      } catch (error) {
        launchSelect.innerHTML = `<option value="">${esc(error.message)}</option>`;
      }
    };
    const updateRecommendedPage = async () => {
      if (spiMenu || !launchSelect?.value) return;
      const slot = matchingSlot();
      if (!slot) return;
      const result = await mmbRecommendedPage(
        pane.image.id,
        slot.slot,
        launchSelect.value,
        modalContent.querySelector('[name="action"]')?.value || ""
      );
      const pageInput = modalContent.querySelector('[name="page"]');
      if (result.page) {
        recommendedPage = result.page;
        pageInput.value = result.page;
        pageInput.title = `Recommended from disk image: ${result.evidence}`;
      } else {
        recommendedPage = null;
        pageInput.title = result.evidence;
      }
    };

    showModal(`
      <h2>${clone ? "Clone" : "Edit"} ${spiMenu ? "SPI Game Menu" : "Universal Menu"} entry</h2>
      <p>${clone ? "The new title starts on the same MMB disk and retains the existing launch settings. All four menu database files are then replaced together." : "Changes are checked against the selected MMB disk before all four menu database files are replaced together."}</p>
      <div class="field"><label>Display title</label><input name="title" value="${esc(initialTitle)}" required></div>
      <div class="field"><label>Publisher</label><input name="publisher" value="${esc(entry.publisher || "")}"></div>
      <div class="field"><label>MMB disk</label><select name="diskTitle" required>
        ${slots.map(slot => `<option value="${esc(slot.name)}" ${slot.name.toLocaleLowerCase() === entry.diskTitle.toLocaleLowerCase() ? "selected" : ""}>Slot ${slot.slot} · ${esc(slot.name)}</option>`).join("")}
      </select></div>
      ${spiMenu ? '<div class="help-note">SPI entries launch the selected disk\'s <code>!BOOT</code>. Only the title, publisher and disk need to differ.</div>' : `<div class="menu-fields">
        <div class="field"><label>Launch file</label><select name="filename" required><option value="">Reading catalogue…</option></select></div>
        <div class="field"><label>Action</label><select name="action">
          <option value="" ${entry.action === "" ? "selected" : ""}>CHAIN</option>
          <option value="R" ${entry.action === "R" ? "selected" : ""}>RUN</option>
          <option value="E" ${entry.action === "E" ? "selected" : ""}>EXEC</option>
          <option value="L" ${entry.action === "L" ? "selected" : ""}>LOAD</option>
        </select></div>
        <div class="field"><label>PAGE (hex)</label><input name="page" maxlength="4" pattern="[0-9A-Fa-f]{1,4}" value="${esc(entry.page || "1900")}" required></div>
      </div>`}
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="save">${clone ? "Add cloned entry" : "Save entry"}</button></div>`,
    async form => {
      if (!spiMenu && !await confirmPageOverride(
        recommendedPage, form.get("page"), form.get("title")
      )) return false;
      const changedEntry = {
        ...entry,
        title: form.get("title"),
        publisher: form.get("publisher"),
        diskTitle: form.get("diskTitle"),
        filename: spiMenu ? "!BOOT" : form.get("filename"),
        action: spiMenu ? "E" : form.get("action"),
        page: spiMenu ? "1900" : form.get("page")
      };
      const edited = installedEntries.slice();
      if (clone) edited.splice(entryIndex + 1, 0, changedEntry);
      else edited[entryIndex] = changedEntry;
      const result = await saveMmbMenuEntries(index, installedEntries, edited, `Validating and ${clone ? "adding" : "saving"} menu entry…`);
      toast(`${clone ? "Added" : "Saved"} ${form.get("title")} · ${result.entries} menu entries`);
      previewMenuAfterCurrentDialog(index, form.get("title"));
    });
    const diskSelect = modalContent.querySelector('[name="diskTitle"]');
    const launchSelect = modalContent.querySelector('[name="filename"]');
    diskSelect.onchange = loadLaunchers;
    launchSelect.onchange = updateRecommendedPage;
    modalContent.querySelector('[name="action"]')?.addEventListener("change", updateRecommendedPage);
    await loadLaunchers();
  } catch (error) {
    toast(error.message, true);
  }
}

async function removeMmbMenuEntry(index, menu, entry, installedEntries) {
  const entryIndex = installedEntries.indexOf(entry);
  if (entryIndex < 0 || !confirm(`Remove “${entry.title}” from the Universal Menu? The disk remains in its MMB slot.`)) return;
  modal.close();
  try {
    const edited = installedEntries.filter((_item, offset) => offset !== entryIndex);
    const result = await saveMmbMenuEntries(index, installedEntries, edited, "Removing Universal Menu entry…");
    toast(`${entry.title} removed; ${result.entries} menu entries remain`);
    showMenuPreview(index);
  } catch (error) {
    toast(error.message, true);
  }
}

async function setupMmbMenu(index) {
  const pane = panes[index];
  let otherMenus = [];
  try {
    const current = await api(`/api/images/${pane.image.id}/menu`);
    if (current.configured) return showMmbMenuMaintenance(index, current);
    const candidates = await Promise.all(otherPaneIndexes(index)
      .filter(offset => panes[offset].image?.kind === "mmb")
      .map(async offset => {
        const image = panes[offset].image;
        const detected = await api(`/api/images/${image.id}/menu`);
        if (!detected.configured) return [];
        const menus = detected.menus?.length
          ? detected.menus
          : [{ slot: detected.menuSlot, type: detected.menuType }];
        return menus.map(menu => ({ ...menu, image: image.id, pane: offset, imageName: image.name }));
      }));
    otherMenus = candidates.flat();
  } catch (error) {
    return toast(error.message, true);
  }
  const firstEmpty = pane.entries.find(item => item.empty)?.slot;
  if (firstEmpty == null) return toast("The MMB has no empty slot for a menu disk.", true);
  showModal(`
    <h2>Create an MMB menu</h2>
    <p>Choose the menu appropriate for the target machine, then reserve an empty slot for it.</p>
    <div class="field"><label>Menu</label><select name="menuType">
      <option value="universal">Games Universal Menu · editable launch metadata</option>
      <option value="spi-game-menu">SPI Game Menu · Electron MMFS · launches each disk's !BOOT</option>
      <option value="electron-magazine">Electron User / Magazine Menu</option>
      <option value="acorn-user">Acorn User Menu</option>
      ${otherMenus.map(menu => `<option value="copy-other:${menu.image}:${menu.slot}">Copy ${esc(menuTypeLabel(menu.type))} · pane ${menu.pane + 1} · ${esc(menu.imageName)} · slot ${menu.slot}</option>`).join("")}
    </select></div>
    <div class="field universal-menu-page"><label>Universal Menu launch PAGE</label><select name="menuPage">${universalPageOptions("current")}</select>
      <small>Choose &amp;E00 only for paged or sideways-RAM MMFS. An ordinary EMMFS build needs its natural PAGE and cannot safely run this larger Universal Menu.</small></div>
    <div class="help-note"><strong>Games Universal Menu</strong> stores a launch file, action and PAGE for each title. <strong>SPI Game Menu</strong> is the Ray Harper Electron menu and launches the selected disk's !BOOT. Both support several titles on one disk.</div>
    <div class="field"><label>Reserved menu slot</label><input name="menuSlot" type="number" min="0" max="510" value="${firstEmpty}" required></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="install">Create menu</button></div>`,
  async form => {
    const selectedMenu = String(form.get("menuType"));
    const copying = selectedMenu.startsWith("copy-other:");
    const [_copy, sourceImage, sourceSlot] = selectedMenu.split(":");
    const data = await paneOperation(index, "Installing MMB menu…", () => api(`/api/images/${pane.image.id}/menu/install`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        menuSlot: Number(form.get("menuSlot")),
        menuType: copying ? "copy-other" : selectedMenu,
        menuPage: form.get("menuPage"),
        sourceImage: copying ? sourceImage : null,
        sourceMenuSlot: copying ? Number(sourceSlot) : null
      })
    }));
    pane.image = data.image;
    await acceptImage(index, pane.image);
    setSelection(panes[index], [String(data.menuSlot)], String(data.menuSlot));
    renderPane(index);
    toast(`${menuTypeLabel(data.menuType)} created in reserved slot ${data.menuSlot}`);
    const existingDisks = panes[index].entries.filter(item =>
      item.formatted && Number(item.slot) !== Number(data.menuSlot)
      && !String(item.name).toUpperCase().startsWith("MBACKUP-")
    ).length;
    if (existingDisks && ["universal", "universal-4r", "spi-game-menu"].includes(data.menuType)) {
      modal.addEventListener("close", () => {
        setTimeout(() => scanMmbMenu(index, "missing"), 0);
      }, { once: true });
    }
  });
  const menuTypeSelect = modalContent.querySelector('[name="menuType"]');
  const pageField = modalContent.querySelector(".universal-menu-page");
  const updatePageVisibility = () => {
    pageField.hidden = menuTypeSelect.value !== "universal";
  };
  menuTypeSelect.addEventListener("change", updatePageVisibility);
  updatePageVisibility();
}

function menuTypeLabel(menuType) {
  return {
    universal: "Games Universal Menu",
    "universal-4r": "Universal Menu 4R",
    "spi-game-menu": "SPI Game Menu",
    "electron-magazine": "Electron User / Magazine Menu",
    "acorn-user": "Acorn User Menu",
    "mmc-desktop": "MMC Desktop 3"
  }[menuType] || "MMB menu";
}

function universalPageOptions(selected = "current") {
  return [
    ["current", "Keep the current BASIC PAGE"],
    ["E00", "&E00 · paged / sideways-RAM MMFS"],
    ["800", "&800 · DataCentre / verified low-PAGE setup"]
  ].map(([value, label]) =>
    `<option value="${value}" ${String(selected).toUpperCase() === value.toUpperCase() ? "selected" : ""}>${label}</option>`
  ).join("");
}

function showMmbMenuMaintenance(index, current) {
  if (!["universal", "universal-4r", "spi-game-menu"].includes(current.menuType)) {
    const canRefresh = current.menuType === "mmc-desktop";
    return showModal(`
      <h2>${esc(menuTypeLabel(current.menuType))}</h2>
      <p>This menu is installed in slot ${current.menuSlot}. It is a catalogue browser rather than a Games Universal Menu launch database.</p>
      <div class="help-note">Files copied from this MMB are still analysed for !BOOT, LOADER, MENU and other conventional launchers. Ambiguous software can be checked online or reviewed manually.</div>
      <div class="modal-actions"><button class="button ${canRefresh ? "ghost" : "primary"}" value="cancel">Close</button>${canRefresh ? '<button class="button primary" value="refresh">Refresh catalogue</button>' : ""}</div>`,
    async () => {
      if (!canRefresh) return;
      const data = await paneOperation(index, "Refreshing MMC Desktop catalogue…", () => api(`/api/images/${panes[index].image.id}/menu/refresh`, {
        method: "POST"
      }));
      panes[index].image = data.image;
      await loadDirectory(index);
      toast(`MMC Desktop catalogue refreshed with ${data.entries} formatted slots`);
    });
  }
  showModal(`
    <h2>Maintain MMB menu</h2>
    <p>The menu is in slot ${current.menuSlot} with ${current.entries.length} entries. Scan only omitted disks, or regenerate the databases from every formatted non-menu slot.</p>
    <div class="field"><label>Operation</label><select name="mode">
      <option value="missing">Add previously unlisted disks</option>
      <option value="all">Regenerate the complete menu</option>
    </select></div>
    ${current.menuType === "universal" ? `<div class="field"><label>Universal Menu launch PAGE</label><select name="menuPage">${universalPageOptions(current.menuPage)}</select>
      <small>&amp;E00 is safe for paged or sideways-RAM MMFS. Do not force it with ordinary EMMFS.</small></div>` : ""}
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button ghost backup-installed-menu" type="button">Backup slot</button>${["universal", "universal-4r"].includes(current.menuType) ? '<button class="button ghost audit-installed-pages" type="button">Audit PAGE</button>' : ""}${current.menuType === "universal" ? '<button class="button ghost set-menu-page" type="button">Apply boot PAGE</button>' : ""}<button class="button ghost edit-installed-menu" type="button">Bulk edit entries</button><button class="button primary" value="scan">Scan disks</button></div>`,
  form => scanMmbMenu(index, form.get("mode")));
  modalContent.querySelector(".set-menu-page")?.addEventListener("click", async () => {
    try {
      const menuPage = modalContent.querySelector('[name="menuPage"]').value;
      const data = await paneOperation(index, "Updating Universal Menu boot PAGE…", () => api(`/api/images/${panes[index].image.id}/menu/page`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ menuPage })
      }));
      panes[index].image = data.image;
      modal.close();
      toast(`Universal Menu boot now uses ${data.menuPage === "current" ? "the current BASIC PAGE" : `PAGE=&${data.menuPage}`}`);
    } catch (error) {
      toast(error.message, true);
    }
  });
  modalContent.querySelector(".edit-installed-menu").onclick = () => {
    modal.close();
    setTimeout(async () => {
      try {
        const data = await paneOperation(index, "Reading the installed menu databases…", () =>
          api(`/api/images/${panes[index].image.id}/menu/preview`));
        showMmbBulkMenuEditor(index, data, data.entries || []);
      } catch (error) {
        toast(error.message, true);
      }
    }, 0);
  };
  modalContent.querySelector(".audit-installed-pages")?.addEventListener("click", () => {
    modal.close();
    setTimeout(() => auditMmbMenuPages(index), 0);
  });
  modalContent.querySelector(".backup-installed-menu")?.addEventListener("click", () => {
    modal.close();
    setTimeout(() => backupMmbMenuSlot(index), 0);
  });
}

function showMmbPageAuditResult(result) {
  const unresolved = result.unresolved || [];
  const corrections = result.corrections || [];
  showModal(`
    <h2>${result.menuType === "adfs-universal" ? "ADFS" : "MMB"} PAGE audit complete</h2>
    <p>${result.rewritten ? "The menu databases were repaired and validated." : "No rewrite was needed; the menu disk still passed validation."}</p>
    <div class="operation-summary">
      <span><b>${result.entries}</b><small>Menu entries</small></span>
      <span><b>${result.verified}</b><small>PAGE verified</small></span>
      <span><b>${result.corrected}</b><small>Values corrected</small></span>
      <span><b>${result.encodingRepairs}</b><small>Record encodings repaired</small></span>
      <span><b>${result.programRepairs || 0}</b><small>Menu program updated</small></span>
      <span><b>${result.notApplicable}</b><small>PAGE not applicable</small></span>
      <span><b>${unresolved.length}</b><small>Need review</small></span>
    </div>
    ${corrections.length ? `<div class="scan-notes">${corrections.slice(0, 12).map(item =>
      `<span>${item.slot != null ? `Slot ${item.slot} · ` : `${esc(item.path)} · `}${esc(item.title)}: &amp;${esc(item.from)} → &amp;${esc(item.to)}</span>`
    ).join("")}${corrections.length > 12 ? `<span>${corrections.length - 12} more corrections were applied.</span>` : ""}</div>` : ""}
    ${unresolved.length ? `<div class="help-warning"><strong>Manual review needed:</strong><ul>${unresolved.slice(0, 12).map(item =>
      `<li>${item.slot != null ? `Slot ${item.slot} · ` : item.path ? `${esc(item.path)} · ` : ""}${esc(item.title || item.diskTitle)}: ${esc(item.reason)}</li>`
    ).join("")}</ul>${unresolved.length > 12 ? `<p>${unresolved.length - 12} more unresolved entries are not shown here.</p>` : ""}</div>` : '<div class="help-note"><strong>Complete:</strong> no CHAIN or EXEC entries remain unresolved.</div>'}
    <div class="help-note"><strong>Validation:</strong> ${esc(result.validation)}. Full PAGE addresses remain visible in the editor; the Universal Menu database uses its required compact high-byte representation.</div>
    <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div>`);
}

async function menuSlotChoices(index) {
  const pane = panes[index];
  const data = await paneOperation(index, "Reading MMB slots…", () =>
    api(`/api/images/${pane.image.id}/slots`));
  return data.slots;
}

async function backupMmbMenuSlot(index) {
  const pane = panes[index];
  if (!pane?.image || pane.image.kind !== "mmb") return;
  try {
    const slots = await menuSlotChoices(index);
    const empty = slots.filter(item => item.empty);
    if (!empty.length) return toast("The MMB has no empty slot for a menu backup.", true);
    showModal(`
      <h2>Backup the installed menu slot</h2>
      <p>Copy the complete active menu disk into another MMB slot without changing the active drive-0 menu.</p>
      <div class="field"><label>Empty destination slot</label><select name="destinationSlot">
        ${empty.map(item => `<option value="${item.slot}">Slot ${item.slot} · Empty</option>`).join("")}
      </select></div>
      <div class="help-note"><strong>Safe backup:</strong> the copy is labelled <code>MBACKUP-xxx</code>, marked read-only, excluded from installed-menu detection and omitted from menu scans. It remains part of the saved MMB image.</div>
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="backup">Create backup</button></div>`,
    async form => {
      const result = await paneOperation(index, "Copying the complete menu slot…", () =>
        api(`/api/images/${pane.image.id}/menu/backup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ destinationSlot: Number(form.get("destinationSlot")) })
        }));
      pane.image = result.image;
      await acceptImage(index, pane.image);
      toast(`Menu slot ${result.menuSlot} backed up to read-only slot ${result.backupSlot} · ${result.backupTitle}`);
    });
  } catch (error) {
    toast(error.message, true);
  }
}

async function restoreMmbMenuSlot(index) {
  const pane = panes[index];
  if (!pane?.image || pane.image.kind !== "mmb") return;
  try {
    const slots = await menuSlotChoices(index);
    const backups = slots.filter(item =>
      item.formatted && String(item.name).toUpperCase().startsWith("MBACKUP-"));
    if (!backups.length) return toast("This MMB has no labelled menu-slot backups.", true);
    showModal(`
      <h2>Restore a menu-slot backup</h2>
      <p>Replace the active menu disk with a previously created backup. The backup slot itself is retained.</p>
      <div class="field"><label>Backup slot</label><select name="backupSlot">
        ${backups.map(item => `<option value="${item.slot}">Slot ${item.slot} · ${esc(item.name)}</option>`).join("")}
      </select></div>
      <div class="help-warning"><strong>This replaces the current active menu slot.</strong> The operation validates the restored disk and rolls back automatically if validation fails. Create a named checkpoint first if the current menu contains changes you may need.</div>
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="restore">Restore backup</button></div>`,
    async form => {
      const result = await paneOperation(index, "Restoring and validating the menu backup…", () =>
        api(`/api/images/${pane.image.id}/menu/restore`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ backupSlot: Number(form.get("backupSlot")) })
        }));
      pane.image = result.image;
      await acceptImage(index, pane.image);
      toast(`Menu restored from slot ${result.backupSlot}; active slot ${result.menuSlot} validated`);
    });
  } catch (error) {
    toast(error.message, true);
  }
}

function auditAdfsMenuPages(index) {
  const pane = panes[index];
  if (!pane?.image || pane.image.kind !== "adfs") return;
  const root = pane.path;
  showModal(`
    <h2>Audit ADFS menu PAGE values</h2>
    <p>Check the installed directory menu in ${esc(root)} against every selected launch file, repair provable PAGE values and legacy record encodings, then validate the complete ADFS image.</p>
    <div class="help-note"><strong>Current menu only:</strong> navigate to another directory containing a menu and run this action again to audit that menu. Ambiguous launchers remain unchanged and are reported for review.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="audit">Audit and repair</button></div>`,
  async () => {
    const result = await paneOperation(index, {
      title: `Auditing the ADFS menu in ${root}`,
      message: "Following launch files, repairing menu records and validating the image…",
      details: [
        { label: "Menu directory", value: root },
        { label: "Safety", value: "Only provable PAGE values are changed" }
      ]
    }, () => api(`/api/images/${pane.image.id}/adfs-menu/page-audit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root })
    }));
    pane.image = result.image;
    await loadDirectory(index);
    setTimeout(() => showMmbPageAuditResult(result), 0);
  });
}

function auditMmbMenuPages(index) {
  const pane = panes[index];
  if (!pane?.image || pane.image.kind !== "mmb") return;
  showModal(`
    <h2>Audit Universal Menu PAGE values</h2>
    <p>Check every menu entry against the actual launcher in its MMB slot, repair values that can be proved, normalise legacy database encoding, then validate the menu disk.</p>
    <div class="help-note"><strong>Automatic and conservative:</strong> CHAIN programs use their saved BASIC address and EXEC command files are followed to their launch target. Machine-code, RUN and LOAD entries are reported as not PAGE-dependent. Ambiguous launchers are listed for manual review instead of guessed.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="audit">Audit and repair</button></div>`,
  async () => {
    const result = await paneOperation(index, {
      title: "Auditing MMB launch PAGE values",
      message: "Reading disk catalogues, following launchers and validating the menu disk…",
      details: [
        { label: "Image", value: pane.image.name },
        { label: "Safety", value: "Only provable PAGE values are changed" }
      ]
    }, () => api(`/api/images/${pane.image.id}/menu/page-audit`, { method: "POST" }));
    pane.image = result.image;
    await acceptImage(index, pane.image);
    setTimeout(() => showMmbPageAuditResult(result), 0);
  });
}

async function scanMmbMenu(index, mode) {
  const pane = panes[index];
  modal.close();
  setLoading(index, true, mode === "missing" ? "Scanning for off-menu disks…" : "Scanning all MMB disks…");
  let data;
  try {
    data = await api(`/api/images/${pane.image.id}/mmb-menu/scan`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, online: true })
    });
  } catch (error) {
    pane.loading = false;
    renderPane(index);
    return toast(error.message, true);
  }
  pane.loading = false;
  renderPane(index);
  if (!data.entries.length) return toast(mode === "missing" ? "Every formatted disk is already represented in the menu." : "There are no formatted disks to add.");
  const spiMenu = data.menuType === "spi-game-menu";
  showModal(`
    <div class="batch-menu">
      <h2>${mode === "missing" ? "Add missing menu entries" : "Regenerate complete MMB menu"}</h2>
      <p>Review the scan. Untick any disk that should remain off-menu.</p>
      <div class="batch-head mmb ${spiMenu ? "spi" : ""}"><span>Use</span><span>Slot / title</span><span>Publisher</span>${spiMenu ? "" : "<span>Launch</span><span>Action</span>"}</div>
      <div class="batch-rows">
      ${data.entries.map((item, offset) => `
        <div class="batch-row mmb ${spiMenu ? "spi" : ""}" data-entry="${offset}">
          <input class="include-entry" type="checkbox" name="include-${offset}" checked aria-label="Include slot ${item.slot}">
          <div>
            <small>Slot ${item.slot} · ${esc(item.diskTitle)}</small>
            <input name="title-${offset}" value="${esc(item.title)}">
            ${item.matches?.length ? `<select class="batch-match" data-offset="${offset}">
              <option value="">Online matches…</option>
              ${item.matches.map((match, matchIndex) => `<option value="${matchIndex}">${esc(match.title)} · ${esc(match.publisher)}</option>`).join("")}
            </select>` : ""}
          </div>
          <input name="publisher-${offset}" value="${esc(item.publisher)}" placeholder="Unknown">
          ${spiMenu ? "" : `<input name="filename-${offset}" maxlength="7" value="${esc(item.filename)}">
          <select name="action-${offset}">
            <option value="" ${item.action === "" ? "selected" : ""}>CHAIN</option>
            <option value="R" ${item.action === "R" ? "selected" : ""}>RUN</option>
            <option value="E" ${item.action === "E" ? "selected" : ""}>EXEC</option>
            <option value="L" ${item.action === "L" ? "selected" : ""}>LOAD</option>
          </select>`}
          ${item.ambiguous ? `<small class="ambiguous">Review · ${item.confidence}%</small>` : `<small class="confident">${item.confidence}%</small>`}
        </div>`).join("")}
      </div>
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="save">${mode === "missing" ? "Add selected" : "Replace menu"}</button></div>
    </div>`,
  async form => {
    const entries = data.entries.flatMap((item, offset) => form.get(`include-${offset}`) ? [{
      title: form.get(`title-${offset}`),
      publisher: form.get(`publisher-${offset}`),
      filename: spiMenu ? "!BOOT" : form.get(`filename-${offset}`),
      action: spiMenu ? "E" : form.get(`action-${offset}`),
      page: item.page,
      diskTitle: item.diskTitle,
      system: "M"
    }] : []);
    const result = await paneOperation(index, mode === "missing" ? "Adding menu entries…" : "Regenerating MMB menu…", () => api(`/api/images/${pane.image.id}/mmb-menu/rebuild`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, entries })
    }));
    pane.image = result.image;
    await acceptImage(index, pane.image);
    toast(`MMB menu now contains ${result.entries} entries`);
    previewMenuAfterCurrentDialog(index, entries.at(-1)?.diskTitle || "");
  });
  modalContent.querySelectorAll(".batch-match").forEach(select => {
    select.onchange = () => {
      if (select.value === "") return;
      const offset = Number(select.dataset.offset);
      const match = data.entries[offset].matches[Number(select.value)];
      modalContent.querySelector(`[name="title-${offset}"]`).value = match.title;
      modalContent.querySelector(`[name="publisher-${offset}"]`).value = match.publisher;
    };
  });
}

async function scanMenuEntry(index) {
  const pane = panes[index];
  const entry = selectedEntry(index);
  if (!entry?.formatted) return;
  try {
    const data = await paneOperation(index, "Analysing disk metadata…", () => api(`/api/images/${pane.image.id}/metadata/scan`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot: entry.slot, online: true })
    }));
    await reviewMenuMetadata(index, data.metadata);
  } catch (error) { toast(error.message, true); }
}

async function reviewMenuMetadata(index, metadata, previewAfter = true, batch = null) {
  const pane = panes[index];
  let menu = { configured: false, menuSlot: null };
  try { menu = await api(`/api/images/${pane.image.id}/menu`); } catch (_) {}
  const firstEmpty = pane.entries.find(item => item.empty && item.slot !== metadata.slot)?.slot ?? 0;
  const menuSlot = menu.configured ? menu.menuSlot : firstEmpty;
  const matches = metadata.matches || [];
  const evidence = [...(metadata.evidence || []), ...(metadata.warnings || [])];
  const spiMenu = menu.menuType === "spi-game-menu";
  let recommendedPage = metadata.page;
  const defaultEntry = {
    title: metadata.title,
    publisher: metadata.publisher,
    filename: spiMenu ? "!BOOT" : metadata.filename,
    action: spiMenu ? "E" : metadata.action,
    page: spiMenu ? "1900" : (metadata.page || "1900"),
    diskTitle: metadata.diskTitle,
    system: "M",
  };
  if (batch?.acceptAll) {
    await saveMmbMenuMetadata(index, metadata, menuSlot, defaultEntry, false, spiMenu);
    return false;
  }
  const canApplyAll = batch?.total > batch?.current;
  const closed = showModal(`
    <h2>Add disk to MMB menu</h2>
    <p>Review the detected ${spiMenu ? "title and publisher" : "launch details"} before the menu database is changed. Confidence: ${metadata.confidence}%.
      ${metadata.ambiguous ? "This disk was ambiguous, so the online Acorn and homebrew catalogues were checked." : ""}</p>
    ${matches.length ? `<div class="field"><label>Online matches</label><select name="match">
      <option value="">Keep the detected values</option>
      ${matches.map((item, offset) => `<option value="${offset}">${esc(item.title)}${item.publisher ? ` · ${esc(item.publisher)}` : ""}${item.year ? ` (${esc(item.year)})` : ""}</option>`).join("")}
    </select></div>` : ""}
    <div class="field"><label>Display title</label><input name="title" value="${esc(metadata.title)}" required></div>
    <div class="field"><label>Publisher</label><input name="publisher" value="${esc(metadata.publisher)}"></div>
    ${spiMenu ? '<div class="help-note"><strong>SPI launch:</strong> this entry will select the MMB disk and execute its !BOOT file.</div>' : `<div class="menu-fields">
      <div class="field"><label>Launch file</label><input name="filename" maxlength="7" value="${esc(metadata.filename)}" required></div>
      <div class="field"><label>Action</label><select name="action">
        <option value="" ${metadata.action === "" ? "selected" : ""}>CHAIN</option>
        <option value="R" ${metadata.action === "R" ? "selected" : ""}>RUN</option>
        <option value="E" ${metadata.action === "E" ? "selected" : ""}>EXEC</option>
        <option value="L" ${metadata.action === "L" ? "selected" : ""}>LOAD</option>
      </select></div>
      <div class="field"><label>PAGE (hex address)</label><input name="page" maxlength="4" value="${esc(metadata.page || "1900")}" required></div>
    </div>`}
    <div class="field"><label>Unique MMB disk title</label><input name="diskTitle" maxlength="12" value="${esc(metadata.diskTitle)}" required></div>
    <div class="field"><label>Menu disk slot</label><input name="menuSlot" type="number" min="0" max="510" value="${menuSlot}" ${menu.configured ? "readonly" : ""} required></div>
    ${evidence.length ? `<div class="scan-notes">${evidence.map(item => `<span>${esc(item)}</span>`).join("")}</div>` : ""}
    ${metadata.sources?.length ? `<div class="source-links">${metadata.sources.map(item => `<a href="${esc(item.url)}" target="_blank" rel="noreferrer">${esc(item.label)}</a>`).join("")}</div>` : ""}
    <input type="hidden" name="applyRemaining" value="no">
    <div class="modal-actions"><button class="button ghost" value="cancel">Keep off-menu</button>${canApplyAll ? '<button class="button ghost apply-menu-all" value="save">Update and accept all remaining</button>' : ""}<button class="button primary" value="save">Update menu</button></div>`,
  async form => {
    const matchValue = form.get("match");
    const selectedMatch = matchValue === "" || matchValue === null ? null : matches[Number(matchValue)];
    if (!spiMenu && !await confirmPageOverride(recommendedPage, form.get("page"), metadata.title)) return false;
    const entry = {
      title: selectedMatch?.title || form.get("title"),
      publisher: selectedMatch?.publisher || form.get("publisher"),
      filename: spiMenu ? "!BOOT" : form.get("filename"), action: spiMenu ? "E" : form.get("action"), page: spiMenu ? "1900" : form.get("page"),
      diskTitle: form.get("diskTitle"), system: "M"
    };
    const targetMenuSlot = Number(form.get("menuSlot"));
    if (batch && form.get("applyRemaining") === "yes") batch.acceptAll = true;
    return saveMmbMenuMetadata(index, metadata, targetMenuSlot, entry, previewAfter, spiMenu);
  });
  modalContent.querySelector(".apply-menu-all")?.addEventListener("click", () => {
    modalContent.querySelector('[name="applyRemaining"]').value = "yes";
  });
  const matchSelect = modalContent.querySelector('[name="match"]');
  const refreshRecommendedPage = async () => {
    if (spiMenu) return;
    const filename = modalContent.querySelector('[name="filename"]')?.value;
    if (!filename) return;
    try {
      const result = await mmbRecommendedPage(
        pane.image.id,
        metadata.slot,
        filename,
        modalContent.querySelector('[name="action"]')?.value || ""
      );
      const pageInput = modalContent.querySelector('[name="page"]');
      if (result.page) {
        recommendedPage = result.page;
        pageInput.value = result.page;
        pageInput.title = `Recommended from disk image: ${result.evidence}`;
      } else {
        recommendedPage = null;
        pageInput.title = result.evidence;
      }
    } catch (error) {
      toast(`Could not inspect PAGE: ${error.message}`, true);
    }
  };
  modalContent.querySelector('[name="filename"]')?.addEventListener("change", refreshRecommendedPage);
  modalContent.querySelector('[name="action"]')?.addEventListener("change", refreshRecommendedPage);
  matchSelect?.addEventListener("change", () => {
    const selected = matches[Number(matchSelect.value)];
    if (!selected || matchSelect.value === "") return;
    modalContent.querySelector('[name="title"]').value = selected.title;
    modalContent.querySelector('[name="publisher"]').value = selected.publisher;
  });
  return Boolean(closed);
}

async function saveMmbMenuMetadata(index, metadata, menuSlot, entry, previewAfter, spiMenu) {
  const pane = panes[index];
  const action = { "": "CHAIN", R: "RUN", E: "EXEC", L: "LOAD" }[entry.action] || entry.action;
  const data = await paneOperation(index, {
    title: `Updating the MMB menu in slot ${menuSlot}`,
    message: `Adding “${entry.title}” and rebuilding the ${spiMenu ? "SPI Game Menu" : "Universal Menu"} databases and indexes.`,
    details: [
      { label: "Disk title", value: entry.diskTitle },
      { label: "Source slot", value: String(metadata.slot) },
      { label: "Launch command", value: spiMenu ? `*DIN 0 ${entry.diskTitle} then *EXEC !BOOT` : `*${action} ${entry.filename}` },
      { label: "Current stage", value: "Writing title and publisher records" },
    ],
  }, () => api(`/api/images/${pane.image.id}/menu/entry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ menuSlot, metadata: entry }),
  }));
  pane.image = data.image;
  await acceptImage(index, pane.image);
  toast(`${entry.title} added to the menu in slot ${data.menuSlot}`);
  if (previewAfter) previewMenuAfterCurrentDialog(index, entry.diskTitle || entry.title);
}

async function buildAdfsMenu(index) {
  const pane = panes[index];
  setLoading(index, true, "Scanning ADFS child directories…");
  let data;
  try {
    data = await api(`/api/images/${pane.image.id}/adfs-menu/scan`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root: pane.path, online: true })
    });
  } catch (error) {
    pane.loading = false;
    renderPane(index);
    return toast(error.message, true);
  }
  pane.loading = false;
  renderPane(index);
  if (!data.entries.length) return toast("This directory has no child directories to add to a menu.", true);
  const holderSummary = data.holders?.length
    ? `<div class="help-note"><strong>Structural groups skipped:</strong> ${data.holders.map(esc).join(", ")}. Their ${data.entries.length} contained disk directories are the menu entries.</div>`
    : "";
  showModal(`
    <div class="batch-menu">
      <h2>Create ADFS directory menu</h2>
      <p>The menu will be installed in ${esc(data.root)}. Review each software directory’s launch details; unrelated files and structural holder directories are left off-menu.</p>
      ${holderSummary}
      <div class="batch-head"><span>Directory / title</span><span>Publisher</span><span>Launch</span><span>Action</span></div>
      <div class="batch-rows">
      ${data.entries.map((item, offset) => `
        <div class="batch-row" data-entry="${offset}">
          <div>
            <small>${esc(item.path)}</small>
            <input name="title-${offset}" value="${esc(item.title)}" required>
            ${item.matches?.length > 1 ? `<select class="batch-match" data-offset="${offset}">
              <option value="">Online matches…</option>
              ${item.matches.map((match, matchIndex) => `<option value="${matchIndex}">${esc(match.title)} · ${esc(match.publisher)}</option>`).join("")}
            </select>` : ""}
          </div>
          <input name="publisher-${offset}" value="${esc(item.publisher)}" placeholder="Unknown">
          <select name="launchCandidate-${offset}" aria-label="Launch file for ${esc(item.title || item.path)}" required>
            ${launchCandidateOptions(item)}
          </select>
          <select name="action-${offset}">
            <option value="" ${item.action === "" ? "selected" : ""}>CHAIN</option>
            <option value="R" ${item.action === "R" ? "selected" : ""}>RUN</option>
            <option value="E" ${item.action === "E" ? "selected" : ""}>EXEC</option>
            <option value="L" ${item.action === "L" ? "selected" : ""}>LOAD</option>
          </select>
          <input type="hidden" name="page-${offset}" value="${esc(item.page || "1900")}">
          ${item.ambiguous ? `<small class="ambiguous">Needs review · ${item.confidence}% confidence</small>` : `<small class="confident">${item.confidence}% confidence</small>`}
        </div>`).join("")}
      </div>
      <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="create">Create / update menu</button></div>
    </div>`,
  async form => {
    const entries = data.entries.map((item, offset) => {
      const candidate = (item.launchCandidates || [])[Number(form.get(`launchCandidate-${offset}`))];
      if (!candidate) throw new Error(`Choose a launch file for ${item.title || item.path}.`);
      return {
        title: form.get(`title-${offset}`),
        publisher: form.get(`publisher-${offset}`),
        filename: candidate.name,
        action: form.get(`action-${offset}`),
        page: form.get(`page-${offset}`),
        path: candidate.path,
        system: "H"
      };
    });
    const progress = {
      title: `Updating the ADFS menu in ${data.root}`,
      message: `Writing ${entries.length} menu ${entries.length === 1 ? "entry" : "entries"} and rebuilding the databases and indexes.`,
      details: [
        { label: "Menu location", value: data.root },
        { label: "Directories", value: String(entries.length) },
        { label: "Current stage", value: "Writing support files, title data and publisher data" }
      ]
    };
    const result = await paneOperation(index, progress, () =>
      retryableMenuWrite(
        index,
        `/api/images/${pane.image.id}/adfs-menu/create`,
        { root: data.root, entries },
        progress
      ));
    pane.image = result.image;
    await loadDirectory(index);
    toast(`ADFS menu created for ${result.entries} directories`);
    previewMenuAfterCurrentDialog(index, entries.at(-1)?.path || "");
  });
  modalContent.querySelectorAll(".batch-match").forEach(select => {
    select.onchange = () => {
      if (select.value === "") return;
      const offset = Number(select.dataset.offset);
      const match = data.entries[offset].matches[Number(select.value)];
      modalContent.querySelector(`[name="title-${offset}"]`).value = match.title;
      modalContent.querySelector(`[name="publisher-${offset}"]`).value = match.publisher;
    };
  });
}

function compactImage(index) {
  const pane = panes[index];
  const supportsOrder = pane.image.kind === "dfs" || pane.image.kind === "mmb";
  showModal(`
    <h2>Compact this filesystem?</h2>
    <p>Files will be reorganised into contiguous low sectors and free space consolidated. The operation is performed only on the working copy.</p>
    ${supportsOrder ? '<div class="field"><label>Place these paths first (optional, comma separated)</label><input name="order" placeholder="$.!BOOT,$.LOADER"></div>' : ""}
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="compact">Compact</button></div>`,
  async form => {
    const data = await paneOperation(index, "Compacting filesystem…", () => api(`/api/images/${pane.image.id}/compact`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot: pane.slot, order: supportsOrder ? (form.get("order") || null) : null })
    }));
    pane.image = data.image;
    await loadDirectory(index);
    toast(data.message);
  });
}

function convertTape(index) {
  const pane = panes[index];
  const defaultTarget = preferredDestinationPane(index);
  showModal(`
    <h2>Convert UEF tape to disk</h2>
    <p>The tape is analysed before conversion. Unusable names are inferred, BASIC loader calls that depend on tape order are rewritten to their final DFS names, and a bootable <code>!BOOT</code> is created. Anything that cannot be repaired safely is reported as a warning.</p>
    <div class="field"><label>Destination format</label><select name="format">
      <option value="ssd">SSD · single-sided DFS</option>
      <option value="dsd">DSD · double-sided DFS</option>
    </select></div>
    <div class="field"><label>Open converted disk in</label><select name="targetPane">
      ${otherPaneIndexes(index).map(offset => `<option value="${offset}" ${offset === defaultTarget ? "selected" : ""}>${esc(paneLabel(offset))}</option>`).join("")}
    </select><small>An empty pane is preferred. Replacing an edited pane requires confirmation.</small></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="convert">Convert tape</button></div>`,
  async form => {
    const targetIndex = Number(form.get("targetPane"));
    if (!otherPaneIndexes(index).includes(targetIndex)) throw new Error("Choose another pane for the converted disk.");
    if (panes[targetIndex].image?.dirty && !confirm(`Replace ${paneLabel(targetIndex)} without downloading its edited image?`)) return false;
    const data = await paneOperation(index, "Converting tape to DFS disk…", () => api(`/api/images/${pane.image.id}/convert`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ format: form.get("format") })
    }));
    await acceptImage(targetIndex, data.image);
    const tapeFiles = data.files.filter(file => !file.generated);
    const repaired = tapeFiles.filter(file => file.loaderChanges?.length).length;
    toast(`${tapeFiles.length} tape file${tapeFiles.length === 1 ? "" : "s"} converted to ${form.get("format").toUpperCase()}${repaired ? ` · ${repaired} loader${repaired === 1 ? "" : "s"} repaired` : ""}`);
  });
}

function showCreateImageModal(preferredIndex = null) {
  const firstEmpty = panes.findIndex(pane => !pane.image);
  const defaultTarget = preferredIndex ?? (firstEmpty < 0 ? 0 : firstEmpty);
  showModal(`
    <h2>Create a blank image</h2>
    <p>The new image opens as an editable working copy and can be downloaded when ready.</p>
    <div class="field"><label>Open new image in</label><select name="targetPane">
      ${panes.map((_pane, index) => `<option value="${index}" ${index === defaultTarget ? "selected" : ""}>${esc(paneLabel(index))}</option>`).join("")}
    </select><small>An empty pane is preferred. Replacing an edited pane requires confirmation.</small></div>
    <div class="field"><label>Format</label><select name="format">
      <option value="ssd">DFS SSD · 200 KiB</option>
      <option value="dsd">DFS DSD · 400 KiB, two sides</option>
      <option value="hfe-ssd">HFE · DFS single-sided floppy</option>
      <option value="hfe-dsd">HFE · DFS double-sided floppy</option>
      <option value="hfe-adfs-s">HFE · ADFS S floppy</option>
      <option value="hfe-adfs-m">HFE · ADFS M floppy</option>
      <option value="hfe-adfs-l">HFE · ADFS L floppy</option>
      <option value="adfs-s">ADFS S floppy · 160 KiB</option>
      <option value="adfs-m">ADFS M floppy · 320 KiB</option>
      <option value="adfs-l">ADFS L floppy · 640 KiB</option>
      <option value="beebscsi">BeebSCSI ADFS HDD · DAT + DSC</option>
      <option value="adfs-hard">Archimedes / RISC OS virtual HDD · HDF</option>
      <option value="adfs-physical">Raw physical HDD image · RAW</option>
      <option value="mmb">MMB bank · 511 empty slots</option>
    </select></div>
    <div class="field"><label>Disk title</label><input name="title" maxlength="12" value="BLANK" required><small data-title-help></small></div>
    <div class="field"><label>Disk size</label><input name="capacity" value="200 KiB" readonly></div>
    <div class="field"><label>Target hardware</label><select name="targetHardware">
      <option value="auto">Auto / inspect only</option>
      <option value="beebscsi">BeebSCSI DAT + DSC · Electron / BBC / Master</option>
      <option value="electron-plus3">Electron Plus 3 · normal ADFS</option>
      <option value="bbc-master">BBC / Master · normal 8-bit ADFS</option>
      <option value="risc-os">Archimedes / RISC OS</option>
    </select><small data-hardware-help></small></div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="create">Create image</button></div>`,
  async form => {
    const targetIndex = Number(form.get("targetPane"));
    if (!panes[targetIndex]) throw new Error("Choose a valid destination pane.");
    if (panes[targetIndex].image?.dirty && !confirm(`Replace ${paneLabel(targetIndex)} without downloading its edited image?`)) return false;
    const data = await api("/api/images/create", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        format: form.get("format"),
        title: form.get("title") || "BLANK",
        capacity: form.get("capacity"),
        targetHardware: modalContent.querySelector('select[name="targetHardware"]').value || "auto"
      })
    });
    await acceptImage(targetIndex, data.image);
    toast(`${data.image.name} created`);
  });
  const format = modalContent.querySelector('select[name="format"]');
  const capacity = modalContent.querySelector('input[name="capacity"]');
  const capacityLabel = capacity.closest(".field").querySelector("label");
  const title = modalContent.querySelector('input[name="title"]');
  const titleHelp = modalContent.querySelector("[data-title-help]");
  const targetHardware = modalContent.querySelector('select[name="targetHardware"]');
  const hardwareHelp = modalContent.querySelector("[data-hardware-help]");
  const profiles = {
    ssd: { size: "200 KiB", hardware: null },
    dsd: { size: "400 KiB", hardware: null },
    "hfe-ssd": { size: "200 KiB", hardware: null },
    "hfe-dsd": { size: "400 KiB", hardware: null },
    "adfs-s": { size: "160 KiB", hardware: "auto", chooseHardware: true },
    "adfs-m": { size: "320 KiB", hardware: "auto", chooseHardware: true },
    "adfs-l": { size: "640 KiB", hardware: "auto", chooseHardware: true },
    "hfe-adfs-s": { size: "160 KiB", hardware: "auto", chooseHardware: true },
    "hfe-adfs-m": { size: "320 KiB", hardware: "auto", chooseHardware: true },
    "hfe-adfs-l": { size: "640 KiB", hardware: "auto", chooseHardware: true },
    beebscsi: { size: null, defaultCapacity: "20MB", hardware: "beebscsi" },
    "adfs-hard": { size: null, defaultCapacity: "20MB", hardware: "risc-os" },
    "adfs-physical": { size: null, defaultCapacity: "20MB", hardware: "risc-os" },
    mmb: { size: "99.8 MiB (511 × 200 KiB)", hardware: null, hasTitle: false }
  };
  const capacities = new Map();
  let diskTitle = title.value;
  let previousFormat = format.value;
  const updateFormatControls = () => {
    const previousProfile = profiles[previousFormat];
    if (previousProfile && !previousProfile.size) capacities.set(previousFormat, capacity.value);
    if (!title.disabled) diskTitle = title.value;

    const profile = profiles[format.value];
    capacity.readOnly = Boolean(profile.size);
    capacity.value = profile.size || capacities.get(format.value) || profile.defaultCapacity;
    capacity.placeholder = profile.size ? "" : profile.defaultCapacity;
    capacityLabel.textContent = profile.size ? "Disk size" : "Hard disk capacity (DAT/HDF/RAW)";

    const hasTitle = profile.hasTitle !== false;
    title.disabled = !hasTitle;
    title.required = hasTitle;
    title.value = hasTitle ? diskTitle : "Not applicable to an MMB bank";
    titleHelp.textContent = hasTitle
      ? "Stored in the new filesystem."
      : "MMB banks contain separately titled disk slots and have no bank-wide filesystem title.";

    targetHardware.value = profile.hardware || "auto";
    targetHardware.disabled = !profile.chooseHardware;
    hardwareHelp.textContent = profile.chooseHardware
      ? "Choose the machine that will use this normal ADFS floppy, or leave Auto for a neutral image."
      : profile.hardware === "beebscsi"
        ? "Fixed because this format is a BeebSCSI DAT/DSC pair."
        : profile.hardware === "risc-os"
          ? "Fixed because this is an Archimedes / RISC OS hard-drive format."
          : "Not applicable to this format.";
    previousFormat = format.value;
  };
  format.addEventListener("change", updateFormatControls);
  updateFormatControls();
}

function showHelp() {
  showModal(`
    <div class="help-guide">
      <div class="help-heading">
        <div><small>ACORN FILE FORGE HANDBOOK</small><h2>How to use Acorn File Forge</h2></div>
        <p>Practical instructions for creating, editing, transferring, checking and saving Acorn media images.</p>
      </div>
      <div class="help-layout">
        <nav class="help-toc" aria-label="Help topics">
          <strong>START HERE</strong>
          <a href="#help-start">Open or create an image</a>
          <a href="#help-workspace">Workspace and selection</a>
          <a href="#help-checkpoints">Undo and checkpoints</a>
          <a href="#help-files">Files and folders</a>
          <strong>MEDIA GUIDES</strong>
          <a href="#help-dfs">SSD and DSD</a>
          <a href="#help-hfe">HFE floppy images</a>
          <a href="#help-mmb">MMB disk banks</a>
          <a href="#help-adfs">ADFS and RISC OS</a>
          <a href="#help-beebscsi">BeebSCSI DAT/DSC</a>
          <a href="#help-tapes">UEF tapes</a>
          <strong>WORKFLOWS</strong>
          <a href="#help-online">Find and install online software</a>
          <a href="#help-transfer">Copy and drag between panes</a>
          <a href="#help-mmb-menu">Create an MMB menu</a>
          <a href="#help-adfs-menu">Create an ADFS menu</a>
          <a href="#help-maintenance">Check and compact</a>
          <a href="#help-hex-editor">Raw image hex editor</a>
          <a href="#help-analysis">Workbench and analysis</a>
          <a href="#help-saving">Save, close and recover</a>
          <a href="#help-shortcuts">Keyboard shortcuts</a>
          <a href="#help-accessibility">Accessibility and appearance</a>
          <a href="#help-limits">Limits and troubleshooting</a>
          <a href="#help-project">Project and support</a>
        </nav>
        <div class="help-content">
          <section id="help-start">
            <h3>Open or create an image</h3>
            <p class="help-lead">Edits are made to a private working copy. The file you selected on your computer is never overwritten.</p>
            <div class="help-note"><strong>Start small:</strong> a new workspace opens with one full-width pane. Select <strong>Add Pane</strong> in the header only when you need another source, destination or scratch image. You can display up to three panes.</div>
            <div class="help-workflow" aria-label="Typical Acorn File Forge workflow">
              <span><b>1</b><strong>Open or create</strong><small>A private working image</small></span><i>→</i>
              <span><b>2</b><strong>Browse and edit</strong><small>Files, slots and directories</small></span><i>→</i>
              <span><b>3</b><strong>Analyse</strong><small>Structure, menus and launchers</small></span><i>→</i>
              <span><b>4</b><strong>Save</strong><small>Timestamped ZIP and README</small></span>
            </div>
            <div class="help-task">
              <h4>Open an existing image</h4>
              <ol>
                <li>Choose any empty pane.</li>
                <li>Select <strong>Open disk image</strong>, or drag an image from your computer onto the empty pane.</li>
                <li>Choose the image. Supported families include SSD, DSD, HFE, MMB, ADFS floppy and hard-drive images, DAT/DSC, HDF, HDD, IMG, RAW, BIN and UEF. ZIP distributions can contain one supported image or a matched DAT/DSC pair.</li>
                <li>Wait for the opening indicator. The catalogue or MMB slot index appears when identification is complete.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Create a new image</h4>
              <ol>
                <li>Select <strong>Create new disk image</strong> in an empty pane.</li>
                <li>Choose DFS SSD or DSD, an HFE-wrapped DFS/ADFS floppy, ADFS S/M/L floppy, BeebSCSI DAT/DSC hard drive, HDF virtual HDD, RAW physical-drive image, or an MMB bank.</li>
                <li>Enter a disk title. For DAT, HDF and RAW images, enter a capacity such as <code>20MB</code> or <code>512MB</code>.</li>
                <li>The size field is read-only for fixed SSD, DSD, ADFS floppy, HFE and MMB formats. It becomes editable for BeebSCSI, HDF and RAW hard drives and remembers the last HDD capacity you entered.</li>
                <li>The target is disabled when it does not apply, fixed to BeebSCSI for DAT/DSC, and fixed to Archimedes / RISC OS for HDF or RAW. Normal ADFS S/M/L floppies retain a target choice because their geometry can be used by several Acorn systems.</li>
                <li>MMB has no bank-wide disk title, so that field is disabled. Titles belong to the individual disks you create or insert in its slots.</li>
                <li>Select <strong>Create image</strong>. The formatted image opens immediately as an editable working copy.</li>
                <li>Add content, then use the <strong>Save Image</strong> button in the pane heading to download it.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Pane heading actions:</strong> after the orange changed indicator, the buttons create a New Blank Image, Load New Image, Save Image, Refresh View, and Close Pane. The × close button offers Save and close, Close without saving, or Cancel whenever the image has changes.</div>
            <h4>Which new format should I choose?</h4>
            <div class="help-table-wrap"><table class="help-table"><caption class="visually-hidden">Supported image formats and their main limits</caption>
              <thead><tr><th>Format</th><th>Best used for</th><th>Important limit</th></tr></thead>
              <tbody>
                <tr><td>SSD</td><td>One BBC DFS disk side</td><td>200 KiB, 31 catalogue files</td></tr>
                <tr><td>DSD</td><td>Two-sided BBC DFS disk</td><td>Two independent 200 KiB sides</td></tr>
                <tr><td>HFE</td><td>HxC, Gotek and flux-style floppy workflows</td><td>Advanced/protected layouts open read-only</td></tr>
                <tr><td>ADFS S/M/L</td><td>BBC Master or compact hierarchical media</td><td>Old-format directory and capacity limits</td></tr>
                <tr><td>DAT + DSC</td><td>BeebSCSI ADFS hard drives</td><td>Downloads as a ZIP containing the required pair</td></tr>
                <tr><td>HDF / RAW</td><td>Archimedes, RISC OS or emulated hard drives</td><td>Choose enough capacity before creating</td></tr>
                <tr><td>MMB</td><td>A library of BBC DFS disks</td><td>511 SSD-sized physical slots</td></tr>
              </tbody>
            </table></div>
          </section>
          <section id="help-workspace">
            <h3>Workspace, navigation and selection</h3>
            <figure><img src="/help/workspace.png" alt="Acorn File Forge showing two work panes and the Add Pane control"><figcaption>The workspace begins with one pane. Add a second or third only when needed; every pane has independent navigation, selection, refresh, progress and save controls.</figcaption></figure>
            <h4>Add, arrange and close panes</h4>
            <ol>
              <li>Select <strong>Add Pane</strong> in the header to add an empty pane. It disables at three panes and re-enables when one is closed.</li>
              <li>Use the numbered grip at the left of a pane heading and drag it onto another pane to swap their positions. With the grip focused, Alt+Left and Alt+Right provide the same operation without dragging.</li>
              <li>The complete pane moves with its image, current directory or MMB slot, selection and scroll position.</li>
              <li>An empty pane is a convenient scratch area for creating an SSD, DSD, MMB, ADFS floppy, BeebSCSI DAT/DSC pair or other supported image.</li>
              <li>Select × at the top-right to close that whole pane. Save changed images from the prompt, deliberately close without saving a download, or cancel. The server working copy remains available through Recovery.</li>
              <li>The current pane count, order and open images are remembered across a normal page refresh. A completely fresh workspace starts with one pane.</li>
            </ol>
            <div class="help-note"><strong>Two different drag handles:</strong> drag the numbered grip to rearrange panes. Drag file rows, MMB slots or a supported image heading to transfer content between images.</div>
            <div class="help-note"><strong>Familiar pane menus:</strong> File and Edit are always first, followed by View, Library, the format-specific Menu when available, Analyse and Tools. File holds open, save, add and create commands. Edit holds Cut, Copy, Paste, Undo and Checkpoints. View holds refresh, DSD side switching and return-to-MMB commands. The heading icons remain quick shortcuts for common image actions.</div>
            <div class="help-note"><strong>Free-space meter:</strong> the lower-right bar uses the image filesystem's real allocation data. Green means under 70% used, orange means 70% or more, and red means 90% or more. Hover over it for used, free and total values. An MMB root counts disk slots; opening one of its disks switches the meter to that slot's DFS bytes. UEF tapes have no fixed free-space capacity and show a neutral striped meter.</div>
            <h4>Navigate an image</h4>
            <ol>
              <li>Double-click a directory to enter it. Double-click a file to download a ZIP containing the file and its <code>.inf</code> metadata.</li>
              <li>Double-click <strong>..</strong> to move to the parent directory, or select any breadcrumb to jump directly to that location.</li>
              <li>Inside an MMB disk, use <strong>All disks</strong> to return to the slot list. The disk you left remains selected and is scrolled back into view.</li>
              <li>Select ↻ in the pane heading to reread the current directory or slot list without closing the image.</li>
              <li>Click the image filename in the pane heading to edit it. Press <kbd>Enter</kbd> or click elsewhere to save, or press <kbd>Escape</kbd> to cancel. The format extension is retained; DAT/DSC pair names stay matched. This renames the recovered and downloaded container, not its internal disk title.</li>
            </ol>
            <h4>Select one or several items</h4>
            <ol>
              <li>Click an item to select only it.</li>
              <li>Use <kbd>Ctrl</kbd>/<kbd>Cmd</kbd>-click to add or remove individual items.</li>
              <li>Use <kbd>Shift</kbd>-click to select the range between the anchor and the clicked row.</li>
              <li>Press <kbd>Ctrl</kbd>/<kbd>Cmd</kbd>-<kbd>A</kbd> while a row has focus to select every usable item in the current view.</li>
              <li>Start dragging any selected row to carry the complete selection.</li>
              <li>Point at a single row to reveal Rename and Delete beside its name. For a multiple selection, Rename is hidden and Delete applies to the whole selection with one confirmation.</li>
              <li>The Access column reveals separate read/write and read-only controls. They apply to one file or disk, or every applicable item in a multiple selection.</li>
            </ol>
            <div class="help-note"><strong>The orange dot means changed:</strong> the working image contains edits not yet downloaded. It clears after Save Image has successfully prepared the download and returns after the next edit. A failed save leaves the dot visible. It does not mean the original file has changed.</div>
          </section>
          <section id="help-checkpoints">
            <h3>Undo changes and create named checkpoints</h3>
            <p class="help-lead">Every image-changing operation starts with an automatic restore point. This includes file and directory edits, transfers, MMB slot operations, compaction, menu writes and save-time image finalisation.</p>
            <div class="help-task">
              <h4>Undo the latest operation</h4>
              <ol>
                <li>Open <strong>Edit</strong> in the affected pane.</li>
                <li>Select <strong>Undo last change</strong>. The button is disabled until an automatic restore point exists.</li>
                <li>Confirm the undo. The most recent automatic point is restored and consumed.</li>
                <li>All panes showing that same image return to its root or MMB disk list and refresh from the restored bytes.</li>
                <li>Repeat to step backwards through earlier operations. Up to 20 recent automatic points are retained per image.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Create and restore a named checkpoint</h4>
              <ol>
                <li>Before a large reorganisation, open <strong>Edit → Checkpoints</strong>.</li>
                <li>Enter a useful name such as <code>Before rebuilding Universal Menu</code>, then select <strong>Create named checkpoint</strong>.</li>
                <li>Return to the same dialog at any time to inspect named checkpoints and automatic undo points.</li>
                <li>Select ↶ beside a checkpoint and confirm to restore it. The state being replaced is first retained as a new automatic undo point.</li>
                <li>Select × beside an unwanted checkpoint to delete only that snapshot.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Large HDD images:</strong> Acorn File Forge asks the host filesystem for a copy-on-write clone. If cloning is unavailable, its safe-copy fallback preserves sparse zero ranges instead of writing unused DAT capacity. Either form remains a complete byte-for-byte restore point.</div>
            <div class="help-warning"><strong>Checkpoints belong to the working session:</strong> they are private to the same browser owner and survive refreshes and container restarts, but clearing the recovered session or deleting the Docker work volume removes them too. Download important finished images separately.</div>
          </section>
          <section id="help-files">
            <h3>Create, modify and delete files and folders</h3>
            <div class="help-task">
              <h4>Add one or more host files</h4>
              <ol>
                <li>Navigate the destination pane to the required DFS catalogue or ADFS directory.</li>
                <li>Open <strong>File → Add file</strong> and choose one or more files.</li>
                <li>For each file, review the target name, load address, execute address and, on ADFS, its RISC OS filetype.</li>
                <li>If a name is illegal for the target filing system, accept the safe suggestion or type a valid replacement.</li>
                <li>Select <strong>Add file</strong> in the dialog. Each successful addition appears in the current view.</li>
                <li>For a multiple selection, choose <strong>Add and apply to all remaining</strong> to accept each later file's own detected name and metadata without reopening the same review.</li>
              </ol>
              <p>Files copied from SSD, DSD, ADFS, HFE or MMB retain their catalogue load/execute addresses and other supported metadata. For loose host files, select their companion <code>.inf</code> sidecars too, or use a conventional <code>name,load-exec</code> filename. Raw host bytes alone do not contain a trustworthy address.</p>
            </div>
            <div class="help-task">
              <h4>Import one or more host folders</h4>
              <ol>
                <li>Navigate to the destination and choose <strong>File → Add folder</strong>, or drag folders from the desktop onto the pane. Use drag and drop to select several top-level folders when your browser supports it.</li>
                <li>Review the preflight. Desktop housekeeping files are ignored and any target-name shortening is shown before the image changes.</li>
                <li>On ADFS, keep <strong>Preserve folder structure</strong> to recreate the tree under the current directory, or choose <strong>Import all files here</strong> to flatten it.</li>
                <li>On DFS, the batch is always flattened into the open catalogue group because A-Z are filename prefixes, not nested folders.</li>
                <li>Tick the explicit replacement option only when existing ordinary files with the same target paths should be overwritten.</li>
                <li>At an MMB disk index, use <strong>File → Insert folder of disk images</strong>. The whole tree is scanned for SSD, DSD, DFS-formatted HFE and ZIP files; unrelated files are listed as ignored and the matches fill suitable slots from the selected or first empty slot.</li>
                <li>When later disk or menu reviews repeat, use <strong>Apply to all remaining</strong>. Every item keeps its own detected filename, launch data, PAGE and catalogue metadata.</li>
              </ol>
              <p>The complete batch uses one filesystem mount and one undo checkpoint, which is substantially quicker and safer than adding every small file separately.</p>
            </div>
            <div class="help-task">
              <h4>Create an ADFS directory</h4>
              <ol>
                <li>Navigate to the parent directory.</li>
                <li>Choose <strong>File → New folder</strong>, enter a legal name and select <strong>Create folder</strong>.</li>
                <li>Double-click the new directory to enter it, then add or drag content into it.</li>
              </ol>
              <p>ADFS directories are real hierarchical objects. DFS uses the separate catalogue-group workflow below.</p>
            </div>
            <div class="help-task">
              <h4>Use DFS catalogue groups</h4>
              <ol>
                <li>At the DFS virtual root, open <strong>$</strong> or any populated A-Z catalogue row.</li>
                <li>Choose <strong>File → New catalogue group</strong> to choose another one-character prefix and then choose its first file.</li>
                <li>An empty group cannot be saved because DFS stores the prefix on each file, not as a separate directory entry.</li>
                <li>Drag selected files onto a catalogue row to move them to that prefix. Open the same image in two panes when you want source and destination catalogues visible together.</li>
                <li>Double-click <strong>..</strong> to return to the catalogue list. At an MMB disk's catalogue root, <strong>..</strong> returns to <strong>All disks</strong>.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Rename or move an item</h4>
              <ol>
                <li>Point at a file or directory and select its pencil icon to rename it in place.</li>
                <li>Enter a legal leaf name and select <strong>Rename</strong>.</li>
                <li>On ADFS, move an item by dragging its row onto a directory. To move several items together, select them first and drag any selected row.</li>
                <li>You can also open the same ADFS image in multiple panes, navigate each pane independently, then drag into the required destination pane.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Change access, download or delete</h4>
              <ol>
                <li>Point at the Access column and select ◇ for read/write or ◆ for read-only. Select several files first to update them together.</li>
                <li>Double-click an ordinary file to download a ZIP containing the loose file and its matching <code>.inf</code> metadata sidecar without changing the image.</li>
                <li>To remove one or several items, select them and use any visible × on the selected rows, or press <kbd>Delete</kbd>.</li>
                <li>Read the single confirmation carefully. Deleting an ADFS directory recursively removes everything below it. Every affected installed-menu record is removed in the same batch update.</li>
              </ol>
            </div>
          </section>
          <section id="help-dfs">
            <h3>SSD and DSD: complete workflow</h3>
            <div class="help-task">
              <h4>Create and populate a DFS disk</h4>
              <ol>
                <li>Create an SSD for one 200 KiB side, or a DSD for two sides.</li>
                <li>On a DSD, use <strong>Side 0</strong>/<strong>Side 2</strong> to choose the catalogue you are editing.</li>
                <li>Open <strong>$</strong> for the default catalogue, or another populated A-Z prefix. Use <strong>File → New catalogue group</strong> when the first file will introduce a new prefix.</li>
                <li>Use <strong>File → Add file</strong>, or drag selected files from another pane or onto a catalogue row.</li>
                <li>Review shortened names and Acorn load/execute addresses before confirming each import.</li>
                <li>Use the row actions to rename or delete. Use the Access column to mark one or several files read/write or read-only.</li>
                <li>Use <strong>Tools → Check filesystem</strong>, optionally compact it, then select <strong>Save Image</strong> in the pane heading.</li>
              </ol>
            </div>
            <h4>DFS rules enforced by the app</h4>
            <ul>
              <li>A leaf name is at most seven characters and its DFS directory prefix is one character.</li>
              <li>The virtual root contains sibling groups <strong>$</strong> and A-Z. These are filename prefixes, not nested directories.</li>
              <li><strong>$</strong> is always shown so a blank disk can receive its first default-catalogue file. Other prefixes appear when populated and disappear when their last file is removed.</li>
              <li>A standard DFS side holds no more than 31 catalogue entries.</li>
              <li>SSD has one catalogue. DSD has separate side 0 and side 2 catalogues.</li>
              <li>A file must fit in the remaining sectors. Compacting can consolidate fragmented free space.</li>
              <li>A complete hierarchical image cannot be expanded into DFS. Copy its individual files instead.</li>
            </ul>
            <div class="help-note"><strong>To copy a whole DFS disk to ADFS:</strong> drag the blue disk-format badge or the open DFS pane heading onto an ADFS pane. Choose a directory name, and the catalogue will be extracted there.</div>
          </section>
          <section id="help-hfe">
            <h3>HFE floppy images: safe editing</h3>
            <figure><img src="/help/hfe-create.png" alt="Create image dialog showing HFE-wrapped DFS and ADFS floppy choices"><figcaption>Create a new HFE around DFS SSD/DSD or ADFS S/M/L geometry. Existing supported HFE images open through the normal image picker.</figcaption></figure>
            <p>HFE stores floppy track timing and bit cells, while DFS and ADFS describe files inside the sectors. Acorn File Forge decodes the sectors with the HxC engine and then opens the detected filing system.</p>
            <ol>
              <li>Open an HFE normally, or create an HFE-wrapped DFS/ADFS floppy from <strong>Create new disk image</strong>.</li>
              <li>Check the opening warning. A clean HFE v1 disk is editable through the usual file tools.</li>
              <li>HFE v2/v3, weak-bit, bad-sector, protected or advanced timing images open as a clearly labelled read-only safe view. Export or drag files from them without changing their tracks.</li>
              <li>For an editable HFE, make the required changes and select <strong>Save Image</strong> in the pane heading.</li>
              <li>The app writes changed sectors into a copy of the original track layout, decodes that result, and compares every sector with the working filesystem. A mismatch blocks the download and leaves the original HFE intact.</li>
            </ol>
            <div class="help-note"><strong>What the pane shows:</strong> the format badge reads HFE, while the directory rules, sides and capacity come from its decoded DFS or ADFS filesystem. Advanced images show <strong>Read-only safe view</strong> and hide editing, compaction and menu-writing controls.</div>
            <div class="help-note"><strong>MMB and ADFS transfers:</strong> a DFS-formatted HFE may be inserted into an MMB. Any supported HFE filesystem can be opened in one pane and copied or extracted into another image. MMB stores only DFS sectors, so timing, weak-bit and protection information from an advanced HFE is deliberately omitted and reported as a destination warning.</div>
          </section>
          <section id="help-mmb">
            <h3>MMB disk banks: slots and embedded disks</h3>
            <figure><img src="/help/mmb-actions.png" alt="MMB File and Menu controls with slot row actions"><figcaption>Every physical slot is listed. File contains disk insertion and creation; Edit contains clipboard actions; rename, access and eject controls live on each formatted slot row.</figcaption></figure>
            <div class="help-task">
              <h4>Insert SSD, DSD or HFE image files and ZIP distributions</h4>
              <ol>
                <li>Select the first empty destination slot.</li>
                <li>Open <strong>File → Insert SSD / DSD / HFE / ZIP</strong>.</li>
                <li>Select one or several SSD/DSD/HFE files, or ZIP files containing them. Every supported ZIP member is imported in archive order and unrelated documentation or artwork is ignored.</li>
                <li>A DSD needs two adjacent empty slots. Its two sides occupy two SSD-sized MMB slots.</li>
                <li>Review the allocation message and, if a menu is installed, review or skip each offered menu entry.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Create a blank writable disk in a slot</h4>
              <ol>
                <li>Select an empty slot.</li>
                <li>Choose <strong>File → Create blank SSD here</strong> or <strong>Create blank DSD here</strong>.</li>
                <li>Enter the disk title and choose whether it is read/write.</li>
                <li>Select <strong>Create and insert</strong>. Blank formatted disks are useful for saved games and user data.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Import a disk that is already open in another pane</h4>
              <ol>
                <li>Open an SSD, DSD, DFS-formatted HFE, or an individual disk inside another MMB pane.</li>
                <li>In the destination MMB, return to <strong>All disks</strong> and select one empty slot.</li>
                <li>Choose <strong>File → Import from open &lt;filename&gt;</strong>. Each other open image has its own entry. The visible SSD/DSD image title becomes the destination slot title; an MMB source keeps its existing slot title.</li>
                <li>Entries for incompatible ADFS filesystems or an MMB still showing <strong>All disks</strong> are disabled and explain why. MMB can contain DFS disk sectors only.</li>
                <li>Review any installed-menu metadata offered after the disk is inserted. A DSD still requires two adjacent empty slots.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Browse and edit a disk inside an MMB</h4>
              <ol>
                <li>Double-click a formatted slot to open its DFS catalogue.</li>
                <li>Add, rename, lock, delete, drag or download files exactly as on an SSD.</li>
                <li>Use <strong>Tools → Compact filesystem</strong> or <strong>Check filesystem</strong> while the disk is open.</li>
                <li>Select <strong>All disks</strong> to return to the MMB index at the same slot.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Rename, protect, move or eject slots</h4>
              <ol>
                <li>Select a formatted slot. Ctrl/Cmd-click or Shift-click to select several.</li>
                <li>Point at one slot and use the pencil beside its name to rename its disk title.</li>
                <li>In the Access column, use ◇ to mark every selected formatted disk read/write or ◆ to mark them read-only.</li>
                <li>Drag one or several selected disks onto another position in the same MMB to cut and paste them as one block. Relative slot spacing is retained. Overlapping moves are safe, and replacing unrelated occupied slots always requires confirmation.</li>
                <li>Select one or several formatted slots, then use × beside any selected name. One confirmation clears every selected catalogue entry and its disk data. Records for those disk titles are removed from an installed Universal or SPI menu in the same operation. If another non-ejected slot has the same title, its records remain available. The list keeps its selection area and scroll position after slot actions.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Empty slots are intentional:</strong> they stay visible so images can be dropped precisely. An unformatted empty slot has no read-only/read-write state.</div>
          </section>
          <section id="help-online">
            <h3>Find and install software from the Online Library</h3>
            <figure><img src="/help/online-library.png" alt="Online Library showing machine, missing-title and multi-selection controls"><figcaption>Search several Acorn catalogues together, compare metadata and install one or many downloadable items.</figcaption></figure>
            <p class="help-lead">The Online Library uses the same format checks, metadata review, undo point and menu workflow as a file selected from your computer. A link is never treated as an installable image unless its source provides a direct supported download.</p>
            <div class="help-task"><h4>Add disks to an MMB</h4><ol>
              <li>Open the MMB at <strong>All disks</strong>. Optionally select one or more empty slots.</li>
              <li>Choose <strong>Library → Find disks online</strong>. Its initial machine comes from the Workbench profile applied to this pane, or the remembered active Workbench profile when the pane has none. Change it when this search needs another machine, then search by title, publisher or keyword. Leave the search blank to browse the current catalogue page. Search results remain installable for one hour and survive a normal app restart.</li>
              <li>Select the <strong>Title</strong>, <strong>Publisher</strong>, <strong>Year</strong> or <strong>Source</strong> heading to sort. The active heading shows ↑ for ascending or ↓ for descending; select it again to reverse the order. Checked results stay selected while sorting.</li>
              <li>Use <strong>Not already present</strong> to hide likely matches found by disk title, remembered online distribution name, or an installed MMB menu record. The comparison ignores punctuation and the publisher suffix saved with online imports. This is a helpful duplicate check, not a checksum guarantee.</li>
              <li>Select several downloadable results. If you did not select empty slots, set a starting slot; the app finds the next suitable empty run and wraps around safely. DSD images still require two adjacent slots.</li>
              <li>Leave <strong>Offer installed disks to the detected menu</strong> selected to review the title, publisher, launcher, action and PAGE after insertion. Clear it for intentionally off-menu disks.</li>
              <li>During a multi-item install, <strong>Abort operation</strong> stops before the next download. The item already in progress finishes at a safe image boundary.</li>
              <li>If an archive contains the same release as both SSD and UEF, the native SSD is selected once. Installing into a blank SSD adopts its catalogue and title; shortened SSD files are safely padded to the target's standard geometry.</li>
            </ol></div>
            <div class="help-task"><h4>Add files or applications to an open disk</h4><ol>
              <li>Open an SSD/DSD disk, an MMB slot, an ADFS directory, or a RISC OS image and choose <strong>Library → Find software online</strong>.</li>
              <li>On DFS, ordinary single-catalogue downloads are copied into the currently open group. Multi-prefix distributions retain their original DFS prefixes so loaders and duplicate leaf names remain valid.</li>
              <li>On ADFS, a downloaded disk is extracted into the current directory by default. Select <strong>Create a folder</strong> to keep each disk separate.</li>
              <li>RISC OS Open packages install only into ADFS/RISC OS images. Application directories are retained, package-control files are omitted, and SparkFS load, execute and filetype metadata is preserved.</li>
            </ol></div>
            <h4>Sources, availability and safety</h4><ul>
              <li>Built-in sources are the Complete BBC Micro Games Archive, every public media category in Acorn Electron World, Every Game Going, 8-Bit Software, 0xC0DE and community Electron SSD projects, cautious itch.io Acorn searches, and the official plus third-party RISC OS Open package feeds.</li>
              <li>Professional, public-domain, companion, EUG, featured, unfinished and unreleased Electron World categories are indexed. DVD-only entries and records without a supported public download are omitted.</li>
              <li>Every Game Going maps BBC B, B+, Master 128/Compact, Electron and Archimedes A3000 machine IDs from provider settings. Each matching item page is checked for actual downloadable media before it is displayed.</li>
              <li>itch.io uses the selected workbench machine to search for BBC Micro, BBC Master, Acorn Electron, Acorn Archimedes or RISC OS software. Unrelated acorn-themed games are suppressed: a project is displayed only after its page is found to contain a supported Acorn disk or tape upload. A fresh short-lived download is requested when Install is selected.</li>
              <li>Choose <strong>Sources…</strong> to edit a provider's URL, loading strategy, page layout, category roots, query templates, machine IDs, validation limit and cache settings. The engine applies generic configured stages and never branches on a catalogue name. The editable JSON is stored in <code>catalog-sources.json</code>.</li>
              <li>Downloads are size-limited, cached briefly and checked for ZIP path traversal. A failed source is reported below the usable results instead of cancelling the complete search.</li>
            </ul>
            <div class="help-warning"><strong>Respect each archive and author:</strong> availability in a catalogue does not change a program's licence. Follow the source page for permissions, payment, documentation and the newest release.</div>
          </section>
          <section id="help-adfs">
            <h3>ADFS, Archimedes and RISC OS images</h3>
            <div class="help-task">
              <h4>Create and organise an ADFS volume</h4>
              <ol>
                <li>Create an ADFS S/M/L floppy or an HDF/RAW hard-drive image, or open a supported existing image.</li>
                <li>Double-click directories to enter them. Double-click <strong>..</strong> or use the breadcrumbs to move back through the hierarchy.</li>
                <li>Use <strong>File → New folder</strong> to create a validated ADFS directory at the current location.</li>
                <li>Use <strong>File → Add file</strong> to import host files with load/execute addresses and optional RISC OS filetype.</li>
                <li>When the selected host file is a recognised disk, tape or ZIP image, review its catalogue preview before anything is written.</li>
                <li>Extraction defaults to the directory currently shown. Optionally choose another existing destination with the directory picker, and optionally create a named child directory there. You can instead store the original image as an ordinary file.</li>
                <li>Direct extraction never overwrites an existing name. A rollback point protects the complete working image if extraction fails or is aborted.</li>
                <li>Use the pencil and × icons on each row to rename or delete. Use the Access-column actions to mark one or several items read/write or read-only.</li>
                <li>Drag files and complete directory trees onto another directory in the same image to reorganise them. Installed menu launch paths are updated automatically.</li>
                <li>Check and compact the working filesystem, then save the image.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Choose the target hardware deliberately:</strong> Auto inspects without applying machine-specific repairs. Electron Plus 3 and BBC/Master select the normal 8-bit ADFS checks. BeebSCSI is a separate Electron/BBC/Master profile and requires a matched DAT/DSC pair. Archimedes/RISC OS selects the 32-bit target without old-ADFS compatibility repairs.</div>
            <div class="help-task">
              <h4>Import a complete disk or tape into a directory</h4>
              <figure><img src="/help/image-import-preview.png" alt="Image import dialog previewing Chuckulus files with optional destination and child-directory controls"><figcaption>Inspect the source before writing. Direct extraction into the current directory is the default; destination browsing and a new child directory are independent options.</figcaption></figure>
              <ol>
                <li>Navigate to the ADFS directory that will contain the imported software.</li>
                <li>Drag an open MMB slot, SSD/DSD/HFE image, UEF tape or another supported image from another pane; alternatively use <strong>File → Add file</strong> and select an image from the host.</li>
                <li>Review the source preview. The current directory is selected by default; optionally tick <strong>Choose a different existing directory</strong> and browse the destination tree.</li>
                <li>Optionally tick <strong>Create a new child directory</strong> and enter its name. Leave it unticked to place the source contents directly in the selected destination.</li>
                <li>Choose whether to offer the imported program as a menu entry. Keeping it off-menu does not require a launch file.</li>
                <li>Review progress and metadata. During a bulk copy, an empty DFS disk pauses for a Skip or Abort decision; no meaningless empty ADFS directory is created.</li>
              </ol>
            </div>
            <p>Where both formats support it, Acorn File Forge preserves load/execute addresses, RISC OS filetypes, datestamps and access flags. Old ADFS names are normally limited to ten characters.</p>
            <div class="help-note"><strong>Very large imports:</strong> old ADFS directories hold at most 47 entries. A large MMB selection is divided into parent groups. Names such as <code>DISCS1</code> and <code>DISCS2</code> are editable suggestions; choose names appropriate to your volume before copying.</div>
          </section>
          <section id="help-beebscsi">
            <h3>BeebSCSI DAT and DSC: open, edit and save</h3>
            <ol>
              <li>Select either the DAT data file or its matching DSC descriptor.</li>
              <li>Choose <strong>BeebSCSI DAT + DSC</strong>. This is separate from the normal ADFS machine profiles because BeebSCSI is available for Electron, BBC and Master hosts.</li>
              <li>In the pairing dialog, the chosen file is already retained. Select only the missing companion.</li>
              <li>Confirm that both base names match, for example <code>SCSI0.dat</code> and <code>SCSI0.dsc</code>, then select <strong>Open DAT + DSC</strong>.</li>
              <li>Traverse, create, add, rename, move, lock and delete content using the normal ADFS controls.</li>
              <li>Select <strong>Save Image</strong> in the pane heading. The same foreground progress dialog used by every format reports validation, checksums, catalogue generation and construction of the complete ZIP. For DAT it also names geometry, directory and map checks. The ready dialog appears only after the hardware-ready ZIP containing <code>BeebSCSI0/scsi0.dat</code> and <code>BeebSCSI0/scsi0.dsc</code> is complete on disk. If the automatic download does not begin, use the direct <strong>Download ZIP</strong> link.</li>
              <li>Extract the ZIP into the root of the BeebSCSI SD card. Keep the <code>BeebSCSI0</code> directory itself. The firmware does not look for DAT/DSC files directly in the SD-card root.</li>
            </ol>
            <div class="help-note"><strong>Large-image performance:</strong> once an ADFS image has been identified, directory changes use a direct memory-mapped view and return the catalogue and free-space value together. The app does not copy or re-identify the complete DAT for every click. Imports keep one destination mount open for the batch. Zero-filled free DAT capacity is also kept sparse in the working image and undo checkpoints, while downloads use fast ZIP compression and sparse-aware checksumming. The extracted DAT retains its complete logical size and exact bytes.</div>
            <div class="help-note"><strong>Why the target matters:</strong> official 8-bit ADFS requires matching <code>Hugo</code> directory headers, footers and parent sequence copies. An edited old-map volume must also receive a new two-byte disc ID, otherwise ADFS can retain state belonging to the original volume and report <em>Broken directory</em> or <em>Disc changed</em>. The BeebSCSI target performs those checks, advances the disc ID and rebuilds its map checksum before download.</div>
            <div class="help-warning"><strong>Do not substitute a descriptor:</strong> DSC geometry belongs to its particular DAT. A DAT without valid matching geometry may be browsed when identifiable, but writing is deliberately blocked to prevent corruption. The DAT ends at the old-format ADFS map boundary, as in the official BeebSCSI Quickstart image; the DSC may describe a slightly larger device. Newly created pairs are checked against that map extent and BeebSCSI's 256-byte sector, 33-sector track, 16-head and ADFS 21-bit size limits before download.</div>
          </section>
          <section id="help-tapes">
            <h3>UEF tapes: inspect, export and convert</h3>
            <div class="help-task">
              <h4>Convert UEF to SSD or DSD</h4>
              <ol>
                <li>Open the UEF in any pane. Tape catalogues are read-only.</li>
                <li>Choose <strong>Tools → Convert tape to disk</strong>.</li>
                <li>Select SSD or DSD as the destination format.</li>
                <li>Acorn File Forge gives unusable cassette names safe, deterministic DFS names, then checks every tokenised BASIC file for calls that rely on the next item on tape.</li>
                <li>Empty <code>*/</code> and <code>CHAIN ""</code> calls are replaced with the final DFS filename. References are also updated when a long cassette name had to be shortened.</li>
                <li>Choose which other pane receives the converted disk. DFS boot option 3 is set. A <code>!BOOT</code> is generated only when the proposed loader can be started independently. If the chosen pane contains unsaved edits, download them before agreeing to replace it.</li>
                <li>Review the reconstructed files, adjust them if required, then save the new DFS image.</li>
              </ol>
            </div>
            <p>Double-click an individual tape file to export it. You can also drag reconstructed tape files to a writable disk, or drag the complete UEF onto ADFS to create and populate a directory. Standard load and execute addresses are retained. Tokenised BASIC is checked for file I/O that inherits an already-open cassette channel; starting that program directly from disk would produce error 222 (<em>Channel</em>), so the app suppresses automatic <code>!BOOT</code> creation and reports the incompatibility. During ADFS extraction, machine-code OSCLI calls are also checked for DFS-only abbreviations such as <code>R.</code> and <code>L.</code>. Proven immediate pointers are redirected to appended <code>RUN</code> and <code>LOAD</code> commands without moving the original code. If the pointer or free address range cannot be proved safe, the file is left untouched and the image receives a warning.</p>
          </section>
          <section id="help-transfer">
            <h3>Copy and drag between panes</h3>
            <figure><img src="/help/workspace.png" alt="Acorn images open together for drag and drop"><figcaption>Navigate the destination first, select one or more source items, then drag any selected row into another pane.</figcaption></figure>
            <div class="help-task">
              <h4>Cut, copy and paste</h4>
              <ol>
                <li>Select one or several source rows, then choose <strong>Edit → Cut</strong> or <strong>Edit → Copy</strong>. Ctrl/Cmd-X and Ctrl/Cmd-C do the same while the pane has focus.</li>
                <li>Navigate normally to the destination. Opening directories, catalogue groups, MMB disks and other panes does not lose the pending selection.</li>
                <li>Choose <strong>Edit → Paste</strong>, or press Ctrl/Cmd-V in the destination pane. The same filename, capacity and filesystem checks used by drag and drop are applied.</li>
                <li>The clipboard is single-use. Paste, cancelling a paste, pressing Escape, or starting a different modifying operation clears it. A cut is not removed from its source until its destination has been written successfully.</li>
                <li>When ADFS files are pasted into DFS, review the proposed seven-character leaf names and paste into the required <strong>$</strong> or A-Z catalogue group. Directories cannot be pasted into flat DFS media.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Reorganise MMB slots with the clipboard</h4>
              <ol>
                <li>Select any formatted slots, including a range containing gaps, and choose Cut or Copy from <strong>Edit</strong>.</li>
                <li>Select the first destination slot and paste. Relative offsets are retained, so a selected section stays laid out the same way.</li>
                <li>An overlapping cut is safe: its source slots count as available and the complete block is snapshotted before anything is moved.</li>
                <li>If other occupied slots would be replaced, inspect their slot numbers and titles, then cancel or explicitly replace them.</li>
                <li>To paste loose files at the MMB index, select an empty starting slot. Choose SSD or DSD in the build planner, review each DFS catalogue group and seven-character name, and inspect how files will be divided when a side reaches 31 entries or its 200 KiB capacity.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Copy files or directories</h4>
              <ol>
                <li>Open the source in one pane and a writable destination in another.</li>
                <li>Navigate the destination to the exact directory or DFS side required.</li>
                <li>Select one or more source files. Complete ADFS directories can also be selected for an ADFS destination.</li>
                <li>Drag any selected row into the destination pane.</li>
                <li>Review replacement filenames where the target has stricter naming rules, then confirm the copy.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Move items inside one ADFS image</h4>
              <ol>
                <li>Select one or more files or directories in an ADFS pane.</li>
                <li>Drag any selected row onto a destination directory row, or into another pane showing a different directory in the same image.</li>
                <li>The operation moves rather than copies. Existing destination objects are never silently replaced.</li>
                <li>If an installed ADFS menu refers to a moved directory or launch file, its stored path, filename and indexes are rebuilt automatically.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Copy MMB disks</h4>
              <ol>
                <li>At the MMB index, select one or several formatted slots.</li>
                <li>To another MMB, drag them onto an empty destination slot. The disks are copied into available positions.</li>
                <li>To ADFS, drag them into the chosen destination directory. Each non-empty disk becomes a directory named from its slot title.</li>
                <li>Cut and paste can move the same slots into ADFS. Each directory is completed first; only successfully extracted source slots are then ejected, with their obsolete MMB menu records removed.</li>
                <li>Review and edit the parent group directories. Names such as DISCS1 are suggestions, not fixed names.</li>
                <li>If shortened ADFS names would clash, keep the default unique DISC-0000 naming scheme or review the highlighted names manually.</li>
                <li>The preflight keeps naming, parent groups and the menu option on the left. Review or edit the dense slot-to-directory table on the right; its rows scroll without moving the Copy button.</li>
                <li>Literal dots in DFS filenames are retained as ADFS path separators. For example, <code>eS.Rob</code> and <code>eT.Rob</code> are copied into separate <code>eS</code> and <code>eT</code> subdirectories within the disk directory.</li>
                <li>Review the menu option, then start the batch.</li>
                <li>If a formatted but empty disk is found, choose <strong>Skip this disk and continue</strong> or <strong>Abort bulk copy</strong>. The dialog shows its slot number and title.</li>
                <li>Watch the foreground progress dialog. If interrupted, use the retry path to skip items already completed in that dialog.</li>
              </ol>
            </div>
            <figure><img src="/help/copy-name-preflight.png" alt="Bulk MMB copy preflight offering generic DISC-0000 names or manual review"><figcaption>The naming choice appears only when the complete preflight finds names that would clash after ADFS shortening. Generic names are selected by default.</figcaption></figure>
            <div class="help-task">
              <h4>Resolve shortened-name collisions before copying</h4>
              <ol>
                <li>The preflight checks every proposed leaf name case-insensitively within its destination parent.</li>
                <li>If there is no collision, the normal safe names are retained and no naming-strategy choice is shown.</li>
                <li>If shortening or sanitising creates a collision, choose <strong>Use generic unique names</strong> for <code>DISC-0000</code>, <code>DISC-0001</code> and so on.</li>
                <li>Alternatively choose <strong>Review shortened names</strong>. Conflicting inputs are highlighted and the copy cannot start until every name is legal and unique in its parent.</li>
                <li>Generic directory names do not replace the MMB slot title used for menu detection and display metadata.</li>
                <li>Generic names make the outer disk directories unique. Complete dotted DFS filenames are also preserved inside each directory, so files sharing a final component cannot collide during extraction.</li>
              </ol>
            </div>
            <figure><img src="/help/destination-conflict.png" alt="Populated ADFS destination conflict with Abort, Keep existing and Replace choices"><figcaption>An existing empty directory is filled automatically. These choices appear only when the existing destination contains files or directories.</figcaption></figure>
            <div class="help-task">
              <h4>When a destination already exists</h4>
              <ol>
                <li>If the existing destination is a directory with no children, it is reused automatically without interrupting the batch.</li>
                <li>If it is populated, choose <strong>Keep existing and continue</strong> to leave it untouched and skip that source disk.</li>
                <li>Choose <strong>Replace and continue</strong> to remove the populated directory recursively, recopy the current disk, and continue.</li>
                <li>Choose <strong>Abort bulk copy</strong> to preserve completed work and start no further disks.</li>
                <li>A same-named file is never treated as an empty directory and is never overwritten silently.</li>
              </ol>
            </div>
            <h4>Transfer behaviour at a glance</h4>
            <div class="help-table-wrap"><table class="help-table"><caption class="visually-hidden">Results of transferring supported source types between image formats</caption>
              <thead><tr><th>Source</th><th>Destination</th><th>Result</th></tr></thead>
              <tbody>
                <tr><td>File</td><td>DFS or ADFS</td><td>Copied with compatible metadata</td></tr>
                <tr><td>ADFS directory</td><td>ADFS</td><td>Recursive directory copy</td></tr>
                <tr><td>SSD/DSD, DFS HFE or MMB slot</td><td>MMB</td><td>Inserted into empty slot(s); HFE track extras cannot be retained</td></tr>
                <tr><td>SSD/DSD/HFE, UEF, ADF or MMB slot</td><td>ADFS</td><td>Extracted into a new directory; ambiguous loader commands are checked</td></tr>
                <tr><td>Several MMB slots</td><td>ADFS</td><td>One directory per non-empty disk, grouped if necessary; every slot is checked</td></tr>
                <tr><td>Whole hierarchical image</td><td>DFS</td><td>Not offered; copy individual files</td></tr>
              </tbody>
            </table></div>
            <div class="help-task">
              <h4>Convert ambiguous loaders safely for ADFS</h4>
              <p>DFS machine-code loaders sometimes pass shortened commands such as <code>R.game</code> or <code>L.data</code> directly to OSCLI. Some ADFS floppy releases retain the same abbreviations. They can become ambiguous on an ADFS hard drive because ADFS adds commands including RENAME, REMOVE, LCAT, LEX and LIB.</p>
              <ol>
                <li>Import a UEF, SSD, DSD, HFE or ADF into an ADFS directory, or copy one or more MMB slots to ADFS in the usual way.</li>
                <li>Textual <code>!BOOT</code>, <code>BOOT</code>, <code>GO</code>, <code>MENU</code>, <code>LOADER</code> and <code>START</code> scripts have line-start <code>R.</code>, <code>L.</code> and <code>LO.</code> commands expanded to explicit <code>RUN</code> and <code>LOAD</code> commands.</li>
                <li>Acorn File Forge starts with conventional boot scripts, follows their directly named launch target, and checks those reachable loaders for the exact immediate-pointer sequence used to pass an inline command to OSCLI. Unrelated documentation, reviews and game data are not treated as loaders.</li>
                <li>Reachable tokenised BASIC loaders are checked for rooted paths such as <code>$.LOADER</code>. If that exact file exists inside the extracted directory, the path is made relative and the BASIC line is rebuilt. A rooted path is retained when its local target cannot be proved, so genuine volume-root dependencies are not guessed at.</li>
                <li>Before changing anything, it checks the loader's load address, the proposed extra bytes, the ADFS workspace range and every other loaded-file range from that source disk.</li>
                <li>If all checks pass, the full <code>RUN</code> or <code>LOAD</code> command is appended without moving the existing machine code. Only the proven OSCLI pointer bytes are redirected.</li>
                <li>A persistent image warning names the source slot or directory, affected file, old command and replacement. For example: <code>ADFS compatibility change made: Chuck: expanded R.EZZZIns to RUN EZZZIns</code>.</li>
                <li>If the pointer or free memory cannot be proved safe, no bytes are changed. Unresolved commands from the same reachable loader are condensed into one warning for manual testing.</li>
                <li>Test the imported program on its intended hardware before saving the final image. A static check cannot prove every self-modifying, protected or dynamically constructed loader.</li>
              </ol>
              <div class="help-warning"><strong>Existing imports are not silently rewritten:</strong> compatibility analysis runs while files are copied into ADFS. To repair a directory imported with an older version, delete that directory and import its UEF, SSD, DSD, HFE, ADF or MMB slot again. If the existing directory is populated, choose Replace only after confirming it is the correct target.</div>
            </div>
          </section>
          <section id="help-mmb-menu">
            <h3>Choose, create and maintain an MMB menu</h3>
            <figure><img src="/help/spi-menu-preview.png" alt="Interpreted SPI Game Menu with three titles and the effective disk and !BOOT launch command"><figcaption>The SPI preview decodes the installed GAMECOL program and displays its real Mode 1 palette, labels and three-field database.</figcaption></figure>
            <div class="help-task">
              <h4>Create the first MMB menu</h4>
              <ol>
                <li>Open the MMB at <strong>All disks</strong>.</li>
                <li>Choose <strong>Menu → Create / manage menu</strong>.</li>
                <li>Choose <strong>Games Universal Menu</strong> for explicit launch metadata, <strong>SPI Game Menu</strong> for the Electron MMFS menu that executes each selected disk's <code>!BOOT</code>, <strong>Electron User / Magazine Menu</strong>, <strong>Acorn User Menu</strong>, or copy a recognised menu from another pane.</li>
                <li>Select an empty slot to reserve for the chosen menu program and choose <strong>Create menu</strong>.</li>
                <li>Select a formatted software disk, then choose <strong>Menu → Add selected disk</strong>.</li>
                <li>For Universal Menu, review title, publisher, launch file, action, PAGE and unique disk title. For SPI Game Menu, review title, publisher and disk title; its launch is always the selected disk's <code>!BOOT</code>.</li>
                <li>Select <strong>Update menu</strong>, or <strong>Keep off-menu</strong> to leave that disk deliberately unlisted.</li>
                <li>Inspect the automatic interpreted preview, then save the MMB when satisfied. The heading identifies the exact installed program and screen mode.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Interpreted, not mocked:</strong> Acorn File Forge decodes both the Universal Menu display path and the SPI menu's tokenised <code>GAMECOL</code> program. The SPI program calls itself <em>ELECTRON SDI GAME MENU</em> on screen. Its preview uses the installed Mode 1 palette, heading, key legend and 26-line three-field renderer. Unsupported programs are labelled <em>Menu database preview</em> instead of receiving an invented layout.</div>
            <div class="help-note"><strong>SPI compilation disks:</strong> add each game as a separate entry with the same MMB disk title. The generated title and publisher databases retain every entry, while only one SSD occupies the slot. The installed program loads its <code>DOEXEC</code> helper, selects the disk with <code>*DIN 0 disk-title</code>, then runs that helper to execute the selected disk's <code>!BOOT</code>.</div>
            <div class="help-note"><strong>Hardware-safe menu text:</strong> metadata supplied wholly in capitals is converted to readable title case while recognised acronyms, Roman numerals, numeric forms such as <code>3D</code>, and deliberate mixed case are preserved. Title and publisher are shortened at a word boundary where possible so the complete <code>A-Title,Publisher</code> entry fits one 40-column hardware line.</div>
            <div class="help-note"><strong>MMFS loader compatibility:</strong> when a tokenised BASIC loader uses DFS's <code>#</code> single-character wildcard, the app checks the actual catalogue. If exactly one filename matches, the loader is changed to that exact name before insertion. Ambiguous references are left untouched rather than guessed.</div>
            <div class="help-note"><strong>Universal Menu PAGE:</strong> its MODE 1 program and buffers need a low BASIC PAGE. In <strong>Create / manage menu</strong>, choose <code>&amp;E00</code> for a verified paged or sideways-RAM MMFS setup, or <code>&amp;800</code> only for a verified DataCentre/low-PAGE setup. The generated <code>!BOOT</code> sets PAGE before chaining <code>UNIMENU</code>. Keep the current PAGE on other configurations.</div>
            <div class="help-note"><strong>PAGE display versus storage:</strong> the editor and preview show complete addresses such as <code>&amp;1900</code>. The original Universal Menu database stores the corresponding high byte, such as <code>19</code>, because its BBC BASIC reader adds the final <code>00</code>. Acorn File Forge performs this conversion automatically when updating or regenerating a menu.</div>
            <div class="help-note"><strong>Centred Universal Menu list:</strong> maintained menu programs add one blank display line before entry A so a full menu page sits more naturally between the heading and footer. Search results keep their original layout. Updating or auditing an existing Universal Menu applies this program repair.</div>
            <div class="help-note"><strong>EXEC !BOOT remains EXEC:</strong> Universal Menu historically used the first title's action field for its global filing-system marker, which could turn that one title into <code>CHAIN "!BOOT"</code>. Acorn File Forge upgrades the installed reader and preserves both values. Updating an older menu also recovers a first-record <code>!BOOT</code> as EXEC.</div>
            <div class="help-warning"><strong>Electron MMFS memory:</strong> <code>PAGE=&amp;E00</code> is correct only for an MMFS build using genuine sideways-RAM workspace, such as the suitable ESWMMFS or relocating ZEMMFS build. Never force ordinary EMMFS from its natural <code>&amp;1900</code> down to <code>&amp;E00</code>; BASIC then overwrites MMFS workspace and programs become corrupted. Disable the Tube for games that require the native Electron execution environment.</div>
            <div class="help-note"><strong>MMC Desktop differs from Universal Menu:</strong> it stores a fixed slot catalogue in <code>DISCCAT</code>, not publisher and launcher records. Acorn File Forge refreshes that catalogue when slots are inserted, created, cleared or moved. Use <strong>Menu → Create / manage menu → Refresh catalogue</strong> to rebuild it manually.</div>
            <div class="help-task">
              <h4>Update, repair or regenerate an existing menu</h4>
              <ol>
                <li>Choose <strong>Menu → Create / manage menu</strong>.</li>
                <li>For a Universal or SPI Game Menu, choose <strong>Bulk edit entries</strong>. The installed database opens as a compact table with headers, similar to a CSV in a spreadsheet.</li>
                <li>Edit names, publishers, disks, launch files, actions and PAGE values across as many rows as needed. Search narrows the visible rows without discarding edits. Choose <strong>Name A-Z</strong> for an alphabetical order, or drag rows by their numbered handle for a manual order.</li>
                <li>Use the copy icon to clone an entry when one MMB disk contains several games, the × icon to remove an entry, or <strong>Add row</strong> for a new title. A Universal Menu launch field opens a dropdown from that row's selected disk catalogue when focused. SPI rows omit launch settings because SPI always executes the disk's <code>!BOOT</code>.</li>
                <li>Choose <strong>Save all edits</strong> once. Acorn File Forge validates changed launchers, detects a menu changed in another tab, then replaces all menu database files together. Cancel leaves the installed menu untouched.</li>
                <li>If an inserted disk is absent, choose <strong>Add missing disks</strong> in the preview. A newly created game menu also opens this scan automatically when the MMB already contains formatted disks.</li>
                <li>When editing, choose its MMB disk by slot/title, select a launch file from that disk's populated catalogue, and set CHAIN, RUN, EXEC or LOAD plus PAGE. Saving is rejected if the disk title is missing, duplicated, or the launcher does not exist.</li>
                <li>For a broader scan, return to <strong>Create / manage menu</strong>. Choose <strong>Add previously unlisted disks</strong> to find only omitted slots, or <strong>Regenerate the complete menu</strong> to rescan all formatted non-menu disks, then select <strong>Scan disks</strong>.</li>
                <li>Review that scan, untick anything that should remain off-menu and correct ambiguous metadata. Select <strong>Add selected</strong> for missing entries or <strong>Replace menu</strong> for a complete regeneration.</li>
                <li>Choose <strong>Menu → Audit launch PAGE values</strong> at any time to compare every Universal Menu CHAIN or EXEC record with the real launcher in its MMB slot. Provable differences and legacy database encodings are repaired automatically, then the menu disk is validated. RUN, LOAD and machine-code entries are reported as not PAGE-dependent; ambiguous entries remain unchanged and are listed for review.</li>
                <li>Choose <strong>Menu → Backup menu slot</strong>, then select an empty destination. The complete menu disk is copied there as a read-only <code>MBACKUP-xxx</code> slot which is ignored by installed-menu detection and automatic scans.</li>
                <li>Choose <strong>Menu → Restore menu backup</strong> to replace the active menu slot from one of those backups. The backup is retained, drive 0 continues to point at the active slot, and a failed validation restores the pre-operation menu automatically.</li>
                <li>Open <strong>Menu → Preview installed menu</strong> and verify titles and launch commands.</li>
              </ol>
            </div>
            <p>Detection checks an existing Universal or SPI menu first, then distribution filenames, the catalogue and executable <code>!BOOT</code> commands. If those sources remain ambiguous, it searches the Complete BBC Micro Games Archive, Internet Archive and itch.io. Internet matches are offered for review and are never silently written.</p>
          </section>
          <section id="help-adfs-menu">
            <h3>Create and reorder an ADFS directory menu</h3>
            <div class="help-task">
              <h4>Create or update a menu at the current directory</h4>
              <ol>
                <li>Organise the software so each software directory represents one disk or title. Large collections may use structural groups such as GAMES1 through GAMES5.</li>
                <li>Navigate to their parent directory. This current path becomes the menu root.</li>
                <li>Choose <strong>Menu → Create / update menu here</strong>.</li>
                <li>The scanner automatically skips structural group directories and offers the contained disk directories as entries. Internal DFS-derived subpaths such as <code>eE</code> and <code>eT</code> remain part of their disk.</li>
                <li>For each directory, review its display title and publisher, then choose a launch file from the populated dropdown and select CHAIN, RUN, EXEC or LOAD.</li>
                <li>Select <strong>Create / update menu</strong>. Support files and the title/publisher databases are written at the menu root.</li>
                <li>Review the preview that opens automatically.</li>
                <li>At any installed menu root, choose <strong>Menu → Audit launch PAGE values</strong> to check its saved launch files, repair provable PAGE or legacy record-encoding errors, and validate the complete ADFS image. Repeat at each menu root if the HDD contains several menus.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Preview and reorder entries</h4>
              <ol>
                <li>At the menu root, choose <strong>Menu → Preview installed menu</strong>.</li>
                <li>Search for a title or move between preview pages to inspect its real installed launch command.</li>
                <li>Choose name ascending or descending, or drag entries into a manual order.</li>
                <li>Select <strong>Save order</strong> to rebuild the title database and index in that order.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Launching nested software:</strong> the menu stores the complete directory of the selected launch file and issues <code>*DIR</code> to that path before CHAIN, RUN, EXEC or LOAD. Grouped titles therefore start in the correct disk directory.</div>
            <div class="help-note"><strong>Automatic launch detection:</strong> the scanner checks a readable <code>!BOOT</code>, then familiar loaders such as <code>SSDMENU</code>, <code>DISKMENU</code>, <code>MENU</code>, <code>LOADER</code> and similar menu-like names. It examines the selected file and proposes EXEC for a command file, CHAIN for a BBC BASIC program at <code>&amp;1900</code>, or RUN for another conventional executable. Multiple plausible choices are left for review.</div>
            <div class="help-note"><strong>Menus follow reorganised files:</strong> renaming, moving or deleting a menu-listed directory or its selected launch file updates the installed menu databases automatically. Use Preview installed menu afterward to check the result.</div>
            <div class="help-note"><strong>Generic directory names:</strong> labels such as <code>DISC-0184</code> are not useful internet search terms. They are offered for local review immediately; genuinely named ambiguous titles are still checked against the online catalogues.</div>
            <div class="help-note"><strong>Adding extracted software:</strong> when an image is copied into ADFS, select the menu option to be offered an entry immediately. Choose Keep off-menu if it should not appear; no launch file is required in that case.</div>
            <div class="help-note"><strong>Shared menu safety:</strong> complete PAGE values are shown in every editor, while both MMB and ADFS Universal Menu databases receive the compact high-byte representation required by their installed BBC BASIC reader. PAGE override warnings and audit repairs therefore behave consistently across floppy and HDD menus.</div>
            <div class="help-note"><strong>Metadata lookup order:</strong> an existing MMB Universal or SPI Game Menu record is authoritative. Next, Acorn File Forge parses the original distribution or ZIP-member filename for a TOSEC/Ghostware-style title, date and publisher, then examines the filesystem and familiar launchers. Online catalogues are checked only while the result remains ambiguous.</div>
            <div class="help-note"><strong>MMB menu metadata comes first:</strong> every existing record for the slot is checked. Compilation disks can therefore create several ADFS menu entries pointing into the same copied directory. Universal records retain their launcher, action and PAGE. SPI records supply title and publisher, while the copied disk is examined to resolve the <code>!BOOT</code> launch inside ADFS.</div>
          </section>
          <section id="help-maintenance">
            <h3>Check, compact and monitor operations</h3>
            <div class="help-task">
              <h4>Check a filesystem</h4>
              <ol>
                <li>Open the DFS or ADFS filesystem you want to inspect. For MMB, first open the individual slot.</li>
                <li>Choose <strong>Tools → Check filesystem</strong>.</li>
                <li>Wait for the result. A structural error is reported without changing the working image.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Compact a filesystem</h4>
              <ol>
                <li>Create a named checkpoint first if the current working state is important.</li>
                <li>Choose <strong>Tools → Compact filesystem</strong>.</li>
                <li>On DFS/MMB, optionally list paths that should be placed first, such as <code>$.!BOOT,$.LOADER</code>.</li>
                <li>Confirm. Files are reorganised into low contiguous sectors and free space is consolidated.</li>
                <li>Run Check filesystem afterward, then save the compacted image.</li>
              </ol>
            </div>
            <h4>Progress, abort and retry</h4>
            <ul>
              <li>Creative and destructive controls disable as soon as an operation starts, preventing duplicate clicks.</li>
              <li>The foreground dialog reports the current phase, disk or file and completed count. Error details appear in the same foreground dialog.</li>
              <li><strong>Abort operation</strong> requests a stop at the next safe boundary. The current low-level filesystem write may need to finish first.</li>
              <li>Completed items in a bulk-copy dialog remain recorded. Use its retry path to continue with the remaining items.</li>
              <li>Do not close the browser or container during a write. A normal page refresh keeps active server sessions, but the pane should be refreshed before retrying an interrupted action.</li>
            </ul>
          </section>
          <section id="help-hex-editor">
            <h3>Raw image hex editor</h3>
            <p class="help-lead">Use the raw editor for deliberate low-level repairs and experiments. It works over the current pane without loading a complete HDD image into the browser.</p>
            <figure><img src="/help/hex-editor.png" alt="Raw image hex editor showing offset, byte, ASCII and value views"><figcaption>The editor overlays only its source pane. Other panes remain visible for reference, while the selected image is protected from other pane actions until the editor closes.</figcaption></figure>
            <div class="help-warning"><strong>Important:</strong> raw edits bypass DFS, ADFS, MMB, UEF and container rules. A plausible-looking byte change can destroy a catalogue, free-space map, checksum or disk geometry. Create a named checkpoint first when the current state matters.</div>
            <div class="help-task"><h4>Inspect and navigate raw bytes</h4><ol>
              <li>Open <strong>Tools → Hex editor</strong> in the relevant pane. It is available at the MMB All disks level as well as inside normal filesystem views.</li>
              <li>For a paired BeebSCSI image, choose the DAT or DSC from <strong>Component</strong>. The DSC option edits only the 22-byte geometry descriptor.</li>
              <li>Use first, previous, next and last page, or enter a hexadecimal offset in <strong>Go to offset</strong>. Append <code>d</code> to enter a decimal address.</li>
              <li>Choose a 128, 256, 512 or 1,024-byte page. Only that range is fetched, even for a multi-gigabyte image.</li>
              <li>Select a hex or ASCII cell. The inspector shows unsigned 8, 16 and 32-bit values in little and big-endian order.</li>
            </ol></div>
            <div class="help-task"><h4>Search, select and edit</h4><ol>
              <li>Search for hexadecimal byte pairs such as <code>44 69 73 63</code>, or switch the search to Latin-1 text. Find previous and Find next can wrap around the image.</li>
              <li>Click a byte, Shift-click another byte, or hold Shift while using the arrow keys to select a range.</li>
              <li>Choose HEX or ASCII mode, then type to replace bytes. You can also paste, fill the selection with one byte, copy as hex or text, or revert selected edits.</li>
              <li>Undo and redo affect staged editor changes only. The staged-change list shows the original and replacement value at every changed offset and can jump back to it.</li>
              <li>Use Ctrl/Cmd-S to write, Ctrl/Cmd-Z or Ctrl/Cmd-Y for undo or redo, Ctrl/Cmd-F to search, Ctrl/Cmd-G to go to an offset, and Escape to close.</li>
            </ol></div>
            <div class="help-task"><h4>Write or close safely</h4><ol>
              <li>Select <strong>Write changes</strong>. Read the <strong>This is dangerous. Are you sure?</strong> warning and confirm only if the listed byte count is expected.</li>
              <li>The server rejects the write if another action changed the image after the editor loaded it. It also rejects overlaps, out-of-range writes, resizing and an unconfirmed request.</li>
              <li>An automatic undo checkpoint is created before the fixed-size byte ranges are flushed. Cached slot, menu, tape and export data is cleared so later views cannot reuse stale content.</li>
              <li>Closing with staged bytes offers Keep editing, Discard changes, or Review and write. A protected advanced HFE can be inspected but not written.</li>
              <li>Refresh the pane and run <strong>Analyse → Image health dashboard</strong> after every raw write. Use Edit → Undo last change if the result is not sound.</li>
            </ol></div>
          </section>
          <section id="help-analysis">
            <h3>Workbench, analysis and repeatable workflows</h3>
            <p class="help-lead">The Analyse menu in each pane checks the image in context. Workbench in the page header stores reusable settings and portable workspace descriptions.</p>
            <div class="help-task"><h4>Run a complete image health check</h4><ol>
              <li>Open the pane's <strong>Analyse</strong> menu and choose <strong>Image health dashboard</strong>.</li>
              <li>Read the duration warning. Large MMB and HDD images may take several minutes; the progress view names the current directory or menu phase and Abort operation stops at a safe boundary.</li>
              <li>Review filesystem, geometry, MMB header, menu, PAGE, compatibility and hardware-profile findings together. Failed menu checks expand into individual records showing the title, slot or menu directory, disk title, launch command, PAGE, exact problem and supporting evidence.</li>
              <li>If a provably safe PAGE repair is available, inspect the itemised count and choose <strong>Repair menu PAGE values</strong>. An automatic checkpoint is made first.</li>
              <li>Run the dashboard again after repairs. Failed launcher or missing-disk checks remain manual because inventing a target would be unsafe.</li>
            </ol></div>
            <figure><img src="/help/health-dashboard.png" alt="Image health dashboard with an expanded failed MMB menu record"><figcaption>A failed menu check is not just a count. Expand it to see the menu location, target disk or slot, launch command, PAGE, exact problem and evidence.</figcaption></figure>
            <div class="help-task"><h4>Dry-run a change</h4><ol>
              <li>Select one or more files, directories or MMB slots.</li>
              <li>Choose <strong>Analyse → Dry-run selected items</strong>.</li>
              <li>Review target-name conversion, truncation and case-insensitive clashes. The dry run does not write the image.</li>
              <li>Bulk MMB-to-ADFS imports perform their more detailed capacity, grouping and collision plan in the copy dialog.</li>
            </ol></div>
            <div class="help-task"><h4>Inspect a file or loader</h4><ol>
              <li>Select a normal file and choose <strong>Analyse → Inspect selected file</strong>.</li>
              <li>Switch between text or decoded tokenised BASIC, hexadecimal bytes and detected loader commands.</li>
              <li>Small plain-text files can be edited in place. Tokenised BASIC is decoded read-only so line records cannot be corrupted by free-form text.</li>
              <li>Choose <strong>Check loader dependencies</strong> to resolve CHAIN, EXEC, RUN, LOAD, DIR and LIB targets beside the launcher and flag root-relative references before moving software below ADFS root.</li>
            </ol></div>
            <div class="help-task"><h4>Audit a collection</h4><ol>
              <li><strong>Test menu entries</strong> is enabled only when a menu is detected: anywhere in an MMB, or in the current ADFS directory. It checks disk or directory selection, launcher presence, action and PAGE for that applicable menu context.</li>
              <li>At an MMB's <strong>All disks</strong> level, <strong>Analyse → Check for duplicate games</strong> compares individual installed game titles across every disk name, catalogued file content, and complete slot images. This detects a game represented on differently named disks instead of relying on MMB disk titles alone.</li>
              <li>Duplicate game records are listed by game title, slot and disk title. Select records directly using the checkbox on each result row. Equivalent disk-content groups compare filenames, load and execution metadata, sizes, and SHA-256 file hashes. Whole-image matches remain available as the strongest disk-level check.</li>
              <li>Compilation disks receive an extra warning listing their other games. Keeping the disk removes only your selected menu record. Ejecting it clears the slot and removes every menu record associated with that disk.</li>
              <li>The same Analyse command is named <strong>Find duplicates / variants</strong> in other image views and provides the broader file and collection report, grouping byte-identical content by SHA-256 and likely variants by normalised disk or path name.</li>
              <li><strong>Export collection manifest</strong> downloads CSV or JSON containing slots, files, Acorn metadata, menu records and checksums.</li>
              <li>For MMB, edit the exported JSON menu records carefully and choose <strong>Apply reviewed JSON</strong>. Current records are compared first so a stale manifest cannot overwrite a newer menu.</li>
            </ol></div>
            <figure><img src="/help/duplicate-check.png" alt="MMB duplicate game review showing selectable menu records and equivalent disk content"><figcaption>The MMB All disks duplicate command lives only in Analyse. Tick the exact menu records to review; disks are kept unless the separate final review explicitly ejects them.</figcaption></figure>
            <div class="help-task"><h4>Profiles, recipes and projects</h4><ol>
              <li>Choose <strong>Workbench → Hardware profiles</strong>. Start from Electron Plus 3, BBC MMFS, BeebSCSI, Master ADFS or RISC OS, choose its Online Library filter, then save or apply the profile to an open image.</li>
              <li>A profile records the machine, Library filter, filing system, MMFS build, Tube state, expected PAGE and validation target. An applied profile controls that pane. The active Workbench profile is remembered and becomes the default for panes without their own profile. On first use this is Electron Plus 3. Selecting, saving or applying another profile also sets the initial machine for <strong>Find disks online</strong> and <strong>Find software online</strong>.</li>
              <li>Choose <strong>Import recipes</strong> to save naming, group prefix, online metadata, compatibility and menu choices. Saved recipes appear in the MMB-to-ADFS planner.</li>
              <li>Choose <strong>Portable project</strong> to export the current pane order, session references, paths, profiles and recipes. Import it on the same retained installation to restore that working context. Theme remains a browser preference.</li>
            </ol></div>
            <div class="help-task"><h4>Monitor, abort and resume jobs</h4><ol>
              <li>Choose <strong>Jobs</strong> in the header. Running, paused, failed, completed and interrupted work remains visible after its foreground dialog closes.</li>
              <li>Abort requests stop at the next safe filesystem boundary.</li>
              <li>Resumable bulk jobs retain their request, completed slots and skipped slots. Choose <strong>Resume</strong> to submit only the remaining items.</li>
              <li>After a container restart, an unfinished job is marked interrupted instead of disappearing. Use Resume after checking the destination pane.</li>
            </ol></div>
            <figure><img src="/help/workbench-analysis.png" alt="Acorn File Forge Workbench and image analysis tools"><figcaption>Workbench holds reusable settings; each pane's Analyse menu runs checks against the currently open image.</figcaption></figure>
          </section>
          <section id="help-saving">
            <h3>Save, close and recover safely</h3>
            <div class="help-task">
              <h4>Keep your changes</h4>
              <ol>
                <li>Look for the orange changed dot in the pane heading.</li>
                <li>Select the <strong>Save Image</strong> icon in the pane heading. The progress bar consistently covers validation, checksums, catalogue generation and complete ZIP construction for every format.</li>
                <li>The ready dialog appears only when the timestamped ZIP is actually complete. The automatic browser download should start immediately; use the dialog's direct <strong>Download ZIP</strong> link if it does not appear.</li>
                <li>Any validation, checksum or archive failure remains inside the app instead of replacing the page with a JSON response.</li>
                <li>Once preparation succeeds, the orange changed dot clears in every pane showing that image. It returns after the next edit. A failed save leaves the dot visible.</li>
                <li>Every save is a ZIP named with the image name and current date/time. This avoids duplicate <code>-edited</code> downloads.</li>
                <li>Every ZIP contains <code>README.md</code> with checksums, target hardware, compatibility warnings, practical restore notes and a complete catalogue. MMB documentation includes all 511 slots, including empty slots, access state and each disk's DFS files.</li>
                <li>DAT/DSC pairs stay together in a <code>BeebSCSI0</code> directory inside the ZIP. Edited HFE images are encoded and sector-verified before downloading.</li>
                <li>Keep the original image until the edited download has been checked in an emulator or on a copy of the target media.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Recover after a refresh or interrupted download</h4>
              <ol>
                <li>Use any empty pane. If none is displayed, select <strong>Add Pane</strong>. If three are occupied, close one after saving or use its <strong>Load New Image</strong> heading button to open a replacement.</li>
                <li>Select <strong>Recover previous session</strong>.</li>
                <li>Choose the retained working image. The newest session is selected first and each entry shows its name, size and last-change time.</li>
                <li>Select <strong>Recover session</strong>. Completed edits, the DAT/DSC pairing and the target-hardware profile are restored.</li>
                <li>Check the current directory, then select Save again.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Keep recovery private or clear old sessions</h4>
              <ol>
                <li>Recovery is tied to an opaque identity kept in both a private cookie and this site's browser storage. Either copy restores the other after a restart. Another browser profile or user receives a different identity and cannot list, open or delete your sessions.</li>
                <li>In the recovery dialog, select <strong>Clear selected</strong> to delete one old working copy, or <strong>Clear all previous</strong> to delete every previous copy shown. Images currently open in any pane are protected from this list.</li>
                <li>Clearing removes only retained server working data. It never deletes the original file previously selected from your computer.</li>
                <li>Clearing both this site's cookies and browser storage removes the browser identity. Keep the same browser profile while recoverable work remains important, and download finished images before clearing site data.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Close or discard a working image</h4>
              <ol>
                <li>Select × in the pane heading, or on an empty pane, to remove that whole pane from the workspace. A changed image offers Save and close, Close without saving, or Cancel. Closing only detaches the image and keeps its server-side working copy.</li>
                <li>Use <strong>Recover previous session</strong> to reopen the image with its completed changes.</li>
                <li>To remove retained storage permanently, use <strong>Clear selected</strong> in the recovery dialog and confirm the deletion.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Two layers of safety:</strong> editing never writes to the source selected in your browser, and automatic undo points protect recent working-copy changes. Named checkpoints are ideal before large deletions, compaction or bulk menu work.</div>
          </section>
          <section id="help-shortcuts">
            <h3>Keyboard and mouse reference</h3>
            <dl>
              <dt>Click</dt><dd>Select one item.</dd>
              <dt>Ctrl/Cmd-click</dt><dd>Add or remove an item from the selection.</dd>
              <dt>Shift-click</dt><dd>Select a continuous range.</dd>
              <dt>Ctrl/Cmd-A</dt><dd>Select every usable item in the current view.</dd>
              <dt>Ctrl/Cmd-X</dt><dd>Cut the selected items or MMB slots for one safe paste.</dd>
              <dt>Ctrl/Cmd-C</dt><dd>Copy the selected items or MMB slots for one paste.</dd>
              <dt>Ctrl/Cmd-V</dt><dd>Paste into the current directory, DFS catalogue group, or selected MMB slot.</dd>
              <dt>Escape</dt><dd>Cancel a pending clipboard selection when no dialog is open.</dd>
              <dt>Double-click / Enter</dt><dd>Open a directory or MMB disk.</dd>
              <dt>Double-click a file</dt><dd>Download a ZIP containing the file and its <code>.inf</code> metadata.</dd>
              <dt>Delete</dt><dd>Delete the selected object after confirmation.</dd>
              <dt>Drag selected files</dt><dd>Copy them to a compatible destination.</dd>
              <dt>Drag MMB slots</dt><dd>Cut and paste as one block within an MMB, or copy to another image.</dd>
              <dt>Alt+Left / Alt+Right on pane grip</dt><dd>Move a pane without dragging it.</dd>
              <dt>Breadcrumb</dt><dd>Jump directly to an ancestor directory.</dd>
              <dt>Refresh ↻</dt><dd>Reread the current view while preserving useful selection state.</dd>
            </dl>
          </section>
          <section id="help-accessibility">
            <h3>Accessibility and appearance</h3>
            <p class="help-lead">The interface targets WCAG 2.2 AA in both its BBC Model B light theme and complementary dark theme.</p>
            <ul>
              <li>Use the first keyboard link, <strong>Skip to workspace</strong>, to bypass the header. All buttons, menus, rows, form controls and dialogs have visible keyboard focus.</li>
              <li>Press Tab and Shift-Tab to move through controls. Enter opens the focused directory or MMB slot. Native modal dialogs and safety warnings retain keyboard focus until they close.</li>
              <li>The <strong>Light / Dark</strong> button follows the operating-system preference on first use and remembers your choice. Both palettes meet AA text contrast, and control boundaries and focus indicators meet non-text contrast requirements.</li>
              <li>Selection, access, warnings, errors and progress use words, shapes or symbols as well as colour. Status and error regions are announced to screen readers.</li>
              <li>Browser zoom and narrower windows are supported. With reduced motion enabled in the operating system, non-essential transitions and animations are suppressed.</li>
            </ul>
            <div class="help-note"><strong>Theme maintenance:</strong> the palette is isolated in <code>theme.css</code>. Layout and component geometry remain in <code>styles.css</code>, so a replacement palette can be reviewed for contrast without changing the application structure.</div>
          </section>
          <section id="help-limits">
            <h3>Compatibility, limits and troubleshooting</h3>
            <h4>Important compatibility limits</h4>
            <ul>
              <li>The current filesystem engine safely edits DFS, ADFS S/M/L, supported old-map D/hard-drive layouts and BeebSCSI DAT with its matching DSC.</li>
              <li>New-map E, F, F+ and later large FileCore variants are rejected instead of being guessed at. An <code>.adf</code> extension alone does not guarantee a supported layout.</li>
              <li>“Physical HDD” means a byte-for-byte RAW image. The browser and container do not access devices such as <code>/dev/sdb</code> directly.</li>
              <li>UEF tape catalogues are read-only; convert or copy their reconstructed files into writable media.</li>
              <li>HFE v2/v3, bad-sector and advanced track images open read-only. Clean sector-based HFE v1 images can be edited and are verified again when saved.</li>
              <li>Metadata is preserved only where the destination filing system has an equivalent field.</li>
            </ul>
            <h4>When something does not work</h4>
            <dl>
              <dt>Button is disabled</dt><dd>Select a suitable item first, or wait for the current pane operation to finish. Blank-disk creation requires an empty MMB slot.</dd>
              <dt>Invalid filename</dt><dd>Use the prompted replacement. DFS leaf names are seven characters; supported old ADFS formats commonly allow ten.</dd>
              <dt>Not enough space</dt><dd>Delete unwanted data, compact the filesystem, or create a larger destination. DFS also has a 31-file catalogue limit.</dd>
              <dt>DSD will not insert</dt><dd>Choose a starting position with two adjacent empty MMB slots.</dd>
              <dt>HFE is read-only</dt><dd>The image uses HFE v2/v3, reports bad sectors, or contains track features the sector editor cannot reproduce safely. Export its files or copy its readable sectors to another image.</dd>
              <dt>Name collision found</dt><dd>Use the default DISC-0000 naming strategy, or review every highlighted name. The check is case-insensitive and scoped to each destination parent.</dd>
              <dt>Empty disk found</dt><dd>Choose Skip and continue or Abort. Blank disks can be stored in MMB, but do not become empty ADFS directories.</dd>
              <dt>Destination exists</dt><dd>An empty directory is reused silently. A populated directory offers Keep, Replace or Abort; a file is never overwritten as though it were an empty directory.</dd>
              <dt>DAT geometry error</dt><dd>Close the session and reopen the original DAT with its exact matching DSC file.</dd>
              <dt>Network error</dt><dd>Keep the dialog open, inspect its detailed stage, refresh the destination pane if necessary, then use retry. Online metadata can be entered manually.</dd>
              <dt>Menu entry is wrong</dt><dd>Preview the installed menu, correct launch choices during an update, or regenerate the complete database.</dd>
              <dt>View appears stale</dt><dd>Select ↻ in that pane. In an MMB disk use All disks, not the root breadcrumb, to return to the slot index.</dd>
              <dt>A refresh shows the start screen</dt><dd>Current browser-owned panes and their open directories are restored automatically after a normal page refresh. On the first refresh after upgrading from an older version, the newest browser-owned working session is reopened as a bridge. Closing a pane deliberately removes it from auto-restore while retaining its server recovery copy.</dd>
            </dl>
            <div class="help-note"><strong>Launcher rule:</strong> when a disk contains SSDMENU it is preferred over !BOOT and launched with CHAIN. Otherwise Acorn File Forge inspects !BOOT and conventional loaders to choose the safest action and PAGE value.</div>
            <div class="help-warning"><strong>PAGE safety:</strong> every new Universal or ADFS menu entry starts with the PAGE derived from its selected launcher in the actual image. CHAIN uses the tokenised BASIC program's saved address; EXEC follows readable boot commands to that program. Machine-code launches are identified as not using BASIC PAGE. Changing a derived value opens a Yes/Cancel warning because an incorrect PAGE can overwrite filing-system or loader workspace and cause corrupted BASIC, hangs or crashes on real hardware.</div>
            <div class="help-note"><strong>Best practice:</strong> work from copies, create named checkpoints, download finished images, validate after large operations, and test the result before restoring it to real media.</div>
          </section>
          <section id="help-project">
            <h3>Project and support</h3>
            <p class="help-lead">Acorn File Forge is an open-source project. The README in the repository tracks the current formats, workflows, limits and technical notes.</p>
            <div class="help-task"><h4>Get the code or report a problem</h4><ol>
              <li>Visit <a href="https://github.com/peteclarke-del/AcornFileForge" target="_blank" rel="noopener noreferrer">github.com/peteclarke-del/AcornFileForge</a>.</li>
              <li>When reporting a problem, include the image format, target hardware profile, operation, visible error and whether the original image still opens correctly.</li>
              <li>Do not attach commercial disk images unless you have permission to share them. A catalogue, screenshot and exact error are often enough to start investigating.</li>
              <li>The repository and its source archives do not include the local <code>samples/</code> directory. Developers can place their own test images there without adding them to Git, <code>git archive</code> output or the Docker build context.</li>
            </ol></div>
            <div class="help-note"><strong>Saved archives are self-documenting:</strong> every downloaded ZIP contains a README with the image details, checksum, target profile, warnings and catalogue, plus a link back to the current project documentation.</div>
          </section>
        </div>
      </div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close help</button></div>
    </div>`);
  const layout = modalContent.querySelector(".help-layout");
  const content = modalContent.querySelector(".help-content");
  modalContent.querySelectorAll(".help-toc a").forEach(link => {
    link.addEventListener("click", event => {
      event.preventDefault();
      const target = modalContent.querySelector(link.getAttribute("href"));
      if (!target) return;
      const scrollHost = content.scrollHeight > content.clientHeight ? content : layout;
      const top = scrollHost.scrollTop
        + target.getBoundingClientRect().top
        - scrollHost.getBoundingClientRect().top;
      scrollHost.scrollTo({ top, behavior: "smooth" });
    });
  });
}

const PROFILE_STORAGE_KEY = "acorn-file-forge-hardware-profiles";
const RECIPE_STORAGE_KEY = "acorn-file-forge-import-recipes";

const BUILTIN_PROFILES = [
  { name: "Electron Plus 3", machine: "Electron", catalogMachine: "electron", filingSystem: "ADFS", targetHardware: "electron-plus3", mmfsBuild: "paged", tube: false, page: "E00", menuType: "universal" },
  { name: "BBC Micro with MMFS", machine: "BBC Micro", catalogMachine: "bbc-b", filingSystem: "MMFS", targetHardware: "bbc-master", mmfsBuild: "paged", tube: false, page: "E00", menuType: "universal" },
  { name: "BBC/Master BeebSCSI", machine: "BBC/Master", catalogMachine: "all", filingSystem: "ADFS + MMFS", targetHardware: "beebscsi", mmfsBuild: "paged", tube: false, page: "E00", menuType: "universal" },
  { name: "Master 128 ADFS", machine: "Master 128", catalogMachine: "master", filingSystem: "ADFS", targetHardware: "bbc-master", mmfsBuild: "none", tube: false, page: "1900", menuType: "universal" },
  { name: "Archimedes / RISC OS", machine: "Archimedes", catalogMachine: "archimedes", filingSystem: "FileCore", targetHardware: "risc-os", mmfsBuild: "none", tube: false, page: "", menuType: "none" },
];

function storedCollection(key, fallback = []) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    return Array.isArray(value) ? value : fallback;
  } catch (_error) { return fallback; }
}

function saveCollection(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function downloadDocument(name, content, type = "application/json") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function analysisLoading(title, detail) {
  showModal(
    `<div class="analysis-loading"><span class="modal-progress-icon">↻</span><h2>${esc(title)}</h2><p>${esc(detail)}</p><span class="progress"><i></i></span></div>`,
    null,
    { replace: modal.open }
  );
}

function replaceAnalysisLoading(html, onSubmit = null) {
  if (!modal.open) return false;
  showModal(html, onSubmit, { replace: true });
  return true;
}

async function runHealthCheck(index) {
  const pane = panes[index];
  modal.classList.add("busy");
  setModalProgress({
    title: "Checking image health",
    message: `Starting the structural scan of ${pane.image.name}…`,
    details: [
      { label: "Large images", value: "Directory and menu traversal can take several minutes" },
      { label: "Safety", value: "This check is read-only and may be aborted at a safe boundary" },
    ],
  });
  try {
    return await trackedPaneOperation(
      index,
      "Checking image health",
      operationId => api(
        `/api/images/${pane.image.id}/health?${new URLSearchParams({ operationId })}`
      ),
    );
  } finally {
    modal.classList.remove("busy");
  }
}

function renderHealthDashboard(index, report) {
  const pane = panes[index];
  const icon = { pass: "✓", warn: "!", fail: "×" };
  const renderFinding = finding => {
    const menuLocation = finding.menuRoot
      ? `Menu ${finding.menuRoot}`
      : finding.menuSlot != null
        ? `Menu slot ${finding.menuSlot}${finding.menuType ? ` (${finding.menuType})` : ""}`
        : "Menu location unknown";
    const targetLocation = finding.slots?.length
      ? `target slot ${finding.slots.join(", ")} · disk ${finding.diskTitle || "Untitled"}`
      : `target disk ${finding.diskTitle || "not found"}`;
    const command = [finding.action, finding.launcher].filter(Boolean).join(" ") || "No launch command";
    const page = finding.page ? ` · PAGE &${finding.page}` : "";
    return `<li><strong>Record ${Number(finding.record)} · ${esc(finding.title)}</strong><small>${esc(menuLocation)} · ${esc(targetLocation)}</small><small>${esc(command)}${esc(page)}</small>${(finding.problems || []).map(problem => `<em>${esc(problem)}</em>`).join("")}${finding.evidence ? `<small>Evidence: ${esc(finding.evidence)}</small>` : ""}</li>`;
  };
  const renderCheck = check => `<article class="health-check ${esc(check.status)}"><b>${icon[check.status] || "·"}</b><span><strong>${esc(check.name)}</strong><small>${esc(check.detail)}</small>${check.findings?.length ? `<details class="health-findings" ${check.status === "fail" ? "open" : ""}><summary>${check.findings.length} itemised ${check.findings.length === 1 ? "failure" : "failures"}</summary><ol>${check.findings.map(renderFinding).join("")}</ol></details>` : ""}</span></article>`;
  if (!replaceAnalysisLoading(`<div class="analysis-dialog wide-analysis">
      <header><div><small>UNIFIED IMAGE HEALTH</small><h2>${esc(pane.image.name)}</h2></div><span class="health-score ${esc(report.status)}">${esc(report.status)}</span></header>
      <div class="health-checks">${report.checks.map(renderCheck).join("") || "<p>No checks were applicable.</p>"}</div>
      ${report.repairable.length ? `<div class="help-note"><strong>Safe repairs available</strong>${report.repairable.map(item => `<p>${esc(item.label)} · ${esc(item.detail)}</p>`).join("")}</div>` : ""}
      <div class="modal-actions"><button class="button ghost" value="cancel">Close</button>${report.repairable.map(item => `<button class="button" data-health-repair="${esc(item.action)}" data-health-root="${esc(item.root || "")}" type="button">${esc(item.label)}</button>`).join("")}<button class="button primary" data-refresh-health type="button">Run again</button></div>
    </div>`)) return false;
  modalContent.querySelector("[data-refresh-health]").onclick = async event => {
    event.currentTarget.disabled = true;
    try {
      renderHealthDashboard(index, await runHealthCheck(index));
    } catch (error) {
      toast(error.message, true);
    }
  };
  modalContent.querySelectorAll("[data-health-repair]").forEach(button => button.onclick = async () => {
    try {
      button.disabled = true;
      const data = await api(`/api/images/${pane.image.id}/health/repair`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: button.dataset.healthRepair, root: button.dataset.healthRoot || undefined }) });
      pane.image = data.image;
      await refreshCurrentView(index);
      renderHealthDashboard(index, await runHealthCheck(index));
    } catch (error) {
      button.disabled = false;
      toast(error.message, true);
    }
  });
  return true;
}

function showHealthDashboard(index) {
  const pane = panes[index];
  const large = pane.image.size >= 20 * 1024 * 1024 || ["mmb", "adfs"].includes(pane.image.kind);
  showModal(`<div class="analysis-dialog health-introduction">
    <small>READ-ONLY IMAGE AUDIT</small>
    <h2>Check ${esc(pane.image.name)}</h2>
    <div class="help-warning"><strong>${large ? "This may take several minutes." : "This may take a little while."}</strong> Acorn File Forge will traverse the filesystem, validate its structure and inspect applicable menu records. Very large HDD and MMB images may not produce a result immediately.</div>
    <div class="help-note"><strong>It has not hung:</strong> the progress view will show the current directory or menu phase. You may use Abort operation to stop at the next safe boundary. No image data is changed by the health check.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button primary" value="run">Run health check</button></div>
  </div>`, async () => {
    const report = await runHealthCheck(index);
    renderHealthDashboard(index, report);
    return false;
  });
}

async function showSelectionPreflight(index) {
  const pane = panes[index];
  const items = selectedEntries(index).map(entry => ({
    name: entry.name,
    source: pane.image.kind === "mmb" && pane.slot === null ? `Slot ${entry.slot}` : fullPath(pane.path, entry.name),
    type: entry.type,
  }));
  if (!items.length) return toast("Select one or more items to dry-run.", true);
  analysisLoading("Dry-run preflight", `Reviewing ${items.length} selected item${items.length === 1 ? "" : "s"}…`);
  try {
    const report = await api(`/api/images/${pane.image.id}/preflight`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation: "selection", changes: items })
    });
    if (!replaceAnalysisLoading(`<div class="analysis-dialog wide-analysis"><small>PREFLIGHT / NO IMAGE WRITES</small><h2>${esc(report.summary)}</h2>
      <div class="preflight-list">${items.map((item, offset) => `<article><b>${offset + 1}</b><span><strong>${esc(item.name)}</strong><small>${esc(item.source)} · ${esc(item.type)}</small></span></article>`).join("")}</div>
      <div class="finding-list">${report.issues.map(item => `<p class="finding ${esc(item.severity)}"><b>${esc(item.severity)}</b>${esc(item.message)}</p>`).join("") || '<p class="finding pass"><b>ready</b>No truncation or clashes were detected.</p>'}</div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div></div>`)) return;
  } catch (error) { toast(error.message, true); modal.close(); }
}

function selectedInspectable(index) {
  const pane = panes[index];
  const entry = selectedEntry(index);
  return entry && entry.type !== "dir" && entry.type !== "directory"
    ? { pane, entry, path: fullPath(pane.path, entry.name) }
    : null;
}

async function showFileInspector(index) {
  const selected = selectedInspectable(index);
  if (!selected) return toast("Select one file to inspect.", true);
  const { pane, entry, path } = selected;
  analysisLoading("Inspecting file", path);
  const query = new URLSearchParams({ path, ...(pane.slot != null ? { slot: pane.slot } : {}), ...(pane.side != null ? { side: pane.side } : {}) });
  try {
    const report = await api(`/api/images/${pane.image.id}/inspect?${query}`);
    const canEdit = report.editable && !pane.image.readOnly;
    if (!replaceAnalysisLoading(`<div class="analysis-dialog file-inspector"><header><div><small>${esc(report.view.toUpperCase())} VIEW · ${humanSize(report.size)}</small><h2>${esc(entry.name)}</h2></div><code>${esc(report.sha256.slice(0, 16))}…</code></header>
      <nav class="inspector-tabs"><button type="button" data-view="primary" class="active">${report.tokenisedBasic ? "BASIC" : report.view === "text" ? "Text" : "Hex"}</button><button type="button" data-view="hex">Hex</button><button type="button" data-view="commands">Loader commands (${report.commands.length})</button></nav>
      <textarea class="inspector-content" name="inspectedText" spellcheck="false" ${canEdit ? "" : "readonly"}>${esc(report.view === "hex" ? report.hex : report.text)}</textarea>
      <div class="inspector-commands" hidden>${report.commands.map(item => `<p><b>${esc(item.action)}</b><code>${esc(item.target)}</code></p>`).join("") || "<p>No conventional loader commands were detected.</p>"}</div>
      ${report.truncated ? '<div class="help-warning">Preview limited to the first 1 MiB.</div>' : ""}
      ${report.tokenisedBasic ? '<div class="help-note">Tokenised BASIC is decoded safely but protected from free-form editing. Use dependency and compatibility repairs for loader changes.</div>' : ""}
      <div class="modal-actions"><button class="button ghost" value="cancel">Close</button>${canEdit ? '<button class="button primary" value="save">Save text</button>' : ""}</div></div>`,
    canEdit ? async form => {
      const data = await api(`/api/images/${pane.image.id}/inspect`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, slot: pane.slot, side: pane.side, text: form.get("inspectedText") })
      });
      pane.image = data.image;
      await loadDirectory(index);
      toast(`${entry.name} updated safely`);
    } : null)) return;
    const textarea = modalContent.querySelector(".inspector-content");
    const commands = modalContent.querySelector(".inspector-commands");
    modalContent.querySelectorAll(".inspector-tabs button").forEach(button => button.onclick = () => {
      modalContent.querySelectorAll(".inspector-tabs button").forEach(item => item.classList.toggle("active", item === button));
      const view = button.dataset.view;
      commands.hidden = view !== "commands";
      textarea.hidden = view === "commands";
      if (view === "hex") { textarea.value = report.hex; textarea.readOnly = true; }
      else if (view === "primary") { textarea.value = report.view === "hex" ? report.hex : report.text; textarea.readOnly = !canEdit; }
    });
  } catch (error) { toast(error.message, true); modal.close(); }
}

async function showDependencyReport(index) {
  const selected = selectedInspectable(index);
  if (!selected) return toast("Select a launcher file first.", true);
  const { pane, path } = selected;
  analysisLoading("Checking loader dependencies", path);
  const query = new URLSearchParams({ path, ...(pane.slot != null ? { slot: pane.slot } : {}), ...(pane.side != null ? { side: pane.side } : {}) });
  try {
    const report = await api(`/api/images/${pane.image.id}/dependencies?${query}`);
    if (!replaceAnalysisLoading(`<div class="analysis-dialog"><small>DEPENDENCY-AWARE COPY CHECK</small><h2>${report.safeForSubdirectory ? "Safe for a subdirectory" : "Review before moving"}</h2>
      <div class="health-checks">${report.dependencies.map(item => `<article class="health-check ${item.resolved && !item.rootRelative ? "pass" : "warn"}"><b>${item.resolved ? "✓" : "!"}</b><span><strong>${esc(item.action)} ${esc(item.target)}</strong><small>${item.resolved ? `Found at ${esc(item.path)}` : "Not found beside launcher"}${item.rootRelative ? " · root-relative" : ""}</small></span></article>`).join("") || "<p>No conventional file dependencies were found.</p>"}</div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div></div>`)) return;
  } catch (error) { toast(error.message, true); modal.close(); }
}

async function showMenuTests(index) {
  const pane = panes[index];
  analysisLoading("Testing menu entries", "Checking disk selection, launcher, action and PAGE…");
  try {
    const query = pane.image.kind === "adfs"
      ? `?${new URLSearchParams({ root: pane.path })}`
      : "";
    const report = await api(`/api/images/${pane.image.id}/menu-tests${query}`);
    if (!replaceAnalysisLoading(`<div class="analysis-dialog wide-analysis"><header><div><small>MENU-ENTRY TEST RUNNER</small><h2>${report.passed} passed · ${report.failed} failed</h2></div></header>
      <div class="test-results">${report.tests.map(test => `<article class="${test.passed ? "pass" : "fail"}"><b>${test.passed ? "✓" : "×"}</b><span><strong>${esc(test.title)}</strong><small>${esc(test.diskTitle)} · ${esc(test.action)} ${esc(test.launcher)} · PAGE &amp;${esc(test.page || "-")}</small>${test.problems.map(problem => `<em>${esc(problem)}</em>`).join("")}</span></article>`).join("") || "<p>No editable game-menu records were found.</p>"}</div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div></div>`)) return;
  } catch (error) { toast(error.message, true); modal.close(); }
}

async function showDuplicateReport(index) {
  const pane = panes[index];
  analysisLoading("Finding duplicates and variants", "Hashing catalogues and comparing normalised titles…");
  try {
    const report = await api(`/api/images/${pane.image.id}/duplicates`);
    const group = (items, exact) => `<article><strong>${exact ? "Byte-identical" : "Likely variants"} · ${items.length}</strong><small>${items.map(item => item.diskTitle ? `Slot ${item.slot}: ${item.diskTitle}` : item.path).map(esc).join("<br>")}</small></article>`;
    if (!replaceAnalysisLoading(`<div class="analysis-dialog wide-analysis"><small>DUPLICATE / VARIANT FINDER</small><h2>${report.exact.length} exact groups · ${report.variants.length} variant groups</h2>
      <div class="duplicate-groups">${report.exact.map(items => group(items, true)).join("")}${report.variants.map(items => group(items, false)).join("") || "<p>No likely variants were found.</p>"}</div>
      <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div></div>`)) return;
  } catch (error) { toast(error.message, true); modal.close(); }
}

async function showMmbDuplicateCheck(index) {
  const pane = panes[index];
  if (pane.image?.kind !== "mmb" || pane.slot != null) {
    return toast("Open the MMB All disks view to check duplicate slots.", true);
  }
  analysisLoading("Checking MMB duplicates", "Hashing complete disk slots and reading the installed menu…");
  try {
    const [report, menu] = await Promise.all([
      api(`/api/images/${pane.image.id}/duplicates`),
      api(`/api/images/${pane.image.id}/menu`),
    ]);
    const slotGroup = items => items
      .filter(item => item.recordType === "slot" && item.formatted)
      .sort((left, right) => Number(left.slot) - Number(right.slot));
    const exactGroups = report.exact.map(slotGroup).filter(items => items.length > 1);
    const exactSignatures = new Set(exactGroups.map(items => items.map(item => item.slot).join(",")));
    const variantGroups = report.variants
      .map(slotGroup)
      .filter(items => items.length > 1 && !exactSignatures.has(items.map(item => item.slot).join(",")));
    const gameDuplicates = Array.isArray(report.gameDuplicates) ? report.gameDuplicates : [];
    const contentMatches = Array.isArray(report.contentMatches) ? report.contentMatches.map(slotGroup).filter(items => items.length > 1) : [];
    const duplicateGameIndexes = new Set(gameDuplicates.flatMap(items => items.map(item => Number(item.entryIndex))));
    const installedEntries = Array.isArray(menu.entries) ? menu.entries : [];
    const matchingMenuEntries = installedEntries
      .map((entry, entryIndex) => ({ entry, entryIndex }))
      .filter(({ entryIndex }) => duplicateGameIndexes.has(entryIndex));
    const editableMenu = menu.configured && ["universal", "universal-4r", "spi-game-menu"].includes(menu.menuType);
    const renderGroup = (items, label) => `<article class="duplicate-disk-group">
      <header><strong>${esc(label)}</strong><small>${items.length} slots</small></header>
      ${items.map(item => `<span><code>${Number(item.slot)}</code><b>${esc(item.diskTitle || item.sourceName || "Untitled disk")}</b><em>${Number(item.fileCount || 0)} files</em></span>`).join("")}
    </article>`;
    const renderGameGroup = items => `<article class="duplicate-game-group">
      <header><strong>${esc(items[0]?.title || "Untitled game")}</strong><small>${items.length} menu records</small></header>
      ${items.map(item => editableMenu
        ? `<label class="duplicate-game-record"><input type="checkbox" name="menuEntry" value="${Number(item.entryIndex)}"><code>${item.slots?.length ? item.slots.map(Number).join(", ") : "?"}</code><span><b>${esc(item.diskTitle || "Untitled disk")}</b><em>${esc(item.publisher || "Unknown publisher")} · ${esc(item.action || "CHAIN")} ${esc(item.filename || "?")}</em></span></label>`
        : `<div class="duplicate-game-record"><code>${item.slots?.length ? item.slots.map(Number).join(", ") : "?"}</code><span><b>${esc(item.diskTitle || "Untitled disk")}</b><em>${esc(item.publisher || "Unknown publisher")} · ${esc(item.action || "CHAIN")} ${esc(item.filename || "?")}</em></span></div>`
      ).join("")}
    </article>`;
    const menuStatus = !menu.configured
      ? '<div class="help-note"><strong>No installed menu was detected.</strong> The duplicate slots are listed for review, but there are no menu records to remove.</div>'
      : !editableMenu
        ? `<div class="help-note"><strong>${esc(menu.menuType || "This menu")} is read-only here.</strong> Duplicate slots are listed, but this menu format cannot be edited safely by Acorn File Forge.</div>`
        : !matchingMenuEntries.length
          ? '<div class="help-note"><strong>No duplicate game menu records were found.</strong> Content matches without corresponding menu records remain review-only.</div>'
          : "";
    showModal(`<div class="analysis-dialog wide-analysis mmb-duplicate-review">
      <small>MMB DUPLICATE CHECK</small><h2>${gameDuplicates.length} duplicate game ${gameDuplicates.length === 1 ? "group" : "groups"} · ${exactGroups.length + contentMatches.length} disk-content ${exactGroups.length + contentMatches.length === 1 ? "match" : "matches"}</h2>
      <p>Game matches come from individual installed menu titles, regardless of the disk names. Tick a game row here to remove that record. Disk-content matches compare catalogued filenames, metadata, and file hashes.</p>
      <div class="duplicate-game-groups">${gameDuplicates.map(renderGameGroup).join("") || '<div class="help-note"><strong>No duplicate installed game titles were found.</strong> Differently named disks can still appear in the content matches below.</div>'}</div>
      ${contentMatches.length ? `<details class="duplicate-variants" open><summary>${contentMatches.length} equivalent disk-content ${contentMatches.length === 1 ? "group" : "groups"} with different image bytes</summary><div class="duplicate-disk-groups">${contentMatches.map(items => renderGroup(items, "Equivalent catalogue content")).join("")}</div></details>` : ""}
      <details class="duplicate-variants" ${gameDuplicates.length || contentMatches.length ? "" : "open"}><summary>${exactGroups.length} byte-identical whole-disk ${exactGroups.length === 1 ? "group" : "groups"}</summary><div class="duplicate-disk-groups">${exactGroups.map(items => renderGroup(items, "Byte-identical disks")).join("") || '<div class="help-note"><strong>No byte-identical disks were found.</strong></div>'}</div></details>
      ${variantGroups.length ? `<details class="duplicate-variants"><summary>Review ${variantGroups.length} possible disk-title ${variantGroups.length === 1 ? "variant" : "variants"}</summary><div class="duplicate-disk-groups">${variantGroups.map(items => renderGroup(items, "Similar disk titles")).join("")}</div></details>` : ""}
      ${menuStatus}
      <div class="help-warning"><strong>No disk is ejected automatically.</strong> After choosing menu records, a second review asks whether the associated slots should also be cleared.</div>
      <div class="modal-actions"><button class="button ghost" value="cancel">Close</button>${editableMenu && matchingMenuEntries.length ? '<button class="button danger remove-duplicate-menu" value="review" disabled>Review selected duplicates</button>' : ""}</div>
    </div>`, form => {
      const selectedIndexes = new Set(form.getAll("menuEntry").map(Number));
      if (!selectedIndexes.size) return;
      setTimeout(() => showMmbDuplicateCleanupChoices(index, installedEntries, selectedIndexes, report.slots || exactGroups.flat()), 0);
    }, { replace: true });
    const removeButton = modalContent.querySelector(".remove-duplicate-menu");
    modalContent.querySelectorAll('[name="menuEntry"]').forEach(checkbox => checkbox.onchange = () => {
      removeButton.disabled = !modalContent.querySelector('[name="menuEntry"]:checked');
    });
  } catch (error) {
    toast(error.message, true);
    modal.close();
  }
}

function showMmbDuplicateCleanupChoices(index, installedEntries, selectedIndexes, slotRecords) {
  const pane = panes[index];
  const selectedTitles = new Set([...selectedIndexes].map(entryIndex =>
    String(installedEntries[entryIndex]?.diskTitle || "").trim().toLocaleLowerCase()
  ).filter(Boolean));
  const candidateSlots = slotRecords.filter(item =>
    selectedTitles.has(String(item.diskTitle || "").trim().toLocaleLowerCase())
  );
  const entriesForDisk = diskTitle => installedEntries
    .map((entry, entryIndex) => ({ entry, entryIndex }))
    .filter(({ entry }) => String(entry.diskTitle || "").trim().toLocaleLowerCase() === String(diskTitle || "").trim().toLocaleLowerCase());
  const slotChoices = candidateSlots.map(slot => {
    const related = entriesForDisk(slot.diskTitle);
    const otherGames = related.filter(({ entryIndex }) => !selectedIndexes.has(entryIndex));
    const multiGame = related.length > 1;
    return `<fieldset class="duplicate-eject-choice">
      <legend>Slot ${Number(slot.slot)} · ${esc(slot.diskTitle || slot.sourceName || "Untitled disk")}</legend>
      ${multiGame ? `<div class="help-warning"><strong>Multi-game disk with ${related.length} menu titles.</strong><span>Ejecting it also removes:</span><ul>${otherGames.map(({ entry }) => `<li>${esc(entry.title || "Untitled entry")} · ${esc(entry.publisher || "Unknown publisher")}</li>`).join("") || "<li>All selected titles on this disk</li>"}</ul></div>` : '<p>This disk has no other menu games associated with it.</p>'}
      <label><input type="radio" name="slotAction-${Number(slot.slot)}" value="keep" checked> <span><strong>Keep disk in slot</strong><small>Remove only the menu record selected in the previous step.</small></span></label>
      <label><input type="radio" name="slotAction-${Number(slot.slot)}" value="eject"> <span><strong>Eject disk from slot ${Number(slot.slot)}</strong><small>${multiGame ? `Remove all ${related.length} menu records for this disk.` : "Remove its menu record and clear the slot."}</small></span></label>
    </fieldset>`;
  }).join("");
  showModal(`<div class="analysis-dialog wide-analysis duplicate-eject-review">
    <small>DUPLICATE CLEANUP · FINAL REVIEW</small><h2>Also eject the duplicate disks?</h2>
    <p>Keeping a disk continues with normal menu-only cleanup. Ejecting clears its MMB catalogue entry and 200 KiB disk data.</p>
    ${slotChoices || '<div class="help-note"><strong>No unambiguous slot match was found.</strong> Only the selected menu records will be removed.</div>'}
    <div class="help-warning"><strong>Your original file is unchanged until you save.</strong> One automatic undo checkpoint covers this complete cleanup.</div>
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button danger" value="apply">Apply cleanup</button></div>
  </div>`, async form => {
    const ejectSlots = candidateSlots
      .filter(slot => form.get(`slotAction-${Number(slot.slot)}`) === "eject")
      .map(slot => Number(slot.slot));
    const result = await paneOperation(index, "Cleaning duplicate MMB records…", () => api(`/api/images/${pane.image.id}/mmb-menu/duplicate-cleanup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        expectedEntries: installedEntries,
        removeIndexes: [...selectedIndexes],
        ejectSlots,
      }),
    }));
    pane.image = result.image;
    await acceptImage(index, pane.image);
    const removed = Number(result.removedRecords || selectedIndexes.size);
    toast(`${removed} menu ${removed === 1 ? "record" : "records"} removed${result.ejectedSlots?.length ? `; slots ${result.ejectedSlots.join(", ")} ejected` : "; disks kept in their slots"}.`);
  });
}

function showManifestExport(index) {
  const pane = panes[index];
  showModal(`<h2>Export collection manifest</h2><p>Create a searchable catalogue of slots, files, menu information, Acorn metadata and checksums.</p>
    ${pane.image.kind === "mmb" ? '<label class="button small">Apply reviewed JSON<input type="file" accept="application/json,.json" data-apply-manifest hidden></label>' : ""}
    <div class="modal-actions"><button class="button ghost" value="cancel">Cancel</button><button class="button" type="button" data-manifest="csv">Download CSV</button><button class="button primary" type="button" data-manifest="json">Download JSON</button></div>`);
  modalContent.querySelectorAll("[data-manifest]").forEach(button => button.onclick = () => {
    const link = document.createElement("a");
    link.href = `/api/images/${pane.image.id}/manifest?format=${button.dataset.manifest}`;
    link.target = "_blank";
    link.click();
    modal.close();
  });
  modalContent.querySelector("[data-apply-manifest]")?.addEventListener("change", async event => {
    try {
      const document = JSON.parse(await event.target.files[0].text());
      const data = await api(`/api/images/${pane.image.id}/manifest/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(document) });
      pane.image = data.image;
      await refreshCurrentView(index);
      modal.close();
      toast(`Applied ${data.entries || 0} reviewed menu entries`);
    } catch (error) { toast(error.message, true); }
  });
}

async function showJobsPanel() {
  showModal(`<div class="analysis-dialog"><small>PERSISTENT JOB HISTORY</small><h2>Operations</h2><div class="jobs-list"><p>Loading…</p></div><div class="modal-actions"><button class="button ghost" data-clear-jobs type="button">Clear finished</button><button class="button primary" value="cancel">Close</button></div></div>`);
  try {
    const data = await api("/api/operations");
    const list = modalContent.querySelector(".jobs-list");
    list.innerHTML = data.operations.map(job => `<article class="job ${esc(job.state)}"><b>${esc(job.state)}</b><span><strong>${esc(job.message)}</strong><small>${job.total != null ? `${job.current || 0} of ${job.total}` : "No item count"} · ${new Date(job.updatedAt * 1000).toLocaleString()}${job.details?.completed?.length ? ` · ${job.details.completed.length} completed` : ""}${job.details?.skipped?.length ? ` · ${job.details.skipped.length} skipped` : ""}</small></span>${job.state === "running" ? `<button type="button" data-cancel-job="${esc(job.id)}">Abort</button>` : job.details?.resumable ? `<button type="button" data-resume-job="${esc(job.id)}">Resume</button>` : ""}</article>`).join("") || "<p>No retained operations.</p>";
    list.querySelectorAll("[data-cancel-job]").forEach(button => button.onclick = async () => { await api(`/api/operations/${button.dataset.cancelJob}/cancel`, { method: "POST" }); showJobsPanel(); });
    list.querySelectorAll("[data-resume-job]").forEach(button => button.onclick = async () => {
      const job = data.operations.find(item => item.id === button.dataset.resumeJob);
      const details = job?.details;
      if (!details?.request?.items) return toast("This operation has no resumable item plan.", true);
      const done = new Set([...(details.completed || []), ...(details.skipped || [])].map(item => Number(item.sourceSlot)));
      const request = { ...details.request, items: details.request.items.filter(item => !done.has(Number(item.sourceSlot))), operationId: crypto.randomUUID() };
      if (!request.items.length) return toast("No pending items remain.");
      button.disabled = true;
      try {
        const result = await api(details.endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
        const targetPane = panes.findIndex(pane => pane.image?.id === request.targetImage);
        if (targetPane >= 0) { panes[targetPane].image = result.image; await refreshCurrentView(targetPane); }
        toast(`Resumed job completed ${result.completed?.length || 0} remaining items`);
      } catch (error) { toast(`Resume paused: ${error.message}`, true); }
      showJobsPanel();
    });
    modalContent.querySelector("[data-clear-jobs]").onclick = async () => { await api("/api/operations", { method: "DELETE" }); showJobsPanel(); };
  } catch (error) { toast(error.message, true); }
}

function projectDocument() {
  return {
    format: "acorn-file-forge-project",
    version: 1,
    created: new Date().toISOString(),
    panes: panes.map(pane => pane.image ? {
      imageId: pane.image.id, imageName: pane.image.name, kind: pane.image.kind,
      slot: pane.slot, side: pane.side, path: pane.path,
      hardwareProfile: pane.image.hardwareProfile || {},
    } : null),
    hardwareProfiles: storedCollection(PROFILE_STORAGE_KEY, BUILTIN_PROFILES),
    importRecipes: storedCollection(RECIPE_STORAGE_KEY, []),
  };
}

async function importProjectFile(file) {
  const project = JSON.parse(await file.text());
  if (project.format !== "acorn-file-forge-project" || !Array.isArray(project.panes)) throw new Error("This is not an Acorn File Forge project file.");
  saveCollection(PROFILE_STORAGE_KEY, project.hardwareProfiles || BUILTIN_PROFILES);
  saveCollection(RECIPE_STORAGE_KEY, project.importRecipes || []);
  const saved = project.panes.slice(0, MAX_PANES);
  localStorage.setItem(OPEN_PANES_STORAGE_KEY, JSON.stringify(saved.map(item => item ? { imageId: item.imageId, slot: item.slot, side: item.side, path: item.path } : null)));
  panes.splice(0, panes.length, ...Array.from({ length: Math.max(1, saved.length) }, () => newPaneState()));
  workspacePersistenceReady = false;
  await restoreOpenPanes();
  toast("Project workspace restored");
}

function renderWorkbench(section = "profiles") {
  const profiles = storedCollection(PROFILE_STORAGE_KEY, BUILTIN_PROFILES);
  const activeProfile = activeWorkbenchProfile(profiles);
  const recipes = storedCollection(RECIPE_STORAGE_KEY, []);
  const imageOptions = panes.map((pane, index) => pane.image ? `<option value="${index}">${esc(paneLabel(index))}</option>` : "").join("");
  showModal(`<div class="workbench-dialog"><header><div><small>ACORN FILE FORGE</small><h2>Workbench</h2></div><select name="workbenchSection"><option value="profiles" ${section === "profiles" ? "selected" : ""}>Hardware profiles</option><option value="recipes" ${section === "recipes" ? "selected" : ""}>Import recipes</option><option value="project" ${section === "project" ? "selected" : ""}>Portable project</option></select></header>
    ${section === "profiles" ? `<div class="workbench-grid"><aside>${profiles.map((profile, index) => `<button type="button" data-profile-index="${index}"><b>${esc(profile.name)}</b><small>${esc(profile.machine)} · ${esc(profile.filingSystem)}</small></button>`).join("")}</aside><section><div class="field"><label>Profile name</label><input name="profileName" value="${esc(profiles[0]?.name || "My Acorn setup")}"></div><div class="field"><label>Machine</label><input name="profileMachine" value="${esc(profiles[0]?.machine || "BBC Micro")}"></div><div class="field"><label>Filing system</label><input name="profileFs" value="${esc(profiles[0]?.filingSystem || "MMFS")}"></div><div class="field"><label>Target validation</label><select name="profileTarget"><option value="auto">Automatic</option><option value="electron-plus3">Electron Plus 3</option><option value="bbc-master">BBC / Master ADFS</option><option value="beebscsi">BeebSCSI</option><option value="risc-os">Archimedes / RISC OS</option></select></div><div class="field"><label>MMFS build</label><input name="profileMmfs" value="${esc(profiles[0]?.mmfsBuild || "paged")}"></div><div class="field"><label>Expected PAGE</label><input name="profilePage" value="${esc(profiles[0]?.page || "E00")}"></div><label class="check-field"><input type="checkbox" name="profileTube" ${profiles[0]?.tube ? "checked" : ""}> Tube enabled</label><div class="field"><label>Apply to open pane</label><select name="profilePane">${imageOptions || '<option value="">No open images</option>'}</select></div><div class="modal-actions"><button type="button" class="button" data-save-profile>Save profile</button><button type="button" class="button primary" data-apply-profile ${imageOptions ? "" : "disabled"}>Apply profile</button></div></section></div>` : section === "recipes" ? `<div class="workbench-grid"><aside>${recipes.map((recipe, index) => `<button type="button" data-recipe-index="${index}"><b>${esc(recipe.name)}</b><small>${esc(recipe.naming)} · ${recipe.addMenu ? "menu" : "off-menu"}</small></button>`).join("") || "<p>No saved recipes yet.</p>"}</aside><section><div class="field"><label>Recipe name</label><input name="recipeName" value="Collection import"></div><div class="field"><label>Directory naming</label><select name="recipeNaming"><option value="source">Use source titles</option><option value="generic">DISC-0000 sequence</option></select></div><div class="field"><label>Group prefix</label><input name="recipeGroup" maxlength="10" value="DISCS"></div><label class="check-field"><input type="checkbox" name="recipeOnline" checked> Use online metadata for ambiguous titles</label><label class="check-field"><input type="checkbox" name="recipeCompat" checked> Apply safe DFS to ADFS compatibility rewrites</label><label class="check-field"><input type="checkbox" name="recipeMenu" checked> Offer imported titles to a menu</label><div class="modal-actions"><button type="button" class="button primary" data-save-recipe>Save recipe</button></div></section></div>` : `<div class="project-tools"><p>A project description preserves the pane layout, working session references, current paths, profiles and recipes. Image bytes remain in their private recoverable sessions and normal timestamped save ZIPs. Theme remains a browser preference.</p><div class="modal-actions"><button type="button" class="button" data-export-project>Export project JSON</button><label class="button primary">Import project JSON<input type="file" accept="application/json,.json" data-import-project hidden></label></div></div>`}
    <div class="modal-actions"><button class="button ghost" value="cancel">Close workbench</button></div></div>`);
  if (section === "profiles") {
    modalContent.querySelector('[name="profileMachine"]')?.closest(".field")?.insertAdjacentHTML(
      "afterend",
      `<div class="field"><label>Online Library filter</label><select name="profileCatalogMachine">${ONLINE_MACHINES.map(([value, label]) => `<option value="${value}">${label}</option>`).join("")}</select></div>`
    );
  }
  modalContent.querySelector('[name="workbenchSection"]').onchange = event => renderWorkbench(event.target.value);
  if (section === "profiles") wireProfileWorkbench(profiles, activeProfile.index);
  if (section === "recipes") wireRecipeWorkbench(recipes);
  modalContent.querySelector("[data-export-project]")?.addEventListener("click", () => downloadDocument(`acorn-file-forge-${new Date().toISOString().replace(/[:.]/g, "-")}.aff-project.json`, JSON.stringify(projectDocument(), null, 2)));
  modalContent.querySelector("[data-import-project]")?.addEventListener("change", async event => { try { await importProjectFile(event.target.files[0]); modal.close(); } catch (error) { toast(error.message, true); } });
}

function wireProfileWorkbench(profiles, initialIndex = 0) {
  let selectedIndex = initialIndex;
  const fill = profile => {
    modalContent.querySelector('[name="profileName"]').value = profile.name || "";
    modalContent.querySelector('[name="profileMachine"]').value = profile.machine || "";
    modalContent.querySelector('[name="profileCatalogMachine"]').value = onlineMachineFromProfile(profile) || "all";
    modalContent.querySelector('[name="profileFs"]').value = profile.filingSystem || "";
    modalContent.querySelector('[name="profileTarget"]').value = profile.targetHardware || "auto";
    modalContent.querySelector('[name="profileMmfs"]').value = profile.mmfsBuild || "";
    modalContent.querySelector('[name="profilePage"]').value = profile.page || "";
    modalContent.querySelector('[name="profileTube"]').checked = Boolean(profile.tube);
  };
  const read = () => ({ name: modalContent.querySelector('[name="profileName"]').value.trim() || "My Acorn setup", machine: modalContent.querySelector('[name="profileMachine"]').value.trim(), catalogMachine: modalContent.querySelector('[name="profileCatalogMachine"]').value, filingSystem: modalContent.querySelector('[name="profileFs"]').value.trim(), targetHardware: modalContent.querySelector('[name="profileTarget"]').value, mmfsBuild: modalContent.querySelector('[name="profileMmfs"]').value.trim(), page: modalContent.querySelector('[name="profilePage"]').value.trim(), tube: modalContent.querySelector('[name="profileTube"]').checked, menuType: "universal" });
  modalContent.querySelectorAll("[data-profile-index]").forEach(button => button.onclick = () => {
    selectedIndex = Number(button.dataset.profileIndex);
    fill(profiles[selectedIndex]);
    setActiveWorkbenchProfile(selectedIndex, profiles[selectedIndex]);
  });
  modalContent.querySelector('[name="profileCatalogMachine"]').onchange = event => rememberOnlineMachine(event.target.value);
  modalContent.querySelector("[data-save-profile]").onclick = () => {
    profiles[selectedIndex] = read();
    setActiveWorkbenchProfile(selectedIndex, profiles[selectedIndex]);
    saveCollection(PROFILE_STORAGE_KEY, profiles);
    renderWorkbench("profiles");
    toast("Hardware profile saved");
  };
  modalContent.querySelector("[data-apply-profile]").onclick = async () => {
    const index = Number(modalContent.querySelector('[name="profilePane"]').value);
    const pane = panes[index]; const profile = read();
    const data = await api(`/api/images/${pane.image.id}/hardware-profile`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile) });
    setActiveWorkbenchProfile(selectedIndex, profile);
    pane.image = data.image; renderPane(index); modal.close();
    toast(`${profile.name} applied to ${pane.image.name}${profile.tube ? " · Tube compatibility warnings enabled" : ""}`);
  };
  if (profiles[selectedIndex]) {
    fill(profiles[selectedIndex]);
    setActiveWorkbenchProfile(selectedIndex, profiles[selectedIndex]);
  }
}

function wireRecipeWorkbench(recipes) {
  let selectedIndex = recipes.length;
  const fill = recipe => {
    modalContent.querySelector('[name="recipeName"]').value = recipe.name || "";
    modalContent.querySelector('[name="recipeNaming"]').value = recipe.naming || "source";
    modalContent.querySelector('[name="recipeGroup"]').value = recipe.groupPrefix || "DISCS";
    modalContent.querySelector('[name="recipeOnline"]').checked = recipe.online !== false;
    modalContent.querySelector('[name="recipeCompat"]').checked = recipe.compatibility !== false;
    modalContent.querySelector('[name="recipeMenu"]').checked = recipe.addMenu !== false;
  };
  modalContent.querySelectorAll("[data-recipe-index]").forEach(button => button.onclick = () => { selectedIndex = Number(button.dataset.recipeIndex); fill(recipes[selectedIndex]); });
  modalContent.querySelector("[data-save-recipe]").onclick = () => {
    const recipe = { name: modalContent.querySelector('[name="recipeName"]').value.trim() || "Collection import", naming: modalContent.querySelector('[name="recipeNaming"]').value, groupPrefix: modalContent.querySelector('[name="recipeGroup"]').value.trim() || "DISCS", online: modalContent.querySelector('[name="recipeOnline"]').checked, compatibility: modalContent.querySelector('[name="recipeCompat"]').checked, addMenu: modalContent.querySelector('[name="recipeMenu"]').checked };
    recipes[selectedIndex] = recipe; saveCollection(RECIPE_STORAGE_KEY, recipes); renderWorkbench("recipes"); toast("Import recipe saved");
  };
}

const storedTheme = localStorage.getItem("acorn-file-forge-theme");
const initialTheme = storedTheme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
document.documentElement.dataset.theme = initialTheme;
const themeToggle = document.querySelector("#themeToggle");
document.querySelector("#addPaneButton").onclick = addPane;
document.querySelector("#helpButton").onclick = showHelp;
document.querySelector("#workbenchButton").onclick = () => renderWorkbench();
document.querySelector("#jobsButton").onclick = showJobsPanel;
document.addEventListener("keydown", event => {
  const editing = event.target.closest("input, textarea, select, [contenteditable=true]");
  if (editing || modal.open) return;
  if (event.key === "Escape" && workspaceClipboard) {
    event.preventDefault();
    clearWorkspaceClipboard("Clipboard cancelled.");
    return;
  }
  if (!(event.ctrlKey || event.metaKey)) return;
  const paneHost = event.target.closest(".pane[data-pane]");
  if (!paneHost) return;
  const index = Number(paneHost.dataset.pane);
  const key = event.key.toLowerCase();
  if (key === "c" || key === "x") {
    event.preventDefault();
    setWorkspaceClipboard(index, key === "x" ? "cut" : "copy");
  } else if (key === "v" && workspaceClipboard) {
    event.preventDefault();
    pasteWorkspaceClipboard(index);
  }
});
async function refreshJobsBadge() {
  try {
    const data = await api("/api/operations");
    const active = data.operations.filter(item => ["running", "cancelling", "paused", "failed", "interrupted"].includes(item.state)).length;
    const badge = document.querySelector("#jobsBadge");
    badge.hidden = active === 0;
    badge.textContent = String(active);
  } catch (_error) { /* The app remains usable if job history is unavailable. */ }
}
refreshJobsBadge();
setInterval(refreshJobsBadge, 3000);
function updateThemeButton() {
  const dark = document.documentElement.dataset.theme === "dark";
  themeToggle.querySelector("b").textContent = dark ? "Light" : "Dark";
  themeToggle.setAttribute("aria-label", `Switch to ${dark ? "light" : "dark"} mode`);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#0b0e0c" : "#c9ba9b");
}
themeToggle.onclick = () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("acorn-file-forge-theme", next);
  updateThemeButton();
};
updateThemeButton();
updateAddPaneButton();

restoreOpenPanes();
