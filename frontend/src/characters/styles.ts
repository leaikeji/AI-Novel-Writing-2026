const STYLE_ID = "anw-character-workspace-styles";

export const CHARACTER_WORKSPACE_CSS = `
.anw-character-workspace-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: grid;
  place-items: center;
  padding: 24px 32px;
  background: rgba(15, 23, 42, 0.48);
}
.anw-character-workspace-dialog {
  --anw-character-surface: #ffffff;
  --anw-character-surface-muted: #f8fafc;
  --anw-character-text: #1f2937;
  --anw-character-text-strong: #252a32;
  --anw-character-text-muted: #64748b;
  --anw-character-border: #e5e7eb;
  --anw-character-control-border: #7c8798;
  --anw-character-accent: #ff7043;
  --anw-character-accent-soft: #fff1eb;
  --anw-character-focus: #c2411d;
  --anw-character-danger: #b42318;
  --anw-character-danger-surface: #fef3f2;
  --anw-character-warning: #92400e;
  --anw-character-warning-surface: #fffbeb;
  position: relative;
  width: min(1240px, calc(100vw - 64px));
  max-height: calc(100dvh - 48px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color-scheme: light;
  color: var(--anw-character-text);
  background: var(--anw-character-surface);
  border: 1px solid var(--anw-character-border);
  border-radius: 16px;
  box-shadow: 0 28px 80px rgba(15, 23, 42, 0.28);
}
.anw-character-workspace-dialog:focus { outline:none; }
.anw-character-workspace-dialog input,
.anw-character-workspace-dialog select,
.anw-character-workspace-dialog textarea {
  color: var(--anw-character-text);
  font: inherit;
}
.anw-character-workspace-dialog button { font: inherit; }
.anw-character-workspace-summary,
.anw-character-workspace-footer {
  position: sticky;
  z-index: 2;
  flex: 0 0 auto;
  padding: 18px 24px;
  color: var(--anw-character-text);
  background: var(--anw-character-surface);
}
.anw-character-workspace-summary { top: 0; border-bottom: 1px solid var(--anw-character-border); }
.anw-character-workspace-footer { bottom: 0; padding:16px 24px; border-top: 1px solid var(--anw-character-border); }
.anw-character-workspace-heading { display: flex; gap: 16px; align-items: center; justify-content: space-between; }
.anw-character-workspace-identity { display:flex; min-width:0; align-items:center; gap:14px; }
.anw-character-workspace-avatar { display:grid; width:48px; height:48px; flex:0 0 48px; place-items:center; border-radius:14px; color:#fff; background:linear-gradient(145deg, #ff8a61, #f06b3f); box-shadow:0 8px 18px rgba(240,107,63,.2); font-size:20px; font-weight:750; }
.anw-character-workspace-heading h2 { margin: 0; color:var(--anw-character-text-strong); font-size:22px; line-height:1.35; }
.anw-character-workspace-heading-meta { display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin-top:5px; color:var(--anw-character-text-muted); font-size:12px; }
.anw-character-workspace-role-badge,.anw-character-workspace-editable-badge,.anw-character-workspace-readonly-badge { display:inline-flex; min-height:24px; align-items:center; border-radius:999px; padding:3px 9px; font-size:12px; font-weight:650; }
.anw-character-workspace-role-badge { color:#e7663d; background:#fff1eb; }
.anw-character-workspace-role-badge.is-supporting { color:#526ed2; background:#eef1ff; }
.anw-character-workspace-heading-actions { display:flex; flex:0 0 auto; align-items:center; gap:10px; }
.anw-character-workspace-close { display:grid; width:36px; height:36px; place-items:center; border:1px solid transparent; border-radius:10px; color:var(--anw-character-text-muted); background:transparent; cursor:pointer; font-size:25px; line-height:1; }
.anw-character-workspace-close:hover { border-color:var(--anw-character-border); color:var(--anw-character-text); background:var(--anw-character-surface-muted); }
.anw-character-workspace-meta { margin-top: 4px; color: var(--anw-character-text-muted); }
.anw-character-workspace-unsaved { border-radius:999px; padding:5px 10px; color:var(--anw-character-warning); background:var(--anw-character-warning-surface); font-size:12px; font-weight: 650; }
.anw-character-workspace-selectors { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
.anw-character-workspace-tabs { display: flex; flex: 0 0 auto; gap: 6px; padding: 8px 24px 0; overflow-x: auto; border-bottom: 1px solid var(--anw-character-border); background:var(--anw-character-surface); }
.anw-character-workspace-tab { display:inline-flex; min-height: 46px; align-items:center; gap:7px; padding: 8px 15px; border: 0; border-bottom: 3px solid transparent; background: transparent; color:var(--anw-character-text-muted); cursor: pointer; white-space: nowrap; }
.anw-character-workspace-tab[aria-selected="true"] { border-bottom-color: var(--anw-character-accent); color: var(--anw-character-accent); font-weight: 650; }
.anw-character-workspace-tab-count { display:grid; min-width:21px; height:21px; place-items:center; border-radius:999px; padding-inline:5px; color:inherit; background:var(--anw-character-surface-muted); font-size:11px; }
.anw-character-workspace-tab[aria-selected="true"] .anw-character-workspace-tab-count { background:color-mix(in srgb, var(--anw-character-accent) 14%, transparent); }
.anw-character-workspace-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 24px; color:var(--anw-character-text); background:var(--anw-character-surface-muted); }
.anw-character-workspace-panel[hidden] { display: none; }
.anw-character-workspace-form-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 16px; }
.anw-character-workspace-form-grid > .anw-character-workspace-field { grid-column:span 6; }
.anw-character-workspace-field--span-3 { grid-column:span 3 !important; }
.anw-character-workspace-field--span-6 { grid-column:span 6 !important; }
.anw-character-workspace-field--span-12,.anw-character-workspace-field--wide { grid-column:1 / -1 !important; }
.anw-character-workspace-field { display: flex; flex-direction: column; gap: 6px; }
.anw-character-workspace-field > span:first-child { color:var(--anw-character-text-muted); font-size:13px; font-weight:600; }
.anw-character-workspace-field input,
.anw-character-workspace-field select,
.anw-character-workspace-field textarea,
.anw-character-workspace-selectors select { min-height: 40px; padding: 8px 10px; border: 1px solid var(--anw-character-control-border); border-radius: 6px; font: inherit; background: var(--anw-character-surface); color: var(--anw-character-text); }
.anw-character-workspace-field option,
.anw-character-workspace-selectors option { color:var(--anw-character-text); background:var(--anw-character-surface); }
.anw-character-workspace-field input:disabled,
.anw-character-workspace-field select:disabled,
.anw-character-workspace-field textarea:disabled,
.anw-character-workspace-selectors select:disabled { border-color:var(--anw-character-border); color:var(--anw-character-text-muted); background:var(--anw-character-surface-muted); -webkit-text-fill-color:var(--anw-character-text-muted); opacity:1; cursor:not-allowed; }
.anw-character-workspace-field textarea { min-height: 104px; resize: vertical; line-height:1.65; }
.anw-character-workspace-form-grid--basic textarea { min-height:112px; }
.anw-character-workspace-field input:hover,.anw-character-workspace-field select:hover,.anw-character-workspace-field textarea:hover { border-color:var(--anw-character-focus); }
.anw-character-workspace-field [aria-invalid="true"] { border-color:var(--anw-character-danger); }
.anw-character-workspace-error { color:var(--anw-character-danger); }
.anw-character-workspace-alert { margin: 0 20px 12px; padding: 10px 12px; border-radius: 6px; background:var(--anw-character-danger-surface); color:var(--anw-character-danger); }
.anw-character-workspace-alert button { display: block; margin-top: 6px; border: 0; padding: 0; background: transparent; color: inherit; text-decoration: underline; cursor: pointer; }
.anw-character-workspace-section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:16px; }
.anw-character-workspace-section-heading h3,.anw-character-workspace-section-heading p { margin:0; }
.anw-character-workspace-section-heading h3 { color:var(--anw-character-text-strong); font-size:17px; }
.anw-character-workspace-section-heading p { margin-top:5px; color:var(--anw-character-text-muted); font-size:13px; }
.anw-character-workspace-editable-badge { color:#dd5b34; background:var(--anw-character-accent-soft); }
.anw-character-workspace-readonly-badge { color:#5f6672; background:#eef1f4; }
.anw-character-workspace-overview-grid,.anw-character-workspace-fact-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:16px; }
.anw-character-workspace-readonly-card { padding: 15px 16px; border: 1px solid var(--anw-character-border); border-radius: 10px; color:var(--anw-character-text); background: var(--anw-character-surface); box-shadow:0 2px 8px rgba(15,23,42,.025); }
.anw-character-workspace-readonly-card + .anw-character-workspace-readonly-card { margin-top: 12px; }
.anw-character-workspace-overview-grid .anw-character-workspace-readonly-card + .anw-character-workspace-readonly-card,.anw-character-workspace-fact-grid .anw-character-workspace-readonly-card + .anw-character-workspace-readonly-card { margin-top:0; }
.anw-character-workspace-readonly-card h3 { margin: 0 0 8px; font-size: 15px; }
.anw-character-workspace-readonly-card p { margin: 4px 0; }
.anw-character-workspace-muted-value { color:var(--anw-character-text-muted); }
.anw-character-workspace-metrics { display:flex; align-items:center; gap:28px; }
.anw-character-workspace-metrics span { display:flex; align-items:baseline; gap:6px; color:var(--anw-character-text-muted); font-size:12px; }
.anw-character-workspace-metrics strong { color:var(--anw-character-text-strong); font-size:22px; }
.anw-character-workspace-fact-card header { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
.anw-character-workspace-fact-card header h3 { flex:1; }
.anw-character-workspace-fact-card header span { flex:0 0 auto; border-radius:999px; padding:3px 8px; color:#526ed2; background:#eef1ff; font-size:11px; font-weight:650; }
.anw-character-workspace-fact-card > p:not(.anw-character-workspace-meta) { color:var(--anw-character-text); line-height:1.65; }
.anw-character-workspace-empty { padding: 28px 16px; text-align: center; color:var(--anw-character-text-muted); }
.anw-character-workspace-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.anw-character-workspace-actions { display: flex; gap: 8px; }
.anw-character-workspace-button { min-height: 40px; padding: 8px 17px; border: 1px solid var(--anw-character-control-border); border-radius: 8px; background: var(--anw-character-surface); color: var(--anw-character-text); cursor: pointer; font-weight:600; }
.anw-character-workspace-button--primary { border-color: var(--anw-character-accent); background: var(--anw-character-accent); color: #fff; }
.anw-character-workspace-button--danger { border-color:var(--anw-character-danger); color:var(--anw-character-danger); background:var(--anw-character-surface); }
.anw-character-workspace-button:not(:disabled):hover { transform:translateY(-1px); box-shadow:0 5px 13px rgba(15,23,42,.08); }
.anw-character-workspace-button:disabled { border-color:var(--anw-character-border); color:var(--anw-character-text-muted); background:var(--anw-character-surface-muted); -webkit-text-fill-color:var(--anw-character-text-muted); cursor:not-allowed; opacity:1; }
.anw-character-workspace-dialog :focus-visible { outline: 3px solid var(--anw-character-focus); outline-offset: 2px; }
.anw-character-profile-layout { display:grid; grid-template-columns:minmax(0,7fr) minmax(320px,5fr); gap:16px; align-items:start; }
.anw-character-profile-main,.anw-character-profile-side details { padding:16px; border:1px solid var(--anw-character-border); border-radius:12px; color:var(--anw-character-text); background:var(--anw-character-surface); }
.anw-character-profile-group-title,.anw-character-profile-side summary { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.anw-character-profile-group-title { margin-bottom:14px; }
.anw-character-profile-group-title h4,.anw-character-profile-side summary span { margin:0; font-size:15px; font-weight:700; }
.anw-character-profile-group-title span,.anw-character-profile-side summary small { color:var(--anw-character-text-muted); font-size:12px; }
.anw-character-profile-side { display:grid; gap:12px; }
.anw-character-profile-side details { padding:0; overflow:hidden; }
.anw-character-profile-side summary { padding:14px 16px; cursor:pointer; list-style:none; }
.anw-character-profile-side summary::-webkit-details-marker { display:none; }
.anw-character-profile-side details[open] summary { border-bottom:1px solid var(--anw-character-border); }
.anw-character-profile-detail-fields { display:grid; gap:12px; padding:16px; }
.anw-character-workspace-form-grid--writing > .anw-character-workspace-field { grid-column:1 / -1; }
.anw-character-workspace-form-grid--writing .anw-character-workspace-field textarea { min-height:88px; }
.anw-character-state-layout { display:grid; grid-template-columns:minmax(0,8fr) minmax(260px,4fr); gap:16px; }
.anw-character-state-current,.anw-character-state-risk { padding:16px; border:1px solid var(--anw-character-border); border-radius:12px; color:var(--anw-character-text); background:var(--anw-character-surface); }
.anw-character-state-current h4,.anw-character-state-risk h4,.anw-character-recent h4,.anw-character-fact-history h4 { margin:0; font-size:15px; }
.anw-character-state-slots { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 20px; margin:12px 0 0; }
.anw-character-state-slot { display:grid; grid-template-columns:92px minmax(0,1fr); gap:10px; padding:9px 0; border-top:1px solid var(--anw-character-border); }
.anw-character-state-slot dt { color:var(--anw-character-text-muted); font-size:13px; }
.anw-character-state-slot dd { margin:0; color:var(--anw-character-text-strong); line-height:1.55; }
.anw-character-state-values,.anw-character-state-more-values ul { margin:0; padding:0; list-style:none; }
.anw-character-state-values li + li,.anw-character-state-more-values li + li { margin-top:5px; }
.anw-character-state-bounded-value > details,.anw-character-state-more-values { margin-top:4px; }
.anw-character-state-bounded-value summary,.anw-character-state-more-values summary { width:max-content; max-width:100%; color:#c2411d; cursor:pointer; font-size:12px; font-weight:650; }
.anw-character-state-bounded-value p { margin:5px 0 0; overflow-wrap:anywhere; }
.anw-character-state-more-values > ul { margin-top:6px; padding-left:16px; list-style:disc; }
.anw-character-fact-status { display:inline-flex; margin-left:7px; border-radius:999px; padding:1px 6px; color:#a16207; background:#fef3c7; font-size:11px; }
.anw-character-state-risk.has-risk { border-color:#fed7aa; background:#fffaf5; }
.anw-character-state-risk ul { margin:12px 0; padding-left:20px; line-height:1.9; }
.anw-character-state-coverage { margin:12px 0 0; color:var(--anw-character-text-strong); font-weight:650; line-height:1.65; }
.anw-character-state-ok { margin:12px 0; color:#16794b; line-height:1.65; }
.anw-character-recent,.anw-character-fact-history { margin-top:20px; }
.anw-character-subsection-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:12px; }
.anw-character-subsection-heading h4,.anw-character-subsection-heading p { margin:0; }
.anw-character-subsection-heading p { margin-top:4px; color:var(--anw-character-text-muted); font-size:12px; }
.anw-character-link-button,.anw-character-row-actions button,.anw-character-action-menu summary { border:0; padding:4px 6px; color:#c2411d; background:transparent; cursor:pointer; font-weight:650; }
.anw-character-recent-list { margin:0; padding:0; border:1px solid var(--anw-character-border); border-radius:12px; color:var(--anw-character-text); background:var(--anw-character-surface); list-style:none; }
.anw-character-recent-row { display:grid; grid-template-columns:104px minmax(0,1fr) 104px 154px; gap:12px; align-items:center; min-height:58px; padding:10px 14px; }
.anw-character-recent-row + .anw-character-recent-row { border-top:1px solid var(--anw-character-border); }
.anw-character-fact-dimension { color:#475569; font-size:12px; font-weight:650; }
.anw-character-recent-content { min-width:0; }
.anw-character-recent-content strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.anw-character-recent-content small,.anw-character-fact-text small { display:block; margin-top:3px; color:var(--anw-character-text-muted); }
.anw-character-fact-sequence,.anw-character-fact-source { color:var(--anw-character-text-muted); font-size:12px; }
.anw-character-row-actions { position:relative; display:flex; align-items:center; justify-content:flex-end; gap:4px; }
.anw-character-action-menu { position:relative; }
.anw-character-action-menu summary { border-radius:6px; list-style:none; }
.anw-character-action-menu summary::-webkit-details-marker { display:none; }
.anw-character-action-menu[open] summary { color:var(--anw-character-text-strong); background:var(--anw-character-accent-soft); }
.anw-character-action-menu-popover { position:absolute; z-index:5; top:calc(100% + 4px); right:0; display:grid; min-width:132px; padding:5px; border:1px solid var(--anw-character-border); border-radius:8px; color:var(--anw-character-text); background:var(--anw-character-surface); box-shadow:0 10px 24px rgba(15,23,42,.14); }
.anw-character-action-menu-popover button { width:100%; min-height:34px; border-radius:5px; text-align:left; white-space:nowrap; }
.anw-character-action-menu-popover button:hover { background:var(--anw-character-surface-muted); }
.anw-character-fact-filters { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:10px; margin-left:auto; }
.anw-character-fact-filters label { display:flex; align-items:center; gap:6px; color:var(--anw-character-text-muted); font-size:12px; }
.anw-character-fact-filters select { min-height:34px; border:1px solid var(--anw-character-control-border); border-radius:7px; padding:5px 28px 5px 8px; color:var(--anw-character-text); background:var(--anw-character-surface); }
.anw-character-fact-filters select:hover { border-color:var(--anw-character-focus); }
.anw-character-fact-filters select:focus-visible { border-color:var(--anw-character-focus); outline:3px solid var(--anw-character-focus); outline-offset:2px; }
.anw-character-fact-filters select:disabled { border-color:var(--anw-character-border); color:var(--anw-character-text-muted); background:var(--anw-character-surface-muted); -webkit-text-fill-color:var(--anw-character-text-muted); opacity:1; cursor:not-allowed; }
.anw-character-fact-filters option { color:var(--anw-character-text); background:var(--anw-character-surface); }
.anw-character-fact-list { margin:0; padding:0; border:1px solid var(--anw-character-border); border-radius:12px; color:var(--anw-character-text); background:var(--anw-character-surface); list-style:none; }
.anw-character-fact-group + .anw-character-fact-group { border-top:1px solid var(--anw-character-border); }
.anw-character-fact-group-items { margin:0; padding:0; list-style:none; }
.anw-character-fact-batch-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border-bottom:1px solid var(--anw-character-border); background:var(--anw-character-surface-muted); }
.anw-character-fact-batch-heading strong,.anw-character-fact-batch-heading small { display:block; }
.anw-character-fact-batch-heading small { margin-top:2px; color:var(--anw-character-text-muted); }
.anw-character-fact-batch-heading button { flex:0 0 auto; min-height:34px; border:1px solid var(--anw-character-control-border); border-radius:7px; padding:5px 9px; color:#c2411d; background:var(--anw-character-surface); cursor:pointer; font-weight:650; }
.anw-character-fact-card { display:grid; grid-template-columns:96px 110px minmax(0,1fr) 76px 150px 116px; gap:12px; align-items:start; min-height:72px; padding:10px 12px; }
.anw-character-fact-card + .anw-character-fact-card { border-top:1px solid var(--anw-character-border); }
.anw-character-fact-card-field { min-width:0; }
.anw-character-fact-card-label { display:block; margin-bottom:4px; color:var(--anw-character-text-muted); font-size:11px; }
.anw-character-fact-state { border-radius:999px; padding:3px 7px; text-align:center; color:#475569; background:#f1f5f9; font-size:11px; }
.anw-character-fact-state.is-current { color:#16794b; background:#ecfdf3; }
.anw-character-fact-state.is-source_invalid,.anw-character-fact-state.is-batch_reverted { color:#b45309; background:#fff7ed; }
.anw-character-fact-text { min-width:0; }
.anw-character-fact-text strong { display:-webkit-box; overflow:hidden; -webkit-box-orient:vertical; -webkit-line-clamp:2; line-height:1.5; }
.anw-character-load-more { display:block; min-width:140px; min-height:38px; margin:14px auto 0; border:1px solid var(--anw-character-control-border); border-radius:8px; color:var(--anw-character-text); background:var(--anw-character-surface); cursor:pointer; }
.anw-character-drawer,.anw-character-source-viewer { position:absolute; inset:0 0 0 auto; z-index:8; display:flex; width:480px; flex-direction:column; overflow:hidden; border-left:1px solid var(--anw-character-border); color:var(--anw-character-text); background:var(--anw-character-surface); box-shadow:-20px 0 50px rgba(15,23,42,.18); }
.anw-character-source-viewer { width:min(720px,72%); }
.anw-character-drawer > header,.anw-character-source-viewer > header { display:flex; min-height:72px; flex:0 0 auto; align-items:center; justify-content:space-between; gap:12px; padding:14px 24px; border-bottom:1px solid var(--anw-character-border); color:var(--anw-character-text); background:var(--anw-character-surface); }
.anw-character-drawer > header h3,.anw-character-source-viewer > header h3,.anw-character-drawer > header p,.anw-character-source-viewer > header p { margin:0; }
.anw-character-workspace-dialog .anw-character-drawer > header h3,.anw-character-workspace-dialog .anw-character-source-viewer > header h3 { color:var(--anw-character-text-strong); }
.anw-character-drawer > header p,.anw-character-source-viewer > header p { margin-top:4px; color:var(--anw-character-text-muted); font-size:12px; }
.anw-character-workspace-dialog .anw-character-drawer > header button,.anw-character-workspace-dialog .anw-character-source-viewer > header button { display:grid; width:36px; height:36px; flex:0 0 36px; place-items:center; border:1px solid transparent; border-radius:10px; padding:0; color:var(--anw-character-text-strong); background:transparent; cursor:pointer; font-size:24px; line-height:1; }
.anw-character-workspace-dialog .anw-character-drawer > header button:not(:disabled):hover,.anw-character-workspace-dialog .anw-character-source-viewer > header button:not(:disabled):hover { border-color:var(--anw-character-border); color:var(--anw-character-text); background:var(--anw-character-surface-muted); }
.anw-character-workspace-dialog .anw-character-drawer > header button:disabled,.anw-character-workspace-dialog .anw-character-source-viewer > header button:disabled { border-color:var(--anw-character-border); color:var(--anw-character-text-muted); background:var(--anw-character-surface-muted); cursor:not-allowed; opacity:1; }
.anw-character-drawer-body,.anw-character-source-body { flex:1 1 auto; min-height:0; overflow:auto; padding:24px; color:var(--anw-character-text); background:var(--anw-character-surface); }
.anw-character-drawer-body section + section,.anw-character-drawer-body section + label,.anw-character-drawer-body label + label,.anw-character-drawer-body label + section { margin-top:20px; }
.anw-character-drawer-body h4 { margin:0 0 8px; color:var(--anw-character-text-strong); }
.anw-character-evidence,.anw-character-drawer blockquote,.anw-character-source-fallback blockquote { margin:0; padding:12px 14px; border-left:3px solid #c2411d; color:var(--anw-character-text); background:#fff7ed; line-height:1.7; }
.anw-character-correction-impact { padding:14px; border-radius:10px; color:var(--anw-character-text); background:var(--anw-character-surface-muted); }
.anw-character-correction-impact ul { margin:8px 0 0; padding-left:20px; line-height:1.8; }
.anw-character-drawer > footer { display:flex; min-height:72px; flex:0 0 auto; align-items:center; justify-content:flex-end; gap:8px; padding:14px 24px; border-top:1px solid var(--anw-character-border); color:var(--anw-character-text); background:var(--anw-character-surface); }
.anw-character-source-meta { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
.anw-character-source-meta span { border-radius:999px; padding:4px 8px; color:#475569; background:#f1f5f9; font-size:12px; }
.anw-character-source-text { margin:0; color:var(--anw-character-text); white-space:pre-wrap; overflow-wrap:anywhere; font:14px/1.8 ui-monospace,SFMono-Regular,Menlo,monospace; }
.anw-character-source-text mark { border-radius:3px; padding:1px 0; color:var(--anw-character-text-strong); background:#fed7aa; }
.anw-character-source-fallback > p { color:var(--anw-character-text-muted); line-height:1.65; }
.anw-character-workspace-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }

@media (max-width: 980px) {
  .anw-character-state-layout,.anw-character-profile-layout { grid-template-columns:1fr; }
  .anw-character-fact-card { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .anw-character-fact-card-field--fact { grid-column:1 / -1; }
  .anw-character-fact-card > .anw-character-row-actions { grid-column:1 / -1; justify-content:flex-start; }
  .anw-character-source-viewer { width:min(720px,100%); }
}

@media (max-width: 640px) {
  .anw-character-workspace-backdrop { padding:0; }
  .anw-character-workspace-dialog { width:100vw; max-height:100dvh; border-radius:0; }
  .anw-character-state-slots,.anw-character-workspace-selectors { grid-template-columns:1fr; }
  .anw-character-recent-row,.anw-character-fact-card { grid-template-columns:1fr; }
  .anw-character-fact-card-field--fact,.anw-character-fact-card > .anw-character-row-actions { grid-column:auto; }
  .anw-character-recent-row > .anw-character-row-actions { justify-content:flex-start; }
  .anw-character-subsection-heading { align-items:flex-start; flex-direction:column; }
  .anw-character-fact-filters { justify-content:flex-start; margin-left:0; }
  .anw-character-drawer,.anw-character-source-viewer { width:100%; }
}
`;

export function ensureCharacterWorkspaceStyles(): void {
  if (typeof document === "undefined" || document.getElementById(STYLE_ID)) return;
  const element = document.createElement("style");
  element.id = STYLE_ID;
  element.textContent = CHARACTER_WORKSPACE_CSS;
  document.head.appendChild(element);
}
