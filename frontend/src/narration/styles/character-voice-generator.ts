export const CHARACTER_VOICE_GENERATOR_STYLE_ID = "anw-character-voice-generator-styles";

export const CHARACTER_VOICE_GENERATOR_STYLES = String.raw`
.anw-character-voice-generator {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px 18px;
  padding: 17px 18px;
  border: 1px solid color-mix(in srgb, #d76832 34%, transparent);
  border-radius: 14px;
  background: linear-gradient(135deg, #fff8f3, #fffdfb);
  color: var(--ant-color-text, #111827);
}

.anw-character-voice-generator.is-progress {
  border-color: color-mix(in srgb, var(--ant-color-primary, #1677ff) 38%, transparent);
  background: color-mix(in srgb, var(--ant-color-primary-bg, #e6f4ff) 42%, white);
}

.anw-character-voice-generator.is-warning {
  border-color: color-mix(in srgb, var(--ant-color-warning, #faad14) 50%, transparent);
}

.anw-character-voice-generator.is-danger {
  border-color: color-mix(in srgb, var(--ant-color-error, #ff4d4f) 45%, transparent);
}

.anw-character-voice-generator.is-success {
  border-color: color-mix(in srgb, var(--ant-color-success, #52c41a) 45%, transparent);
}

.anw-character-voice-generator__heading {
  display: flex;
  grid-column: 1 / -1;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.anw-character-voice-generator__heading h3,
.anw-character-voice-generator__heading p,
.anw-character-voice-generator__status,
.anw-character-voice-generator__detail,
.anw-character-voice-generator__error {
  margin: 0;
}

.anw-character-voice-generator__eyebrow {
  color: var(--ant-color-text-secondary, #6b7280);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.anw-character-voice-generator__heading h3 {
  margin-top: 3px;
  font-size: 16px;
  line-height: 1.45;
}

.anw-character-voice-generator__terminal {
  flex: 0 0 auto;
  padding: 3px 8px;
  border-radius: 999px;
  background: var(--ant-color-fill-tertiary, #f3f4f6);
  color: var(--ant-color-text-secondary, #6b7280);
  font-size: 12px;
}

.anw-character-voice-generator__status {
  grid-column: 1;
  font-weight: 650;
  line-height: 1.55;
}

.anw-character-voice-generator__detail,
.anw-character-voice-generator__error {
  grid-column: 1;
  color: var(--ant-color-text-secondary, #6b7280);
  font-size: 13px;
  line-height: 1.6;
}

.anw-character-voice-generator__error {
  color: var(--ant-color-error, #d9363e);
}

.anw-character-voice-generator__progress {
  display: grid;
  grid-column: 1;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  color: var(--ant-color-text-secondary, #6b7280);
  font-variant-numeric: tabular-nums;
}

.anw-character-voice-generator__progress progress {
  width: 100%;
  height: 8px;
  accent-color: var(--ant-color-primary, #1677ff);
}

.anw-character-voice-generator__primary {
  min-height: 44px;
  grid-column: 2;
  grid-row: 2 / span 2;
  align-self: center;
  justify-self: end;
  padding: 9px 16px;
  border: 1px solid #d76832;
  border-radius: 9px;
  background: linear-gradient(135deg, #e26f3d, #cf5328);
  color: #fff;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}

.anw-character-voice-generator__primary:hover:not(:disabled) {
  filter: brightness(0.96);
}

.anw-character-voice-generator__primary:focus-visible {
  outline: 3px solid color-mix(in srgb, #d76832 34%, transparent);
  outline-offset: 2px;
}

.anw-character-voice-generator__primary.is-cancel {
  border-color: var(--ant-color-border, #d1d5db);
  background: var(--ant-color-bg-container, #fff);
  color: var(--ant-color-text, #111827);
}

.anw-character-voice-generator__primary:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

@media (max-width: 640px) {
  .anw-character-voice-generator {
    grid-template-columns: minmax(0, 1fr);
    padding: 14px;
  }

  .anw-character-voice-generator__heading {
    display: grid;
  }

  .anw-character-voice-generator__terminal {
    justify-self: start;
  }

  .anw-character-voice-generator__primary {
    grid-column: 1;
    grid-row: auto;
    width: 100%;
    justify-self: stretch;
  }
}
`;
