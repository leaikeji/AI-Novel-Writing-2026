export const CHARACTER_PROFILE_COMPLETION_STATES = [
  "never",
  "running",
  "ready",
  "stale",
  "failed",
  "conflict",
  "applied",
] as const;


export type CharacterProfileCompletionState =
  typeof CHARACTER_PROFILE_COMPLETION_STATES[number];
export type CharacterProfileCompletionBasis = "designed" | "mixed" | "observed";
export type CharacterProfileCompletionCandidateStatus =
  | "candidate"
  | "insufficient_evidence";
export type CharacterProfileCompletionSourceType =
  | "character"
  | "outline"
  | "chapter"
  | "story_fact";


export interface CharacterProfileCompletionEvidence {
  readonly source_type: CharacterProfileCompletionSourceType;
  readonly source_id: string;
  readonly quote: string;
}


export interface CharacterProfileCompletionCandidate {
  readonly character_id: string;
  readonly character_name: string;
  readonly base_version: number;
  readonly current_personality: string | null;
  readonly status: CharacterProfileCompletionCandidateStatus;
  readonly personality?: string | null;
  readonly basis?: CharacterProfileCompletionBasis | null;
  readonly confidence?: number | null;
  readonly evidence: readonly CharacterProfileCompletionEvidence[];
  readonly warnings: readonly string[];
}


export interface CharacterProfileCompletionSourceSummary {
  readonly characters: number;
  readonly characters_without_personality: number;
  readonly chapters: number;
  readonly story_facts: number;
}


export interface CharacterProfileCompletionJobSummary {
  readonly id: string;
  readonly requested_model?: string | null;
  readonly actual_model?: string | null;
}


export interface CharacterProfileCompletionStatusRecord {
  readonly eligible: boolean;
  readonly state: CharacterProfileCompletionState;
  readonly stale: boolean;
  readonly source_summary: CharacterProfileCompletionSourceSummary;
  readonly job: CharacterProfileCompletionJobSummary | null;
  readonly candidates: readonly CharacterProfileCompletionCandidate[];
  readonly last_error?: string | null;
  readonly last_applied_at?: string | null;
  readonly can_restore?: boolean;
}


export type CharacterProfileCompletionLocalPhase =
  | "idle"
  | "checking"
  | "preparing"
  | "applying"
  | "restoring";


export type CharacterProfileCompletionPresentationAction =
  | "reload-status"
  | "generate"
  | "reanalyze"
  | "apply"
  | "restore";


export interface CharacterProfileCompletionPresentation {
  readonly title: string;
  readonly description: string;
  readonly actionLabel: string;
  readonly action: CharacterProfileCompletionPresentationAction;
  readonly actionDisabled: boolean;
  readonly forceNew: boolean;
}


function sourceSummary(status: CharacterProfileCompletionStatusRecord): string {
  const source = status.source_summary;
  return `当前可分析 ${source.characters} 个角色、${source.chapters} 章正式正文、${source.story_facts} 条已确认角色事实`;
}


function modelSuffix(status: CharacterProfileCompletionStatusRecord): string {
  const model = status.job?.actual_model || status.job?.requested_model;
  return model ? ` 任务模型：${model}。` : "";
}


