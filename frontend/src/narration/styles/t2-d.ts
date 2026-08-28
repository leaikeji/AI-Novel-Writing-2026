/** Local T2-D styles. T2-GATE is the only owner allowed to inject these. */
export const T2_D_NARRATION_STYLE_ID = "anw-narration-t2-d-styles" as const;

export const T2_D_NARRATION_STYLES = `
.anw-narration-voice-source-panel {
  display: grid;
  gap: 16px;
  min-width: 0;
  color: var(--ant-color-text, #24262b);
}
.anw-narration-voice-source-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.anw-narration-voice-source-heading h2,
.anw-narration-voice-source-heading p { margin: 0; }
.anw-narration-voice-source-heading p {
  margin-top: 4px;
  color: var(--ant-color-text-secondary, #727780);
  font-size: 13px;
}
.anw-narration-voice-source-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.anw-narration-voice-source-card {
  display: grid;
  align-content: start;
  gap: 8px;
  min-width: 0;
  min-height: 148px;
  padding: 14px;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 12px;
  background: var(--ant-color-bg-container, #fff);
}
.anw-narration-voice-source-card.is-selected {
  border-color: var(--ant-color-primary, #ff7548);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--ant-color-primary, #ff7548) 16%, transparent);
}
.anw-narration-voice-source-card.is-disabled { opacity: .72; }
.anw-narration-voice-source-card h3,
.anw-narration-voice-source-card p { margin: 0; }
.anw-narration-voice-source-card p {
  color: var(--ant-color-text-secondary, #727780);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.anw-narration-voice-source-card button,
.anw-narration-voice-rights button,
.anw-narration-voice-actions button {
  min-width: 44px;
  min-height: 44px;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 9px;
  color: inherit;
  background: var(--ant-color-bg-container, #fff);
  cursor: pointer;
}
.anw-narration-voice-source-card button:focus-visible,
.anw-narration-voice-rights button:focus-visible,
.anw-narration-voice-actions button:focus-visible,
.anw-narration-voice-rights input:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #ff7548) 38%, transparent);
  outline-offset: 2px;
}
.anw-narration-voice-source-card button:disabled,
.anw-narration-voice-rights button:disabled,
.anw-narration-voice-actions button:disabled {
  cursor: not-allowed;
  opacity: .62;
}
.anw-narration-voice-rights {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 14px;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 12px;
}
.anw-narration-voice-rights label {
  display: grid;
  gap: 6px;
  line-height: 1.45;
}
.anw-narration-voice-rights label.anw-narration-voice-rights-check,
.anw-narration-voice-quality-confirmation {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  line-height: 1.45;
}
.anw-narration-voice-rights input[type="text"],
.anw-voice-workspace input[type="text"],
.anw-voice-workspace select,
.anw-voice-workspace textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 42px;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 9px;
  padding: 9px 10px;
  color: inherit;
  background: var(--ant-color-bg-container, #fff);
}
.anw-narration-voice-rights input[type="checkbox"] {
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
}
.anw-narration-voice-rights input[type="file"] { max-width: 100%; }
.anw-narration-voice-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.anw-narration-voice-quality-confirmation {
  max-width: 520px;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 9px;
  padding: 10px 12px;
  background: var(--ant-color-fill-quaternary, #fafafa);
}
.anw-narration-voice-quality-confirmation input {
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
}
.anw-narration-voice-status {
  min-height: 44px;
  padding: 10px 12px;
  border-radius: 9px;
  color: var(--ant-color-text-secondary, #727780);
  background: var(--ant-color-fill-tertiary, #f5f5f6);
}
.anw-narration-voice-status.is-error { color: var(--ant-color-error, #d4380d); }
.anw-narration-voice-status.is-ready { color: var(--ant-color-success, #237804); }
.anw-voice-workspace {
  display: grid;
  gap: 18px;
  min-width: 0;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 16px;
  padding: 18px;
  color: var(--ant-color-text, #24262b);
  background: var(--ant-color-bg-container, #fff);
}
.anw-voice-workspace__header,
.anw-voice-workspace__section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.anw-voice-workspace__header h2,
.anw-voice-workspace__header p,
.anw-voice-workspace__section-heading h3,
.anw-voice-workspace__section-heading p,
.anw-voice-workspace__preview-playback p {
  margin: 0;
}
.anw-voice-workspace__header > div > p:last-child,
.anw-voice-workspace__section-heading p {
  margin-top: 5px;
  color: var(--ant-color-text-secondary, #727780);
  font-size: 13px;
}
.anw-voice-workspace__eyebrow,
.anw-voice-workspace__scope {
  color: var(--ant-color-text-secondary, #727780);
  font-size: 12px;
}
.anw-voice-workspace__scope {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 6px 10px;
  background: var(--ant-color-fill-tertiary, #f5f5f6);
}
.anw-voice-workspace__status,
.anw-voice-workspace__error,
.anw-voice-workspace__empty,
.anw-voice-workspace__loading {
  margin: 0;
  border-radius: 10px;
  padding: 11px 13px;
  color: var(--ant-color-text-secondary, #727780);
  background: var(--ant-color-fill-tertiary, #f5f5f6);
}
.anw-voice-workspace__status.is-error,
.anw-voice-workspace__error {
  color: var(--ant-color-error, #d4380d);
  background: #fff2ed;
}
.anw-voice-workspace__error {
  display: grid;
  justify-items: start;
  gap: 8px;
}
.anw-voice-workspace__profiles,
.anw-voice-workspace__source,
.anw-voice-workspace__preset-catalog,
.anw-voice-workspace__preview {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 13px;
  min-width: 0;
  border-top: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  padding-top: 16px;
}
.anw-voice-workspace__preset-catalog > button {
  justify-self: start;
}
.anw-voice-workspace__preset-evidence {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
  margin: 0;
}
.anw-voice-workspace__preset-evidence > div {
  display: grid;
  grid-template-columns: minmax(116px, max-content) minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
  border-radius: 9px;
  padding: 9px 10px;
  background: var(--ant-color-fill-quaternary, #fafafa);
}
.anw-voice-workspace__preset-evidence dt {
  color: var(--ant-color-text-secondary, #727780);
  font-size: 12px;
}
.anw-voice-workspace__preset-evidence dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 13px;
}
.anw-voice-workspace__create-row,
.anw-voice-workspace__preview-grid {
  display: grid;
  grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr);
  width: 100%;
  min-width: 0;
  align-items: end;
  gap: 12px;
}
.anw-voice-workspace__create-row {
  grid-template-columns: minmax(0, 1fr) max-content;
}
.anw-voice-workspace__field {
  display: grid;
  gap: 6px;
  min-width: 0;
}
.anw-voice-workspace__field > input,
.anw-voice-workspace__field > select,
.anw-voice-workspace__field > textarea {
  min-width: 0;
  max-width: 100%;
}
.anw-voice-workspace__field > span {
  font-size: 13px;
  font-weight: 650;
}
.anw-voice-workspace__language { max-width: 360px; }
.anw-voice-workspace textarea {
  min-height: 92px;
  resize: vertical;
}
.anw-voice-workspace button,
.anw-voice-workspace__continue {
  min-height: 42px;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 9px;
  padding: 8px 13px;
  color: inherit;
  background: var(--ant-color-bg-container, #fff);
  cursor: pointer;
}
.anw-voice-workspace button:disabled {
  cursor: not-allowed;
  opacity: .62;
}
.anw-voice-workspace button:focus-visible,
.anw-voice-workspace input:focus-visible,
.anw-voice-workspace select:focus-visible,
.anw-voice-workspace textarea:focus-visible,
.anw-narration-voice-preview-playback audio:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #ff7548) 38%, transparent);
  outline-offset: 2px;
}
.anw-narration-voice-preview-playback {
  display: grid;
  gap: 8px;
  min-width: 0;
  border-radius: 10px;
  padding: 12px;
  background: var(--ant-color-fill-quaternary, #fafafa);
}
.anw-narration-voice-preview-playback audio { width: 100%; }
.anw-narration-voice-preview-playback p {
  margin: 0;
  color: var(--ant-color-text-secondary, #727780);
  font-size: 12px;
}
@media (prefers-reduced-motion: reduce) {
  .anw-narration-voice-source-card,
  .anw-narration-voice-source-card button,
  .anw-narration-voice-rights button,
  .anw-narration-voice-actions button,
  .anw-voice-workspace button { scroll-behavior: auto; transition: none; }
}
`;
