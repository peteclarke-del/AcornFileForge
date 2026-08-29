(() => {
  "use strict";

  function create({ showModal, esc, context }) {
    return function showAbout() {
      const details = context();
      const host = details.host === "desktop" ? "Linux desktop application" : "Web application";
      showModal(`<div class="about-dialog">
        <header class="about-heading">
          <img src="/favicon.svg" alt="">
          <div><small>ACORN FILE IMAGE WORKSHOP</small><h2>Acorn File Forge</h2><p>Version ${esc(details.version)}</p></div>
        </header>
        <p>Create, inspect, edit, convert, validate and deploy Acorn media images from one shared workbench.</p>
        <dl class="about-facts">
          <dt>Edition</dt><dd>${esc(host)}</dd>
          <dt>Filesystem engine</dt><dd>${esc(details.engine)}</dd>
          <dt>Formats</dt><dd>DFS SSD/DSD, HFE, SCP, MMB, ADFS and FileCore, BeebSCSI DAT/DSC, HDF/RAW, UEF, ROM and ROMFS</dd>
          <dt>Platforms</dt><dd>BBC Micro and Master, Acorn Electron, Archimedes and RISC OS</dd>
          <dt>Licence</dt><dd>MIT License · Copyright © 2026 Pete Clarke</dd>
        </dl>
        <nav class="about-links" aria-label="Project links">
          <a class="button small" href="https://github.com/peteclarke-del/AcornFileForge" target="_blank" rel="noopener noreferrer">Source and support</a>
          <a class="button small" href="https://github.com/peteclarke-del/AcornFileForge/releases" target="_blank" rel="noopener noreferrer">Release downloads</a>
          <a class="button small" href="https://github.com/peteclarke-del/AcornFileForge/blob/main/THIRD_PARTY_NOTICES.md" target="_blank" rel="noopener noreferrer">Third-party notices</a>
        </nav>
        <div class="modal-actions"><button class="button primary" value="cancel">Close</button></div>
      </div>`);
    };
  }

  window.AcornAbout = Object.freeze({ create });
})();
