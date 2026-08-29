const STYLE_ID = "anw-character-workspace-styles";

export const CHARACTER_WORKSPACE_CSS = `
.anw-character-workspace-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(15, 23, 42, 0.48);
}
.anw-character-workspace-dialog {
  width: min(900px, calc(100vw - 32px));
  max-height: calc(100dvh - 32px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--ant-color-text, #1f2937);
  background: var(--ant-color-bg-container, #fff);
  border-radius: 12px;
  box-shadow: 0 24px 64px rgba(15, 23, 42, 0.24);
}
.anw-character-workspace-summary,
.anw-character-workspace-footer {
  position: sticky;
  z-index: 2;
  flex: 0 0 auto;
  padding: 16px 20px;
  background: var(--ant-color-bg-container, #fff);
}
.anw-character-workspace-summary { top: 0; border-bottom: 1px solid var(--ant-color-border-secondary, #e5e7eb); }
.anw-character-workspace-footer { bottom: 0; border-top: 1px solid var(--ant-color-border-secondary, #e5e7eb); }
.anw-character-workspace-heading { display: flex; gap: 12px; align-items: start; justify-content: space-between; }
.anw-character-workspace-heading h2 { margin: 0; font-size: 20px; line-height: 1.4; }
.anw-character-workspace-meta { margin-top: 4px; color: var(--ant-color-text-secondary, #64748b); }
.anw-character-workspace-unsaved { color: var(--ant-color-warning-text, #ad6800); font-weight: 600; }
.anw-character-workspace-selectors { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
.anw-character-workspace-tabs { display: flex; gap: 4px; padding: 8px 20px 0; overflow-x: auto; border-bottom: 1px solid var(--ant-color-border-secondary, #e5e7eb); }
.anw-character-workspace-tab { min-height: 44px; padding: 8px 14px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: inherit; cursor: pointer; white-space: nowrap; }
.anw-character-workspace-tab[aria-selected="true"] { border-bottom-color: var(--ant-color-primary, #1677ff); color: var(--ant-color-primary, #1677ff); font-weight: 600; }
.anw-character-workspace-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 20px; }
.anw-character-workspace-panel[hidden] { display: none; }
.anw-character-workspace-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.anw-character-workspace-field { display: flex; flex-direction: column; gap: 6px; }
.anw-character-workspace-field--wide { grid-column: 1 / -1; }
.anw-character-workspace-field input,
.anw-character-workspace-field select,
.anw-character-workspace-field textarea,
.anw-character-workspace-selectors select { min-height: 40px; padding: 8px 10px; border: 1px solid var(--ant-color-border, #d1d5db); border-radius: 6px; font: inherit; background: inherit; color: inherit; }
.anw-character-workspace-field textarea { min-height: 96px; resize: vertical; }
.anw-character-workspace-field [aria-invalid="true"] { border-color: var(--ant-color-error, #ff4d4f); }
.anw-character-workspace-error { color: var(--ant-color-error-text, #cf1322); }
.anw-character-workspace-alert { margin: 0 20px 12px; padding: 10px 12px; border-radius: 6px; background: var(--ant-color-error-bg, #fff2f0); color: var(--ant-color-error-text, #cf1322); }
.anw-character-workspace-alert button { display: block; margin-top: 6px; border: 0; padding: 0; background: transparent; color: inherit; text-decoration: underline; cursor: pointer; }
.anw-character-workspace-readonly-card { padding: 14px; border: 1px solid var(--ant-color-border-secondary, #e5e7eb); border-radius: 8px; background: var(--ant-color-fill-quaternary, #fafafa); }
.anw-character-workspace-readonly-card + .anw-character-workspace-readonly-card { margin-top: 12px; }
.anw-character-workspace-readonly-card h3 { margin: 0 0 8px; font-size: 15px; }
.anw-character-workspace-readonly-card p { margin: 4px 0; }
.anw-character-workspace-empty { padding: 28px 16px; text-align: center; color: var(--ant-color-text-secondary, #64748b); }
.anw-character-workspace-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.anw-character-workspace-actions { display: flex; gap: 8px; }
.anw-character-workspace-button { min-height: 40px; padding: 8px 16px; border: 1px solid var(--ant-color-border, #d1d5db); border-radius: 6px; background: var(--ant-color-bg-container, #fff); color: inherit; cursor: pointer; }
.anw-character-workspace-button--primary { border-color: var(--ant-color-primary, #1677ff); background: var(--ant-color-primary, #1677ff); color: #fff; }
.anw-character-workspace-button:disabled { cursor: not-allowed; opacity: 0.55; }
.anw-character-workspace-dialog :focus-visible { outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #1677ff) 45%, transparent); outline-offset: 2px; }
.anw-character-workspace-sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (max-width: 720px) {
  .anw-character-workspace-backdrop { display: block; padding: 0; }
  .anw-character-workspace-dialog { position: fixed; inset: 0; width: 100vw; height: 100dvh; max-height: none; border-radius: 0; }
  .anw-character-workspace-summary, .anw-character-workspace-footer, .anw-character-workspace-body { padding: 14px 16px; }
  .anw-character-workspace-tabs { padding-inline: 12px; }
  .anw-character-workspace-selectors, .anw-character-workspace-form-grid { grid-template-columns: 1fr; }
  .anw-character-workspace-field--wide { grid-column: auto; }
  .anw-character-workspace-footer { align-items: stretch; flex-direction: column; }
  .anw-character-workspace-actions { display: grid; grid-template-columns: 1fr 1fr; }
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
