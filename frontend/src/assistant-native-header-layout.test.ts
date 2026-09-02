import { describe, expect, it } from "vitest";

import { ensureNovelStyles } from "./styles";


describe("native assistant header containment", () => {
  it("lets a long native session title shrink before header actions leave the PawApp pane", () => {
    const source = ensureNovelStyles.toString();

    expect(source).toContain(
      ".anw-assistant-pane .qwenpaw-chat-anywhere-layout-right-header { min-width:0; overflow:hidden; }",
    );
    expect(source).toContain(
      ".anw-assistant-pane .qwenpaw-chat-anywhere-default-header-right { width:100%; min-width:0; overflow:hidden; }",
    );
    expect(source).toContain(
      ".anw-assistant-pane .qwenpaw-chat-anywhere-default-header-right > :first-child { min-width:0; flex:1 1 0; overflow:hidden; }",
    );
  });

  it("shrinks the project-directory control before the native send action is clipped", () => {
    const source = ensureNovelStyles.toString();

    expect(source).toContain(
      ".anw-assistant-pane .qwenpaw-sender-actions-list { width:100%; min-width:0; }",
    );
    expect(source).toContain(
      ".anw-assistant-pane .qwenpaw-sender-actions-list > :nth-child(2) { min-width:0; flex:1 1 0; }",
    );
    expect(source).toContain(
      ".anw-assistant-pane .qwenpaw-sender-actions-list > :nth-child(2) > :nth-child(2) { min-width:40px; flex:1 1 0; }",
    );
  });
});
