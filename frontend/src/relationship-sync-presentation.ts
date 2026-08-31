import { RelationshipAutoSyncStatusRecord } from "./types";


export type RelationshipSyncPhase = "idle" | "checking" | "preparing" | "syncing";
export type RelationshipSyncAction = "reload-status" | "generate";


export interface RelationshipSyncPresentation {
  title: string;
  description: string;
  actionLabel: string;
  action: RelationshipSyncAction;
  actionDisabled: boolean;
  forceNew: boolean;
}


function sourceSummary(status: RelationshipAutoSyncStatusRecord): string {
  const source = status.source_summary;
  return `当前可分析 ${source.characters} 个角色、${source.chapters} 章正文、${source.relationship_facts} 条已确认关系情报`;
}


export function relationshipSyncPresentation(
  status: RelationshipAutoSyncStatusRecord | null,
  options: {
    phase: RelationshipSyncPhase;
    error: string;
    modelLabel: string;
    confirming: boolean;
  },
): RelationshipSyncPresentation {
  const { phase, error, modelLabel, confirming } = options;
  const isBusy = phase !== "idle";
  const modelSuffix = modelLabel ? ` 任务模型：${modelLabel}。` : "";

  if (error) {
    return {
      title: "关系同步状态读取失败",
      description: `${error}；现有关系和人工修改均已保留。`,
      actionLabel: "重新读取状态",
      action: "reload-status",
      actionDisabled: isBusy || confirming,
      forceNew: false,
    };
  }

  if (phase === "checking" || phase === "preparing") {
    return {
      title: phase === "checking" ? "正在读取关系同步状态" : "正在准备关系网生成",
      description: "正在统计角色、章节正文和已确认关系情报。",
      actionLabel: "请稍候",
      action: "generate",
      actionDisabled: true,
      forceNew: false,
    };
  }

  if (phase === "syncing" || status?.state === "running") {
    return {
      title: "关系网正在生成",
      description: `模型正在分析现有角色与正文；完成前不会覆盖人工关系。${modelSuffix}`,
      actionLabel: "生成中",
      action: "generate",
      actionDisabled: true,
      forceNew: false,
    };
  }

  if (!status) {
    return {
      title: "关系同步状态尚未就绪",
      description: "请重新读取状态；现有关系不会受到影响。",
      actionLabel: "重新读取状态",
      action: "reload-status",
      actionDisabled: confirming,
      forceNew: false,
    };
  }

  if (!status.eligible) {
    return {
      title: "至少需要两个角色",
      description: "新增第二个角色后即可生成关系网；人工关系仍可继续维护。",
      actionLabel: "暂不可生成",
      action: "generate",
      actionDisabled: true,
      forceNew: false,
    };
  }

  const summary = sourceSummary(status);
  const safety = "人工修改不会被 AI 覆盖。";
  if (status.state === "failed") {
    return {
      title: `上次关系网生成失败 · 当前 ${status.ai_relationship_count} 条 AI 关系`,
      description: `${summary}；可以安全重试，${safety}${modelSuffix}`,
      actionLabel: "重新生成",
      action: "generate",
      actionDisabled: confirming,
      forceNew: false,
    };
  }

  if (!status.last_synced_at) {
    const incrementallyCreated = status.ai_relationship_count > 0;
    return {
      title: incrementallyCreated
        ? `关系网已由章节同步建立 · 当前 ${status.ai_relationship_count} 条 AI 关系`
        : "尚无全书关系快照 · 可从章节同步逐步建立",
      description: `${summary}；章节“同步进展”确认后会自动增量完善关系网。这里的整书分析仅用于快速初始化或重建，点击后才会另行调用模型，${safety}`,
      actionLabel: "生成全书关系快照",
      action: "generate",
      actionDisabled: confirming,
      forceNew: false,
    };
  }

  if (status.stale) {
    return {
      title: `全书关系快照可更新 · 当前 ${status.ai_relationship_count} 条 AI 关系`,
      description: `${summary}；章节关系已随“同步进展”增量写入，这里只重算整书快照，${safety}${modelSuffix}`,
      actionLabel: "更新全书关系快照",
      action: "generate",
      actionDisabled: confirming,
      forceNew: false,
    };
  }

  return {
    title: `全书关系快照已生成 · ${status.ai_relationship_count} 条 AI 关系`,
    description: `${summary}；整书资料已分析完成，日常关系变化继续由章节“同步进展”增量写入，${safety}${modelSuffix}`,
    actionLabel: "重新分析全书快照",
    action: "generate",
    actionDisabled: confirming,
    forceNew: true,
  };
}
