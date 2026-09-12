import type { QwenPawReactRuntime } from "../assistant-pane";
import type {
  CapabilityKey,
  FeatureCapability,
  NarrationOverviewResponse,
  RuntimeLifecycleStatus,
} from "./contracts";
import type { ReadingSectionKey } from "./reading-overview";
import { DEFAULT_TTS_PROVIDER_ID, TTS_PROVIDER_PRESENTATIONS } from "./tts-provider";


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
  readonly synthesisLabel: string;
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
  ready: "本地语音服务就绪",
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
    && overview.runtime.provider_reachable
    && overview.runtime.model_ready
    && overview.runtime.model_fingerprint_sha256 !== null;
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
      message: "暂时无法清理缓存；音色和已有朗读版本不受影响。",
      section: "audio-cache",
    });
  }
  return {
    novelId: overview.novel_id,
    runtimeLabel: overview.runtime.lifecycle_status === "ready" && !runtimeReady
      ? "本地语音服务尚未就绪"
      : RUNTIME_LABELS[overview.runtime.lifecycle_status],
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
    synthesisLabel: TTS_PROVIDER_PRESENTATIONS[
      overview.settings.values.tts_provider?.provider_id ?? DEFAULT_TTS_PROVIDER_ID
    ].label,
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
      ["语音生成", model.synthesisLabel, "已保存的生成位置；在基础朗读中修改"],
      ["本地服务", model.runtimeLabel, "仅表示本地服务状态，不代表云端已通过测试"],
      ["说话人识别", model.privacyLabel, "仅指识别方式，不改变语音生成位置"],
      ["复核方式", model.reviewLabel, "在朗读规则中修改"],
      ["人物配音", model.characterCoverageLabel, "已配置 / 全部人物"],
      ["制作状态", model.productionLabel, "生成数量不代表所有句段均已通过"],
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
          h("p", { className: "anw-reading-status__eyebrow" }, "服务与制作概况"),
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
      h(
        "details",
        { className: "anw-reading-status__diagnostics" },
        h("summary", null, props.overview.coverage.failed_job_count > 0
          ? `历史与诊断（${props.overview.coverage.failed_job_count}）`
          : "技术诊断"),
        h("p", null, model.modelFingerprintShort ? `本地模型指纹：${model.modelFingerprintShort}…` : "无可用模型指纹"),
        props.overview.coverage.failed_job_count > 0 ? h(
          "p",
          null,
          `${props.overview.coverage.failed_job_count} 个历史朗读任务记录为失败，不代表当前朗读版本无法播放。具体失败句段请到章节播放器查看；正文和已有音频不会因此改变。`,
        ) : null,
      ),
    );
  };
}