export function characterProfileCompletionPresentation(
  status: CharacterProfileCompletionStatusRecord | null,
  options: {
    readonly phase: CharacterProfileCompletionLocalPhase;
    readonly error: string;
    readonly confirming: boolean;
    readonly selectedCount?: number;
  },
): CharacterProfileCompletionPresentation {
  const isBusy = options.phase !== "idle";

  if (options.error) {
    return {
      title: "角色卡补全状态读取失败",
      description: `${options.error}；现有角色资料均已保留。`,
      actionLabel: "重新读取状态",
      action: "reload-status",
      actionDisabled: isBusy || options.confirming,
      forceNew: false,
    };
  }

  if (options.phase === "checking" || options.phase === "preparing") {
    return {
      title: options.phase === "checking" ? "正在读取角色卡状态" : "正在准备角色卡分析",
      description: "正在统计角色设定、正式大纲、已确认角色事实和正式正文证据。",
      actionLabel: "请稍候",
      action: "generate",
      actionDisabled: true,
      forceNew: false,
    };
  }

  if (options.phase === "applying") {
    return {
      title: "正在应用已选择的性格",
      description: "系统正在校验角色版本并整批写入；未选择的角色不会改变。",
      actionLabel: "应用中",
      action: "apply",
      actionDisabled: true,
      forceNew: false,
    };
  }

  if (options.phase === "restoring") {
    return {
      title: "正在恢复角色性格",
      description: "恢复会创建新的角色版本，不会改写历史记录。",
      actionLabel: "恢复中",
      action: "restore",
      actionDisabled: true,
      forceNew: false,
    };
  }

  if (!status) {
    return {
      title: "角色卡补全状态尚未就绪",
      description: "请重新读取状态；现有角色资料不会受到影响。",
      actionLabel: "重新读取状态",
      action: "reload-status",
      actionDisabled: options.confirming,
      forceNew: false,
    };
  }

  if (status.state === "running") {
    return {
      title: "角色性格正在分析",
      description: `模型正在生成证据化候选；完成前不会写入角色卡。${modelSuffix(status)}`,
      actionLabel: "分析中",
      action: "generate",
      actionDisabled: true,
      forceNew: false,
    };
  }

  if (!status.eligible) {
    return {
      title: "当前资料不足以生成候选",
      description: "请先建立至少一个正式角色及可核验的设定或正文证据。",
      actionLabel: "暂不可分析",
      action: "generate",
      actionDisabled: true,
      forceNew: false,
    };
  }

  const summary = sourceSummary(status);
  if (status.state === "failed") {
    const failure = status.last_error ? `失败原因：${status.last_error}。` : "";
    return {
      title: "上次角色性格分析失败",
      description: `${failure}${summary}；可以安全重试，正式角色资料未改变。${modelSuffix(status)}`,
      actionLabel: "重新分析",
      action: "reanalyze",
      actionDisabled: options.confirming,
      forceNew: false,
    };
  }

  if (status.state === "conflict") {
    return {
      title: "角色资料已发生变化",
      description: "候选基于旧版本，未写入任何角色；请刷新状态后重新分析。",
      actionLabel: "重新读取状态",
      action: "reload-status",
      actionDisabled: options.confirming,
      forceNew: false,
    };
  }

  if (status.state === "stale" || status.stale) {
    return {
      title: "角色或正文已有新资料",
      description: `${summary}；旧候选仅供查看，重新分析后才可应用。${modelSuffix(status)}`,
      actionLabel: "重新分析",
      action: "reanalyze",
      actionDisabled: options.confirming,
      forceNew: false,
    };
  }

  if (status.state === "ready") {
    return {
      title: `角色性格候选已就绪 · ${status.candidates.length} 个角色`,
      description: "当前默认未选择任何候选；请逐个核对证据，已有性格不会自动替换。",
      actionLabel: options.selectedCount
        ? `应用所选候选（${options.selectedCount}）`
        : "请先选择候选",
      action: "apply",
      actionDisabled: options.confirming || !options.selectedCount,
      forceNew: false,
    };
  }

  if (status.state === "applied") {
    const restoreCopy = status.can_restore
      ? "可以通过恢复操作创建新版本。"
      : "本次结果已保存为正式角色资料。";
    return {
      title: "已应用所选角色性格",
      description: `未选择的角色和其他扩展字段均未改变；${restoreCopy}`,
      actionLabel: status.can_restore ? "恢复应用前版本" : "查看结果",
      action: status.can_restore ? "restore" : "reanalyze",
      actionDisabled: options.confirming,
      forceNew: false,
    };
  }

  return {
    title: `角色卡性格尚未分析 · ${status.source_summary.characters_without_personality} 个角色待补全`,
    description: `${summary}；点击后只生成候选，不会自动写入角色卡。`,
    actionLabel: "分析角色性格",
    action: "generate",
    actionDisabled: options.confirming,
    forceNew: false,
  };
}


