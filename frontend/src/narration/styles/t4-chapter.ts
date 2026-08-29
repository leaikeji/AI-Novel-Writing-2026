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
    position: relative;
    z-index: 35;
    display: grid;
    width: min(1440px, calc(100% - 48px));
    min-width: 0;
    flex: 0 0 auto;
    gap: 6px;
    margin: 0 auto 14px;
    border: 1px solid color-mix(in srgb, #5f493c 18%, transparent);
    border-radius: 18px;
    padding: 8px 12px 7px;
    overflow: hidden;
    background: color-mix(in srgb, #fff 96%, #fff7f0);
    box-shadow: 0 12px 32px rgba(76, 49, 34, 0.16);
    backdrop-filter: blur(18px);
  }

  .anw-chapter-narration-player__compact {
    display: grid;
    min-width: 0;
    min-height: 64px;
    grid-template-columns: minmax(184px, 0.85fr) auto minmax(250px, 1.15fr) minmax(252px, auto) auto;
    align-items: center;
    gap: 8px 14px;
  }

  .anw-chapter-narration-player__identity {
    display: grid;
    min-width: 0;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: 9px;
  }

  .anw-chapter-narration-source {
    display: inline-flex;
    min-height: 28px;
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
    color: #8d3f19;
  }

  .anw-chapter-narration-current-copy {
    display: grid;
    min-width: 0;
    gap: 1px;
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
    font-size: 11px;
  }

  .anw-chapter-narration-current-copy .anw-chapter-narration-voice-summary {
    color: #965033;
    font-weight: 650;
  }

  .anw-chapter-narration-player__controls,
  .anw-chapter-narration-player__view-actions,
  .anw-chapter-narration-player__preferences,
  .anw-chapter-narration-player__actions {
    display: flex;
    min-width: 0;
    align-items: center;
    gap: 6px;
  }

  .anw-chapter-narration-player__view-actions,
  .anw-chapter-narration-player__actions {
    justify-content: flex-end;
  }

  .anw-chapter-narration-icon-button,
  .anw-chapter-narration-play-button,
  .anw-chapter-narration-primary-action,
  .anw-chapter-narration-update,
  .anw-chapter-narration-link-button,
  .anw-chapter-narration-more,
  .anw-chapter-narration-failure-trigger,
  .anw-chapter-narration-details__close,
  .anw-chapter-narration-retry-button {
    min-width: 44px;
    min-height: 44px;
    border: 0;
    cursor: pointer;
  }

  .anw-chapter-narration-icon-button,
  .anw-chapter-narration-play-button {
    width: 44px;
    height: 44px;
    flex: 0 0 44px;
    border-radius: 999px;
  }

  .anw-chapter-narration-icon-button {
    background: transparent;
    color: #5c4b41;
  }

  .anw-chapter-narration-play-button {
    background: #d76832;
    color: #fff;
    font-size: 18px;
    box-shadow: 0 7px 16px rgba(215, 104, 50, 0.24);
  }

  .anw-chapter-narration-primary-action,
  .anw-chapter-narration-update {
    border-radius: 10px;
    padding: 8px 14px;
    background: #d76832;
    color: #fff;
    font-weight: 700;
  }

  .anw-chapter-narration-update:not(.is-required) {
    background: #f4eee9;
    color: #6f5547;
  }

  .anw-chapter-narration-more,
  .anw-chapter-narration-failure-trigger,
  .anw-chapter-narration-details__close {
    border-radius: 10px;
    padding: 7px 10px;
    background: #f5efea;
    color: #684b3c;
    font-size: 12px;
    font-weight: 700;
  }

  .anw-chapter-narration-failure-trigger {
    background: #fff0e9;
    color: #a12f24;
  }

  .anw-chapter-narration-player button:disabled,
  .anw-chapter-narration-player select:disabled,
  .anw-chapter-narration-player input:disabled {
    cursor: not-allowed;
    opacity: 0.48;
  }

  .anw-chapter-narration-player__metrics {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(3, minmax(78px, 1fr));
    align-items: center;
    gap: 10px;
  }

  .anw-chapter-narration-metric,
  .anw-chapter-narration-generation {
    display: grid;
    min-width: 0;
    gap: 2px;
  }

  .anw-chapter-narration-metric span,
  .anw-chapter-narration-generation span {
    color: #8a7b72;
    font-size: 10px;
  }

  .anw-chapter-narration-metric strong,
  .anw-chapter-narration-generation strong {
    overflow: hidden;
    color: #51443d;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .anw-chapter-narration-generation > div {
    display: flex;
    justify-content: space-between;
    gap: 6px;
  }

  .anw-chapter-narration-generation progress {
    width: 100%;
    height: 5px;
    accent-color: #d76832;
  }

  .anw-chapter-narration-generation.is-failed progress {
    accent-color: #b3261e;
  }

  .anw-chapter-narration-player__preferences {
    justify-content: flex-end;
  }

  .anw-chapter-narration-select,
  .anw-chapter-narration-volume {
    display: inline-flex;
    min-height: 44px;
    align-items: center;
    gap: 5px;
    color: #6d6058;
    font-size: 11px;
  }

  .anw-chapter-narration-select select {
    max-width: 180px;
    min-height: 44px;
    border: 1px solid #ded4cc;
    border-radius: 9px;
    padding-inline: 6px;
    background: #fff;
    color: #493c35;
  }

  .anw-chapter-narration-volume input[type="range"] {
    width: 86px;
    min-height: 44px;
    accent-color: #d76832;
  }

  .anw-chapter-narration-volume output {
    width: 32px;
    color: #594c44;
    font-variant-numeric: tabular-nums;
  }

  .anw-chapter-narration-player__timeline {
    display: grid;
    min-width: 0;
    min-height: 44px;
    grid-template-columns: minmax(180px, 1fr) auto;
    align-items: center;
    gap: 10px;
    color: #786a61;
    font-size: 11px;
  }

  .anw-chapter-narration-player__timeline input[type="range"] {
    width: 100%;
    min-height: 44px;
    accent-color: #d76832;
  }

  .anw-chapter-narration-link-button {
    border-radius: 8px;
    padding: 7px 9px;
    background: transparent;
    color: #8d3d1e;
    font-size: 12px;
    text-decoration: underline;
    text-underline-offset: 3px;
  }

  .anw-chapter-narration-details[hidden],
  .anw-chapter-narration-details [hidden],
  .anw-chapter-narration-failures[hidden] {
    display: none !important;
  }

  .anw-chapter-narration-details {
    display: grid;
    min-width: 0;
    max-height: min(44vh, 420px);
    gap: 12px;
    border-top: 1px solid #e9ddd5;
    padding: 12px 2px 4px;
    overflow: auto;
    overscroll-behavior: contain;
  }

  .anw-chapter-narration-details__header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }

  .anw-chapter-narration-details__header > div {
    display: grid;
    gap: 2px;
  }

  .anw-chapter-narration-details__header strong {
    color: #4c3c34;
    font-size: 14px;
  }

  .anw-chapter-narration-details__header span {
    color: #81736a;
    font-size: 11px;
  }

  .anw-chapter-narration-details__overview {
    display: grid;
    min-width: 0;
    grid-template-columns: minmax(0, 1.1fr) minmax(240px, 0.9fr);
    gap: 12px 18px;
  }

  .anw-chapter-narration-status-grid {
    display: grid;
    min-width: 0;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin: 0;
  }

  .anw-chapter-narration-status-grid > div {
    display: grid;
    min-width: 0;
    gap: 2px;
    border-radius: 10px;
    padding: 8px 10px;
    background: #f8f3ef;
  }

  .anw-chapter-narration-status-grid dt {
    color: #8a7a70;
    font-size: 10px;
    font-weight: 700;
  }

  .anw-chapter-narration-status-grid dd {
    margin: 0;
    overflow-wrap: anywhere;
    color: #514139;
    font-size: 12px;
  }

  .anw-chapter-narration-voices {
    display: grid;
    min-width: 0;
    gap: 7px;
  }

  .anw-chapter-narration-voices > strong {
    color: #57463d;
    font-size: 12px;
  }

  .anw-chapter-narration-voices ul {
    display: grid;
    max-height: 118px;
    gap: 5px;
    margin: 0;
    padding: 0;
    overflow: auto;
    list-style: none;
  }

  .anw-chapter-narration-voices li {
    display: grid;
    min-width: 0;
    gap: 2px;
    border-radius: 8px;
    padding: 6px 8px;
    background: #fff7f1;
  }

  .anw-chapter-narration-voices li span,
  .anw-chapter-narration-voices p {
    margin: 0;
    overflow-wrap: anywhere;
    color: #57453c;
    font-size: 12px;
  }

  .anw-chapter-narration-voices li small {
    overflow-wrap: anywhere;
    color: #806e64;
    font-size: 10px;
  }

  .anw-chapter-narration-details__overview > .anw-chapter-narration-player__actions {
    grid-column: 1 / -1;
    flex-wrap: wrap;
  }

  .anw-chapter-narration-details .anw-chapter-narration-failures {
    display: grid;
    min-width: 0;
    gap: 8px;
    border: 0;
    padding: 0;
  }

  .anw-chapter-narration-details .anw-chapter-narration-failures__header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
  }

  .anw-chapter-narration-details .anw-chapter-narration-failures__header strong {
    color: #8f2f24;
    font-size: 13px;
  }

  .anw-chapter-narration-details .anw-chapter-narration-failures__header span {
    color: #82766e;
    font-size: 11px;
  }

  .anw-chapter-narration-details .anw-chapter-narration-failures__list {
    display: grid;
    max-height: min(34vh, 260px);
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin: 0;
    padding: 0;
    overflow: auto;
    list-style: none;
  }

  .anw-chapter-narration-details .anw-chapter-narration-failure {
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

  .anw-chapter-narration-details .anw-chapter-narration-failure.is-busy {
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
    border: 1px solid #d76832 !important;
    border-radius: 8px;
    padding: 6px 10px;
    color: #943b1c;
    background: #fff;
    font-size: 12px;
    font-weight: 700;
    white-space: nowrap;
  }

  .anw-chapter-narration-preference-live,
  .anw-chapter-narration-retry-live,
  .anw-chapter-narration-live {
    min-width: 0;
    overflow: hidden;
    color: #6f625a;
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .anw-chapter-narration-preference-live.is-conflict,
  .anw-chapter-narration-preference-live.is-error,
  .anw-chapter-narration-retry-live.is-error,
  .anw-chapter-narration-live.is-error {
    color: #9f271e;
    font-weight: 650;
  }

  @container (max-width: 1024px) {
    .anw-chapter-narration-player__compact {
      grid-template-columns: minmax(160px, 1fr) auto minmax(220px, 1fr) auto;
    }

    .anw-chapter-narration-player__preferences {
      grid-column: 1 / -1;
      justify-content: flex-start;
    }

    .anw-chapter-narration-player__view-actions {
      grid-column: 4;
      grid-row: 1;
    }
  }

  @media (max-width: 1024px) {
    .anw-chapter-narration-player {
      width: calc(100% - 28px);
    }

    .anw-chapter-narration-player__compact {
      grid-template-columns: minmax(160px, 1fr) auto minmax(220px, 1fr) auto;
    }

    .anw-chapter-narration-player__preferences {
      grid-column: 1 / -1;
      justify-content: flex-start;
    }

    .anw-chapter-narration-player__view-actions {
      grid-column: 4;
      grid-row: 1;
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
      bottom: 0;
      width: 100%;
      margin: 0;
      border-right: 0;
      border-bottom: 0;
      border-left: 0;
      border-radius: 16px 16px 0 0;
      padding: 4px 8px;
      background: #fffdfb;
      box-shadow: 0 -10px 28px rgba(76, 49, 34, 0.16);
      backdrop-filter: none;
    }

    .anw-chapter-narration-player__compact {
      min-height: 64px;
      grid-template-columns: minmax(0, 1fr) auto auto;
      gap: 6px;
    }

    .anw-chapter-narration-player__identity {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-chapter-narration-source,
    .anw-chapter-narration-current-copy > span:last-child,
    .anw-chapter-narration-player.is-layout-compact .anw-chapter-narration-player__metrics,
    .anw-chapter-narration-player.is-layout-compact .anw-chapter-narration-player__preferences,
    .anw-chapter-narration-player.is-layout-compact .anw-chapter-narration-player__timeline {
      display: none;
    }

    .anw-chapter-narration-player.is-layout-compact > .anw-chapter-narration-live:not(.is-error) {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
    }

    .anw-chapter-narration-current-copy strong,
    .anw-chapter-narration-current-copy .anw-chapter-narration-voice-summary {
      display: block;
    }

    .anw-chapter-narration-player__controls {
      gap: 2px;
    }

    .anw-chapter-narration-player__view-actions {
      grid-column: auto;
      grid-row: auto;
    }

    .anw-chapter-narration-failure-trigger {
      padding-inline: 8px;
    }

    .anw-chapter-narration-player.is-layout-compact .anw-chapter-narration-more,
    .anw-chapter-narration-player.is-layout-compact .anw-chapter-narration-failure-trigger {
      min-width: 44px;
      padding-inline: 6px;
    }

    .anw-chapter-narration-player:not(.is-layout-compact) .anw-chapter-narration-player__compact {
      grid-template-columns: minmax(0, 1fr) auto auto;
      padding-bottom: 4px;
    }

    .anw-chapter-narration-player:not(.is-layout-compact) .anw-chapter-narration-player__metrics,
    .anw-chapter-narration-player:not(.is-layout-compact) .anw-chapter-narration-player__preferences {
      grid-column: 1 / -1;
    }

    .anw-chapter-narration-player__metrics {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .anw-chapter-narration-player__preferences {
      flex-wrap: wrap;
      justify-content: flex-start;
    }

    .anw-chapter-narration-volume {
      min-width: min(250px, 100%);
      flex: 1 1 210px;
    }

    .anw-chapter-narration-volume input[type="range"] {
      min-width: 90px;
      flex: 1 1 auto;
    }

    .anw-chapter-narration-player__timeline {
      grid-template-columns: minmax(0, 1fr);
      gap: 0;
    }

    .anw-chapter-narration-details {
      max-height: min(52dvh, 440px);
      padding: 10px 2px 6px;
    }

    .anw-chapter-narration-details__overview,
    .anw-chapter-narration-status-grid,
    .anw-chapter-narration-details .anw-chapter-narration-failures__list {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-chapter-narration-details .anw-chapter-narration-failures__header,
    .anw-chapter-narration-details .anw-chapter-narration-failure {
      align-items: stretch;
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-chapter-narration-details .anw-chapter-narration-failures__header {
      display: grid;
      gap: 3px;
    }

    .anw-chapter-narration-player__actions {
      justify-content: flex-start;
    }
  }

  @media (max-width: 390px) {
    .anw-chapter-narration-player__compact {
      grid-template-columns: minmax(72px, 1fr) auto auto;
    }

    .anw-chapter-narration-current-copy .anw-chapter-narration-voice-summary,
    .anw-chapter-narration-player.is-layout-compact .anw-chapter-narration-failure-trigger {
      display: none;
    }

    .anw-chapter-narration-icon-button,
    .anw-chapter-narration-play-button {
      width: 44px;
      flex-basis: 44px;
    }

    .anw-chapter-narration-player__metrics {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-chapter-narration-select {
      width: 100%;
      justify-content: space-between;
    }

    .anw-chapter-narration-select select {
      max-width: min(230px, 68vw);
    }
  }

  @media (forced-colors: active) {
    .anw-chapter-narration-player,
    .anw-chapter-narration-status-grid > div,
    .anw-chapter-narration-details .anw-chapter-narration-failure {
      border: 1px solid CanvasText;
    }

    .anw-chapter-narration-source,
    .anw-chapter-narration-play-button,
    .anw-chapter-narration-failure-trigger {
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

  .anw-narration-edition-confirm__copy {
    display: grid;
    gap: 8px;
    overflow-wrap: anywhere;
  }

  .anw-narration-edition-confirm__copy p {
    margin: 0;
  }
`;
