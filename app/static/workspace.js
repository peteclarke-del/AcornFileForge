window.AcornWorkspace = (() => {
  function newPaneState(image = null) {
    return {
      image,
      slot: null,
      side: image?.doubleSided ? 0 : null,
      slotName: "",
      path: "$",
      archivePath: null,
      archiveName: "",
      archiveMember: "",
      archiveKind: "",
      entries: [],
      capacity: null,
      selected: null,
      selection: [],
      selectionAnchor: null,
      loading: Boolean(image),
      requestToken: 0,
      menuDetected: false,
      fileKinds: {},
      menuDetectionPending: Boolean(image?.kind === "mmb")
    };
  }

  const isDfsPane = pane => (
    pane?.image?.kind === "dfs"
    || (pane?.image?.kind === "mmb" && pane.slot !== null)
  );

  function restoredDfsPath(saved) {
    return typeof saved?.path !== "string" || saved.path === "" ? "$" : saved.path;
  }

  function normalisePage(value) {
    const cleaned = String(value || "").trim().replace(/^&/, "").toUpperCase();
    return cleaned.replace(/^0+(?=[0-9A-F])/, "") || "0";
  }

  function fullPath(directory, name) {
    if (directory === "") return name;
    return directory === "$" ? `$.${name}` : `${directory}.${name}`;
  }

  function parentPath(path) {
    if (path === "" || path === "$") return path;
    const parts = path.split(".");
    parts.pop();
    return parts.join(".") || "";
  }

  function selectionKeys(pane) {
    if (Array.isArray(pane.selection) && pane.selection.length) {
      return pane.selection.map(String);
    }
    return pane.selected == null ? [] : [String(pane.selected)];
  }

  function setSelection(pane, keys, anchor = null) {
    pane.selection = [...new Set(keys.map(String))];
    pane.selected = pane.selection.length === 1 ? pane.selection[0] : null;
    pane.selectionAnchor = anchor ?? pane.selection.at(-1) ?? null;
  }

  const entrySelectionKey = entry => String(entry.slot ?? entry.path ?? entry.name);
  const pathNameWithoutExtension = value => String(value || "").replace(/\.[^.]+$/, "");

  return {
    entrySelectionKey,
    fullPath,
    isDfsPane,
    newPaneState,
    normalisePage,
    parentPath,
    pathNameWithoutExtension,
    restoredDfsPath,
    selectionKeys,
    setSelection,
  };
})();
