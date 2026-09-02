const STYLE_ID = "anw-retrieval-status-styles";


export function ensureRetrievalStatusStyles(): void {
  if (typeof document === "undefined" || document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .anw-retrieval-status { display: grid; gap: 4px; margin: 8px 0; padding: 10px 12px; border: 1px solid #d9d9d9; border-radius: 8px; background: #fafafa; }
    .anw-retrieval-status.is-success { border-color: #b7eb8f; background: #f6ffed; }
    .anw-retrieval-status.is-warning { border-color: #ffe58f; background: #fffbe6; }
    .anw-retrieval-status__title { font-weight: 600; }
    .anw-retrieval-status__description { color: rgba(0, 0, 0, .65); }
    .anw-retrieval-status__link { justify-self: start; color: #1677ff; text-decoration: none; }
    .anw-retrieval-status__link:focus-visible { outline: 2px solid #1677ff; outline-offset: 2px; border-radius: 2px; }
  `;
  document.head.appendChild(style);
}
