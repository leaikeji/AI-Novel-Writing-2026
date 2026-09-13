import { describe, expect, it, vi } from "vitest";
import type { LibraryCheckHitRecord, LibraryCheckReportRecord } from "../types";
import {
  canCompleteLibraryCheck,
  createLibraryCheckDecisionPanel,
  persistLibraryCheckChoices,
  type LibraryCheckDecisionPanelProps,
} from "./candidate-adoption";
import { TEST_ANTD, createPrivateLibraryHarness, findAll, findButton, findByLabel, textContent } from "./test-harness";

function hits(count: number): LibraryCheckHitRecord[] {
  return Array.from({ length: count }, (_, index) => ({
    hit_id: `hit-${index + 1}`, entry_id: "entry-1", asset_id: "pack-1", asset_version_id: "pack-v1",
    action: "forbid", matched_text: "命运的齿轮", start_utf16: index * 20, end_utf16: index * 20 + 5,
    reason: "避免抽象套话，改写成具体动作。", count: 1,
  }));
}

function report(count = 9, offset = 0, limit = 200): LibraryCheckReportRecord {
  const all = hits(count);
  return {
    schema_version: "library-check/1", id: "report-1", version: 1, status: "complete",
    text_sha256: "a".repeat(64), rules_sha256: "b".repeat(64),
    hits: all.slice(offset, offset + limit), unresolved_forbid_hit_ids: all.map((hit) => hit.hit_id),
    scanned_rule_count: 1, omitted_rule_count: 0, visible_character_count: count * 20,
    offset, limit, total_hits: count, has_more: offset + limit < count, decisions: [],
  };
}

function store(initial: LibraryCheckReportRecord) {
  let current = initial;
  const all = hits(initial.total_hits);
  const loadPage = vi.fn(async (offset: number) => ({
    ...current, offset, hits: all.slice(offset, offset + current.limit), has_more: offset + current.limit < all.length,
  }));
  const saveDecisions = vi.fn(async (baseline: LibraryCheckReportRecord, ids: string[], skip: boolean) => {
    expect(baseline.version).toBe(current.version);
    expect(ids.length).toBeLessThanOrEqual(200);
    current = {
      ...current, version: current.version + 1,
      unresolved_forbid_hit_ids: current.unresolved_forbid_hit_ids.filter((id) => !ids.includes(id)),
      decisions: [
        ...(current.decisions ?? []),
        ...ids.map((hit_id) => ({ kind: "keep_once", hit_id })),
        ...(skip ? [{ kind: "skip_incomplete" }] : []),
      ],
    };
    return current;
  });
  return { loadPage, saveDecisions, current: () => current };
}

function panel(initial = report()) {
  const harness = createPrivateLibraryHarness();
  const Panel = createLibraryCheckDecisionPanel(harness.React, TEST_ANTD);
  const server = store(initial);
  const props: LibraryCheckDecisionPanelProps = {
    report: initial, ...server, onComplete: vi.fn(), onCancel: vi.fn(), onLocateHit: vi.fn(),
  };
  return { ...server, props, render: () => harness.render(Panel, props) };
}

async function settle() { for (let index = 0; index < 30; index += 1) await Promise.resolve(); }

function check(element: ReturnType<typeof findByLabel>, checked = true) {
  (element.props.onChange as (event: { target: { checked: boolean } }) => void)({ target: { checked } });
}

function click(element: ReturnType<typeof findButton>) { (element.props.onClick as () => void)(); }

