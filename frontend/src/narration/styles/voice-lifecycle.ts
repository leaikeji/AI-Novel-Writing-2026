/** Styles are injected by the narration integration owner; this module is side-effect free. */
export const VOICE_LIFECYCLE_STYLE_ID = "anw-voice-lifecycle-styles" as const;


export const VOICE_LIFECYCLE_STYLES = `
.anw-voice-lifecycle {
  display: grid;
  gap: 14px;
  min-width: 0;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 14px;
  padding: 16px;
  color: var(--ant-color-text, #24262b);
  background: var(--ant-color-bg-container, #fff);
}
.anw-voice-lifecycle__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.anw-voice-lifecycle__header > div {
  min-width: 0;
}
.anw-voice-lifecycle__header h3,
.anw-voice-lifecycle__header p,
.anw-voice-lifecycle__status,
.anw-voice-lifecycle__error,
.anw-voice-lifecycle__countdown,
.anw-voice-lifecycle__impact h4,
.anw-voice-lifecycle__consequence,
.anw-voice-lifecycle__backup {
  margin: 0;
}
.anw-voice-lifecycle__header h3 {
  overflow-wrap: anywhere;
  font-size: 17px;
  line-height: 1.45;
}
.anw-voice-lifecycle__eyebrow {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  letter-spacing: .04em;
}
.anw-voice-lifecycle__source {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 5px 9px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-quaternary, #fafafa);
  font-size: 12px;
}
.anw-voice-lifecycle__status,
.anw-voice-lifecycle__error,
.anw-voice-lifecycle__countdown,
.anw-voice-lifecycle__backup {
  min-height: 44px;
  box-sizing: border-box;
  border-radius: 10px;
  padding: 11px 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.anw-voice-lifecycle__status {
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-tertiary, #f5f5f6);
}
.anw-voice-lifecycle__status.is-warning,
.anw-voice-lifecycle__countdown {
  color: #765d10;
  background: #fff9e8;
}
.anw-voice-lifecycle__status.is-danger,
.anw-voice-lifecycle__error {
  color: var(--ant-color-error, #b42318);
  background: #fff2ed;
}
.anw-voice-lifecycle__status.is-success {
  color: var(--ant-color-success, #176b32);
  background: #f0faf2;
}
.anw-voice-lifecycle__impact {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.anw-voice-lifecycle__impact h4 {
  font-size: 15px;
  line-height: 1.45;
}
.anw-voice-lifecycle__impact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
  margin: 0;
}
.anw-voice-lifecycle__impact-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  min-width: 0;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 9px;
  padding: 9px 10px;
}
.anw-voice-lifecycle__impact-row dt {
  min-width: 0;
  color: var(--ant-color-text-secondary, #5f6670);
  overflow-wrap: anywhere;
}
.anw-voice-lifecycle__impact-row dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
  font-weight: 650;
  text-align: right;
  overflow-wrap: anywhere;
}
.anw-voice-lifecycle__consequence,
.anw-voice-lifecycle__backup {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 13px;
  line-height: 1.55;
}
.anw-voice-lifecycle__backup {
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  background: var(--ant-color-fill-quaternary, #fafafa);
}
.anw-voice-lifecycle__backup.is-unmanaged {
  border-color: #e4d4a1;
  color: #765d10;
  background: #fff9e8;
}
.anw-voice-lifecycle__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.anw-voice-lifecycle__button {
  min-width: 44px;
  min-height: 44px;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 9px;
  padding: 9px 13px;
  color: inherit;
  background: var(--ant-color-bg-container, #fff);
  font: inherit;
  line-height: 1.35;
  cursor: pointer;
}
.anw-voice-lifecycle__button.is-danger {
  border-color: var(--ant-color-error, #b42318);
  color: var(--ant-color-error, #b42318);
  background: var(--ant-color-error-bg, #fff2ed);
  font-weight: 650;
}
.anw-voice-lifecycle__button:disabled {
  cursor: not-allowed;
  opacity: .62;
}
.anw-voice-lifecycle__button:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #d95d36) 42%, transparent);
  outline-offset: 2px;
}

@media (max-width: 720px) {
  .anw-voice-lifecycle {
    padding: 14px;
  }
  .anw-voice-lifecycle__impact-grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .anw-voice-lifecycle__actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 390px) {
  .anw-voice-lifecycle__header {
    display: grid;
  }
  .anw-voice-lifecycle__source {
    justify-self: start;
  }
  .anw-voice-lifecycle__impact-row {
    grid-template-columns: minmax(0, 1fr);
  }
  .anw-voice-lifecycle__impact-row dd {
    text-align: left;
  }
  .anw-voice-lifecycle__actions {
    grid-template-columns: minmax(0, 1fr);
  }
  .anw-voice-lifecycle__button {
    width: 100%;
  }
}

@media (forced-colors: active) {
  .anw-voice-lifecycle,
  .anw-voice-lifecycle__impact-row,
  .anw-voice-lifecycle__backup,
  .anw-voice-lifecycle__button {
    border-color: CanvasText;
  }
  .anw-voice-lifecycle__button:focus-visible {
    outline-color: Highlight;
  }
}
`;
