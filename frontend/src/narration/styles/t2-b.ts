/** T2-B local style fragment. T2-GATE is the only owner allowed to compose it globally. */
export const T2_B_READING_STYLES = String.raw`
  .anw-reading-page {
    --anw-reading-accent: #d76832;
    --anw-reading-accent-soft: #fff3eb;
    --anw-reading-border: color-mix(in srgb, currentColor 14%, transparent);
    --anw-reading-muted: color-mix(in srgb, currentColor 62%, transparent);
    box-sizing: border-box;
    min-height: 100%;
    padding: 24px;
    color: inherit;
    overflow: auto;
  }

  .anw-reading-page *,
  .anw-reading-page *::before,
  .anw-reading-page *::after {
    box-sizing: border-box;
  }

  .anw-reading-page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 24px;
    max-width: 1320px;
    margin: 0 auto 20px;
  }

  .anw-reading-page-header h1,
  .anw-reading-section-heading h2,
  .anw-reading-status-card h3,
  .anw-reading-empty h3,
  .anw-reading-integration-slot h2 {
    margin: 0;
  }

  .anw-reading-page-header h1 {
    font-size: clamp(25px, 2vw, 32px);
    line-height: 1.2;
  }

  .anw-reading-page-header p,
  .anw-reading-section-heading p,
  .anw-reading-status-card p,
  .anw-reading-empty p,
  .anw-reading-integration-slot p {
    margin: 6px 0 0;
    color: var(--anw-reading-muted);
    line-height: 1.6;
  }

  .anw-reading-eyebrow {
    margin: 0 0 4px !important;
    color: var(--anw-reading-accent) !important;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .08em;
  }

  .anw-reading-product-state,
  .anw-reading-version {
    display: inline-flex;
    flex: 0 0 auto;
    align-items: center;
    min-height: 30px;
    padding: 5px 10px;
    border: 1px solid var(--anw-reading-border);
    border-radius: 999px;
    color: var(--anw-reading-muted);
    font-size: 12px;
    line-height: 1.4;
  }

  .anw-reading-product-state.is-enabled {
    border-color: color-mix(in srgb, #2f9e44 40%, transparent);
    color: #2f9e44;
  }

  .anw-reading-layout {
    display: grid;
    grid-template-columns: minmax(168px, 208px) minmax(0, 1fr);
    gap: 20px;
    width: 100%;
    max-width: 1320px;
    margin: 0 auto;
  }

  .anw-reading-nav {
    position: sticky;
    top: 0;
    display: flex;
    flex-direction: column;
    align-self: start;
    gap: 4px;
    padding: 8px;
    border: 1px solid var(--anw-reading-border);
    border-radius: 14px;
    background: color-mix(in srgb, Canvas 95%, transparent);
  }

  .anw-reading-nav button,
  .anw-reading-page button,
  .anw-reading-page input,
  .anw-reading-page select {
    font: inherit;
  }

  .anw-reading-nav button {
    min-height: 42px;
    padding: 8px 12px;
    border: 0;
    border-radius: 9px;
    color: inherit;
    background: transparent;
    text-align: left;
    cursor: pointer;
  }

  .anw-reading-nav button:hover,
  .anw-reading-nav button:focus-visible {
    background: color-mix(in srgb, currentColor 7%, transparent);
  }

  .anw-reading-nav button.is-active {
    color: var(--anw-reading-accent);
    background: var(--anw-reading-accent-soft);
    font-weight: 700;
  }

  .anw-reading-nav button:focus-visible,
  .anw-reading-page button:focus-visible,
  .anw-reading-page input:focus-visible,
  .anw-reading-page select:focus-visible {
    outline: 2px solid var(--anw-reading-accent);
    outline-offset: 2px;
  }

  .anw-reading-content {
    min-width: 0;
  }

  .anw-reading-overview,
  .anw-reading-narrator-panel,
  .anw-reading-scope-panel,
  .anw-reading-integration-slot {
    padding: 20px;
    border: 1px solid var(--anw-reading-border);
    border-radius: 16px;
    background: Canvas;
  }

  .anw-reading-overview.is-loading,
  .anw-reading-overview.is-error,
  .anw-reading-page.is-unavailable {
    max-width: 960px;
    margin: 0 auto;
  }

  .anw-reading-overview.is-loading {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 260px;
    gap: 12px;
  }

  .anw-reading-spinner {
    width: 22px;
    height: 22px;
    border: 2px solid var(--anw-reading-border);
    border-top-color: var(--anw-reading-accent);
    border-radius: 50%;
    animation: anw-reading-spin .8s linear infinite;
  }

  @keyframes anw-reading-spin {
    to { transform: rotate(360deg); }
  }

  @media (prefers-reduced-motion: reduce) {
    .anw-reading-spinner { animation: none; }
  }

  .anw-reading-section-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 18px;
  }

  .anw-reading-gate-notice,
  .anw-reading-operation,
  .anw-reading-empty,
  .anw-reading-field-error,
  .anw-reading-gate-inline {
    padding: 12px 14px;
    border-radius: 10px;
  }

  .anw-reading-gate-notice {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 16px;
    border: 1px solid color-mix(in srgb, #d99000 35%, transparent);
    background: color-mix(in srgb, #fff4cc 60%, Canvas);
  }

  .anw-reading-gate-notice span,
  .anw-reading-gate-inline {
    color: var(--anw-reading-muted);
  }

  .anw-reading-empty {
    margin-bottom: 16px;
    border: 1px dashed var(--anw-reading-border);
    text-align: center;
  }

  .anw-reading-empty button,
  .anw-reading-overview-actions button,
  .anw-reading-form-actions button,
  .anw-reading-operation button,
  .anw-reading-overview.is-error button,
  .anw-reading-link-button {
    min-height: 38px;
    padding: 8px 14px;
    border: 1px solid var(--anw-reading-border);
    border-radius: 9px;
    color: inherit;
    background: Canvas;
    cursor: pointer;
  }

  .anw-reading-form-actions button {
    border-color: var(--anw-reading-accent);
    color: white;
    background: var(--anw-reading-accent);
    font-weight: 700;
  }

  .anw-reading-page button:disabled,
  .anw-reading-page fieldset:disabled input,
  .anw-reading-page fieldset:disabled select {
    cursor: not-allowed;
    opacity: .58;
  }

  .anw-reading-status-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }

  .anw-reading-status-card {
    min-width: 0;
    min-height: 132px;
    padding: 14px;
    border: 1px solid var(--anw-reading-border);
    border-radius: 12px;
    background: color-mix(in srgb, Canvas 94%, currentColor 1%);
  }

  .anw-reading-status-card h3 {
    color: var(--anw-reading-muted);
    font-size: 13px;
    font-weight: 600;
  }

  .anw-reading-status-card strong {
    display: block;
    margin-top: 12px;
    overflow-wrap: anywhere;
    font-size: 18px;
  }

  .anw-reading-status-card p {
    overflow-wrap: anywhere;
    font-size: 12px;
  }

  .anw-reading-overview-actions,
  .anw-reading-form-actions {
    display: flex;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 18px;
  }

  .anw-reading-narrator-stack {
    display: grid;
    gap: 18px;
  }

  .anw-reading-form-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
    min-width: 0;
    margin: 0 0 18px;
    padding: 16px;
    border: 1px solid var(--anw-reading-border);
    border-radius: 12px;
  }

  .anw-reading-form-grid legend {
    padding: 0 7px;
    font-weight: 700;
  }

  .anw-reading-form-grid label,
  .anw-reading-readonly-field {
    display: grid;
    align-content: start;
    gap: 7px;
    min-width: 0;
  }

  .anw-reading-form-grid label > span,
  .anw-reading-readonly-field > span {
    color: var(--anw-reading-muted);
    font-size: 13px;
  }

  .anw-reading-form-grid input:not([type="checkbox"]):not([type="range"]),
  .anw-reading-form-grid select {
    width: 100%;
    min-height: 40px;
    padding: 7px 10px;
    border: 1px solid var(--anw-reading-border);
    border-radius: 8px;
    color: inherit;
    background: Canvas;
  }

  .anw-reading-form-grid input[type="range"] {
    width: 100%;
    accent-color: var(--anw-reading-accent);
  }

  .anw-reading-form-grid .anw-reading-check {
    display: flex;
    align-items: center;
    grid-template-columns: none;
    min-height: 40px;
  }

  .anw-reading-check input {
    width: 17px;
    height: 17px;
    margin: 0;
    accent-color: var(--anw-reading-accent);
  }

  .anw-reading-inline-fields {
    display: grid;
    grid-column: 1 / -1;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .anw-reading-scope-rules {
    display: grid;
    grid-column: 1 / -1;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    padding: 12px;
    border: 1px solid var(--anw-reading-border);
    border-radius: 10px;
  }

  .anw-reading-operation {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
    border: 1px solid color-mix(in srgb, #2f9e44 35%, transparent);
    background: color-mix(in srgb, #d3f9d8 45%, Canvas);
  }

  .anw-reading-operation.is-error,
  .anw-reading-field-error {
    border: 1px solid color-mix(in srgb, #d63939 38%, transparent);
    background: color-mix(in srgb, #ffe3e3 50%, Canvas);
  }

  .anw-reading-field-error,
  .anw-reading-gate-inline {
    margin: 0 0 12px;
  }

  @media (max-width: 1040px) {
    .anw-reading-status-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 760px) {
    .anw-reading-page { padding: 16px; }

    .anw-reading-page-header,
    .anw-reading-section-heading {
      flex-direction: column;
    }

    .anw-reading-layout {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-reading-nav {
      position: static;
      flex-direction: row;
      overflow-x: auto;
      scroll-snap-type: x proximity;
    }

    .anw-reading-nav button {
      flex: 0 0 auto;
      min-width: max-content;
      scroll-snap-align: start;
    }

    .anw-reading-form-grid {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-reading-inline-fields,
    .anw-reading-scope-rules {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  @media (max-width: 480px) {
    .anw-reading-status-grid {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-reading-overview,
    .anw-reading-narrator-panel,
    .anw-reading-scope-panel,
    .anw-reading-integration-slot {
      padding: 14px;
      border-radius: 12px;
    }
  }
`;
