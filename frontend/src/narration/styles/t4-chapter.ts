export const T4_CHAPTER_NARRATION_STYLES = String.raw`
  .anw-editor-content.has-chapter-narration {
    position: relative;
    display: flex;
    min-height: 0;
    flex-direction: column;
    overflow: hidden;
  }

  .anw-editor-content.has-chapter-narration > .anw-editor-scroll {
    min-height: 0;
    flex: 1 1 auto;
    overflow: auto;
    padding-bottom: 34px;
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
    --anw-chapter-editor-scrollbar-width: 0px;
    position: relative;
    z-index: 35;
    display: grid;
    width: min(
      1440px,
      calc(100% - 48px - var(--anw-chapter-editor-scrollbar-width))
    );
    min-width: 0;
    flex: 0 0 auto;
    gap: 7px;
    margin: 0 0 0 max(
      24px,
      calc((100% - var(--anw-chapter-editor-scrollbar-width) - 1440px) / 2)
    );
    border: 1px solid #e7ddd7;
    border-bottom: 0;
    border-radius: 14px 14px 0 0;
    padding: 8px 12px 9px;
    overflow: visible;
    background: #fffdfb;
    box-shadow: 0 -8px 24px rgba(75, 51, 39, 0.09);
    color: #403630;
    container-type: inline-size;
  }

  .anw-chapter-narration-player__compact {
    display: grid;
    min-width: 0;
    min-height: 56px;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    align-items: center;
    gap: 14px;
  }

  .anw-chapter-narration-player__identity,
  .anw-chapter-narration-player__controls,
  .anw-chapter-narration-player__tools,
  .anw-chapter-narration-player__actions {
    display: flex;
    min-width: 0;
    align-items: center;
  }

  .anw-chapter-narration-player__identity {
    justify-self: start;
    gap: 8px;
    overflow: hidden;
    color: #786d67;
  }

  .anw-chapter-narration-player__speaker-icon {
    display: inline-grid;
    width: 22px;
    height: 22px;
    flex: 0 0 22px;
    place-items: center;
    color: #9b8f88;
    font-size: 15px;
  }

  .anw-chapter-narration-player__identity strong {
    overflow: hidden;
    color: #5c514b;
    font-size: 13px;
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .anw-chapter-narration-player__controls {
    justify-self: center;
    gap: 5px;
  }

  .anw-chapter-narration-player__tools {
    justify-self: end;
    gap: 8px;
  }

  .anw-chapter-narration-player button,
  .anw-chapter-narration-player select {
    font: inherit;
  }

  .anw-chapter-narration-icon-button,
  .anw-chapter-narration-play-button,
  .anw-chapter-narration-tool-button,
  .anw-chapter-narration-primary-action,
  .anw-chapter-narration-update,
  .anw-chapter-narration-link-button,
  .anw-chapter-narration-more,
  .anw-chapter-narration-notice__action,
  .anw-chapter-narration-retry-button {
    min-width: 44px;
    min-height: 44px;
    border: 0;
    cursor: pointer;
  }

  .anw-chapter-narration-icon-button,
  .anw-chapter-narration-play-button,
  .anw-chapter-narration-tool-button {
    display: inline-grid;
    place-items: center;
    border-radius: 999px;
    padding: 0;
    background: transparent;
    color: #685d57;
    font-size: 17px;
  }

  .anw-chapter-narration-icon-button,
  .anw-chapter-narration-tool-button {
    width: 44px;
    height: 44px;
    flex: 0 0 44px;
  }

  .anw-chapter-narration-icon-button:hover:not(:disabled),
  .anw-chapter-narration-tool-button:hover:not(:disabled),
  .anw-chapter-narration-more:hover:not(:disabled) {
    background: #f6f0ec;
    color: #443a35;
  }

  .anw-chapter-narration-play-button {
    width: 48px;
    height: 48px;
    min-width: 48px;
    min-height: 48px;
    flex: 0 0 48px;
    background: #e86f32;
    color: #fff;
    font-size: 19px;
    box-shadow: 0 5px 12px rgba(211, 92, 38, 0.22);
  }

  .anw-chapter-narration-play-button:hover:not(:disabled) {
    background: #d75f28;
    transform: translateY(-1px);
  }

  .anw-chapter-narration-primary-action {
    border-radius: 11px;
    padding: 0 18px;
    background: #e86f32;
    color: #fff;
    font-size: 13px;
    font-weight: 750;
  }

  .anw-chapter-narration-player__phase {
    color: #7a6f68;
    font-size: 13px;
  }

  .anw-chapter-narration-player__time {
    color: #544943;
    font-size: 12px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .anw-chapter-narration-rate {
    display: inline-flex;
  }

  .anw-chapter-narration-rate__select {
    width: 62px;
    min-height: 40px;
    border: 1px solid #e1d7d1;
    border-radius: 9px;
    padding: 0 6px;
    background: #fff;
    color: #554943;
    font-size: 12px;
    text-align: center;
    cursor: pointer;
  }

  .anw-chapter-narration-volume-control {
    position: relative;
    display: inline-flex;
  }

  .anw-chapter-narration-volume-popover[hidden],
  .anw-chapter-narration-details[hidden],
  .anw-chapter-narration-details [hidden],
  .anw-chapter-narration-failures[hidden] {
    display: none !important;
  }

  .anw-chapter-narration-volume-popover {
    position: absolute;
    z-index: 6;
    right: 0;
    bottom: calc(100% + 9px);
    display: grid;
    width: 190px;
    gap: 8px;
    border: 1px solid #e4d8d1;
    border-radius: 11px;
    padding: 10px 12px;
    background: #fff;
    color: #675b54;
    box-shadow: 0 12px 30px rgba(73, 49, 37, 0.16);
    font-size: 12px;
  }

  .anw-chapter-narration-volume-popover input[type="range"] {
    width: 100%;
    min-height: 28px;
    accent-color: #e86f32;
  }

  .anw-chapter-narration-more {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 5px;
    border-radius: 9px;
    padding: 0 9px;
    background: transparent;
    color: #655a54;
    font-size: 12px;
    white-space: nowrap;
  }

  .anw-chapter-narration-player button:disabled,
  .anw-chapter-narration-player select:disabled,
  .anw-chapter-narration-player input:disabled {
    cursor: not-allowed;
    opacity: 0.46;
  }

  .anw-chapter-narration-notice {
    display: grid;
    min-width: 0;
    min-height: 48px;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    border: 1px solid #f0d2b2;
    border-radius: 10px;
    padding: 4px 7px 4px 12px;
    background: #fff8eb;
    color: #85512e;
  }

  .anw-chapter-narration-notice.is-error {
    border-color: #efcbc4;
    background: #fff5f3;
    color: #9a3429;
  }

  .anw-chapter-narration-notice.is-progress,
  .anw-chapter-narration-notice.is-info {
    border-color: #ded8d3;
    background: #f8f5f2;
    color: #655a54;
  }

  .anw-chapter-narration-notice__icon {
    display: inline-grid;
    width: 22px;
    place-items: center;
    font-size: 16px;
  }

  .anw-chapter-narration-notice__copy {
    display: grid;
    min-width: 0;
    gap: 3px;
    font-size: 12px;
    font-weight: 650;
  }

  .anw-chapter-narration-notice__copy progress {
    width: min(320px, 100%);
    height: 4px;
    accent-color: #e86f32;
  }

  .anw-chapter-narration-notice__action {
    border: 1px solid #e7a77e;
    border-radius: 9px;
    padding: 0 12px;
    background: #fff;
    color: #ba5428;
    font-size: 12px;
    font-weight: 700;
    white-space: nowrap;
  }

  .anw-chapter-narration-player__timeline {
    display: grid;
    min-width: 0;
    height: 22px;
    align-items: center;
  }

  .anw-chapter-narration-player__timeline input[type="range"] {
    width: 100%;
    min-height: 22px;
    margin: 0;
    accent-color: #e86f32;
    cursor: pointer;
  }

  .anw-chapter-narration-sr-only,
  .anw-chapter-narration-preference-live,
  .anw-chapter-narration-retry-live,
  .anw-chapter-narration-live {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    border: 0;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }

  .anw-chapter-narration-details {
    position: absolute;
    z-index: 5;
    right: 0;
    bottom: calc(100% + 10px);
    display: grid;
    width: min(700px, calc(100% - 16px));
    min-width: 0;
    max-height: min(58vh, 520px);
    gap: 12px;
    border: 1px solid #e4d8d1;
    border-radius: 14px;
    padding: 14px;
    overflow: auto;
    overscroll-behavior: contain;
    background: #fffdfb;
    box-shadow: 0 20px 50px rgba(65, 43, 33, 0.2);
  }

  .anw-chapter-narration-details__header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 14px;
    border-bottom: 1px solid #eee5df;
    padding-bottom: 10px;
  }

  .anw-chapter-narration-details__header > div {
    display: grid;
    gap: 2px;
  }

  .anw-chapter-narration-details__header strong {
    color: #443832;
    font-size: 14px;
  }

  .anw-chapter-narration-details__header span {
    color: #83766f;
    font-size: 11px;
  }

  .anw-chapter-narration-details__overview {
    display: grid;
    min-width: 0;
    grid-template-columns: minmax(220px, 0.85fr) minmax(260px, 1.15fr);
    gap: 12px;
  }

  .anw-chapter-narration-details__version {
    display: grid;
    align-content: start;
    gap: 8px;
    color: #776a63;
    font-size: 11px;
  }

  .anw-chapter-narration-select {
    display: grid;
    min-width: 0;
    gap: 5px;
    color: #756861;
    font-size: 11px;
  }

  .anw-chapter-narration-select select {
    width: 100%;
    min-height: 44px;
    border: 1px solid #ded4ce;
    border-radius: 9px;
    padding: 0 9px;
    background: #fff;
    color: #493f39;
  }

  .anw-chapter-narration-voices {
    min-width: 0;
    border: 1px solid #e9dfd9;
    border-radius: 10px;
    background: #fff;
  }

  .anw-chapter-narration-voices summary {
    min-height: 44px;
    padding: 13px 12px;
    color: #5b4f48;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
  }

  .anw-chapter-narration-voices ul {
    display: grid;
    max-height: 170px;
    gap: 5px;
    margin: 0;
    border-top: 1px solid #eee5df;
    padding: 8px;
    overflow: auto;
    list-style: none;
  }

  .anw-chapter-narration-voices li {
    display: flex;
    min-width: 0;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    border-radius: 7px;
    padding: 7px 8px;
    background: #faf6f3;
  }

  .anw-chapter-narration-voices li span,
  .anw-chapter-narration-voices p {
    margin: 0;
    overflow-wrap: anywhere;
    color: #574b44;
    font-size: 12px;
  }

  .anw-chapter-narration-voices li small {
    color: #8a7d75;
    font-size: 10px;
    white-space: nowrap;
  }

  .anw-chapter-narration-player__actions {
    grid-column: 1 / -1;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 6px;
  }

  .anw-chapter-narration-link-button,
  .anw-chapter-narration-update,
  .anw-chapter-narration-retry-button {
    border-radius: 8px;
    padding: 0 10px;
    background: transparent;
    color: #8d4628;
    font-size: 12px;
  }

  .anw-chapter-narration-link-button {
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .anw-chapter-narration-update {
    border: 1px solid #e0c8bc;
    background: #fff;
    text-decoration: none;
  }

  .anw-chapter-narration-update.is-required {
    border-color: #e2a47e;
    color: #b34e25;
    font-weight: 700;
  }

  .anw-chapter-narration-failures {
    display: grid;
    min-width: 0;
    gap: 8px;
  }

  .anw-chapter-narration-failures__header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
  }

  .anw-chapter-narration-failures__header strong {
    color: #8f2f24;
    font-size: 13px;
  }

  .anw-chapter-narration-failures__header span {
    color: #82766e;
    font-size: 11px;
  }

  .anw-chapter-narration-failures__list {
    display: grid;
    max-height: min(34vh, 260px);
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin: 0;
    padding: 0;
    overflow: auto;
    list-style: none;
  }

  .anw-chapter-narration-failure {
    display: grid;
    min-width: 0;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 12px;
    border: 1px solid #ead8cf;
    border-radius: 10px;
    padding: 8px 10px;
    background: #fffaf7;
  }

  .anw-chapter-narration-failure.is-busy {
    border-color: #e2a081;
    background: #fff4ed;
  }

  .anw-chapter-narration-failure__copy {
    display: grid;
    min-width: 0;
    gap: 2px;
  }

  .anw-chapter-narration-failure__copy strong {
    color: #5d4035;
    font-size: 12px;
  }

  .anw-chapter-narration-failure__copy span {
    overflow: hidden;
    color: #756861;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .anw-chapter-narration-failure__copy small {
    color: #8a5747;
    font-size: 10px;
    line-height: 1.45;
  }

  .anw-chapter-narration-retry-button {
    border: 1px solid #d76832;
    background: #fff;
    color: #943b1c;
    font-weight: 700;
    white-space: nowrap;
  }

  @container (max-width: 760px) {
    .anw-chapter-narration-player__compact {
      gap: 7px;
    }

    .anw-chapter-narration-player__tools {
      gap: 3px;
    }

    .anw-chapter-narration-player__time {
      display: none;
    }

    .anw-chapter-narration-details__overview,
    .anw-chapter-narration-failures__list {
      grid-template-columns: minmax(0, 1fr);
    }
  }

  @media (max-width: 720px) {
    .anw-editor-content.has-chapter-narration {
      display: block;
      height: auto;
      min-height: 100%;
      overflow: visible;
    }

    .anw-editor-content.has-chapter-narration > .anw-editor-scroll {
      min-height: 0;
      overflow: visible;
      padding-bottom: 16px;
    }

    .anw-chapter-narration-player {
      position: sticky;
      z-index: 0;
      bottom: 0;
      width: 100%;
      margin: 0;
      border-right: 0;
      border-left: 0;
      border-radius: 12px 12px 0 0;
      padding-inline: 8px;
    }

    .anw-chapter-narration-player__compact {
      grid-template-columns: minmax(70px, 1fr) auto minmax(70px, 1fr);
      gap: 4px;
    }

    .anw-chapter-narration-player__speaker-icon,
    .anw-chapter-narration-more span {
      display: none;
    }

    .anw-chapter-narration-player__tools {
      gap: 0;
    }

    .anw-chapter-narration-rate__select {
      width: 56px;
    }

    .anw-chapter-narration-details {
      right: 8px;
      width: calc(100% - 16px);
      max-height: min(58dvh, 480px);
    }

    .anw-chapter-narration-notice {
      min-height: 44px;
      padding-left: 9px;
    }

    .anw-chapter-narration-failures__header,
    .anw-chapter-narration-failure {
      align-items: stretch;
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-chapter-narration-failures__header {
      display: grid;
      gap: 3px;
    }
  }

  @media (forced-colors: active) {
    .anw-chapter-narration-player,
    .anw-chapter-narration-notice,
    .anw-chapter-narration-details,
    .anw-chapter-narration-failure {
      border: 1px solid CanvasText;
    }

    .anw-chapter-narration-play-button {
      forced-color-adjust: auto;
    }
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

  @media (max-width: 768px) {
    .anw-script-review-shell {
      inset: 0;
      width: 100%;
      border: 0;
      border-radius: 0;
    }

    .anw-script-review__header,
    .anw-script-review__footer,
    .anw-script-review__snapshot,
    .anw-script-review__filters,
    .anw-script-review__snapshot-choice,
    .anw-script-review__error,
    .anw-script-review__global-issues {
      padding-inline: 14px;
    }

    .anw-script-review__header {
      gap: 12px;
      padding-block: 14px 12px;
    }

    .anw-script-review__compact-player {
      grid-template-columns: minmax(0, 1fr);
      gap: 10px;
      padding-inline: 14px;
    }

    .anw-script-review__compact-player-actions,
    .anw-script-review__segment-actions {
      flex-wrap: wrap;
    }

    .anw-script-review__workspace {
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
      padding: 0 14px 16px;
    }

    .anw-script-review__guide {
      position: static;
    }

    .anw-script-review__segment-actions button {
      flex: 1 1 150px;
    }

    .anw-script-review__footer {
      flex-wrap: wrap;
      gap: 10px;
    }

    .anw-script-review__footer button {
      flex: 1 0 100%;
    }
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
