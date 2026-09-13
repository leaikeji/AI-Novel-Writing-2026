import type { LibraryCheckHitRecord, LibraryCheckReportRecord } from "../types";
import type { FocusHandle, KeyboardEventLike, PrivateLibraryAntdRuntime, PrivateLibraryReactRuntime } from "./ui-runtime";

export interface LibraryCheckDecisionPanelProps {
  readonly report: LibraryCheckReportRecord;
  readonly loadPage: (offset: number) => Promise<LibraryCheckReportRecord>;
  readonly saveDecisions: (
    report: LibraryCheckReportRecord, keepHitIds: string[], skipIncomplete: boolean,
  ) => Promise<LibraryCheckReportRecord>;
  readonly onComplete: (report: LibraryCheckReportRecord) => void;
  readonly onCancel: () => void;
  readonly onLocateHit?: (hit: LibraryCheckHitRecord) => void;
}

function hasSkippedIncomplete(report: LibraryCheckReportRecord): boolean {
  return report.decisions?.some((decision) => decision.kind === "skip_incomplete") === true;
}

export function canCompleteLibraryCheck(report: LibraryCheckReportRecord): boolean {
  return report.unresolved_forbid_hit_ids.length === 0
    && (report.status === "complete" || (report.status === "incomplete" && hasSkippedIncomplete(report)));
}

class ReportChangedError extends Error {
  constructor(message: string, readonly status: "stale" | "failed" = "stale") { super(message); }
}

function assertSameReport(baseline: LibraryCheckReportRecord, next: LibraryCheckReportRecord): void {
  if (next.id !== baseline.id || next.text_sha256 !== baseline.text_sha256
    || next.rules_sha256 !== baseline.rules_sha256 || next.version < baseline.version) {
    throw new ReportChangedError("正文或规则报告已变化，请关闭面板并重新检查；原候选仍保留。");
  }
  if (next.status === "stale" || next.status === "failed") {
    throw new ReportChangedError(next.status === "stale"
      ? "正文或规则已变化，请重新检查；旧保留选择不能用于新报告。"
      : "检查失败，请重新检查；正文未被修改。", next.status);
  }
}

/** Persist only explicit choices. An uncertain write is reconciled before one retry. */
export async function persistLibraryCheckChoices(input: {
  report: LibraryCheckReportRecord;
  selectedHitIds: readonly string[];
  skipIncomplete: boolean;
  loadPage: LibraryCheckDecisionPanelProps["loadPage"];
  saveDecisions: LibraryCheckDecisionPanelProps["saveDecisions"];
  onProgress?: (report: LibraryCheckReportRecord) => void;
}): Promise<LibraryCheckReportRecord> {
  let report = input.report;
  assertSameReport(report, report);
  const selected = [...new Set(input.selectedHitIds)];
  const pending = () => selected.filter((id) => report.unresolved_forbid_hit_ids.includes(id));
  const needsSkip = () => input.skipIncomplete && report.status === "incomplete" && !hasSkippedIncomplete(report);
  const receive = (next: LibraryCheckReportRecord) => {
    assertSameReport(report, next);
    report = next;
    input.onProgress?.(report);
  };
  while (pending().length > 0 || needsSkip()) {
    const batch = pending().slice(0, 200);
    const skip = needsSkip();
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const missing = batch.filter((id) => report.unresolved_forbid_hit_ids.includes(id));
      const missingSkip = skip && needsSkip();
      if (!missing.length && !missingSkip) break;
      let next: LibraryCheckReportRecord;
      try {
        next = await input.saveDecisions(report, missing, missingSkip);
      } catch {
        // Network failure or CAS conflict does not prove that the prior write failed.
        receive(await input.loadPage(report.offset));
        continue;
      }
      receive(next);
      break;
    }
    if (batch.some((id) => report.unresolved_forbid_hit_ids.includes(id)) || (skip && needsSkip())) {
      throw new Error("保留选择尚未保存，请重新读取报告后重试；候选未被采用。");
    }
  }
  return report;
}

