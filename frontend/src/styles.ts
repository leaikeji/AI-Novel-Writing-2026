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
      --anw-scrollbar-track: #f1f2f3;
      --anw-scrollbar-thumb: #919499;
      --anw-scrollbar-thumb-hover: #777b81;
    }

    .anw-app,
    .anw-app * { box-sizing: border-box; }

    .anw-app {
      min-height: 100%;
      color: var(--anw-text);
      background: var(--anw-canvas);
      color-scheme: light;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }

    /* Keep every app-owned scrolling surface visually consistent without touching QwenPaw's shell. */
    .anw-app,
    .anw-app *,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal * {
      color-scheme: light;
      scrollbar-color: var(--anw-scrollbar-thumb) var(--anw-scrollbar-track);
      scrollbar-width: thin;
    }

    .anw-app::-webkit-scrollbar,
    .anw-app *::-webkit-scrollbar,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal::-webkit-scrollbar,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal *::-webkit-scrollbar {
      width: 8px;
      height: 8px;
    }

    .anw-app::-webkit-scrollbar-track,
    .anw-app *::-webkit-scrollbar-track,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal::-webkit-scrollbar-track,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal *::-webkit-scrollbar-track {
      border-radius: 999px;
      background: var(--anw-scrollbar-track);
    }

    .anw-app::-webkit-scrollbar-thumb,
    .anw-app *::-webkit-scrollbar-thumb,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal::-webkit-scrollbar-thumb,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal *::-webkit-scrollbar-thumb {
      min-width: 42px;
      min-height: 42px;
      border: 0;
      border-radius: 999px;
      background: var(--anw-scrollbar-thumb);
    }

    .anw-app::-webkit-scrollbar-thumb:hover,
    .anw-app *::-webkit-scrollbar-thumb:hover,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal::-webkit-scrollbar-thumb:hover,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal *::-webkit-scrollbar-thumb:hover {
      background: var(--anw-scrollbar-thumb-hover);
    }

    .anw-app::-webkit-scrollbar-corner,
    .anw-app *::-webkit-scrollbar-corner,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal::-webkit-scrollbar-corner,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal *::-webkit-scrollbar-corner {
      background: transparent;
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
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      height: 100%;
      min-height: 0;
      overflow: hidden;
      color: var(--anw-text);
      background: var(--anw-canvas);
    }
    .anw-editor.has-chapter-tree { grid-template-columns:var(--anw-chapter-tree-width,270px) minmax(0,1fr); }
    .anw-editor.has-chapter-tree.is-chapter-tree-collapsed { grid-template-columns:54px minmax(0,1fr); }
    .anw-editor-content { --anw-editor-inline-gutter:24px; min-width:0; min-height:0; height:100%; overflow:auto; container-type:inline-size; }
    .anw-chapter-tree {
      display:flex;
      min-width:0;
      min-height:0;
      flex-direction:column;
      align-self:stretch;
      margin:14px 0 14px 14px;
      overflow:hidden;
      border:1px solid var(--anw-line);
      border-radius:15px;
      color:#373b42;
      background:#fff;
      box-shadow:var(--anw-shadow-soft);
    }
    .anw-chapter-tree.is-collapsed { align-items:center; padding-top:10px; }
    .anw-chapter-tree-header { display:flex; min-height:64px; flex:0 0 auto; align-items:center; justify-content:space-between; gap:10px; border-bottom:1px solid #f0f1f3; padding:12px 12px 12px 18px; }
    .anw-chapter-tree-header h2 { margin:0; color:#202329; font-size:17px; font-weight:760; line-height:1.35; }
    .anw-chapter-tree-controls { display:flex; align-items:center; gap:8px; }
    html body .anw-app .anw-chapter-tree-icon-button.qwenpaw-btn,
    html body .anw-app .anw-chapter-tree-restore.qwenpaw-btn { display:grid; width:32px; min-width:32px; height:32px; place-items:center; border:0!important; border-radius:7px; padding:0!important; color:#626871!important; background:#f7f8fa!important; box-shadow:none!important; }
    html body .anw-app .anw-chapter-tree-icon-button.qwenpaw-btn:hover,
    html body .anw-app .anw-chapter-tree-icon-button.qwenpaw-btn.is-active,
    html body .anw-app .anw-chapter-tree-restore.qwenpaw-btn:hover { color:#ef7046!important; background:#fff1eb!important; }
    .anw-chapter-tree-search { flex:0 0 auto; border-bottom:1px solid #f0f1f3; padding:10px 12px; }
    .anw-chapter-tree-search .qwenpaw-input-affix-wrapper { min-height:38px; border-color:#e6e8eb!important; border-radius:8px; background:#fafbfc!important; box-shadow:none!important; }
    .anw-chapter-tree-search .qwenpaw-input-affix-wrapper-focused { border-color:#ff9a75!important; box-shadow:0 0 0 2px rgba(255,112,67,.09)!important; }
    .anw-chapter-tree-book-title { flex:0 0 auto; overflow:hidden; padding:16px 18px 10px; color:#2b2f35; font-size:14px; font-weight:720; text-overflow:ellipsis; white-space:nowrap; }
    .anw-chapter-tree-nav { min-height:0; flex:1; overflow:auto; padding:2px 8px 18px; }
    .anw-chapter-tree-volume { margin:0 0 3px; }
    .anw-chapter-tree-volume-toggle { display:grid; width:100%; min-height:38px; grid-template-columns:15px minmax(0,1fr) auto; align-items:center; gap:7px; border:0; border-radius:7px; padding:7px 8px; color:#353940; background:transparent; cursor:pointer; text-align:left; }
    .anw-chapter-tree-volume-toggle:hover { background:#f7f8fa; }
    .anw-chapter-tree-volume-toggle > .qwenpawicon { color:#6d727a; font-size:10px; }
    .anw-chapter-tree-volume-toggle strong { min-width:0; overflow:hidden; font-size:13px; font-weight:720; text-overflow:ellipsis; white-space:nowrap; }
    .anw-chapter-tree-volume-toggle span:last-child { color:#a0a4ab; font-size:11px; font-weight:500; white-space:nowrap; }
    .anw-chapter-tree-chapters { display:grid; gap:2px; margin:1px 0 7px; }
    .anw-chapter-tree-chapter { position:relative; display:grid; width:100%; min-height:40px; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:7px; overflow:hidden; border:0; border-radius:7px; padding:8px 8px 8px 30px; color:#50555d; background:transparent; cursor:pointer; text-align:left; }
    .anw-chapter-tree-chapter:hover { color:#2d3137; background:#f7f8fa; }
    .anw-chapter-tree-chapter.is-active { color:#ef673b; background:#fff0e9; font-weight:700; }
    .anw-chapter-tree-chapter.is-active::before { position:absolute; top:5px; bottom:5px; left:0; width:3px; border-radius:0 3px 3px 0; background:#ff7043; content:""; }
    .anw-chapter-tree-chapter > span { min-width:0; overflow:hidden; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
    .anw-chapter-tree-chapter > small { color:#a0a4ab; font-size:10px; font-weight:500; white-space:nowrap; }
    .anw-chapter-tree-chapter.is-active > small { color:#ba8a78; }
    .anw-chapter-tree-empty { display:grid; min-height:180px; place-items:center; padding:24px 12px; color:#a0a4ab; font-size:12px; text-align:center; }
    .anw-editor.has-chapter-tree .anw-editor-topbar { width:min(1000px,calc(100% - 48px)); transform:none; }
    .anw-editor.has-chapter-tree .anw-editor-scroll { padding-right:var(--anw-editor-inline-gutter); padding-left:var(--anw-editor-inline-gutter); }
    .anw-editor-topbar {
      display: flex;
      width: min(1000px, calc(100% - 196px));
      align-items: center;
      align-self: center;
      gap: 12px;
      min-height: 64px;
      margin: 14px auto 0;
      transform: translateX(20px);
      padding: 10px 16px;
      border: 1px solid var(--anw-line);
      border-radius: 15px;
      background: #fff;
      box-shadow: var(--anw-shadow-soft);
    }
    .anw-save-state { border-radius:999px; padding:5px 9px; color:#407464; background:#eaf8f2; font-size:12px; white-space:nowrap; }
    .anw-save-state.is-error { color:#b43c2a; background:#fff0ec; }
    .anw-editor-topbar .anw-delete-button { margin-left:0; color:#ee774c!important; border-color:#ffebd8!important; background:#fff5e8!important; }
    .anw-current-model-inline { display:flex; min-width:0; max-width:190px; align-items:center; margin-left:auto; overflow:hidden; color:#30343a; line-height:1.2; }
    .anw-current-model-inline strong { overflow:hidden; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }

    /* Keep these queries anonymous: the inline CSS compactor removes the
       required separator between a named container and its condition. */
    @container (max-width:840px) {
      .anw-current-model-inline { display:none; }
      .anw-editor-topbar .anw-delete-button { margin-left:auto; }
    }
    @container (max-width:420px) {
      .anw-editor-topbar { gap:6px; padding-right:8px; padding-left:8px; }
      .anw-editor-topbar > .qwenpaw-btn { padding-right:8px!important; padding-left:8px!important; }
    }

    .anw-editor-scroll { position:relative; display:grid; width:100%; min-height:auto; grid-template-columns:minmax(0,1000px); align-items:start; justify-content:center; overflow:visible; padding:14px var(--anw-editor-inline-gutter); }
    .anw-editor-paper { display:flex; width:100%; min-width:0; min-height:calc(100vh - 220px); grid-column:1; flex-direction:column; margin:0; border:1px solid var(--anw-line); border-radius:18px; padding:36px 40px 38px; background:#fff; box-shadow:var(--anw-shadow); }
    .anw-editor-title-row { display:flex; flex-wrap:wrap; align-items:flex-start; gap:16px; padding-bottom:20px; border-bottom:1px solid var(--anw-line); }
    .anw-editor-title-row > :first-child { min-width:0; flex:1 1 260px; }
    .anw-editor-title { margin:0 0 8px; color:var(--anw-ink); font-size:27px; }
    .anw-editor-count { color:var(--anw-muted); font-size:13px; }
    .anw-editor-count strong { color:var(--anw-orange-strong); }
    .anw-editor-title-actions { display:flex; flex:0 0 auto; align-items:center; justify-content:flex-end; gap:8px; margin-left:auto; }
    .anw-chapter-title-tools,.anw-chapter-title-tool-buttons { display:flex; align-items:center; gap:8px; }
    .anw-chapter-title-tools:empty { display:none; }
    html body .anw-app .anw-chapter-title-tool.qwenpaw-btn { height:36px; min-width:0; border:1px solid #ffd6c7!important; border-radius:8px; padding:0 11px!important; color:#e9653b!important; background:#fff7f2!important; box-shadow:none!important; font-size:13px; font-weight:680; }
    html body .anw-app .anw-chapter-title-tool.qwenpaw-btn:hover { border-color:#ef7044!important; color:#dc572f!important; background:#fff0e9!important; }
    html body .anw-app .anw-chapter-title-tool.qwenpaw-btn:focus-visible { outline:3px solid rgba(255,112,67,.2); outline-offset:2px; }
    html .anw-editor-title-row .anw-title-edit-button.qwenpaw-btn { display:grid; width:36px; min-width:36px; height:36px; place-items:center; border-radius:8px; padding:0!important; color:#7f8590!important; }
    html .anw-editor-title-row .anw-title-edit-button.qwenpaw-btn:hover { color:#ef7044!important; background:#fff3ed!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .qwenpaw-modal-content { overflow:hidden!important; border-radius:20px!important; padding:0!important; box-shadow:0 24px 70px rgba(0,0,0,.28)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .qwenpaw-modal-header { margin:0!important; border:0!important; padding:34px 28px 22px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .qwenpaw-modal-title { color:#202124!important; font-size:22px!important; font-weight:780!important; line-height:1.35!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .qwenpaw-modal-body { padding:0 28px 28px!important; }
    .anw-title-edit-form { display:grid; gap:0; }
    .anw-title-edit-form > label { margin-bottom:11px; color:#34363a; font-size:16px; font-weight:720; line-height:1.4; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .anw-title-edit-form > .qwenpaw-input { height:48px; border:2px solid #dedfe1!important; border-radius:10px!important; padding:0 16px!important; color:#25272b!important; background:#fff!important; box-shadow:none!important; font-size:17px; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .anw-title-edit-form > .qwenpaw-input:focus { border-color:#ff8258!important; box-shadow:0 0 0 3px rgba(255,112,67,.1)!important; }
    .anw-title-edit-count { margin:8px 0 0; color:#a1a3a7; font-size:13px; font-weight:600; line-height:1.5; }
    .anw-title-edit-actions { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:27px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .anw-title-edit-actions > .qwenpaw-btn { width:100%; height:52px; margin:0!important; border-radius:10px!important; font-size:16px; font-weight:720; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .anw-title-edit-cancel.qwenpaw-btn { color:#64666a!important; border:1px solid #dedfe1!important; background:#fff!important; box-shadow:none!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .anw-title-edit-save.qwenpaw-btn { border:0!important; color:#fff!important; background:linear-gradient(100deg,#ff6b38,#ff8254)!important; box-shadow:0 9px 20px rgba(255,105,56,.24)!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-title-edit-modal .anw-title-edit-save.qwenpaw-btn:disabled { color:#fff!important; background:#dedfe1!important; box-shadow:none!important; }
    .anw-editor-textarea {
      width:100%;
      min-height:560px;
      flex:none;
      overflow:hidden;
      resize:none;
      border:0;
      border-radius:10px;
      outline:0;
      margin-top:24px;
      padding:20px;
      color:#30343b;
      background:#fafafa;
      font:17px/2 ui-serif, "Songti SC", STSong, serif;
    }
    .anw-editor-empty { display:flex; min-height:500px; flex:1; flex-direction:column; align-items:center; justify-content:center; padding:48px 24px 24px; color:#9a9ea6; text-align:center; }
    .anw-editor-empty-icon { display:flex; width:72px; height:72px; align-items:center; justify-content:center; margin-bottom:18px; border-radius:50%; color:#ef7950; background:#fff4ee; font-size:31px; }
    .anw-editor-empty strong { color:#4f535a; font-size:19px; }
    .anw-editor-empty p { margin:8px 0 22px; font-size:13px; }
    .anw-editor-empty .anw-editor-empty-generate.qwenpaw-btn { min-width:164px; height:42px; border-radius:8px; color:#fff!important; border-color:#ef7046!important; background:#ef7046!important; font-weight:700; box-shadow:0 8px 18px rgba(239,112,70,.2); }
    .anw-editor-direct-link { margin-top:12px; border:0; padding:4px 8px; color:#ef7046; background:transparent; cursor:pointer; font-size:12px; }
    .anw-editor-direct-link:hover { text-decoration:underline; }
    .anw-editor-generating { display:flex; min-height:500px; flex:1; flex-direction:column; align-items:center; justify-content:center; padding:48px 24px 24px; color:#888d95; text-align:center; }
    .anw-editor-generating strong { margin-top:22px; color:#4b4f56; font-size:18px; }
    .anw-editor-generating p { margin:10px 0 5px; color:#6f747d; }
    .anw-editor-generating span { font-size:13px; }
    .anw-editor-generating small { margin-top:18px; border-radius:999px; padding:6px 13px; color:#ef7046; background:#fff2ec; }
    .anw-editor-footer {
      display:flex;
      width:100%;
      align-items:center;
      justify-content:center;
      gap:10px;
      margin:32px 0 0;
      border-top:1px solid var(--anw-line);
      padding-top:24px;
    }

    .anw-workflow-buttons { width:100%; border:0; padding:0; background:transparent; box-shadow:none; }
    .anw-workflow-panel { display:grid; width:100%; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }
    .anw-workflow-buttons .anw-workflow-panel > .qwenpaw-btn { width:100%; height:52px; border-radius:9px; font-size:15px; font-weight:700; box-shadow:0 8px 18px rgba(20,28,43,.08); }
    .anw-app .anw-workflow-panel > .qwenpaw-btn.anw-generate-button { color:#fff!important; border-color:#ff7b4e!important; background:linear-gradient(90deg,#ff7042,#ff8d5d)!important; }
    .anw-app .anw-workflow-panel > .qwenpaw-btn.anw-outline-button { color:#4d5158!important; border-color:#d9dcdf!important; background:#fff!important; }
    .anw-app .anw-workflow-panel > .qwenpaw-btn.anw-sync-button { color:#fff!important; border-color:#10b77a!important; background:#10b77a!important; }
    .anw-app .anw-workflow-panel > .qwenpaw-btn.anw-sync-button:disabled { color:#9aa09f!important; border-color:#dfe5e2!important; background:#eef3f1!important; }
    .anw-app .anw-workflow-panel > .qwenpaw-btn.anw-history-button { color:#4d5158!important; border-color:#d9dcdf!important; background:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-save-volume-modal .qwenpaw-modal-body { padding:10px 26px 28px!important; }
    .anw-save-volume-body { display:grid; gap:18px; }
    .anw-save-volume-body > p { margin:0; color:#858991; line-height:1.7; }
    .anw-save-volume-list { display:grid; gap:12px; }
    .anw-save-volume-list > button:not(.qwenpaw-btn) { display:flex; width:100%; min-height:56px; align-items:center; justify-content:space-between; border:1px solid #e4e6e9; border-radius:9px; padding:0 16px; color:#373b42; background:#fff; cursor:pointer; }
    .anw-save-volume-list > button:not(.qwenpaw-btn):hover { border-color:#ff8b63; background:#fff9f6; box-shadow:0 4px 14px rgba(255,116,72,.08); }
    .anw-save-volume-list > button:not(.qwenpaw-btn) span { color:#9a9ea5; font-size:12px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-save-volume-modal .anw-save-volume-list > .qwenpaw-btn { height:50px; border:0!important; color:#666b72!important; background:#f6f6f7!important; box-shadow:none!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-save-volume-modal .anw-save-volume-list > .anw-save-and-next-button.qwenpaw-btn { min-height:44px; color:#ef7046!important; border:1px solid #ffd3c2!important; border-radius:9px!important; background:#fff7f2!important; font-weight:650; }
    .anw-save-confirm-copy { display:grid; gap:6px; color:#72767e; line-height:1.65; }
    .anw-save-confirm-copy strong { color:#3c4046; }
    .anw-save-confirm-copy p { margin:0; }
    .anw-save-confirm-copy b { margin-top:6px; color:#34373c; }

    .anw-workbench-frame { --anw-chapter-tree-width:270px; --mb-workbench-rail-width:clamp(260px,19vw,320px); --mb-workbench-main-min:640px; --mb-workbench-gap:clamp(18px,1.5vw,28px); --mb-workbench-padding:24px; --mb-panel-body-padding:24px 28px 44px; position:relative; isolation:isolate; display:flex; width:100%; height:100%; min-height:0; overflow:hidden; background:var(--anw-canvas); }
    .anw-workbench-frame[data-assistant-density="comfortable"] { --anw-chapter-tree-width:286px; }
    .anw-workbench-frame[data-assistant-density="compact"] { --anw-chapter-tree-width:240px; --mb-workbench-rail-width:260px; --mb-workbench-main-min:0px; --mb-workbench-gap:18px; --mb-workbench-padding:18px; }
    .anw-workbench-frame[data-assistant-density="constrained"] { --anw-chapter-tree-width:220px; --mb-workbench-rail-width:220px; --mb-workbench-main-min:0px; --mb-workbench-gap:12px; --mb-workbench-padding:12px; --mb-panel-body-padding:16px 16px 32px; }
    .anw-workbench-main > .qwenpaw-spin-nested-loading,
    .anw-workbench-main > .qwenpaw-spin-nested-loading > .qwenpaw-spin-container { height:100%; min-height:0; }
    .anw-workbench-main { min-width:0; min-height:0; flex:1 1 auto; overflow:hidden; container-type:inline-size; }
    .anw-assistant-pane { position:relative; min-height:0; flex:0 0 auto; color:#30343a; background:#fff; box-shadow:-8px 0 24px rgba(25,31,41,.04); }
    .anw-assistant-pane.is-overlay { box-shadow:-14px 0 36px rgba(25,31,41,.18); }
    .anw-assistant-pane-separator::after { position:absolute; top:50%; left:2px; width:2px; height:64px; transform:translateY(-50%); border-radius:999px; background:#d7d9de; content:""; transition:height .15s ease,background .15s ease; }
    .anw-assistant-pane-separator:hover::after,.anw-assistant-pane-separator:focus-visible::after { height:92px; background:#ff835c; }
    .anw-assistant-pane-separator:focus-visible { outline:2px solid rgba(255,112,67,.25); outline-offset:-2px; }
    .anw-assistant-pane-toggle { color:#5f646d; transition:color .15s ease,border-color .15s ease,background .15s ease; }
    .anw-assistant-pane-toggle:hover,.anw-assistant-pane-toggle:focus-visible { color:#ef7046; border-color:#ffb69c!important; background:#fff5f0!important; outline:0; }
    .anw-assistant-pane-inner { position:relative; box-sizing:border-box; min-height:0; height:100%; }
    .anw-assistant-pane-inner.has-status-bar { padding-top:88px; }
    .anw-assistant-pane-inner > :first-child { min-height:0; height:100%; }
    .anw-assistant-context-status-slot { position:absolute; z-index:4; top:0; right:0; left:0; box-sizing:border-box; height:88px; border-bottom:1px solid #eceef1; padding-right:54px; background:rgba(255,255,255,.98); }
    .anw-assistant-context-status { display:grid; height:100%; align-content:center; gap:4px; overflow:hidden; padding:9px 48px 9px 14px; color:#6d727a; }
    .anw-assistant-context-status-main { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:8px; }
    .anw-assistant-context-status-main strong { min-width:0; overflow:hidden; color:#2f3339; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
    .anw-assistant-context-status-main span { flex:0 0 auto; color:#27745b; font-size:10px; white-space:nowrap; }
    .anw-assistant-context-status.is-unsupported .anw-assistant-context-status-main span { color:#a35e1c; }
    .anw-assistant-context-status-meta { display:flex; min-width:0; align-items:center; gap:7px; overflow:hidden; font-size:10px; white-space:nowrap; }
    .anw-assistant-context-status-meta span { border-radius:999px; padding:2px 6px; color:#666b73; background:#f3f4f6; }
    .anw-assistant-context-status small { overflow:hidden; color:#9a9ea5; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }
    .anw-assistant-pane.is-collapsed { box-shadow:-3px 0 10px rgba(25,31,41,.03); }
    .anw-assistant-selection-toolbar { position:fixed; z-index:1200; display:grid; box-sizing:border-box; width:max-content; max-width:calc(100vw - 16px); overflow:hidden; border:1px solid rgba(255,112,67,.22); border-radius:14px; color:#30343a; background:rgba(255,255,255,.98); box-shadow:0 14px 42px rgba(25,31,41,.2),0 2px 8px rgba(255,112,67,.12); backdrop-filter:blur(12px); }
    .anw-assistant-selection-actions { display:flex; max-width:100%; align-items:center; gap:4px; overflow-x:auto; padding:6px; scrollbar-color:#c7c9ce transparent; scrollbar-width:thin; }
    .anw-assistant-selection-actions button { display:inline-flex; min-width:40px; min-height:40px; flex:0 0 auto; align-items:center; justify-content:center; border:0; border-radius:10px; padding:0 11px; color:#51565f; background:transparent; font:inherit; font-size:12px; font-weight:700; cursor:pointer; transition:color .15s ease,background .15s ease,box-shadow .15s ease; }
    .anw-assistant-selection-actions button:hover,.anw-assistant-selection-actions button:focus-visible,.anw-assistant-selection-actions button.is-active { color:#e95f34; background:#fff1eb; outline:0; box-shadow:inset 0 0 0 1px rgba(255,112,67,.22); }
    .anw-assistant-selection-actions button:disabled { color:#a6aab1; cursor:wait; background:#f5f5f6; box-shadow:none; }
    .anw-assistant-selection-actions .anw-assistant-selection-close { min-width:40px; padding:0; color:#8c9199; font-size:20px; font-weight:500; }
    .anw-assistant-selection-status { display:flex; min-width:0; align-items:center; gap:8px; overflow:hidden; border-top:1px solid #f0f1f3; padding:6px 10px 7px; color:#80858d; background:#fbfbfc; font-size:10px; white-space:nowrap; }
    .anw-assistant-selection-status strong { max-width:110px; overflow:hidden; color:#444950; text-overflow:ellipsis; }
    .anw-assistant-selection-status span:last-child { min-width:0; overflow:hidden; text-overflow:ellipsis; }
    .anw-assistant-selection-toolbar.is-failed { border-color:#efb6ad; }
    .anw-assistant-selection-toolbar.is-failed .anw-assistant-selection-status { color:#b42318; background:#fff7f6; }
    .anw-assistant-selection-custom { display:grid; gap:8px; width:min(430px,calc(100vw - 32px)); border-top:1px solid #f0f1f3; padding:10px; background:#fff; }
    .anw-assistant-selection-custom > label { color:#3e434b; font-size:12px; font-weight:750; }
    .anw-assistant-selection-custom > textarea { width:100%; min-height:68px; resize:vertical; border:1px solid #dfe2e6; border-radius:9px; padding:9px 11px; color:#34383f; background:#fff; font-size:12px; line-height:1.6; }
    .anw-assistant-selection-custom > textarea:focus { border-color:var(--anw-orange); outline:0; box-shadow:0 0 0 3px rgba(255,112,67,.11); }
    .anw-assistant-selection-custom-actions { display:flex; align-items:center; justify-content:flex-end; gap:7px; }
    .anw-assistant-selection-custom-actions > span { margin-right:auto; color:#999da5; font-size:10px; }
    .anw-assistant-selection-custom-actions > button { min-height:32px; border:1px solid #e2e4e8; border-radius:8px; padding:0 12px; color:#5e646e; background:#fff; cursor:pointer; font-size:11px; font-weight:700; }
    .anw-assistant-selection-custom-actions > button[type="submit"] { border-color:#ff7043; color:#fff; background:#ff7043; box-shadow:0 4px 10px rgba(255,112,67,.18); }
    .anw-assistant-selection-custom-actions > button:disabled { cursor:not-allowed; opacity:.48; box-shadow:none; }
    html .qwenpaw-modal-root .qwenpaw-modal-wrap.anw-assistant-aware-modal-wrap { pointer-events:none; }
    html .qwenpaw-modal-root .qwenpaw-modal-wrap.anw-assistant-aware-modal-wrap > .qwenpaw-modal { pointer-events:auto; }
    .anw-selection-edit-host { width:100%; min-width:0; }
    .anw-selection-edit-host.is-reviewing { display:block; min-height:220px; }
    .anw-selection-edit-host.is-reviewing > :not(.anw-selection-edit-review) { display:none!important; }
    .anw-editor-selection-review-host.is-reviewing { min-height:clamp(520px,calc(100vh - 300px),1080px); }
    .anw-selection-edit-review { display:grid; width:100%; min-width:0; align-content:start; overflow:visible; border:1px solid #e7e9ed; border-radius:12px; color:#34383f; background:#fff; box-shadow:0 5px 20px rgba(29,35,46,.06); }
    .anw-selection-edit-review > header { grid-row:2; display:grid; gap:5px; border-bottom:1px solid #eceef1; padding:18px 20px 15px; }
    .anw-selection-edit-review h2 { margin:0!important; color:#24282f!important; font-size:19px; font-weight:780; line-height:1.3; }
    .anw-selection-edit-review > header > p { margin:0; color:#858a92; font-size:12px; line-height:1.6; }
    .anw-selection-edit-review-toolbar { position:sticky; z-index:5; top:0; grid-row:1; display:flex; min-height:58px; flex-wrap:wrap; align-items:center; gap:8px; border-bottom:1px solid #e9ebee; padding:9px 14px; background:rgba(255,255,255,.97); box-shadow:0 3px 10px rgba(29,35,46,.04); backdrop-filter:blur(10px); }
    .anw-selection-edit-review-toolbar > span { margin-right:auto; color:#ff6738; font-size:12px; font-weight:760; white-space:nowrap; }
    .anw-selection-edit-review button { min-height:36px; border:1px solid #dfe2e6; border-radius:7px; padding:0 13px; color:#565c65; background:#fff; cursor:pointer; font:inherit; font-size:12px; font-weight:720; transition:border-color .15s ease,color .15s ease,background .15s ease,box-shadow .15s ease; }
    .anw-selection-edit-review button:hover,.anw-selection-edit-review button:focus-visible { border-color:#ff8d68; color:#e95e31; outline:0; box-shadow:0 0 0 3px rgba(255,112,67,.1); }
    .anw-selection-edit-review button:disabled { color:#a7abb2; border-color:#eceef1; cursor:not-allowed; background:#f6f7f8; box-shadow:none; }
    .anw-selection-edit-review-toolbar > button:nth-last-child(2) { border-color:#ff7043; color:#fff; background:#ff7043; box-shadow:0 5px 13px rgba(255,112,67,.2); }
    .anw-selection-edit-review-toolbar > button:nth-last-child(3) { border-color:#ffb197; color:#ef673c; background:#fff8f4; }
    .anw-selection-edit-review-toolbar > button:disabled { border-color:#eceef1; color:#a7abb2; background:#f6f7f8; box-shadow:none; }
    .anw-selection-edit-review-warnings { display:grid; gap:4px; margin:7px 0 0; border:1px solid #f1d9a8; border-radius:8px; padding:8px 10px 8px 27px; color:#986719; background:#fff9e9; font-size:11px; line-height:1.55; }
    .anw-selection-edit-review-diff { grid-row:3; margin:0; padding:0; list-style:none; background:#fff; }
    .anw-selection-edit-review-diff > li { min-width:0; overflow-wrap:anywhere; }
    .anw-selection-edit-review-context { display:block; padding:16px 20px; color:#3d424a; font-size:14px; line-height:1.9; white-space:pre-wrap; }
    .anw-selection-edit-review-change { display:grid; border-block:1px solid #ebecef; background:#fff; scroll-margin-top:72px; }
    .anw-selection-edit-review-change + .anw-selection-edit-review-change { border-top:0; }
    .anw-selection-edit-review-change.is-current { position:relative; box-shadow:inset 4px 0 #ff7548; }
    .anw-selection-edit-review-delete,.anw-selection-edit-review-insert { display:grid; min-height:52px; grid-template-columns:22px 48px minmax(0,1fr); align-items:start; gap:7px; padding:13px 20px; font-size:14px; line-height:1.85; white-space:pre-wrap; }
    .anw-selection-edit-review-delete { color:#8b433d; background:#fff1ef; }
    .anw-selection-edit-review-insert { color:#276e50; background:#eef9f3; }
    .anw-selection-edit-review-delete > span:first-child,.anw-selection-edit-review-insert > span:first-child { font-size:18px; font-weight:850; line-height:1.4; }
    .anw-selection-edit-review-delete > strong,.anw-selection-edit-review-insert > strong { font-size:11px; font-weight:800; line-height:2.5; }
    .anw-selection-edit-review-change-actions { display:flex; justify-content:flex-end; gap:8px; border-top:1px solid rgba(0,0,0,.045); padding:8px 20px 10px; background:#fff; }
    .anw-selection-edit-review-change-actions button[aria-pressed="true"] { border-color:#ff7043; color:#fff; background:#ff7043; }
    .anw-selection-edit-review-change.is-accept { box-shadow:inset 4px 0 #2e9f6d; }
    .anw-selection-edit-review-change.is-reject { opacity:.72; box-shadow:inset 4px 0 #9ba0a8; }
    .anw-selection-edit-review-decision-label { margin:0; border-top:1px solid #eceef1; padding:8px 20px; color:#737981; background:#fafbfc; font-size:11px; text-align:right; }
    .anw-selection-edit-review-empty-result { margin:0; padding:8px 20px; color:#8e5550; background:#fff7f6; font-size:11px; }
    .anw-selection-edit-review-footer { position:sticky; z-index:4; bottom:0; grid-row:4; display:flex; min-height:40px; align-items:center; justify-content:flex-end; gap:20px; border-top:1px solid #e8eaed; padding:8px 16px; color:#878c94; background:rgba(255,255,255,.97); font-size:11px; backdrop-filter:blur(10px); }
    .anw-selection-edit-review-live { position:absolute!important; width:1px!important; height:1px!important; margin:-1px!important; overflow:hidden!important; clip:rect(0 0 0 0)!important; white-space:nowrap!important; }
    .anw-selection-edit-review-original { max-height:none; margin:0; overflow:visible; border:1px solid #e8eaed; border-radius:9px; padding:16px; color:#4f555e; background:#fafbfc; font:13px/1.8 ui-monospace,SFMono-Regular,Menlo,monospace; white-space:pre-wrap; overflow-wrap:anywhere; }
    .anw-selection-edit-review.is-preparing,.anw-selection-edit-review.is-generating,.anw-selection-edit-review.is-failed,.anw-selection-edit-review.is-conflict,.anw-selection-edit-review.is-applied { gap:16px; min-height:260px; align-content:center; padding:28px; }
    .anw-selection-edit-review.is-preparing > h2,.anw-selection-edit-review.is-generating > h2,.anw-selection-edit-review.is-failed > h2,.anw-selection-edit-review.is-conflict > h2,.anw-selection-edit-review.is-applied > h2 { text-align:center; }
    .anw-selection-edit-review-status-actions { display:flex; flex-wrap:wrap; justify-content:center; gap:9px; }
    .anw-selection-edit-review-status-actions > button:last-child { border-color:#ff7043; color:#fff; background:#ff7043; }
    .anw-selection-edit-review-error { margin:0; color:#b0473b; line-height:1.7; text-align:center; }
    .anw-selection-edit-review-empty { grid-row:3; min-height:180px; padding:70px 20px; color:#7c828b; text-align:center; }
    .anw-selection-edit-review.is-compact { border-radius:10px; }
    .anw-selection-edit-review.is-compact .anw-selection-edit-review-context { padding:11px 14px; font-size:13px; }
    .anw-selection-edit-review.is-compact .anw-selection-edit-review-delete,.anw-selection-edit-review.is-compact .anw-selection-edit-review-insert { min-height:44px; padding:10px 14px; font-size:13px; }
    html .qwenpaw-modal-root .qwenpaw-modal:has(.anw-outline-selection-review-host.is-reviewing) .qwenpaw-modal-footer,
    html .qwenpaw-modal-root .qwenpaw-modal:has(.mb-relationship-selection-review-host.is-reviewing) .qwenpaw-modal-footer { display:none!important; }
    .anw-assistant-review-editor { display:grid; box-sizing:border-box; width:100%; min-width:0; gap:0; overflow:hidden; border-block:1px solid #383b41; color:#e4e6e9; background:#17191c; box-shadow:none; }
    .anw-assistant-review-editor > header { display:flex; min-width:0; min-height:44px; align-items:center; justify-content:space-between; gap:10px; border-bottom:1px solid #34373d; padding:7px 10px; background:#202226; }
    .anw-assistant-review-editor > header > div { display:grid; min-width:0; gap:1px; }
    .anw-assistant-review-editor > header strong { overflow:hidden; color:#f0f1f2; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
    .anw-assistant-review-editor > header span { overflow:hidden; color:#969ba4; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }
    .anw-assistant-review-editor > header > span { flex:0 0 auto; color:#ff9a76; font-size:10px; font-weight:700; }
    .anw-assistant-review-text { box-sizing:border-box; width:100%; min-height:180px; max-height:min(42vh,360px); margin:0; overflow:auto; border:0; border-radius:0; padding:13px 12px 18px; color:#dfe2e6; background:#15171a; font:inherit; font-size:12px; line-height:1.8; white-space:pre-wrap; overflow-wrap:anywhere; scrollbar-color:#737780 #24272c; scrollbar-width:thin; }
    .anw-assistant-review-text:focus-visible { outline:2px solid #ff835c; outline-offset:-2px; }
    .anw-assistant-review-warnings { display:grid; gap:4px; margin:0; padding:8px 12px 8px 28px; border-top:1px solid #4a402e; color:#e3bd79; background:#29251d; font-size:11px; line-height:1.55; }
    .anw-assistant-review-status { margin:0; border-top:1px solid #29463c; padding:7px 10px; color:#90d6b9; background:#1b2b25; font-size:10px; line-height:1.5; }
    .anw-assistant-review-status.is-checking { border-color:#4a402e; color:#e3bd79; background:#29251d; }
    .anw-assistant-review-status.is-conflict,.anw-assistant-review-status.is-invalid,.anw-assistant-review-status.is-failed { border-color:#55332f; color:#f2a79d; background:#2f1f1d; }
    .anw-assistant-review-status.is-applied,.anw-assistant-review-status.is-undone { color:#9ce0c3; background:#173027; }
    .anw-assistant-review-status.is-discarded { border-color:#383b41; color:#aeb2b9; background:#23252a; }
    .anw-assistant-review-editor > footer { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; border-top:1px solid #34373d; padding:8px 10px; background:#202226; }
    .anw-assistant-review-editor > footer button { min-width:0; min-height:40px; border:1px solid #464a52; border-radius:6px; padding:7px 8px; color:#d0d3d8; background:#292c31; cursor:pointer; font:inherit; font-size:11px; font-weight:680; line-height:1.25; transition:color .15s ease,border-color .15s ease,background .15s ease,box-shadow .15s ease; }
    .anw-assistant-review-editor > footer button:hover,.anw-assistant-review-editor > footer button:focus-visible { border-color:#ff9a73; color:#fff; background:#3a2b27; outline:0; box-shadow:0 0 0 2px rgba(255,117,72,.2); }
    .anw-assistant-review-editor > footer button.is-primary { border-color:#ff8057; color:#fff; background:#e96940; box-shadow:none; }
    .anw-assistant-review-editor > footer button.is-quiet { color:#b6bac1; background:#24262b; }
    .anw-assistant-review-editor > footer button:disabled { border-color:#35383e; color:#6f747d; background:#222429; box-shadow:none; cursor:not-allowed; }
    .anw-assistant-review-editor > small { padding:0 10px 8px; color:#858a93; background:#202226; font-size:9px; line-height:1.5; }
    .anw-assistant-review-editor.is-conflict { border-color:#55332f; }
    .anw-assistant-review-editor.is-invalid { border-style:dashed; }

    .anw-modal .qwenpaw-modal-content { overflow:hidden; border-radius:18px; color:var(--anw-text)!important; background:#fff!important; box-shadow:0 22px 70px rgba(17,24,39,.2); }
    .anw-modal .qwenpaw-modal-header { padding:20px 22px 14px; border-bottom:1px solid var(--anw-line); background:#fff!important; }
    .anw-modal .qwenpaw-modal-title { color:var(--anw-ink)!important; font-size:18px; }
    .anw-modal .qwenpaw-modal-close { color:#8a909d!important; }
    .anw-modal .qwenpaw-modal-body { color:var(--anw-text)!important; background:#fff!important; }
    .anw-modal .qwenpaw-modal-footer { padding:14px 20px 18px; border-top:1px solid var(--anw-line); background:#fff!important; }
    .anw-modal .qwenpaw-typography { color:var(--anw-text); }
    .anw-modal .qwenpaw-input,
    .anw-modal .qwenpaw-input-number,
    .anw-modal .qwenpaw-input-number-input { color:var(--anw-text)!important; border-color:#dfe3e8!important; background:#fff!important; }
    .anw-modal .qwenpaw-input::placeholder { color:#a3a8b1!important; }
    .anw-modal .qwenpaw-input:focus,
    .anw-modal .qwenpaw-input-focused,
    .anw-modal .qwenpaw-input-number-focused { border-color:var(--anw-orange)!important; box-shadow:0 0 0 2px rgba(255,112,67,.12)!important; }
    .anw-outline-chapter-label { display:inline-flex; width:fit-content; border-radius:999px; padding:5px 10px; color:var(--anw-orange-strong)!important; background:var(--anw-orange-soft); font-size:12px; font-weight:750; }
    .anw-asset-picker-copy { margin:0 0 8px!important; color:var(--anw-muted)!important; line-height:1.7; }
    .anw-asset-modal .qwenpaw-tabs-tab { color:#69707c!important; }
    .anw-asset-modal .qwenpaw-tabs-tab-active .qwenpaw-tabs-tab-btn { color:var(--anw-orange-strong)!important; }
    .anw-asset-modal .qwenpaw-tabs-ink-bar { background:var(--anw-orange)!important; }
    .anw-asset-empty { display:flex; min-height:290px; align-items:center; justify-content:center; border:1px dashed #e1e4e9; border-radius:14px; background:#fafbfc; }
    .anw-generation-progress { display:flex; min-height:230px; flex-direction:column; align-items:center; justify-content:center; padding:20px; text-align:center; }
    .anw-generation-progress h2 { margin:22px 0 8px; color:var(--anw-ink); font-size:21px; }
    .anw-generation-progress p { margin:0 0 10px; color:#555d69; }
    .anw-generation-progress span { color:var(--anw-muted); font-size:12px; }

    .anw-chapter-field { display:grid; gap:8px; color:#3d4148; }
    .anw-chapter-field > strong { color:#30343a; font-size:14px; }
    .anw-chapter-field > span { color:#999da4; font-size:12px; }
    .anw-quick-asset-body { display:grid; gap:20px; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .qwenpaw-modal-content { overflow:hidden!important; border-radius:21px!important; padding:0!important; box-shadow:0 26px 72px rgba(0,0,0,.32)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .qwenpaw-modal-header { min-height:84px; margin:0!important; border-bottom:0!important; padding:24px 24px!important; background:linear-gradient(100deg,#ff6e3b,#ff8659)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-intelligence-modal .qwenpaw-modal-header { border-bottom:0!important; background:linear-gradient(100deg,#ff703d,#ff8a5a)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .qwenpaw-modal-content,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-intelligence-modal .qwenpaw-modal-content { padding:0!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .qwenpaw-modal-close { top:26px!important; right:24px!important; width:34px!important; height:34px!important; border-radius:50%!important; color:#fff!important; background:rgba(255,255,255,.22)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .qwenpaw-modal-close:hover { background:rgba(255,255,255,.32)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-intelligence-modal .qwenpaw-modal-close { top:12px!important; right:12px!important; color:#fff!important; }
    .anw-outline-edit-title { display:flex; align-items:center; gap:12px; color:#fff; }
    .anw-outline-edit-icon { display:grid; width:36px; height:36px; flex:0 0 36px; place-items:center; border-radius:10px; color:#fff; background:rgba(255,255,255,.2); font-size:20px; }
    .anw-outline-edit-heading { display:grid; gap:2px; }
    .anw-outline-edit-heading strong { color:#fff; font-size:20px; font-weight:760; line-height:1.2; }
    .anw-outline-edit-heading small { color:rgba(255,255,255,.92); font-size:14px; font-weight:520; line-height:1.3; }
    .anw-intelligence-title { display:flex; align-items:center; gap:10px; color:#fff; }
    .anw-intelligence-title strong { color:#fff; font-size:18px; }
    .anw-intelligence-title > span:last-child { margin-left:auto; color:rgba(255,255,255,.78); font-size:12px; font-weight:400; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .qwenpaw-modal-body { padding:24px 20px 22px!important; }
    .anw-outline-edit-body { display:grid; gap:24px; }
    .anw-outline-edit-field { display:grid; gap:10px; color:#303238; }
    .anw-outline-edit-field > strong { color:#303238; font-size:16px; font-weight:750; line-height:1.4; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-field > textarea.qwenpaw-input { height:320px; min-height:180px!important; max-height:min(520px,calc(100vh - 410px))!important; resize:vertical; overflow:auto; border:2px solid #dedfe1!important; border-radius:11px!important; padding:22px 16px!important; color:#202226!important; background:#fff!important; box-shadow:0 0 0 5px rgba(255,112,67,.09)!important; font-size:15px; line-height:1.75; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-field > textarea.qwenpaw-input:focus { border-color:#ff8057!important; box-shadow:0 0 0 5px rgba(255,112,67,.12)!important; }
    .anw-outline-edit-target { gap:9px; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-target > .qwenpaw-input { width:100%; height:44px; border:2px solid #dedfe1!important; border-radius:10px!important; padding:0 15px; color:#25272b!important; background:#fff!important; box-shadow:none!important; font-size:16px; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-target > input[type="number"] { -moz-appearance:textfield; appearance:textfield; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-target > input[type="number"]::-webkit-inner-spin-button,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-target > input[type="number"]::-webkit-outer-spin-button { margin:0; -webkit-appearance:none; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-target > .qwenpaw-input:focus { border-color:#ff8057!important; box-shadow:0 0 0 3px rgba(255,112,67,.1)!important; }
    .anw-outline-edit-target > small { color:#9b9da2; font-size:13px; font-weight:550; line-height:1.4; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .qwenpaw-modal-footer { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:0!important; border-top:1px solid #ececee; padding:16px 20px 20px!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .qwenpaw-modal-footer > button { width:100%; height:48px; margin:0!important; border-radius:10px!important; font-size:16px; font-weight:750; }
    .anw-outline-edit-cancel { display:block!important; width:100%!important; min-width:0!important; height:48px!important; border:0!important; border-radius:10px!important; color:#64666b!important; background-color:#f0f0f1!important; background-image:none!important; box-shadow:none!important; cursor:pointer; font-size:16px; font-weight:750; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal button.anw-outline-edit-cancel:hover { color:#4f5156; background:#e9e9eb; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-save.qwenpaw-btn { color:#fff!important; border:0!important; background:linear-gradient(100deg,#ff6b38,#ff8254)!important; box-shadow:0 9px 20px rgba(255,105,56,.22)!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-outline-edit-modal .anw-outline-edit-save.qwenpaw-btn:disabled { color:#fff!important; background:#dedfe1!important; box-shadow:none!important; }
    .anw-sync-copy { display:grid; gap:8px; padding:6px 4px; color:#555a61; line-height:1.8; text-align:center; }
    .anw-sync-copy p { margin:0; }
    .anw-sync-copy strong { margin-top:4px; color:#41454c; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-confirm-title,
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-confirm-content { color:#4d5158!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-confirm-btns .qwenpaw-btn:not(.qwenpaw-btn-primary) { color:#555a61!important; border-color:#dfe2e6!important; background:#fff!important; box-shadow:none!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-confirm-btns .qwenpaw-btn-primary { color:#fff!important; border-color:#ff7548!important; background:#ff7548!important; }

    html .qwenpaw-modal-root .qwenpaw-modal.anw-asset-modal .qwenpaw-modal-body { min-height:480px; max-height:calc(100vh - 220px); overflow:auto; padding:18px 24px 8px!important; }
    .anw-asset-picker-copy { margin:0 0 12px!important; color:#858991!important; text-align:left; }
    .anw-asset-search-row { display:flex; align-items:center; gap:12px; margin-bottom:12px; border:1px solid #ffd9c9; border-radius:8px; padding:8px 10px; background:#fffaf7; }
    .anw-asset-search-row .qwenpaw-input-affix-wrapper { flex:1; }
    .anw-asset-search-row .qwenpaw-btn { flex:0 0 auto; color:#ef7046!important; }
    .anw-asset-modal .qwenpaw-tabs-nav-list { display:grid!important; width:100%; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; }
    .anw-asset-modal .qwenpaw-tabs-tab { justify-content:center; margin:0!important; border:1px solid #e2e4e7; border-radius:8px; padding:9px 8px!important; background:#fff; }
    .anw-asset-modal .qwenpaw-tabs-tab-active { border-color:#ff7a50!important; background:#ff7a50!important; }
    .anw-asset-modal .qwenpaw-tabs-tab-active .qwenpaw-tabs-tab-btn { color:#fff!important; }
    .anw-asset-modal .qwenpaw-tabs-ink-bar { display:none!important; }
    .anw-asset-grid { display:grid; grid-template-columns:minmax(0,1fr); gap:10px; min-height:300px; align-content:start; padding:5px 1px 14px; }
    .anw-asset-card { display:flex; min-width:0; min-height:72px; align-items:flex-start; gap:11px; border:1px solid #e3e5e8; border-radius:9px; padding:12px 14px; color:#444950; background:#fff; cursor:pointer; text-align:left; }
    .anw-asset-card:hover,.anw-asset-card.is-selected { border-color:#ff7a50; background:#fff9f6; box-shadow:0 4px 12px rgba(255,116,72,.08); }
    .anw-asset-card > span:last-child { display:grid; min-width:0; gap:7px; }
    .anw-asset-card strong { overflow:hidden; color:#30343a; text-overflow:ellipsis; white-space:nowrap; }
    .anw-asset-card small { display:-webkit-box; overflow:hidden; color:#7c8188; line-height:1.6; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-asset-modal .qwenpaw-checkbox-inner { border-color:#c8cbd0!important; background:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-asset-modal .qwenpaw-checkbox-checked .qwenpaw-checkbox-inner { border-color:#ff7548!important; background:#ff7548!important; }
    .anw-asset-empty { min-height:300px; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-asset-modal .qwenpaw-modal-footer { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-asset-modal .qwenpaw-modal-footer .qwenpaw-btn { width:100%; margin:0!important; }
    .anw-generation-confirm-copy { display:grid; gap:8px; color:#6e6258; line-height:1.65; }
    .anw-generation-confirm-copy strong { border:1px solid #ffe0ad; border-radius:8px; padding:10px 12px; color:#9a641c; background:#fff8e8; font-size:13px; }
    .anw-generation-confirm-copy p { margin:0; color:#7d8188; font-size:13px; }
    .anw-generation-confirm-copy b { margin-top:3px; color:#35383e; }

    html .qwenpaw-modal-root .qwenpaw-modal.anw-generation-history-modal .qwenpaw-modal-body { max-height:calc(100vh - 185px); overflow:auto; padding:18px 22px 24px!important; }
    .anw-history-title,.anw-review-title { display:flex; align-items:center; gap:10px; }
    .anw-history-title strong,.anw-review-title strong { color:#24282e; font-size:18px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-generation-history-modal .qwenpaw-tag,
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-review-result-modal .qwenpaw-tag { color:#e5673f!important; border-color:#ffd8c9!important; background:#fff2ed!important; }
    .anw-generation-history-list { display:grid; gap:14px; }
    .anw-history-card { display:grid; gap:12px; border:1px solid #e5e7ea; border-radius:10px; padding:16px 18px; background:#fff; }
    .anw-history-card.is-featured { border-color:#ffb095; box-shadow:0 4px 16px rgba(255,117,72,.1); }
    .anw-history-card > header,.anw-history-card > footer { display:flex; align-items:center; justify-content:space-between; gap:14px; }
    .anw-history-card > header > div { display:flex; align-items:center; gap:12px; }
    .anw-history-card > header span { color:#969aa1; font-size:12px; }
    .anw-history-meta { display:flex; flex-wrap:wrap; gap:8px 18px; color:#7c8188; font-size:12px; }
    .anw-history-card > p { display:-webkit-box; margin:0; overflow:hidden; color:#555a62; line-height:1.75; -webkit-box-orient:vertical; -webkit-line-clamp:3; }
    .anw-history-card > p.is-error { color:#cf4c3c; }
    .anw-history-card footer small { min-width:0; overflow:hidden; color:#989ca3; text-overflow:ellipsis; white-space:nowrap; }
    .anw-history-card footer .qwenpaw-btn { flex:0 0 auto; border-color:#ff9471!important; color:#ef7046!important; background:#fff!important; }

    html .qwenpaw-modal-root .qwenpaw-modal.anw-intelligence-modal .qwenpaw-modal-body { max-height:calc(100vh - 210px); overflow:auto; padding:26px 30px!important; }
    .anw-intelligence-groups { display:grid; gap:24px; }
    .anw-intelligence-groups section { display:grid; gap:12px; }
    .anw-intelligence-groups h3 { margin:0; border-left:4px solid #ff7548; padding-left:11px; color:#2f3339!important; font-size:17px; }
    .anw-intelligence-groups article { display:grid; gap:12px; border-left:3px solid #ff8b63; border-radius:9px; padding:16px 18px; background:#f8f8f9; }
    .anw-intelligence-groups article > strong { color:#30343a; font-size:15px; }
    .anw-intelligence-groups article > div { display:grid; grid-template-columns:1fr 1fr; gap:24px; color:#555a61; line-height:1.65; }
    .anw-intelligence-groups article span { min-width:0; }
    .anw-intelligence-groups article small { display:block; margin-bottom:4px; color:#969aa1; }

    html .qwenpaw-modal-root .qwenpaw-modal.anw-review-result-modal .qwenpaw-modal-body { max-height:calc(100vh - 210px); overflow:auto; padding:22px 24px!important; }
    .anw-review-result { display:grid; gap:16px; }
    .anw-review-issues { display:grid; gap:12px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-review-result-modal .qwenpaw-card { color:#4f545b!important; border-color:#e6e8eb!important; background:#fafafa!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-review-result-modal .qwenpaw-card-body { color:#4f545b!important; background:#fafafa!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-review-result-modal .qwenpaw-alert { color:#5a4a2f!important; border:1px solid #f2d9a8!important; background:#fff8e9!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-review-result-modal .qwenpaw-alert-message { color:#473a27!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.anw-review-result-modal .qwenpaw-alert-description { color:#655741!important; }
    .anw-review-issues header { display:flex; align-items:center; gap:8px; }
    .anw-review-issues p { margin:10px 0 0; color:#555a61; line-height:1.7; }

    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-content,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-header,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-body,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-footer { color:var(--anw-text)!important; background-color:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-title { color:var(--anw-ink)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-close { color:#8a909d!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-input,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-input-affix-wrapper,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-input-number,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-input-number-input { color:var(--anw-text)!important; border-color:#dfe3e8!important; background-color:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-input::placeholder { color:#a3a8b1!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-input-show-count-suffix,
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-input-data-count { color:#92969d!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-select-arrow { color:#7a7f87!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-typography { color:var(--anw-text)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-tabs-tab { color:#69707c!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-tabs-tab-active .qwenpaw-tabs-tab-btn { color:var(--anw-orange-strong)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-footer .qwenpaw-btn:not(.qwenpaw-btn-primary) { color:#555d69!important; border-color:#dfe3e8!important; background:#fff!important; box-shadow:none!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.anw-modal .qwenpaw-modal-footer .qwenpaw-btn-primary { color:#fff!important; border-color:var(--anw-orange)!important; background:var(--anw-orange)!important; }

    .mb-orange-button.qwenpaw-btn,
    .mb-orange-button {
      min-height:44px;
      border:0!important;
      border-radius:9px!important;
      color:#fff!important;
      background:linear-gradient(100deg,#ff6b35,#ff8c5e)!important;
      box-shadow:0 8px 18px rgba(255,105,53,.22)!important;
      font-weight:700!important;
    }
    .mb-orange-button.qwenpaw-btn:disabled { color:#fff!important; background:#ffc3aa!important; box-shadow:none!important; }

    .mb-center-page { min-height:100%; overflow:auto; padding:24px 30px 72px; background:#fff; }
    .mb-center-inner { position:relative; width:min(1100px,100%); min-height:760px; margin:0 auto; }
    .mb-center-header { display:flex; align-items:center; justify-content:space-between; min-height:42px; }
    .mb-center-header h1 { margin:0; font-size:18px; font-weight:600; }
    .mb-center-actions { display:flex; gap:22px; margin-top:15px; }
    .mb-center-action { display:grid; justify-items:center; gap:8px; border:0; color:#52545a; background:transparent; cursor:pointer; font-size:12px; }
    .mb-center-action-icon { display:flex; width:46px; height:46px; align-items:center; justify-content:center; border-radius:50%; color:#fff; background:linear-gradient(145deg,#ef5b87,#d93f72); box-shadow:0 8px 18px rgba(218,63,114,.22); font-size:23px; }
    .mb-center-action:hover .mb-center-action-icon { transform:translateY(-1px); }
    .mb-center-loading { display:flex; min-height:520px; flex-direction:column; align-items:center; justify-content:center; gap:13px; color:#8a8b90; font-size:13px; }

    .mb-novel-card { width:600px; margin:150px auto 0; overflow:hidden; border-radius:12px; background:#fff; box-shadow:0 9px 25px rgba(21,34,50,.09); }
    .mb-novel-card-hero { display:grid; grid-template-columns:112px minmax(0,1fr); gap:22px; min-height:202px; padding:22px 24px; background:linear-gradient(110deg,#edf9ff 0%,#eaf2f9 52%,#e6eef5 100%); }
    .mb-novel-cover { width:112px; height:150px; align-self:center; border-radius:7px; object-fit:cover; box-shadow:0 10px 19px rgba(19,43,67,.24); }
    .mb-novel-card-meta { display:flex; min-width:0; flex-direction:column; justify-content:center; }
    .mb-novel-card-meta h2 { margin:0 0 13px; overflow:hidden; font-size:20px; font-weight:700; text-overflow:ellipsis; white-space:nowrap; }
    .mb-novel-counts { display:flex; gap:18px; color:#777b83; font-size:12px; }
    .mb-novel-counts span { display:inline-flex; align-items:center; gap:5px; }
    .mb-novel-tags { display:flex; flex-wrap:wrap; gap:8px; margin-top:36px; }
    .mb-novel-tags span { border-radius:5px; padding:6px 12px; color:#777c85; background:#e9edf1; font-size:12px; }
    .mb-novel-tags span.is-audience { color:#5366cc; background:#e1e7ff; }
    .mb-latest-chapter { min-height:38px; padding:10px 22px; color:#656a71; background:#f6f8fa; font-size:12px; }
    .mb-novel-tool-row { display:grid; grid-template-columns:repeat(4,1fr); padding:17px 72px 10px; }
    .mb-novel-tool-row button { display:grid; justify-items:center; gap:4px; border:0; color:#4d5056; background:transparent; cursor:pointer; font-size:12px; }
    .mb-novel-tool-row button > span:first-child { font-size:19px; }
    .mb-novel-tool-row button:hover { color:#f36a3d; }
    .mb-novel-start { padding:8px 20px 18px; }
    .mb-novel-start .qwenpaw-btn { height:44px; }
    .mb-novel-switcher { display:flex; width:600px; align-items:flex-start; justify-content:center; gap:12px; margin:14px auto 0; }
    .mb-novel-switcher > button { position:relative; display:flex; width:72px; height:96px; align-items:center; justify-content:center; overflow:hidden; border:1px solid transparent; border-radius:5px; padding:0; background:#fff; cursor:pointer; }
    .mb-novel-switcher > button.is-active { border:2px solid #ff7848; box-shadow:0 5px 13px rgba(255,112,67,.2); }
    .mb-novel-switcher > button > img { width:100%; height:100%; object-fit:cover; }
    .mb-novel-switcher > button > .mb-novel-switch-check { position:absolute; right:2px; top:2px; z-index:1; border-radius:50%; padding:2px; color:#fff; background:#ff7848; font-size:9px; }
    .mb-novel-switcher > button.mb-new-novel-tile { flex-direction:column; gap:7px; border:1px dashed #f49c7c; color:#ef7044; background:#fffaf7; font-size:12px; }
    .mb-new-novel-tile > .qwenpawicon { position:static!important; padding:0!important; color:#ef7044!important; background:transparent!important; font-size:18px!important; }
    .mb-empty-center { display:flex; width:600px; min-height:340px; flex-direction:column; align-items:center; justify-content:center; gap:12px; margin:150px auto 0; border:1px dashed #e7ddd8; border-radius:14px; background:#fffcfa; text-align:center; }
    .mb-empty-center > .qwenpawicon { color:#ff7a4a; font-size:42px; }
    .mb-empty-center h2 { margin:6px 0 0; font-size:20px; }
    .mb-empty-center p { margin:0 0 10px; color:#8c8e93; font-size:13px; }

    .mb-private-page { min-height:100%; overflow:auto; padding:28px 34px 72px; background:#fff; }
    .mb-private-inner { width:min(1180px,100%); margin:0 auto; }
    .mb-private-header { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; }
    .mb-private-title-row { display:flex; align-items:center; gap:22px; }
    .mb-private-title-row h1 { margin:0; font-size:31px; }
    .mb-back-link { display:inline-flex; align-items:center; gap:7px; border:0; color:#555a61; background:transparent; cursor:pointer; font-size:14px; }
    html body button.mb-preset-button.qwenpaw-btn.qwenpaw-btn-default,
    html body .mb-preset-button.qwenpaw-btn,
    html body .mb-preset-button { min-width:100px; height:44px; border:0!important; border-radius:10px; color:#fff!important; background-color:#f57a43!important; background-image:none!important; box-shadow:0 7px 16px rgba(245,122,67,.22)!important; }
    .mb-private-tabs { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-top:36px; }
    .mb-private-tabs button { min-height:58px; border:1px solid #e0e2e5; border-radius:12px; color:#44474d; background:#fff; cursor:pointer; font-size:16px; font-weight:650; }
    .mb-private-tabs button.is-active { border-color:transparent; color:#fff; background:linear-gradient(100deg,#f56a39,#fa875b); box-shadow:0 9px 20px rgba(245,106,57,.2); }
    .mb-add-asset { display:flex; width:100%; min-height:62px; align-items:center; justify-content:center; gap:6px; margin:20px 0; border:1px dashed #e2a289; border-radius:12px; color:#686b71; background:#fff; cursor:pointer; font-size:14px; }
    .mb-add-asset:hover { color:#ef7044; background:#fffaf8; }
    .mb-private-loading,.mb-private-empty { display:flex; min-height:300px; align-items:center; justify-content:center; gap:12px; color:#8b8d92; }
    .mb-asset-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; }
    .mb-asset-card { display:flex; min-width:0; min-height:224px; flex-direction:column; border:1px solid #f1f1f2; border-radius:13px; padding:22px 22px 18px; background:#fff; box-shadow:0 6px 18px rgba(30,37,48,.06); }
    .mb-asset-card h2 { margin:0 0 14px; font-size:17px; }
    .mb-asset-card p { display:-webkit-box; flex:1; margin:0; overflow:hidden; color:#74777e; font-size:13px; line-height:1.8; -webkit-box-orient:vertical; -webkit-line-clamp:3; }
    .mb-asset-actions { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-top:20px; }
    .mb-asset-actions button { min-height:39px; border:0; border-radius:8px; color:#555a60; background:#f6f7f8; cursor:pointer; }
    .mb-asset-actions button.is-danger { color:#d86662; background:#fff1f0; }

    .mb-field-label { display:block; margin:16px 0 7px; color:#303238; font-size:13px; font-weight:650; }
    .mb-form-modal .qwenpaw-input,.mb-form-modal textarea.qwenpaw-input { min-height:42px; border-radius:8px; }
    .mb-modal-actions { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:24px; }
    .mb-modal-actions .qwenpaw-btn { min-height:44px; border-radius:8px; }
    .mb-modal-actions > .qwenpaw-btn:not(.mb-orange-button),
    .mb-modal-actions > button:not(.mb-orange-button) { color:#555a61!important; border-color:#dfe2e6!important; background:#fff!important; box-shadow:none!important; }
    .mb-preset-empty { display:flex; min-height:190px; flex-direction:column; align-items:center; justify-content:center; color:#8a8d93; }
    .mb-preset-empty > .qwenpawicon { color:#d8dade; font-size:48px; }
    .mb-preset-list { display:grid; max-height:300px; gap:10px; overflow:auto; }
    .mb-preset-list article { display:flex; align-items:center; justify-content:space-between; gap:14px; border:1px solid #eceef1; border-radius:10px; padding:13px 15px; }
    .mb-preset-list p { margin:4px 0 0; color:#888b91; font-size:12px; }
    .mb-preset-picker-entry { display:flex; width:100%; min-height:52px; align-items:center; justify-content:center; gap:8px; border:1px dashed #d7d9dd; border-radius:8px; color:#64676d; background:#fff; cursor:pointer; }
    .mb-picker-subtitle { margin:-8px 0 16px; color:#8d8f94; font-size:12px; }
    .mb-picker-tabs { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin:16px 0; }
    .mb-picker-tabs button { min-height:43px; border:1px solid #e4e5e8; border-radius:8px; color:#56595f; background:#fff; cursor:pointer; }
    .mb-picker-tabs button.is-active { border-color:transparent; color:#fff; background:linear-gradient(100deg,#f56a39,#fa875b); }
    .mb-picker-list { display:grid; max-height:370px; gap:10px; overflow:auto; padding-right:4px; }
    .mb-picker-item { display:flex; align-items:flex-start; gap:12px; border:1px solid #e8e9ec; border-radius:10px; padding:14px 16px; background:#fff; cursor:pointer; box-shadow:0 3px 9px rgba(25,31,42,.04); }
    .mb-picker-item > span:last-child { display:grid; gap:5px; }
    .mb-picker-item small { overflow:hidden; color:#888b91; text-overflow:ellipsis; white-space:nowrap; }

    html .qwenpaw-modal-root .qwenpaw-modal.mb-create-modal .qwenpaw-modal-content { border-radius:10px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal-wrap:has(.mb-create-modal) { display:flex; align-items:center; justify-content:center; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-create-modal { top:auto!important; margin:0!important; padding-bottom:0!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-create-modal .qwenpaw-modal-header { padding:18px 20px 15px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-create-modal .qwenpaw-modal-title { font-size:18px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-create-modal .qwenpaw-modal-body { max-height:calc(100vh - 120px); overflow:auto; padding:20px 21px 24px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-create-modal h2,
    html .qwenpaw-modal-root .qwenpaw-modal.mb-template-modal h2 { color:#17191f!important; }
    .mb-wizard-loading { display:flex; min-height:360px; flex-direction:column; align-items:center; justify-content:center; gap:12px; color:#888b91; }
    .mb-wizard-progress { margin:0 0 42px; }
    .mb-wizard-hint { width:fit-content; margin:0 auto 12px; border:1px solid #ffd6c6; border-radius:999px; padding:5px 17px; color:#ed7046; background:#fff1eb; font-size:12px; font-weight:700; }
    .mb-wizard-steps { position:relative; display:grid; grid-template-columns:repeat(6,1fr); }
    .mb-wizard-steps::before { position:absolute; z-index:0; right:8%; top:13px; left:8%; height:2px; content:""; background:#dadde1; }
    .mb-wizard-step { position:relative; z-index:1; display:grid; justify-items:center; gap:8px; color:#96999e; font-size:12px; }
    .mb-wizard-step::before { position:absolute; z-index:-1; right:50%; top:13px; width:100%; height:2px; content:""; background:transparent; }
    .mb-wizard-step.is-complete::before,.mb-wizard-step.is-current::before { background:#f57a49; }
    .mb-wizard-step:first-child::before { display:none; }
    .mb-wizard-dot { display:flex; width:28px; height:28px; align-items:center; justify-content:center; border:2px solid #d8dade; border-radius:50%; color:#898c92; background:#fff; font-size:12px; font-weight:700; }
    .mb-wizard-step.is-complete .mb-wizard-dot,.mb-wizard-step.is-current .mb-wizard-dot { border-color:#f57a49; color:#fff; background:#f57a49; box-shadow:0 3px 8px rgba(245,122,73,.22); }
    .mb-wizard-step.is-complete .mb-wizard-step-label,.mb-wizard-step.is-current .mb-wizard-step-label { color:#ef7046; font-weight:650; }
    .mb-wizard-body,.mb-type-step { text-align:center; }
    .mb-wizard-body > h2,.mb-type-step > h2 { margin:0; font-size:21px; }
    .mb-wizard-body > p { margin:8px 0 37px; color:#94969c; font-size:12px; }
    .mb-type-step > p { margin:8px 0 30px; color:#94969c; font-size:12px; }
    .mb-type-step { min-height:352px; padding-top:18px; }
    .mb-type-cards,.mb-audience-cards { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
    .mb-choice-card { position:relative; display:grid; min-height:140px; justify-items:center; align-content:center; gap:8px; border:1px solid #e3e5e8; border-radius:11px; padding:18px; color:#373a40; background:#fff; cursor:pointer; text-align:center; }
    .mb-choice-card:hover { border-color:#f3a589; background:#fffaf8; }
    .mb-choice-card:focus { outline:none; }
    .mb-choice-card:focus-visible { outline:2px solid #f47a4b; outline-offset:2px; }
    .mb-choice-card.is-selected { border:2px solid #f47a4b!important; background:#fff9f6; box-shadow:0 7px 17px rgba(244,122,75,.13); }
    .mb-choice-card.is-selected:focus-visible { outline:none; }
    .mb-choice-icon { display:flex; width:42px; height:42px; align-items:center; justify-content:center; border-radius:10px; color:#f27445; background:#fff0e9; font-size:24px; }
    .mb-choice-card small { color:#92949a; font-size:11px; line-height:1.55; }
    .mb-choice-badge { display:inline-flex; margin-left:7px; border-radius:999px; padding:1px 7px; color:#fff; background:#ff7650; font-size:9px; font-weight:700; line-height:1.55; vertical-align:2px; }
    .mb-choice-check { position:absolute; right:12px; top:12px; color:#f27445; }
    .mb-audience-cards .mb-choice-card { min-height:218px; }
    .mb-audience-cards .mb-choice-icon { width:58px; height:58px; border-radius:50%; font-size:31px; }
    .mb-audience-cards .mb-choice-card:first-child.is-selected .mb-choice-icon { color:#fff; background:#6861d9; }
    .mb-audience-cards .mb-choice-card:nth-child(2).is-selected .mb-choice-icon { color:#fff; background:#f15a96; }
    .mb-idea-label { display:flex; align-items:center; justify-content:space-between; margin:0 0 8px; text-align:left; }
    .mb-idea-label strong { font-size:13px; }
    .mb-direct-template { border:0; padding:0; color:#f07a51; background:transparent; cursor:pointer; font-size:11px; }
    .mb-direct-template:hover { color:#dc5d34; text-decoration:underline; }
    .mb-idea-input { min-height:200px!important; border-radius:10px!important; text-align:left; }
    .mb-idea-meta { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-top:9px; margin-bottom:12px; }
    .mb-idea-tip { display:flex; align-items:center; gap:5px; color:#9a9ca1; font-size:11px; }
    .mb-idea-tip .qwenpawicon { color:#efad42; }
    .mb-char-count { flex:none; border-radius:999px; padding:2px 7px; color:#92959b; background:#f3f4f5; font-size:11px; text-align:right; }
    .mb-template-empty { display:flex; min-height:210px; flex-direction:column; align-items:center; justify-content:center; gap:16px; color:#777a80; }
    .mb-template-empty > .qwenpawicon { color:#dedfe2; font-size:42px; }
    .mb-template-current { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; margin-bottom:22px; text-align:left; }
    .mb-template-current > div:first-child { display:grid; gap:10px; }
    .mb-template-current > div:first-child > span { width:fit-content; border-radius:6px; padding:6px 10px; color:#fff; background:#f47a49; font-size:11px; }
    .mb-template-actions { display:flex; align-items:center; gap:8px; }
    .mb-template-actions .qwenpaw-btn:not(.mb-orange-button),
    .mb-template-actions .qwenpaw-btn:not(.mb-orange-button):focus { color:#565b63!important; border-color:#dfe2e6!important; background:#fff!important; box-shadow:none!important; }
    .mb-template-generating { display:flex; min-height:270px; flex-direction:column; align-items:center; justify-content:center; gap:13px; color:#6f7278; }
    .mb-template-generating strong { color:#303238; font-size:15px; }
    .mb-template-generating span { color:#97999e; font-size:12px; }
    .mb-template-heading { display:flex; align-items:center; justify-content:space-between; margin-bottom:13px; text-align:left; }
    .mb-template-heading span { color:#f07a51; font-size:11px; }
    .mb-template-form { max-height:520px; overflow:auto; padding:12px 3px 8px 0; }
    .mb-template-form .mb-wizard-field { margin-bottom:20px; }
    .mb-wizard-field { display:grid; gap:7px; margin:0 0 14px; color:#303238; font-size:13px; font-weight:650; text-align:left; }
    .mb-wizard-field .qwenpaw-input { min-height:42px; border-radius:8px; font-weight:400; }
    .mb-ai-name { margin-top:7px; }
    .mb-info-step { min-height:344px; }
    .mb-name-cost { display:flex; width:fit-content; align-items:center; gap:4px; margin-top:7px; border-radius:999px; padding:3px 8px; color:#a98d7f; background:#fff3eb; font-size:11px; }
    .mb-name-cost .qwenpawicon { color:#f0aa37; }
    .mb-model-note { display:block; margin-top:8px; color:#aa795f; text-align:left; }
    .mb-cover-label { display:block; margin:-6px 0 10px; text-align:left; }
    .mb-cover-mode-list { display:grid; gap:12px; }
    .mb-cover-mode-list .mb-choice-card { min-height:82px; grid-template-columns:48px minmax(0,1fr); justify-items:start; align-content:center; gap:2px 12px; padding:12px 20px; text-align:left; }
    .mb-cover-mode-list .mb-choice-card .mb-choice-icon { grid-row:1/3; }
    .mb-cover-mode-list .mb-choice-card small { grid-column:2; }
    .mb-cover-upload { display:flex; min-height:112px; align-items:center; justify-content:center; margin-top:13px; overflow:hidden; border:1px dashed #d6d9de; border-radius:9px; color:#60636a; cursor:pointer; }
    .mb-cover-upload span { display:grid; justify-items:center; gap:8px; }
    .mb-cover-upload input { display:none; }
    .mb-cover-upload.has-image { min-height:180px; }
    .mb-cover-upload img { width:120px; height:160px; object-fit:cover; }
    .mb-complete-step > p { margin-bottom:15px; }
    .mb-complete-cover { width:236px; height:315px; border-radius:11px; object-fit:cover; box-shadow:0 13px 27px rgba(27,37,51,.18); }
    .mb-complete-book { display:grid; gap:4px; margin-top:12px; }
    .mb-complete-book strong { font-size:15px; }
    .mb-complete-book span { color:#83868c; font-size:11px; }
    .mb-create-success { display:flex; min-height:350px; flex-direction:column; align-items:center; justify-content:center; text-align:center; }
    .mb-create-success-icon { display:flex; width:58px; height:58px; align-items:center; justify-content:center; border-radius:50%; color:#fff; background:#ff7548; font-size:28px; box-shadow:0 10px 24px rgba(255,117,72,.22); }
    .mb-create-success h2 { margin:22px 0 8px; color:#202329; font-size:22px; }
    .mb-create-success p { margin:0; color:#868a91; font-size:13px; }
    .mb-create-success-actions { display:grid; width:100%; grid-template-columns:1fr 1fr; gap:12px; margin-top:38px; }
    .mb-create-success-actions .qwenpaw-btn { min-height:46px; border-radius:9px; }
    .mb-create-success-actions .qwenpaw-btn:not(.mb-orange-button) { color:#555a61!important; border-color:#dfe2e6!important; background:#fff!important; box-shadow:none!important; }
    .mb-wizard-footer { display:grid; grid-template-columns:108px minmax(0,1fr); gap:12px; margin-top:33px; }
    .mb-wizard-footer > .qwenpaw-btn:only-child { grid-column:1/3; }
    .mb-wizard-footer .qwenpaw-btn { min-height:48px; border-radius:9px; }
    .mb-wizard-footer > .qwenpaw-btn:not(.mb-orange-button),
    .mb-wizard-footer > button:not(.mb-orange-button) { color:#555a61!important; border-color:#dfe2e6!important; background:#fff!important; box-shadow:none!important; }

    html .qwenpaw-modal-root .qwenpaw-modal.mb-template-modal .qwenpaw-modal-body { padding:18px 26px 22px!important; }
    .mb-template-modal-title { display:inline-flex; align-items:center; gap:8px; }
    .mb-template-modal-title > .qwenpawicon { color:#ef784b; }
    .mb-template-tabs { display:grid; grid-template-columns:1fr 1fr; margin-bottom:20px; border-radius:9px; padding:3px; background:#fafafa; }
    .mb-template-tabs button { min-height:44px; border:0; border-radius:8px; color:#777a80; background:transparent; cursor:pointer; }
    .mb-template-tabs button.is-active { color:#ed7046; background:#fff; box-shadow:0 2px 8px rgba(26,32,42,.07); }
    .mb-template-category-select { width:100%; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-template-modal .mb-template-category-select.qwenpaw-select .qwenpaw-select-selector { min-height:44px!important; align-items:center; border-radius:8px!important; border-color:#e4e6e9!important; background-color:#fff!important; background-image:none!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-template-modal .mb-template-category-select .qwenpaw-select-selection-placeholder,
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-template-modal .mb-template-category-select .qwenpaw-select-selection-item { color:#555960!important; }
    html body .qwenpaw-select-dropdown.mb-template-category-dropdown { border:1px solid #eceef1!important; background:#fff!important; box-shadow:0 9px 26px rgba(29,36,48,.13)!important; }
    html body .qwenpaw-select-dropdown.mb-template-category-dropdown .qwenpaw-select-item { color:#4f535a!important; background:#fff!important; }
    html body .qwenpaw-select-dropdown.mb-template-category-dropdown .qwenpaw-select-item-option-active { background:#fff6f2!important; }
    html body .qwenpaw-select-dropdown.mb-template-category-dropdown .qwenpaw-select-item-option-selected { color:#ef7044!important; background:#fff1eb!important; }
    .mb-template-list { display:grid; max-height:230px; overflow:auto; border:1px solid #e5e6e9; border-radius:8px; }
    .mb-template-list > button { display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:68px; border:0; border-bottom:1px solid #eeeff1; padding:12px 16px; color:#33363b; background:#fff; cursor:pointer; text-align:left; }
    .mb-template-list > button.is-active { color:#ef7044; background:#fff4ef; }
    .mb-template-list > button span { display:grid; gap:5px; }
    .mb-template-list > button small { color:#91949a; }
    .mb-template-list-empty { display:flex; min-height:170px; flex-direction:column; align-items:center; justify-content:center; gap:10px; color:#8c8f95; background:#fafafa; }
    .mb-template-list-empty > .qwenpawicon { color:#d5d7da; font-size:40px; }
    .mb-custom-template-empty { border:1px dashed #e0e2e5; border-radius:9px; padding:18px; text-align:center; }
    .mb-custom-template-empty p { margin:0 0 7px; }

    .mb-confirm-modal .qwenpaw-modal-confirm-content { color:#666a71!important; }

    /* Miaobi-inspired desktop workbench: all content is backed by persisted domain data. */
    .mb-workbench {
      display:grid;
      width:100%;
      height:100%;
      min-height:0;
      grid-template-columns:var(--mb-workbench-rail-width) minmax(var(--mb-workbench-main-min),1fr);
      align-items:start;
      justify-content:stretch;
      gap:var(--mb-workbench-gap);
      padding:var(--mb-workbench-padding);
      overflow:auto;
      background:#fafafa;
    }
    .mb-book-rail {
      align-self:start;
      position:sticky;
      top:0;
      display:flex;
      box-sizing:border-box;
      max-height:calc(100vh - 105px);
      max-height:calc(100dvh - 105px);
      min-height:0;
      flex-direction:column;
      border:1px solid #ececef;
      border-radius:14px;
      padding:24px 20px 18px;
      overflow-y:auto;
      background:#fff;
      box-shadow:0 8px 28px rgba(26,32,44,.05);
    }
    .mb-book-cover-wrap { position:relative; width:100%; max-width:270px; margin:0 auto 20px; }
    .mb-book-cover { display:block; width:100%; aspect-ratio:3/4; object-fit:cover; border-radius:12px; box-shadow:0 10px 24px rgba(31,41,55,.14); }
    .mb-book-cover-actions { position:absolute; top:10px; right:10px; display:flex; gap:6px; }
    .mb-book-cover-actions .qwenpaw-btn { display:grid; width:34px; min-width:34px; height:34px; place-items:center; border:0!important; border-radius:8px!important; padding:0!important; color:#fff!important; background:rgba(29,45,53,.72)!important; box-shadow:0 4px 10px rgba(0,0,0,.14)!important; backdrop-filter:blur(5px); }
    .mb-book-rail > h1 { margin:0 0 8px; font-size:23px; line-height:1.35; }
    .mb-book-rail > p { display:-webkit-box; min-height:42px; margin:0 0 12px; overflow:hidden; color:#777c85; font-size:13px; line-height:1.7; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
    .mb-book-stats { display:flex; gap:18px; margin-bottom:16px; color:#5c616a; font-size:13px; }
    .anw-current-model-card { display:flex; margin:0 0 16px; border:1px solid #eceef1; border-radius:10px; padding:10px 11px; flex-direction:column; gap:4px; background:#fafbfc; }
    .anw-current-model-card > strong { color:#555b65; font-size:11px; }
    .anw-current-model-card > span { overflow:hidden; color:#252a31; font-size:13px; font-weight:700; text-overflow:ellipsis; white-space:nowrap; }
    .anw-current-model-card > small { color:#858a93; font-size:10px; line-height:1.5; }
    .mb-book-nav { display:grid; gap:8px; border-top:1px solid #eff0f2; padding-top:16px; }
    .mb-book-nav > button { display:flex; align-items:center; gap:11px; min-height:44px; border:0; border-radius:8px; padding:0 15px; color:#30343a; background:#f7f7f8; cursor:pointer; font-size:15px; font-weight:650; text-align:left; }
    .mb-book-nav > button:hover { color:#ef6d42; background:#fff5f0; }
    .mb-book-nav > button.is-active { color:#2f3339; outline:2px solid #ff7548; outline-offset:-2px; background:#f7f7f8; box-shadow:none; }
    .mb-book-nav > button .qwenpawicon { color:inherit; font-size:17px; }
    .mb-back-center-wrap { margin-top:18px; border-top:1px solid #eff0f2; padding-top:16px; }
    html .mb-book-rail .mb-back-center.qwenpaw-btn { width:100%; min-height:40px; color:#6d727b!important; border-color:#e4e6e9!important; background:#fff!important; box-shadow:none!important; }
    .mb-workbench-main { min-width:0; align-self:start; border:1px solid #ececef; border-radius:14px; overflow:clip; background:#fff; box-shadow:0 8px 28px rgba(26,32,44,.05); }
    .anw-workbench-frame[data-assistant-density="compact"] .mb-workbench { grid-template-columns:260px minmax(0,1fr); gap:18px; padding:18px; }
    .anw-workbench-frame[data-assistant-density="compact"] .mb-book-rail { max-height:calc(100vh - 93px); max-height:calc(100dvh - 93px); }
    .anw-workbench-frame[data-assistant-density="constrained"] .mb-workbench { grid-template-columns:220px minmax(0,1fr); gap:12px; padding:12px; }
    .anw-workbench-frame[data-assistant-density="constrained"] .mb-book-rail { top:0; max-height:calc(100vh - 81px); max-height:calc(100dvh - 81px); padding:14px 12px; }
    .anw-workbench-frame[data-assistant-density="constrained"] .mb-book-cover-wrap { max-width:180px; margin-bottom:12px; }
    .anw-workbench-frame[data-assistant-density="constrained"] .mb-book-rail > h1 { font-size:19px; }
    .anw-workbench-frame[data-assistant-density="constrained"] .mb-panel-header { min-height:68px; padding:12px 16px; }
    .anw-workbench-frame[data-assistant-density="constrained"] .mb-panel-body { padding:16px 16px 32px; }
    .anw-workbench-frame[data-assistant-density="constrained"] .mb-volume-grid { grid-template-columns:1fr; }
    .anw-workbench-frame[data-assistant-density="constrained"] .anw-editor-content { --anw-editor-inline-gutter:14px; }
    .anw-workbench-frame[data-assistant-density="constrained"] .anw-editor.has-chapter-tree .anw-editor-topbar { width:min(1000px,calc(100% - 28px)); }
    .anw-workbench-frame[data-assistant-density="constrained"] .anw-editor-scroll { grid-template-columns:minmax(0,1fr); }
    .anw-workbench-frame[data-assistant-density="constrained"] .anw-editor-paper { grid-column:1; }
    .mb-panel-header { display:flex; min-height:84px; align-items:center; justify-content:space-between; gap:20px; border-bottom:1px solid #eceef1; padding:18px 28px; }
    .mb-panel-header > h2 { margin:0; font-size:25px; line-height:1.3; }
    .mb-panel-actions { display:flex; align-items:center; gap:10px; }
    .mb-panel-header.is-tabs-only { min-height:58px; padding:0 24px; }
    .mb-panel-header.is-tabs-only > h2 { display:none; }
    .mb-panel-header.is-tabs-only .mb-panel-actions { width:100%; }
    .mb-panel-header.is-tabs-only .mb-top-tabs { display:grid; width:100%; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0; }
    .mb-panel-header.is-tabs-only .mb-top-tabs.is-four { grid-template-columns:repeat(4,minmax(0,1fr)); }
    .mb-panel-header.is-tabs-only .mb-top-tabs > button { min-height:58px; padding:0 2px 13px; }
    .mb-panel-actions .qwenpaw-btn:not(.anw-primary-button) { color:#5f646d!important; border-color:#e0e2e5!important; background:#fff!important; box-shadow:none!important; }
    .mb-panel-body { padding:var(--mb-panel-body-padding); }
    .mb-subtitle-row { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:15px; }
    .mb-subtitle-row h3 { margin:0; font-size:18px; }
    .mb-subtitle-row p { margin:5px 0 0; color:#93969c; font-size:13px; }
    .mb-inline-add.qwenpaw-btn { color:#f06e43!important; font-weight:650; }

    .mb-volume-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); align-items:start; gap:18px; }
    .mb-volume-zero { grid-column:1/-1; min-height:72px; display:grid; place-items:center; color:#a7abb2; font-size:13px; }
    .mb-volume-card { border:1px solid #e8e9ec; border-radius:9px; overflow:hidden; background:#fff; }
    .mb-volume-header { display:flex; min-height:80px; align-items:center; gap:8px; padding:10px 14px 10px 16px; background:#fafafa; }
    .mb-volume-toggle { display:grid; min-width:0; flex:1; grid-template-columns:18px minmax(0,1fr); grid-template-rows:auto auto; align-items:center; column-gap:8px; row-gap:3px; border:0; padding:0; color:#373b42; background:transparent; cursor:pointer; text-align:left; }
    .mb-volume-toggle > .qwenpawicon { grid-row:1/3; }
    .mb-volume-toggle strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .mb-volume-toggle > span:last-child { grid-column:2; color:#999ca2; font-size:12px; }
    .mb-volume-actions { display:flex; align-items:center; gap:8px; }
    .mb-volume-actions .qwenpaw-btn { min-width:46px; border:0!important; border-radius:6px!important; padding:0 10px!important; color:#777b83!important; background:#f3f3f4!important; box-shadow:none!important; }
    .mb-volume-actions .qwenpaw-btn-dangerous { color:#e36d64!important; background:#fff0ee!important; }
    .mb-volume-chapters { display:grid; gap:9px; border-top:1px solid #ebeced; padding:12px; }
    .mb-volume-empty { min-height:94px; display:grid; place-items:center; color:#aaaeb5; font-size:13px; }
    .mb-chapter-card { display:flex; min-height:68px; align-items:center; gap:8px; border:1px solid #ececef; border-radius:7px; padding:9px 12px 9px 15px; background:#fff; }
    .mb-chapter-open { display:grid; min-width:0; flex:1; gap:5px; border:0; padding:0; color:#34383e; background:transparent; cursor:pointer; text-align:left; }
    .mb-chapter-open strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; }
    .mb-chapter-open span { color:#9a9da3; font-size:12px; }
    .mb-chapter-actions { display:flex; align-items:center; gap:2px; }
    .mb-chapter-actions .qwenpaw-btn { padding-inline:5px!important; }
    .mb-chapter-actions .qwenpaw-btn-link { color:#f06d42!important; }
    .mb-move-select { width:102px; }
    .mb-ungrouped { margin-top:24px; border-top:1px solid #eceef1; padding-top:20px; }
    .mb-ungrouped-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
    .mb-ungrouped-empty { display:grid; min-height:150px; place-content:center; justify-items:center; gap:8px; color:#aaaeb5; }
    .mb-ungrouped-empty strong { color:#aaaeb5; font-size:14px; font-weight:500; }
    .mb-ungrouped-empty span { font-size:12px; }

    html .qwenpaw-modal-root .qwenpaw-modal.mb-volume-modal .qwenpaw-modal-content { border-radius:20px!important; padding:0!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-volume-modal .qwenpaw-modal-header { margin:0!important; padding:30px 30px 11px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-volume-modal .qwenpaw-modal-title { font-size:20px!important; font-weight:750!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-volume-modal .qwenpaw-modal-body { padding:0 30px 31px!important; }
    .mb-volume-form { display:grid; gap:26px; }
    .mb-volume-form .mb-field { gap:2px; }
    .mb-volume-form .qwenpaw-input { min-height:48px; border-radius:9px; font-size:14px; }
    .mb-volume-form-actions { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-volume-modal .mb-volume-form-actions > button.qwenpaw-btn:not(.anw-primary-button) { height:50px; border-width:0!important; border-style:none!important; border-color:transparent!important; border-radius:9px!important; color:#555a61!important; background:#f6f6f7!important; box-shadow:none!important; font-size:15px; font-weight:650; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-volume-modal .mb-volume-form-actions > button.qwenpaw-btn.anw-primary-button { height:50px; border-width:0!important; border-style:none!important; border-color:transparent!important; border-radius:9px!important; color:#fff!important; background:linear-gradient(100deg,#ff6b35,#ff8c5e)!important; box-shadow:0 8px 18px rgba(255,105,53,.22)!important; font-size:15px; font-weight:650; }

    .mb-search-body { display:grid; grid-template-columns:minmax(0,1fr) 92px; gap:12px; }
    .mb-search-body > .qwenpaw-input-affix-wrapper { min-height:46px; border-color:#dedfe2!important; border-radius:10px!important; background:#fff!important; box-shadow:none!important; }
    .mb-search-body > .qwenpaw-input-affix-wrapper-focused { border-color:#ff7548!important; box-shadow:0 0 0 2px rgba(255,117,72,.1)!important; }
    .mb-search-body > .anw-primary-button { min-height:46px; border-radius:10px!important; }
    .mb-search-results { grid-column:1/-1; display:grid; gap:10px; max-height:470px; min-height:240px; margin-top:4px; overflow:auto; }
    .mb-search-result { display:grid; gap:9px; border:1px solid #e6e7e9; border-radius:10px; padding:14px 16px; color:#33373e; background:#fff; cursor:pointer; text-align:left; }
    .mb-search-result:hover,.mb-search-result:focus-visible { border-color:#ffb89d; outline:0; background:#fffaf7; box-shadow:0 5px 16px rgba(35,39,47,.06); }
    .mb-search-result-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; }
    .mb-search-result-heading strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:15px; }
    .mb-search-result-heading small { flex:0 0 auto; color:#999da4; font-size:11px; }
    .mb-search-result-snippet { display:-webkit-box; overflow:hidden; color:#6e737b; font-size:13px; line-height:1.7; -webkit-box-orient:vertical; -webkit-line-clamp:3; }
    .mb-search-empty { display:grid; min-height:240px; place-content:center; justify-items:center; gap:12px; color:#9a9ea5; }
    .mb-search-empty > .qwenpawicon { font-size:28px; }

    /* Miaobi chapter creation flow: six persisted steps, Agent outline generation, atomic chapter creation. */
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal .qwenpaw-modal-content { overflow:hidden!important; border:0!important; border-radius:12px!important; padding:0!important; color:#30343a!important; background:#fff!important; box-shadow:0 20px 60px rgba(23,28,36,.24)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal .qwenpaw-modal-header { margin:0!important; border-bottom:1px solid #eceef1!important; padding:18px 20px!important; background:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal .qwenpaw-modal-title { color:#24272d!important; font-size:20px!important; font-weight:750!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal .qwenpaw-modal-close { top:13px!important; right:13px!important; color:#7c8189!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal .qwenpaw-modal-body { max-height:calc(100vh - 118px); overflow:auto; padding:20px 42px 28px!important; color:#30343a!important; background:#fff!important; }
    .mb-chapter-loading { display:grid; min-height:440px; place-content:center; justify-items:center; gap:18px; color:#8c9198; }
    .mb-chapter-wizard { display:grid; min-height:470px; align-content:start; }
    .mb-chapter-wizard > .qwenpaw-alert { margin-bottom:14px; }
    .mb-chapter-step-chip { width:max-content; margin:0 auto 13px; border:1px solid #ffd8c9; border-radius:999px; padding:5px 14px; color:#ef7249; background:#fff1eb; font-size:12px; font-weight:700; }
    .mb-chapter-steps { position:relative; display:flex; justify-content:space-between; margin:0 0 54px; }
    .mb-chapter-steps::before,.mb-chapter-steps::after { position:absolute; z-index:0; top:14px; left:14px; height:3px; content:""; }
    .mb-chapter-steps::before { right:14px; background:#e8e9eb; }
    .mb-chapter-steps::after { width:calc(var(--mb-chapter-progress,0%) - 14px); max-width:calc(100% - 28px); background:#ff7548; }
    .mb-chapter-step { position:relative; z-index:1; display:grid; width:34px; flex:0 0 34px; justify-items:center; gap:8px; color:#9a9ea5; font-size:12px; white-space:nowrap; }
    .mb-chapter-step-dot { display:grid; width:28px; height:28px; place-items:center; border:2px solid #e1e3e6; border-radius:50%; color:#8d9198; background:#fff; font-size:12px; font-weight:750; }
    .mb-chapter-step.is-active,.mb-chapter-step.is-complete { color:#ef7044; font-weight:700; }
    .mb-chapter-step.is-active .mb-chapter-step-dot,.mb-chapter-step.is-complete .mb-chapter-step-dot { border-color:#ff7548; color:#fff; background:#ff7548; box-shadow:0 4px 10px rgba(255,117,72,.24); }
    .mb-chapter-step-body { display:grid; gap:12px; align-content:start; }
    .mb-chapter-step-body > h3 { margin:0; color:#22252b; font-size:21px; text-align:center; }
    .mb-chapter-step-body > p { margin:0 0 2px; color:#92969d; line-height:1.65; text-align:center; }
    .mb-chapter-step-body .qwenpaw-input,.mb-chapter-step-body .qwenpaw-input-number { color:#34383f!important; border-color:#e0e2e5!important; background:#fff!important; box-shadow:none!important; }
    .mb-chapter-step-body .qwenpaw-input:focus,.mb-chapter-step-body .qwenpaw-input-number-focused { border-color:#ff7548!important; box-shadow:0 0 0 2px rgba(255,117,72,.1)!important; }
    .mb-chapter-tip { display:flex; align-items:flex-start; gap:8px; margin:2px 0 4px; color:#df8a2c; font-size:12px; line-height:1.65; text-align:center; }
    .mb-chapter-tip > .qwenpawicon { flex:0 0 auto; margin-top:2px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal button.qwenpaw-btn.anw-primary-button { appearance:none; border-width:0!important; border-style:none!important; border-color:transparent!important; outline:0!important; color:#fff!important; background:linear-gradient(100deg,#ff6b35,#ff8c5e)!important; box-shadow:0 8px 18px rgba(255,105,53,.22)!important; font-weight:700; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal button.qwenpaw-btn.anw-primary-button:disabled { color:#fff!important; background:#dedfe1!important; box-shadow:none!important; }
    .mb-chapter-ai-button.qwenpaw-btn { justify-self:center; min-height:43px; margin-top:1px; border-radius:9px!important; padding-inline:22px!important; }
    .mb-chapter-ai-caption { color:#9a9da3!important; font-size:11px; }
    .mb-chapter-line-groups { display:grid; gap:10px; margin-top:6px; }
    .mb-chapter-line-group { overflow:hidden; border:1px solid #e5e6e8; border-radius:9px; background:#fff; }
    .mb-chapter-group-toggle { display:flex; width:100%; min-height:54px; align-items:center; justify-content:space-between; gap:14px; border:0; padding:0 16px; color:#30343a; background:#fff; cursor:pointer; }
    .mb-chapter-group-name { display:flex; align-items:center; gap:8px; }
    .mb-chapter-group-name i { width:10px; height:10px; flex:0 0 auto; border-radius:50%; }
    .mb-chapter-group-name strong { font-size:14px; }
    .mb-chapter-group-name small { color:#a0a4aa; font-size:11px; }
    .mb-chapter-group-items { display:grid; gap:8px; border-top:1px solid #eeeff1; padding:10px; }
    .mb-chapter-group-empty,.mb-chapter-inline-empty { display:grid; min-height:68px; place-items:center; border-radius:8px; color:#a0a4ab; background:#fafafa; font-size:12px; }
    .mb-chapter-foreshadow-empty { display:grid; min-height:220px; place-content:center; justify-items:center; gap:12px; color:#8f939a; }
    .mb-chapter-foreshadow-empty span { font-size:14px; }
    .mb-chapter-foreshadow-empty small { color:#b1b4ba; font-size:12px; }
    .mb-chapter-choice-list { display:grid; gap:10px; }
    .mb-chapter-choice-card { display:flex; width:100%; min-height:84px; align-items:center; gap:14px; border:1px solid #e2e3e5; border-radius:9px; padding:14px 15px; color:#373b42; background:#fff; cursor:pointer; text-align:left; }
    .mb-chapter-choice-card:hover { border-color:#ffc2aa; background:#fffaf7; }
    .mb-chapter-choice-card.is-selected { border:2px solid #ff7548; padding:13px 14px; background:#fff8f4; box-shadow:0 2px 8px rgba(255,117,72,.05); }
    .mb-chapter-choice-card:disabled { cursor:default; opacity:.62; }
    .mb-chapter-choice-copy { display:grid; min-width:0; flex:1; gap:6px; }
    .mb-chapter-choice-copy > strong { color:#292c32; font-size:14px; }
    .mb-chapter-choice-copy > span { display:-webkit-box; overflow:hidden; color:#696e75; font-size:12px; line-height:1.55; text-overflow:ellipsis; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
    .mb-chapter-choice-copy > small { display:-webkit-box; overflow:hidden; color:#9a9ea5; font-size:11px; line-height:1.5; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
    .mb-chapter-selection { display:grid; width:20px; height:20px; flex:0 0 auto; place-items:center; border-radius:50%; color:#fff; background:#dedfe1; }
    .mb-chapter-selection.is-selected { background:#ff7548; }
    .mb-chapter-selection .qwenpawicon { font-size:12px; }
    .mb-chapter-direct-link,.mb-chapter-back-link { justify-self:center; border:0; padding:6px 4px; color:#ef7952; background:transparent; cursor:pointer; font-size:12px; font-weight:650; }
    .mb-chapter-direct-link:disabled,.mb-chapter-back-link:disabled { cursor:wait; opacity:.55; }
    .mb-chapter-next.qwenpaw-btn { min-height:52px; border-radius:10px!important; font-size:16px; }
    .mb-chapter-section-heading { display:flex; align-items:center; gap:8px; margin-top:8px; color:#32363c; }
    .mb-chapter-section-heading::before { width:4px; height:18px; border-radius:4px; background:#ff7548; content:""; }
    .mb-chapter-section-heading > strong { font-size:14px; }
    .mb-chapter-section-heading > span { border-radius:5px; padding:3px 7px; color:#f0734a; background:#fff0e9; font-size:11px; }
    .mb-chapter-soft-tip { border:1px solid #ffe1d4; border-radius:9px; padding:13px 15px; color:#7b7f86; background:#fff9f6; font-size:12px; }
    .mb-chapter-role-title,.mb-chapter-foreshadow-title { display:flex!important; align-items:center; gap:8px; }
    .mb-chapter-role-title strong,.mb-chapter-foreshadow-title strong { color:#2f3339; font-size:14px; }
    .mb-chapter-role-title em,.mb-chapter-foreshadow-title em { border-radius:5px; padding:2px 6px; color:#ef7045; background:#fff0e9; font-size:10px; font-style:normal; }
    .mb-chapter-role-title em:last-child { color:#e88751; background:#fff5ee; }
    .mb-chapter-ai-options { display:grid; gap:12px; border-radius:9px; padding:16px 14px; background:#fafafa; }
    .mb-chapter-ai-options > label,.mb-chapter-auto-card { display:flex; align-items:flex-start; gap:10px; cursor:pointer; }
    .mb-chapter-ai-options label > span:last-child,.mb-chapter-auto-card > span:last-child { display:grid; gap:4px; }
    .mb-chapter-ai-options strong,.mb-chapter-auto-card strong { color:#3b3f46; font-size:13px; }
    .mb-chapter-ai-options small,.mb-chapter-auto-card small { color:#979ba2; font-size:11px; }
    .mb-chapter-dual-actions { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:10px; }
    .mb-chapter-dual-actions > .qwenpaw-btn { min-height:50px; border-radius:9px!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal .mb-chapter-dual-actions > button.qwenpaw-btn:not(.anw-primary-button) { color:#60646b!important; border-color:transparent!important; background:#f5f5f6!important; box-shadow:none!important; }
    .mb-chapter-triple-actions { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-top:10px; }
    .mb-chapter-triple-actions > .qwenpaw-btn { min-height:48px; border-radius:9px!important; }
    .mb-chapter-title-row { display:grid; grid-template-columns:90px minmax(0,1fr) 90px; align-items:center; gap:10px; }
    .mb-chapter-title-row > div { display:grid; gap:5px; text-align:center; }
    .mb-chapter-title-row h3,.mb-chapter-title-row p { margin:0; }
    .mb-chapter-title-row h3 { color:#22252b; font-size:20px; }
    .mb-chapter-title-row p { color:#969aa1; font-size:12px; }
    .mb-chapter-title-row > .qwenpaw-btn { justify-self:end; }
    .mb-chapter-auto-card { border:1px solid #ffe1d4; border-radius:9px; padding:14px 16px; background:#fff9f6; }
    .mb-chapter-foreshadow-title em { color:#b78128; background:#fff5db; }
    .mb-chapter-textarea-hint { display:grid; gap:6px; color:#8f939a; font-size:11px; line-height:1.6; }
    .mb-chapter-textarea-hint small { color:#999da4; }
    .mb-chapter-target-block { display:grid; gap:10px; }
    .mb-chapter-target-block > strong { color:#34383f; font-size:14px; }
    .mb-chapter-target-block > .qwenpaw-input-number { width:100%; border-radius:9px!important; }
    .mb-chapter-target-block .qwenpaw-input-number-input { height:50px; font-size:15px; }
    .mb-chapter-target-block > small { color:#92969d; line-height:1.5; }
    .mb-chapter-step-body.is-target { min-height:300px; }
    .mb-chapter-step-body.is-generating { min-height:560px; justify-items:center; align-content:start; gap:14px; }
    .mb-chapter-step-body.is-generating .mb-chapter-target-block { width:100%; justify-self:stretch; }
    .mb-chapter-step-body.is-generating > .qwenpaw-spin { margin-top:80px; }
    .mb-chapter-step-body.is-generating > h3 { color:#ef7044; font-size:16px; }
    .mb-chapter-step-body.is-generating > p { color:#6f737a; }
    .mb-chapter-step-body.is-generating > .qwenpaw-progress { width:86%; margin-top:12px; }
    .mb-chapter-step-body.is-generating > small { color:#999da4; }
    .mb-chapter-result-heading { display:grid; justify-items:center; gap:7px; margin:14px 0 8px; }
    .mb-chapter-result-heading h3,.mb-chapter-result-heading p { margin:0; }
    .mb-chapter-result-heading h3 { color:#24272d; font-size:20px; }
    .mb-chapter-result-heading p { color:#999da4; font-size:12px; }
    .mb-chapter-step-body.is-outline-result textarea.qwenpaw-input { min-height:220px; line-height:1.8; }
    .mb-chapter-summary-card { display:grid; gap:6px; border-radius:9px; padding:16px; background:#fafafa; }
    .mb-chapter-summary-card > strong { color:#3d4148; }
    .mb-chapter-summary-card > p { margin:0; color:#70747b; font-size:12px; line-height:1.6; }
    .mb-chapter-step-body.is-complete { min-height:580px; }
    .mb-chapter-final-card { border:1px solid #ffe0d2; border-radius:14px; padding:20px 24px; background:#fffaf7; }
    .mb-chapter-final-card dl { display:grid; gap:14px; margin:0; }
    .mb-chapter-final-card dl > div { display:grid; gap:5px; }
    .mb-chapter-final-card dt { color:#979ba2; font-size:12px; }
    .mb-chapter-final-card dd { margin:0; color:#3d4148; font-size:14px; line-height:1.65; }
    .mb-chapter-final-card dd.is-outline { max-height:250px; overflow:auto; white-space:pre-wrap; }

    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-confirm-modal .qwenpaw-modal-content { border-radius:12px!important; padding:0!important; color:#30343a!important; background:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-confirm-modal .qwenpaw-modal-header { margin:0!important; border-bottom:1px solid #eceef1!important; padding:18px 22px!important; background:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-confirm-modal .qwenpaw-modal-title { color:#24272d!important; font-size:19px!important; font-weight:750!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-confirm-modal .qwenpaw-modal-body { padding:28px!important; }
    .mb-chapter-confirm-modal p { margin:0 0 26px; color:#5f646b; line-height:1.7; text-align:center; }
    .mb-chapter-confirm-actions { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .mb-chapter-confirm-actions > .qwenpaw-btn { min-height:48px; border-radius:9px!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-confirm-modal .mb-chapter-confirm-actions > button.qwenpaw-btn:not(.anw-primary-button) { color:#5b5f66!important; border-color:#e1e3e6!important; background:#fff!important; box-shadow:none!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-confirm-modal .mb-chapter-confirm-actions > button.qwenpaw-btn.anw-primary-button { border-width:0!important; border-style:none!important; border-color:transparent!important; color:#fff!important; background:linear-gradient(100deg,#ff6b35,#ff8c5e)!important; box-shadow:0 8px 18px rgba(255,105,53,.22)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-recommend-loading .qwenpaw-modal-content,
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-recommend-results .qwenpaw-modal-content { border-radius:12px!important; color:#30343a!important; background:#fff!important; box-shadow:0 20px 60px rgba(23,28,36,.24)!important; }
    .mb-chapter-recommend-loading .qwenpaw-modal-body { display:grid; justify-items:center; gap:12px; padding:34px 30px!important; text-align:center; }
    .mb-chapter-recommend-loading h3 { margin:4px 0 0; font-size:19px; }
    .mb-chapter-recommend-loading p { margin:0; color:#676b72; line-height:1.7; }
    .mb-chapter-recommend-loading strong { margin-top:6px; color:#f06d42; }
    .mb-chapter-recommend-loading small { color:#94989f; }
    .mb-chapter-recommend-results .qwenpaw-modal-body { display:grid; gap:14px; max-height:72vh; overflow:auto; padding:20px 24px 24px!important; }
    .mb-chapter-recommend-results .qwenpaw-modal-body > p { margin:0; color:#747981; text-align:center; }
    .mb-chapter-recommend-results .mb-chapter-choice-card { min-height:112px; }

    .mb-outline-cards { display:grid; gap:20px; }
    .mb-outline-empty { display:flex; min-height:410px; flex-direction:column; align-items:center; justify-content:center; gap:9px; border:1px solid #eceef1; border-radius:11px; color:#a3a7ad; background:#fff; box-shadow:0 5px 16px rgba(34,40,50,.05); }
    .mb-outline-empty > .qwenpawicon { margin-bottom:3px; color:#ff7548; font-size:42px; }
    .mb-outline-empty strong { color:#8d9198; font-size:14px; font-weight:500; }
    .mb-outline-empty span { color:#b7bac0; font-size:11px; }
    .mb-outline-workspace { display:grid; min-height:620px; min-width:0; gap:0; background:transparent; }
    .mb-outline-workspace > .mb-outline-selection-review-host,.mb-outline-workspace > .mb-outline-wizard { min-width:0; padding:6px 0 0; }
    .mb-outline-step-stage { position:relative; min-width:0; }
    .mb-outline-inline-progress { position:absolute; z-index:4; display:grid; inset:0; place-content:center; justify-items:center; gap:8px; border:1px solid rgba(255,190,164,.82); border-radius:16px; padding:24px; background:rgba(255,253,252,.94); box-shadow:0 10px 30px rgba(62,45,37,.1); text-align:center; backdrop-filter:blur(4px); }
    .mb-outline-inline-progress>strong { color:#d95830; font-size:16px; }
    .mb-outline-inline-progress>span { max-width:440px; color:#6e7279; font-size:12px; line-height:1.65; }
    .mb-outline-footer.mb-outline-workspace-footer { position:static; margin:0; padding:4px 0 0; background:transparent; }
    .mb-outline-workspace-footer>.qwenpaw-btn:first-child:not(:last-child) { width:30%; }
    html body .mb-outline-workspace-footer>button.qwenpaw-btn:not(.anw-primary-button) { color:#4a4d52!important; border-color:#e2e3e6!important; background:#fff!important; box-shadow:none!important; }
    html body .mb-outline-workspace-footer>button.qwenpaw-btn.anw-primary-button { min-height:50px; flex:1; border-width:0!important; border-color:transparent!important; border-radius:11px; color:#fff!important; background:#ff7548!important; box-shadow:0 8px 18px rgba(255,117,72,.2)!important; font-size:15px; font-weight:700; }
    html body .mb-outline-workspace-footer>button.qwenpaw-btn.anw-primary-button:hover:not(:disabled) { background:#f3683c!important; transform:translateY(-1px); }
    html body .mb-outline-workspace-footer>button.qwenpaw-btn.anw-primary-button:disabled { color:#fff!important; background:#ffc6b3!important; box-shadow:none!important; opacity:.78; }
    .mb-outline-card { min-height:190px; border:1px solid #f0e6df; border-radius:10px; padding:22px 26px; background:#fffaf7; }
    .mb-outline-card > header { display:flex; align-items:center; justify-content:space-between; gap:16px; }
    .mb-outline-card h3 { position:relative; margin:0; padding-left:16px; font-size:19px; }
    .mb-outline-card h3::before { position:absolute; top:2px; bottom:2px; left:0; width:4px; border-radius:3px; background:#ff7548; content:""; }
    .mb-outline-card .qwenpaw-btn { color:#777c84!important; }
    .mb-outline-card > p { margin:28px 14px 0; color:#4c5057; font-size:15px; line-height:2; white-space:pre-wrap; }

    .mb-top-tabs { display:flex; align-self:stretch; align-items:flex-end; gap:26px; }
    .mb-top-tabs > button { position:relative; border:0; padding:8px 2px 15px; color:#777b83; background:transparent; cursor:pointer; font-size:15px; font-weight:650; }
    .mb-top-tabs > button.is-active { color:#f06e43; }
    .mb-top-tabs > button:focus-visible { outline:2px solid #ff7548; outline-offset:-2px; }
    .mb-top-tabs > button.is-active::after { position:absolute; bottom:0; left:50%; width:24px; height:3px; border-radius:3px; background:#ff7548; content:""; transform:translateX(-50%); }
    .mb-top-tabs.is-four { gap:32px; }
    .mb-top-tabs.is-settings { border-radius:9px; padding:3px; background:#fafafa; }
    .mb-top-tabs.is-settings > button { border:1px solid transparent; border-radius:8px; padding-bottom:0!important; }
    .mb-top-tabs.is-settings > button.is-active { border-color:#ff7548; background:#fff; box-shadow:0 2px 8px rgba(26,32,42,.06); }
    .mb-top-tabs.is-settings > button.is-active::after { display:none; }
    .mb-role-list { display:grid; gap:18px; }
    .mb-role-section { border-radius:8px; padding:18px 18px 24px; background:#fafafa; }
    .mb-role-section.is-supporting { background:#fafafa; }
    .mb-role-section .mb-subtitle-row h3 { display:flex; align-items:center; gap:7px; }
    .mb-role-section .mb-subtitle-row h3::before { width:4px; height:20px; border-radius:3px; background:#ff7548; content:""; }
    .mb-role-section.is-supporting .mb-subtitle-row h3::before { background:#5c7cea; }
    .mb-role-section .mb-subtitle-row h3 span { color:#969aa1; font-size:12px; font-weight:500; }
    .mb-role-section .mb-subtitle-row .qwenpaw-btn { color:#fff!important; border:0!important; border-radius:7px!important; background:#ff7548!important; box-shadow:0 5px 12px rgba(255,117,72,.2)!important; }
    .mb-role-section.is-supporting .mb-subtitle-row .qwenpaw-btn { background:#5c7cea!important; box-shadow:0 5px 12px rgba(92,124,234,.2)!important; }
    .mb-role-grid { display:flex; flex-wrap:wrap; gap:14px; }
    .mb-role-card { position:relative; display:flex; width:116px; min-height:124px; flex:0 0 116px; align-items:stretch; border:1px solid #eee7e3; border-radius:9px; padding:13px 10px 10px; background:#fff; box-shadow:0 3px 10px rgba(31,41,55,.04); }
    .mb-role-section.is-supporting .mb-role-card { border-color:#e3e6fa; }
    .mb-role-card-main { display:flex; min-width:0; flex:1; flex-direction:column; align-items:center; gap:8px; border:0; padding:0; background:transparent; cursor:pointer; text-align:center; }
    .mb-role-avatar { display:grid; width:46px; height:46px; flex:0 0 auto; place-items:center; border-radius:50%; color:#fff; background:#ff7548; font-weight:750; }
    .is-supporting .mb-role-avatar { background:#6b7ce7; }
    .mb-role-copy { display:grid; width:100%; min-width:0; gap:5px; }
    .mb-role-copy strong,.mb-role-copy small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .mb-role-copy strong { color:#343840; font-size:14px; }
    .mb-role-copy small { color:#969aa1; }
    .mb-role-card > .qwenpaw-btn { position:absolute; top:5px; right:5px; width:24px; min-width:24px; padding:0!important; color:#ff9b7b!important; }
    .mb-inline-empty { display:grid; min-height:86px; place-items:center; border:1px dashed rgba(145,149,158,.3); border-radius:7px; color:#a0a4ab; }
    .mb-relationship-panel,.mb-relationship-workspace { display:grid; gap:16px; min-width:0; }
    .mb-relationship-workspace { position:relative; gap:12px; }
    .mb-relation-heading { display:grid; justify-items:center; gap:5px; text-align:center; }
    .mb-relation-heading h3 { margin:0; color:#30343b; font-size:18px; }
    .mb-relation-heading p { margin:0; color:#969aa1; font-size:12px; }
    .mb-relation-ai-status { display:flex; width:100%; min-width:0; min-height:40px; align-items:center; gap:8px; border:1px solid #dce9e2; border-radius:8px; padding:6px 8px 6px 10px; color:#39745a; background:#f7fbf8; box-shadow:none; text-align:left; }
    .mb-relation-ai-status.is-syncing { border-color:#f0ddc9; color:#b7653d; background:#fff9f4; }
    .mb-relation-ai-status.is-error { border-color:#f3d5d5; color:#b34f4f; background:#fff8f8; }
    .mb-relation-ai-icon { display:grid; width:20px; flex:0 0 20px; place-items:center; font-size:15px; }
    .mb-relation-ai-copy { display:flex; min-width:0; flex:1; align-items:center; gap:8px; }
    .mb-relation-ai-copy strong,.mb-relation-ai-copy small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .mb-relation-ai-copy strong { flex:0 0 auto; color:inherit; font-size:12px; }
    .mb-relation-ai-copy small { min-width:0; flex:1; color:#7f9187; font-size:10px; }
    .mb-relation-ai-status.is-syncing small { color:#a58873; }
    .mb-relation-ai-status.is-error small { color:#9c7474; }
    .mb-relation-ai-status .qwenpaw-btn { flex:0 0 auto; color:inherit!important; }
    .mb-relation-loading { display:flex; min-height:520px; align-items:center; justify-content:center; gap:10px; border:1px solid #e5e7ea; border-radius:10px; color:#8a8f97; background:#fcfcfd; }
    .mb-relation-overlay-stack { position:sticky; z-index:6; top:8px; display:grid; gap:8px; }
    .mb-relation-overlay-stack > .qwenpaw-alert { max-width:min(520px,100%); justify-self:end; border-color:#f1dfb8; padding:7px 11px; background:rgba(255,251,241,.95); box-shadow:0 4px 16px rgba(54,49,40,.07); backdrop-filter:blur(8px); }
    .mb-relation-overlay-stack > .qwenpaw-alert .qwenpaw-alert-content { display:flex; min-width:0; align-items:center; gap:7px; }
    .mb-relation-overlay-stack > .qwenpaw-alert .qwenpaw-alert-message { margin:0; white-space:nowrap; }
    .mb-relation-overlay-stack > .qwenpaw-alert .qwenpaw-alert-description { overflow:hidden; color:#8d7657; text-overflow:ellipsis; white-space:nowrap; }
    .mb-relation-toolbar { position:static; display:grid; min-width:0; gap:8px; border:1px solid #e6e8ec; border-radius:10px; padding:9px 10px; background:rgba(255,255,255,.97); box-shadow:0 5px 18px rgba(35,41,51,.06); backdrop-filter:blur(10px); }
    .mb-relation-filter-tools { display:grid; min-width:0; grid-template-columns:minmax(180px,1.55fr) minmax(112px,.8fr) minmax(112px,.8fr); gap:8px; }
    .mb-relation-toolbar .qwenpaw-select { width:100%; min-width:0; }
    .mb-relation-toolbar .mb-relation-character-search { width:100%; }
    .mb-relation-edit-tools { display:flex; min-width:0; align-items:center; gap:8px; }
    .mb-relation-toolbar-spacer { min-width:10px; flex:1; }
    html body .mb-relationship-workspace .mb-relation-toolbar .qwenpaw-select .qwenpaw-select-selector { min-height:36px!important; align-items:center!important; border:1px solid #e2e5ea!important; border-radius:8px!important; color:#3f4650!important; background-color:#fff!important; background-image:none!important; box-shadow:none!important; }
    html body .mb-relationship-workspace .mb-relation-toolbar .qwenpaw-select-selection-item { color:#3f4650!important; }
    html body .mb-relationship-workspace .mb-relation-toolbar .qwenpaw-select-selection-placeholder { color:#969ca5!important; }
    html body .mb-relationship-workspace .mb-relation-toolbar .qwenpaw-select-arrow,.mb-relation-toolbar .qwenpaw-select-clear { color:#7c838d!important; background:#fff!important; }
    html body .mb-relationship-workspace .mb-relation-toolbar .qwenpaw-select:not(.qwenpaw-select-disabled):hover .qwenpaw-select-selector { border-color:#ffb397!important; }
    html body .mb-relationship-workspace .mb-relation-toolbar .qwenpaw-select-focused .qwenpaw-select-selector { border-color:#ff9a73!important; box-shadow:0 0 0 3px rgba(255,117,72,.16)!important; }
    html body .mb-relationship-workspace .mb-relation-toolbar button.qwenpaw-btn:not(.anw-primary-button) { min-height:32px; border-color:#e2e5ea!important; color:#59616c!important; background-color:#fff!important; background-image:none!important; box-shadow:none!important; }
    html body .mb-relationship-workspace .mb-relation-toolbar button.qwenpaw-btn:not(.anw-primary-button):hover { border-color:#ff9a73!important; color:#e86e45!important; background-color:#fff8f4!important; }
    html body .mb-relationship-workspace .mb-relation-toolbar button.qwenpaw-btn.anw-primary-button { border-color:transparent!important; color:#fff!important; background:linear-gradient(100deg,#ff6b35,#ff8c5e)!important; box-shadow:0 5px 12px rgba(255,110,66,.18)!important; }
    html body div.qwenpaw-select-dropdown.mb-relation-filter-dropdown { border:1px solid #e5e8ec!important; border-radius:9px!important; color:#3f4650!important; background-color:#fff!important; background-image:none!important; box-shadow:0 10px 28px rgba(31,38,49,.14)!important; }
    html body div.qwenpaw-select-dropdown.mb-relation-filter-dropdown .qwenpaw-select-item { color:#3f4650!important; background-color:#fff!important; }
    html body div.qwenpaw-select-dropdown.mb-relation-filter-dropdown .qwenpaw-select-item-option-content { color:#3f4650!important; }
    html body div.qwenpaw-select-dropdown.mb-relation-filter-dropdown .qwenpaw-select-item-option-active:not(.qwenpaw-select-item-option-disabled) { background-color:#fff7f3!important; }
    html body div.qwenpaw-select-dropdown.mb-relation-filter-dropdown .qwenpaw-select-item-option-selected:not(.qwenpaw-select-item-option-disabled) { color:#e86e45!important; background-color:#fff0e9!important; font-weight:650!important; }
    .mb-relation-legacy-chip { display:inline-flex; min-height:30px; align-items:center; gap:5px; border:1px solid #f0dfbc; border-radius:999px; padding:4px 9px; color:#9a7434; background:#fffbf2; cursor:pointer; font-size:11px; white-space:nowrap; }
    .mb-relation-legacy-chip:hover,.mb-relation-legacy-chip:focus-visible,.mb-relation-legacy-chip.is-active { border-color:#e3b45e; color:#875f1d; background:#fff4d9; outline:0; }
    .mb-relation-view-tools { display:flex; min-width:0; align-items:center; gap:4px; margin-left:auto; border:1px solid #e8eaee; border-radius:8px; padding:3px; background:#f7f8fa; }
    .mb-relation-view-tools .qwenpaw-btn { width:30px; min-width:30px; height:30px; padding:0!important; }
    .mb-relation-scale { width:44px; color:#69717c; font-size:11px; font-variant-numeric:tabular-nums; text-align:center; }
    .mb-relation-add { min-width:100px; }
    .mb-relation-stage { position:relative; height:540px; min-height:540px; border:1px solid #e5e7ea; border-radius:10px; overflow:hidden; background:linear-gradient(#fdfdfe,#fbfbfc); }
    .mb-relation-network { width:100%; height:100%; outline:0; }
    .mb-relation-network:focus-visible { box-shadow:inset 0 0 0 2px rgba(255,117,72,.58); }
    .mb-relation-layout-actions { position:absolute; z-index:3; right:12px; bottom:12px; display:flex; align-items:center; gap:6px; border:1px solid #ffd6c6; border-radius:9px; padding:5px 6px 5px 10px; color:#c65e3b; background:rgba(255,250,247,.97); box-shadow:0 5px 16px rgba(48,43,40,.1); font-size:11px; backdrop-filter:blur(8px); }
    html body .mb-relation-layout-actions .qwenpaw-btn:not(.anw-primary-button) { border-color:#eadfd9!important; color:#6e625d!important; background:#fff!important; box-shadow:none!important; }
    html body .mb-relation-layout-actions .qwenpaw-btn.anw-primary-button { border-color:transparent!important; color:#fff!important; background:#ff7548!important; box-shadow:none!important; }
    .mb-relation-filter-empty { position:absolute; z-index:2; top:50%; left:50%; border:1px solid #e5e7ea; border-radius:8px; padding:9px 13px; color:#888d95; background:rgba(255,255,255,.94); transform:translate(-50%,-50%); }
    .mb-relation-accessible-list { display:grid; gap:11px; border:1px solid #e8eaed; border-radius:10px; padding:15px 16px 16px; background:#fff; }
    .mb-relation-accessible-list > header { display:flex; align-items:end; justify-content:space-between; gap:16px; }
    .mb-relation-accessible-list > header > div { display:flex; align-items:center; gap:8px; }
    .mb-relation-accessible-list h4 { margin:0; color:#3b3f46; font-size:14px; }
    .mb-relation-accessible-list header span,.mb-relation-accessible-list header small { color:#969ba3; font-size:11px; }
    .mb-relation-accessible-list ul { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; margin:0; padding:0; list-style:none; }
    .mb-relation-accessible-list li { min-width:0; }
    .mb-relation-accessible-list li > button { display:grid; width:100%; min-width:0; gap:4px; border:1px solid #ebecef; border-radius:8px; padding:10px 11px; color:#454950; background:#fcfcfd; cursor:pointer; text-align:left; }
    .mb-relation-accessible-list li > button:hover,.mb-relation-accessible-list li > button:focus-visible { border-color:#ffb49a; background:#fff9f6; outline:0; }
    .mb-relation-accessible-list li span,.mb-relation-accessible-list li strong,.mb-relation-accessible-list li small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .mb-relation-accessible-list li span { color:#8c9199; font-size:11px; }
    .mb-relation-accessible-list li strong { font-size:13px; }
    .mb-relation-accessible-list li small { color:#a0a4aa; }
    .mb-relation-accessible-list li .mb-relation-list-title { display:flex; min-width:0; align-items:center; gap:7px; color:#454950; }
    .mb-relation-list-title strong { min-width:0; flex:1; }
    .mb-relation-list-title em { flex:0 0 auto; border:1px solid #dbe9e1; border-radius:999px; padding:1px 6px; color:#4f8268; background:#f3faf6; font-size:9px; font-style:normal; font-weight:650; }
    .mb-relation-list-title em.is-manual { border-color:#f0ded2; color:#bd6848; background:#fff8f4; }
    .mb-relation-direction.is-legacy_unspecified { color:#b46c41!important; }

    html .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .qwenpaw-modal-content { overflow:hidden; border-radius:12px!important; padding:0!important; color:#34383f!important; background:#fff!important; box-shadow:0 22px 64px rgba(28,34,43,.25)!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .qwenpaw-modal-header { margin:0!important; border-bottom:1px solid #eceef1!important; padding:18px 24px!important; background:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .qwenpaw-modal-body { max-height:min(620px,calc(100vh - 245px)); overflow:auto; padding:0!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .qwenpaw-modal-footer { margin:0!important; border-top:1px solid #eceef1!important; padding:14px 24px!important; background:#fff!important; }
    .mb-relationship-editor-title { display:flex; align-items:baseline; gap:12px; }
    .mb-relationship-editor-title strong { color:#24282f; font-size:19px; }
    .mb-relationship-editor-title span { color:#9a9ea5; font-size:12px; font-weight:400; }
    .mb-relationship-editor-body { display:grid; gap:14px; padding:20px 24px 24px; }
    .mb-relationship-editor-heading,.mb-relationship-editor-footer { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    .mb-relationship-editor-heading > strong { font-size:14px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .mb-relationship-editor-heading .qwenpaw-btn { color:#ef7045!important; border-color:#ffb69d!important; background:#fff8f4!important; box-shadow:none!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .mb-relationship-editor-footer > .qwenpaw-btn.anw-primary-button { min-width:164px; border-color:transparent!important; color:#fff!important; background:linear-gradient(100deg,#ff6b35,#ff8c5e)!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .mb-relationship-editor-footer > .qwenpaw-btn.anw-primary-button:disabled { color:#a0a4aa!important; background:#eceef1!important; box-shadow:none!important; }
    .mb-relationship-editor-empty { display:grid; min-height:138px; place-items:center; border:1px dashed #dfe2e6; border-radius:9px; color:#969ba2; background:#fafafa; }
    .mb-relationship-draft-list { display:grid; gap:12px; }
    .mb-relationship-draft { display:grid; gap:13px; border:1px solid #e6e8eb; border-radius:9px; padding:15px 16px 17px; background:#fcfcfd; }
    .mb-relationship-draft.is-focused { border-color:#ff9e7c; box-shadow:0 0 0 3px rgba(255,117,72,.1); }
    .mb-relationship-draft > header { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:12px; border-bottom:1px solid #ededef; padding-bottom:10px; }
    .mb-relationship-draft > header strong { overflow:hidden; color:#3f434a; text-overflow:ellipsis; white-space:nowrap; }
    .mb-relationship-draft > header .qwenpaw-btn { color:#e36b45!important; }
    .mb-relationship-draft-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
    .mb-relationship-draft label { display:grid; min-width:0; gap:7px; color:#3f434a; font-size:13px; font-weight:650; }
    .mb-relationship-draft label > .qwenpaw-select { width:100%; }
    .mb-relationship-direction .qwenpaw-radio-group { display:flex; flex-wrap:wrap; gap:16px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .qwenpaw-radio-inner { border-color:#bfc3c9!important; background:#fff!important; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .qwenpaw-radio-checked .qwenpaw-radio-inner { border-color:#ff7548!important; background:#ff7548!important; }
    .mb-relationship-direction small { color:#b85c39; font-weight:500; }

    .mb-storyline-board { min-height:620px; }
    .mb-large-empty { display:grid; min-height:520px; place-content:center; justify-items:center; gap:18px; border:1px solid #eceef1; border-radius:10px; background:#fcfcfd; }
    .mb-storyline-timeline { position:relative; display:grid; gap:18px; padding:10px 0 10px 62px; }
    .mb-storyline-timeline::before { position:absolute; top:15px; bottom:15px; left:27px; width:2px; background:#ffdbcd; content:""; }
    .mb-storyline-card { position:relative; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; border:1px solid #ece6e2; border-radius:10px; padding:18px 16px 16px 20px; background:#fffaf7; }
    .mb-timeline-index { position:absolute; top:25px; left:-52px; display:grid; width:34px; height:34px; place-items:center; border:3px solid #fff; border-radius:50%; color:#fff; background:#ff7548; box-shadow:0 2px 8px rgba(255,117,72,.3); font-weight:750; }
    .mb-storyline-content header { display:flex; align-items:center; justify-content:space-between; gap:20px; }
    .mb-storyline-content h3 { margin:0; font-size:17px; }
    .mb-storyline-content header span { color:#f06d42; font-weight:700; }
    .mb-storyline-content p { display:-webkit-box; margin:10px 0 13px; overflow:hidden; color:#646970; line-height:1.8; white-space:pre-wrap; -webkit-box-orient:vertical; -webkit-line-clamp:7; }
    .mb-card-actions { display:flex; align-items:flex-start; }
    .mb-card-actions .qwenpaw-btn:not(.qwenpaw-btn-dangerous) { color:#686d74!important; border-color:#e2e4e8!important; background:transparent!important; box-shadow:none!important; }

    .mb-template-settings { display:grid; gap:18px; }
    .mb-template-card { border:1px solid #e8e9ec; border-radius:10px; overflow:hidden; background:#fff; }
    .mb-template-card > header { display:flex; align-items:center; justify-content:space-between; gap:16px; border-bottom:1px solid #eceef1; padding:18px 22px; background:#fafafa; }
    .mb-template-card > header h3 { margin:0 0 5px; font-size:18px; }
    .mb-template-card > header span { color:#90949b; font-size:13px; }
    .mb-template-card > section { padding:20px 22px; }
    .mb-template-card > section strong { display:block; margin-bottom:8px; color:#3e4249; }
    .mb-template-card > section p { margin:0; color:#686d74; line-height:1.8; white-space:pre-wrap; }
    .mb-template-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px; border-top:1px solid #eceef1; background:#eceef1; }
    .mb-template-grid > div { display:grid; gap:7px; min-height:82px; padding:15px 22px; background:#fff; }
    .mb-template-grid span { color:#91959c; font-size:12px; }
    .mb-template-grid strong { color:#454950; font-size:14px; line-height:1.6; }
    .mb-foreshadow-summary { display:grid; grid-template-columns:repeat(3,150px); justify-content:center; align-items:center; gap:18px; min-height:112px; margin-bottom:22px; border-radius:10px; background:#fff7f3; }
    .mb-foreshadow-summary > span { display:grid; min-height:72px; place-content:center; justify-items:center; color:#8c9097; font-size:13px; }
    .mb-foreshadow-summary strong { color:#f06e43; font-size:28px; }
    .mb-foreshadow-summary > span:nth-child(2) strong { color:#f59e0b; }
    .mb-foreshadow-summary > span:nth-child(3) strong { color:#42aa62; }
    .mb-foreshadow-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
    .mb-foreshadow-card { border:1px solid #e8e9ec; border-radius:9px; padding:18px; background:#fff; }
    .mb-foreshadow-card > header { display:flex; align-items:center; justify-content:space-between; gap:12px; }
    .mb-foreshadow-card h3 { margin:0; font-size:17px; }
    .mb-foreshadow-card header span { border-radius:999px; padding:4px 9px; color:#916f2b; background:#fff3d5; font-size:11px; font-weight:700; }
    .mb-foreshadow-card header span.is-active { color:#d35d35; background:#fff0e9; }
    .mb-foreshadow-card header span.is-resolved { color:#16805f; background:#e8f8f1; }
    .mb-foreshadow-card header span.is-dropped { color:#7b7f87; background:#eff0f2; }
    .mb-foreshadow-card > p { min-height:50px; margin:14px 0; color:#62676e; line-height:1.75; white-space:pre-wrap; }
    .mb-foreshadow-progress { border-radius:7px; padding:10px 11px; color:#777b82; background:#f7f7f8; font-size:12px; line-height:1.7; }
    .mb-foreshadow-progress strong { color:#62666d; }
    .mb-foreshadow-card .mb-card-actions { gap:10px; justify-content:stretch; margin-top:12px; }
    .mb-foreshadow-card .mb-card-actions .qwenpaw-btn { min-height:38px; flex:1; justify-content:center; border-radius:7px!important; background:#f7f7f8!important; }
    .mb-foreshadow-card .mb-card-actions .qwenpaw-btn-dangerous { color:#ef7044!important; background:#fff3dc!important; }

    .mb-cover-edit-stack { display:grid; gap:14px; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-cover-edit-modal .qwenpaw-modal-content { border-radius:10px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-cover-edit-modal .qwenpaw-modal-header { padding:28px 16px 20px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-cover-edit-modal .qwenpaw-modal-body { padding:24px 0!important; }
    .mb-cover-edit-modes { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
    .mb-cover-edit-modes > button { display:grid; min-height:88px; place-content:center; justify-items:center; gap:8px; border:1px solid #e2e4e7; border-radius:9px; color:#565a61; background:#fff; cursor:pointer; }
    .mb-cover-edit-modes > button .qwenpawicon { color:#78808a; font-size:23px; }
    .mb-cover-edit-modes > button.is-active { border:2px solid #ff7548; color:#ef6d42; background:#fff8f4; }
    .mb-cover-edit-modes > button.is-active .qwenpawicon { color:#ff7548; }
    .mb-cover-edit-preview { display:grid; min-height:218px; place-content:center; justify-items:center; gap:10px; overflow:hidden; border-radius:9px; color:#91959c; background:#fafafa; text-align:center; }
    .mb-cover-edit-preview > span { display:grid; justify-items:center; gap:8px; }
    .mb-cover-edit-preview > span > .qwenpawicon { color:#c6c9ce; font-size:42px; }
    .mb-cover-edit-preview small { color:#aa795f; }
    .mb-cover-edit-preview input { display:none; }
    .mb-cover-edit-preview.is-upload { border:1px dashed #dadddf; cursor:pointer; }
    .mb-cover-edit-preview.has-image { min-height:240px; }
    .mb-cover-edit-preview img { width:150px; height:200px; border-radius:8px; object-fit:cover; box-shadow:0 7px 18px rgba(30,36,46,.15); }
    .mb-cover-edit-stack > .qwenpaw-btn { min-height:48px; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-cover-edit-modal .mb-cover-edit-stack > .qwenpaw-btn:not(.anw-primary-button) { color:#4a4d52!important; border-color:#e2e3e6!important; background:#fff!important; box-shadow:none!important; }

    html .qwenpaw-modal-root .qwenpaw-modal.mb-foreshadow-modal .qwenpaw-modal-content { border-radius:20px!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-foreshadow-modal .qwenpaw-modal-header { padding:24px 0 20px!important; }
    .mb-foreshadow-modal .mb-form-stack { gap:20px; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-foreshadow-modal .qwenpaw-input-affix-wrapper:not(.qwenpaw-input-textarea-affix-wrapper),
    html .qwenpaw-modal-root .qwenpaw-modal.mb-foreshadow-modal .qwenpaw-select-selector { min-height:44px!important; align-items:center; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-foreshadow-modal .mb-form-stack > .qwenpaw-btn { min-height:54px; }

    .mb-field { display:grid; min-width:0; gap:7px; color:#3d4148; }
    .mb-field-label { color:#3d4148; font-size:13px; font-weight:680; }
    .mb-field-hint { color:#999da4; font-size:11px; }
    .mb-form-stack { display:grid; gap:16px; }
    .mb-form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
    .mb-form-grid-three { grid-template-columns:2fr 1fr 1fr; }
    .mb-character-demographics { grid-template-columns:repeat(2,minmax(0,1fr)); }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-entity-modal .mb-character-identity-input.qwenpaw-input { min-height:64px!important; max-height:220px!important; resize:vertical; overflow:auto; }
    .mb-entity-modal .qwenpaw-select,.mb-small-modal .qwenpaw-select,.mb-outline-modal .qwenpaw-select { width:100%; }
    html .qwenpaw-modal-root .anw-modal .qwenpaw-select-selector { color:#34383f!important; border-color:#dfe2e6!important; background:#fff!important; }
    html .qwenpaw-modal-root .anw-modal .qwenpaw-select-selection-placeholder { color:#a1a5ac!important; }
    html .qwenpaw-modal-root .anw-modal h2,
    html .qwenpaw-modal-root .anw-modal h3 { color:#1e2127!important; }
    html .qwenpaw-select-dropdown { color:#34383f!important; background:#fff!important; }
    html .qwenpaw-select-dropdown .qwenpaw-select-item { color:#34383f!important; }
    html .qwenpaw-select-dropdown .qwenpaw-select-item-option-selected { background:#fff0e9!important; }

    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal .qwenpaw-checkbox-inner { border-color:#c8cbd0!important; background:#fff!important; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-chapter-wizard-modal .qwenpaw-checkbox-checked .qwenpaw-checkbox-inner { border-color:#2f80ed!important; background:#2f80ed!important; }

    .mb-outline-modal { width:min(680px,calc(100vw - 32px))!important; max-width:calc(100vw - 32px); padding-bottom:0!important; }
    .mb-outline-modal .qwenpaw-modal-content { overflow:hidden!important; border:1px solid #ebe6e2; border-radius:22px!important; padding:0!important; background:#fff!important; box-shadow:0 28px 80px rgba(30,24,20,.24),0 8px 24px rgba(30,24,20,.1)!important; }
    .mb-outline-modal .qwenpaw-modal-header { min-height:70px; margin:0!important; border-bottom:1px solid #f0ebe7; padding:18px 58px 16px 24px!important; background:linear-gradient(180deg,#fffaf7 0%,#fff 100%)!important; }
    .mb-outline-modal .qwenpaw-modal-body { max-height:min(760px,calc(100dvh - 104px)); overflow-y:auto; overscroll-behavior:contain; scrollbar-gutter:stable; padding:18px 24px 24px!important; }
    .mb-outline-modal .qwenpaw-modal-close { top:16px!important; right:16px!important; width:36px; height:36px; border-radius:10px; transform:none; }
    .mb-outline-modal .qwenpaw-modal-close:hover { color:#f06d42!important; background:#fff0e9!important; }
    .mb-outline-generation-panel { display:grid; min-height:260px; place-content:center; justify-items:center; gap:20px; border:1px solid #f0e7e2; border-radius:16px; padding:34px 24px; background:radial-gradient(circle at 50% 44%,rgba(255,112,67,.08),transparent 145px),linear-gradient(180deg,#fffdfc 0%,#fbfaf9 100%); box-shadow:inset 0 1px 0 rgba(255,255,255,.9); }
    .mb-outline-generation-panel .qwenpaw-spin { color:#e66239!important; }
    .mb-outline-generation-panel .qwenpaw-spin-dot-item { background:#ff7043!important; }
    .mb-outline-generation-status { display:grid; min-width:300px; max-width:min(460px,calc(100vw - 96px)); justify-items:center; gap:6px; padding:10px 18px; color:#34383f; }
    .mb-outline-generation-status strong { color:#d95830; font-size:16px; font-weight:760; line-height:1.45; }
    .mb-outline-generation-status > span { color:#5f646c; font-size:12px; font-weight:550; line-height:1.55; }
    .mb-outline-generation-status small { color:#989ca3; font-size:11px; font-weight:500; line-height:1.5; }
    .mb-outline-cost-modal .qwenpaw-modal-content { border-radius:10px!important; padding:20px 22px!important; }
    .mb-outline-cost-modal .qwenpaw-modal-header { margin-bottom:14px!important; }
    .mb-outline-cost-copy h3 { margin:0 0 8px; color:#24272d; font-size:18px; }
    .mb-outline-cost-copy p { margin:0; color:#74787f; font-size:13px; line-height:1.8; }
    .mb-outline-candidate-modal .qwenpaw-modal-content { overflow:hidden; border:1px solid #eee6e1; border-radius:16px!important; box-shadow:0 22px 60px rgba(43,31,24,.2)!important; }
    .mb-outline-candidate-body { display:grid; gap:16px; max-height:min(62vh,680px); overflow:auto; padding:2px; }
    .mb-outline-candidate-text { padding:18px 20px; border:1px solid #eee8e4; border-radius:12px; background:#fffdfa; color:#303238; font-size:14px; line-height:1.9; white-space:pre-wrap; }
    .mb-outline-candidate-characters { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .mb-outline-candidate-character { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:6px 10px; margin:0; padding:14px 16px; border:1px solid #eee8e4; border-radius:12px; background:#fffdfa; }
    .mb-outline-candidate-character > strong { min-width:0; color:#2f3135; font-size:15px; }
    .mb-outline-candidate-character > span { color:#ff7043; font-size:12px; }
    .mb-outline-candidate-character > p { grid-column:1/-1; margin:0; color:#686c73; font-size:13px; line-height:1.65; }
    html .qwenpaw-modal-root .qwenpaw-modal.mb-outline-modal .mb-outline-footer .qwenpaw-btn:not(.anw-primary-button) { color:#4a4d52!important; border-color:#e2e3e6!important; background:#fff!important; box-shadow:none!important; }
    .mb-outline-modal-title { display:flex; min-width:0; align-items:center; gap:12px; }
    .mb-outline-modal-title-icon { display:grid; width:36px; height:36px; flex:0 0 36px; place-items:center; border:1px solid #ffd9c9; border-radius:11px; color:#f06d42; background:#fff0e9; font-size:18px; }
    .mb-outline-modal-title-copy { display:grid; min-width:0; gap:2px; }
    .mb-outline-modal-title-copy strong { color:#202329; font-size:19px; line-height:1.25; }
    .mb-outline-modal-title-copy small { overflow:hidden; color:#999da4; font-size:11px; font-weight:500; line-height:1.35; text-overflow:ellipsis; white-space:nowrap; }
    .mb-outline-wizard { display:grid; min-height:0; gap:16px; transform:none; }
    .mb-outline-steps { position:relative; display:flex; box-sizing:border-box; width:100%; justify-content:space-between; margin:0 0 2px; padding:0 8px; }
    .mb-outline-steps::before { position:absolute; z-index:0; top:15px; right:15px; left:15px; height:3px; background:#e6e7e9; content:""; }
    .mb-outline-steps::after { position:absolute; z-index:0; top:15px; left:10%; width:calc((var(--mb-step-progress,0))*20%); height:3px; background:#ff7548; content:""; }
    .mb-outline-step { position:relative; z-index:1; display:grid; width:30px; flex:0 0 30px; justify-items:center; gap:8px; color:#999da4; font-size:12px; }
    .mb-outline-step-dot { display:grid; width:30px; height:30px; place-items:center; border:2px solid #e1e3e6; border-radius:50%; color:#8d9198; background:#fff; font-weight:750; }
    .mb-outline-step.is-active,.mb-outline-step.is-complete { color:#f06d42; font-weight:700; }
    .mb-outline-step.is-active .mb-outline-step-dot,.mb-outline-step.is-complete .mb-outline-step-dot { border-color:#ff7548; color:#fff; background:#ff7548; box-shadow:0 4px 12px rgba(255,117,72,.24); }
    .mb-outline-step.is-complete::after { display:none; }
    .mb-outline-step-body { display:grid; min-height:260px; align-content:start; gap:12px; border:1px solid #eceef1; border-radius:16px; padding:24px; background:linear-gradient(180deg,#fcfcfd 0%,#fafafa 100%); box-shadow:inset 0 1px 0 rgba(255,255,255,.8); }
    .mb-outline-step-body > h3 { margin:0; color:#24272d; font-size:21px; line-height:1.3; text-align:center; }
    .mb-outline-step-body > p { max-width:520px; margin:0 auto 8px; color:#858a92; font-size:13px; line-height:1.7; text-align:center; }
    .mb-outline-heading-row { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:18px; margin-bottom:6px; }
    .mb-outline-heading-row > div { display:grid; min-width:0; gap:3px; }
    .mb-outline-heading-row>div>h3 { margin:0; color:#24272d; font-size:20px; line-height:1.35; }
    .mb-outline-heading-row>div>span { color:#969aa1; font-size:12px; line-height:1.55; }
    html body .mb-outline-heading-row > .qwenpaw-btn { flex:0 0 auto; border-color:#ffd3c3!important; color:#d85f38!important; background:#fff8f4!important; box-shadow:none!important; }
    .mb-outline-step-body>textarea.qwenpaw-input { min-height:240px; color:#34383f!important; border-color:#e0e2e5!important; background:#fff!important; font-size:14px; line-height:1.75; }
    .mb-outline-step-body>textarea.qwenpaw-input:focus { border-color:#ff7548!important; box-shadow:0 0 0 2px rgba(255,117,72,.1)!important; }
    .mb-outline-step-body.is-count { min-height:260px; place-items:center; align-content:center; padding:28px 24px; }
    .mb-outline-step-body.is-count>.qwenpaw-input-number { width:220px; margin-top:8px; border:1px solid #dfe2e6!important; border-radius:12px; background:#fff!important; box-shadow:0 8px 22px rgba(34,40,50,.08); transition:border-color .15s ease,box-shadow .15s ease; }
    .mb-outline-step-body.is-count>.qwenpaw-input-number:hover,.mb-outline-step-body.is-count>.qwenpaw-input-number-focused { border-color:#ff8b64!important; box-shadow:0 0 0 3px rgba(255,117,72,.1),0 8px 22px rgba(34,40,50,.08)!important; }
    .mb-outline-step-body.is-count>.qwenpaw-input-number .qwenpaw-input-number-input { height:56px; color:#202329!important; background:#fff!important; font-size:22px; font-weight:750; text-align:center; }
    .mb-count-hint { color:#999da4; font-size:11px; }
    .mb-outline-step-body.is-highlight>.mb-count-hint { margin-top:8px; }
    .mb-outline-success { display:grid; min-height:340px; justify-items:center; align-content:start; padding-top:28px; text-align:center; }
    .mb-outline-success-icon { display:grid; width:100px; height:100px; place-items:center; border-radius:50%; color:#fff; background:linear-gradient(145deg,#ff6a32,#ff875d); box-shadow:0 16px 28px rgba(255,117,72,.28); font-size:48px; }
    .mb-outline-success h3 { margin:34px 0 0; color:#202329; font-size:25px; }
    .mb-outline-success p { margin:18px 0 38px; color:#999da4; font-size:15px; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-outline-modal .mb-outline-success > button.qwenpaw-btn.anw-primary-button { width:100%; min-height:54px; border-width:0!important; border-color:transparent!important; border-radius:10px; color:#fff!important; background:linear-gradient(90deg,#ff6531,#ff875d)!important; box-shadow:0 10px 20px rgba(255,117,72,.24)!important; font-size:16px; font-weight:700; }
    .mb-manual-link { display:block; width:max-content; max-width:100%; margin:-2px auto 0; border:0; border-radius:8px; padding:7px 10px; color:#df6841; background:transparent; cursor:pointer; font-size:12px; font-weight:650; }
    .mb-manual-link:hover,.mb-manual-link:focus-visible { color:#c9502a; background:#fff2ec; outline:0; }
    .mb-manual-link:disabled { cursor:wait; opacity:.58; }
    .mb-outline-footer { position:sticky; z-index:3; bottom:-24px; display:flex; gap:12px; margin:0 -24px -24px; padding:14px 24px 24px; background:linear-gradient(180deg,rgba(255,255,255,.72) 0%,#fff 24%,#fff 100%); transform:none; }
    .mb-outline-footer > .qwenpaw-btn { height:50px; min-height:50px; border-radius:11px; }
    .mb-outline-footer > .qwenpaw-btn:first-child:not(:last-child) { width:34%; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-outline-modal .mb-outline-footer > button.qwenpaw-btn.anw-primary-button { min-height:50px; flex:1; appearance:none; border-width:0!important; border-style:none!important; border-color:transparent!important; outline:0!important; color:#fff!important; background:linear-gradient(100deg,#ff6938 0%,#ff865e 100%)!important; box-shadow:0 10px 22px rgba(255,105,56,.24)!important; font-size:15px; font-weight:700; }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-outline-modal .mb-outline-footer > button.qwenpaw-btn.anw-primary-button:hover:not(:disabled) { background:linear-gradient(100deg,#f85d2d 0%,#ff754d 100%)!important; box-shadow:0 12px 26px rgba(255,105,56,.3)!important; transform:translateY(-1px); }
    html body .qwenpaw-modal-root .qwenpaw-modal.mb-outline-modal .mb-outline-footer > button.qwenpaw-btn.anw-primary-button:disabled { color:#fff!important; background:linear-gradient(100deg,#ffc1aa 0%,#ffd0bd 100%)!important; box-shadow:none!important; opacity:.74; }
    .mb-outline-complete-label { letter-spacing:0; }
    .mb-outline-role-group { display:grid; gap:11px; }
    .mb-outline-role-group > strong { color:#3c4047; }
    .mb-outline-role-pills { display:flex; min-height:52px; flex-wrap:wrap; align-items:center; gap:10px; }
    .mb-role-pill { display:flex; align-items:center; border:1px solid #ffdbc9; border-radius:8px; color:#f06e43; background:#fff8f4; }
    .mb-role-pill.is-supporting { border-color:#dfe3ff; color:#6475dd; background:#f6f7ff; }
    .mb-role-pill > button { border:0; padding:8px 4px 8px 12px; color:inherit; background:transparent; cursor:pointer; font-weight:650; }
    .mb-role-pill > .mb-role-remove { padding:8px 9px 8px 3px; }
    .mb-add-role.qwenpaw-btn { color:#fff!important; border:0!important; background:#ff7548!important; box-shadow:0 4px 10px rgba(255,117,72,.2); }
    .mb-add-role.is-supporting.qwenpaw-btn { background:#6b62d7!important; box-shadow:0 4px 10px rgba(107,98,215,.2); }

    @media (max-height: 760px) {
      .mb-outline-modal .qwenpaw-modal-body { max-height:calc(100dvh - 80px); padding-top:14px!important; }
      .mb-outline-wizard { gap:12px; }
      .mb-outline-step-body,.mb-outline-step-body.is-count { min-height:224px; padding:20px 22px; }
      .mb-outline-footer { padding-top:10px; }
    }

    @media (max-width: 720px) {
      .mb-outline-workspace { min-height:0; }
      .mb-outline-workspace > .mb-outline-selection-review-host,.mb-outline-workspace > .mb-outline-wizard { padding-top:2px; }
      .mb-outline-heading-row { align-items:flex-start; }
      .mb-outline-heading-row > .qwenpaw-btn { min-width:40px; }
      .mb-outline-heading-row > .qwenpaw-btn > span:not(.qwenpaw-btn-icon) { display:none; }
      .mb-outline-workspace-footer { flex-wrap:wrap; }
      .mb-outline-workspace-footer>.qwenpaw-btn:first-child:not(:last-child) { width:100%; }
      .mb-outline-candidate-characters { grid-template-columns:1fr; }
      .mb-outline-modal { width:calc(100vw - 20px)!important; max-width:calc(100vw - 20px); }
      .mb-outline-modal .qwenpaw-modal-header { padding-left:18px!important; }
      .mb-outline-modal .qwenpaw-modal-body { padding-right:16px!important; padding-left:16px!important; }
      .mb-outline-modal-title-copy small { display:none; }
      .mb-outline-steps { padding-inline:2px; }
      .mb-outline-step { font-size:11px; }
      .mb-outline-step-body,.mb-outline-step-body.is-count { padding-right:16px; padding-left:16px; }
      .mb-outline-footer { margin-right:-16px; margin-left:-16px; padding-right:16px; padding-left:16px; }
    }

    @media (min-width: 2300px) {
      .mb-workbench { padding:34px 40px 42px; }
      .mb-panel-body { padding:24px 28px 44px; }
      .mb-relation-stage,.mb-relation-canvas { height:598px; }
      .mb-relation-stage { min-height:598px; }
    }

    @media (max-width: 980px) {
      .anw-library-grid { grid-template-columns:1fr; }
      .anw-project { grid-template-columns:220px minmax(0,1fr); padding:14px; }
      .anw-entity-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .mb-relation-toolbar-spacer { display:none; }
      .mb-relation-accessible-list ul { grid-template-columns:repeat(2,minmax(0,1fr)); }
      .mb-relationship-draft-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
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

      .anw-editor.has-chapter-tree,.anw-editor.has-chapter-tree.is-chapter-tree-collapsed { display:block; overflow:auto; }
      .anw-chapter-tree { display:none; }
      .anw-editor-content { height:auto; min-height:100%; overflow:visible; }
      .anw-editor-topbar { width:100%; flex-wrap:wrap; gap:6px; margin:0; transform:none; border:0; border-bottom:1px solid var(--anw-line); border-radius:0; padding:8px 10px; box-shadow:none; }
      .anw-editor.has-chapter-tree .anw-editor-topbar,
      .anw-workbench-frame[data-assistant-density="constrained"] .anw-editor.has-chapter-tree .anw-editor-topbar { width:100%; }
      .anw-editor-topbar > .qwenpaw-btn { min-width:0; flex:1 1 0; padding-inline:8px!important; }
      .anw-current-model-inline { order:10; width:100%; min-width:0; flex:1 0 100%; flex-direction:row; align-items:center; justify-content:space-between; gap:8px; }
      .anw-current-model-inline small,.anw-current-model-inline strong { max-width:48%; }
      .anw-editor-scroll { padding:0 0 112px; }
      .anw-editor-paper { min-height:100%; border:0; border-radius:0; padding:24px 20px 48px; box-shadow:none; }
      .anw-editor-title { font-size:22px; }
      .anw-editor-textarea { min-height:calc(100vh - 230px); font-size:16px; line-height:1.95; }
      .anw-editor-footer { right:12px; bottom:10px; left:12px; overflow-x:auto; justify-content:flex-start; }
      .anw-workflow-buttons { flex-wrap:nowrap; justify-content:flex-start; padding:7px; }
      .anw-workflow-buttons .qwenpaw-btn { flex:0 0 auto; }
      .mb-relation-overlay-stack { position:static; }
      .mb-relation-overlay-stack > .qwenpaw-alert { width:100%; max-width:none; justify-self:stretch; }
      .mb-relation-overlay-stack > .qwenpaw-alert .qwenpaw-alert-content { display:block; }
      .mb-relation-overlay-stack > .qwenpaw-alert .qwenpaw-alert-message,.mb-relation-overlay-stack > .qwenpaw-alert .qwenpaw-alert-description { white-space:normal; }
      .mb-relation-ai-copy { display:grid; gap:2px; }
      .mb-relation-toolbar { position:static; align-items:stretch; }
      .mb-relation-filter-tools { grid-template-columns:1fr; }
      .mb-relation-edit-tools { flex-wrap:wrap; }
      .mb-relation-toolbar .qwenpaw-select,.mb-relation-toolbar .mb-relation-character-search { width:100%; }
      .mb-relation-toolbar .mb-relation-scale { align-self:center; }
      .mb-relation-view-tools { order:2; margin-left:0; }
      .mb-relation-add { margin-left:auto; }
      .mb-relation-stage { height:430px; min-height:430px; }
      .mb-relation-accessible-list > header { align-items:start; flex-direction:column; gap:4px; }
      .mb-relation-accessible-list ul { grid-template-columns:1fr; }
      .mb-relationship-draft-grid { grid-template-columns:1fr; }
      .mb-relationship-direction .qwenpaw-radio-group { display:grid; }
      .mb-relationship-editor-body { padding:16px; }
      html .qwenpaw-modal-root .qwenpaw-modal.mb-relationship-editor-modal .qwenpaw-modal-footer { padding:12px 16px!important; }
    }
  `;
  document.head.appendChild(style);
}
