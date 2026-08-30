const STYLE_ID = "anw-story-timeline-styles";

export function ensureStoryTimelineStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = `
    .anw-timeline-workspace { display: grid; gap: 16px; }
    .anw-timeline-header { display:flex; gap:12px; justify-content:space-between; align-items:flex-start; }
    .anw-timeline-muted { color: rgba(0,0,0,.58); margin: 4px 0 0; }
    .anw-timeline-list { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }
    .anw-timeline-list button { border:1px solid #d9d9d9; border-radius:8px; padding:8px 12px; background:#fff; cursor:pointer; }
    .anw-timeline-list button[aria-current='true'] { border-color:#1677ff; color:#1677ff; background:#e6f4ff; }
    .anw-timeline-grid { display:grid; grid-template-columns:minmax(220px,.8fr) minmax(300px,1.2fr); gap:16px; }
    .anw-instance-list { display:grid; gap:8px; }
    .anw-instance-list button { text-align:left; border:1px solid #eee; border-radius:8px; padding:10px; background:#fff; cursor:pointer; }
    .anw-instance-list button[aria-current='true'] { border-color:#1677ff; }
    .anw-timeline-fork-form { display:grid; gap:10px; }
    .anw-timeline-fork-form label { display:grid; gap:5px; font-weight:600; }
    .anw-timeline-fork-form input { width:100%; box-sizing:border-box; border:1px solid #d9d9d9; border-radius:6px; padding:8px; font:inherit; font-weight:400; }
    .anw-instance-summary { display:grid; gap:14px; }
    .anw-instance-summary dl { display:grid; gap:10px; margin:0; }
    .anw-instance-summary dl div { display:grid; grid-template-columns:minmax(72px,auto) 1fr; gap:12px; align-items:start; }
    .anw-instance-summary dt { color:rgba(0,0,0,.58); }
    .anw-instance-summary dd { margin:0; overflow-wrap:anywhere; }
    @media (max-width: 760px) { .anw-timeline-grid { grid-template-columns:1fr; } .anw-timeline-header { flex-direction:column; } }
  `;
  document.head.appendChild(style);
}
