import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import type * as ChapterWorkflow from "./chapter-workflow";
import type * as RelationshipEditor from "./relationship-editor";
import type * as WorkbenchStudio from "./workbench-studio";


let chapter: typeof ChapterWorkflow;
let relationship: typeof RelationshipEditor;
let studio: typeof WorkbenchStudio;


function sorted(values: readonly string[]): string[] {
  return [...values].sort((left, right) => left.localeCompare(right));
}


beforeAll(async () => {
  const Component = Object.assign(() => null, {
    Group: () => null,
    TextArea: () => null,
  });
  const components = new Proxy({ Input: Component, Radio: Component }, {
    get: (target, key) => (
      key === "Input" ? target.Input : key === "Radio" ? target.Radio : Component
    ),
  });
  vi.stubGlobal("window", {
    QwenPaw: {
      host: {
        React: { createElement: () => null },
        ReactDOM: {},
        antd: components,
        antdIcons: new Proxy({}, { get: () => Component }),
      },
    },
  });
  [chapter, relationship, studio] = await Promise.all([
    import("./chapter-workflow"),
    import("./relationship-editor"),
    import("./workbench-studio"),
  ]);
});


afterAll(() => vi.unstubAllGlobals());


describe("selection edit page host contract", () => {
  it("keeps every chapter editor field assigned to a local review surface", () => {
    expect(sorted([
      chapter.CHAPTER_BODY_FIELD_ID,
      chapter.CHAPTER_TITLE_FIELD_ID,
      ...Object.values(chapter.CHAPTER_OUTLINE_FIELD_IDS),
    ])).toEqual(sorted([
      "chapter.body",
      "chapter.title",
      "chapter.outline",
      "chapter.outline.targetCharacters",
      "chapter.outline.expectation",
      "chapter.outline.forbidden",
      "chapter.outline.roles.required",
      "chapter.outline.roles.allowed",
      "chapter.outline.roles.contextOnly",
      "chapter.outline.roles.forbidden",
    ]));
  });

  it("assigns every static studio adapter to exactly one owning surface", () => {
    const assigned = Object.values(studio.STUDIO_SELECTION_REVIEW_FIELD_GROUPS).flat();
    expect(sorted(assigned)).toEqual(sorted(Object.values(studio.STUDIO_ASSISTANT_FIELD_IDS)));
    expect(new Set(assigned).size).toBe(assigned.length);
  });

  it("assigns all relationship adapters to the relationship modal surface", () => {
    expect(sorted(relationship.RELATIONSHIP_SELECTION_REVIEW_FIELD_IDS))
      .toEqual(sorted(Object.values(relationship.RELATIONSHIP_ASSISTANT_FIELD_IDS)));
  });
});
