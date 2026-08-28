import { describe, expect, it, vi } from "vitest";

import {
  NARRATION_REVIEW_TAXONOMY_VERSION,
  NARRATION_SCRIPT_REVIEW_API_VERSION,
  parseScriptReviewResource,
  type ScriptReviewResource,
} from "./script-contracts";
import {
  deriveChapterNarrationState,
  type ChapterNarrationStateInput,
} from "./chapter-narration-state";
import {
  EDITION_HISTORY_CONTRACT_VERSION,
  parseDocumentEditionHistory,
} from "./edition-history";
import {
  createScriptReviewPanel,
  type ScriptReviewPanelApi,
  type ScriptReviewPanelProps,
  type ScriptReviewReactRuntime,
} from "./script-review-panel";


interface FakeElement {
  readonly type: unknown;
  readonly props: Record<string, unknown>;
  readonly children: readonly unknown[];
}


interface EffectRecord {
  readonly dependencies: readonly unknown[];
  cleanup?: () => void;
}


function isElement(value: unknown): value is FakeElement {
  return typeof value === "object" && value !== null && "type" in value && "props" in value;
}


function textContent(root: unknown): string {
  if (typeof root === "string" || typeof root === "number") return String(root);
  if (Array.isArray(root)) return root.map(textContent).join("");
  if (!isElement(root)) return "";
  return root.children.map(textContent).join("");
}


function findAll(root: unknown, predicate: (element: FakeElement) => boolean): FakeElement[] {
  if (Array.isArray(root)) return root.flatMap((child) => findAll(child, predicate));
  if (!isElement(root)) return [];
  return [
    ...(predicate(root) ? [root] : []),
    ...root.children.flatMap((child) => findAll(child, predicate)),
  ];
}


function button(root: unknown, label: string): FakeElement {
  const found = findAll(
    root,
    (element) => element.type === "button" && textContent(element) === label,
  )[0];
  if (!found) throw new Error(`button not found: ${label}`);
  return found;
}


function sameDependencies(
  left: readonly unknown[] | undefined,
  right: readonly unknown[],
): boolean {
  return Boolean(left
    && left.length === right.length
    && left.every((item, index) => Object.is(item, right[index])));
}


function createReactHarness() {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const effects: Array<EffectRecord | undefined> = [];
  let pendingEffects: Array<{
    index: number;
    effect: () => void | (() => void);
    dependencies: readonly unknown[];
  }> = [];
  let stateIndex = 0;
  let refIndex = 0;
  let effectIndex = 0;
  const React: ScriptReviewReactRuntime = {
    createElement(type, props, ...children): FakeElement {
      return { type, props: props ?? {}, children };
    },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const index = stateIndex++;
      if (!(index in states)) {
        states[index] = typeof initial === "function" ? (initial as () => T)() : initial;
      }
      return [
        states[index] as T,
        (next) => {
          states[index] = typeof next === "function"
            ? (next as (current: T) => T)(states[index] as T)
            : next;
        },
      ];
    },
    useRef<T>(initial: T): { current: T } {
      const index = refIndex++;
      if (!refs[index]) refs[index] = { current: initial };
      return refs[index] as { current: T };
    },
    useEffect(effect, dependencies): void {
      const index = effectIndex++;
      if (sameDependencies(effects[index]?.dependencies, dependencies)) return;
      pendingEffects.push({ index, effect, dependencies: [...dependencies] });
    },
  };
  return {
    React,
    render<Props>(Component: (props: Props) => unknown, props: Props): FakeElement {
      stateIndex = 0;
      refIndex = 0;
      effectIndex = 0;
      pendingEffects = [];
      return Component(props) as FakeElement;
    },
    commitEffects(): void {
      const pending = pendingEffects;
      pendingEffects = [];
      for (const item of pending) {
        effects[item.index]?.cleanup?.();
        const cleanup = item.effect();
        effects[item.index] = {
          dependencies: item.dependencies,
          cleanup: typeof cleanup === "function" ? cleanup : undefined,
        };
      }
    },
    unmount(): void {
      for (const effect of effects) effect?.cleanup?.();
    },
  };
}


const DOCUMENT = "20000000-0000-4000-8000-000000000001";
const NOVEL = "20000000-0000-4000-8000-000000000002";
const EDITION = "20000000-0000-4000-8000-000000000003";
const REVISION = "20000000-0000-4000-8000-000000000004";
const SCRIPT = "20000000-0000-4000-8000-000000000005";
const SCRIPT_VERSION = "20000000-0000-4000-8000-000000000006";
const REQUEST = "20000000-0000-4000-8000-000000000007";
const SEGMENT = "20000000-0000-4000-8000-000000000008";
const CHARACTER = "20000000-0000-4000-8000-000000000009";
const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);


function review(): ScriptReviewResource {
  return parseScriptReviewResource({
    contract_version: NARRATION_SCRIPT_REVIEW_API_VERSION,
    taxonomy_version: NARRATION_REVIEW_TAXONOMY_VERSION,
    script_id: SCRIPT,
    script_version_id: SCRIPT_VERSION,
    novel_id: NOVEL,
    document_id: DOCUMENT,
    revision_id: REVISION,
    source_content_hash: SHA_A,
    immutable_hash: "c".repeat(64),
    version_number: 1,
    state: "review_required",
    effective_policy: "always_review",
    source_status: "working_copy_diverged",
    warning_count: 0,
    blocker_count: 0,
    allowed_actions: [
      "approve", "edit_segment", "reanalyze_segments", "continue_snapshot", "reanalyze_latest",
    ],
    segments: [{
      segment_id: SEGMENT,
      ordinal: 0,
      segment_kind: "dialogue",
      source_block_key: `sb1_${"d".repeat(64)}`,
      source_start_utf16: 0,
      source_end_utf16: 4,
      source_text: "“旧稿台词”",
      spoken_text: "旧稿台词",
      local_hash: "e".repeat(64),
      speaker_kind: "character",
      speaker_label: "林晚",
      character_id: CHARACTER,
      anonymous_speaker_id: null,
      confidence: "high",
      casting_state: "resolved",
      issue_codes: [],
      editable: true,
    }],
    issues: [],
    approval: null,
  });
}


