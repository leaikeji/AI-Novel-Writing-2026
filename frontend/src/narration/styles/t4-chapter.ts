export const T4_CHAPTER_NARRATION_STYLES = String.raw`
  .anw-editor-content.has-chapter-narration {
    --anw-chapter-player-height: 94px;
    position: relative;
  }

  .anw-editor-content.has-chapter-narration > .anw-editor-scroll {
    padding-bottom: calc(var(--anw-chapter-player-height) + 34px);
  }

  .anw-chapter-editor-surface {
    position: relative;
    min-width: 0;
    min-height: 560px;
    color: #26201c;
  }

  .anw-chapter-editor-surface .cm-editor {
    min-height: 560px;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
  }

  .anw-chapter-editor-surface .cm-scroller {
    overflow: visible;
    font: 17px/2.05 ui-serif, "Noto Serif SC", "Songti SC", serif;
  }

  .anw-chapter-editor-surface .cm-content {
    min-height: 560px;
    padding: 10px 0 120px;
    caret-color: #b95025;
  }

  .anw-chapter-editor-surface .cm-line {
    padding: 0 8px;
  }

  .anw-chapter-editor-surface .cm-focused {
    outline: none;
  }

  .anw-chapter-editor-surface .cm-gutters {
    border: 0;
    background: transparent;
    color: #9a8e84;
  }

  .anw-chapter-editor-surface .cm-activeLine,
  .anw-chapter-editor-surface .cm-activeLineGutter {
    background: color-mix(in srgb, #d76832 5%, transparent);
  }

  .anw-narration-current-segment {
    border-radius: 4px;
    background: color-mix(in srgb, #f1a45d 26%, transparent);
    box-shadow: inset 0 -2px 0 color-mix(in srgb, #c65628 55%, transparent);
  }

  .anw-chapter-editor-textarea-fallback {
    display: block;
    width: 100%;
    min-height: 560px;
    resize: none;
    border: 0;
    outline: 0;
    padding: 10px 8px 120px;
    background: transparent;
    color: inherit;
    font: 17px/2.05 ui-serif, "Noto Serif SC", "Songti SC", serif;
  }

  .anw-chapter-paragraph-gutter-button {
    display: inline-grid;
    width: 24px;
    height: 24px;
    place-items: center;
    border: 0;
    border-radius: 999px;
    padding: 0;
    background: transparent;
    color: #a94a26;
    cursor: pointer;
  }

  .anw-chapter-paragraph-gutter-button:hover:not(:disabled) {
    background: #fff0e7;
  }

  .anw-chapter-paragraph-gutter-button:focus-visible,
  .anw-chapter-narration-player button:focus-visible,
  .anw-chapter-narration-player select:focus-visible,
  .anw-chapter-narration-player input[type="range"]:focus-visible {
    outline: 3px solid color-mix(in srgb, #d76832 38%, transparent);
    outline-offset: 2px;
  }

  .anw-chapter-paragraph-gutter-button:disabled {
    color: #c4bbb4;
    cursor: not-allowed;
  }

  .anw-chapter-narration-player {
    position: sticky;
    z-index: 35;
    bottom: 14px;
    display: grid;
    width: min(1120px, calc(100% - 48px));
    min-height: var(--anw-chapter-player-height, 94px);
    grid-template-columns: minmax(190px, 0.9fr) auto minmax(260px, 1.35fr) auto;
    grid-template-rows: auto auto;
    align-items: center;
    gap: 6px 18px;
    margin: calc(-1 * var(--anw-chapter-player-height, 94px) - 20px) auto 14px;
    border: 1px solid color-mix(in srgb, #5f493c 18%, transparent);
    border-radius: 18px;
    padding: 12px 16px 10px;
    background: color-mix(in srgb, #fff 94%, #fff7f0);
    box-shadow: 0 18px 48px rgba(76, 49, 34, 0.18);
    backdrop-filter: blur(18px);
  }

  .anw-chapter-narration-player__identity {
    display: grid;
    min-width: 0;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 10px;
  }

  .anw-chapter-narration-source {
    display: inline-flex;
    min-height: 24px;
    align-items: center;
    border-radius: 999px;
    padding: 3px 9px;
    background: #eef8f2;
    color: #276746;
    font-size: 12px;
    font-weight: 700;
    white-space: nowrap;
  }

  .anw-chapter-narration-source.is-working-copy-diverged,
  .anw-chapter-narration-source.is-historical {
    background: #fff0e2;
    color: #a34a1e;
  }

  .anw-chapter-narration-current-copy {
    display: grid;
    min-width: 0;
  }

  .anw-chapter-narration-current-copy strong,
  .anw-chapter-narration-current-copy span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .anw-chapter-narration-current-copy strong {
    color: #4a3a31;
    font-size: 13px;
  }

  .anw-chapter-narration-current-copy span {
    color: #82766e;
    font-size: 12px;
  }

  .anw-chapter-narration-player__controls {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .anw-chapter-narration-icon-button,
  .anw-chapter-narration-play-button,
  .anw-chapter-narration-primary-action,
  .anw-chapter-narration-update,
  .anw-chapter-narration-link-button {
    border: 0;
    cursor: pointer;
  }

  .anw-chapter-narration-icon-button {
    width: 32px;
    height: 32px;
    border-radius: 999px;
    background: transparent;
    color: #5c4b41;
  }

  .anw-chapter-narration-play-button {
    width: 42px;
    height: 42px;
    border-radius: 999px;
    background: #d76832;
    color: #fff;
    font-size: 18px;
    box-shadow: 0 8px 18px rgba(215, 104, 50, 0.26);
  }

  .anw-chapter-narration-primary-action,
  .anw-chapter-narration-update {
    min-height: 36px;
    border-radius: 10px;
    padding: 7px 14px;
    background: #d76832;
    color: #fff;
    font-weight: 700;
  }

  .anw-chapter-narration-update:not(.is-required) {
    background: #f4eee9;
    color: #6f5547;
  }

  .anw-chapter-narration-player button:disabled,
  .anw-chapter-narration-player select:disabled,
  .anw-chapter-narration-player input:disabled {
    cursor: not-allowed;
    opacity: 0.48;
  }

  .anw-chapter-narration-player__timeline {
    display: grid;
    min-width: 0;
    grid-template-columns: minmax(180px, 1fr) auto;
    align-items: center;
    gap: 10px;
    color: #786a61;
    font-size: 12px;
  }

  .anw-chapter-narration-player__timeline input[type="range"] {
    width: 100%;
    accent-color: #d76832;
  }

  .anw-chapter-narration-player__actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
  }

  .anw-chapter-narration-select {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    color: #6d6058;
    font-size: 12px;
  }

  .anw-chapter-narration-select select {
    max-width: 154px;
    min-height: 32px;
    border: 1px solid #ded4cc;
    border-radius: 8px;
    background: #fff;
    color: #493c35;
  }

  .anw-chapter-narration-link-button {
    background: transparent;
    color: #a34824;
    font-size: 12px;
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .anw-chapter-narration-live {
    min-width: 0;
    grid-column: 1 / -1;
    overflow: hidden;
    color: #7c7068;
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .anw-chapter-narration-live.is-error {
    color: #b3261e;
  }

  .anw-script-review-shell {
    position: absolute;
    z-index: 48;
    inset: 58px 22px 116px auto;
    width: min(940px, calc(100% - 72px));
    overflow: auto;
    border: 1px solid color-mix(in srgb, #5f493c 20%, transparent);
    border-radius: 18px;
    background: #fffdfb;
    box-shadow: 0 22px 64px rgba(58, 38, 28, 0.22);
  }

  .anw-script-review {
    display: grid;
    min-height: 100%;
    grid-template-rows: auto auto auto auto minmax(0, 1fr) auto;
    color: #3f332d;
  }

  .anw-script-review__header,
  .anw-script-review__footer,
  .anw-script-review__snapshot,
  .anw-script-review__filters,
  .anw-script-review__snapshot-choice,
  .anw-script-review__error,
  .anw-script-review__global-issues {
    margin: 0;
    padding-inline: 22px;
  }

  .anw-script-review__header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
    border-bottom: 1px solid #eee5df;
    padding-block: 18px 14px;
  }

  .anw-script-review__header h2,
  .anw-script-review__header p {
    margin: 0;
  }

  .anw-script-review__eyebrow {
    color: #ad4c25;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.08em;
  }

  .anw-script-review__header h2 {
    margin-top: 4px;
    font-size: 21px;
  }

  .anw-script-review__header button,
  .anw-script-review__footer button,
  .anw-script-review__filters button,
  .anw-script-review__snapshot-choice button,
  .anw-script-review__segment-actions button,
  .anw-script-review__compact-player-actions button {
    min-height: 34px;
    border: 1px solid #ddcfc5;
    border-radius: 9px;
    padding: 6px 11px;
    background: #fff;
    color: #6d4431;
    cursor: pointer;
  }

  .anw-script-review button:focus-visible {
    outline: 3px solid color-mix(in srgb, #d76832 38%, transparent);
    outline-offset: 2px;
  }

  .anw-script-review button:disabled {
    cursor: not-allowed;
    opacity: 0.48;
  }

  .anw-script-review__compact-player {
    display: grid;
    grid-template-columns: minmax(240px, 1fr) minmax(180px, 0.75fr) auto;
    align-items: center;
    gap: 14px;
    border-bottom: 1px solid #eadfd7;
    padding: 12px 22px;
    background: #fff6ef;
  }

  .anw-script-review__compact-player-status {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
    color: #74665d;
    font-size: 12px;
  }

  .anw-script-review__compact-player progress {
    width: 100%;
    accent-color: #d76832;
  }

  .anw-script-review__compact-player-actions {
    display: flex;
    gap: 8px;
  }

  .anw-script-review__snapshot {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    padding-block: 12px;
    background: #faf6f2;
    color: #766960;
    font-size: 12px;
  }

  .anw-script-review__snapshot-choice,
  .anw-script-review__error {
    padding-block: 12px;
    background: #fff1e6;
  }

  .anw-script-review__error {
    color: #a82b22;
  }

  .anw-script-review__filters {
    display: flex;
    gap: 8px;
    padding-block: 12px;
  }

  .anw-script-review__filters button[aria-pressed="true"] {
    border-color: #d76832;
    background: #fff0e7;
    color: #a44320;
  }

  .anw-script-review__global-issues {
    display: grid;
    gap: 6px;
    list-style: none;
    padding-block: 10px;
  }

  .anw-script-review__workspace {
    display: grid;
    min-height: 0;
    grid-template-columns: minmax(0, 1fr) 240px;
    gap: 18px;
    padding: 0 22px 18px;
  }

  .anw-script-review__segments {
    display: grid;
    align-content: start;
    gap: 10px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .anw-script-review__segment {
    display: grid;
    gap: 8px;
    border: 1px solid #e9ded7;
    border-radius: 12px;
    padding: 13px 14px;
    background: #fff;
  }

  .anw-script-review__segment[data-severity="blocker"] {
    border-color: #e6a49b;
    box-shadow: inset 4px 0 0 #c13c30;
  }

  .anw-script-review__segment[data-severity="warning"] {
    box-shadow: inset 4px 0 0 #d88a35;
  }

  .anw-script-review__segment > div:first-child,
  .anw-script-review__segment-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 12px;
  }

  .anw-script-review__segment p,
  .anw-script-review__segment ul {
    margin: 0;
  }

  .anw-script-review__source-text {
    font: 15px/1.7 ui-serif, "Noto Serif SC", "Songti SC", serif;
  }

  .anw-script-review__spoken-text {
    color: #7e6c61;
    font-size: 13px;
  }

  .anw-script-review__guide {
    align-self: start;
    position: sticky;
    top: 12px;
    border-radius: 12px;
    padding: 14px;
    background: #f7f1ec;
    color: #6f625a;
    font-size: 13px;
  }

  .anw-script-review__guide h3 {
    margin: 0 0 8px;
  }

  .anw-script-review__footer {
    position: sticky;
    bottom: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    border-top: 1px solid #e8ddd6;
    padding-block: 12px;
    background: #fffdfb;
  }

  .anw-script-review__footer button:not(:disabled) {
    border-color: #d76832;
    background: #d76832;
    color: #fff;
  }

  .anw-narration-edition-confirm__copy {
    display: grid;
    gap: 8px;
    overflow-wrap: anywhere;
  }

  .anw-narration-edition-confirm__copy p {
    margin: 0;
  }
`;
