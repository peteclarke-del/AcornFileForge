(() => {
  "use strict";
  function create({ showModal, modalContent }) {
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
          <a href="#help-rom">ROM images</a>
          <a href="#help-romfs">ROMFS data ROMs</a>
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
            <div class="help-note"><strong>Start small:</strong> a new workspace opens with one full-workspace pane. Select <strong>Add Pane</strong> whenever you need another source, destination or scratch image. There is no fixed pane-count limit, and extra panes open as cascading windows.</div>
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
                <li>Select <strong>Open image</strong>, or drag a disk, tape or ROM image from your computer onto the empty pane.</li>
                <li>Choose the image. Supported families include SSD, DSD, HFE, MMB, ADFS floppy and hard-drive images, DAT/DSC, HDF, HDD, IMG, RAW, BIN and UEF. ZIP distributions can contain one supported image or a matched DAT/DSC pair.</li>
                <li>Wait for the opening indicator. The catalogue or MMB slot index appears when identification is complete.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Create a new image</h4>
              <ol>
                <li>Open <strong>File → New → New Image (current format)</strong>. The current pane format is preselected.</li>
                <li>An existing empty pane is used first. If every pane contains an image, another workspace window is added automatically. Existing work is not replaced.</li>
                <li>Choose DFS SSD or DSD, an HFE-wrapped DFS/ADFS floppy, ADFS S/M/L/D/E/E+/F/F+/G/G+ floppy, BeebSCSI DAT/DSC hard drive, HDF virtual HDD, RAW physical-drive image, or an MMB bank.</li>
                <li>Enter a disk title. For DAT, HDF and RAW images, enter a capacity such as <code>20MB</code> or <code>512MB</code>.</li>
                <li>The size field is read-only for fixed SSD, DSD, ADFS floppy, HFE and MMB formats. It becomes editable for BeebSCSI, HDF and RAW hard drives and remembers the last HDD capacity you entered.</li>
                <li>The target is disabled when it does not apply, fixed to BeebSCSI for DAT/DSC, and fixed to Archimedes / RISC OS for HDF or RAW. Normal ADFS S/M/L floppies retain a target choice because their geometry can be used by several Acorn systems.</li>
                <li>MMB has no bank-wide disk title, so that field is disabled. Titles belong to the individual disks you create or insert in its slots.</li>
                <li>Select <strong>Create image</strong>. The formatted image opens immediately as an editable working copy.</li>
                <li>Add content, then use the <strong>Save Image</strong> button in the pane heading to download it.</li>
              </ol>
            </div>
            <div class="help-note"><strong>Pane heading actions:</strong> after the orange changed indicator, the buttons create a New Blank Image, Load New Image, Save Image, Refresh View, Minimise, Maximise or restore, and Close Pane. The × close button offers Save and close, Close without saving, or Cancel whenever the image has changes.</div>
            <h4>Which new format should I choose?</h4>
            <div class="help-table-wrap"><table class="help-table"><caption class="visually-hidden">Supported image formats and their main limits</caption>
              <thead><tr><th>Format</th><th>Best used for</th><th>Important limit</th></tr></thead>
              <tbody>
                <tr><td>SSD</td><td>One BBC DFS disk side</td><td>200 KiB, 31 catalogue files</td></tr>
                <tr><td>DSD</td><td>Two-sided BBC DFS disk</td><td>Two independent 200 KiB sides</td></tr>
                <tr><td>HFE</td><td>HxC, Gotek and flux-style floppy workflows</td><td>Advanced/protected layouts open read-only</td></tr>
                <tr><td>ADFS S/M/L</td><td>BBC Master or compact hierarchical media</td><td>Old-format directory and capacity limits</td></tr>
                <tr><td>ADFS D/E/F/G</td><td>Arthur, Archimedes and RISC OS FileCore floppies</td><td>77 entries and 10-character names per directory</td></tr>
                <tr><td>ADFS E+/F+/G+</td><td>RISC OS media with Big directories</td><td>Names up to 255 characters; entry count is capacity-dependent</td></tr>
                <tr><td>DAT + DSC</td><td>BeebSCSI ADFS hard drives</td><td>Downloads as a ZIP containing the required pair</td></tr>
                <tr><td>HDF / RAW</td><td>Archimedes, RISC OS or emulated hard drives</td><td>Choose enough capacity before creating</td></tr>
                <tr><td>MMB</td><td>A library of BBC DFS disks</td><td>511 SSD-sized physical slots</td></tr>
                <tr><td>ROM</td><td>Raw code, banked firmware and physical chip sets</td><td>Bytes are not assumed to be files</td></tr>
                <tr><td>ROMFS</td><td>BBC/Master/Electron files in a data ROM</td><td>Flat, case-sensitive, 10-character names; 8 or 16 KiB</td></tr>
              </tbody>
            </table></div>
          </section>
          <section id="help-workspace">
            <h3>Workspace, navigation and selection</h3>
            <figure><img src="/help/workspace.png" alt="Acorn File Forge showing movable image panes and the Add Pane control"><figcaption>The workspace begins with one pane. Add and arrange as many movable image windows as the computer can comfortably display; each retains independent navigation, selection, refresh, progress and save controls.</figcaption></figure>
            <h4>Add, arrange and close panes</h4>
            <ol>
              <li>Select <strong>Add Pane</strong> in the header to add an empty cascading window. There is no fixed pane-count limit.</li>
              <li>Drag an empty part of a pane heading, or use the numbered grip at its left, to move it. Windows may overlap, and selecting any part of a window brings it to the front.</li>
              <li>Drag a pane to the left or right edge to fill that half, to a corner to fill that quarter, or to the top edge to maximise it. The translucent preview shows the result before release.</li>
              <li>Drag any pane edge or corner to resize it. The lower-right corner has a visible resize mark. Double-click the numbered grip or use the square heading button to maximise or restore it.</li>
              <li>Select the line button to minimise a pane to the shelf at the bottom of the workspace. Select its shelf button to restore and focus it.</li>
              <li>With the numbered grip focused, use Alt+Left or Alt+Right to snap, Alt+Up to maximise, and Alt+Down to minimise without a pointer. Hold Shift as well to resize in 32-pixel steps.</li>
              <li>An empty pane is a convenient scratch area for creating an SSD, DSD, MMB, ADFS floppy, BeebSCSI DAT/DSC pair or other supported image.</li>
              <li>Select × at the top-right to close that whole pane. Save changed images from the prompt, deliberately close without saving a download, or cancel. The server working copy remains available through Recovery.</li>
              <li>Open images, positions, sizes, snap layout, stacking order and minimised windows are remembered across a normal page refresh. A completely fresh workspace starts with one pane.</li>
            </ol>
            <div class="help-note"><strong>Two different drag operations:</strong> drag a heading or its numbered grip to move or snap the window. Drag file rows, MMB slots, or the coloured format badge on a supported disk image to transfer content between images.</div>
            <div class="help-note"><strong>Familiar pane menus:</strong> File and Edit are always first, followed by View, Library, the format-specific Menu when available, Analyse and Tools. File holds open, save, add and create commands. Edit holds Cut, Copy, Paste, Undo and Checkpoints. View holds refresh, DSD side switching and return-to-MMB commands. The heading icons remain quick shortcuts for common image actions.</div>
            <div class="help-note"><strong>Free-space meter:</strong> the lower-right bar uses the image filesystem's real allocation data. Green means under 70% used, orange means 70% or more, and red means 90% or more. Hover over it for used, free and total values. An MMB root counts disk slots; opening one of its disks switches the meter to that slot's DFS bytes. UEF tapes have no fixed free-space capacity and show a neutral striped meter.</div>
            <h4>Navigate an image</h4>
            <ol>
              <li>Double-click a directory to enter it. Double-click a file to open the BASIC, script, text, disassembly or hex editor selected from its contents.</li>
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
                <li>Open <strong>File → Insert File</strong> and choose one or more files.</li>
                <li>For each file, review the target name, load address, execute address and, on ADFS, its RISC OS filetype.</li>
                <li>If a name is illegal for the target filing system, accept the safe suggestion or type a valid replacement.</li>
                <li>Select <strong>Insert File</strong> in the dialog. Each successful insertion appears in the current view.</li>
                <li>For a multiple selection, choose <strong>Insert and apply to all remaining</strong> to accept each later file's own detected name and metadata without reopening the same review.</li>
              </ol>
              <p>Files copied from SSD, DSD, ADFS, HFE or MMB retain their catalogue load/execute addresses and other supported metadata. For loose host files, select their companion <code>.inf</code> sidecars too, or use a conventional <code>name,load-exec</code> filename. Raw host bytes alone do not contain a trustworthy address.</p>
            </div>
            <div class="help-task">
              <h4>Inspect or change load and execution addresses</h4>
              <figure><img src="/help/catalogue-addresses.png" alt="DFS file catalogue with separate Load and Execute columns"><figcaption>Every file-level catalogue presents the stored words explicitly. The values are metadata from the image, not guesses made from the file bytes.</figcaption></figure>
              <ol>
                <li>At file level, read the separate <strong>Load</strong> and <strong>Execute</strong> columns. Each value is the complete eight-digit catalogue word. DFS sign extension is shown conventionally, for example <code>&amp;FFFF1900</code>.</li>
                <li>On writable DFS, MMB disk, ADFS or ROMFS media, select either address value. Both words are reviewed together so they cannot be changed accidentally in separate operations.</li>
                <li>Enter one to eight hexadecimal digits, with an optional <code>&amp;</code> or <code>0x</code> prefix, then read the safety warning.</li>
                <li>Select <strong>I understand, change addresses</strong> only when the values came from the original catalogue, a trusted <code>.inf</code> sidecar or reliable documentation. The app changes the catalogue record without rewriting the file bytes.</li>
              </ol>
              <div class="help-warning"><strong>Incorrect addresses can stop software loading or corrupt memory.</strong> On RISC OS-style FileCore entries, the same words can encode filetype and timestamp data. The dialog identifies that case before accepting the change.</div>
              <figure><img src="/help/catalogue-address-edit-warning.png" alt="Guarded dialog for changing the load and execution words"><figcaption>The address editor changes both words together and requires explicit acceptance of the risk.</figcaption></figure>
              <p>A value of <code>&amp;00000000</code> is not automatically an error. Data, command files and BASIC programs loaded by filing-system-aware commands can legitimately carry zero words. Acorn File Forge preserves what the source catalogue or sidecar says and does not invent a machine-code entry address from file content.</p>
            </div>
            <div class="help-task">
              <h4>Import one or more host folders</h4>
              <ol>
                <li>Navigate to the destination and choose <strong>File → Insert Folder &amp; Contents</strong>, or drag folders from the desktop onto the pane. Use drag and drop to select several top-level folders when your browser supports it.</li>
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
                <li>Choose <strong>File → New → New folder</strong>, enter a legal name and select <strong>Create folder</strong>.</li>
                <li>Double-click the new directory to enter it, then add or drag content into it.</li>
              </ol>
              <p>ADFS directories are real hierarchical objects. DFS uses the separate catalogue-group workflow below.</p>
            </div>
            <div class="help-task">
              <h4>Use DFS catalogue groups</h4>
              <ol>
                <li>An SSD, DSD side or open MMB disk starts directly on <strong>$</strong>. Default-catalogue files appear first.</li>
                <li>After a visual gap, populated A-Z groups appear below as complete DFS names such as <strong>R.GAME</strong>. Each prefix stays grouped like a catalogue listing, but it is still part of the same flat DFS catalogue.</li>
                <li>Choose <strong>File → New catalogue group</strong> to choose another one-character prefix and then choose its first file.</li>
                <li>An empty group cannot be saved because DFS stores the prefix on each file, not as a separate directory entry.</li>
                <li>Files from every displayed prefix can be opened, downloaded, renamed, protected, copied or deleted without changing views.</li>
                <li>At an MMB disk's catalogue root, double-click <strong>..</strong> to return to <strong>All disks</strong>.</li>
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
                <li>Use the download arrow beside an ordinary file to download a ZIP containing the loose file and its matching <code>.inf</code> metadata sidecar without changing the image. The sidecar retains the real catalogue path, load address, execution address, length and lock state. UEF members and archive members with valid SparkFS or companion <code>.inf</code> metadata use the same bundle. Double-click opens the appropriate editor.</li>
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
                <li>The pane opens on <strong>$</strong>. Files from populated A-Z prefixes are grouped underneath with complete names such as <strong>R.GAME</strong>. Use <strong>File → New catalogue group</strong> when the first file will introduce a new prefix.</li>
                <li>Use <strong>File → Insert File</strong>, or drag selected files from another pane or onto a catalogue row.</li>
                <li>Review shortened names and Acorn load/execute addresses before confirming each import.</li>
                <li>Use the row actions to rename or delete. Use the Access column to mark one or several files read/write or read-only.</li>
                <li>Use <strong>Tools → Check filesystem</strong>, optionally compact it, then select <strong>Save Image</strong> in the pane heading.</li>
              </ol>
            </div>
            <h4>DFS rules enforced by the app</h4>
            <ul>
              <li>A leaf name is at most seven characters and its DFS directory prefix is one character.</li>
              <li><strong>$</strong> is the default view. Populated A-Z prefixes are grouped below its files, not represented as nested directories.</li>
              <li>A blank disk still opens at <strong>$</strong>. Other prefixes appear when populated and disappear when their last file is removed.</li>
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
              <li>Open an HFE normally, or create an HFE-wrapped DFS/ADFS floppy from <strong>File → New → New Image</strong>.</li>
              <li>Check the opening warning. A clean HFE v1 disk is editable through the usual file tools.</li>
              <li>HFE v2/v3, weak-bit, bad-sector, protected or advanced timing images open as a clearly labelled read-only safe view. Export or drag files from them without changing their tracks.</li>
              <li>For an editable HFE, make the required changes and select <strong>Save Image</strong> in the pane heading.</li>
              <li>The app writes changed sectors into a copy of the original track layout, decodes that result, and compares every sector with the working filesystem. A mismatch blocks the download and leaves the original HFE intact.</li>
            </ol>
            <div class="help-note"><strong>What the pane shows:</strong> the format badge reads HFE, while the directory rules, sides and capacity come from its decoded DFS or ADFS filesystem. Advanced images show <strong>Read-only safe view</strong> and hide editing, compaction and menu-writing controls.</div>
            <div class="help-note"><strong>MMB and ADFS transfers:</strong> a DFS-formatted HFE may be inserted into an MMB. Any supported HFE filesystem can be opened in one pane and copied or extracted into another image. MMB stores only DFS sectors, so timing, weak-bit and protection information from an advanced HFE is deliberately omitted and reported as a destination warning.</div>
          </section>
          <section id="help-rom">
            <h3>ROM images: banks, headers and chip sets</h3>
            <p class="help-lead">A ROM is a byte image rather than a filing system. The pane divides it into explicit banks without changing the saved bytes.</p>
            <figure><img src="/help/rom-pane.png" alt="ROM pane showing bank address, decoded identity, purpose, entry points and programmed utilisation"><figcaption>The main pane is a bank inventory, not a directory. At narrow pane widths each bank becomes a readable two-column card while retaining the same decoded fields.</figcaption></figure>
            <div class="help-note"><strong>Terms used in the pane:</strong> <em>Bank</em> is the zero-based logical block selected by the configured bank size. <em>File address</em> is its byte offset in the complete image. <em>Mapped address</em> is the conventional CPU window for the selected target. <em>Programmed</em> means bytes that differ from the configured erased value; it is not filesystem free space.</div>
            <div class="help-task"><h4>Open and inspect a ROM</h4><ol>
              <li>Open a <code>.rom</code>, numbered <code>.rom0</code> to <code>.rom7</code>, or a <code>.bin</code> carrying a recognised sideways-ROM header. For a headerless or generically named dump, choose the Acorn ROM raw-format override in the open dialog.</li>
              <li>The default view uses 16 KiB banks. Choose <strong>Tools → ROM layout</strong> if the device uses 8K, 32K or another 256-byte-aligned bank size.</li>
              <li>Read the bank inventory from left to right: bank and image address, decoded identity, purpose and entry points, then programmed contents. A BBC-family bank also shows its mapped CPU window. Empty and unrecognised banks are labelled plainly.</li>
              <li>The guidance strip above the inventory explains the shortcuts. Select ⓘ for decoded information, double-click for Hex, or open <strong>Tools → ROM Workbench</strong> for disassembly, comparison and hardware preparation.</li>
              <li>Image Health recognises BBC-family headers and the standard RISC OS <code>ExtnROM0</code> trailer. A bad RISC OS extension-ROM checksum is reported as a failure.</li>
              <li>Select ⓘ on a bank to open its decoded-content view. It shows header fields, processor type, declared feature bits, mapped entry points, known regions and bounded printable strings with their byte offsets and mapped addresses.</li>
              <li>Use <strong>Provided star commands</strong> in that view to see commands such as <code>*MENU</code>. RISC OS module command tables are decoded as declared commands, including parameter limits and configuration keywords.</li>
              <li>A <strong>?</strong> beside a command provides its available <code>*HELP</code> information. Point at it, focus it from the keyboard, or select it to keep the tooltip open. The source label distinguishes declared RISC OS help, reconstructed BBC command syntax and literal lines recovered from a shared BBC help topic. Press <kbd>Escape</kbd> to close pinned help.</li>
              <li>BBC, Master and Electron sideways ROMs do not have one standard command catalogue. The app recognises coherent token-dispatch and address-dispatch MOS keyword tables. Address tables must also have an indexed 6502 code reference and valid handlers inside the sideways-ROM window.</li>
              <li>Printable <code>*Command</code> text alone is not included because help text, examples and even machine code can resemble a command. Address-dispatch results provide separate Table and Handler buttons. Token tables link to their table entry. These links open a hex editor inside the decoded-information dialog; closing it reveals the same information at its previous scroll position. Hex editing opened from a pane menu stays inside that pane.</li>
              <li>If no command is shown, the ROM may still provide commands through dynamic matching, abbreviations or a table form the static scanner does not recognise. Try the ROM's <code>*HELP</code> output on suitable hardware or inspect its service entry in the hex editor.</li>
              <li>Printable strings can also reveal messages and build information, but are labelled as evidence rather than guessed files. Every decoded location and command has a direct Hex button.</li>
              <li>The decoder also reports SHA-256, CRC-32, entropy, distinct byte values, erased space, used range, programming offsets and identical banks. Header flags are checked against the actual entry vectors.</li>
              <li>For an Archimedes target, plausible RISC OS module headers expose titles, help text, entry facilities and SWI information. They remain labelled as candidates unless the enclosing ROM structure proves them.</li>
              <li>A recognised BBC, Master or Electron header shows its title, version and language/service roles. RISC OS extension images show their <code>ExtnROM0</code> size and checksum trailer. Unknown custom data remains honestly labelled as raw code and data.</li>
              <li>Double-click a bank to open the hex editor at that bank's first byte. Use the image health dashboard to report partial banks and recognised headers.</li>
            </ol></div>
            <figure><img src="/help/rom-decoder.png" alt="Decoded BBC-family ROM header, fingerprints and star-command table"><figcaption>The decoder separates proven header fields, byte statistics and structured command evidence. It opens with focus on the heading, not on the first command; Tab moves into the controls.</figcaption></figure>
            <figure><img src="/help/rom-command-help.png" alt="A pinned tooltip showing command syntax reconstructed from a ROM table"><figcaption>Command help states its source. Hover or keyboard focus shows it temporarily; select the question mark to pin it while reading.</figcaption></figure>
            <div class="help-note"><strong>Decoder boundaries:</strong> entropy, strings and command candidates are evidence, not a claim that code is safe or that strings are files. A missing command may be constructed dynamically. A plausible RISC OS module remains a candidate until its enclosing structure proves it.</div>
            <div class="help-task"><h4>Create and edit a banked image</h4><ol>
              <li>Choose <strong>File → New → New Image (ROM)</strong>. Set the total byte size, logical bank size, target family, erased byte and layout.</li>
              <li>Choose erased bytes for a blank device, or the inert BBC-family language and service header skeleton for custom sideways-ROM development.</li>
              <li>Use <strong>File → Insert ROM bank(s)</strong> for one or several files. Exact-multiple combined images are split into consecutive banks; anything requiring silent truncation is refused.</li>
              <li>Rename edits a recognised header title. Erase fills selected banks with <code>&FF</code> or <code>&00</code> without shrinking the image. Append empty bank grows the image by exactly one configured bank.</li>
              <li>Use Cut, Copy, Paste or drag between ROM panes. Dragging inside one ROM is an atomic move and overlapping ranges are safe.</li>
            </ol></div>
            <div class="help-task"><h4>Open physical chip sets</h4><ol>
              <li>Select two or four equal-sized ROM component files together.</li>
              <li>Choose concatenate for consecutive banks, or byte interleave for byte-wide chips. Keep the displayed file order correct for the physical sockets.</li>
              <li>Four-way byte interleaving covers the usual Archimedes/RISC OS ROM arrangement. The working pane shows logical byte order.</li>
              <li>The save ZIP keeps the logical image and reconstructs the individual component files under <code>ROM-components</code>. Its README records the original component names and order.</li>
            </ol></div>
            <div class="help-task"><h4>Analyse and compare ROM code</h4><ol>
              <li>Choose <strong>Tools → ROM Workbench</strong>. Overview shows every bank, its file offset, decoded identity, physical byte lanes and duplicate banks.</li>
              <li>Review the audit findings. The app can safely align contradictory sideways-ROM role flags with proven entry vectors and rebuild a standard RISC OS extension-ROM checksum. An automatic undo point is made first.</li>
              <li>Open <strong>Disassembly</strong>, choose a bank, architecture, mapped origin and offset. Auto detect chooses ARM for an Archimedes target and follows a recognised BBC-family processor header elsewhere.</li>
              <li>NMOS 6502, 65C02, 65816, ARM and 68000 instructions use their correct byte order. Unknown NMOS 6502 opcodes remain visible as <code>EQUB</code> data. Known entry points seed reachable-code analysis, call and branch targets gain cross-references, and BBC MOS jump-table calls are labelled.</li>
              <li>Save address labels under <strong>Project</strong> using <code>address = label</code>. Known regions use <code>start-end = meaning</code>. Disassemble again to apply them to the listing.</li>
              <li>To compare revisions, open the other ROM in another pane and select it under <strong>Compare</strong>. Download the guarded patch when required.</li>
              <li>Tick individual comparison ranges to export only reviewed changes. A patch is applied only when the complete source SHA-256 matches. The finished bytes must then match the stored target SHA-256 or the operation fails.</li>
              <li>Use <strong>Identify this exact ROM</strong> on Overview to add a private title, version, publisher and platform record. It is keyed by SHA-256 and scoped to the current browser owner.</li>
            </ol></div>
            <figure><img src="/help/rom-workbench-overview.png" alt="ROM Workbench Overview showing bank map, exact identity and audit findings"><figcaption>Overview relates logical banks to file offsets, decoded type and duplicates. Repairs appear only when the fault and replacement value are deterministic.</figcaption></figure>
            <figure><img src="/help/rom-workbench-disassembly.png" alt="ROM Workbench Disassembly showing architecture controls, decoded instructions, reachability and references"><figcaption>Disassembly is bounded static analysis. Select architecture, mapped origin, bank offset and byte count; saved project symbols and regions annotate later listings.</figcaption></figure>
            <div class="help-note"><strong>Workbench safety model:</strong> Overview, Disassembly and Compare are read-only. Identity, Project and Emulator store separate project metadata. Repair, patch application and Build change ROM bytes only after review and an automatic checkpoint. Programmer transforms affect only its downloaded ZIP.</div>
            <div class="help-task"><h4>Build and prepare ROMs</h4><ol>
              <li>Under <strong>Build</strong>, choose a service-ROM scaffold or AFFROMFS data archive, then review the replacement warning.</li>
              <li>The service-ROM scaffold has an inert handler. It is a development starting point and does not pretend that named commands already have implementations.</li>
              <li>AFFROMFS packages named bytes for companion service code. An unmodified MOS cannot mount it as a filing system.</li>
              <li>Under <strong>Programmer</strong>, choose the physical device size, one, two or four byte lanes, and any required mirroring, adjacent-byte swapping, 16-bit word swapping or address-line swaps.</li>
              <li>Keep the generated programming report with the chip files and verify its checksum against a programmer read-back.</li>
              <li>The saved image ZIP includes <code>ROM-project.json</code> with notes, symbols and emulator results. These annotations never alter the ROM bytes.</li>
            </ol></div>
            <figure><img src="/help/rom-workbench-programmer.png" alt="ROM Workbench Programmer tab configured to mirror and split a ROM into two byte-wide chips"><figcaption>Programmer export applies padding or mirroring, byte and word transforms, address-line swaps, then physical lane splitting. Its report records checksums for programmer read-back.</figcaption></figure>
            <div class="help-task"><h4>Understand each Workbench tab</h4><ul>
              <li><strong>Overview:</strong> bank map, byte lanes, exact SHA-256 identity, audit and narrowly proven repairs.</li>
              <li><strong>Disassembly:</strong> NMOS 6502, 65C02, 65816, ARM or 68000 decoding with reachable-code analysis, cross-references, MOS call labels and project annotations.</li>
              <li><strong>Compare:</strong> contiguous revision differences and complete or selective patches guarded by source and target SHA-256.</li>
              <li><strong>Build:</strong> an inert BBC service-ROM scaffold or an <code>AFFROMFS1</code> data archive for companion code. Neither is a finished application by itself.</li>
              <li><strong>Programmer:</strong> device padding or mirroring, adjacent-byte swaps, 16-bit word swaps, address-line swaps and one, two or four physical byte lanes.</li>
              <li><strong>Project:</strong> hardware notes, research, address labels and known regions stored outside the ROM bytes.</li>
              <li><strong>Emulator:</strong> the managed emulator selected by the applied hardware profile. Direct ROM attachment is enabled only when the target machine's slot mapping is safe.</li>
            </ul></div>
            <div class="help-task"><h4>Run a configured emulator check</h4><ol>
              <li>Choose a machine and emulator in <strong>Workbench → Hardware profiles</strong>, then apply it to the ROM pane.</li>
              <li>Open <strong>ROM Workbench → Emulator</strong>. The panel identifies the managed tool and whether this machine has a proven sideways-ROM slot mapping.</li>
              <li>If direct attachment is disabled, use Programmer export or place the ROM in a machine-specific image. The app does not guess a bank or replace a system ROM silently.</li>
            </ol></div>
            <div class="help-task"><h4>Troubleshoot a ROM</h4><ul>
              <li>If identity, processor or mapped addresses look wrong, confirm platform, layout and bank size before editing bytes.</li>
              <li>If commands are missing, test <code>*HELP</code> on suitable hardware and inspect the service entry. Static extraction intentionally rejects weak string-only matches.</li>
              <li>If disassembly looks meaningless, check architecture, origin and offset. The range may be text, tables, compressed data, an interleaved dump or unreachable code.</li>
              <li>If a programmed device fails, verify chip size, erased value, lane order, swaps, board links and read-back checksum against the Programmer report.</li>
              <li>Run <strong>Analyse → Image health dashboard</strong> after raw changes. Return to the checkpoint or untouched source when the result is uncertain.</li>
            </ul></div>
            <div class="help-warning"><strong>Hardware warning:</strong> a valid header does not prove that code is safe, correctly bank-switched or suitable for a particular machine. Make a checkpoint, retain the original dump and test an emulator or spare programmable device first.</div>
          </section>
          <section id="help-romfs">
            <h3>ROMFS data ROMs: complete workflow</h3>
            <p class="help-lead">ROMFS is a genuine flat filing system stored in a standard 8 KiB or 16 KiB paged ROM. It is shown as files, unlike a raw ROM's bank inventory.</p>
            <div class="help-task"><h4>Create a ROMFS image</h4><ol>
              <li>Choose <strong>File → New → New Image</strong>, then <strong>Acorn ROMFS data ROM</strong>.</li>
              <li>Review the target platform. BBC/Master or Electron is preselected from the pane workbench profile when possible. If no profile applies, choose it in the dialog.</li>
              <li>Use 16 KiB for the normal full sideways-ROM capacity, or 8 KiB for a compact device. Enter a title of up to eight characters, the version byte and an Acorn copyright string beginning with <code>(C)</code>.</li>
              <li>Create the image, then use <strong>File → Insert File</strong>, folder import, drag and drop, or cross-pane Copy and Paste to populate it.</li>
              <li>Choose <strong>Tools → Check filesystem</strong>, save the timestamped ZIP, then test the ROM on an emulator or spare programmable device.</li>
            </ol></div>
            <div class="help-task"><h4>Edit and transfer files</h4><ol>
              <li>Double-click a BASIC, script, text or binary file to use the appropriate editor. The download arrow exports a loose copy with its load/execute metadata sidecar.</li>
              <li>Names are case-sensitive, contain up to ten Latin-1 characters and may include dots or slashes. Those characters are part of the name because ROMFS has no directories.</li>
              <li>Use the pencil and × row controls to rename or delete. Multiple selections can be copied, exported or deleted together.</li>
              <li>In the Access column choose <strong>Make loadable</strong> or <strong>Mark *RUN-only</strong>. ROMFS run-only protection is not the DFS/ADFS lock bit.</li>
              <li>Host folders are flattened. Transfers to DFS or ADFS apply that destination's shorter naming and hierarchy rules while retaining load and execution addresses where possible.</li>
            </ol></div>
            <div class="help-task"><h4>Identity, CRCs and safe editing</h4><ol>
              <li>Choose <strong>Tools → ROMFS properties</strong> to edit the catalogue title, version byte and copyright. The standard paged-ROM header checksum is rebuilt.</li>
              <li>Every file header and data block carries a CRC. Normal edits rebuild the chain, and Check filesystem verifies it from the ROM header to the end marker.</li>
              <li>Complete plain ROMFS images are rebuilt in storage order, so Compact is neither shown nor needed.</li>
              <li>A composite ROM with executable bytes after its catalogue, or an incomplete multi-ROM fragment, opens as a read-only safe view. Export its files instead of moving code and absolute pointers accidentally.</li>
              <li>The creator produces a selectable data ROM, commonly entered with <code>*ROM</code>. It does not claim to produce an autostart language ROM.</li>
            </ol></div>
          </section>
          <section id="help-mmb">
            <h3>MMB disk banks: slots and embedded disks</h3>
            <figure><img src="/help/mmb-actions.png" alt="MMB File and Menu controls with slot row actions"><figcaption>Every physical slot is listed. File contains disk insertion and creation; Edit contains clipboard actions; rename, access and eject controls live on each formatted slot row.</figcaption></figure>
            <div class="help-task">
              <h4>Insert SSD, DSD or HFE image files and ZIP distributions</h4>
              <ol>
                <li>Select the first empty destination slot.</li>
                <li>Open <strong>File → Insert existing SSD / DSD / HFE / ZIP</strong>.</li>
                <li>Select one or several SSD/DSD/HFE files, or ZIP files containing them. Every supported ZIP member is imported in archive order and unrelated documentation or artwork is ignored.</li>
                <li>A DSD needs two adjacent empty slots. Its two sides occupy two SSD-sized MMB slots.</li>
                <li>Review the allocation message and, if a menu is installed, review or skip each offered menu entry.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Create a blank writable disk in a slot</h4>
              <ol>
                <li>Select an empty slot.</li>
                <li>Choose <strong>File → New → Insert new disc image</strong>.</li>
                <li>Choose SSD or DSD in the normal creation dialog, enter the disk title and choose whether it is read/write.</li>
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
                <li>Use the download arrow beside a formatted slot to export that disk directly as a standalone SSD. Empty slots have no download action.</li>
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
              <li>During a multi-item install, <strong>Abort operation</strong> stops before the next download. The item already in progress finishes at a safe image boundary. The foreground status reports elapsed time, measured item throughput and an ETA once enough completed work exists to calculate them honestly.</li>
              <li>If an archive contains the same release as both SSD and UEF, the native SSD is selected once. Installing into a blank SSD adopts its catalogue and title; shortened SSD files are safely padded to the target's standard geometry.</li>
            </ol></div>
            <div class="help-task"><h4>Insert files or applications into an open disk</h4><ol>
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
                <li>Create any supported ADFS S through G+ floppy or an HDF/RAW hard-drive image, or open a supported existing image.</li>
                <li>Double-click directories to enter them. Double-click <strong>..</strong> or use the breadcrumbs to move back through the hierarchy.</li>
                <li>Use <strong>File → New → New folder</strong> to create a validated ADFS directory at the current location.</li>
                <li>Use <strong>File → New → New file</strong> for an empty, correctly named file with explicit load and execution addresses. This is also available inside writable DFS catalogue groups and MMB disks.</li>
                <li>Use <strong>File → Insert File</strong> to import host files with load/execute addresses and optional RISC OS filetype.</li>
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
                <li>Drag an open MMB slot, SSD/DSD/HFE image, UEF tape or another supported image from another pane; alternatively use <strong>File → Insert File</strong> and select an image from the host.</li>
                <li>Review the source preview. The current directory is selected by default; optionally tick <strong>Choose a different existing directory</strong> and browse the destination tree.</li>
                <li>Optionally tick <strong>Create a new child directory</strong> and enter its name. Leave it unticked to place the source contents directly in the selected destination.</li>
                <li>Choose <strong>Keep this disc off all menus</strong>, create or update a global Universal Menu in the current directory, or add the title to any detected Universal Menu elsewhere on the HDD. A menu-bound disc is installed as its own child directory below that menu root. Bulk MMB imports provide the same global choice plus a Menu checkbox on every disc row, so individual titles can remain hidden. Keeping software off-menu never requires a launch file.</li>
                <li>An ADFS floppy is not necessarily relocatable. The importer follows direct and DATA-selected loader stages, makes proven local <code>$.name</code> references current-directory relative, and expands proven DFS abbreviations such as <code>R.</code> and <code>L.</code>. It warns when a reachable loader switches filing system or drive, or appears to use direct sector I/O. Those titles should remain mounted as floppy images unless a specific HDD installer exists.</li>
                <li>Review progress and metadata. During a bulk copy, an empty DFS disk pauses for a Skip or Abort decision; no meaningless empty ADFS directory is created.</li>
              </ol>
            </div>
            <div class="help-task">
              <h4>Check software already installed on an HDD</h4>
              <ol>
                <li>Open the ADFS HDD pane and choose <strong>Tools → Check installed disk software</strong>. This command is intentionally unavailable on ADFS floppy images.</li>
                <li>Choose the whole HDD or the current directory. The read-only pass recursively finds imports from retained source-image details and conventional launch files including <code>!BOOT</code>, <code>LOADER</code>, <code>MENU</code>, <code>GO</code> and <code>START</code>.</li>
                <li>Review every directory. The result shows the source image when known, its file count, every exact proposed rewrite and warnings which require human testing.</li>
                <li>ADFS directory paths are resolved against the installed tree before commands are classified. A real path such as <code>R.+AP2</code>, meaning file <code>+AP2</code> inside directory <code>R</code>, is preserved rather than mistaken for abbreviated <code>RUN</code>.</li>
                <li>Commands inside tokenised BASIC <code>*KEY</code> macros are interpreted without disturbing control-key sequences such as <code>|M</code> and <code>|F</code>. Changed lines receive corrected BASIC length bytes, and the audit can repair malformed lengths left by older imports before continuing its loader analysis.</li>
                <li>Select the deterministic repairs to apply and choose <strong>Repair selected</strong>, or choose <strong>Cancel</strong> to leave the image untouched. An automatic undo checkpoint is made before a repair.</li>
                <li>Run the check again. Proven current-directory path and loader-command issues should be clear. Explicit filing-system changes and direct-sector I/O remain warnings because automatically changing those behaviours would be unsafe.</li>
                <li>Older sessions may contain loader diagnoses made before the current path-aware audit. Those point-in-time messages are replaced by one review notice, repeated directory and Tube notices are consolidated, and actual byte-level compatibility changes remain in the saved history.</li>
              </ol>
            </div>
            <p>Where both formats support it, Acorn File Forge preserves load/execute addresses, RISC OS filetypes, datestamps and access flags. Old ADFS names are normally limited to ten characters.</p>
            <div class="help-note"><strong>Very large imports:</strong> the planner reads the mounted format instead of assuming an old directory. Old directories hold 47 entries, New directories hold 77, and Big directories are capacity-dependent. A large MMB selection is divided into parent groups only when required. Names such as <code>DISCS1</code> and <code>DISCS2</code> remain editable suggestions.</div>
          </section>
          <section id="help-beebscsi">
            <h3>BeebSCSI DAT and DSC: open, edit and save</h3>
            <ol>
              <li>Select either the DAT data file or its matching DSC descriptor.</li>
              <li>Choose <strong>BeebSCSI DAT + DSC</strong>. This is separate from the normal ADFS machine profiles because BeebSCSI is available for Electron, BBC and Master hosts.</li>
              <li>In the pairing dialog, the chosen file is already retained. Select only the missing companion.</li>
              <li>Confirm that both base names match, for example <code>SCSI0.dat</code> and <code>SCSI0.dsc</code>, then select <strong>Open DAT + DSC</strong>.</li>
              <li>Traverse, create, add, rename, move, lock and delete content using the normal ADFS controls.</li>
              <li>Select <strong>Save Image</strong> in the pane heading. The same foreground progress dialog used by every format reports validation, checksums, catalogue generation, elapsed time, throughput, ETA and construction of the complete ZIP. For DAT it also names geometry, directory and map checks. The ready dialog appears only after the hardware-ready ZIP containing <code>BeebSCSI0/scsi0.dat</code> and <code>BeebSCSI0/scsi0.dsc</code> is complete on disk. If the automatic download does not begin, use the direct <strong>Download ZIP</strong> link.</li>
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
            <p>Double-click an individual tape file to open its BASIC, text, disassembly or hex view. Use the download arrow beside its name to export it. Tape files remain read-only until copied to a writable disk image. A UEF stored inside ADFS or another filing system also opens as a read-only hierarchy of reconstructed cassette files. Detection uses the content, so names such as <code>$.UEF.THRUST</code> work without a <code>.uef</code> suffix, and gzip-compressed UEF data works too. The hierarchy shows load and execution addresses and marks incomplete tape sequences rather than hiding them. You can also drag reconstructed tape files to a writable disk, or drag the complete UEF onto ADFS to create and populate a directory. Standard load and execute addresses are retained. Tokenised BASIC is checked for file I/O that inherits an already-open cassette channel; starting that program directly from disk would produce error 222 (<em>Channel</em>), so the app suppresses automatic <code>!BOOT</code> creation and reports the incompatibility. During ADFS extraction, machine-code OSCLI calls are also checked for DFS-only abbreviations such as <code>R.</code> and <code>L.</code>. Proven immediate pointers are redirected to appended <code>RUN</code> and <code>LOAD</code> commands without moving the original code. If the pointer or free address range cannot be proved safe, the file is left untouched and the image receives a warning.</p>
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
              <li>Open <strong>Analyse</strong> to compare the current bytes with a local binary. Differing bytes are marked in the grid, the inspector reports byte and size differences, and <strong>Next difference</strong> navigates through them.</li>
              <li>Select a structure template to decode generic values, BBC sideways-ROM headers, RISC OS module headers, DFS catalogue sectors or ADFS map fields. Automatic mode recognises safe signatures; a template is an interpretation only and never changes bytes.</li>
            </ol></div>
            <div class="help-task"><h4>Search, select and edit</h4><ol>
              <li>Search for hexadecimal byte pairs such as <code>44 69 73 63</code>, or switch the search to Latin-1 text. Find previous and Find next can wrap around the image. Find and Replace selects the complete matched range and stages a same-length replacement; it cannot insert or remove raw bytes.</li>
              <li>Click a byte, Shift-click another byte, or hold Shift while using the arrow keys to select a range.</li>
              <li>Choose HEX or ASCII mode, then type to replace bytes. You can also paste, fill the selection with one byte, copy as hex or text, or revert selected edits.</li>
              <li>Undo and redo affect staged editor changes only. The staged-change list shows the original and replacement value at every changed offset and can jump back to it.</li>
              <li>Use Ctrl/Cmd-S to write, Ctrl/Cmd-Z or Ctrl/Cmd-Y for undo or redo, Ctrl/Cmd-F to search, Ctrl/Cmd-H for replacement, Ctrl/Cmd-G to go to an offset, and Escape to close.</li>
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
              <li>Read the duration warning. Large MMB and HDD images may take several minutes. The progress view names the current directory or menu phase and reports elapsed time, throughput and ETA. Abort operation stops at a safe boundary.</li>
              <li>If the container or browser is interrupted, reopen the application in the same browser. Recover previous session restores browser-owned working images, while History marks an in-flight server job as interrupted instead of pretending that it completed.</li>
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
              <li>Double-click a file in any filesystem pane, or select it and choose <strong>Analyse → Open selected file</strong>. Use the download arrow beside its name when you only want the original file and metadata.</li>
              <li>Tokenised BBC BASIC II opens as numbered editable source with a space after every line number. Use <strong>Tools → Renumber BASIC</strong> to update line numbers and encoded GOTO, GOSUB and other references without changing numbers inside strings.</li>
              <li>When pasting into BASIC, choose whether to validate and normalise numbered BBC BASIC source or insert the clipboard exactly as plain text. The complete listing must be valid BASIC before Save can retokenise it.</li>
              <li><code>!BOOT</code>, <code>LOADER</code> and other recognised command files open as compact unnumbered script editors. Edit their ordered <code>*EXEC</code>, OS and BASIC command lines directly.</li>
              <li>Source and disassembly windows open centred at a useful desktop working size, then scale proportionally on smaller browser windows. They can be moved by dragging the title bar and resized from any edge or corner. Use the square title-bar control, or double-click the title bar, to maximise and restore the editor. The window remains constrained to the visible browser area and resizing does not disturb the document or its scroll position. File and Edit menus provide Save, Save As, Export, Close, undo, redo, clipboard actions, Select All, Find and Find and Replace. Replace Next starts at the current selection and wraps once; Replace All reports how many case-insensitive matches it changed. Save As creates a sibling inside the image while Export downloads readable source as browser-local text. Read-only disassembly retains Find without unsafe source replacement.</li>
              <li>The tab strip keeps several files from the mounted image open together. It retains each source draft, selection and scroll position, marks dirty tabs and warns before discarding one. <strong>Open from image…</strong> searches filenames and bounded readable content, restores the result's directory, MMB slot and side, and opens it as another tab.</li>
              <li>BASIC and command scripts use themed syntax colours for keywords, strings, numbers, comments, symbols and line numbers. The normal textarea remains the editable document, preserving browser undo, clipboard and input-method behaviour. Hover a highlighted command for its purpose, syntax, requirements and important compatibility notes. One catalogue covers 8-bit BBC BASIC plus BASIC IV and BASIC V/VI extensions, with availability checked against the detected dialect. Compact source such as <code>COLOUR129</code> and <code>T%DIV256</code> follows the interpreter's token boundaries.</li>
              <li>Star commands retain their MOS context in highlighting and help. For example, <code>LOAD "PROGRAM"</code> shows BBC BASIC LOAD help, while <code>*LOAD CODE 3000</code> is labelled <code>*LOAD</code> and shows the filing-system command syntax. Compact <code>*FX200 0</code> resolves to <code>*FX</code> plus its arguments. RUN, SAVE and other overlapping names follow the same rule. Commands supplied by an optional sideways ROM receive clearly labelled ROM-dependent help when their exact syntax is not built in.</li>
              <li>Help interprets constant operands, not just command names. <code>*FX200,3</code> explains the Escape and BREAK control bits; an <code>OSCLI"FX ..."</code> string and inline-assembler OSBYTE call receive the same data-driven parameter decoding when their values can be proved. VDU help expands commas as bytes and semicolons as low-byte-first words. SOUND and ENVELOPE show every proven argument. The result is compared with the hardware profile applied to the pane. Calls documented for a different platform are still explained, then clearly marked as out of scope and liable to fail or behave unexpectedly on the configured target. Dynamic expressions remain unguessed.</li>
              <li>Inline assembler also decodes proven constant calls. Preceding same-line A, X and Y loads provide OSBYTE and OSWORD reason details, OSCLI's command pointer, and OSWRCH or VDUCHR character meaning. BASIC V/VI <code>SYS</code> calls name recognised RISC OS SWIs and their purpose.</li>
              <li>BBC BASIC inline assembler between <code>[</code> and <code>]</code> reuses the disassembly editor's processor and MOS help. Hover 6502 or ARM mnemonics, named MOS entry points such as <code>OSWRCH</code>, standard addresses such as <code>&amp;FFEE</code>, or directives such as <code>EQUB</code>. The processor catalogue distinguishes NMOS 6502, 65C02 and 65816 instruction sets rather than treating every extension as interchangeable. Matching names outside an assembler region remain ordinary BASIC variables. Refactor and Condense leave assembler lines physically intact.</li>
              <li>Press <strong>F1</strong> for help on the command at the caret. The editor's <strong>Help</strong> menu gives an overview of the detected language, a searchable command reference, live problems and document symbols. Problem and symbol entries jump back to their source location.</li>
              <li><strong>Edit → Find all references</strong> lists code uses of the symbol at the caret. <strong>Rename symbol</strong> changes those uses as one undoable operation while leaving strings and comments alone. The BASIC program outline lists procedures and functions with their call sites. Diagnostics also flag unused definitions, mismatched procedure endings and conservative unreachable-line candidates.</li>
              <li><strong>Find and Replace</strong> stays open while you work and supports match case, whole identifiers, regular expressions, selection-only scope, previous/next, one replacement, preview and Replace All. <strong>Search files in this image</strong> finds names and bounded readable content across MMB slots and filesystem directories, then opens the containing location. <strong>Analyse file dependencies</strong> checks the entire image and reports exact, unique, ambiguous, missing and root-relative launcher targets.</li>
              <li>Press <strong>Ctrl+Space</strong> for completions from known commands, identifiers, document symbols and templates. Text and script files provide duplicate, move, join and delete line operations. BASIC disables line moves that cannot preserve line-number meaning. <strong>Format selection or file</strong> applies conservative whitespace rules; BASIC must pass a token round trip before the proposal is applied.</li>
              <li>Refactor and Condense show the original and proposed source side by side. Changed rows are marked. Every BASIC proposal completes an exact tokenise, detokenise and retokenise check before acceptance; the review displays its line count and tokenised byte size. Use <strong>Tools → Verify BASIC round trip</strong> to run the check independently, and <strong>Editor history</strong> to review accepted transformations and symbol renames from this window.</li>
              <li><strong>View → Show synchronized bytes</strong> follows the BASIC line, text caret or selected disassembly row. It shows the matching saved bytes and printable characters, with a shortcut into the full Hex editor. Unsaved source is never presented as if it had already changed the image. A new or renumbered BASIC line reports that it has no saved byte range until Save succeeds.</li>
              <li>Live BASIC checks cover missing, duplicate and out-of-order line numbers, unresolved direct GOTO, GOSUB and RESTORE destinations, missing local DEF PROC definitions and unclosed strings. Script checks cover unclosed strings, filing-system-dependent <code>R.</code> and <code>L.</code> abbreviations and use of <code>CHAIN "!BOOT"</code> where a command script needs <code>*EXEC</code>. Treat these as focused editing checks rather than proof that software will run on every target.</li>
              <li>Use <strong>Edit → Go to line</strong> for a physical source line or BASIC line number. BASIC selections can be commented or uncommented with <strong>Toggle comment</strong>. <strong>Tools → Normalise recognised commands</strong> follows the detected language convention while leaving strings, comments and identifiers unchanged. BBC BASIC and Acorn command scripts currently normalise commands to uppercase; the mechanism can support lowercase-preferring languages.</li>
              <li><strong>Tools → Refactor selection or program</strong> applies to one selected line, a selected block, or the complete program when nothing is selected. It opens a non-destructive proposal that normalises proven BASIC commands, expands every safe colon-separated operation, and turns nested IF/ELSE IF/ELSE forms into readable guarded branches without changing their scope. It renumbers from 10 and updates direct destinations, including every entry in ON GOTO and ON GOSUB lists. Omitted-THEN command and assignment branches are recognised when the statement boundary can be proved. A compact ON ERROR handler is extracted behind an explicit ON ERROR GOTO target and a normal-flow jump over the handler. Star commands remain physical units because the rest of their line is command text. Nothing changes until ✓ is selected and confirmed; × discards the proposal untouched. The accepted rewrite is one undoable operation and retains the logical cursor and viewport.</li>
              <li><strong>Tools → Condense selection or program</strong> is the safe inverse. It uses colons to pack adjacent statements into the fewest tokenised lines allowed by the real BBC BASIC line limit. Explicit target lines begin a new packed line. Inline IF scope, ON ERROR handlers, comments, star commands, unconditional transfers and structured branch boundaries are never crossed. Programs with computed line destinations or ERL-dependent behaviour are refused rather than guessed. Surviving line numbers are retained. Condense also uses the ✓/× proposal, one-step undo and viewport preservation.</li>
              <li>BASIC procedures, FOR and REPEAT loops, structured IF, CASE and WHILE blocks have minus controls in the left gutter. Select one to collapse that block and use its plus control to restore it. The single View command reads <strong>Collapse all blocks</strong> when everything is expanded and <strong>Expand all blocks</strong> when anything is collapsed. Folding never changes the real textarea or saved program. Double-click an outline line to expand everything and continue editing there. Every file initially opens fully expanded.</li>
              <li><strong>View → Structure guidance</strong> draws live 2, 4, or 8-character guide steps beside the editable BASIC source and highlights the innermost procedure, function, loop or structured conditional containing the caret. It is presentation only and never inserts indentation, replaces the textarea, changes dirty state or alters saved image bytes.</li>
              <li>Procedures and multi-line functions receive consistent guide levels from <code>DEFPROCname</code> or <code>DEFFNname</code> to <code>ENDPROC</code> or the function's leading <code>=</code> return. Compact tokenised forms such as <code>FORI%=...</code> and closers later on a line, such as <code>]:NEXT</code>, <code>NEXT:ENDPROC</code> and <code>CALL address:ENDPROC</code>, are recognised. A one-line <code>DEFFNname(...)=expression</code> does not open a block. Folding uses the same scanner.</li>
              <li>Structure guidance classifies Refactor's generated lines immediately using the same scanner as folding. A classic <code>IF condition THEN line</code> controls one statement and does not open a multi-line block, so later physical lines reached through branching or fall-through are not shown inside it. The saved program remains free of display-only indentation.</li>
              <li>Other readable files open in the text editor. Binary files open as editor-style NMOS 6502, 65C02, 65816, ARM or 68000 source. Proven register values, MOS call purposes and reason codes, branch conditions, hardware I/O regions, entry points, BRK error messages and cross-references appear as semicolon comments on the relevant instruction. Internal targets receive stable labels derived from proved behaviour, such as <code>write_text_8120</code>, <code>execute_command_834A</code>, <code>loop_8057</code> or <code>equal_80C2</code>, instead of anonymous subroutine/location names. The hexadecimal suffix keeps similar routines distinct. The analyser drops register assumptions at uncertain control-flow joins instead of inventing values. The readable-string list filters out accidental punctuation and number runs; select a string to jump to its disassembled line. Double-click an instruction only when you want that offset in Hex.</li>
              <li>Every processor disassembly row has hover help, including condition and size variants, unfamiliar decoder mnemonics and pseudo-operations such as <code>EQUB</code> and <code>EQUS</code>. Help combines the operation family, exact operand and addressing form, encoded bytes, cross-references and the analyser's contextual comment. MOS entry points retain their specific calling conventions. The Help menu lists operations actually present as well as its instruction and MOS reference.</li>
              <li>The disassembly <strong>Project</strong> menu retains notes, bookmarks, symbols, offset-bound comments and code/data decisions outside the image bytes. Click one row or shift-click a range, then mark it as code, text, bytes, words, addresses or bitmap data. The listing is rebuilt using that decision. ARM word regions use little-endian values and 68000 word regions use big-endian values. Symbols apply to every supported processor and use a portable <code>&amp;address = label</code> text format for import and export. Find references and the outline show direct callers and labelled entry points.</li>
              <li><strong>Tools → Inspect selected data</strong> presents bounded text, bytes, little-endian and big-endian words, plus a one-bit bitmap preview. Project metadata has one manager for notes, symbols, comments, bookmarks and portable JSON. A saved line comment remains attached to its exact file offset and is rendered beside the instruction. <strong>Compare with saved file</strong> displays saved and current source side by side.</li>
              <li><strong>Edit and reassemble</strong> is enabled only when <code>ACORN_FILE_ASSEMBLER_COMMAND</code> contains <code>{source}</code> and <code>{output}</code>. It opens generated label-oriented assembly for review and requires confirmation before checksum-guarded replacement of the complete binary. <strong>Debug from selected address</strong> uses a configured <code>ACORN_FILE_DEBUGGER_COMMAND</code>; the return status and output are retained in project history.</li>
              <li><strong>Tools → Run… / Debug…</strong> appears in every pane whose media can be attached to the configured machine. Standalone DFS, ADFS and tape images mount directly. At an MMB index, select exactly one formatted slot; the app extracts a temporary SSD and leaves the working MMB unchanged. The commands remain available while browsing inside that slot. Whole-MMB mounting is shown separately but disabled until an MMFS-compatible SD-card emulator adapter is available.</li>
              <li><strong>Project → Run in configured emulator</strong> appears in source and disassembly editors. Choose a hardware profile in the Workbench and apply it to the pane. Electron uses the bundled Elkulator build with the Pi1MHz and AP5 patches; BBC B, B+ and Master use bundled B-em; Archimedes uses bundled MAME when matching RISC OS firmware is available. BASIC offers Inject and run/debug BASIC buffer, Mount and boot parent, or Mount parent only. Injection tokenises the current editor text into a temporary bootable floppy as <code>PROGRAM</code>, so unsaved changes are included but companion files are not. Parent choices retain dependencies and appear only if that emulator supports the container. The running machine appears in a live browser display. Click the display before typing, use Full screen when useful, and choose Stop and close to end the emulator cleanly. Capability and error text always names the effective pane emulator. <strong>Emulator and debugger results</strong> retains return status and output. Errors and notices raised while an editor is open are displayed inside that editor window, above its content, so they cannot be hidden behind the modal backdrop.</li>
              <li>Editor tabs, unsaved drafts, selection and scroll position survive a refresh in bounded browser-session storage. <strong>Open from image…</strong> searches every formatted slot of an MMB and labels results with slot number and disk title.</li>
              <li>The Hex editor includes structured views for ROM, ROMFS, RISC OS modules, DFS, ADFS, MMB, BeebSCSI DSC and UEF data. A custom JSON template can describe bounded fields relative to the selected byte.</li>
              <li>Labelled disassembly regions also have left-gutter folding controls. The single state-aware <strong>View</strong> command collapses or expands all labelled regions as appropriate. Visible instruction rows retain double-click-to-Hex while other regions are folded.</li>
              <li>ZIP, TAR, compressed TAR, GZIP, BZIP2 and XZ files are marked as archives. Double-click one to browse its safe file and folder hierarchy in the pane; use breadcrumbs or <strong>..</strong> to move up. Double-click a member to extract it in memory and open the normal BASIC, command-script, text, disassembly or hex viewer. Readable members can be edited: Save verifies both hashes, rebuilds the complete container and checkpoints the outer image. UEF tape members stay read-only because reconstruction could alter timing or loader behaviour. Parent traversal, non-regular TAR objects, archives over 512 MiB, members over 128 MiB and catalogues reaching 20,000 entries are rejected rather than processed without a safe bound.</li>
              <li>Use <strong>Tools → Open raw bytes in Hex</strong> from any file viewer when the automatic interpretation is uncertain. File saves retain Acorn load, execution and filetype metadata, reject stale edits and create an undo checkpoint.</li>
              <li>The shared structural scanner understands classic and structured BBC BASIC forms, typed variables and star commands, and carries explicit BASIC I through VI capability profiles. Diagnostics flag commands that require a later detected dialect. BASIC II programs with a recognised trailing payload are editable because only the tokenised prefix is replaced and the payload is preserved byte for byte. BASIC V remains read-only because rewriting its extended tokens as BASIC II would be unsafe.</li>
              <li>Choose <strong>Check loader dependencies</strong> to resolve CHAIN, EXEC, RUN, LOAD, DIR and LIB targets beside the launcher and flag root-relative references before moving software below ADFS root.</li>
            </ol></div>
            <figure><img src="/help/file-editor-script.png" alt="Command-script editor showing a real DFS !BOOT file"><figcaption>Command scripts remain unnumbered and preserve their execution order. Save keeps the file's Acorn metadata.</figcaption></figure>
            <figure><img src="/help/file-editor-basic.png" alt="BBC BASIC editor showing a tokenised loader with syntax colour and folding controls"><figcaption>Tokenised BBC BASIC II opens as editable numbered source. Folding and visual indentation do not alter the saved program.</figcaption></figure>
            <figure><img src="/help/file-editor-disassembly.png" alt="Annotated 6502 disassembly with address, bytes, instruction and annotation columns"><figcaption>Binary files open as bounded NMOS 6502, 65C02, 65816, ARM or 68000 disassembly. Comments remain beside the instruction they describe and the original bytes remain available through Hex.</figcaption></figure>
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
              <li>Choose <strong>Workbench → Hardware profiles</strong>. Start from a stock Electron, BBC B, BBC B+, Master or Archimedes profile, a common disk or mass-storage configuration, or the supplied RH Plus 1/2, Plus 3, AP5 and BeebSCSI custom system.</li>
              <li>Select the base machine in the left column, then build its hardware in the wider right column. Chassis, floppy interface, memory and Tube choices use dropdowns because only one can be fitted. PiTubeDirect is offered for BBC B, BBC B+, Master and Electron systems; an Electron profile also needs an AP5 Tube interface. Cumulative firmware, mass storage and podule groups use bounded checkboxes. The list changes with the machine, required carrier or bus expansions are added automatically, and removing a dependency clears combinations that can no longer exist.</li>
              <li>A profile also records the Library filter, filing system, MMFS build, expected PAGE, validation target, managed emulator, debugger, RAM and startup action. Emulator-driven additions select the closest B-em model, Elkulator configuration, Tube processor, controller or MAME podule. Hardware marked <strong>Validation only</strong> still affects analysis without pretending that the emulator implements it.</li>
              <li>Save retains the profile in this browser. Apply attaches it to an image session. The active profile becomes the default for panes without their own profile and drives Online Library machine filtering.</li>
              <li>Choose <strong>Import recipes</strong> to save naming, group prefix, online metadata, compatibility and menu choices. Saved recipes appear in the MMB-to-ADFS planner.</li>
              <li>Choose <strong>Portable project</strong> to export the current pane windows, their geometry and stack, session references, paths, profiles and recipes. Import it on the same retained installation to restore that working context. Theme remains a browser preference.</li>
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
              <dt>Double-click a file</dt><dd>Open the content-aware BASIC, script, text, disassembly or hex editor.</dd>
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
              <li>The released Oaknut 12.14.1 engine safely creates and edits ADFS S/M/L/D/E/E+/F/F+/G/G+, old-map and new-map FileCore hard disks, and BeebSCSI old-map DAT with its matching DSC.</li>
              <li>D/E/F/G New directories allow 77 entries with 10-character names. E+/F+/G+ Big directories allow names up to 255 characters and a capacity-dependent number of entries. The pane and bulk planner use those detected limits.</li>
              <li>RPCEmu and Arculator HDF/HD4 images whose logical FileCore disc begins at the 0x200-byte emulator offset are content-detected and retain that layout.</li>
              <li>“Physical HDD” means a byte-for-byte RAW image. The browser and container do not access devices such as <code>/dev/sdb</code> directly.</li>
              <li>UEF tape catalogues are read-only; convert or copy their reconstructed files into writable media.</li>
              <li>HFE v2/v3, bad-sector and advanced track images open read-only. Clean sector-based HFE v1 images can be edited and are verified again when saved.</li>
              <li>Metadata is preserved only where the destination filing system has an equivalent field.</li>
            </ul>
            <h4>When something does not work</h4>
            <dl>
              <dt>Button is disabled</dt><dd>Select a suitable item first, or wait for the current pane operation to finish. Blank-disk creation requires an empty MMB slot.</dd>
              <dt>Invalid filename</dt><dd>Use the prompted replacement. DFS leaf names are seven characters; normal ADFS directories allow ten and FileCore Big directories allow up to 255.</dd>
              <dt>Not enough space</dt><dd>Delete unwanted data, compact the filesystem, or create a larger destination. DFS also has a 31-file catalogue limit.</dd>
              <dt>DSD will not insert</dt><dd>Choose a starting position with two adjacent empty MMB slots.</dd>
              <dt>HFE is read-only</dt><dd>The image uses HFE v2/v3, reports bad sectors, or contains track features the sector editor cannot reproduce safely. Export its files or copy its readable sectors to another image.</dd>
              <dt>A FileCore image cannot be opened</dt><dd>Confirm it is a raw ADFS/FileCore image or a supported HDF/HD4 layout rather than a compressed archive or track dump. The Docker build pins Oaknut 12.14.1 and needs no local patch. The detailed error distinguishes an unrecognised filesystem from a corrupt map or directory.</dd>
              <dt>Name collision found</dt><dd>Use the default DISC-0000 naming strategy, or review every highlighted name. The check is case-insensitive and scoped to each destination parent.</dd>
              <dt>Empty disk found</dt><dd>Choose Skip and continue or Abort. Blank disks can be stored in MMB, but do not become empty ADFS directories.</dd>
              <dt>Destination exists</dt><dd>An empty directory is reused silently. A populated directory offers Keep, Replace or Abort; a file is never overwritten as though it were an empty directory.</dd>
              <dt>DAT geometry error</dt><dd>An old-map BeebSCSI DAT needs its exact matching DSC file. New-map FileCore DAT images describe their filesystem geometry on-disc and do not need that sidecar.</dd>
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
            <p class="help-lead">Acorn File Forge is an open-source project. Its documentation covers installation, every supported media family, the file editors, ROM maintenance, firmware and release validation.</p>
            <div class="help-task"><h4>Choose the detailed reference</h4><ul>
              <li><a href="https://github.com/peteclarke-del/AcornFileForge/blob/main/docs/README.md" target="_blank" rel="noopener noreferrer">Documentation index</a>: a task and capability map for the complete handbook.</li>
              <li><a href="https://github.com/peteclarke-del/AcornFileForge/blob/main/README.md" target="_blank" rel="noopener noreferrer">Product and media handbook</a>: formats, restrictions, workflows, architecture, configuration and tests.</li>
              <li><a href="https://github.com/peteclarke-del/AcornFileForge/blob/main/docs/INSTALLATION.md" target="_blank" rel="noopener noreferrer">Installation and operations</a>: desktop and Raspberry Pi builds, ports, sessions, updates, backups and diagnostics.</li>
              <li><a href="https://github.com/peteclarke-del/AcornFileForge/blob/main/docs/FILE-EDITOR-GUIDE.md" target="_blank" rel="noopener noreferrer">File editor and code analysis</a>: BASIC, scripts, disassembly, archives, binary synchronisation and emulator hand-off.</li>
              <li><a href="https://github.com/peteclarke-del/AcornFileForge/blob/main/docs/ROM-GUIDE.md" target="_blank" rel="noopener noreferrer">ROM image handbook</a>: banks, commands, decoded regions, ROMFS, Workbench, programmers and projects.</li>
            </ul></div>
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
    return showHelp;
  }
  window.AcornHelp = Object.freeze({ create });
})();
