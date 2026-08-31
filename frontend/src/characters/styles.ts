const STYLE_ID = "anw-character-workspace-styles";

export const CHARACTER_WORKSPACE_CSS = `
.anw-character-workspace-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: grid;
  place-items: center;
  padding: 20px 24px;
  background: rgba(15, 23, 42, 0.48);
}
.anw-character-workspace-dialog {
  width: min(1120px, calc(100vw - 48px));
  max-height: calc(100dvh - 40px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--ant-color-text, #1f2937);
  background: var(--ant-color-bg-container, #fff);
  border: 1px solid color-mix(in srgb, var(--ant-color-border-secondary, #e5e7eb) 86%, transparent);
  border-radius: 16px;
  box-shadow: 0 28px 80px rgba(15, 23, 42, 0.28);
}
.anw-character-workspace-dialog:focus { outline:none; }
.anw-character-workspace-summary,
.anw-character-workspace-footer {
  position: sticky;
  z-index: 2;
  flex: 0 0 auto;
  padding: 18px 24px;
  background: var(--ant-color-bg-container, #fff);
}
.anw-character-workspace-summary { top: 0; border-bottom: 1px solid var(--ant-color-border-secondary, #e5e7eb); }
.anw-character-workspace-footer { bottom: 0; border-top: 1px solid var(--ant-color-border-secondary, #e5e7eb); }
.anw-character-workspace-heading { display: flex; gap: 16px; align-items: center; justify-content: space-between; }
.anw-character-workspace-identity { display:flex; min-width:0; align-items:center; gap:14px; }
.anw-character-workspace-avatar { display:grid; width:48px; height:48px; flex:0 0 48px; place-items:center; border-radius:14px; color:#fff; background:linear-gradient(145deg, #ff8a61, #f06b3f); box-shadow:0 8px 18px rgba(240,107,63,.2); font-size:20px; font-weight:750; }
.anw-character-workspace-heading h2 { margin: 0; color:var(--ant-color-text, #252a32); font-size:22px; line-height:1.35; }
.anw-character-workspace-heading-meta { display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin-top:5px; color:var(--ant-color-text-secondary, #64748b); font-size:12px; }
.anw-character-workspace-role-badge,.anw-character-workspace-editable-badge,.anw-character-workspace-readonly-badge { display:inline-flex; min-height:24px; align-items:center; border-radius:999px; padding:3px 9px; font-size:12px; font-weight:650; }
.anw-character-workspace-role-badge { color:#e7663d; background:#fff1eb; }
.anw-character-workspace-role-badge.is-supporting { color:#526ed2; background:#eef1ff; }
.anw-character-workspace-heading-actions { display:flex; flex:0 0 auto; align-items:center; gap:10px; }
.anw-character-workspace-close { display:grid; width:36px; height:36px; place-items:center; border:1px solid transparent; border-radius:10px; color:var(--ant-color-text-secondary, #64748b); background:transparent; cursor:pointer; font-size:25px; line-height:1; }
.anw-character-workspace-close:hover { border-color:var(--ant-color-border-secondary, #e5e7eb); color:var(--ant-color-text, #1f2937); background:var(--ant-color-fill-quaternary, #f8fafc); }
.anw-character-workspace-meta { margin-top: 4px; color: var(--ant-color-text-secondary, #64748b); }
.anw-character-workspace-unsaved { border-radius:999px; padding:5px 10px; color: var(--ant-color-warning-text, #ad6800); background:var(--ant-color-warning-bg, #fffbe6); font-size:12px; font-weight: 650; }
.anw-character-workspace-selectors { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
.anw-character-workspace-tabs { display: flex; flex: 0 0 auto; gap: 6px; padding: 8px 24px 0; overflow-x: auto; border-bottom: 1px solid var(--ant-color-border-secondary, #e5e7eb); background:var(--ant-color-bg-container, #fff); }
.anw-character-workspace-tab { display:inline-flex; min-height: 46px; align-items:center; gap:7px; padding: 8px 15px; border: 0; border-bottom: 3px solid transparent; background: transparent; color:var(--ant-color-text-secondary, #64748b); cursor: pointer; white-space: nowrap; }
.anw-character-workspace-tab[aria-selected="true"] { border-bottom-color: var(--ant-color-primary, #1677ff); color: var(--ant-color-primary, #1677ff); font-weight: 600; }
.anw-character-workspace-tab-count { display:grid; min-width:21px; height:21px; place-items:center; border-radius:999px; padding-inline:5px; color:inherit; background:var(--ant-color-fill-secondary, #f1f5f9); font-size:11px; }
.anw-character-workspace-tab[aria-selected="true"] .anw-character-workspace-tab-count { background:color-mix(in srgb, var(--ant-color-primary, #1677ff) 12%, transparent); }
.anw-character-workspace-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 24px; background:color-mix(in srgb, var(--ant-color-fill-quaternary, #fafafa) 54%, #fff); }
.anw-character-workspace-panel[hidden] { display: none; }
.anw-character-workspace-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.anw-character-workspace-form-grid--profile { grid-template-columns:repeat(3, minmax(0, 1fr)); }
.anw-character-workspace-field { display: flex; flex-direction: column; gap: 6px; }
.anw-character-workspace-field > span:first-child { color:var(--ant-color-text-secondary, #5f6672); font-size:13px; font-weight:600; }
.anw-character-workspace-field--wide { grid-column: 1 / -1; }
.anw-character-workspace-field input,
.anw-character-workspace-field select,
.anw-character-workspace-field textarea,
.anw-character-workspace-selectors select { min-height: 40px; padding: 8px 10px; border: 1px solid var(--ant-color-border, #d1d5db); border-radius: 6px; font: inherit; background: inherit; color: inherit; }
.anw-character-workspace-field textarea { min-height: 104px; resize: vertical; line-height:1.65; }
.anw-character-workspace-field input:hover,.anw-character-workspace-field select:hover,.anw-character-workspace-field textarea:hover { border-color:color-mix(in srgb, var(--ant-color-primary, #1677ff) 55%, var(--ant-color-border, #d1d5db)); }
.anw-character-workspace-field [aria-invalid="true"] { border-color: var(--ant-color-error, #ff4d4f); }
.anw-character-workspace-error { color: var(--ant-color-error-text, #cf1322); }
.anw-character-workspace-alert { margin: 0 20px 12px; padding: 10px 12px; border-radius: 6px; background: var(--ant-color-error-bg, #fff2f0); color: var(--ant-color-error-text, #cf1322); }
.anw-character-workspace-alert button { display: block; margin-top: 6px; border: 0; padding: 0; background: transparent; color: inherit; text-decoration: underline; cursor: pointer; }
.anw-character-workspace-section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin-bottom:16px; }
.anw-character-workspace-section-heading h3,.anw-character-workspace-section-heading p { margin:0; }
.anw-character-workspace-section-heading h3 { color:var(--ant-color-text, #252a32); font-size:17px; }
.anw-character-workspace-section-heading p { margin-top:5px; color:var(--ant-color-text-secondary, #64748b); font-size:13px; }
.anw-character-workspace-editable-badge { color:#1677ff; background:#eaf4ff; }
.anw-character-workspace-readonly-badge { color:#5f6672; background:#eef1f4; }
.anw-character-workspace-overview-grid,.anw-character-workspace-fact-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:16px; }
.anw-character-workspace-readonly-card { padding: 15px 16px; border: 1px solid var(--ant-color-border-secondary, #e5e7eb); border-radius: 10px; background: var(--ant-color-bg-container, #fff); box-shadow:0 2px 8px rgba(15,23,42,.025); }
.anw-character-workspace-readonly-card + .anw-character-workspace-readonly-card { margin-top: 12px; }
.anw-character-workspace-overview-grid .anw-character-workspace-readonly-card + .anw-character-workspace-readonly-card,.anw-character-workspace-fact-grid .anw-character-workspace-readonly-card + .anw-character-workspace-readonly-card { margin-top:0; }
.anw-character-workspace-readonly-card h3 { margin: 0 0 8px; font-size: 15px; }
.anw-character-workspace-readonly-card p { margin: 4px 0; }
.anw-character-workspace-muted-value { color:var(--ant-color-text-tertiary, #8c8c8c); }
.anw-character-workspace-metrics { display:flex; align-items:center; gap:28px; }
.anw-character-workspace-metrics span { display:flex; align-items:baseline; gap:6px; color:var(--ant-color-text-secondary, #64748b); font-size:12px; }
.anw-character-workspace-metrics strong { color:var(--ant-color-text, #252a32); font-size:22px; }
.anw-character-workspace-fact-card header { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
.anw-character-workspace-fact-card header h3 { flex:1; }
.anw-character-workspace-fact-card header span { flex:0 0 auto; border-radius:999px; padding:3px 8px; color:#526ed2; background:#eef1ff; font-size:11px; font-weight:650; }
.anw-character-workspace-fact-card > p:not(.anw-character-workspace-meta) { color:var(--ant-color-text, #343840); line-height:1.65; }
.anw-character-workspace-empty { padding: 28px 16px; text-align: center; color: var(--ant-color-text-secondary, #64748b); }
.anw-character-workspace-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.anw-character-workspace-actions { display: flex; gap: 8px; }
.anw-character-workspace-button { min-height: 40px; padding: 8px 17px; border: 1px solid var(--ant-color-border, #d1d5db); border-radius: 8px; background: var(--ant-color-bg-container, #fff); color: inherit; cursor: pointer; font-weight:600; }
.anw-character-workspace-button--primary { border-color: var(--ant-color-primary, #1677ff); background: var(--ant-color-primary, #1677ff); color: #fff; }
.anw-character-workspace-button:not(:disabled):hover { transform:translateY(-1px); box-shadow:0 5px 13px rgba(15,23,42,.08); }
.anw-character-workspace-button:disabled { cursor: not-allowed; opacity: 0.55; }
.anw-character-workspace-dialog :focus-visible { outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #1677ff) 45%, transparent); outline-offset: 2px; }
.anw-character-workspace-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 980px) {
  .anw-character-workspace-form-grid--profile { grid-template-columns:1fr 1fr; }
}
@media (max-width: 720px) {
  .anw-character-workspace-backdrop { display: block; padding: 0; }
  .anw-character-workspace-dialog { position: fixed; inset: 0; width: 100vw; height: 100dvh; max-height: none; border-radius: 0; }
  .anw-character-workspace-summary, .anw-character-workspace-footer, .anw-character-workspace-body { padding: 14px 16px; }
  .anw-character-workspace-avatar { width:42px; height:42px; flex-basis:42px; border-radius:12px; }
  .anw-character-workspace-heading h2 { font-size:19px; }
  .anw-character-workspace-heading-meta > span:not(.anw-character-workspace-role-badge) { display:none; }
  .anw-character-workspace-unsaved { display:none; }
  .anw-character-workspace-tabs { padding-inline: 12px; }
  .anw-character-workspace-selectors, .anw-character-workspace-form-grid { grid-template-columns: 1fr; }
  .anw-character-workspace-field--wide { grid-column: auto; }
  .anw-character-workspace-overview-grid,.anw-character-workspace-fact-grid { grid-template-columns:1fr; }
  .anw-character-workspace-section-heading { align-items:flex-start; }
  .anw-character-workspace-footer { align-items: stretch; flex-direction: column; }
  .anw-character-workspace-actions { display: grid; grid-template-columns: 1fr 1fr; }
  .anw-character-workspace-actions .anw-character-workspace-button--primary { grid-column:1 / -1; grid-row:1; }
  .anw-character-workspace-button { min-height: 44px; }
}
`;

export function ensureCharacterWorkspaceStyles(): void {
  if (typeof document === "undefined" || document.getElementById(STYLE_ID)) return;
  const element = document.createElement("style");
  element.id = STYLE_ID;
  element.textContent = CHARACTER_WORKSPACE_CSS;
  document.head.appendChild(element);
}
