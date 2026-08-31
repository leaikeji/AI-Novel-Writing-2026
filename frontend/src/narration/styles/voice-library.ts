/** Styles are injected by the narration integration owner; this module is side-effect free. */
export const OFFICIAL_VOICE_LIBRARY_STYLE_ID = "anw-official-voice-library-styles" as const;


export const OFFICIAL_VOICE_LIBRARY_STYLES = `
.anw-official-voice-library {
  display: grid;
  gap: 18px;
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
.anw-official-voice-library__group h3,
.anw-official-voice-library__live-status,
.anw-official-voice-library__scope-error,
.anw-official-voice-library__empty {
  margin: 0;
}
.anw-official-voice-library__header > div > p:last-child {
  max-width: 760px;
  margin-top: 5px;
  color: var(--ant-color-text-secondary, #5f6670);
  line-height: 1.55;
}
.anw-official-voice-library__eyebrow {
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  letter-spacing: .04em;
}
.anw-official-voice-library__count {
  flex: 0 0 auto;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 999px;
  padding: 6px 10px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-quaternary, #fafafa);
  font-size: 12px;
}
.anw-official-voice-library__live-status,
.anw-official-voice-library__scope-error,
.anw-official-voice-library__empty {
  min-height: 44px;
  box-sizing: border-box;
  border-radius: 10px;
  padding: 11px 13px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-tertiary, #f5f5f6);
  line-height: 1.5;
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
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 12px;
  min-width: 0;
}
.anw-official-voice-library__filters label {
  display: grid;
  flex: 1 1 220px;
  gap: 6px;
  min-width: 0;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
}
.anw-official-voice-library__filters input,
.anw-official-voice-library__filters select {
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
.anw-official-voice-library__filter-count {
  flex: 0 1 auto;
  align-self: end;
  min-height: 44px;
  box-sizing: border-box;
  border-radius: 9px;
  padding: 11px 12px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-quaternary, #fafafa);
  font-size: 12px;
  white-space: nowrap;
}
.anw-official-voice-library__group {
  display: grid;
  gap: 11px;
  min-width: 0;
}
.anw-official-voice-library__group h3 {
  font-size: 15px;
  line-height: 1.45;
}
.anw-official-voice-library__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
  gap: 12px;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.anw-official-voice-library__item {
  min-width: 0;
}
.anw-official-voice-card {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr) auto auto;
  gap: 11px;
  min-width: 0;
  height: 100%;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 14px;
  padding: 14px;
  background: var(--ant-color-bg-container, #fff);
}
.anw-official-voice-card.is-current {
  border-color: var(--ant-color-primary, #d95d36);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--ant-color-primary, #d95d36) 16%, transparent);
}
.anw-official-voice-card.is-unavailable {
  border-style: dashed;
}
.anw-official-voice-card__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}
.anw-official-voice-card__heading > div {
  min-width: 0;
}
.anw-official-voice-card__heading h4,
.anw-official-voice-card__group,
.anw-official-voice-card__language-note {
  margin: 0;
}
.anw-official-voice-card__heading h4 {
  overflow-wrap: anywhere;
  font-size: 16px;
  line-height: 1.4;
}
.anw-official-voice-card__group {
  margin-top: 3px;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.anw-official-voice-card__current {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--ant-color-primary-text, #8c2d12);
  background: var(--ant-color-primary-bg, #fff1eb);
  font-size: 12px;
}
.anw-official-voice-card__badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.anw-official-voice-card__badge {
  border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
  border-radius: 999px;
  padding: 3px 7px;
  color: var(--ant-color-text-secondary, #5f6670);
  background: var(--ant-color-fill-quaternary, #fafafa);
  font-size: 11px;
  line-height: 1.35;
}
.anw-official-voice-card__badge.is-verified,
.anw-official-voice-card__badge.is-available {
  border-color: #a8d5b2;
  color: var(--ant-color-success, #176b32);
  background: #f0faf2;
}
.anw-official-voice-card__badge.is-unreviewed {
  border-color: #e4d4a1;
  color: #765d10;
  background: #fff9e8;
}
.anw-official-voice-card__badge.is-unavailable {
  border-color: #dfb5aa;
  color: var(--ant-color-error, #b42318);
  background: #fff2ed;
}
.anw-official-voice-card__language-note {
  border-left: 3px solid #d8ad45;
  padding-left: 9px;
  color: var(--ant-color-text-secondary, #5f6670);
  font-size: 12px;
  line-height: 1.5;
}
.anw-official-voice-card__actions {
  display: grid;
  grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr);
  gap: 8px;
  align-self: end;
}
.anw-official-voice-card button,
.anw-official-voice-library__refresh,
.anw-official-voice-card__details summary {
  min-width: 44px;
  min-height: 44px;
  box-sizing: border-box;
  border: 1px solid var(--ant-color-border, #d9dadd);
  border-radius: 9px;
  padding: 9px 11px;
  color: inherit;
  background: var(--ant-color-bg-container, #fff);
  font: inherit;
  line-height: 1.35;
}
.anw-official-voice-card button,
.anw-official-voice-library__refresh,
.anw-official-voice-card__details summary {
  cursor: pointer;
}
.anw-official-voice-card__use {
  border-color: var(--ant-color-primary, #d95d36);
  color: var(--ant-color-primary-text, #8c2d12);
  background: var(--ant-color-primary-bg, #fff1eb);
  font-weight: 650;
}
.anw-official-voice-card button:disabled {
  cursor: not-allowed;
  opacity: .62;
}
.anw-official-voice-card button:focus-visible,
.anw-official-voice-library__refresh:focus-visible,
.anw-official-voice-library__filters input:focus-visible,
.anw-official-voice-library__filters select:focus-visible,
.anw-official-voice-card__details summary:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--ant-color-primary, #d95d36) 42%, transparent);
  outline-offset: 2px;
}
.anw-official-voice-card__details {
  min-width: 0;
}
.anw-official-voice-card__details summary {
  display: flex;
  align-items: center;
  width: 100%;
}
.anw-official-voice-card__details dl {
  display: grid;
  gap: 7px;
  min-width: 0;
  margin: 9px 0 0;
}
.anw-official-voice-card__details dl > div {
  display: grid;
  grid-template-columns: minmax(92px, max-content) minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
  border-radius: 8px;
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
@media (max-width: 680px) {
  .anw-official-voice-library__header {
    display: grid;
  }
  .anw-official-voice-library__count {
    justify-self: start;
  }
  .anw-official-voice-library__filters label,
  .anw-official-voice-library__filter-count {
    flex-basis: 100%;
  }
  .anw-official-voice-library__filter-count {
    justify-self: stretch;
  }
  .anw-official-voice-library__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 390px) {
  .anw-official-voice-card__actions,
  .anw-official-voice-card__details dl > div {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (prefers-reduced-motion: reduce) {
  .anw-official-voice-card,
  .anw-official-voice-card button,
  .anw-official-voice-library__refresh,
  .anw-official-voice-card__details summary {
    scroll-behavior: auto;
    transition: none;
  }
}
@media (forced-colors: active) {
  .anw-official-voice-card.is-current,
  .anw-official-voice-card__badge,
  .anw-official-voice-card__language-note {
    border-color: CanvasText;
  }
}
`;
