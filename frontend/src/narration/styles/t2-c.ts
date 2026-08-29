/** Local T2-C fragment. T2-GATE owns composition into narration/styles.ts. */
export const T2_C_CHARACTER_VOICE_PANEL_STYLES = `
  .anw-character-voice-panel {
    min-width: 0;
    width: 100%;
    max-width: 100%;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 16px;
    padding: 18px;
    color: var(--anw-text, #343844);
    background: var(--anw-card, #fff);
  }

  .anw-character-voice-panel__header,
  .anw-character-voice-panel__footer {
    display: flex;
    min-width: 0;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .anw-character-voice-panel__header h3 {
    margin: 3px 0 0;
    font-size: 18px;
    line-height: 1.35;
  }

  .anw-character-voice-panel__eyebrow,
  .anw-character-voice-panel__version {
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-character-voice-panel__live {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

  .anw-character-voice-panel__notice,
  .anw-character-voice-panel__error,
  .anw-character-voice-panel__impact {
    margin: 14px 0 0;
    border-radius: 12px;
    padding: 12px 14px;
  }

  .anw-character-voice-panel__notice {
    color: #704b00;
    background: #fff7dc;
  }

  .anw-character-voice-panel__error {
    display: grid;
    gap: 8px;
    color: #8d2424;
    background: #fff0f0;
  }

  .anw-character-voice-panel__error button {
    justify-self: start;
  }

  .anw-character-voice-panel__body {
    display: grid;
    min-width: 0;
    gap: 16px;
    margin-top: 16px;
  }

  .anw-character-voice-panel fieldset {
    display: grid;
    min-width: 0;
    gap: 8px;
    margin: 0;
    border: 0;
    padding: 0;
  }

  .anw-character-voice-panel legend,
  .anw-character-voice-panel__field > label,
  .anw-character-voice-panel__impact h4 {
    color: var(--anw-ink, #17191f);
    font-size: 13px;
    font-weight: 700;
  }

  .anw-character-voice-panel__radio {
    display: flex;
    min-height: 38px;
    align-items: center;
    gap: 9px;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 10px;
    padding: 7px 10px;
  }

  .anw-character-voice-panel__field {
    display: grid;
    min-width: 0;
    gap: 7px;
  }

  .anw-character-voice-panel select,
  .anw-character-voice-panel input[type="text"] {
    min-width: 0;
    width: 100%;
    min-height: 42px;
    border: 1px solid #cfd3dc;
    border-radius: 10px;
    padding: 8px 10px;
    color: inherit;
    background: #fff;
  }

  .anw-character-voice-panel button {
    min-height: 42px;
    border: 1px solid #cfd3dc;
    border-radius: 10px;
    padding: 8px 13px;
    color: inherit;
    background: #fff;
    cursor: pointer;
  }

  .anw-character-voice-panel button:focus-visible,
  .anw-character-voice-panel input:focus-visible,
  .anw-character-voice-panel select:focus-visible {
    outline: 3px solid rgba(255, 93, 42, .28);
    outline-offset: 2px;
  }

  .anw-character-voice-panel button:disabled,
  .anw-character-voice-panel input:disabled,
  .anw-character-voice-panel select:disabled {
    cursor: not-allowed;
    opacity: .58;
  }

  .anw-character-voice-panel__hint,
  .anw-character-voice-panel__loading {
    margin: 0;
    color: var(--anw-muted, #737987);
    font-size: 12px;
    line-height: 1.55;
  }

  .anw-character-voice-panel__validation {
    color: #a52b2b;
    font-size: 12px;
  }

  .anw-character-voice-panel__impact {
    border: 1px solid #dce8ff;
    background: #f5f8ff;
  }

  .anw-character-voice-panel__impact h4,
  .anw-character-voice-panel__impact p {
    margin: 0;
  }

  .anw-character-voice-panel__impact dl {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
    margin: 12px 0;
  }

  .anw-character-voice-panel__impact dl > div {
    min-width: 0;
    border-radius: 9px;
    padding: 9px;
    background: #fff;
  }

  .anw-character-voice-panel__impact dt {
    color: var(--anw-muted, #737987);
    font-size: 11px;
  }

  .anw-character-voice-panel__impact dd {
    margin: 3px 0 0;
    color: var(--anw-ink, #17191f);
    font-weight: 750;
  }

  .anw-character-voice-panel__save {
    border: 0 !important;
    color: #fff !important;
    background: linear-gradient(135deg, var(--anw-orange, #ff7043), var(--anw-orange-strong, #ff5d2a)) !important;
  }

  .anw-narration-character-section,
  .anw-narration-character-card-panel,
  .anw-narration-source-summary {
    display: grid;
    min-width: 0;
    gap: 18px;
  }

  .anw-character-voice-roster {
    display: grid;
    min-width: 0;
    gap: 14px;
  }

  .anw-character-voice-roster__header {
    display: flex;
    min-width: 0;
    align-items: end;
    justify-content: space-between;
    gap: 16px;
  }

  .anw-character-voice-roster__header h2,
  .anw-character-voice-roster__header p,
  .anw-character-voice-roster__eyebrow,
  .anw-character-voice-roster__result,
  .anw-character-voice-roster__status {
    margin: 0;
  }

  .anw-character-voice-roster__header h2 {
    margin-top: 3px;
    color: var(--anw-ink, #17191f);
    font-size: 22px;
  }

  .anw-character-voice-roster__eyebrow,
  .anw-character-voice-roster__version,
  .anw-character-voice-roster__status {
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-character-voice-roster__list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
    gap: 12px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .anw-character-voice-roster__card {
    display: grid;
    min-width: 0;
    gap: 12px;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 14px;
    padding: 14px;
    background: var(--anw-card, #fff);
  }

  .anw-character-voice-roster__card.is-unconfigured {
    border-style: dashed;
    background: #fffdf9;
  }

  .anw-character-voice-roster__identity,
  .anw-character-voice-roster__binding,
  .anw-character-voice-roster__actions {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }

  .anw-character-voice-roster__identity {
    justify-content: space-between;
  }

  .anw-character-voice-roster__coverage,
  .anw-character-voice-roster__source {
    border-radius: 999px;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 700;
  }

  .anw-character-voice-roster__coverage.is-configured,
  .anw-character-voice-roster__source.is-official {
    color: #235f3a;
    background: #eaf8ef;
  }

  .anw-character-voice-roster__coverage.is-missing {
    color: #805600;
    background: #fff4cf;
  }

  .anw-character-voice-roster__source.is-private {
    color: #314c86;
    background: #edf2ff;
  }

  .anw-character-voice-roster__source.is-unresolved {
    color: #7a3030;
    background: #fff0f0;
  }

  .anw-character-voice-roster__actions button,
  .anw-character-voice-roster__batch {
    min-height: 44px;
    border: 1px solid #cfd3dc;
    border-radius: 10px;
    padding: 8px 12px;
    color: inherit;
    background: #fff;
    cursor: pointer;
  }

  .anw-character-voice-roster__batch,
  .anw-character-voice-roster__generate:not(:disabled) {
    border-color: transparent !important;
    color: #fff !important;
    background: linear-gradient(135deg, var(--anw-orange, #ff7043), var(--anw-orange-strong, #ff5d2a)) !important;
  }

  .anw-character-voice-roster button:focus-visible {
    outline: 3px solid rgba(255, 93, 42, .28);
    outline-offset: 2px;
  }

  .anw-character-voice-roster button:disabled {
    cursor: not-allowed;
    opacity: .58;
  }

  .anw-character-voice-roster__result {
    border-radius: 9px;
    padding: 8px 10px;
    font-size: 12px;
  }

  .anw-character-voice-roster__result.is-running {
    color: #704b00;
    background: #fff7dc;
  }

  .anw-character-voice-roster__result.is-success {
    color: #235f3a;
    background: #eaf8ef;
  }

  .anw-character-voice-roster__result.is-error {
    color: #8d2424;
    background: #fff0f0;
  }

  .anw-character-voice-roster__generator-note {
    margin: 0;
    border-radius: 9px;
    padding: 9px 11px;
    color: var(--anw-muted, #737987);
    background: #f5f6f8;
    font-size: 12px;
  }

  .anw-character-voice-roster__empty {
    margin: 0;
    border: 1px dashed var(--anw-line, #e7e9ee);
    border-radius: 14px;
    padding: 22px;
    color: var(--anw-muted, #737987);
    text-align: center;
  }

  @media (max-width: 640px) {
    .anw-character-voice-roster__header {
      align-items: stretch;
      flex-direction: column;
    }

    .anw-character-voice-roster__actions {
      align-items: stretch;
      flex-direction: column;
    }

    .anw-character-voice-roster__actions button,
    .anw-character-voice-roster__batch {
      width: 100%;
    }
  }
`;
