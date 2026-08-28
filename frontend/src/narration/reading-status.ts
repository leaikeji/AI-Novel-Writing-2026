import type { QwenPawReactRuntime } from "../assistant-pane";
import type {
  CapabilityKey,
  FeatureCapability,
  NarrationOverviewResponse,
  RuntimeLifecycleStatus,
} from "./contracts";
import type { ReadingSectionKey } from "./reading-overview";


export type ReadingStatusReactRuntime = Pick<QwenPawReactRuntime, "createElement">;


export interface ReadingStatusIssue {
  readonly code: string;
  readonly severity: "info" | "warning" | "blocker";
  readonly message: string;
  readonly section: ReadingSectionKey | null;
}


export interface ReadingStatusModel {
  readonly novelId: string;
  readonly runtimeLabel: string;
  readonly runtimeReady: boolean;
  readonly modelFingerprintShort: string | null;
  readonly privacyLabel: string;
  readonly reviewLabel: string;
  readonly diskLabel: string;
  readonly diskPercentFree: number;
  readonly cacheLabel: string;
  readonly characterCoverageLabel: string;
  readonly productionLabel: string;
  readonly issues: readonly ReadingStatusIssue[];
}


export interface ReadingStatusProps {
  readonly overview: NarrationOverviewResponse;
  readonly onOpenSection?: (section: ReadingSectionKey) => void;
}


const RUNTIME_LABELS: Readonly<Record<RuntimeLifecycleStatus, string>> = {
  disabled: "本地 TTS 未启用",
  starting: "本地 TTS 正在启动",
  ready: "本地 TTS 技术就绪",
  unavailable: "本地 TTS 不可用",
  stopping: "本地 TTS 正在停止",
};


function capability(
  overview: NarrationOverviewResponse,
  key: CapabilityKey,
): FeatureCapability | null {
  return overview.capabilities.items.find((item) => item.key === key) ?? null;
}


function capabilityActionable(item: FeatureCapability | null): boolean {
  return item?.state === "enabled" && item.visible && item.actionable;
}


