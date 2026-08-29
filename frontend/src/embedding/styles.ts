export const EMBEDDING_STYLE_ID = "ai-novel-world-2026-embedding-ui" as const;


export const EMBEDDING_STYLES = String.raw`
  .anw-embedding-page,
  .anw-semantic-index-card {
    min-width: 0;
    color: inherit;
  }

  .anw-embedding-page {
    display: grid;
    gap: 18px;
    width: min(1180px, 100%);
    margin: 0 auto;
    padding: 20px;
    overflow: auto;
  }

  .anw-embedding-hero {
    padding: 22px 24px;
    border: 1px solid color-mix(in srgb, #1677ff 22%, transparent);
    border-radius: 16px;
    background:
      radial-gradient(circle at 92% 16%, color-mix(in srgb, #722ed1 16%, transparent), transparent 34%),
      linear-gradient(135deg, color-mix(in srgb, #1677ff 12%, transparent), transparent 62%);
  }

  .anw-embedding-eyebrow {
    margin: 0 0 5px;
    color: #1677ff;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .12em;
  }

  .anw-embedding-hero__summary {
    max-width: 700px;
    margin: 8px 0 0;
    line-height: 1.65;
    opacity: .78;
  }

  .anw-embedding-hero__tags {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    flex-wrap: wrap;
    gap: 8px;
  }

  .anw-embedding-steps {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .anw-embedding-steps > div {
    display: grid;
    grid-template-columns: 32px minmax(0, 1fr);
    gap: 1px 10px;
    align-items: center;
    min-width: 0;
    padding: 13px 14px;
    border: 1px solid color-mix(in srgb, currentColor 13%, transparent);
    border-radius: 12px;
    background: color-mix(in srgb, currentColor 3%, transparent);
  }

  .anw-embedding-steps > div > span {
    grid-row: 1 / span 2;
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: color-mix(in srgb, currentColor 10%, transparent);
    font-weight: 700;
  }

  .anw-embedding-steps > div[data-state="done"] > span {
    color: #fff;
    background: #389e0d;
  }

  .anw-embedding-steps > div[data-state="current"] {
    border-color: color-mix(in srgb, #1677ff 38%, transparent);
  }

  .anw-embedding-steps > div[data-state="current"] > span {
    color: #fff;
    background: #1677ff;
  }

  .anw-embedding-steps small {
    opacity: .65;
  }

  .anw-embedding-page__header,
  .anw-semantic-index-card__header,
  .anw-embedding-actions,
  .anw-embedding-inline-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 10px;
  }

  .anw-embedding-page h2,
  .anw-embedding-page h3,
  .anw-semantic-index-card h3,
  .anw-semantic-index-card h4 {
    margin: 0;
  }

  .anw-embedding-grid,
  .anw-embedding-metrics,
  .anw-semantic-corpora {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .anw-embedding-field {
    display: grid;
    gap: 6px;
    min-width: 0;
  }

  .anw-embedding-field > span:first-child {
    font-weight: 600;
  }

  .anw-embedding-field input {
    width: 100%;
    min-height: 40px;
  }

  .anw-embedding-field .ant-select {
    width: 100%;
  }

  .anw-embedding-field-error {
    color: #ff4d4f;
    font-size: 12px;
    line-height: 1.5;
  }

  .anw-embedding-readonly,
  .anw-embedding-metrics > div,
  .anw-semantic-corpora > li,
  .anw-embedding-confirm,
  .anw-embedding-credential {
    border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
    border-radius: 10px;
    padding: 12px;
  }

  .anw-embedding-credential {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: minmax(120px, auto) minmax(180px, 1fr);
    gap: 6px 14px;
    align-items: center;
    background: color-mix(in srgb, #1677ff 6%, transparent);
  }

  .anw-embedding-credential code {
    justify-self: end;
    padding: 6px 10px;
    border-radius: 8px;
    background: color-mix(in srgb, currentColor 7%, transparent);
    font-size: 14px;
    font-weight: 650;
    letter-spacing: .06em;
    overflow-wrap: anywhere;
  }

  .anw-embedding-credential small {
    grid-column: 1 / -1;
    opacity: .68;
    line-height: 1.55;
  }

  .anw-embedding-card {
    overflow: hidden;
    border-radius: 14px;
  }

  .anw-embedding-card--diagnostics {
    opacity: .92;
  }

  .anw-embedding-actions {
    margin-top: 16px;
  }

  .anw-embedding-live {
    padding: 11px 14px;
    border-left: 4px solid #1677ff;
    border-radius: 8px;
    background: color-mix(in srgb, #1677ff 8%, transparent);
  }

  .anw-embedding-readonly,
  .anw-embedding-metrics > div {
    display: grid;
    gap: 4px;
  }

  .anw-embedding-readonly strong,
  .anw-embedding-metrics dt,
  .anw-semantic-corpora strong {
    font-size: 12px;
    opacity: .72;
  }

  .anw-embedding-metrics {
    margin: 0;
  }

  .anw-embedding-metrics dd {
    margin: 0;
    overflow-wrap: anywhere;
  }

  .anw-embedding-secret-note,
  .anw-embedding-disclosure,
  .anw-embedding-muted {
    margin: 0;
    line-height: 1.65;
  }

  .anw-embedding-secret-note,
  .anw-embedding-muted {
    opacity: .76;
  }

  .anw-embedding-live:focus,
  .anw-embedding-confirm:focus,
  .anw-semantic-index-card [tabindex="-1"]:focus {
    outline: 3px solid color-mix(in srgb, #1677ff 34%, transparent);
    outline-offset: 2px;
  }

  .anw-semantic-corpora {
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .anw-semantic-corpora > li {
    display: grid;
    gap: 5px;
  }

  .anw-semantic-index-card__body {
    display: grid;
    gap: 14px;
  }

  .anw-embedding-confirm {
    display: grid;
    gap: 10px;
  }

  .anw-embedding-confirm label {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    cursor: pointer;
  }

  .anw-embedding-confirm input[type="checkbox"] {
    width: 18px;
    height: 18px;
    margin-top: 3px;
    flex: 0 0 auto;
  }

  @media (max-width: 720px) {
    .anw-embedding-page {
      padding: 12px;
    }

    .anw-embedding-grid,
    .anw-embedding-metrics,
    .anw-semantic-corpora,
    .anw-embedding-steps {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-embedding-hero {
      padding: 18px;
    }

    .anw-embedding-hero__tags {
      justify-content: flex-start;
    }

    .anw-embedding-credential {
      grid-template-columns: minmax(0, 1fr);
    }

    .anw-embedding-credential code {
      justify-self: stretch;
    }

    .anw-embedding-actions > *,
    .anw-embedding-inline-actions > * {
      width: 100%;
    }
  }
`;


export function ensureEmbeddingStyles(): void {
  if (typeof document === "undefined" || document.getElementById(EMBEDDING_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = EMBEDDING_STYLE_ID;
  style.dataset.pawappOwner = "ai-novel-world-2026";
  style.textContent = EMBEDDING_STYLES;
  document.head.appendChild(style);
}
