import { T2_B_READING_STYLES } from "./styles/t2-b";
import { T2_C_CHARACTER_VOICE_PANEL_STYLES } from "./styles/t2-c";
import { T2_D_NARRATION_STYLES } from "./styles/t2-d";
import { T2_F_NARRATION_SETTINGS_PANEL_STYLES } from "./styles/t2-f";
import { T2_G_NARRATION_READING_RULES_STYLES } from "./styles/t2-g";
import { T4_CHAPTER_NARRATION_STYLES } from "./styles/t4-chapter";


export const NARRATION_STYLE_ID = "ai-novel-world-2026-narration-ui" as const;


export const NARRATION_STYLES = [
  T2_B_READING_STYLES,
  T2_C_CHARACTER_VOICE_PANEL_STYLES,
  T2_D_NARRATION_STYLES,
  T2_F_NARRATION_SETTINGS_PANEL_STYLES,
  T2_G_NARRATION_READING_RULES_STYLES,
  T4_CHAPTER_NARRATION_STYLES,
  String.raw`
    .anw-narration-character-section,
    .anw-narration-character-card-panel {
      display: grid;
      gap: 16px;
      min-width: 0;
    }

    .mb-novel-tool-row.has-reading {
      grid-template-columns: repeat(5, minmax(0, 1fr));
      padding-inline: 44px;
    }

    .mb-panel-body.is-reading {
      padding: 0;
      overflow: hidden;
    }

    .anw-narration-character-picker {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .anw-narration-character-picker button,
    .anw-character-modal-tabs button {
      min-height: 40px;
      border: 1px solid color-mix(in srgb, currentColor 16%, transparent);
      border-radius: 999px;
      padding: 7px 14px;
      background: transparent;
      color: inherit;
      cursor: pointer;
    }

    .anw-narration-character-picker button.is-active,
    .anw-character-modal-tabs button.is-active {
      border-color: #d76832;
      background: #fff3eb;
      color: #a8441f;
    }

    .anw-narration-character-picker button:focus-visible,
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

      .anw-narration-character-picker {
        display: grid;
        grid-template-columns: minmax(0, 1fr);
      }

      .anw-narration-character-picker button {
        width: 100%;
        border-radius: 10px;
        text-align: left;
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
