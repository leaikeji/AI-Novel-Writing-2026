/** Styles are injected by the narration integration owner; this module is side-effect free. */
export const OFFICIAL_VOICE_LIBRARY_STYLE_ID = "anw-official-voice-library-styles" as const;


export const OFFICIAL_VOICE_LIBRARY_STYLES = `
.anw-official-voice-library {
  display: grid;
  gap: 14px;
  min-width: 0;
  color: var(--ant-color-text, #24262b);
}
.anw-official-voice-library__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.anw-official-voice-library__header h2,
.anw-official-voice-library__header p,
.anw-official-voice-library__live-status,
.anw-official-voice-library__scope-error,
.anw-official-voice-library__empty {
  margin: 0;
}
.anw-official-voice-library__header > div:first-child > p:last-child {
  max-width: 660px;
  margin-top: 4px;
  color: var(--ant-color-text-secondary, #5f6670);
  line-height: 1.5;
}
.anw-official-voice-library__eyebrow {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  letter-spacing: .04em;
}
.anw-official-voice-library__header-actions {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}
.anw-official-voice-library__count {
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 999px;
  padding: 5px 9px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-quaternary, #fafafa);
  font-size: 12px;
}
.anw-official-voice-library__live-status,
.anw-official-voice-library__scope-error,
.anw-official-voice-library__empty {
  min-height: 40px;
  box-sizing: border-box;
  border-radius: 9px;
  padding: 9px 11px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-tertiary, #f5f5f6);
  line-height: 1.5;
}
.anw-official-voice-library__live-status:empty {
  display: none;
}
.anw-official-voice-library__live-status.is-error,
.anw-official-voice-library__scope-error,
.anw-official-voice-library__empty.is-error {
  color: var(--ant-color-error, #b42318);
  background: #fff2ed;
}
.anw-official-voice-library__refresh {
  justify-self: start;
}
.anw-official-voice-library__filters {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto auto;
  align-items: end;
  gap: 10px;
  min-width: 0;
}
.anw-official-voice-library__filters label {
  display: grid;
  gap: 5px;
  min-width: 0;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
}
.anw-official-voice-library__filters input[type="search"] {
  width: 100%;
  min-width: 0;
  min-height: 44px;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 9px;
  padding: 9px 11px;
  color: var(--ant-color-text, #24262b);
  background: var(--ant-color-bg-container, #fff);
  font: inherit;
  font-size: 14px;
}
.anw-official-voice-library__language-tabs {
  display: inline-grid;
  grid-template-columns: repeat(3, max-content);
  gap: 3px;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 10px;
  padding: 3px;
  background: var(--ant-color-fill-quaternary, #fafafa);
}
.anw-official-voice-library__language-tabs button {
  min-height: 44px;
  border: 0;
  border-radius: 7px;
  padding: 7px 10px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: transparent;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.anw-official-voice-library__language-tabs button.is-active {
  color: var(--ant-color-primary-text, #8c2d12);
  background: var(--ant-color-bg-container, #fff);
  box-shadow: 0 1px 4px rgba(27, 31, 36, .1);
  font-weight: 700;
}
.anw-official-voice-library__filter-count {
  min-height: 44px;
  box-sizing: border-box;
  border-radius: 9px;
  padding: 11px 10px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-quaternary, #fafafa);
  font-size: 12px;
  white-space: nowrap;
}
.anw-official-voice-library__filter-status {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  border: 0;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}
.anw-official-voice-library__grid {
  display: grid;
  min-width: 0;
  margin: 0;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 12px;
  padding: 0;
  overflow: hidden;
  background: var(--ant-color-bg-container, #fff);
  list-style: none;
}
.anw-official-voice-library__item {
  min-width: 0;
}
.anw-official-voice-library__item + .anw-official-voice-library__item {
  border-top: 1px solid var(--ant-color-border-secondary, #e5e6e8);
}
.anw-official-voice-card {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(76px, auto) minmax(76px, auto);
  align-items: center;
  gap: 12px;
  min-width: 0;
  box-sizing: border-box;
  padding: 12px 14px;
  background: var(--ant-color-bg-container, #fff);
}
.anw-official-voice-card.is-current {
  background: color-mix(in srgb, var(--ant-color-primary-bg, #fff1eb) 56%, white);
  box-shadow: inset 3px 0 0 var(--ant-color-primary, #d95d36);
}
.anw-official-voice-card.is-unavailable {
  background: var(--ant-color-fill-quaternary, #fafafa);
}
.anw-official-voice-card__selection {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  min-width: 0;
  min-height: 44px;
  box-sizing: border-box;
  border: 1px solid transparent;
  border-radius: 9px;
  padding: 4px 6px;
  cursor: pointer;
}
.anw-official-voice-card__selection.is-disabled {
  cursor: default;
}
.anw-official-voice-card__selection:has(.anw-official-voice-card__radio:focus-visible) {
  border-color: color-mix(in srgb, var(--ant-color-primary, #d95d36) 48%, transparent);
  outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #d95d36) 28%, transparent);
  outline-offset: 1px;
}
.anw-official-voice-card__radio {
  width: 18px;
  height: 18px;
  margin: 0;
  accent-color: var(--ant-color-primary, #d95d36);
  cursor: pointer;
}
.anw-official-voice-card__radio:disabled {
  cursor: default;
}
.anw-official-voice-card__heading {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}
.anw-official-voice-card__heading > span:first-child {
  display: grid;
  min-width: 0;
}
.anw-official-voice-card__heading strong,
.anw-official-voice-card__group {
  margin: 0;
}
.anw-official-voice-card__heading strong {
  overflow-wrap: anywhere;
  font-size: 14px;
  line-height: 1.4;
}
.anw-official-voice-card__group {
  margin-top: 2px;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.anw-official-voice-card__current {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 3px 7px;
  color: var(--ant-color-primary-text, #8c2d12);
  background: var(--ant-color-primary-bg, #fff1eb);
  font-size: 11px;
}
.anw-official-voice-card button,
.anw-official-voice-library__refresh,
.anw-official-voice-card__details summary {
  min-width: 44px;
  min-height: 44px;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 8px;
  padding: 8px 11px;
  color: inherit;
  background: var(--ant-color-bg-container, #fff);
  font: inherit;
  font-size: 13px;
  line-height: 1.35;
  cursor: pointer;
}
.anw-official-voice-card button:disabled {
  cursor: not-allowed;
  opacity: .58;
}
.anw-official-voice-card__details {
  min-width: 76px;
}
.anw-official-voice-card__details summary {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  list-style: none;
}
.anw-official-voice-card__details summary::-webkit-details-marker {
  display: none;
}
.anw-official-voice-card__details summary::after {
  content: "⌄";
  margin-left: 6px;
  color: var(--ant-color-text-secondary, #5f6670);
}
.anw-official-voice-card__details[open] {
  grid-column: 1 / -1;
  width: 100%;
}
.anw-official-voice-card__details[open] summary {
  width: max-content;
}
.anw-official-voice-card__details[open] summary::after {
  transform: rotate(180deg);
}
.anw-official-voice-card__details dl {
  display: grid;
  gap: 6px;
  min-width: 0;
  margin: 9px 0 0;
}
.anw-official-voice-card__details dl > div {
  display: grid;
  grid-template-columns: minmax(92px, max-content) minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
  border-radius: 7px;
  padding: 7px 8px;
  background: var(--ant-color-fill-quaternary, #fafafa);
}
.anw-official-voice-card__details dt {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 11px;
}
.anw-official-voice-card__details dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-size: 12px;
}
.anw-official-voice-card__language-note {
  border-left: 3px solid #d8ad45;
}
.anw-official-voice-card button:focus-visible,
.anw-official-voice-card__radio:focus-visible,
.anw-official-voice-library__refresh:focus-visible,
.anw-official-voice-library__filters input:focus-visible,
.anw-official-voice-library__language-tabs button:focus-visible,
.anw-official-voice-card__details summary:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #d95d36) 42%, transparent);
  outline-offset: 2px;
}
@media (max-width: 860px) {
  .anw-official-voice-library__filters {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
  }
  .anw-official-voice-library__language-tabs {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (max-width: 680px) {
  .anw-official-voice-library__header {
    display: grid;
  }
  .anw-official-voice-library__header-actions {
    justify-content: flex-start;
  }
  .anw-official-voice-card {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
    padding: 12px;
  }
  .anw-official-voice-card__selection {
    grid-column: 1 / -1;
  }
  .anw-official-voice-card__preview,
  .anw-official-voice-card__details {
    width: 100%;
  }
  .anw-official-voice-card__details[open] {
    grid-column: 1 / -1;
    grid-row: auto;
  }
  .anw-official-voice-card__details summary,
  .anw-official-voice-card__details[open] summary {
    width: 100%;
  }
}
@media (max-width: 390px) {
  .anw-official-voice-library__language-tabs button {
    padding-inline: 5px;
    font-size: 11px;
  }
  .anw-official-voice-card__details dl > div {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (prefers-reduced-motion: reduce) {
  .anw-official-voice-card,
  .anw-official-voice-card button,
  .anw-official-voice-library__refresh,
  .anw-official-voice-library__language-tabs button,
  .anw-official-voice-card__details summary {
    scroll-behavior: auto;
    transition: none;
  }
}
@media (forced-colors: active) {
  .anw-official-voice-card.is-current,
  .anw-official-voice-card__radio,
  .anw-official-voice-card__language-note {
    border-color: CanvasText;
  }
}
`;
