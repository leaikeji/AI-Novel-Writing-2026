/** Local T2-F fragment. T2-GATE owns composition into narration/styles.ts. */
export const T2_F_NARRATION_SETTINGS_PANEL_STYLES = `
  .anw-pronunciation-panel,
  .anw-cache-panel {
    min-width: 0;
    width: 100%;
    max-width: 100%;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 16px;
    padding: 18px;
    color: var(--anw-text, #343844);
    background: var(--anw-card, #fff);
  }

  .anw-pronunciation-panel__header,
  .anw-cache-panel__header,
  .anw-pronunciation-panel__section-heading,
  .anw-pronunciation-panel__footer,
  .anw-cache-panel__preview-actions,
  .anw-cache-panel__actions {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .anw-pronunciation-panel h3,
  .anw-cache-panel h3 {
    margin: 3px 0 0;
    color: var(--anw-ink, #17191f);
    font-size: 18px;
    line-height: 1.35;
  }

  .anw-pronunciation-panel h4,
  .anw-cache-panel h4 {
    margin: 0;
    color: var(--anw-ink, #17191f);
    font-size: 14px;
  }

  .anw-pronunciation-panel__eyebrow,
  .anw-pronunciation-panel__version,
  .anw-cache-panel__eyebrow {
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-pronunciation-panel__live,
  .anw-cache-panel__live {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

  .anw-pronunciation-panel__body,
  .anw-cache-panel__body {
    display: grid;
    min-width: 0;
    gap: 16px;
    margin-top: 16px;
  }

  .anw-pronunciation-panel__notice,
  .anw-pronunciation-panel__error,
  .anw-pronunciation-panel__history,
  .anw-cache-panel__notice,
  .anw-cache-panel__error,
  .anw-cache-panel__guard,
  .anw-cache-panel__disk-warning,
  .anw-cache-panel__success {
    margin: 14px 0 0;
    border-radius: 12px;
    padding: 12px 14px;
  }

  .anw-pronunciation-panel__notice,
  .anw-cache-panel__notice {
    color: #704b00;
    background: #fff7dc;
  }

  .anw-pronunciation-panel__error,
  .anw-cache-panel__error,
  .anw-cache-panel__disk-warning {
    display: grid;
    gap: 8px;
    color: #8d2424;
    background: #fff0f0;
  }

  .anw-pronunciation-panel__history,
  .anw-cache-panel__guard {
    margin: 0;
    border: 1px solid #dce8ff;
    background: #f5f8ff;
  }

  .anw-pronunciation-panel__history p,
  .anw-cache-panel__guard p,
  .anw-cache-panel__success p {
    margin: 6px 0 0;
    line-height: 1.55;
  }

  .anw-pronunciation-panel__pauses,
  .anw-pronunciation-panel__rules,
  .anw-pronunciation-panel__preview,
  .anw-cache-panel__preview {
    min-width: 0;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 13px;
    padding: 14px;
  }

  .anw-pronunciation-panel__section-heading p,
  .anw-pronunciation-panel__empty,
  .anw-cache-panel__actions span,
  .anw-cache-panel__loading,
  .anw-pronunciation-panel__loading {
    margin: 4px 0 0;
    color: var(--anw-muted, #737987);
    font-size: 12px;
    line-height: 1.55;
  }

  .anw-pronunciation-panel__pauses dl,
  .anw-cache-panel__preview dl {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
    margin: 13px 0 0;
  }

  .anw-pronunciation-panel__pauses dl > div,
  .anw-cache-panel__preview dl > div {
    min-width: 0;
    border-radius: 9px;
    padding: 10px;
    background: var(--anw-panel-soft, #f6f7f9);
  }

  .anw-pronunciation-panel dt,
  .anw-cache-panel dt {
    color: var(--anw-muted, #737987);
    font-size: 11px;
  }

  .anw-pronunciation-panel dd,
  .anw-cache-panel dd {
    overflow-wrap: anywhere;
    margin: 4px 0 0;
    color: var(--anw-ink, #17191f);
    font-weight: 750;
  }

  .anw-pronunciation-panel__rule-list {
    display: grid;
    min-width: 0;
    gap: 10px;
    margin-top: 13px;
  }

  .anw-pronunciation-panel__rule {
    display: grid;
    min-width: 0;
    gap: 10px;
    margin: 0;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 11px;
    padding: 12px;
  }

  .anw-pronunciation-panel__rule legend {
    padding: 0 4px;
    color: var(--anw-ink, #17191f);
    font-size: 13px;
    font-weight: 700;
  }

  .anw-pronunciation-panel__grid {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .anw-pronunciation-panel__grid label {
    display: grid;
    min-width: 0;
    gap: 5px;
    color: var(--anw-ink, #17191f);
    font-size: 12px;
    font-weight: 650;
  }

  .anw-pronunciation-panel input,
  .anw-pronunciation-panel select,
  .anw-pronunciation-panel textarea,
  .anw-pronunciation-panel button,
  .anw-cache-panel button {
    min-width: 0;
    min-height: 44px;
    border: 1px solid #cfd3dc;
    border-radius: 10px;
    padding: 8px 10px;
    color: inherit;
    background: #fff;
  }

  .anw-pronunciation-panel input,
  .anw-pronunciation-panel select,
  .anw-pronunciation-panel textarea {
    width: 100%;
  }

  .anw-pronunciation-panel textarea {
    resize: vertical;
    line-height: 1.55;
  }

  .anw-pronunciation-panel button,
  .anw-cache-panel button {
    cursor: pointer;
  }

  .anw-pronunciation-panel button:disabled,
  .anw-pronunciation-panel input:disabled,
  .anw-pronunciation-panel select:disabled,
  .anw-cache-panel button:disabled {
    cursor: not-allowed;
    opacity: .58;
  }

  .anw-pronunciation-panel button:focus-visible,
  .anw-pronunciation-panel input:focus-visible,
  .anw-pronunciation-panel select:focus-visible,
  .anw-pronunciation-panel textarea:focus-visible,
  .anw-cache-panel button:focus-visible,
  .anw-cache-panel input:focus-visible {
    outline: 3px solid rgba(255, 93, 42, .28);
    outline-offset: 2px;
  }

  .anw-pronunciation-panel__validation,
  .anw-cache-panel__validation {
    margin: 0;
    color: #a52b2b;
    font-size: 12px;
  }

  .anw-pronunciation-panel__remove {
    justify-self: start;
    color: #8d2424 !important;
  }

  .anw-pronunciation-panel__advanced {
    border-radius: 9px;
    background: var(--anw-panel-soft, #f6f7f9);
  }

  .anw-pronunciation-panel__advanced summary {
    min-height: 44px;
    padding: 11px 12px;
    cursor: pointer;
    color: var(--anw-ink, #17191f);
    font-size: 12px;
    font-weight: 700;
  }

  .anw-pronunciation-panel__advanced > label {
    display: grid;
    gap: 5px;
    padding: 0 12px 12px;
    color: var(--anw-ink, #17191f);
    font-size: 12px;
    font-weight: 650;
  }

  .anw-pronunciation-panel__preview-controls {
    display: grid;
    grid-template-columns: minmax(180px, .42fr) minmax(0, 1fr);
    gap: 10px;
    margin-top: 13px;
  }

  .anw-pronunciation-panel__preview-controls label {
    display: grid;
    min-width: 0;
    gap: 5px;
    color: var(--anw-ink, #17191f);
    font-size: 12px;
    font-weight: 650;
  }

  .anw-pronunciation-panel__preview-result {
    display: grid;
    gap: 8px;
    margin-top: 12px;
    border-radius: 10px;
    padding: 11px 12px;
    background: #f1f7ff;
  }

  .anw-pronunciation-panel__preview-result p,
  .anw-pronunciation-panel__preview-result ol,
  .anw-pronunciation-panel__preview-note {
    margin: 0;
    line-height: 1.55;
  }

  .anw-pronunciation-panel__preview-result ol {
    display: grid;
    gap: 6px;
    padding-left: 22px;
  }

  .anw-pronunciation-panel__preview-result li small {
    display: block;
    color: var(--anw-muted, #737987);
  }

  .anw-pronunciation-panel__preview-note {
    margin-top: 10px;
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-pronunciation-panel__save,
  .anw-cache-panel__execute {
    border: 0 !important;
    color: #fff !important;
    background: linear-gradient(135deg, var(--anw-orange, #ff7043), var(--anw-orange-strong, #ff5d2a)) !important;
  }

  .anw-cache-panel__metrics {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px;
    margin: 0;
  }

  .anw-cache-panel__metrics > div {
    min-width: 0;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 11px;
    padding: 11px;
  }

  .anw-cache-panel__metrics > .is-reclaimable {
    border-color: #b8dec4;
    background: #f1fbf4;
  }

  .anw-cache-panel__exact-capacity {
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 10px;
    padding: 9px 11px;
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-cache-panel__exact-capacity > summary {
    cursor: pointer;
    font-weight: 650;
  }

  .anw-cache-panel__exact-capacity dl {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 7px 14px;
    margin: 10px 0 0;
  }

  .anw-cache-panel__exact-capacity dl > div {
    display: flex;
    justify-content: space-between;
    gap: 10px;
  }

  .anw-cache-panel__preview {
    border-color: #f0c9b8;
    background: #fff9f5;
  }

  .anw-cache-panel__preview > p {
    margin: 6px 0 0;
    line-height: 1.55;
  }

  .anw-cache-panel__confirm {
    display: flex;
    min-height: 44px;
    align-items: flex-start;
    gap: 9px;
    margin-top: 13px;
    border: 1px solid #f0c9b8;
    border-radius: 10px;
    padding: 10px;
    line-height: 1.45;
  }

  .anw-cache-panel__confirm input {
    width: 18px;
    height: 18px;
    margin: 1px 0 0;
  }

  .anw-cache-panel__preview-actions,
  .anw-cache-panel__actions {
    margin-top: 13px;
  }

  .anw-cache-panel__success {
    margin: 0;
    color: #235d34;
    background: #eef9f1;
  }

  @media (max-width: 720px) {
    .anw-pronunciation-panel__grid,
    .anw-pronunciation-panel__preview-controls {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 560px) {
    .anw-pronunciation-panel,
    .anw-cache-panel {
      border-radius: 12px;
      padding: 14px;
    }

    .anw-pronunciation-panel__header,
    .anw-cache-panel__header,
    .anw-pronunciation-panel__section-heading,
    .anw-pronunciation-panel__footer,
    .anw-cache-panel__preview-actions,
    .anw-cache-panel__actions {
      align-items: stretch;
      flex-direction: column;
    }

    .anw-pronunciation-panel__grid,
    .anw-pronunciation-panel__preview-controls,
    .anw-pronunciation-panel__pauses dl,
    .anw-cache-panel__metrics,
    .anw-cache-panel__exact-capacity dl,
    .anw-cache-panel__preview dl {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-pronunciation-panel button,
    .anw-cache-panel button {
      width: 100%;
    }
  }
`;
