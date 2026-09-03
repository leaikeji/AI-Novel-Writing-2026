/** Styles are injected by the narration integration owner; this module is side-effect free. */
export const VOICE_PREPARATION_STYLE_ID = "anw-voice-preparation-styles" as const;

export const VOICE_PREPARATION_STYLES = String.raw`
.anw-voice-preparation {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px 16px;
  min-width: 0;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 12px;
  padding: 14px 16px;
  color: var(--ant-color-text, #24262b);
  background: var(--ant-color-bg-container, #fff);
}
.anw-voice-preparation.is-progress {
  border-color: color-mix(in srgb, var(--ant-color-primary, #d95d36) 34%, transparent);
  background: color-mix(in srgb, var(--ant-color-primary-bg, #fff2e8) 36%, white);
}
.anw-voice-preparation.is-success {
  border-color: color-mix(in srgb, var(--ant-color-success, #52c41a) 40%, transparent);
}
.anw-voice-preparation.is-warning {
  border-color: color-mix(in srgb, var(--ant-color-warning, #faad14) 46%, transparent);
}
.anw-voice-preparation.is-danger {
  border-color: color-mix(in srgb, var(--ant-color-error, #ff4d4f) 42%, transparent);
}
.anw-voice-preparation__copy {
  min-width: 0;
}
.anw-voice-preparation__copy strong,
.anw-voice-preparation__copy p,
.anw-voice-preparation__error {
  margin: 0;
  overflow-wrap: anywhere;
}
.anw-voice-preparation__copy strong {
  display: block;
  font-size: 14px;
  line-height: 1.5;
}
.anw-voice-preparation__copy p,
.anw-voice-preparation__error {
  margin-top: 3px;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  line-height: 1.55;
}
.anw-voice-preparation__error {
  grid-column: 1 / -1;
  color: var(--ant-color-error, #b42318);
}
.anw-voice-preparation__progress {
  display: grid;
  grid-column: 1;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.anw-voice-preparation__progress progress {
  width: 100%;
  height: 7px;
  accent-color: var(--ant-color-primary, #d95d36);
}
.anw-voice-preparation__action {
  grid-column: 2;
  grid-row: 1 / span 2;
  min-height: 40px;
  box-sizing: border-box;
  border: 1px solid #d76832;
  border-radius: 9px;
  padding: 8px 14px;
  color: #fff;
  background: #d95d36;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}
.anw-voice-preparation__action.is-secondary {
  border-color: var(--ant-color-border, #d9dadd);
  color: var(--ant-color-text, #24262b);
  background: var(--ant-color-bg-container, #fff);
}
.anw-voice-preparation__action:disabled {
  cursor: not-allowed;
  opacity: .58;
}
.anw-voice-preparation__action:focus-visible,
.anw-voice-preparation__details summary:focus-visible,
.anw-generic-voice-pack summary:focus-visible,
.anw-generic-voice-pack button:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #d95d36) 42%, transparent);
  outline-offset: 2px;
}
.anw-voice-preparation__details {
  grid-column: 1 / -1;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
}
.anw-voice-preparation__details summary,
.anw-generic-voice-pack summary {
  cursor: pointer;
}
.anw-voice-preparation__details dl {
  display: grid;
  gap: 4px;
  margin: 8px 0 0;
}
.anw-voice-preparation__details dl > div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 8px;
}
.anw-voice-preparation__details dt,
.anw-voice-preparation__details dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.anw-voice-preparation.is-player-inline {
  grid-template-columns: minmax(0, 1fr) auto;
  border-radius: 10px;
  padding: 10px 12px;
}

.anw-generic-voice-pack {
  min-width: 0;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 12px;
  color: var(--ant-color-text, #24262b);
  background: var(--ant-color-bg-container, #fff);
  overflow: clip;
}
.anw-generic-voice-pack__summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 62px;
  box-sizing: border-box;
  padding: 12px 16px;
  list-style-position: outside;
}
.anw-generic-voice-pack__summary > span:first-child {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.anw-generic-voice-pack__summary strong,
.anw-generic-voice-pack__summary small {
  overflow-wrap: anywhere;
}
.anw-generic-voice-pack__summary small {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  line-height: 1.45;
}
.anw-generic-voice-pack__count {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-tertiary, #f5f5f6);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.anw-generic-voice-pack__body {
  display: grid;
  gap: 14px;
  border-top: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  padding: 14px 16px 16px;
}
.anw-generic-voice-pack__progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.anw-generic-voice-pack__progress progress {
  width: 100%;
  height: 7px;
  accent-color: var(--ant-color-primary, #d95d36);
}
.anw-generic-voice-pack__notice,
.anw-generic-voice-pack__error {
  margin: 0;
  border-radius: 9px;
  padding: 9px 11px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-tertiary, #f5f5f6);
  font-size: 12px;
  line-height: 1.5;
}
.anw-generic-voice-pack__error {
  color: var(--ant-color-error, #b42318);
  background: var(--ant-color-error-bg, #fff2ed);
}
.anw-generic-voice-pack__primary,
.anw-generic-voice-pack__secondary,
.anw-generic-voice-pack__slot-actions button {
  min-height: 36px;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 8px;
  padding: 7px 11px;
  color: var(--ant-color-text, #24262b);
  background: var(--ant-color-bg-container, #fff);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.anw-generic-voice-pack__primary {
  justify-self: end;
  border-color: #d76832;
  color: #fff;
  background: #d95d36;
  font-weight: 650;
}
.anw-generic-voice-pack button:disabled {
  cursor: not-allowed;
  opacity: .58;
}
.anw-generic-voice-pack__group {
  display: grid;
  gap: 7px;
}
.anw-generic-voice-pack__group h4 {
  margin: 0;
  font-size: 13px;
}
.anw-generic-voice-pack__group ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.anw-generic-voice-pack__group li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px 12px;
  min-width: 0;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 9px;
  padding: 8px 10px;
}
.anw-generic-voice-pack__slot-copy {
  display: grid;
  min-width: 0;
}
.anw-generic-voice-pack__slot-copy strong,
.anw-generic-voice-pack__slot-copy small {
  overflow-wrap: anywhere;
}
.anw-generic-voice-pack__slot-copy small {
  color: var(--ant-color-text-secondary, #5f6670);
}
.anw-generic-voice-pack__slot-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}
.anw-generic-voice-pack__slot-actions button.is-danger {
  color: var(--ant-color-error, #b42318);
}
.anw-generic-voice-pack__slot-failure {
  grid-column: 1 / -1;
  color: var(--ant-color-error, #b42318);
  overflow-wrap: anywhere;
}
.anw-generic-voice-pack__technical {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
}
.anw-generic-voice-pack__technical code {
  display: block;
  margin-top: 6px;
  overflow-wrap: anywhere;
}

@media (max-width: 720px) {
  .anw-voice-preparation,
  .anw-voice-preparation.is-player-inline {
    grid-template-columns: minmax(0, 1fr);
  }
  .anw-voice-preparation__action {
    grid-column: 1;
    grid-row: auto;
    width: 100%;
  }
  .anw-generic-voice-pack__summary,
  .anw-generic-voice-pack__group li {
    align-items: stretch;
  }
  .anw-generic-voice-pack__group li {
    grid-template-columns: minmax(0, 1fr);
  }
  .anw-generic-voice-pack__slot-actions {
    justify-content: stretch;
  }
  .anw-generic-voice-pack__slot-actions button {
    flex: 1 1 auto;
  }
}

@media (forced-colors: active) {
  .anw-voice-preparation,
  .anw-generic-voice-pack,
  .anw-generic-voice-pack__group li,
  .anw-voice-preparation__action,
  .anw-generic-voice-pack button {
    border-color: CanvasText;
  }
}
`;
