import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { NovelAssistantContextRuntime } from "./assistant-context-runtime";
import type { AIApplyMeta } from "./assistant-fields";
import {
  buildStoryLedgerAssistantContextFromWorkspace,
  STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS,
} from "./story-ledger";
import type * as StudioContext from "./workbench-studio";


let studio: typeof StudioContext;


const NOVEL = { id: "novel-1", title: "潮声替我说晚安" };


function runtime(): NovelAssistantContextRuntime {
  const value = new NovelAssistantContextRuntime();
  value.setHostBinding("ai-novel-writer", "session-1");
  return value;
}


beforeAll(async () => {
  const Component = Object.assign(() => null, { TextArea: () => null });
  const components = new Proxy({ Input: Component }, {
    get: (target, key) => key === "Input" ? target.Input : Component,
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
  studio = await import("./workbench-studio");
});


afterAll(() => vi.unstubAllGlobals());


describe("workbench studio assistant context integration", () => {
  it("rejects stale or aborted whole-domain loads before they can cross novels", () => {
    const controller = new AbortController();
    expect(studio.studioDomainLoadIsCurrent(4, 4, controller.signal)).toBe(true);
    expect(studio.studioDomainLoadIsCurrent(3, 4, controller.signal)).toBe(false);
    controller.abort();
    expect(studio.studioDomainLoadIsCurrent(4, 4, controller.signal)).toBe(false);
  });

  it("reserves the actually visible studio width when the assistant overlays", () => {
    expect(studio.studioOverlayVisibleWidth({
      containerWidth: 768,
      assistantWidth: 450,
      mainWidth: 768,
      mainMinWidth: 640,
      density: "constrained",
      assistantOverlay: true,
      recommendedNavigationWidth: 220,
    })).toBe(318);
    expect(studio.studioOverlayVisibleWidth({
      containerWidth: 1_267,
      assistantWidth: 520,
      mainWidth: 747,
      mainMinWidth: 720,
      density: "constrained",
      assistantOverlay: false,
      recommendedNavigationWidth: 240,
    })).toBeNull();
  });

  it("restores the internal ledger section and its frozen route filters", () => {
    const factId = "11111111-1111-4111-8111-111111111111";
    const timelineId = "22222222-2222-4222-8222-222222222222";
    const sourceDocumentId = "33333333-3333-4333-8333-333333333333";

    expect(studio.studioSectionFromSearch("", "chapters", "ledger")).toBe("ledger");
    expect(studio.studioSectionFromSearch("?section=outline", "outline", "ledger"))
      .toBe("outline");
    expect(studio.studioSectionFromSearch("?section=ledger", "chapters"))
      .toBe("ledger");
    expect(studio.studioLedgerFiltersFromRoute({
      factType: "character_state",
      effectiveState: "current",
      health: "conflict",
      sourceDocumentId,
    })).toEqual({
      factTypes: ["character_state"],
      effectiveState: "current",
      health: "conflict",
      sourceDocumentId,
    });
    expect(studio.studioLedgerRouteFromContext({
      snapshotToken: null,
      timeline: {
        mode: "multiple",
        timeline_id: timelineId,
        timeline_name: "分支",
        narrative_cutoff: null,
      },
      filters: {
        factTypes: ["character_state"],
        effectiveState: "current",
        health: "conflict",
        sourceDocumentId,
      },
      summary: null,
      selectedFactId: factId,
      selected: null,
    })).toEqual({
      factId,
      timelineId,
      factType: "character_state",
      effectiveState: "current",
      health: "conflict",
      sourceDocumentId,
    });
  });

  it("publishes all frozen background views, including a body-free ledger payload", () => {
    const contextRuntime = runtime();
    const cases = [
      ["outline", "novel-outline", "outline"],
      ["roles", "character-list", "novel"],
      ["clues", "clue-list", "novel"],
      ["settings", "novel-settings", "setting"],
    ] as const;

    for (const [section, view, entityType] of cases) {
      const envelope = studio.studioAssistantPageEnvelope(NOVEL, section);
      expect(envelope).toMatchObject({
        agentId: "ai-novel-writer",
        novel: NOVEL,
        page: { section, view },
        entity: { type: entityType, id: NOVEL.id },
      });
      const mounted = studio.mountStudioAssistantScope(
        contextRuntime,
        {
          id: `test:page:${section}`,
          kind: "page",
          envelope: envelope!,
        },
      );
      expect(contextRuntime.getStatus()).toMatchObject({
        scopeKind: "page",
        section,
        view,
        fieldCount: 0,
      });
      mounted.dispose();
    }

    expect(studio.studioAssistantPageEnvelope(NOVEL, "chapters")).toBeNull();
    expect(studio.studioAssistantPageEnvelope(NOVEL, "reading")).toBeNull();
    expect(studio.studioAssistantPageEnvelope(NOVEL, "roles", "graph")).toBeNull();
    expect(studio.studioAssistantPageEnvelope(NOVEL, "ledger")).toBeNull();

    const timeline = {
      mode: "single",
      timeline_id: "timeline-1",
      timeline_name: "主线",
      narrative_cutoff: null,
    } as const;
    const ledger = buildStoryLedgerAssistantContextFromWorkspace({
      novel: NOVEL,
      context: {
        snapshotToken: "ledger-snapshot/1:novel-1:9",
        timeline,
        filters: { factTypes: ["character_state"], reviewOnly: true },
        summary: {
          schema_version: "story-ledger-summary/1",
          novel_id: NOVEL.id,
          ledger_snapshot_token: "ledger-snapshot/1:novel-1:9",
          story_ledger_version: 9,
          timeline,
          filter_sha256: "a".repeat(64),
          total: 1,
          by_fact_type: { character_state: 1 },
          by_effective_state: { current: 1 },
          by_health: { ok: 1 },
          review_required: 0,
        },
        selectedFactId: "fact-1",
        selected: {
          factId: "fact-1",
          factType: "character_state",
          timelineId: "timeline-1",
          dimension: "location",
          eventKind: "state",
          effectiveState: "current",
          health: "ok",
          source: {
            source_document_id: "document-1",
            document_title: "第一章",
            document_position: 1,
            source_revision_id: "revision-1",
            revision_number: 2,
            revision_is_current: true,
            binding_state: "current",
            commit_batch_id: null,
            evidence_available: true,
          },
        },
      },
    });
    const ledgerEnvelope = studio.studioAssistantPageEnvelope(
      NOVEL,
      "ledger",
      "list",
      ledger!,
    );
    const ledgerPage = studio.mountStudioAssistantScope(contextRuntime, {
      id: "test:page:ledger",
      kind: "page",
      envelope: ledgerEnvelope!,
    });
    const captured = contextRuntime.capture();
    const serialized = captured?.serialized ?? "";
    expect(captured?.context).toMatchObject({
      page: { section: "ledger", view: "story-ledger" },
      ledger: {
        selected_fact_id: "fact-1",
        selected_fact: { id: "fact-1", object_text: "" },
      },
    });
    expect(captured?.context.ledger?.budget.used_code_points)
      .toBeLessThanOrEqual(STORY_LEDGER_ASSISTANT_CONTEXT_MAX_CODE_POINTS);
    expect(serialized).not.toContain("source_excerpt");
    expect(serialized).not.toContain("details");
    expect(serialized).not.toContain("完整章节");
    ledgerPage.dispose();

    expect(studio.WORKBENCH_SECTIONS).toEqual([
      "chapters",
      "outline",
      "roles",
      "clues",
      "settings",
      "reading",
      "ledger",
    ]);
  });

  it("overlays a modal, applies through live controlled state, stays dirty, and restores the page", async () => {
    const contextRuntime = runtime();
    const pageEnvelope = studio.studioAssistantPageEnvelope(NOVEL, "roles");
    const page = studio.mountStudioAssistantScope(
      contextRuntime,
      {
        id: "test:page:roles",
        kind: "page",
        envelope: pageEnvelope!,
      },
    );
    const state = { value: "苏晚", dirty: false };
    const originalSaveButton = vi.fn();
    const focus = vi.fn();
    const disposed = vi.fn();
    const fieldId = studio.STUDIO_ASSISTANT_FIELD_IDS.characterName;
    const modal = studio.mountStudioAssistantScope(
      contextRuntime,
      {
        id: "test:modal:character",
        kind: "modal",
        envelope: {
          ...pageEnvelope!,
          page: { ...pageEnvelope!.page, modal: "character-editor" },
          entity: { type: "character", id: "character-1", title: state.value },
        },
      },
      [{
        id: fieldId,
        label: "角色姓名",
        getValue: () => state.value,
        getDirty: () => state.dirty,
        applyDraftValue: (nextValue) => { state.value = nextValue; },
        markDirty: () => { state.dirty = true; },
        focus,
        dispose: disposed,
      }],
    );

    expect(contextRuntime.getStatus()).toMatchObject({
      scopeKind: "modal",
      view: "character-list",
      modal: "character-editor",
      fieldCount: 1,
      dirtyFieldCount: 0,
    });
    const adapter = modal.adapters.get(fieldId)!;
    const sourceValueSha256 = await studio.hashStudioAssistantField(state.value);
    const meta: AIApplyMeta = {
      transactionId: "transaction-1",
      agentId: "ai-novel-writer",
      sessionId: "session-1",
      operation: "replace",
      sourceValueSha256,
      appliedAt: "2026-08-25T10:00:00.000Z",
    };
    const receipt = await adapter.applyValueWithReceipt("苏晚·潮生", meta);

    expect(sourceValueSha256).toBe(
      "d65c66a7267504a28033b6d144ea681cb6e145c5faec4c555cb27878d18fa95b",
    );
    expect(receipt).toMatchObject({
      fieldId,
      persistence: "explicit-save",
      saveRequested: false,
      before: { value: "苏晚", dirty: false },
      after: { value: "苏晚·潮生", dirty: true },
    });
    expect(state).toEqual({ value: "苏晚·潮生", dirty: true });
    expect(originalSaveButton).not.toHaveBeenCalled();
    expect(contextRuntime.getStatus().dirtyFieldCount).toBe(1);
    expect(contextRuntime.capture()?.context.editing?.fields).toEqual([
      expect.objectContaining({
        id: fieldId,
        value: "苏晚·潮生",
        dirty: true,
        persistence: "explicit-save",
      }),
    ]);

    adapter.focus();
    expect(focus).toHaveBeenCalledTimes(1);
    modal.dispose();
    expect(disposed).toHaveBeenCalledTimes(1);
    expect(() => adapter.getValue()).toThrow("disposed");
    expect(contextRuntime.getStatus()).toMatchObject({
      scopeKind: "page",
      section: "roles",
      view: "character-list",
      fieldCount: 0,
    });
    page.dispose();
    expect(contextRuntime.getStatus().active).toBe(false);
  });

  it("keeps every registered studio field id stable and unique", () => {
    const ids = Object.values(studio.STUDIO_ASSISTANT_FIELD_IDS);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual([
      "outline.targetChapterCount",
      "outline.background",
      "outline.plot",
      "outline.highlight",
      "outline.character.roleType",
      "outline.character.name",
      "outline.character.gender",
      "outline.character.age",
      "outline.character.personality",
      "outline.character.identity",
      "outline.character.description",
      "character.roleType",
      "character.name",
      "character.gender",
      "character.age",
      "character.identity",
      "character.personality",
      "character.description",
      "storyline.storylineType",
      "storyline.title",
      "storyline.description",
      "storyline.status",
      "storyline.progress",
      "foreshadow.title",
      "foreshadow.content",
      "foreshadow.latestProgress",
      "foreshadow.status",
      "settings.templateName",
      "settings.genre",
      "settings.subgenre",
      "settings.idea",
    ]);
  });
});
