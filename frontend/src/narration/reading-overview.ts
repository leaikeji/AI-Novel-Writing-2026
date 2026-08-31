import type { QwenPawReactRuntime } from "../assistant-pane";
import type {
  CapabilityKey,
  FeatureCapability,
  NarrationOverviewResponse,
} from "./contracts";


export const READING_SECTION_KEYS = [
  "overview",
  "narrator",
  "characters",
  "voice-library",
  "advanced-tuning",
  "private-voices",
  "reading-rules",
  "storage-privacy",
  "casting-rules",
  "pronunciation",
  "audio-cache",
] as const;


export type ReadingSectionKey = typeof READING_SECTION_KEYS[number];


export interface ReadingSectionDefinition {
  readonly key: ReadingSectionKey;
  readonly label: string;
}


export const READING_SECTIONS: readonly ReadingSectionDefinition[] = [
  { key: "narrator", label: "基础朗读" },
  { key: "voice-library", label: "官方音色" },
  { key: "characters", label: "人物配音" },
  { key: "advanced-tuning", label: "高级调音" },
  { key: "private-voices", label: "私人音色" },
] as const;


export function canonicalReadingSection(
  section: ReadingSectionKey | null | undefined,
): ReadingSectionKey {
  if (
    section === null
    || section === undefined
    || section === "overview"
    || section === "reading-rules"
    || section === "casting-rules"
    || section === "pronunciation"
  ) return "narrator";
  if (section === "storage-privacy" || section === "audio-cache") return "private-voices";
  return section;
}


const REASON_LABELS: Readonly<Record<string, string>> = {
  T2_GATE_REQUIRED: "等待声音设置阶段门禁通过",
  T3_GATE_REQUIRED: "等待说话人分析阶段门禁通过",
  T4_GATE_REQUIRED: "等待合成与播放器阶段门禁通过",
  T5_GATE_REQUIRED: "等待高级音色阶段门禁通过",
  VOICE_SOURCE_NOT_APPROVED: "尚无通过授权与质量验收的试听音色",
  OFFICIAL_PRESET_CATALOG_NOT_RELEASED: "固定官方 ONNX 音色目录尚未完成技术发布",
  OFFICIAL_PRESET_MANIFEST_MISSING: "固定官方 ONNX manifest 缺失",
  OFFICIAL_PRESET_MANIFEST_HASH_MISMATCH: "固定官方 ONNX manifest 校验失败",
  OFFICIAL_PRESET_MODEL_FINGERPRINT_MISMATCH: "固定官方 ONNX 模型指纹不一致",
  OFFICIAL_PRESET_RUNTIME_UNAVAILABLE: "官方预设本地推理运行时尚未就绪",
  REFERENCE_CLONE_PRODUCT_GATE_HOLD: "参考录音克隆仍处于产品门禁保留状态",
  CLOUD_CONSENT_FLOW_NOT_READY: "云端最小化分析授权流程尚未就绪",
};


const RUNTIME_LABELS = {
  disabled: "未启用",
  starting: "启动中",
  ready: "技术运行态就绪",
  unavailable: "不可用",
  stopping: "停止中",
} as const;


export type ReadingOverviewReactRuntime = Pick<QwenPawReactRuntime, "createElement">;


export type ReadingOverviewViewState =
  | { readonly phase: "loading" }
  | {
    readonly phase: "error";
    readonly message: string;
    readonly onRetry?: () => void;
  }
  | {
    readonly phase: "ready";
    readonly overview: NarrationOverviewResponse;
    readonly onRetry?: () => void;
    readonly onNavigate?: (section: ReadingSectionKey) => void;
  };


export interface ReadingOverviewModel {
  readonly configurationEmpty: boolean;
  readonly mutationAllowed: boolean;
  readonly mutationBlockReason: string | null;
  readonly runtimeLabel: string;
  readonly runtimeDetail: string;
  readonly privacyLabel: string;
  readonly reviewPolicyLabel: string;
  readonly narratorLabel: string;
  readonly characterCoverageLabel: string;
  readonly reviewLabel: string;
  readonly generationLabel: string;
  readonly cacheLabel: string;
  readonly diskLabel: string;
}


export function isReadingSectionKey(value: string | null | undefined): value is ReadingSectionKey {
  return value !== null
    && value !== undefined
    && (READING_SECTION_KEYS as readonly string[]).includes(value);
}


