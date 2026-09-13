import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import type { CandidateRecord, LibraryCheckHitRecord, LibraryCheckReportRecord } from "./types";
import { findAll } from "./private-library/test-harness";

const request = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...await original<typeof import("./api")>(), apiRequest: request }));
const confirm = vi.fn();
let workflow: typeof import("./chapter-workflow");
const report: LibraryCheckReportRecord = {
  schema_version: "library-check/1", id: "report-current", version: 5, status: "complete",
  text_sha256: "a".repeat(64), rules_sha256: "b".repeat(64), hits: [],
  unresolved_forbid_hit_ids: [], scanned_rule_count: 2, omitted_rule_count: 0,
  visible_character_count: 4, offset: 0, limit: 200, total_hits: 0, has_more: false,
};
const candidate = { id: "candidate", document_id: "chapter", content_hash: report.text_sha256,
  content_markdown: "潮声拍岸。" } as CandidateRecord;

beforeEach(async () => {
  request.mockReset(); confirm.mockReset();
  const component = Object.assign(() => null, { TextArea: () => null });
  const components = new Proxy({ Modal: { confirm }, Input: component }, {
    get: (target, key) => key in target ? target[key as keyof typeof target] : component,
  });
  vi.stubGlobal("window", { QwenPaw: { host: {
    React: { createElement: (type: unknown, props: unknown, ...children: unknown[]) => ({ type, props: props ?? {}, children }) },
    ReactDOM: {}, antd: components, antdIcons: components,
  } } });
  confirm.mockReturnValue({ destroy: vi.fn() });
  workflow = await import("./chapter-workflow");
});
afterEach(() => vi.unstubAllGlobals());

describe("whole chapter current-library adoption entry", () => {
  it("checks a legacy candidate against current rules and adopts by report reference only", async () => {
    request.mockResolvedValueOnce(report).mockResolvedValueOnce({ document: { id: "chapter" }, candidate });
    await workflow.adoptLibraryAwareCandidate("novel", candidate, 7);
    expect(request.mock.calls[0]?.[0]).toBe("/novels/novel/library-checks");
    expect(JSON.parse(request.mock.calls[0]?.[1].body)).toMatchObject({ source_kind: "candidate", source_id: "candidate" });
    expect(JSON.parse(request.mock.calls[1]?.[1].body)).toEqual({
      expected_draft_version: 7, library_check_report_id: report.id, library_check_version: 5,
    });
    expect(confirm).not.toHaveBeenCalled();
  });

  it.each(["library_check_required", "library_check_report_version_conflict"])("rechecks %s only once and never regenerates", async (type) => {
    const conflict = new ApiError(409, "规则或决定改变", { type });
    request.mockResolvedValueOnce(report).mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({ ...report, id: "new-report" }).mockRejectedValueOnce(conflict);
    await expect(workflow.adoptLibraryAwareCandidate("novel", candidate, 7)).rejects.toBe(conflict);
    expect(request).toHaveBeenCalledTimes(4);
    expect(request.mock.calls.every(([path]) => !String(path).includes("generation"))).toBe(true);
  });

  it("refreshes the same report after a decision CAS conflict and sends its new version", async () => {
    const conflict = new ApiError(409, "决定已更新", { type: "library_check_report_version_conflict" });
    const result = { document: { id: "chapter" }, candidate };
    request.mockResolvedValueOnce(report).mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({ ...report, version: 6 }).mockResolvedValueOnce(result);
    expect(await workflow.adoptLibraryAwareCandidate("novel", candidate, 7)).toEqual(result);
    expect(request.mock.calls.map(([path]) => path)).toEqual([
      "/novels/novel/library-checks", "/candidates/candidate/adopt",
      "/novels/novel/library-checks", "/candidates/candidate/adopt",
    ]);
    expect(JSON.parse(request.mock.calls[3]![1].body)).toEqual({
      expected_draft_version: 7, library_check_report_id: report.id, library_check_version: 6,
    });
    expect(confirm).not.toHaveBeenCalled();
  });

  it("uses the shared panel and does not adopt cancelled or unselected hits", async () => {
    const blocked = { ...report, unresolved_forbid_hit_ids: ["hit-1", "hit-2"] };
    request.mockResolvedValueOnce(blocked);
    const operation = workflow.adoptLibraryAwareCandidate("novel", candidate, 7);
    await vi.waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    const modal = confirm.mock.calls[0]?.[0];
    expect(modal.footer).toBeNull();
    const panel = findAll(modal.content, (node) => node.props.report === blocked)[0]!;
    const preview = findAll(modal.content, (node) => typeof node.props.bindLocator === "function")[0]!;
    expect(preview.props.text).toBe(candidate.content_markdown);
    const locate = vi.fn();
    (preview.props.bindLocator as (callback: typeof locate) => void)(locate);
    const hit = { start_utf16: 0, end_utf16: 2, matched_text: "潮声" } as LibraryCheckHitRecord;
    (panel.props.onLocateHit as (hit: LibraryCheckHitRecord) => void)(hit);
    expect(locate).toHaveBeenCalledExactlyOnceWith(hit);
    (panel.props.onCancel as () => void)();
    expect(await operation).toBeNull();
    expect(request).toHaveBeenCalledOnce();
  });

  it("stops a late check response after leaving the chapter", async () => {
    let current = true;
    let resolveCheck: (value: LibraryCheckReportRecord) => void = () => undefined;
    request.mockImplementationOnce(() => new Promise((resolve) => { resolveCheck = resolve; }));
    const operation = workflow.adoptLibraryAwareCandidate("novel", candidate, 7, () => current);
    current = false; resolveCheck(report);
    expect(await operation).toBeNull();
    expect(request).toHaveBeenCalledOnce();
  });

  it("does not return a late adoption result to the new chapter", async () => {
    let current = true;
    let resolveAdopt: (value: unknown) => void = () => undefined;
    request.mockResolvedValueOnce(report).mockImplementationOnce(() => new Promise(resolve => { resolveAdopt = resolve; }));
    const operation = workflow.adoptLibraryAwareCandidate("novel", candidate, 7, () => current);
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    current = false;
    resolveAdopt({ document: { id: "chapter" }, candidate });
    expect(await operation).toBeNull();
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("does not retry an old adoption conflict after leaving the chapter", async () => {
    let current = true;
    let rejectAdopt: (value: unknown) => void = () => undefined;
    request.mockResolvedValueOnce(report).mockImplementationOnce(() => new Promise((_, reject) => { rejectAdopt = reject; }));
    const operation = workflow.adoptLibraryAwareCandidate("novel", candidate, 7, () => current);
    await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    current = false;
    rejectAdopt(new ApiError(409, "决定已更新", { type: "library_check_report_version_conflict" }));
    expect(await operation).toBeNull();
    expect(request).toHaveBeenCalledTimes(2);
  });
});