export function formatNarrationBytes(bytes: number): string {
  if (!Number.isSafeInteger(bytes) || bytes < 0) return "不可用";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"] as const;
  let value = bytes / 1024;
  let unit: (typeof units)[number] = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${unit}`;
}


function safeReason(value: string | null, fallback: string): string {
  return value && /^[A-Z][A-Z0-9_]{0,95}$/.test(value) ? value : fallback;
}


export function buildReadingStatusModel(
  overview: NarrationOverviewResponse,
): ReadingStatusModel {
  if (
    overview.settings.novel_id !== overview.novel_id
    || overview.cache.novel_id !== overview.novel_id
  ) {
    throw new Error("narration overview child scope mismatch");
  }
  const runtimeReady = overview.runtime.lifecycle_status === "ready"
    && overview.runtime.technical_enabled
    && overview.runtime.sidecar_reachable
    && overview.runtime.model_ready
    && overview.runtime.model_fingerprint_sha256 !== null;
  const diskTotal = overview.cache.disk_total_bytes;
  const diskFree = overview.cache.disk_free_bytes;
  const diskPercentFree = Number.isSafeInteger(diskTotal)
    && diskTotal > 0
    && Number.isSafeInteger(diskFree)
    && diskFree >= 0
    && diskFree <= diskTotal
    ? Math.max(0, Math.min(100, Math.round((diskFree / diskTotal) * 100)))
    : 0;
  const issues: ReadingStatusIssue[] = [];
  const product = capability(overview, "narration_product");
  const reading = capability(overview, "reading_settings");
  const cleanup = capability(overview, "cache_cleanup");
  if (!capabilityActionable(product)) {
    issues.push({
      code: safeReason(product?.reason_code ?? null, "NARRATION_PRODUCT_DISABLED"),
      severity: "blocker",
      message: "朗读产品入口仍处于门禁状态。",
      section: null,
    });
  } else if (!capabilityActionable(reading)) {
    issues.push({
      code: safeReason(reading?.reason_code ?? null, "READING_SETTINGS_DISABLED"),
      severity: "blocker",
      message: "朗读设置当前只读。",
      section: "narrator",
    });
  }
  if (!runtimeReady) {
    issues.push({
      code: safeReason(overview.runtime.reason_code, "TTS_RUNTIME_NOT_READY"),
      severity: "warning",
      message: "本地模型当前不能承担合成；设置与历史数据仍可安全查看。",
      section: "audio-cache",
    });
  }
  if (
    overview.settings.values.analysis_mode === "cloud_assisted"
    && overview.authorization.cloud_consent.state !== "active"
  ) {
    issues.push({
      code: "CLOUD_CONSENT_REQUIRED",
      severity: "blocker",
      message: "设置仍引用云端辅助，但作品级授权当前无效；不会外发正文。",
      section: "casting-rules",
    });
  }
  if (!capabilityActionable(cleanup)) {
    issues.push({
      code: safeReason(
        overview.cache.cleanup_capability.reason_code,
        cleanup?.reason_code ?? "CACHE_CLEANUP_DISABLED",
      ),
      severity: "info",
      message: "缓存清理当前不可操作；受保护音色和历史 Edition 不受影响。",
      section: "audio-cache",
    });
  }
  if (overview.coverage.failed_job_count > 0) {
    issues.push({
      code: "NARRATION_JOBS_FAILED",
      severity: "warning",
      message: `${overview.coverage.failed_job_count} 个朗读任务失败，未改写正式正文。`,
      section: "audio-cache",
    });
  }
  return {
    novelId: overview.novel_id,
    runtimeLabel: RUNTIME_LABELS[overview.runtime.lifecycle_status],
    runtimeReady,
    modelFingerprintShort: overview.runtime.model_fingerprint_sha256?.slice(0, 12) ?? null,
    privacyLabel: overview.settings.values.analysis_mode === "local_rules_only"
      ? "仅本地规则"
      : overview.authorization.cloud_consent.state === "active"
        ? "云端最小上下文（已授权）"
        : "云端模式已阻断",
    reviewLabel: overview.settings.values.script_review_policy === "always_review"
      ? "每次作者复核"
      : "仅阻断项复核",
    diskLabel: `${formatNarrationBytes(diskFree)} 可用 / ${formatNarrationBytes(diskTotal)}`,
    diskPercentFree,
    cacheLabel: `${formatNarrationBytes(overview.cache.reclaimable_bytes)} 可回收`,
    characterCoverageLabel: `${overview.coverage.locked_character_voice_count}/${overview.coverage.character_count}`,
    productionLabel: `${overview.coverage.generated_chapter_count} 章已生成 · ${overview.coverage.pending_review_script_count} 份待复核`,
    issues: Object.freeze(issues),
  };
}


export function createReadingStatus(
  React: ReadingStatusReactRuntime,
): (props: ReadingStatusProps) => unknown {
  const h = React.createElement;
  return function ReadingStatus(props: ReadingStatusProps): unknown {
    let model: ReadingStatusModel;
    try {
      model = buildReadingStatusModel(props.overview);
    } catch {
      return h(
        "section",
        { className: "anw-reading-status", "aria-labelledby": "anw-reading-status-title" },
        h("h2", { id: "anw-reading-status-title" }, "朗读运行状态"),
        h("p", { role: "alert" }, "朗读状态与当前作品不一致，已拒绝显示。"),
      );
    }
    const cards = [
      ["本地模型", model.runtimeLabel, model.modelFingerprintShort ? `指纹 ${model.modelFingerprintShort}…` : "无可用模型指纹"],
      ["隐私模式", model.privacyLabel, model.reviewLabel],
      ["磁盘", model.diskLabel, `可用 ${model.diskPercentFree}%`],
      ["派生缓存", model.cacheLabel, `待处理任务 ${props.overview.cache.pending_job_count}`],
      ["人物专属音色", model.characterCoverageLabel, "已锁定 / 全部人物"],
      ["制作状态", model.productionLabel, `失败任务 ${props.overview.coverage.failed_job_count}`],
    ] as const;
    return h(
      "section",
      {
        className: "anw-reading-status",
        "aria-labelledby": "anw-reading-status-title",
        "data-runtime-ready": String(model.runtimeReady),
      },
      h("header", null,
        h("div", null,
          h("p", { className: "anw-reading-status__eyebrow" }, "状态只反映真实后端证据"),
          h("h2", { id: "anw-reading-status-title" }, "朗读运行状态"),
        ),
      ),
      h("dl", { className: "anw-reading-status__grid" },
        ...cards.map(([label, value, detail]) => h(
          "div",
          { key: label },
          h("dt", null, label),
          h("dd", null, value),
          h("p", null, detail),
        )),
      ),
      model.issues.length === 0
        ? h("p", { className: "anw-reading-status__ok", role: "status" }, "当前设置层未发现阻断项。")
        : h(
          "section",
          { className: "anw-reading-status__issues", "aria-labelledby": "anw-reading-status-issues-title" },
          h("h3", { id: "anw-reading-status-issues-title" }, "需要处理"),
          h("ul", null,
            ...model.issues.map((issue) => h(
              "li",
              { key: `${issue.code}:${issue.section ?? "none"}`, "data-severity": issue.severity },
              h("div", null,
                h("strong", null, issue.message),
                h("code", null, issue.code),
              ),
              issue.section === null || props.onOpenSection === undefined
                ? null
                : h("button", {
                  type: "button",
                  onClick: () => props.onOpenSection?.(issue.section as ReadingSectionKey),
                }, "前往设置"),
            )),
          ),
        ),
    );
  };
}