export interface CharacterProfileCompletionSelectionState {
  readonly jobId: string | null;
  readonly candidates: readonly CharacterProfileCompletionCandidate[];
  readonly selectedCharacterIds: Readonly<Record<string, true>>;
  readonly replacementConfirmedCharacterIds: Readonly<Record<string, true>>;
}


export type CharacterProfileCompletionSelectionAction =
  | {
    readonly type: "load-candidates";
    readonly jobId: string;
    readonly candidates: readonly CharacterProfileCompletionCandidate[];
  }
  | { readonly type: "confirm-replacement"; readonly characterId: string }
  | { readonly type: "cancel-replacement"; readonly characterId: string }
  | { readonly type: "set-selected"; readonly characterId: string; readonly selected: boolean }
  | { readonly type: "clear-selections" };


export function createCharacterProfileCompletionSelectionState(): CharacterProfileCompletionSelectionState {
  return {
    jobId: null,
    candidates: [],
    selectedCharacterIds: {},
    replacementConfirmedCharacterIds: {},
  };
}


function hasCurrentPersonality(candidate: CharacterProfileCompletionCandidate): boolean {
  return Boolean(candidate.current_personality?.trim());
}


function isSelectableCandidate(candidate: CharacterProfileCompletionCandidate): boolean {
  return candidate.status === "candidate" && Boolean(candidate.personality?.trim());
}


function recordWithoutKey(
  source: Readonly<Record<string, true>>,
  key: string,
): Readonly<Record<string, true>> {
  const next = { ...source };
  delete next[key];
  return next;
}


export function reduceCharacterProfileCompletionSelection(
  state: CharacterProfileCompletionSelectionState,
  action: CharacterProfileCompletionSelectionAction,
): CharacterProfileCompletionSelectionState {
  if (action.type === "load-candidates") {
    return {
      jobId: action.jobId,
      candidates: [...action.candidates],
      selectedCharacterIds: {},
      replacementConfirmedCharacterIds: {},
    };
  }

  if (action.type === "clear-selections") {
    return {
      ...state,
      selectedCharacterIds: {},
      replacementConfirmedCharacterIds: {},
    };
  }

  const candidate = state.candidates.find((item) => item.character_id === action.characterId);
  if (!candidate || !isSelectableCandidate(candidate)) return state;

  if (action.type === "confirm-replacement") {
    if (!hasCurrentPersonality(candidate)) return state;
    return {
      ...state,
      replacementConfirmedCharacterIds: {
        ...state.replacementConfirmedCharacterIds,
        [action.characterId]: true,
      },
    };
  }

  if (action.type === "cancel-replacement") {
    return {
      ...state,
      selectedCharacterIds: recordWithoutKey(state.selectedCharacterIds, action.characterId),
      replacementConfirmedCharacterIds: recordWithoutKey(
        state.replacementConfirmedCharacterIds,
        action.characterId,
      ),
    };
  }

  if (!action.selected) {
    return {
      ...state,
      selectedCharacterIds: recordWithoutKey(state.selectedCharacterIds, action.characterId),
    };
  }

  if (hasCurrentPersonality(candidate)
    && !state.replacementConfirmedCharacterIds[action.characterId]) return state;

  return {
    ...state,
    selectedCharacterIds: {
      ...state.selectedCharacterIds,
      [action.characterId]: true,
    },
  };
}


const BASIS_LABELS: Readonly<Record<CharacterProfileCompletionBasis, string>> = {
  designed: "设定依据",
  mixed: "设定与正文混合依据",
  observed: "多章正文观察依据",
};


const SOURCE_TYPE_LABELS: Readonly<Record<CharacterProfileCompletionSourceType, string>> = {
  character: "角色资料",
  outline: "正式大纲",
  chapter: "正式正文",
  story_fact: "已确认角色事实",
};


export interface CharacterProfileCompletionEvidenceView {
  readonly sourceTypeLabel: string;
  readonly sourceIdLabel: string;
  readonly quote: string;
}


export type CharacterProfileCompletionSelectionDisabledReason =
  | "insufficient-evidence"
  | "invalid-candidate"
  | "replacement-confirmation-required"
  | null;