describe("library check explicit decisions", () => {
  it("shows all nine visible hits, defaults to none and persists only the selected ninth hit", async () => {
    const view = panel();
    let tree = view.render();
    const choices = findAll(tree, (element) => element.type === "input" && element.props.type === "checkbox");
    expect(choices).toHaveLength(9);
    expect(choices.every((choice) => choice.props.checked === false)).toBe(true);
    expect(findButton(tree, "确认检查并继续").props.disabled).toBe(true);
    check(choices[8]!);
    expect(view.saveDecisions).not.toHaveBeenCalled();
    tree = view.render();
    click(findButton(tree, "保存所选决定"));
    await settle();
    tree = view.render();
    expect(view.saveDecisions).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ version: 1 }), ["hit-9"], false);
    expect(view.props.onComplete).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain("8 处禁用表达待处理");
    expect(textContent(tree)).toContain("所选保留决定已保存，尚未采用到正文");
  });

  it("does not grant unseen hits and retains unsaved selections across pages", async () => {
    const view = panel(report(201));
    let tree = view.render();
    check(findByLabel(tree, "本次保留第 1 处：命运的齿轮"));
    tree = view.render();
    click(findButton(tree, "下一页"));
    await settle();
    tree = view.render();
    expect(view.loadPage).toHaveBeenCalledWith(200);
    check(findByLabel(tree, "本次保留第 201 处：命运的齿轮"));
    tree = view.render();
    click(findButton(tree, "保存所选决定"));
    await settle();
    expect(view.saveDecisions).toHaveBeenCalledExactlyOnceWith(expect.anything(), ["hit-1", "hit-201"], false);
    expect(view.current().unresolved_forbid_hit_ids).toHaveLength(199);
    expect(view.props.onComplete).not.toHaveBeenCalled();
  });

  it("persists 201 explicitly chosen hits in two serial CAS batches and completes only on author click", async () => {
    const view = panel(report(201));
    let tree = view.render();
    for (const input of findAll(tree, (element) => element.type === "input")) check(input);
    tree = view.render();
    click(findButton(tree, "下一页"));
    await settle();
    tree = view.render();
    check(findByLabel(tree, "本次保留第 201 处：命运的齿轮"));
    tree = view.render();
    click(findButton(tree, "保存所选决定"));
    await settle();
    expect(view.saveDecisions.mock.calls.map((call) => [call[0].version, call[1].length])).toEqual([[1, 200], [2, 1]]);
    expect(view.props.onComplete).not.toHaveBeenCalled();
    tree = view.render();
    expect(findButton(tree, "确认检查并继续").props.disabled).toBe(false);
    click(findButton(tree, "确认检查并继续"));
    expect(view.props.onComplete).toHaveBeenCalledWith(expect.objectContaining({ version: 3, unresolved_forbid_hit_ids: [] }));
  });

  it("reconciles a lost reply without resending already saved choices", async () => {
    const initial = report(201);
    const server = store(initial);
    let first = true;
    const save = vi.fn(async (baseline: LibraryCheckReportRecord, ids: string[], skip: boolean) => {
      const next = await server.saveDecisions(baseline, ids, skip);
      if (first) { first = false; throw new Error("response lost"); }
      return next;
    });
    const result = await persistLibraryCheckChoices({
      report: initial, selectedHitIds: initial.unresolved_forbid_hit_ids, skipIncomplete: false,
      loadPage: server.loadPage, saveDecisions: save,
    });
    expect(save.mock.calls.map((call) => call[1].length)).toEqual([200, 1]);
    expect(server.loadPage).toHaveBeenCalledOnce();
    expect(result.version).toBe(3);
  });

  it("after a partial batch response loss resends only the remaining explicit choices", async () => {
    const initial = report();
    const server = store(initial);
    let first = true;
    const save = vi.fn(async (baseline: LibraryCheckReportRecord, ids: string[], skip: boolean) => {
      if (first) {
        first = false;
        await server.saveDecisions(baseline, ids.slice(0, 1), skip);
        throw new Error("reply unknown");
      }
      return server.saveDecisions(baseline, ids, skip);
    });
    await persistLibraryCheckChoices({
      report: initial, selectedHitIds: ["hit-2", "hit-8"], skipIncomplete: false,
      loadPage: server.loadPage, saveDecisions: save,
    });
    expect(save.mock.calls.map((call) => [call[0].version, call[1]])).toEqual([[1, ["hit-2", "hit-8"]], [2, ["hit-8"]]]);
    expect(server.current().unresolved_forbid_hit_ids).toHaveLength(7);
  });

  it("stops after a bounded retry and reconciles every uncertain write", async () => {
    const initial = report();
    const server = store(initial);
    const saveDecisions = vi.fn().mockRejectedValue(new Error("offline"));
    await expect(persistLibraryCheckChoices({
      report: initial, selectedHitIds: ["hit-2"], skipIncomplete: false,
      loadPage: server.loadPage, saveDecisions,
    })).rejects.toThrow("尚未保存");
    expect(saveDecisions).toHaveBeenCalledTimes(2);
    expect(server.loadPage).toHaveBeenCalledTimes(2);
  });

  it("does not retry author exceptions against a stale report after an uncertain write", async () => {
    const initial = report();
    const saveDecisions = vi.fn().mockRejectedValue(new Error("reply unknown"));
    const loadPage = vi.fn().mockResolvedValue({ ...initial, status: "stale" });
    await expect(persistLibraryCheckChoices({
      report: initial, selectedHitIds: ["hit-2"], skipIncomplete: false, loadPage, saveDecisions,
    })).rejects.toThrow("重新检查");
    expect(saveDecisions).toHaveBeenCalledOnce();
    expect(loadPage).toHaveBeenCalledOnce();
  });

  it("keeps saved batches after a later failure and resumes only missing author choices", async () => {
    const initial = report(201);
    const server = store(initial);
    let calls = 0;
    const save = vi.fn(async (baseline: LibraryCheckReportRecord, ids: string[], skip: boolean) => {
      calls += 1;
      if (calls > 1) throw new Error("offline");
      return server.saveDecisions(baseline, ids, skip);
    });
    await expect(persistLibraryCheckChoices({
      report: initial, selectedHitIds: initial.unresolved_forbid_hit_ids, skipIncomplete: false,
      loadPage: server.loadPage, saveDecisions: save,
    })).rejects.toThrow("尚未保存");
    expect(server.current().unresolved_forbid_hit_ids).toEqual(["hit-201"]);
    const fresh = await server.loadPage(200);
    const result = await persistLibraryCheckChoices({
      report: fresh, selectedHitIds: ["hit-201"], skipIncomplete: false,
      loadPage: server.loadPage, saveDecisions: server.saveDecisions,
    });
    expect(result.unresolved_forbid_hit_ids).toEqual([]);
    expect(server.saveDecisions.mock.lastCall?.[1]).toEqual(["hit-201"]);
  });

  it.each(["stale", "failed"] as const)("does not save or complete a %s report", async (status) => {
    const view = panel({ ...report(0), status });
    const tree = view.render();
    expect(findButton(tree, "保存所选决定").props.disabled).toBe(true);
    expect(findButton(tree, "确认检查并继续").props.disabled).toBe(true);
    click(findButton(tree, "保存所选决定"));
    click(findButton(tree, "确认检查并继续"));
    await settle();
    expect(view.saveDecisions).not.toHaveBeenCalled();
    expect(view.props.onComplete).not.toHaveBeenCalled();
  });

  it("requires an explicit saved skip for incomplete checks and still blocks unresolved forbids", async () => {
    const view = panel({ ...report(0), status: "incomplete", omitted_rule_count: 5 });
    let tree = view.render();
    expect(findButton(tree, "确认检查并继续").props.disabled).toBe(true);
    check(findByLabel(tree, "明确跳过本次未完成检查"));
    tree = view.render();
    expect(findButton(tree, "确认检查并继续").props.disabled).toBe(true);
    click(findButton(tree, "保存所选决定"));
    await settle();
    tree = view.render();
    expect(view.saveDecisions).toHaveBeenCalledWith(expect.anything(), [], true);
    expect(findButton(tree, "确认检查并继续").props.disabled).toBe(false);
    expect(canCompleteLibraryCheck({ ...view.current(), unresolved_forbid_hit_ids: ["hit-1"] })).toBe(false);
    expect(view.current().status).toBe("incomplete");
  });

  it("rejects a changed report while paging and does not retain old completion authority", async () => {
    const view = panel(report(0));
    view.loadPage.mockResolvedValueOnce({ ...report(0), id: "report-2" });
    let tree = view.render();
    click(findButton(tree, "重新读取报告"));
    await settle();
    tree = view.render();
    expect(findButton(tree, "确认检查并继续").props.disabled).toBe(true);
    click(findButton(tree, "确认检查并继续"));
    expect(view.props.onComplete).not.toHaveBeenCalled();
  });

  it("prevents double-submit synchronously and exposes location, page focus and Escape cancellation", async () => {
    const view = panel(report(201));
    let tree = view.render();
    const focus = vi.fn();
    const heading = findAll(tree, (element) => element.type === "h3")[0]!;
    (heading.props.ref as (node: { focus(): void }) => void)({ focus });
    click(findAll(tree, (element) => element.type === "button" && textContent(element) === "定位原句")[0]!);
    expect(view.props.onLocateHit).toHaveBeenCalledWith(expect.objectContaining({ hit_id: "hit-1" }));
    const next = findButton(tree, "下一页");
    click(next); click(next);
    await settle();
    expect(view.loadPage).toHaveBeenCalledOnce();
    expect(focus).toHaveBeenCalledOnce();
    tree = view.render();
    const preventDefault = vi.fn();
    (tree.props.onKeyDown as (event: { key: string; preventDefault(): void }) => void)({ key: "Escape", preventDefault });
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(view.props.onCancel).toHaveBeenCalledOnce();
  });

  it("restores persisted decisions from a fresh report without pretending unsaved choices persisted", () => {
    const initial = report(2);
    const view = panel({ ...initial, unresolved_forbid_hit_ids: ["hit-2"], decisions: [{ kind: "keep_once", hit_id: "hit-1" }] });
    const tree = view.render();
    const inputs = findAll(tree, (element) => element.type === "input");
    expect(inputs).toHaveLength(1);
    expect(inputs[0]!.props.checked).toBe(false);
    expect(textContent(tree)).toContain("1 处禁用表达待处理");
  });

  it("dispatches completion only once even before the modal has rerendered", () => {
    const view = panel(report(0));
    const button = findButton(view.render(), "确认检查并继续");
    click(button); click(button);
    expect(view.props.onComplete).toHaveBeenCalledOnce();
  });
});
