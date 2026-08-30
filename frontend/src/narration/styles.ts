import { T2_B_READING_STYLES } from "./styles/t2-b";
import { T2_C_CHARACTER_VOICE_PANEL_STYLES } from "./styles/t2-c";
import { T2_D_NARRATION_STYLES } from "./styles/t2-d";
import { T2_F_NARRATION_SETTINGS_PANEL_STYLES } from "./styles/t2-f";
import { T2_G_NARRATION_READING_RULES_STYLES } from "./styles/t2-g";
import { T4_CHAPTER_NARRATION_STYLES } from "./styles/t4-chapter";
import { OFFICIAL_VOICE_LIBRARY_STYLES } from "./styles/voice-library";
import { NANO_ADVANCED_TUNING_STYLES } from "./styles/nano-advanced-tuning";
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

    .anw-narration-feature-target,
    .anw-narration-voice-library-target {
      display: grid;
      gap: 6px;
      max-width: 420px;
      font-weight: 650;
    }

    .anw-narration-feature-target select,
    .anw-narration-voice-library-target select {
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

    .anw-character-card-voice-match {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      border: 1px solid color-mix(in srgb, #d76832 22%, transparent);
      border-radius: 12px;
      padding: 14px;
      background: color-mix(in srgb, #fff3eb 72%, transparent);
    }

    .anw-character-card-voice-match button {
      min-height: 44px;
      border: 1px solid #d76832;
      border-radius: 9px;
      padding: 9px 13px;
      color: #a8441f;
      background: #fff;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
    }

    .anw-character-card-voice-match p {
      flex-basis: 100%;
      margin: 0;
      overflow-wrap: anywhere;
    }

    .anw-character-card-voice-match button:focus-visible,
    .anw-narration-feature-target select:focus-visible,
    .anw-narration-voice-library-target select:focus-visible {
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

    .anw-narration-source-summary {
      border-top: 1px solid color-mix(in srgb, currentColor 12%, transparent);
      padding-top: 16px;
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

      .anw-character-card-voice-match {
        display: grid;
      }

      .anw-character-card-voice-match button {
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