export interface CharacterProfileCompletionCandidateView {
  readonly characterId: string;
  readonly characterName: string;
  readonly currentPersonality: string;
  readonly suggestedPersonality: string;
  readonly statusLabel: string;
  readonly basisLabel: string;
  readonly confidenceLabel: string;
  readonly warnings: readonly string[];
  readonly evidence: readonly CharacterProfileCompletionEvidenceView[];
  readonly selected: boolean;
  readonly selectionDisabled: boolean;
  readonly selectionDisabledReason: CharacterProfileCompletionSelectionDisabledReason;
  readonly requiresReplacementConfirmation: boolean;
  readonly replacementConfirmed: boolean;
}


export function characterProfileCompletionCandidateViews(
  state: CharacterProfileCompletionSelectionState,
): readonly CharacterProfileCompletionCandidateView[] {
  return state.candidates.map((candidate) => {
    const hasCurrent = hasCurrentPersonality(candidate);
    const replacementConfirmed = Boolean(
      state.replacementConfirmedCharacterIds[candidate.character_id],
    );
    let selectionDisabledReason: CharacterProfileCompletionSelectionDisabledReason = null;
    if (candidate.status === "insufficient_evidence") {
      selectionDisabledReason = "insufficient-evidence";
    } else if (!candidate.personality?.trim()) {
      selectionDisabledReason = "invalid-candidate";
    } else if (hasCurrent && !replacementConfirmed) {
      selectionDisabledReason = "replacement-confirmation-required";
    }
    const warnings = [...candidate.warnings];
    if (candidate.status === "insufficient_evidence") {
      warnings.unshift("证据不足：不会生成或应用推测性格");
    }
    if (hasCurrent) warnings.unshift("已有作者确认的性格，默认保留当前值");

    return {
      characterId: candidate.character_id,
      characterName: candidate.character_name,
      currentPersonality: candidate.current_personality?.trim() || "尚未填写",
      suggestedPersonality: candidate.personality?.trim() || "无可应用候选",
      statusLabel: candidate.status === "candidate" ? "候选可审阅" : "证据不足",
      basisLabel: candidate.basis ? BASIS_LABELS[candidate.basis] : "未形成依据判断",
      confidenceLabel: typeof candidate.confidence === "number"
        ? `置信度 ${candidate.confidence}/100`
        : "未提供置信度",
      warnings,
      evidence: candidate.evidence.map((item) => ({
        sourceTypeLabel: SOURCE_TYPE_LABELS[item.source_type],
        sourceIdLabel: item.source_id,
        quote: item.quote,
      })),
      selected: Boolean(state.selectedCharacterIds[candidate.character_id]),
      selectionDisabled: selectionDisabledReason !== null,
      selectionDisabledReason,
      requiresReplacementConfirmation: hasCurrent,
      replacementConfirmed,
    };
  });
}


export interface CharacterProfileCompletionApplyDecision {
  readonly character_id: string;
  readonly base_version: number;
  readonly replace_existing: boolean;
}


export interface CharacterProfileCompletionSelectionSummary {
  readonly selectedCount: number;
  readonly candidateCount: number;
  readonly insufficientEvidenceCount: number;
  readonly applyDisabled: boolean;
  readonly decisions: readonly CharacterProfileCompletionApplyDecision[];
}


export function characterProfileCompletionSelectionSummary(
  state: CharacterProfileCompletionSelectionState,
): CharacterProfileCompletionSelectionSummary {
  const decisions = state.candidates.flatMap((candidate) => {
    if (!state.selectedCharacterIds[candidate.character_id]
      || !isSelectableCandidate(candidate)) return [];
    if (hasCurrentPersonality(candidate)
      && !state.replacementConfirmedCharacterIds[candidate.character_id]) return [];
    return [{
      character_id: candidate.character_id,
      base_version: candidate.base_version,
      replace_existing: hasCurrentPersonality(candidate),
    }];
  });
  return {
    selectedCount: decisions.length,
    candidateCount: state.candidates.filter(isSelectableCandidate).length,
    insufficientEvidenceCount: state.candidates.filter(
      (candidate) => candidate.status === "insufficient_evidence",
    ).length,
    applyDisabled: decisions.length === 0,
    decisions,
  };
}
