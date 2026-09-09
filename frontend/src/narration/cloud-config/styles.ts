const STYLE_ID = "anw-tts-cloud-config-styles";


export function ensureTtsCloudConfigStyles(): void {
  if (typeof document === "undefined" || document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .anw-tts-cloud-config {
      display: grid;
      gap: 18px;
      width: min(1120px, 100%);
      margin: 0 auto;
      padding: 24px;
    }
    .anw-tts-cloud-config__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
    }
    .anw-tts-cloud-config__header h2,
    .anw-tts-cloud-config__header p { margin: 0 0 8px; }
    .anw-tts-cloud-config__form {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .anw-tts-cloud-config__form label,
    .anw-tts-cloud-config__form > div { display: grid; gap: 7px; }
    .anw-tts-cloud-config section[aria-labelledby="anw-tts-cloud-list-heading"] {
      display: grid;
      gap: 14px;
    }
    .anw-tts-cloud-config dl {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px 18px;
      margin: 0 0 14px;
    }
    .anw-tts-cloud-config dl > div { min-width: 0; }
    .anw-tts-cloud-config dt { font-weight: 600; }
    .anw-tts-cloud-config dd { margin: 4px 0 0; overflow-wrap: anywhere; }
    .anw-tts-cloud-config__actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }
    .anw-tts-cloud-config [role="alertdialog"] {
      display: grid;
      gap: 12px;
      padding: 20px;
      border: 1px solid rgba(120, 120, 120, .35);
      border-radius: 12px;
      background: var(--qwenpaw-color-bg-container, #fff);
      box-shadow: 0 14px 40px rgba(0, 0, 0, .14);
    }
    .anw-tts-cloud-config audio { width: min(520px, 100%); }
    @media (max-width: 720px) {
      .anw-tts-cloud-config { padding: 16px; }
      .anw-tts-cloud-config__header { flex-direction: column; }
      .anw-tts-cloud-config__form,
      .anw-tts-cloud-config dl { grid-template-columns: minmax(0, 1fr); }
    }
  `;
  document.head.appendChild(style);
}