export function capabilityFor(
  overview: NarrationOverviewResponse,
  key: CapabilityKey,
): FeatureCapability {
  const capability = overview.capabilities.items.find((item) => item.key === key);
  if (!capability) throw new Error(`缺少朗读能力状态：${key}`);
  return capability;
}


export function narrationReasonLabel(reasonCode: string | null): string {
  if (reasonCode === null) return "";
  return REASON_LABELS[reasonCode] ?? "当前能力尚不可用";
}


export function capabilityStatusText(capability: FeatureCapability): string {
  if (capability.actionable) return "可用";
  const reason = narrationReasonLabel(capability.reason_code);
  return `${reason}（${capability.reason_code ?? capability.state}）`;
}


function formatCountRatio(current: number, total: number): string {
  return total === 0 ? "暂无对象" : `${current} / ${total}`;
}


export function formatNarrationBytes(bytes: number): string {
  if (bytes < 1_024) return `${bytes} B`;
  if (bytes < 1_024 ** 2) return `${(bytes / 1_024).toFixed(1)} KiB`;
  if (bytes < 1_024 ** 3) return `${(bytes / 1_024 ** 2).toFixed(1)} MiB`;
  return `${(bytes / 1_024 ** 3).toFixed(1)} GiB`;
}


export function buildReadingOverviewModel(
  overview: NarrationOverviewResponse,
): ReadingOverviewModel {
  const productCapability = capabilityFor(overview, "narration_product");
  const settingsCapability = capabilityFor(overview, "reading_settings");
  const mutationCapability = !productCapability.actionable
    ? productCapability
    : settingsCapability;
  const mutationAllowed = mutationCapability.actionable
    && overview.authorization.can_configure;
  const mutationBlockReason = mutationAllowed
    ? null
    : !mutationCapability.actionable
      ? capabilityStatusText(mutationCapability)
      : "当前作品授权不允许修改朗读配置（AUTHORIZATION_READ_ONLY）";
  const coverage = overview.coverage;
  const cache = overview.cache;
  const consent = overview.authorization.cloud_consent;
  const runtimeReason = overview.runtime.reason_code === null
    ? ""
    : ` · ${narrationReasonLabel(overview.runtime.reason_code)}（${overview.runtime.reason_code}）`;
  const configurationEmpty = !overview.settings.exists
    && overview.settings.values.narrator === null
    && coverage.configured_character_count === 0
    && coverage.generic_ready_slot_count === 0
    && coverage.generated_chapter_count === 0;

  return {
    configurationEmpty,
    mutationAllowed,
    mutationBlockReason,
    runtimeLabel: RUNTIME_LABELS[overview.runtime.lifecycle_status],
    runtimeDetail: `协议 ${overview.runtime.protocol_version}${runtimeReason}`,
    privacyLabel: overview.settings.values.analysis_mode === "local_rules_only"
      ? "隐私优先 · 仅本地规则"
      : consent.state === "active"
        ? "智能增强 · 已取得作品级授权"
        : "智能增强 · 授权未生效",
    reviewPolicyLabel: overview.settings.values.script_review_policy === "blockers_only"
      ? "仅异常复核"
      : "每章都复核",
    narratorLabel: overview.settings.values.narrator === null
      ? "未配置"
      : "已配置锁定音色版本",
    characterCoverageLabel: formatCountRatio(
      coverage.configured_character_count,
      coverage.character_count,
    ),
    reviewLabel: `${coverage.pending_review_script_count} 待复核 · ${coverage.blocker_count} 阻塞 · ${coverage.warning_count} 提醒`,
    generationLabel: `${coverage.generated_chapter_count} 章已生成 · ${coverage.failed_job_count} 个失败任务`,
    cacheLabel: `${formatNarrationBytes(cache.derived_cache_bytes)} 派生缓存 · ${formatNarrationBytes(cache.reclaimable_bytes)} 可回收`,
    diskLabel: `${formatNarrationBytes(cache.disk_free_bytes)} 可用 / ${formatNarrationBytes(cache.disk_total_bytes)} 总空间`,
  };
}


function statusCard(
  h: ReadingOverviewReactRuntime["createElement"],
  label: string,
  value: string,
  detail?: string,
  className = "",
): unknown {
  return h(
    "article",
    { className: `anw-reading-status-card ${className}`.trim() },
    h("h3", null, label),
    h("strong", null, value),
    detail ? h("p", null, detail) : null,
  );
}


