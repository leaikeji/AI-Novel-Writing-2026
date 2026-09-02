export const STORY_LEDGER_WORKSPACE_STYLE_ID = "anw-story-ledger-workspace-styles";

export const STORY_LEDGER_WORKSPACE_STYLES = `
.anw-story-ledger-workspace {
  container: anw-story-ledger / inline-size;
  color: var(--anw-text, #172033);
  display: grid;
  gap: 16px;
  min-width: 0;
}
.anw-story-ledger-workspace button,
.anw-story-ledger-workspace input,
.anw-story-ledger-workspace select,
.anw-story-ledger-workspace textarea {
  font: inherit;
}
.anw-story-ledger-workspace button {
  cursor: pointer;
}
.anw-story-ledger-workspace button:focus-visible,
.anw-story-ledger-workspace input:focus-visible,
.anw-story-ledger-workspace select:focus-visible,
.anw-story-ledger-workspace textarea:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--anw-primary, #4f46e5) 45%, transparent);
  outline-offset: 2px;
}
.anw-story-ledger-heading,
.anw-story-ledger-summary-header,
.anw-story-ledger-fact-heading,
.anw-story-ledger-detail-heading,
.anw-story-ledger-fact-actions,
.anw-story-ledger-detail-actions,
.anw-story-ledger-filter-actions {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: space-between;
}
.anw-story-ledger-heading h2,
.anw-story-ledger-fact-heading h3,
.anw-story-ledger-detail-heading h2 {
  margin: 0;
}
.anw-story-ledger-heading p,
.anw-story-ledger-fact-heading p,
.anw-story-ledger-detail-heading p {
  color: var(--anw-text-secondary, #667085);
  margin: 3px 0 0;
}
.anw-story-ledger-timeline-context,
.anw-story-ledger-snapshot {
  background: var(--anw-surface-subtle, #f6f7fb);
  border: 1px solid var(--anw-border, #d9deea);
  border-radius: 10px;
  color: var(--anw-text-secondary, #596276);
  padding: 8px 10px;
}
.anw-story-ledger-timeline-context strong {
  color: var(--anw-text, #172033);
}
.anw-story-ledger-summary {
  background: var(--anw-surface, #fff);
  border: 1px solid var(--anw-border, #d9deea);
  border-radius: 14px;
  padding: 16px;
}
.anw-story-ledger-summary-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
}
.anw-story-ledger-summary-grid li {
  background: var(--anw-surface-subtle, #f6f7fb);
  border-radius: 10px;
  display: grid;
  gap: 3px;
  padding: 10px;
}
.anw-story-ledger-summary-grid strong {
  font-size: 1.25rem;
}
.anw-story-ledger-review-button.is-active {
  background: var(--anw-primary, #4f46e5);
  color: #fff;
}
.anw-story-ledger-filters {
  background: var(--anw-surface, #fff);
  border: 1px solid var(--anw-border, #d9deea);
  border-radius: 14px;
  display: grid;
  gap: 14px;
  padding: 16px;
}
.anw-story-ledger-type-filter {
  border: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin: 0;
  min-width: 0;
  padding: 0;
}
.anw-story-ledger-type-filter legend {
  font-weight: 650;
  margin-bottom: 8px;
  width: 100%;
}
.anw-story-ledger-type-filter label,
.anw-story-ledger-review-toggle {
  align-items: center;
  display: inline-flex;
  gap: 6px;
}
.anw-story-ledger-filter-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.anw-story-ledger-filter {
  display: grid;
  gap: 5px;
  min-width: 0;
}
.anw-story-ledger-filter > span,
.anw-story-ledger-field-label {
  color: var(--anw-text-secondary, #596276);
  font-size: .78rem;
  font-weight: 650;
}
.anw-story-ledger-filter input,
.anw-story-ledger-filter select {
  background: var(--anw-surface, #fff);
  border: 1px solid var(--anw-border-strong, #b7c0d4);
  border-radius: 8px;
  color: inherit;
  min-height: 38px;
  min-width: 0;
  padding: 7px 9px;
  width: 100%;
}
.anw-story-ledger-main {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.anw-story-ledger-list-column,
.anw-story-ledger-detail-shell,
.anw-story-ledger-detail {
  min-width: 0;
}
.anw-story-ledger-list-heading {
  align-items: end;
  display: flex;
  gap: 10px;
  justify-content: space-between;
  margin-bottom: 10px;
}
.anw-story-ledger-list-heading h2,
.anw-story-ledger-list-heading p {
  margin: 0;
}
.anw-story-ledger-list-heading p {
  color: var(--anw-text-secondary, #596276);
  font-size: .85rem;
}
.anw-story-ledger-fact-list,
.anw-story-ledger-detail-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.anw-story-ledger-fact-list {
  display: grid;
  gap: 10px;
}
.anw-story-ledger-fact-card,
.anw-story-ledger-detail {
  background: var(--anw-surface, #fff);
  border: 1px solid var(--anw-border, #d9deea);
  border-radius: 14px;
}
.anw-story-ledger-fact-card {
  display: grid;
  gap: 11px;
  padding: 14px;
}
.anw-story-ledger-fact-card.is-selected {
  border-color: var(--anw-primary, #4f46e5);
  box-shadow: 0 0 0 1px var(--anw-primary, #4f46e5);
}
.anw-story-ledger-fact-kicker,
.anw-story-ledger-fact-value {
  margin: 0;
}
.anw-story-ledger-fact-value {
  display: grid;
  gap: 4px;
  overflow-wrap: anywhere;
}
.anw-story-ledger-fact-badges,
.anw-story-ledger-entities {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.anw-story-ledger-fact-badges span,
.anw-story-ledger-entities span {
  background: var(--anw-surface-subtle, #f2f4f8);
  border-radius: 999px;
  font-size: .78rem;
  padding: 3px 8px;
}
.anw-story-ledger-fact-badges .is-health-conflict,
.anw-story-ledger-fact-badges .is-effective-source_invalid,
.anw-story-ledger-entities .is-missing {
  background: #fff1f0;
  color: #a61d24;
}
.anw-story-ledger-fact-badges .is-health-ambiguous {
  background: #fff7e6;
  color: #8c4a00;
}
.anw-story-ledger-fact-meta,
.anw-story-ledger-detail-properties {
  display: grid;
  gap: 7px;
  margin: 0;
}
.anw-story-ledger-fact-meta > div,
.anw-story-ledger-detail-properties > div {
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(78px, .38fr) minmax(0, 1fr);
}
.anw-story-ledger-fact-meta dt,
.anw-story-ledger-detail-properties dt {
  color: var(--anw-text-secondary, #596276);
  font-size: .8rem;
}
.anw-story-ledger-fact-meta dd,
.anw-story-ledger-detail-properties dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.anw-story-ledger-action-menu {
  position: relative;
}
.anw-story-ledger-menu-popover {
  background: var(--anw-surface, #fff);
  border: 1px solid var(--anw-border, #d9deea);
  border-radius: 10px;
  box-shadow: 0 10px 32px rgb(31 42 68 / 18%);
  display: grid;
  inset: calc(100% + 5px) 0 auto auto;
  min-width: 210px;
  padding: 5px;
  position: absolute;
  z-index: 5;
}
.anw-story-ledger-menu-popover button {
  background: transparent;
  border: 0;
  border-radius: 7px;
  padding: 8px 10px;
  text-align: left;
}
.anw-story-ledger-menu-popover button:hover,
.anw-story-ledger-menu-popover button:focus-visible {
  background: var(--anw-surface-subtle, #f2f4f8);
}
.anw-story-ledger-load-more {
  margin-top: 12px;
  width: 100%;
}
.anw-story-ledger-detail {
  align-self: start;
  display: grid;
  gap: 14px;
  padding: 16px;
}
.anw-story-ledger-detail-body,
.anw-story-ledger-detail-body section {
  display: grid;
  gap: 9px;
}
.anw-story-ledger-detail-body {
  gap: 18px;
}
.anw-story-ledger-detail-body h3,
.anw-story-ledger-detail-body h4,
.anw-story-ledger-detail-body p {
  margin: 0;
}
.anw-story-ledger-detail-value {
  line-height: 1.7;
  white-space: pre-wrap;
}
.anw-story-ledger-detail-list {
  display: grid;
  gap: 7px;
}
.anw-story-ledger-detail-list li {
  background: var(--anw-surface-subtle, #f6f7fb);
  border-radius: 8px;
  overflow-wrap: anywhere;
  padding: 8px 10px;
}
.anw-story-ledger-state,
.anw-story-ledger-inline-error {
  background: var(--anw-surface-subtle, #f6f7fb);
  border-radius: 12px;
  padding: 18px;
  text-align: center;
}
.anw-story-ledger-state.is-error,
.anw-story-ledger-inline-error {
  background: #fff1f0;
  color: #a61d24;
}
.anw-story-ledger-live-status {
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  height: 1px;
  overflow: hidden;
  position: absolute;
  white-space: nowrap;
  width: 1px;
}
.anw-story-ledger-modal-layer {
  background: rgb(16 24 40 / 32%);
  display: grid;
  inset: 0;
  overflow: auto;
  padding: 24px;
  place-items: center;
  position: fixed;
  z-index: 1200;
}
.anw-story-ledger-modal-layer > aside {
  background: var(--anw-surface, #fff);
  max-height: min(760px, calc(100vh - 48px));
  max-width: 720px;
  overflow: auto;
  width: min(100%, 720px);
}
.anw-story-ledger-modal-layer > aside > header,
.anw-story-ledger-modal-layer > aside > footer {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: space-between;
  padding: 14px 16px;
}
.anw-story-ledger-modal-layer > aside > header {
  border-bottom: 1px solid var(--anw-border, #d9deea);
}
.anw-story-ledger-modal-layer > aside > footer {
  border-top: 1px solid var(--anw-border, #d9deea);
  justify-content: flex-end;
}
.anw-story-ledger-modal-layer > aside > header h3,
.anw-story-ledger-modal-layer > aside > header p {
  margin: 0;
}
.anw-story-ledger-modal-layer .anw-character-drawer-body,
.anw-story-ledger-modal-layer .anw-character-source-body {
  display: grid;
  gap: 14px;
  padding: 16px;
}
.anw-story-ledger-modal-layer .anw-character-workspace-field {
  display: grid;
  gap: 6px;
}
.anw-story-ledger-modal-layer textarea {
  border: 1px solid var(--anw-border-strong, #b7c0d4);
  border-radius: 8px;
  min-height: 96px;
  padding: 9px;
  resize: vertical;
  width: 100%;
}
.anw-story-ledger-modal-layer .anw-character-source-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
}
.anw-story-ledger-modal-layer .anw-character-source-text {
  background: var(--anw-surface-subtle, #f6f7fb);
  border-radius: 10px;
  line-height: 1.65;
  margin: 0;
  overflow-wrap: anywhere;
  padding: 12px;
  white-space: pre-wrap;
}
@container anw-story-ledger (min-width: 640px) {
  .anw-story-ledger-summary-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
  .anw-story-ledger-filter-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@container anw-story-ledger (min-width: 960px) {
  .anw-story-ledger-main {
    grid-template-columns: minmax(430px, 1.1fr) minmax(340px, .9fr);
  }
  .anw-story-ledger-detail {
    max-height: calc(100dvh - 240px);
    overflow: auto;
    position: sticky;
    top: 12px;
  }
}
@container anw-story-ledger (max-width: 959px) {
  .anw-story-ledger-detail-shell.is-open {
    align-items: stretch;
    background: rgb(16 24 40 / 32%);
    display: grid;
    inset: 0;
    justify-items: end;
    padding: 18px;
    position: fixed;
    z-index: 1100;
  }
  .anw-story-ledger-detail-shell.is-open .anw-story-ledger-detail {
    border-radius: 16px;
    max-height: calc(100vh - 36px);
    max-width: 620px;
    overflow: auto;
    width: min(100%, 620px);
  }
}
@container anw-story-ledger (max-width: 639px) {
  .anw-story-ledger-heading,
  .anw-story-ledger-summary-header,
  .anw-story-ledger-fact-heading,
  .anw-story-ledger-filter-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .anw-story-ledger-filter-grid,
  .anw-story-ledger-fact-meta > div,
  .anw-story-ledger-detail-properties > div {
    grid-template-columns: 1fr;
  }
  .anw-story-ledger-fact-meta > div,
  .anw-story-ledger-detail-properties > div {
    gap: 2px;
  }
  .anw-story-ledger-modal-layer {
    align-items: end;
    padding: 0;
  }
  .anw-story-ledger-modal-layer > aside {
    border-radius: 16px 16px 0 0;
    max-height: 88vh;
  }
}
`;

export function ensureStoryLedgerWorkspaceStyles(): void {
  if (typeof document === "undefined") return;
  if (document.getElementById(STORY_LEDGER_WORKSPACE_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STORY_LEDGER_WORKSPACE_STYLE_ID;
  style.textContent = STORY_LEDGER_WORKSPACE_STYLES;
  document.head.appendChild(style);
}
