const STYLE_ID = "ai-novel-world-2026-ui";


export function ensureNovelStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    :root {
      --anw-orange: #ff7043;
      --anw-orange-strong: #ff5d2a;
      --anw-orange-soft: #fff2ec;
      --anw-violet: #7c3aed;
      --anw-ink: #17191f;
      --anw-text: #343844;
      --anw-muted: #8a909d;
      --anw-line: #eceef2;
      --anw-canvas: #f7f8fa;
      --anw-card: #ffffff;
      --anw-success: #07986b;
      --anw-shadow: 0 10px 30px rgba(24, 31, 46, .07);
      --anw-shadow-soft: 0 4px 14px rgba(24, 31, 46, .06);
    }

    .anw-app,
    .anw-app * { box-sizing: border-box; }

    .anw-app {
      min-height: 100%;
      color: var(--anw-text);
      background: var(--anw-canvas);
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    .anw-app h1,
    .anw-app h2,
    .anw-app h3 { color: var(--anw-ink) !important; }

    .anw-app button,
    .anw-app input,
    .anw-app textarea { font-family: inherit; }

    .anw-page {
      min-height: 100%;
      overflow: auto;
      padding: 28px clamp(20px, 4vw, 52px) 56px;
      background:
        radial-gradient(circle at 88% 2%, rgba(255, 112, 67, .08), transparent 260px),
        var(--anw-canvas);
    }

    .anw-page-inner { width: min(1120px, 100%); margin: 0 auto; }

    .anw-page-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 22px;
    }

    .anw-eyebrow {
      color: var(--anw-orange-strong);
      font-size: 12px;
      font-weight: 750;
      letter-spacing: .12em;
      text-transform: uppercase;
    }

    .anw-page-title { margin: 5px 0 7px; color: var(--anw-ink); font-size: 30px; line-height: 1.25; }
    .anw-page-subtitle { margin: 0; color: var(--anw-muted); font-size: 14px; }

    .anw-primary-button.qwenpaw-btn,
    .anw-primary-button {
      border: 0 !important;
      color: #fff !important;
      background: linear-gradient(135deg, var(--anw-orange), var(--anw-orange-strong)) !important;
      box-shadow: 0 7px 16px rgba(255, 93, 42, .22);
    }

    .anw-primary-button:hover { transform: translateY(-1px); }

    .anw-quick-nav {
      display: flex;
      gap: 12px;
      margin-bottom: 22px;
      padding: 5px;
      width: fit-content;
      border-radius: 16px;
      background: rgba(255,255,255,.78);
      box-shadow: var(--anw-shadow-soft);
    }

    .anw-quick-item {
      display: flex;
      align-items: center;
      gap: 8px;
      border: 0;
      border-radius: 12px;
      padding: 10px 15px;
      color: #69707d;
      background: transparent;
      cursor: pointer;
      font-size: 13px;
      font-weight: 650;
    }

    .anw-quick-item.is-active { color: var(--anw-orange-strong); background: var(--anw-orange-soft); }
    .anw-quick-item:disabled { cursor:not-allowed; opacity:.58; }
    .anw-soon-badge { border-radius:999px; padding:2px 6px; color:#747b87; background:#eef0f3; font-size:9px; font-weight:700; }

    .anw-library-grid { display:grid; width:min(760px,100%); gap:22px; margin:0 auto; }

    .anw-novel-card {
      min-width: 0;
      overflow: hidden;
      border: 1px solid rgba(228, 231, 237, .86);
      border-radius: 16px;
      background: var(--anw-card);
      box-shadow: var(--anw-shadow);
      transition: transform .2s ease, box-shadow .2s ease;
    }

    .anw-novel-card:hover { transform: translateY(-2px); box-shadow: 0 16px 38px rgba(24, 31, 46, .1); }

    .anw-novel-hero {
      display: grid;
      grid-template-columns: 154px minmax(0, 1fr);
      gap: 24px;
      min-height: 250px;
      padding: 24px;
      background: linear-gradient(135deg, #effbff 0%, #f4f7ff 68%, #fff4ee 100%);
    }

    .anw-cover {
      width: 154px;
      height: 212px;
      border-radius: 12px;
      object-fit: cover;
      box-shadow: 0 14px 26px rgba(20, 33, 53, .2);
      background: #111827;
    }

    .anw-cover-fallback {
      display: flex;
      flex-direction: column;
      gap: 10px;
      width: 154px;
      height: 212px;
      align-items: center;
      justify-content: center;
      padding: 18px;
      border: 1px dashed #ccd3dc;
      border-radius: 12px;
      color: #747b87;
      background: #eef1f5;
      font-size: 12px;
      line-height: 1.6;
      text-align: center;
    }
    .anw-cover-monogram { display:flex; width:52px; height:52px; align-items:center; justify-content:center; border-radius:15px; color:#fff; background:linear-gradient(135deg,#ff8a65,#ff5d2a); font-size:24px; font-weight:850; box-shadow:0 10px 20px rgba(255,93,42,.2); }
    .anw-cover-empty-label { font-size:11px; }

    .anw-novel-meta { display: flex; min-width: 0; flex-direction: column; padding-top: 4px; }
    .anw-novel-title { margin: 0 0 12px; color: var(--anw-ink); font-size: 24px; line-height: 1.35; }
    .anw-stats { display: flex; flex-wrap: wrap; gap: 6px 14px; color: #707783; font-size: 13px; }
    .anw-tags { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 13px; }
    .anw-tag { border-radius: 999px; padding: 4px 9px; color: #657080; background: rgba(255,255,255,.8); font-size: 12px; }
    .anw-tag.is-accent { color: #4b64be; background: #eaf0ff; }
    .anw-latest { margin-top: auto; color: #68707d; font-size: 12px; line-height: 1.6; }

    .anw-novel-tools {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      padding: 14px 18px 10px;
      border-top: 1px solid rgba(232,235,240,.78);
    }

    .anw-tool-button {
      display: flex;
      min-width: 0;
      flex-direction: column;
      align-items: center;
      gap: 5px;
      border: 0;
      color: #747b86;
      background: transparent;
      cursor: pointer;
      font-size: 12px;
    }

    .anw-tool-button:hover { color: var(--anw-orange-strong); }
    .anw-start { padding: 0 18px 18px; }
    .anw-start .qwenpaw-btn { height: 40px; border-radius: 10px; font-weight: 700; }

    .anw-empty-library {
      padding: 44px;
      border: 1px dashed #d9dde4;
      border-radius: 20px;
      background: rgba(255,255,255,.76);
      text-align: center;
    }

    .anw-project {
      display: grid;
      grid-template-columns: 286px minmax(0, 1fr);
      gap: 20px;
      height: 100%;
      min-height: 0;
      padding: 20px;
      overflow: auto;
      color: var(--anw-text);
      background: var(--anw-canvas);
    }

    .anw-book-rail {
      align-self: start;
      overflow: hidden;
      border: 1px solid var(--anw-line);
      border-radius: 18px;
      background: #fff;
      box-shadow: var(--anw-shadow-soft);
    }

    .anw-book-rail-top { padding: 18px; }
    .anw-book-cover-large { width: 100%; aspect-ratio: 2 / 2.72; border-radius: 14px; object-fit: cover; box-shadow: 0 12px 24px rgba(12, 26, 48, .18); }
    .anw-book-cover-empty { display:flex; width:100%; aspect-ratio:2/2.72; flex-direction:column; gap:10px; align-items:center; justify-content:center; border-radius:14px; color:#8a9099; background:#eef1f4; }
    .anw-book-title { margin: 17px 0 7px; color: var(--anw-ink); font-size: 20px; }
    .anw-book-description { color: var(--anw-muted); font-size: 12px; line-height: 1.7; }
    .anw-book-counts { display: flex; gap: 16px; margin-top: 13px; color: #535a66; font-size: 13px; }

    .anw-project-nav { display: grid; gap: 7px; padding: 0 14px 16px; }
    .anw-project-nav-button {
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      min-height: 42px;
      border: 1px solid transparent;
      border-radius: 10px;
      padding: 0 13px;
      color: #59606c;
      background: #f2f3f5;
      cursor: pointer;
      font-weight: 650;
      text-align: left;
    }
    .anw-project-nav-button.is-active { border-color: var(--anw-orange); color: var(--anw-ink); background: #fff7f3; }
    .anw-project-nav-button:focus { outline:none; }
    .anw-project-nav-button.is-active:focus { box-shadow:inset 0 0 0 1px var(--anw-orange); }

    .anw-project-main {
      min-width: 0;
      min-height: 520px;
      overflow: hidden;
      border: 1px solid var(--anw-line);
      border-radius: 18px;
      background: #fff;
      box-shadow: var(--anw-shadow);
    }

    .anw-panel-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 76px;
      padding: 18px 22px;
      border-bottom: 1px solid var(--anw-line);
    }
    .anw-panel-title { margin: 0; color: var(--anw-ink); font-size: 21px; }
    .anw-panel-subtitle { margin-top: 4px; color: var(--anw-muted); font-size: 12px; }
    .anw-panel-actions { display: flex; flex-wrap: wrap; gap: 9px; }
    .anw-panel-actions .qwenpaw-btn:not(.anw-primary-button),
    .anw-editor-topbar .qwenpaw-btn:not(.anw-primary-button),
    .anw-volume-actions .qwenpaw-btn {
      color:#555d69 !important;
      border-color:#e4e7eb !important;
      background:#fff !important;
      box-shadow:none !important;
    }

    .anw-panel-body { padding: 22px; }
    .anw-chapter-dashboard { display:grid; gap:18px; }
    .anw-subsection-title { margin:0; color:var(--anw-ink); font-size:16px; }
    .anw-subsection-row { display:flex; align-items:center; justify-content:space-between; gap:16px; }
    .anw-volume-overview { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:14px; }
    .anw-volume-tile { position:relative; min-height:132px; overflow:hidden; border:1px solid var(--anw-line); border-radius:14px; padding:20px 92px 18px 20px; background:linear-gradient(145deg,#fff,#fafbfc); }
    .anw-volume-index { position:absolute; right:16px; top:9px; color:#f0f1f3; font-size:58px; font-weight:900; line-height:1; }
    .anw-volume-actions { position:absolute; right:10px; bottom:10px; display:flex; }
    .anw-chapter-shelf { overflow:hidden; border:1px solid var(--anw-line); border-radius:14px; }
    .anw-volume-card { overflow: hidden; border: 1px solid var(--anw-line); border-radius: 14px; background: #fcfcfd; }
    .anw-volume-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 16px; }
    .anw-volume-name { color: var(--anw-ink); font-weight: 750; }
    .anw-volume-count { color: var(--anw-muted); font-size: 12px; }
    .anw-chapter-list { display: grid; gap: 1px; border-top: 1px solid var(--anw-line); background: var(--anw-line); }
    .anw-chapter-row {
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr) auto auto;
      align-items: center;
      gap: 14px;
      min-height: 58px;
      border: 0;
      padding: 10px 16px;
      color: var(--anw-text);
      background: #fff;
      cursor: pointer;
      text-align: left;
    }
    .anw-chapter-row:hover { background: #fff8f5; }
    .anw-chapter-number { color:#b2b6bd; font-size:12px; font-weight:750; }
    .anw-chapter-row-title { overflow: hidden; color: var(--anw-ink); font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
    .anw-chapter-row-meta { color: var(--anw-muted); font-size: 12px; white-space: nowrap; }
    .anw-chapter-volume-list { display:grid; gap:14px; }
    .anw-chapter-volume-section { overflow:hidden; border:1px solid var(--anw-line); border-radius:14px; background:#fff; }
    .anw-chapter-group-header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 16px; color:var(--anw-muted); background:#fafbfc; font-size:12px; }
    .anw-chapter-group-header strong { color:var(--anw-ink); font-size:13px; }
    .anw-inline-empty { padding:18px; color:var(--anw-muted); text-align:center; font-size:12px; }

    .anw-content-sections { display: grid; gap: 16px; }
    .anw-info-card { position:relative; border: 1px solid #f0dfd7; border-radius: 14px; padding: 22px 24px; background: #fffaf6; }
    .anw-card-tools { position:absolute; right:18px; top:17px; display:flex; align-items:center; justify-content:center; width:30px; height:30px; border-radius:8px; color:#8c929d; background:#fff; box-shadow:var(--anw-shadow-soft); }
    .anw-info-card-title { margin: 0 0 10px; padding-left: 12px; border-left: 4px solid var(--anw-orange); color: var(--anw-ink); font-size: 16px; }
    .anw-info-card-copy { margin: 0; color: #515762; font-size: 14px; line-height: 1.85; white-space: pre-wrap; }
    .anw-version-title { color:var(--anw-ink) !important; font-size:14px; }
    .anw-restore-confirm p { margin:0 0 8px; color:inherit; line-height:1.7; opacity:.78; }
    .anw-restore-impact { margin:14px 0; border:1px solid #f0dfd7; border-radius:12px; padding:14px 16px; background:#fffaf6; }
    .anw-restore-impact strong { color:var(--anw-ink); }
    .anw-restore-impact ul { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 20px; margin:10px 0 0; padding-left:20px; color:#555d69; }
    .anw-restore-diff { margin-top:14px; border-top:1px solid var(--anw-line); padding-top:12px; }
    .anw-restore-diff summary { color:var(--anw-orange-strong); cursor:pointer; font-weight:650; }
    .anw-restore-diff pre { max-height:220px; margin:10px 0 0; overflow:auto; border-radius:10px; padding:12px; color:#4e5561; background:#f7f8fa; font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace; white-space:pre-wrap; }

    .anw-entity-group { margin-bottom: 24px; }
    .anw-entity-heading { margin: 0 0 12px; color: var(--anw-ink); font-size: 16px; }
    .anw-entity-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .anw-entity-card { min-width: 0; border: 1px solid var(--anw-line); border-radius: 14px; padding: 18px; background: #fff; box-shadow: var(--anw-shadow-soft); }
    .anw-entity-card.is-stale,.anw-clue-card.is-stale { border-style:dashed; background:#fffaf4; }
    .anw-avatar { display:flex; width:44px; height:44px; align-items:center; justify-content:center; border-radius:50%; color:#fff; background:var(--anw-orange); font-size:18px; font-weight:800; }
    .anw-entity-name { margin: 10px 0 3px; color: var(--anw-ink); font-weight: 750; }
    .anw-role-identity { color:var(--anw-orange-strong); font-size:12px; font-weight:700; }
    .anw-entity-copy { min-height:56px; margin-top:10px; overflow: hidden; color: var(--anw-muted); font-size: 12px; line-height: 1.65; text-overflow: ellipsis; }
    .anw-role-footer { display:flex; align-items:center; justify-content:space-between; margin-top:14px; padding-top:12px; border-top:1px solid var(--anw-line); color:var(--anw-muted); font-size:11px; }
    .anw-role-footer strong { color:var(--anw-success); font-size:12px; }
    .anw-role-footer strong.is-stale,.anw-clue-state.is-stale { color:#b76b1c; }

    .anw-segmented { display:flex; gap:4px; padding:4px; border-radius:10px; background:#f1f2f4; }
    .anw-segmented button { border:0; border-radius:7px; padding:6px 12px; color:#747a84; background:transparent; cursor:pointer; font-size:12px; }
    .anw-segmented button.is-active { color:var(--anw-ink); background:#fff; box-shadow:0 2px 7px rgba(20,28,43,.08); }
    .anw-segmented button:disabled { cursor:not-allowed; opacity:.45; }
    .anw-clue-board { display:grid; gap:16px; }
    .anw-clue-tabs { width:fit-content; max-width:100%; overflow-x:auto; }
    .anw-clue-card { display:grid; grid-template-columns:64px minmax(0,1fr) auto; align-items:start; gap:16px; border:1px solid var(--anw-line); border-radius:14px; padding:18px; background:#fff; box-shadow:var(--anw-shadow-soft); }
    .anw-clue-kind { border-radius:999px; padding:5px 8px; color:#9b4b2c; background:var(--anw-orange-soft); font-size:11px; font-weight:750; text-align:center; }
    .anw-clue-content h3 { margin:0 0 7px; color:var(--anw-ink); font-size:15px; }
    .anw-clue-content p { margin:0; color:var(--anw-muted); font-size:12px; line-height:1.7; }
    .anw-clue-state { color:var(--anw-success); font-size:12px; white-space:nowrap; }

    .anw-empty-panel,.anw-loading-panel { display:flex; min-height:300px; flex-direction:column; align-items:center; justify-content:center; gap:14px; }
    .anw-loading-panel { color:var(--anw-muted); font-size:12px; }

    .anw-empty-state { display:flex; min-height: 330px; flex-direction:column; align-items:center; justify-content:center; padding:36px; color:var(--anw-muted); text-align:center; }
    .anw-empty-state strong { margin-bottom:8px; color:#646b76; font-size:18px; }
    .anw-empty-state p { max-width:440px; margin:0 0 18px; line-height:1.7; }

    .anw-editor {
      display: flex;
      height: 100%;
      min-height: 0;
      flex-direction: column;
      overflow: hidden;
      color: var(--anw-text);
      background: var(--anw-canvas);
    }
    .anw-editor-topbar {
      display: flex;
      align-items: center;
      gap: 12px;
      min-height: 64px;
      margin: 14px 16px 0;
      padding: 10px 16px;
      border: 1px solid var(--anw-line);
      border-radius: 15px;
      background: #fff;
      box-shadow: var(--anw-shadow-soft);
    }
    .anw-editor-crumb { min-width:0; flex:1; overflow:hidden; color:var(--anw-muted); font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
    .anw-editor-crumb strong { color:var(--anw-ink); }
    .anw-save-state { border-radius:999px; padding:5px 9px; color:#407464; background:#eaf8f2; font-size:12px; white-space:nowrap; }
    .anw-save-state.is-error { color:#b43c2a; background:#fff0ec; }

    .anw-editor-scroll { flex:1; min-height:0; overflow:auto; padding:18px 16px 98px; }
    .anw-editor-paper { display:flex; width:min(880px,100%); min-height:100%; flex-direction:column; margin:0 auto; border:1px solid var(--anw-line); border-radius:18px; padding:36px 42px 54px; background:#fff; box-shadow:var(--anw-shadow); }
    .anw-editor-title-row { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding-bottom:20px; border-bottom:1px solid var(--anw-line); }
    .anw-editor-title { margin:0 0 8px; color:var(--anw-ink); font-size:27px; }
    .anw-editor-count { color:var(--anw-muted); font-size:13px; }
    .anw-editor-count strong { color:var(--anw-orange-strong); }
    .anw-editor-textarea {
      width:100%;
      min-height:560px;
      flex:1;
      resize:none;
      border:0;
      outline:0;
      padding:24px 0 0;
      color:#30343b;
      background:transparent;
      font:17px/2 ui-serif, "Songti SC", STSong, serif;
    }
    .anw-editor-footer {
      position:absolute;
      z-index:10;
      right:22px;
      bottom:18px;
      left:22px;
      display:flex;
      align-items:center;
      justify-content:center;
      gap:10px;
      pointer-events:none;
    }
    .anw-editor-footer > * { pointer-events:auto; }

    .anw-workflow-buttons { display:flex; flex-wrap:wrap; align-items:center; justify-content:center; gap:8px; padding:8px; border:1px solid rgba(226,229,235,.92); border-radius:15px; background:rgba(255,255,255,.95); box-shadow:0 12px 30px rgba(20,28,43,.13); backdrop-filter:blur(14px); }
    .anw-workflow-panel { flex-wrap:nowrap!important; }
    .anw-workflow-buttons .qwenpaw-btn { height:38px; border-radius:10px; }
    .anw-workflow-buttons .qwenpaw-btn:not(.anw-generate-button):not(.anw-intel-button) { color:#4f5661!important; border-color:#e1e4e9!important; background:#fff!important; }
    .anw-app .anw-workflow-buttons .qwenpaw-btn.anw-generate-button { color:#fff!important; border-color:#ff7043!important; background:#ff7043!important; font-weight:750; }
    .anw-app .anw-workflow-buttons .qwenpaw-btn.anw-intel-button { color:#fff!important; border-color:#07986b!important; background:#07986b!important; }

    .anw-workbench-frame { position:relative; display:grid; grid-template-columns:minmax(0,1fr); height:100%; min-height:0; overflow:hidden; background:var(--anw-canvas); }
    .anw-workbench-main > .qwenpaw-spin-nested-loading,
    .anw-workbench-main > .qwenpaw-spin-nested-loading > .qwenpaw-spin-container { height:100%; min-height:0; }
    .anw-workbench-main { min-width:0; min-height:0; overflow:hidden; }

    .anw-modal .qwenpaw-modal-content { overflow:hidden; border-radius:18px; }
    .anw-modal .qwenpaw-modal-header { padding:20px 22px 14px; border-bottom:1px solid var(--anw-line); }
    .anw-modal .qwenpaw-modal-title { color:var(--anw-ink); font-size:18px; }
    .anw-modal .qwenpaw-modal-body { color:var(--anw-text); background:#fff; }
    .anw-modal .qwenpaw-modal-footer { padding:14px 20px 18px; border-top:1px solid var(--anw-line); }

    @media (max-width: 980px) {
      .anw-library-grid { grid-template-columns:1fr; }
      .anw-project { grid-template-columns:220px minmax(0,1fr); padding:14px; }
      .anw-entity-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    }

    @media (max-width: 720px) {
      .anw-page { padding:18px 14px 90px; }
      .anw-page-header { align-items:center; }
      .anw-page-title { font-size:23px; }
      .anw-page-subtitle { display:none; }
      .anw-quick-nav { width:100%; overflow-x:auto; }
      .anw-quick-item { flex:1 0 auto; justify-content:center; }
      .anw-library-grid { gap:14px; }
      .anw-novel-hero { grid-template-columns:84px minmax(0,1fr); gap:14px; min-height:0; padding:14px; }
      .anw-cover,.anw-cover-fallback { width:84px; height:116px; border-radius:9px; }
      .anw-novel-title { font-size:17px; }
      .anw-latest { margin-top:12px; }
      .anw-novel-tools { padding-inline:10px; }
      .anw-start { padding-inline:12px; }

      .anw-project { display:block; padding:0 0 72px; overflow:auto; }
      .anw-book-rail { position:static; border:0; border-radius:0; box-shadow:none; }
      .anw-book-rail-top { display:grid; grid-template-columns:84px minmax(0,1fr); gap:14px; padding:16px; background:linear-gradient(135deg,#eefbff,#fff4ed); }
      .anw-book-cover-large,.anw-book-cover-empty { grid-row:1/4; width:84px; height:116px; aspect-ratio:auto; border-radius:9px; }
      .anw-book-title { margin:2px 0 4px; font-size:18px; }
      .anw-book-description { max-height:38px; overflow:hidden; }
      .anw-book-counts { margin-top:4px; }
      .anw-project-nav { position:sticky; z-index:8; top:0; display:flex; gap:0; overflow-x:auto; padding:0; border-bottom:1px solid var(--anw-line); background:#fff; }
      .anw-project-nav-button { flex:1 0 auto; justify-content:center; min-height:48px; border:0; border-bottom:2px solid transparent; border-radius:0; padding:0 14px; background:#fff; }
      .anw-project-nav-button.is-active { border-bottom-color:var(--anw-orange); background:#fff; }
      .anw-project-nav-button .anw-nav-label { display:block; }
      .anw-project-main { min-height:520px; border:0; border-radius:0; box-shadow:none; }
      .anw-panel-header { min-height:64px; padding:14px 16px; }
      .anw-panel-title { font-size:18px; }
      .anw-panel-body { padding:14px; }
      .anw-panel-actions .qwenpaw-btn:not(.anw-primary-button) { display:none; }
      .anw-chapter-row { grid-template-columns:minmax(0,1fr) auto; }
      .anw-chapter-number { display:none; }
      .anw-chapter-row-meta:last-child { display:none; }
      .anw-entity-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .anw-volume-overview { grid-template-columns:1fr; }
      .anw-clue-card { grid-template-columns:58px minmax(0,1fr); }
      .anw-clue-state { grid-column:2; }

      .anw-editor-topbar { margin:0; border:0; border-bottom:1px solid var(--anw-line); border-radius:0; box-shadow:none; }
      .anw-editor-crumb { display:none; }
      .anw-editor-scroll { padding:0 0 112px; }
      .anw-editor-paper { min-height:100%; border:0; border-radius:0; padding:24px 20px 48px; box-shadow:none; }
      .anw-editor-title { font-size:22px; }
      .anw-editor-textarea { min-height:calc(100vh - 230px); font-size:16px; line-height:1.95; }
      .anw-editor-footer { right:12px; bottom:10px; left:12px; overflow-x:auto; justify-content:flex-start; }
      .anw-workflow-buttons { flex-wrap:nowrap; justify-content:flex-start; padding:7px; }
      .anw-workflow-buttons .qwenpaw-btn { flex:0 0 auto; }
    }
  `;
  document.head.appendChild(style);
}
