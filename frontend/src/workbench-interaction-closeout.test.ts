// @ts-expect-error Vitest executes this contract test in Node; the browser bundle omits Node types.
import { readFileSync } from "node:fs";

import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { templateFieldMeta } from "./template-field-meta";
import type * as Studio from "./workbench-studio";


let studio: typeof Studio;


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


function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}


function searchHarness() {
  const open = vi.fn<(value: boolean) => void>();
  const busy = vi.fn<(value: boolean) => void>();
  const results = vi.fn<(value: readonly string[]) => void>();
  const error = vi.fn<(reason: unknown) => void>();
  const controller = new studio.WorkbenchSearchController<string>({
    onOpenChange: open,
    onBusyChange: busy,
    onResults: results,
    onError: error,
  });
  return { controller, open, busy, results, error };
}


describe("workbench interaction closeout", () => {
  const source = readFileSync(new URL("./workbench-studio.ts", import.meta.url), "utf8");

  it("uses the shared author-facing setting labels while preserving custom keys", () => {
    expect(templateFieldMeta("core_conflict").label).toBe("核心冲突");
    expect(templateFieldMeta("weather_pressure").label).toBe("自定义字段（weather_pressure）");
    expect(source).toContain('import { templateFieldMeta } from "./template-field-meta";');
    expect(source).toContain("templateFieldMeta(key).label");
    expect(source).toContain('!key.startsWith("cover_")');
    const nested = { pressure: 2 };
    const entries = studio.authorFacingTemplateEntries({
      core_conflict: "家园与真相",
      weather_pressure: "暴雨将至",
      zero_value: 0,
      false_value: false,
      null_value: null,
      nested_value: nested,
      cover_prompt: "internal",
    });
    expect(entries).toEqual([
      ["core_conflict", "家园与真相"],
      ["weather_pressure", "暴雨将至"],
      ["zero_value", 0],
      ["false_value", false],
      ["null_value", null],
      ["nested_value", nested],
    ]);
    expect(entries[5][1]).toBe(nested);
    expect(studio.settingsTemplateDisplayValue(0)).toBe("0");
    expect(studio.settingsTemplateDisplayValue(false)).toBe("false");
    expect(studio.settingsTemplateDisplayValue(null)).toBe("null");
    expect(studio.settingsTemplateDisplayValue(nested)).toBe('{\n  "pressure": 2\n}');
    expect(studio.settingsTemplateValueIsWritable("0")).toBe(true);
    for (const value of [null, 0, false, nested]) {
      expect(studio.settingsTemplateValueIsWritable(value)).toBe(false);
    }
    expect(source).toContain("const data: Record<string, unknown> = { ...(novel.template_data || {}) };");
    expect(source).toContain("value: settingsTemplateDisplayValue(rawValue)");
  });

  it("matches the backend encoded assistant-field suffix boundary", () => {
    expect(source).toContain("readOnly: !writable");
    expect(source).toContain('"aria-invalid": writable ? undefined : true');
    expect(source).toContain("不能在修复前保存");
    expect(source).toContain("fieldId.length <= 200");
    expect(studio.settingsTemplateKeyIsWritable("core_conflict")).toBe(true);
    expect(studio.settingsTemplateKeyIsWritable("")).toBe(false);
    expect(studio.settingsTemplateKeyIsWritable(" ")).toBe(true);
    expect(studio.settingsTemplateKeyIsWritable("a".repeat(160))).toBe(true);
    expect(studio.settingsTemplateKeyIsWritable("a".repeat(161))).toBe(false);
    expect(studio.settingsTemplateKeyIsWritable("汉".repeat(17))).toBe(true);
    expect(studio.settingsTemplateKeyIsWritable("汉".repeat(18))).toBe(false);
    expect(studio.settingsTemplateKeyIsWritable("path/with space")).toBe(true);
    expect(studio.settingsTemplateKeyIsWritable("\uD800")).toBe(false);
  });

  it("lets Escape close a live search and returns focus to its trigger", () => {
    expect(source).toContain("onClick: () => openSearch(false)");
    expect(source).toContain("keyboard: true");
    expect(source).toContain("closable: true");
    expect(source).toContain("maskClosable: false");
    expect(source).toContain("onCancel: () => closeSearch()");
    expect(source).toContain("window.setTimeout(() => searchTriggerRef.current?.focus?.(), 0)");
    expect(source).not.toContain("disabled: searching");
  });

  it("drops a successful response that arrives after close", async () => {
    const harness = searchHarness();
    const pending = deferred<readonly string[]>();
    harness.controller.openDialog();
    const running = harness.controller.run(() => pending.promise);
    harness.controller.closeDialog();
    pending.resolve(["late"]);
    await running;

    expect(harness.open.mock.calls).toEqual([[true], [false]]);
    expect(harness.busy.mock.calls).toEqual([[true], [false]]);
    expect(harness.results).not.toHaveBeenCalled();
    expect(harness.error).not.toHaveBeenCalled();
  });

  it("drops a failed response that arrives after close", async () => {
    const harness = searchHarness();
    const pending = deferred<readonly string[]>();
    harness.controller.openDialog();
    const running = harness.controller.run(() => pending.promise);
    harness.controller.closeDialog();
    pending.reject(new Error("late failure"));
    await running;

    expect(harness.error).not.toHaveBeenCalled();
    expect(harness.busy.mock.calls).toEqual([[true], [false]]);
  });

  it("makes an empty query supersede a pending successful search", async () => {
    const harness = searchHarness();
    const pending = deferred<readonly string[]>();
    harness.controller.openDialog();
    const running = harness.controller.run(() => pending.promise);
    harness.controller.clearResults();

    expect(harness.results.mock.calls).toEqual([[[]]]);
    expect(harness.busy.mock.calls).toEqual([[true], [false]]);
    pending.resolve(["late"]);
    await running;

    expect(harness.results.mock.calls).toEqual([[[]]]);
    expect(harness.busy.mock.calls).toEqual([[true], [false]]);
    expect(harness.error).not.toHaveBeenCalled();
    expect(source).toContain("setSearchQuery(value);");
    expect(source).toMatch(/setSearchQuery\(value\);[\s\S]*?searchController\.clearResults\(\);/);
    expect(source).not.toContain("if (!value.trim()) searchController.clearResults();");
    expect(source.match(/changeSearchQuery\(event\.target\.value\)/g)).toHaveLength(2);
  });

  it("makes a different non-empty query supersede pending results before rerun", async () => {
    const harness = searchHarness();
    const pending = deferred<readonly string[]>();
    harness.controller.openDialog();
    const running = harness.controller.run(() => pending.promise);

    // The component now calls clearResults for every text edit, including a
    // non-empty replacement such as “潮声” -> “雾港”.
    harness.controller.clearResults();
    pending.resolve(["result-for-previous-query"]);
    await running;

    expect(harness.results.mock.calls).toEqual([[[]]]);
    expect(harness.busy.mock.calls).toEqual([[true], [false]]);
    expect(harness.error).not.toHaveBeenCalled();
  });

  it("makes an empty query suppress a pending failed search", async () => {
    const harness = searchHarness();
    const pending = deferred<readonly string[]>();
    harness.controller.openDialog();
    const running = harness.controller.run(() => pending.promise);
    harness.controller.clearResults();
    pending.reject(new Error("superseded failure"));
    await running;

    expect(harness.results.mock.calls).toEqual([[[]]]);
    expect(harness.busy.mock.calls).toEqual([[true], [false]]);
    expect(harness.error).not.toHaveBeenCalled();
  });

  it("does not let an old finally clear the busy state of a reopened search", async () => {
    const harness = searchHarness();
    const oldPending = deferred<readonly string[]>();
    const nextPending = deferred<readonly string[]>();
    harness.controller.openDialog();
    const oldRun = harness.controller.run(() => oldPending.promise);
    harness.controller.closeDialog();
    harness.controller.openDialog();
    const nextRun = harness.controller.run(() => nextPending.promise);

    oldPending.resolve(["old"]);
    await oldRun;
    expect(harness.busy.mock.calls).toEqual([[true], [false], [true]]);
    expect(harness.results).not.toHaveBeenCalled();

    nextPending.resolve(["next"]);
    await nextRun;
    expect(harness.results).toHaveBeenCalledTimes(1);
    expect(harness.results).toHaveBeenLastCalledWith(["next"]);
    expect(harness.busy.mock.calls).toEqual([[true], [false], [true], [false]]);
  });

  it("invalidates without callbacks and remains reusable after a StrictMode-style cleanup", async () => {
    const harness = searchHarness();
    const oldPending = deferred<readonly string[]>();
    harness.controller.openDialog();
    const oldRun = harness.controller.run(() => oldPending.promise);
    const callsBeforeInvalidate = {
      open: harness.open.mock.calls.length,
      busy: harness.busy.mock.calls.length,
      results: harness.results.mock.calls.length,
      error: harness.error.mock.calls.length,
    };
    harness.controller.invalidate();
    oldPending.resolve(["unmounted"]);
    await oldRun;

    expect(harness.open.mock.calls).toHaveLength(callsBeforeInvalidate.open);
    expect(harness.busy.mock.calls).toHaveLength(callsBeforeInvalidate.busy);
    expect(harness.results.mock.calls).toHaveLength(callsBeforeInvalidate.results);
    expect(harness.error.mock.calls).toHaveLength(callsBeforeInvalidate.error);

    const nextPending = deferred<readonly string[]>();
    harness.controller.openDialog();
    const nextRun = harness.controller.run(() => nextPending.promise);
    nextPending.resolve(["remounted"]);
    await nextRun;
    expect(harness.results).toHaveBeenLastCalledWith(["remounted"]);
    expect(source).toContain("return () => searchController.invalidate();");
    expect(source).toContain("}, [novel.id, searchController]);");
  });

  it("names outline and clue icon actions in Chinese with their objects", () => {
    expect(source).toContain('title: `复制${item.label.replace("&", "")}`');
    expect(source).toContain('"aria-label": `编辑${item.label.replace("&", "")}`');
    expect(source).toContain('title: `编辑${storylineLabels[activeClueTab]}“${item.title}”`');
    expect(source).toContain('"aria-label": `删除${storylineLabels[activeClueTab]}“${item.title}”`');
  });
});
