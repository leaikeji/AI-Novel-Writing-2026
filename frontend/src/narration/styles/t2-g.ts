/** Local T2-G fragment. T2-GATE owns composition into narration/styles.ts. */
export const T2_G_NARRATION_READING_RULES_STYLES = `
  .anw-reading-rules-panel,
  .anw-reading-status {
    min-width: 0;
    width: 100%;
    max-width: 100%;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 16px;
    padding: 18px;
    color: var(--anw-text, #343844);
    background: var(--anw-card, #fff);
  }

  .anw-reading-rules-panel > header,
  .anw-reading-rules-panel > footer,
  .anw-reading-status > header {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .anw-reading-rules-panel h2,
  .anw-reading-status h2 {
    margin: 3px 0 0;
    color: var(--anw-ink, #17191f);
    font-size: 18px;
    line-height: 1.35;
  }

  .anw-reading-rules-panel h3,
  .anw-reading-status h3 {
    margin: 0;
    color: var(--anw-ink, #17191f);
    font-size: 14px;
  }

  .anw-reading-rules-panel__eyebrow,
  .anw-reading-status__eyebrow {
    margin: 0;
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-reading-rules-panel fieldset,
  .anw-reading-rules-panel__consent,
  .anw-reading-status__issues {
    min-width: 0;
    margin: 16px 0 0;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 13px;
    padding: 14px;
  }

  .anw-reading-rules-panel fieldset {
    display: grid;
    gap: 10px;
  }

  .anw-reading-rules-panel fieldset:disabled {
    opacity: 0.66;
  }

  .anw-reading-rules-panel legend {
    padding: 0 5px;
    color: var(--anw-ink, #17191f);
    font-size: 13px;
    font-weight: 750;
  }

  .anw-reading-rules-panel fieldset > label,
  .anw-reading-rules-panel__consent label {
    display: grid;
    min-width: 0;
    grid-template-columns: 20px minmax(0, 1fr);
    column-gap: 9px;
    row-gap: 3px;
    align-items: start;
    border-radius: 10px;
    padding: 10px;
    background: var(--anw-panel-soft, #f6f7f9);
  }

  .anw-reading-rules-panel label input {
    width: 18px;
    height: 18px;
    margin: 1px 0 0;
  }

  .anw-reading-rules-panel label span,
  .anw-reading-rules-panel__consent label {
    color: var(--anw-ink, #17191f);
    font-weight: 700;
  }

  .anw-reading-rules-panel label small {
    grid-column: 2;
    color: var(--anw-muted, #737987);
    font-size: 12px;
    line-height: 1.55;
  }

  .anw-reading-rules-panel__notice,
  .anw-reading-rules-panel__error,
  .anw-reading-rules-panel__status {
    margin: 14px 0 0;
    border-radius: 11px;
    padding: 11px 13px;
  }

  .anw-reading-rules-panel__notice {
    color: #704b00;
    background: #fff7dc;
  }

  .anw-reading-rules-panel__error {
    display: grid;
    gap: 8px;
    color: #8d2424;
    background: #fff0f0;
  }

  .anw-reading-rules-panel__status,
  .anw-reading-status__ok {
    color: #155d3a;
    background: #edf9f2;
  }

  .anw-reading-rules-panel__consent {
    background: #f5f8ff;
  }

  .anw-reading-rules-panel__consent p {
    margin: 7px 0 0;
    line-height: 1.55;
  }

  .anw-reading-rules-panel__consent > div,
  .anw-reading-rules-panel__consent > div > div {
    display: grid;
    gap: 10px;
    margin-top: 10px;
  }

  .anw-reading-rules-panel button,
  .anw-reading-status button {
    min-height: 42px;
    border: 1px solid #cfd3dc;
    border-radius: 10px;
    padding: 8px 12px;
    color: inherit;
    background: #fff;
  }

  .anw-reading-rules-panel button:not(:disabled),
  .anw-reading-status button:not(:disabled) {
    cursor: pointer;
  }

  .anw-reading-rules-panel button:focus-visible,
  .anw-reading-rules-panel input:focus-visible,
  .anw-reading-status button:focus-visible {
    outline: 3px solid rgba(48, 103, 214, 0.35);
    outline-offset: 2px;
  }

  .anw-reading-rules-panel button:disabled {
    cursor: not-allowed;
    opacity: 0.56;
  }

  .anw-reading-rules-panel__save {
    border-color: var(--anw-accent, #3067d6) !important;
    color: #fff !important;
    background: var(--anw-accent, #3067d6) !important;
  }

  .anw-reading-rules-panel > footer {
    align-items: flex-end;
    margin-top: 16px;
  }

  .anw-reading-rules-panel > footer p {
    margin: 0;
    color: var(--anw-muted, #737987);
    font-size: 12px;
    line-height: 1.55;
  }

  .anw-reading-status__grid {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
    margin: 16px 0 0;
  }

  .anw-reading-status__grid > div {
    min-width: 0;
    border-radius: 11px;
    padding: 12px;
    background: var(--anw-panel-soft, #f6f7f9);
  }

  .anw-reading-status dt {
    color: var(--anw-muted, #737987);
    font-size: 11px;
  }

  .anw-reading-status dd {
    overflow-wrap: anywhere;
    margin: 5px 0 0;
    color: var(--anw-ink, #17191f);
    font-weight: 750;
  }

  .anw-reading-status__grid p,
  .anw-reading-status__issues code {
    overflow-wrap: anywhere;
    margin: 5px 0 0;
    color: var(--anw-muted, #737987);
    font-size: 11px;
  }

  .anw-reading-status__ok {
    margin: 14px 0 0;
    border-radius: 11px;
    padding: 11px 13px;
  }

  .anw-reading-status__issues ul {
    display: grid;
    gap: 9px;
    margin: 10px 0 0;
    padding: 0;
    list-style: none;
  }

  .anw-reading-status__issues li {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    border-left: 4px solid #b77700;
    border-radius: 8px;
    padding: 10px;
    background: #fff9e8;
  }

  .anw-reading-status__issues li[data-severity="blocker"] {
    border-left-color: #b43131;
    background: #fff0f0;
  }

  .anw-reading-status__issues li[data-severity="info"] {
    border-left-color: #4777b8;
    background: #f3f7ff;
  }

  .anw-reading-status__issues li > div {
    display: grid;
    min-width: 0;
    gap: 3px;
  }

  .anw-reading-preferences-panel,
  .anw-reading-rules-workspace,
  .anw-scope-overrides-panel {
    min-width: 0;
    width: 100%;
    max-width: 100%;
    color: var(--anw-text, #343844);
  }

  .anw-reading-preferences-panel,
  .anw-reading-rules-workspace {
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 16px;
    padding: 18px;
    background: var(--anw-card, #fff);
  }

  .anw-reading-preferences-panel__header,
  .anw-reading-preferences-panel__section-heading,
  .anw-scope-overrides-panel__body > header,
  .anw-scope-overrides-panel footer {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .anw-reading-preferences-panel h2,
  .anw-reading-rules-workspace > header h2,
  .anw-scope-overrides-panel h2 {
    margin: 3px 0 0;
    color: var(--anw-ink, #17191f);
    font-size: 18px;
    line-height: 1.35;
  }

  .anw-reading-preferences-panel h3,
  .anw-scope-overrides-panel h3 {
    margin: 0;
    color: var(--anw-ink, #17191f);
    font-size: 14px;
  }

  .anw-reading-preferences-panel__eyebrow,
  .anw-reading-rules-workspace__eyebrow,
  .anw-reading-preferences-panel__version {
    margin: 0;
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-reading-preferences-panel__intro,
  .anw-reading-rules-workspace > header p,
  .anw-scope-overrides-panel__body > header p,
  .anw-reading-preferences-panel__section-heading p {
    margin: 5px 0 0;
    color: var(--anw-muted, #737987);
    font-size: 12px;
    line-height: 1.55;
  }

  .anw-reading-preferences-panel__section {
    display: grid;
    min-width: 0;
    gap: 12px;
    margin-top: 16px;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 13px;
    padding: 14px;
  }

  .anw-reading-preferences-panel__section-heading > span.is-unsaved {
    color: #8b5300;
    font-weight: 700;
  }

  .anw-reading-preferences-panel fieldset,
  .anw-scope-overrides-panel fieldset {
    display: grid;
    min-width: 0;
    gap: 10px;
    margin: 0;
    border: 0;
    padding: 0;
  }

  .anw-reading-preferences-panel legend,
  .anw-scope-overrides-panel legend {
    margin-bottom: 6px;
    padding: 0;
    color: var(--anw-ink, #17191f);
    font-size: 13px;
    font-weight: 750;
  }

  .anw-reading-preferences-panel fieldset > label,
  .anw-scope-overrides-panel fieldset > label,
  .anw-scope-overrides-panel__checks label,
  .anw-scope-overrides-panel__advanced label {
    display: grid;
    min-width: 0;
    gap: 6px;
    color: var(--anw-ink, #17191f);
    font-size: 12px;
    font-weight: 650;
  }

  .anw-reading-preferences-panel fieldset > label:has(input[type="range"]) {
    grid-template-columns: minmax(100px, .3fr) minmax(56px, auto) minmax(180px, 1fr);
    align-items: center;
  }

  .anw-reading-preferences-panel fieldset > label:has(input[type="range"]) input {
    grid-column: 3;
  }

  .anw-reading-preferences-panel__check,
  .anw-scope-overrides-panel__check,
  .anw-scope-overrides-panel__checks label {
    grid-template-columns: 20px minmax(0, 1fr) !important;
    align-items: start;
    border-radius: 10px;
    padding: 10px;
    background: var(--anw-panel-soft, #f6f7f9);
  }

  .anw-reading-preferences-panel__check input,
  .anw-scope-overrides-panel__check input,
  .anw-scope-overrides-panel__checks input {
    width: 18px;
    height: 18px;
    margin: 1px 0 0;
  }

  .anw-reading-preferences-panel select,
  .anw-reading-preferences-panel input[type="number"],
  .anw-reading-preferences-panel button,
  .anw-scope-overrides-panel select,
  .anw-scope-overrides-panel input[type="number"],
  .anw-scope-overrides-panel button,
  .anw-reading-rules-workspace nav button {
    min-width: 0;
    min-height: 44px;
    border: 1px solid #cfd3dc;
    border-radius: 10px;
    padding: 8px 11px;
    color: inherit;
    background: #fff;
  }

  .anw-reading-preferences-panel select,
  .anw-reading-preferences-panel input[type="number"],
  .anw-scope-overrides-panel select,
  .anw-scope-overrides-panel input[type="number"] {
    width: 100%;
  }

  .anw-reading-preferences-panel button:not(:disabled),
  .anw-scope-overrides-panel button:not(:disabled),
  .anw-reading-rules-workspace nav button:not(:disabled) {
    cursor: pointer;
  }

  .anw-reading-preferences-panel button:focus-visible,
  .anw-reading-preferences-panel input:focus-visible,
  .anw-reading-preferences-panel select:focus-visible,
  .anw-reading-preferences-panel summary:focus-visible,
  .anw-scope-overrides-panel button:focus-visible,
  .anw-scope-overrides-panel input:focus-visible,
  .anw-scope-overrides-panel select:focus-visible,
  .anw-scope-overrides-panel summary:focus-visible,
  .anw-reading-rules-workspace button:focus-visible,
  .anw-reading-rules-workspace__section:focus-visible {
    outline: 3px solid rgba(48, 103, 214, .32);
    outline-offset: 2px;
  }

  .anw-reading-preferences-panel__pause-presets,
  .anw-scope-overrides-panel__pause-presets {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 9px;
  }

  .anw-reading-preferences-panel__pause-presets > label,
  .anw-scope-overrides-panel__pause-presets > label {
    display: grid;
    min-width: 0;
    grid-template-columns: 20px minmax(0, 1fr);
    gap: 5px 8px;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 11px;
    padding: 11px;
    background: #fff;
  }

  .anw-reading-preferences-panel__pause-presets > label.is-selected,
  .anw-scope-overrides-panel__pause-presets > label.is-selected {
    border-color: #7d9fe5;
    background: #f2f6ff;
  }

  .anw-reading-preferences-panel__pause-presets small {
    grid-column: 2;
    color: var(--anw-muted, #737987);
    font-weight: 400;
    line-height: 1.45;
  }

  .anw-reading-preferences-panel__custom {
    grid-column: 1 / -1;
    margin: 0;
    color: #704b00;
    font-size: 12px;
  }

  .anw-reading-preferences-panel__advanced,
  .anw-scope-overrides-panel__advanced {
    border-radius: 11px;
    background: var(--anw-panel-soft, #f6f7f9);
  }

  .anw-reading-preferences-panel__advanced summary,
  .anw-scope-overrides-panel__advanced summary {
    min-height: 44px;
    padding: 12px;
    cursor: pointer;
    color: var(--anw-ink, #17191f);
    font-size: 12px;
    font-weight: 700;
  }

  .anw-reading-preferences-panel__advanced > p {
    margin: 0;
    padding: 0 12px;
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-reading-preferences-panel__advanced > div,
  .anw-scope-overrides-panel__advanced > div {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 9px;
    padding: 12px;
  }

  .anw-reading-preferences-panel__save,
  .anw-scope-overrides-panel__save {
    justify-self: end;
    border-color: var(--anw-accent, #3067d6) !important;
    color: #fff !important;
    background: var(--anw-accent, #3067d6) !important;
  }

  .anw-reading-preferences-panel__notice,
  .anw-reading-preferences-panel__error,
  .anw-reading-preferences-panel__status,
  .anw-scope-overrides-panel__notice,
  .anw-scope-overrides-panel__error,
  .anw-scope-overrides-panel__status,
  .anw-scope-overrides-panel__inherited {
    margin: 14px 0 0;
    border-radius: 11px;
    padding: 11px 13px;
  }

  .anw-reading-preferences-panel__notice,
  .anw-scope-overrides-panel__notice {
    color: #704b00;
    background: #fff7dc;
  }

  .anw-reading-preferences-panel__error,
  .anw-scope-overrides-panel__error {
    color: #8d2424;
    background: #fff0f0;
  }

  .anw-reading-preferences-panel__status,
  .anw-scope-overrides-panel__status,
  .anw-scope-overrides-panel__inherited {
    color: #155d3a;
    background: #edf9f2;
  }

  .anw-reading-preferences-panel__sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
  }

  .anw-scope-overrides-panel {
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 14px;
    background: var(--anw-card, #fff);
  }

  .anw-scope-overrides-panel > summary {
    display: flex;
    min-height: 52px;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 13px 16px;
    cursor: pointer;
    font-weight: 750;
  }

  .anw-scope-overrides-panel > summary small {
    color: var(--anw-muted, #737987);
    font-weight: 400;
  }

  .anw-scope-overrides-panel__body {
    display: grid;
    min-width: 0;
    gap: 14px;
    border-top: 1px solid var(--anw-line, #e7e9ee);
    padding: 16px;
  }

  .anw-scope-overrides-panel__inheritance {
    border-radius: 11px;
    padding: 12px;
    background: #f5f8ff;
  }

  .anw-scope-overrides-panel__inheritance ol {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 8px;
    margin: 9px 0 0;
    padding: 0;
    list-style: none;
  }

  .anw-scope-overrides-panel__inheritance li {
    border-radius: 999px;
    padding: 5px 9px;
    background: #e8eefb;
    font-size: 12px;
  }

  .anw-scope-overrides-panel__inheritance li[aria-current="step"] {
    color: #fff;
    background: var(--anw-accent, #3067d6);
  }

  .anw-scope-overrides-panel__inheritance p {
    margin: 8px 0 0;
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-scope-overrides-panel__checks {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .anw-reading-rules-workspace {
    display: grid;
    gap: 16px;
  }

  .anw-reading-rules-workspace > header p:last-child {
    max-width: 70ch;
  }

  .anw-reading-rules-workspace nav {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    gap: 8px;
  }

  .anw-reading-rules-workspace nav button[aria-current="page"] {
    border-color: var(--anw-accent, #3067d6);
    color: #fff;
    background: var(--anw-accent, #3067d6);
  }

  .anw-reading-rules-workspace__section {
    min-width: 0;
    scroll-margin-top: 16px;
  }

  @media (max-width: 840px) {
    .anw-reading-status__grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 560px) {
    .anw-reading-rules-panel,
    .anw-reading-status,
    .anw-reading-preferences-panel,
    .anw-reading-rules-workspace {
      border-radius: 13px;
      padding: 14px;
    }

    .anw-reading-rules-panel > header,
    .anw-reading-rules-panel > footer,
    .anw-reading-preferences-panel__header,
    .anw-reading-preferences-panel__section-heading,
    .anw-scope-overrides-panel__body > header,
    .anw-scope-overrides-panel footer,
    .anw-reading-status__issues li {
      align-items: stretch;
      flex-direction: column;
    }

    .anw-reading-status__grid {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-reading-preferences-panel fieldset > label:has(input[type="range"]),
    .anw-reading-preferences-panel__advanced > div,
    .anw-scope-overrides-panel__advanced > div,
    .anw-reading-preferences-panel__pause-presets,
    .anw-scope-overrides-panel__pause-presets,
    .anw-scope-overrides-panel__checks {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-reading-preferences-panel fieldset > label:has(input[type="range"]) input {
      grid-column: 1;
    }

    .anw-scope-overrides-panel > summary {
      align-items: flex-start;
      flex-direction: column;
    }

    .anw-reading-rules-panel button,
    .anw-reading-status button,
    .anw-reading-preferences-panel button,
    .anw-scope-overrides-panel button {
      width: 100%;
    }
  }
`;


export const T2_G_NARRATION_STYLE_ID = "ai-novel-world-narration-t2-g-styles";