function chapterInput(phase: "playing" | "paused" | "ended" = "playing"): ChapterNarrationStateInput {
  const history = parseDocumentEditionHistory({
    contract_version: EDITION_HISTORY_CONTRACT_VERSION,
    document_id: DOCUMENT,
    pointer_version: 2,
    current_edition_id: EDITION,
    working_copy_content_hash: SHA_A,
    working_copy_draft_version: 6,
    editions: [{
      edition_id: EDITION,
      request_id: REQUEST,
      source_revision_id: REVISION,
      source_content_hash: SHA_A,
      edition_fingerprint: "f".repeat(64),
      state: "ready",
      created_at: "2026-08-27T12:00:00Z",
      manifest_revision: 1,
      manifest_etag: `"${"1".repeat(64)}"`,
      ready_segment_count: 1,
      total_segment_count: 1,
      is_current: true,
      source_status: "current",
      rights_available: true,
      playable: true,
      default_start_ready: true,
      resume_available: true,
      switch_allowed: true,
    }],
  });
  return {
    documentId: DOCUMENT,
    generation: 3,
    history,
    workingCopy: {
      documentId: DOCUMENT,
      generation: 3,
      draftVersion: 6,
      contentHash: SHA_B,
      saveState: "dirty",
    },
    reviewOpen: true,
    reviewSource: { revisionId: REVISION, contentHash: SHA_A },
    playback: {
      editionId: EDITION,
      phase,
      currentSegmentId: SEGMENT,
      currentOrdinal: 0,
      offsetMs: 420,
      durationMs: 1200,
      subtitle: {
        editionId: EDITION,
        segmentId: SEGMENT,
        ordinal: 0,
        speakerLabel: "林晚",
        sourceText: "“旧稿台词”",
        spokenText: "旧稿台词",
      },
    },
  };
}


function api(): ScriptReviewPanelApi {
  return {
    approve: vi.fn(async () => review()),
    reanalyzeSegments: vi.fn(async () => review()),
  };
}


describe("script review and player coexistence", () => {
  it("renders one compact old-draft player and leaves the full player hidden", () => {
    const state = deriveChapterNarrationState(chapterInput());
    const toggle = vi.fn();
    const openOldDraft = vi.fn();
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const tree = harness.render(Panel, {
      review: review(),
      requestId: REQUEST,
      requestVersion: 4,
      compactPlayer: {
        ...state.compactPlayer!,
        onTogglePlayback: toggle,
        onOpenOldDraft: openOldDraft,
      },
    });

    expect(state.fullPlayerVisible).toBe(false);
    expect(findAll(tree, (element) => element.props["data-player-layout"] === "compact")).toHaveLength(1);
    expect(textContent(tree)).toContain("旧稿朗读");
    expect(textContent(tree)).toContain("说话人：林晚");
    expect(tree.props["data-min-viewport"]).toBe("1920x1080");
    const progress = findAll(tree, (element) => element.type === "progress")[0];
    expect(progress.props).toMatchObject({ value: 420, max: 1200 });
    expect(toggle).not.toHaveBeenCalled();

    (button(tree, "暂停朗读").props.onClick as () => void)();
    (button(tree, "查看不可变旧稿").props.onClick as () => void)();
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(openOldDraft).toHaveBeenCalledTimes(1);
  });

  it("does not pause audio when the review panel mounts, closes, or unmounts", () => {
    const state = deriveChapterNarrationState(chapterInput("playing"));
    const toggle = vi.fn();
    const closed = vi.fn();
    const restored = vi.fn();
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const tree = harness.render(Panel, {
      review: review(),
      requestId: REQUEST,
      requestVersion: 4,
      compactPlayer: { ...state.compactPlayer!, onTogglePlayback: toggle },
      onClose: closed,
      triggerRef: { current: { focus: restored } },
    });

    harness.commitEffects();
    expect(toggle).not.toHaveBeenCalled();
    (button(tree, "关闭").props.onClick as () => void)();
    harness.unmount();
    expect(toggle).not.toHaveBeenCalled();
    expect(closed).toHaveBeenCalledTimes(1);
    expect(restored).toHaveBeenCalledTimes(1);
  });

  it("uses a resume label for a paused compact player", () => {
    const state = deriveChapterNarrationState(chapterInput("paused"));
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const tree = harness.render(Panel, {
      review: review(),
      requestId: REQUEST,
      requestVersion: 4,
      compactPlayer: { ...state.compactPlayer!, onTogglePlayback: vi.fn() },
    });
    expect(button(tree, "继续朗读").props["aria-label"]).toBe("继续朗读");
  });

  it("keeps the T3 review panel player-free when no active session exists", () => {
    const state = deriveChapterNarrationState(chapterInput("ended"));
    const harness = createReactHarness();
    const Panel = createScriptReviewPanel(harness.React, api());
    const props: ScriptReviewPanelProps = {
      review: review(),
      requestId: REQUEST,
      requestVersion: 4,
    };
    const tree = harness.render(Panel, props);

    expect(state.compactPlayer).toBeNull();
    expect(findAll(tree, (element) => element.props["data-player-layout"] === "compact")).toHaveLength(0);
    expect(textContent(tree)).toContain("这份复核绑定旧正文快照");
    expect(button(tree, "确认并冻结脚本").props.disabled).toBe(true);
  });
});
