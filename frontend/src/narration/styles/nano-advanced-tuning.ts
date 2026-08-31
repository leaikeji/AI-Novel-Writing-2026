/** Styles are injected by the narration integration owner; this module is side-effect free. */
export const NANO_ADVANCED_TUNING_STYLE_ID = "anw-nano-advanced-tuning-styles" as const;

export const NANO_ADVANCED_TUNING_STYLES = `
.anw-nano-tuning {
  display: grid;
  gap: 16px;
  min-width: 0;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 14px;
  padding: 16px;
  color: var(--ant-color-text, #24262b);
  background: var(--ant-color-bg-container, #fff);
}
.anw-nano-tuning__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}
.anw-nano-tuning__header > div {
  min-width: 0;
}
.anw-nano-tuning__header h3,
.anw-nano-tuning__header p,
.anw-nano-tuning__description,
.anw-nano-tuning__status,
.anw-nano-tuning__error {
  margin: 0;
}
.anw-nano-tuning__header h3 {
  overflow-wrap: anywhere;
  font-size: 17px;
  line-height: 1.45;
}
.anw-nano-tuning__eyebrow,
.anw-nano-tuning__hint {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
}
.anw-nano-tuning__eyebrow {
  letter-spacing: .04em;
}
.anw-nano-tuning__fixed {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 5px 9px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-quaternary, #fafafa);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.anw-nano-tuning__description {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 13px;
  line-height: 1.6;
}
.anw-nano-tuning__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  min-width: 0;
}
.anw-nano-tuning__field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px 10px;
  min-width: 0;
}
.anw-nano-tuning__field label {
  min-width: 0;
  font-weight: 650;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.anw-nano-tuning__hint {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.anw-nano-tuning__field input {
  grid-column: 1 / -1;
  width: 100%;
  min-width: 0;
  min-height: 44px;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 9px;
  padding: 9px 11px;
  color: inherit;
  background: var(--ant-color-bg-container, #fff);
  font: inherit;
  font-variant-numeric: tabular-nums;
}
.anw-nano-tuning__field input[aria-invalid="true"] {
  border-color: var(--ant-color-error, #b42318);
}
.anw-nano-tuning__field-error {
  grid-column: 1 / -1;
  color: var(--ant-color-error, #b42318);
  font-size: 12px;
  line-height: 1.45;
}
.anw-nano-tuning__status,
.anw-nano-tuning__error {
  min-height: 44px;
  box-sizing: border-box;
  border-radius: 10px;
  padding: 11px 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.anw-nano-tuning__status {
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-tertiary, #f5f5f6);
}
.anw-nano-tuning__status.is-warning {
  color: #765d10;
  background: #fff9e8;
}
.anw-nano-tuning__status.is-danger,
.anw-nano-tuning__error {
  color: var(--ant-color-error, #b42318);
  background: #fff2ed;
}
.anw-nano-tuning__status.is-success {
  color: var(--ant-color-success, #176b32);
  background: #f0faf2;
}
.anw-nano-tuning__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.anw-nano-tuning__button {
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
.anw-nano-tuning__button.is-primary {
  border-color: var(--ant-color-primary, #d95d36);
  color: var(--ant-color-primary, #d95d36);
  background: color-mix(in srgb, var(--ant-color-primary, #d95d36) 9%, transparent);
  font-weight: 650;
}
.anw-nano-tuning__button:disabled,
.anw-nano-tuning__field input:disabled {
  cursor: not-allowed;
  opacity: .62;
}
.anw-nano-tuning__button:focus-visible,
.anw-nano-tuning__field input:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #d95d36) 42%, transparent);
  outline-offset: 2px;
}

@media (max-width: 720px) {
  .anw-nano-tuning {
    padding: 14px;
  }
  .anw-nano-tuning__grid {
    grid-template-columns: minmax(0, 1fr);
  }
  .anw-nano-tuning__actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 390px) {
  .anw-nano-tuning__header,
  .anw-nano-tuning__field {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }
  .anw-nano-tuning__fixed {
    justify-self: start;
  }
  .anw-nano-tuning__hint {
    text-align: left;
  }
  .anw-nano-tuning__actions {
    grid-template-columns: minmax(0, 1fr);
  }
  .anw-nano-tuning__button {
    width: 100%;
  }
}

@media (forced-colors: active) {
  .anw-nano-tuning,
  .anw-nano-tuning__field input,
  .anw-nano-tuning__button {
    border-color: CanvasText;
  }
  .anw-nano-tuning__button:focus-visible,
  .anw-nano-tuning__field input:focus-visible {
    outline-color: Highlight;
  }
}
`;