export function createLibraryCheckDecisionPanel(
  React: PrivateLibraryReactRuntime,
  antd: PrivateLibraryAntdRuntime,
): (props: LibraryCheckDecisionPanelProps) => unknown {
  const h = React.createElement;
  const { Alert, Button, Tag } = antd;
  return function LibraryCheckDecisionPanel(props: LibraryCheckDecisionPanelProps): unknown {
    const [report, setReport] = React.useState(props.report);
    const [selectedIds, setSelectedIds] = React.useState<string[]>([]);
    const [skipIncomplete, setSkipIncomplete] = React.useState(false);
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState<string | null>(null);
    const [notice, setNotice] = React.useState<string | null>(null);
    const pendingRef = React.useRef(false);
    const mountedRef = React.useRef(true);
    const reportRef = React.useRef(report);
    const headingRef = React.useRef<FocusHandle | null>(null);
    const identity = `${props.report.id}:${props.report.text_sha256}:${props.report.rules_sha256}`;
    const identityRef = React.useRef(identity);
    identityRef.current = identity;
    React.useEffect(() => {
      mountedRef.current = true;
      headingRef.current?.focus();
      return () => { mountedRef.current = false; };
    }, []);
    React.useEffect(() => {
      setReport(props.report);
      reportRef.current = props.report;
      setSelectedIds([]);
      setSkipIncomplete(false);
      setError(null);
      setNotice(null);
    }, [identity]);

    const forbidden = new Set(report.unresolved_forbid_hit_ids);
    const pendingChoices = selectedIds.filter((id) => forbidden.has(id));
    const blocked = report.status === "stale" || report.status === "failed";
    const run = (operation: () => Promise<void>) => {
      if (pendingRef.current) return;
      pendingRef.current = true;
      setBusy(true);
      setError(null);
      setNotice(null);
      void operation().catch((reason: unknown) => {
        if (mountedRef.current && identityRef.current === identity) {
          if (reason instanceof ReportChangedError) {
            reportRef.current = { ...reportRef.current, status: reason.status };
            setReport(reportRef.current);
          }
          setError(reason instanceof Error ? reason.message : "操作失败，请重试；候选仍保留。");
        }
      }).finally(() => {
        pendingRef.current = false;
        if (mountedRef.current) setBusy(false);
      });
    };
    const receive = (next: LibraryCheckReportRecord) => {
      if (!mountedRef.current || identityRef.current !== identity) throw new Error("检查面板已切换。");
      assertSameReport(reportRef.current, next);
      reportRef.current = next;
      setReport(next);
      setSelectedIds((ids) => ids.filter((id) => next.unresolved_forbid_hit_ids.includes(id)));
    };
    const load = (offset: number) => run(async () => {
      receive(await props.loadPage(offset));
      headingRef.current?.focus();
    });
    const save = () => {
      if (blocked || (pendingChoices.length === 0 && !(skipIncomplete && !hasSkippedIncomplete(report)))) return;
      run(async () => {
        const next = await persistLibraryCheckChoices({
          report: reportRef.current,
          selectedHitIds: pendingChoices,
          skipIncomplete,
          loadPage: props.loadPage,
          saveDecisions: props.saveDecisions,
          onProgress: receive,
        });
        receive(next);
        setNotice("所选保留决定已保存，尚未采用到正文。");
      });
    };
    const cancel = () => { if (!pendingRef.current) props.onCancel(); };
    return h("section", {
      "aria-label": "用词检查逐项处置",
      "aria-busy": busy,
      onKeyDown: (event: KeyboardEventLike & { stopPropagation?(): void }) => {
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation?.();
          cancel();
        }
      },
    },
    h("h3", { tabIndex: -1, ref: (node: FocusHandle | null) => { headingRef.current = node; } }, "确认本次用词"),
    h("p", null, "逐项勾选需要本次保留的禁用表达，再保存决定；未勾选项不会被放行。慎用词仅提示。"),
    h("p", { role: "status", "aria-live": "polite" },
      `共 ${report.total_hits} 处命中 · ${forbidden.size} 处禁用表达待处理 · ${pendingChoices.length} 处已选但未保存`),
    blocked ? h(Alert, { type: "error", showIcon: true, message: report.status === "stale"
      ? "正文或规则已变化，请关闭面板并重新检查。" : "检查失败，请关闭面板并重新检查。" }) : null,
    report.status === "incomplete" ? h(Alert, {
      type: "warning", showIcon: true, message: "检查未完成",
      description: `已扫描 ${report.scanned_rule_count} 条规则，${report.omitted_rule_count} 条规则未扫描；未扫描范围不能视为通过。`,
    }) : null,
    error ? h(Alert, { type: "error", showIcon: true, message: error }) : null,
    notice ? h("p", { role: "status" }, notice) : null,
    h("ol", { start: report.offset + 1, style: { maxHeight: "40vh", overflowY: "auto", paddingInlineStart: 24 } },
      ...report.hits.map((hit, index) => h("li", { key: hit.hit_id, style: { marginBlock: 12 }, "data-hit-id": hit.hit_id },
        h("div", null,
          h(Tag, { color: hit.action === "forbid" ? "red" : "orange" }, hit.action === "forbid" ? "禁用" : "慎用"),
          h("strong", null, hit.matched_text),
          h("span", null, ` · 字符位置 ${hit.start_utf16}–${hit.end_utf16}`),
        ),
        h("p", null, hit.reason),
        hit.action === "forbid" && forbidden.has(hit.hit_id)
          ? h("label", null, h("input", {
              type: "checkbox", checked: selectedIds.includes(hit.hit_id), disabled: busy || blocked,
              "aria-label": `本次保留第 ${report.offset + index + 1} 处：${hit.matched_text}`,
              onChange: (event: { target: { checked: boolean } }) => {
                if (pendingRef.current || blocked) return;
                setSelectedIds((ids) => event.target.checked
                  ? [...new Set([...ids, hit.hit_id])] : ids.filter((id) => id !== hit.hit_id));
              },
            }), "本次保留")
          : hit.action === "forbid" ? h("span", null, "已处理（已保存保留或原有未改动）") : null,
        props.onLocateHit ? h(Button, { type: "link", disabled: busy, onClick: () => props.onLocateHit?.(hit) }, "定位原句") : null,
      )),
    ),
    report.total_hits === 0 ? h("p", null, report.status === "complete" ? "当前报告没有用词命中。" : "当前已扫描范围没有命中，不表示整项检查通过。") : null,
    h("nav", { "aria-label": "检查命中分页", style: { display: "flex", gap: 12, alignItems: "center" } },
      h(Button, { disabled: busy || report.offset === 0, onClick: () => load(Math.max(0, report.offset - report.limit)) }, "上一页"),
      h("span", null, `${report.total_hits ? report.offset + 1 : 0}–${Math.min(report.offset + report.hits.length, report.total_hits)} / ${report.total_hits}`),
      h(Button, { disabled: busy || !report.has_more, onClick: () => load(report.offset + report.limit) }, "下一页"),
      h(Button, { disabled: busy, onClick: () => load(report.offset) }, "重新读取报告"),
    ),
    report.status === "incomplete" ? h("label", { style: { display: "block", marginBlock: 16 } }, h("input", {
      type: "checkbox", checked: hasSkippedIncomplete(report) || skipIncomplete,
      disabled: busy || hasSkippedIncomplete(report), "aria-label": "明确跳过本次未完成检查",
      onChange: (event: { target: { checked: boolean } }) => { if (!pendingRef.current) setSkipIncomplete(event.target.checked); },
    }), hasSkippedIncomplete(report) ? "已保存跳过本次未完成检查的决定。" : "我了解未扫描范围，明确跳过本次未完成检查（保存后生效）。") : null,
    h("div", { style: { display: "flex", flexWrap: "wrap", gap: 12, marginTop: 16 } },
      h(Button, { disabled: busy, onClick: cancel }, "返回修改，保留候选"),
      h(Button, {
        loading: busy, disabled: busy || blocked || (pendingChoices.length === 0 && !(skipIncomplete && !hasSkippedIncomplete(report))),
        onClick: save,
      }, "保存所选决定"),
      h(Button, {
        type: "primary", disabled: busy || error !== null || !canCompleteLibraryCheck(report),
        onClick: () => {
          if (!pendingRef.current && !error && canCompleteLibraryCheck(reportRef.current)) {
            pendingRef.current = true;
            setBusy(true);
            props.onComplete(reportRef.current);
          }
        },
      }, "确认检查并继续"),
    ));
  };
}