export function createReadingOverview(
  React: ReadingOverviewReactRuntime,
): (props: { readonly state: ReadingOverviewViewState }) => unknown {
  const h = React.createElement;

  return function ReadingOverview(props) {
    const state = props.state;
    if (state.phase === "loading") {
      return h(
        "section",
        {
          className: "anw-reading-overview is-loading",
          role: "status",
          "aria-live": "polite",
          "aria-busy": true,
          "data-reading-state": "loading",
        },
        h("span", { className: "anw-reading-spinner", "aria-hidden": true }),
        h("p", null, "正在加载朗读设置与能力状态…"),
      );
    }

    if (state.phase === "error") {
      return h(
        "section",
        {
          className: "anw-reading-overview is-error",
          role: "alert",
          "data-reading-state": "error",
        },
        h("h2", null, "朗读设置加载失败"),
        h("p", null, state.message),
        state.onRetry
          ? h("button", { type: "button", onClick: state.onRetry }, "重新加载")
          : null,
      );
    }

    const model = buildReadingOverviewModel(state.overview);
    const product = capabilityFor(state.overview, "narration_product");
    const settings = capabilityFor(state.overview, "reading_settings");
    const pageState = !product.actionable || !settings.actionable
      ? "gated"
      : model.configurationEmpty
        ? "empty"
        : "success";

    return h(
      "section",
      {
        className: `anw-reading-overview is-${pageState}`,
        role: "region",
        "aria-labelledby": "anw-reading-overview-heading",
        "data-reading-state": pageState,
      },
      h(
        "header",
        { className: "anw-reading-section-heading" },
        h("div", null,
          h("h2", { id: "anw-reading-overview-heading" }, "朗读总览"),
          h("p", null, "这里只展示服务端核实的能力、配置覆盖与存储状态。"),
        ),
        state.onRetry
          ? h("button", { type: "button", className: "anw-reading-link-button", onClick: state.onRetry }, "刷新状态")
          : null,
      ),
      model.mutationBlockReason
        ? h(
          "div",
          {
            className: "anw-reading-gate-notice",
            role: "status",
            "data-capability": !product.actionable ? product.key : settings.key,
            "data-reason-code": (!product.actionable ? product.reason_code : settings.reason_code) ?? undefined,
          },
          h("strong", null, "当前为只读状态"),
          h("span", null, model.mutationBlockReason),
        )
        : null,
      model.configurationEmpty
        ? h(
          "div",
          { className: "anw-reading-empty", "data-reading-empty": "true" },
          h("h3", null, "还没有朗读配置"),
          h("p", null, "可从 18 个官方音色中直接选择旁白，再为正式人物一键匹配或手动配置声音。"),
          h(
            "button",
            {
              type: "button",
              disabled: !model.mutationAllowed,
              title: model.mutationBlockReason ?? undefined,
              onClick: () => state.onNavigate?.("narrator"),
            },
            "配置旁白",
          ),
        )
        : null,
      h(
        "div",
        { className: "anw-reading-status-grid" },
        statusCard(h, "Nano Runtime", model.runtimeLabel, model.runtimeDetail),
        statusCard(h, "正文分析", model.privacyLabel, `云端授权：${state.overview.authorization.cloud_consent.state}`),
        statusCard(h, "脚本复核", model.reviewPolicyLabel, model.reviewLabel),
        statusCard(h, "当前旁白", model.narratorLabel),
        statusCard(h, "人物音色覆盖", model.characterCoverageLabel, `${state.overview.coverage.locked_character_voice_count} 个已锁定`),
        statusCard(h, "章节与任务", model.generationLabel),
        statusCard(h, "音频与缓存", model.cacheLabel, model.diskLabel),
      ),
      h(
        "div",
        { className: "anw-reading-overview-actions", role: "group", "aria-label": "朗读配置快捷入口" },
        h(
          "button",
          {
            type: "button",
            disabled: !model.mutationAllowed,
            title: model.mutationBlockReason ?? undefined,
            onClick: () => state.onNavigate?.("narrator"),
          },
          "旁白设置",
        ),
        h(
          "button",
          {
            type: "button",
            disabled: !model.mutationAllowed,
            title: model.mutationBlockReason ?? undefined,
            onClick: () => state.onNavigate?.("characters"),
          },
          "人物配音",
        ),
      ),
    );
  };
}
