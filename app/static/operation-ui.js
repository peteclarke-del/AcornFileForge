window.AcornOperationUI = (() => {
  function create({ panes, api, setLoading, renderPane, modal, setModalAbort, setModalProgress }) {
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
              { label: "Completed work", value: "Previously completed batch items will be preserved" },
            ],
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
                  { label: "Completed work", value: "Previously completed batch items will be preserved" },
                ],
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
                details: progress.total != null ? [{
                  label: "Progress",
                  value: `${Math.round(100 * Number(progress.current || 0) / Number(progress.total || 1))}% complete`,
                }] : [],
              }, progress.current, progress.total);
            }
            renderPane(index);
          }
        } catch (_error) {
          // The first poll can arrive before the POST registers the operation.
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
          await new Promise(resolve => modal.addEventListener("close", resolve, { once: true }));
        }
      } finally {
        if (panes[index] === pane) {
          pane.actionPending = false;
          renderPane(index);
        }
      }
    }

    return { guardedPaneAction, trackedPaneOperation };
  }

  return { create };
})();
