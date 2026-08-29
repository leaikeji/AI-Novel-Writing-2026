export const EMBEDDING_STYLE_ID = "ai-novel-world-2026-embedding-ui" as const;


export const EMBEDDING_STYLES = String.raw`
  .anw-embedding-page,
  .anw-semantic-index-card {
    min-width: 0;
    color: inherit;
  }

  .anw-embedding-page {
    display: grid;
    gap: 16px;
    width: min(1120px, 100%);
    margin: 0 auto;
    padding: 20px;
    overflow: auto;
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

  .anw-embedding-readonly,
  .anw-embedding-metrics > div,
  .anw-semantic-corpora > li,
  .anw-embedding-confirm {
    border: 1px solid color-mix(in srgb, currentColor 14%, transparent);
    border-radius: 10px;
    padding: 12px;
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
    .anw-semantic-corpora {
      grid-template-columns: minmax(0, 1fr);
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
