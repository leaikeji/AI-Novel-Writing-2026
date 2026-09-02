import { describe, expect, it } from "vitest";

import { CHARACTER_WORKSPACE_CSS } from "./styles";

function channel(value: string): number {
  const normalized = Number.parseInt(value, 16) / 255;
  return normalized <= 0.04045
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const normalized = hex.replace("#", "");
  return (
    0.2126 * channel(normalized.slice(0, 2))
    + 0.7152 * channel(normalized.slice(2, 4))
    + 0.0722 * channel(normalized.slice(4, 6))
  );
}

function contrast(left: string, right: string): number {
  const lighter = Math.max(luminance(left), luminance(right));
  const darker = Math.min(luminance(left), luminance(right));
  return (lighter + 0.05) / (darker + 0.05);
}

describe("character workspace desktop layout contract", () => {
  it("keeps the approved 1240px dialog and gives labeled fact cards a narrow-screen fallback", () => {
    expect(CHARACTER_WORKSPACE_CSS).toContain("width: min(1240px, calc(100vw - 64px))");
    expect(CHARACTER_WORKSPACE_CSS).toContain("grid-template-columns: repeat(12");
    expect(CHARACTER_WORKSPACE_CSS).toContain("anw-character-state-layout");
    expect(CHARACTER_WORKSPACE_CSS).toContain("anw-character-fact-card");
    expect(CHARACTER_WORKSPACE_CSS).not.toContain("anw-character-fact-table-row");
    expect(CHARACTER_WORKSPACE_CSS).toContain("@media (max-width: 640px)");
    expect(CHARACTER_WORKSPACE_CSS).toContain("max-height: calc(100dvh - 48px)");
    expect(CHARACTER_WORKSPACE_CSS).toContain("position: sticky");
    expect(CHARACTER_WORKSPACE_CSS).toContain("anw-character-workspace-tabs { display: flex; flex: 0 0 auto");
    expect(CHARACTER_WORKSPACE_CSS).toContain(":focus-visible");
    expect(CHARACTER_WORKSPACE_CSS).toContain("grid-column:1 / -1");
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-accent: #ff7043");
  });

  it("establishes a local light theme without leaking color-scheme to the host", () => {
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-surface: #ffffff");
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-surface-muted: #f8fafc");
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-text: #1f2937");
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-text-strong: #252a32");
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-text-muted: #64748b");
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-border: #e5e7eb");
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-workspace-dialog \{[\s\S]*?color-scheme: light;/,
    );
    expect(CHARACTER_WORKSPACE_CSS).not.toMatch(/(?:^|\n)\s*(?::root|html|body)\s*\{[^}]*color-scheme/);
    expect(CHARACTER_WORKSPACE_CSS).toContain("color: var(--anw-character-text);\n  background: var(--anw-character-surface);");
    expect(CHARACTER_WORKSPACE_CSS).not.toContain("var(--ant-color");
  });

  it("gives native select and option controls explicit readable colors", () => {
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-fact-filters select \{[^}]*min-height:34px;[^}]*color:var\(--anw-character-text\);[^}]*background:var\(--anw-character-surface\);/,
    );
    expect(CHARACTER_WORKSPACE_CSS).toContain(
      ".anw-character-fact-filters option { color:var(--anw-character-text); background:var(--anw-character-surface); }",
    );
    expect(CHARACTER_WORKSPACE_CSS).toContain(
      ".anw-character-fact-filters select:hover { border-color:var(--anw-character-focus); }",
    );
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-fact-filters select:disabled \{[^}]*color:var\(--anw-character-text-muted\);[^}]*background:var\(--anw-character-surface-muted\);[^}]*opacity:1;/,
    );
  });

  it("keeps drawer headers, close controls, content and footers on the local surface", () => {
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-drawer,.anw-character-source-viewer \{[^}]*width:480px;[^}]*color:var\(--anw-character-text\);[^}]*background:var\(--anw-character-surface\);/,
    );
    expect(CHARACTER_WORKSPACE_CSS).toContain(
      ".anw-character-source-viewer { width:min(720px,72%); }",
    );
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-workspace-dialog \.anw-character-drawer > header h3,[^}]*\{ color:var\(--anw-character-text-strong\); \}/,
    );
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-workspace-dialog \.anw-character-drawer > header button,[^}]*\{[^}]*width:36px;[^}]*height:36px;[^}]*color:var\(--anw-character-text-strong\);[^}]*background:transparent;/,
    );
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-drawer-body,.anw-character-source-body \{[^}]*color:var\(--anw-character-text\);[^}]*background:var\(--anw-character-surface\);/,
    );
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-drawer > footer \{[^}]*color:var\(--anw-character-text\);[^}]*background:var\(--anw-character-surface\);/,
    );
  });

  it("does not let the generic button rule swallow semantic button colors", () => {
    expect(CHARACTER_WORKSPACE_CSS).toContain(
      ".anw-character-workspace-dialog button { font: inherit; }",
    );
    expect(CHARACTER_WORKSPACE_CSS).not.toMatch(
      /\.anw-character-workspace-dialog button \{[^}]*color:/,
    );
    expect(CHARACTER_WORKSPACE_CSS).toContain(
      ".anw-character-workspace-button--primary { border-color: var(--anw-character-accent); background: var(--anw-character-accent); color: #fff; }",
    );
    expect(CHARACTER_WORKSPACE_CSS).toContain(
      ".anw-character-workspace-button--danger { border-color:var(--anw-character-danger); color:var(--anw-character-danger); background:var(--anw-character-surface); }",
    );
    expect(CHARACTER_WORKSPACE_CSS).toContain(
      ".anw-character-link-button,.anw-character-row-actions button,.anw-character-action-menu summary { border:0; padding:4px 6px; color:#c2411d; background:transparent; cursor:pointer; font-weight:650; }",
    );
    expect(CHARACTER_WORKSPACE_CSS).toMatch(
      /\.anw-character-workspace-dialog \.anw-character-drawer > header button,[^}]*\{[^}]*color:var\(--anw-character-text-strong\);/,
    );
  });

  it("uses non-transparent focus and control colors that meet the scoped contrast gates", () => {
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-control-border: #7c8798");
    expect(CHARACTER_WORKSPACE_CSS).toContain("--anw-character-focus: #c2411d");
    expect(CHARACTER_WORKSPACE_CSS).toContain(
      ".anw-character-workspace-dialog :focus-visible { outline: 3px solid var(--anw-character-focus); outline-offset: 2px; }",
    );
    expect(contrast("#1f2937", "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#64748b", "#ffffff")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("#7c8798", "#ffffff")).toBeGreaterThanOrEqual(3);
    expect(contrast("#c2411d", "#ffffff")).toBeGreaterThanOrEqual(3);
  });
});
