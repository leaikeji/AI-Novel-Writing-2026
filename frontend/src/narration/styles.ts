import { T2_B_READING_STYLES } from "./styles/t2-b";
import { T2_C_CHARACTER_VOICE_PANEL_STYLES } from "./styles/t2-c";
import { T2_D_NARRATION_STYLES } from "./styles/t2-d";
import { T2_F_NARRATION_SETTINGS_PANEL_STYLES } from "./styles/t2-f";
import { T2_G_NARRATION_READING_RULES_STYLES } from "./styles/t2-g";
import { T4_CHAPTER_NARRATION_STYLES } from "./styles/t4-chapter";
import { OFFICIAL_VOICE_LIBRARY_STYLES } from "./styles/voice-library";
import { NANO_ADVANCED_TUNING_STYLES } from "./styles/nano-advanced-tuning";
import { CHARACTER_VOICE_GENERATOR_STYLES } from "./styles/character-voice-generator";
import { VOICE_LIFECYCLE_STYLES } from "./styles/voice-lifecycle";


export const NARRATION_STYLE_ID = "ai-novel-world-2026-narration-ui" as const;


export const NARRATION_STYLES = [
  T2_B_READING_STYLES,
  T2_C_CHARACTER_VOICE_PANEL_STYLES,
  T2_D_NARRATION_STYLES,
  T2_F_NARRATION_SETTINGS_PANEL_STYLES,
  T2_G_NARRATION_READING_RULES_STYLES,
  T4_CHAPTER_NARRATION_STYLES,
  OFFICIAL_VOICE_LIBRARY_STYLES,
  NANO_ADVANCED_TUNING_STYLES,
  CHARACTER_VOICE_GENERATOR_STYLES,
  VOICE_LIFECYCLE_STYLES,
  String.raw`
    .anw-narration-character-section,
    .anw-narration-character-card-panel,
    .anw-narration-feature-workspace,
    .anw-narration-private-stack,
    .anw-narration-private-list {
      display: grid;
      gap: 16px;
      min-width: 0;
    }

    .anw-narration-feature-target {
      display: grid;
      gap: 6px;
      max-width: 420px;
      font-weight: 650;
    }

    .anw-narration-feature-target select {
      width: 100%;
      min-height: 44px;
      box-sizing: border-box;
      border: 1px solid var(--ant-color-border, #d9dadd);
      border-radius: 9px;
      padding: 8px 11px;
      color: inherit;
      background: var(--ant-color-bg-container, #fff);
      font: inherit;
    }

    .anw-character-current-voice {
      display: grid;
      gap: 10px;
      border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
      border-radius: 13px;
      padding: 14px 16px;
      background: var(--ant-color-bg-container, #fff);
    }

    .anw-character-current-voice header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }

    .anw-character-current-voice h3,
    .anw-character-current-voice p {
      margin: 0;
    }

    .anw-character-current-voice h3 {
      margin-top: 2px;
      font-size: 16px;
    }

    .anw-character-current-voice__badge {
      flex: 0 0 auto;
      border-radius: 999px;
      padding: 4px 8px;
      color: #176b32;
      background: #f0faf2;
      font-size: 11px;
    }

    .anw-character-current-voice__badge.is-muted {
      color: var(--ant-color-text-secondary, #5f6670);
      background: var(--ant-color-fill-tertiary, #f5f5f6);
    }

    .anw-character-current-voice__badge.is-error {
      color: var(--ant-color-error, #b42318);
      background: #fff2ed;
    }

    .anw-character-current-voice__identity {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 6px 12px;
    }

    .anw-character-current-voice__identity strong {
      font-size: 15px;
    }

    .anw-character-current-voice__identity span,
    .anw-character-current-voice__status {
      color: var(--ant-color-text-secondary, #5f6670);
      font-size: 12px;
    }

    .anw-character-current-voice__status.is-error {
      color: var(--ant-color-error, #b42318);
    }

    .anw-character-voice-advanced-stack {
      display: grid;
      min-width: 0;
      gap: 16px;
    }

    .anw-narrator-current-voice {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      border: 1px solid var(--ant-color-border-secondary, #e5e6e8);
      border-radius: 13px;
      padding: 14px 16px;
      background: var(--ant-color-bg-container, #fff);
    }

    .anw-narrator-current-voice__copy {
      display: grid;
      min-width: 0;
      gap: 3px;
    }

    .anw-narrator-current-voice__copy > span,
    .anw-narrator-current-voice__copy > small {
      color: var(--ant-color-text-secondary, #5f6670);
      font-size: 12px;
      overflow-wrap: anywhere;
    }

    .anw-narrator-current-voice__copy > strong {
      font-size: 16px;
    }

    .anw-narrator-current-voice__actions {
      display: flex;
      flex: 0 0 auto;
      gap: 8px;
    }

    .anw-narrator-current-voice__actions button {
      min-height: 42px;
      border: 1px solid var(--ant-color-border, #d9dadd);
      border-radius: 9px;
      padding: 8px 13px;
      color: inherit;
      background: #fff;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
    }

    .anw-narrator-current-voice__actions .anw-narration-primary-action {
      border-color: transparent;
      color: #fff;
      background: linear-gradient(135deg, #ff7043, #ff5d2a);
    }

    .anw-narrator-voice-library-editor {
      min-width: 0;
    }

    .anw-narration-feature-target select:focus-visible,
    .anw-narrator-current-voice__actions button:focus-visible {
      outline: 3px solid color-mix(in srgb, #d76832 38%, transparent);
      outline-offset: 2px;
    }

    .mb-novel-tool-row.has-reading {
      grid-template-columns: repeat(5, minmax(0, 1fr));
      padding-inline: 44px;
    }

    .mb-panel-body.is-reading {
      padding: 0;
      overflow: hidden;
    }

    .anw-character-modal-tabs button {
      min-height: 40px;
      border: 1px solid color-mix(in srgb, currentColor 16%, transparent);
      border-radius: 999px;
      padding: 7px 14px;
      background: transparent;
      color: inherit;
      cursor: pointer;
    }

    .anw-character-modal-tabs button.is-active {
      border-color: #d76832;
      background: #fff3eb;
      color: #a8441f;
    }

    .anw-character-modal-tabs button:focus-visible {
      outline: 3px solid color-mix(in srgb, #d76832 38%, transparent);
      outline-offset: 2px;
    }

    .anw-character-modal-tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
    }

    .anw-narration-card-loading,
    .anw-narration-card-error,
    .anw-narration-empty-characters {
      border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
      border-radius: 12px;
      padding: 18px;
    }

    @media (max-width: 560px) {
      .mb-novel-tool-row.has-reading {
        padding-inline: 12px;
      }

      .anw-narrator-current-voice {
        align-items: stretch;
        flex-direction: column;
      }

      .anw-narrator-current-voice__actions {
        display: grid;
      }

      .anw-narrator-current-voice__actions button {
        width: 100%;
      }

    }
  `,
].join("\n");


export function ensureNarrationStyles(): void {
  if (document.getElementById(NARRATION_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = NARRATION_STYLE_ID;
  style.dataset.pawappOwner = "ai-novel-world-2026";
  style.textContent = NARRATION_STYLES;
  document.head.appendChild(style);
}
