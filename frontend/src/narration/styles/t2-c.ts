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
  .anw-narration-character-card-panel {
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
  .anw-character-voice-roster__result,
  .anw-character-voice-roster__status {
    margin: 0;
  }

  .anw-character-voice-roster__header h2 {
    margin-top: 3px;
    color: var(--anw-ink, #17191f);
    font-size: 22px;
  }

  .anw-character-voice-roster__status {
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-character-voice-roster__status.is-error {
    color: var(--ant-color-error, #b42318);
  }

  .anw-character-voice-roster__list {
    display: grid;
    gap: 8px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .anw-character-voice-roster__card {
    display: grid;
    grid-template-columns: minmax(140px, .7fr) minmax(260px, 2fr) auto;
    align-items: center;
    min-width: 0;
    gap: 10px 16px;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 12px;
    padding: 11px 12px;
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
    align-items: flex-start;
    flex-direction: column;
    gap: 3px;
  }

  .anw-character-voice-roster__role {
    color: var(--anw-muted, #737987);
    font-size: 12px;
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
  .anw-character-voice-roster__batch:not(:disabled) {
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
    grid-column: 2 / -1;
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

  .anw-character-voice-roster__empty {
    margin: 0;
    border: 1px dashed var(--anw-line, #e7e9ee);
    border-radius: 14px;
    padding: 22px;
    color: var(--anw-muted, #737987);
    text-align: center;
  }

  .anw-character-voice-drawer-layer {
    position: fixed;
    z-index: 1150;
    inset: 0;
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    justify-items: end;
    overflow: hidden;
  }

  .anw-character-voice-drawer-layer[hidden] {
    display: none;
  }

  .anw-character-voice-drawer__backdrop {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    border: 0;
    border-radius: 0;
    padding: 0;
    background: rgba(20, 24, 32, .44);
  }

  .anw-character-voice-drawer {
    position: relative;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    width: min(760px, 92vw);
    height: 100%;
    min-width: 0;
    min-height: 0;
    max-height: 100%;
    overflow: hidden;
    color: var(--anw-text, #343844);
    background: var(--anw-card, #fff);
    box-shadow: -18px 0 48px rgba(20, 24, 32, .18);
  }

  .anw-character-voice-drawer:focus-visible {
    outline: none;
  }

  .anw-character-voice-drawer__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    border-bottom: 1px solid var(--anw-line, #e7e9ee);
    padding: 16px 20px;
  }

  .anw-character-voice-drawer__header h2,
  .anw-character-voice-drawer__header p {
    margin: 0;
  }

  .anw-character-voice-drawer__header p {
    color: var(--anw-muted, #737987);
    font-size: 12px;
  }

  .anw-character-voice-drawer__close {
    min-width: 44px;
    min-height: 44px;
    border: 1px solid #cfd3dc;
    border-radius: 10px;
    padding: 8px 12px;
    color: inherit;
    background: #fff;
    cursor: pointer;
  }

  .anw-character-voice-drawer__body {
    box-sizing: border-box;
    min-width: 0;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 18px 20px 32px;
    overscroll-behavior: contain;
    scrollbar-color: rgba(103, 110, 124, .42) transparent;
    scrollbar-gutter: stable;
    scrollbar-width: thin;
    touch-action: pan-y;
  }

  .anw-character-voice-drawer__body::-webkit-scrollbar {
    width: 10px;
  }

  .anw-character-voice-drawer__body::-webkit-scrollbar-track {
    background: transparent;
  }

  .anw-character-voice-drawer__body::-webkit-scrollbar-thumb {
    border: 3px solid transparent;
    border-radius: 999px;
    background: rgba(103, 110, 124, .42);
    background-clip: padding-box;
  }

  .anw-character-voice-configurator {
    display: grid;
    min-width: 0;
    gap: 14px;
  }

  .anw-character-voice-configurator__match {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px 16px;
    border: 1px solid color-mix(in srgb, var(--anw-orange, #ff7043) 28%, transparent);
    border-radius: 13px;
    padding: 14px 16px;
    background: #fffaf6;
  }

  .anw-character-voice-configurator__match h3,
  .anw-character-voice-configurator__match p {
    margin: 0;
  }

  .anw-character-voice-configurator__match h3 {
    font-size: 16px;
  }

  .anw-character-voice-configurator__match > div > p,
  .anw-character-voice-configurator__match-status {
    margin-top: 3px;
    color: var(--anw-muted, #737987);
    font-size: 12px;
    line-height: 1.5;
  }

  .anw-character-voice-configurator__match-status {
    grid-column: 1 / -1;
  }

  .anw-character-voice-configurator__match-status:empty {
    display: none;
  }

  .anw-character-voice-configurator__match-status.is-error {
    color: var(--ant-color-error, #b42318);
  }

  .anw-character-voice-configurator__match button {
    min-height: 44px;
    border: 1px solid transparent;
    border-radius: 9px;
    padding: 8px 13px;
    color: #fff;
    background: linear-gradient(135deg, var(--anw-orange, #ff7043), var(--anw-orange-strong, #ff5d2a));
    font: inherit;
    font-weight: 650;
    cursor: pointer;
  }

  .anw-character-voice-configurator__match button.anw-character-voice-configurator__secondary {
    grid-column: 2;
    color: inherit;
    background: #fff;
    border-color: #cfd3dc;
  }

  .anw-character-voice-configurator__match button:disabled {
    cursor: not-allowed;
    opacity: .58;
  }

  .anw-character-voice-configurator__disclosure {
    min-width: 0;
    border: 1px solid var(--anw-line, #e7e9ee);
    border-radius: 12px;
    background: var(--anw-card, #fff);
    overflow: clip;
  }

  .anw-character-voice-configurator__disclosure > summary {
    display: flex;
    min-height: 54px;
    box-sizing: border-box;
    align-items: center;
    justify-content: space-between;
    padding: 11px 14px;
    list-style: none;
    cursor: pointer;
  }

  .anw-character-voice-configurator__disclosure > summary::-webkit-details-marker {
    display: none;
  }

  .anw-character-voice-configurator__disclosure > summary::after {
    content: "⌄";
    color: var(--anw-muted, #737987);
    font-size: 18px;
  }

  .anw-character-voice-configurator__disclosure[open] > summary::after {
    transform: rotate(180deg);
  }

  .anw-character-voice-configurator__disclosure > summary span {
    display: grid;
    gap: 2px;
  }

  .anw-character-voice-configurator__disclosure > summary small {
    color: var(--anw-muted, #737987);
    font-size: 12px;
    font-weight: 400;
  }

  .anw-character-voice-configurator__disclosure-body {
    display: grid;
    min-width: 0;
    gap: 14px;
    border-top: 1px solid var(--anw-line, #e7e9ee);
    padding: 14px;
  }

  .anw-character-voice-configurator__disclosure:not([open])
    > .anw-character-voice-configurator__disclosure-body {
    display: none;
  }

  .anw-character-voice-configurator button:focus-visible,
  .anw-character-voice-configurator summary:focus-visible,
  .anw-character-voice-drawer button:focus-visible {
    outline: 3px solid rgba(255, 93, 42, .28);
    outline-offset: 2px;
  }

  @media (max-width: 900px) {
    .anw-character-voice-roster__card {
      grid-template-columns: minmax(120px, .7fr) minmax(220px, 1.6fr);
    }

    .anw-character-voice-roster__actions {
      grid-column: 1 / -1;
      justify-content: flex-end;
    }
  }

  @media (max-width: 768px) {
    .anw-character-voice-roster__header {
      align-items: stretch;
      flex-direction: column;
    }

    .anw-character-voice-roster__card {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-character-voice-roster__result,
    .anw-character-voice-roster__actions {
      grid-column: 1;
    }

    .anw-character-voice-roster__actions {
      align-items: stretch;
      flex-direction: column;
    }

    .anw-character-voice-roster__actions button,
    .anw-character-voice-roster__batch {
      width: 100%;
    }

    .anw-character-voice-drawer {
      width: 100vw;
      height: 100dvh;
    }

    .anw-character-voice-drawer__header,
    .anw-character-voice-drawer__body {
      padding-inline: 14px;
    }

    .anw-character-voice-configurator__match {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-character-voice-configurator__match button,
    .anw-character-voice-configurator__match button.anw-character-voice-configurator__secondary {
      grid-column: 1;
      width: 100%;
    }
  }
`;
