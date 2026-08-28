import {
  apiErrorMessage,
  apiRequest,
  generationModelLabel,
  getGenerationModelStatus,
} from "./api";
import {
  characterProfileCompletionCandidateViews,
  characterProfileCompletionPresentation,
  characterProfileCompletionSelectionSummary,
  createCharacterProfileCompletionSelectionState,
  reduceCharacterProfileCompletionSelection,
  type CharacterProfileCompletionCandidate,
  type CharacterProfileCompletionLocalPhase,
  type CharacterProfileCompletionStatusRecord,
} from "./character-profile-completion";


const host = window.QwenPaw.host;
const React = host.React;
const h = React.createElement;
const { Alert, Button, Checkbox, Modal, Progress, Spin, Tag } = host.antd;
const { ReloadOutlined, RobotOutlined } = host.antdIcons;


interface CharacterProfileCompletionPanelProps {
  novelId: string;
  onApplied: () => Promise<unknown>;
}


interface CharacterProfileCompletionApiStatus extends CharacterProfileCompletionStatusRecord {
  readonly last_apply_batch_id?: string | null;
}


function readError(reason: unknown): string {
  return apiErrorMessage(reason, "角色卡补全失败");
}


export function CharacterProfileCompletionPanel({
  novelId,
  onApplied,
}: CharacterProfileCompletionPanelProps) {
  const [status, setStatus] = React.useState(
    null as CharacterProfileCompletionApiStatus | null,
  );
  const [phase, setPhase] = React.useState("checking" as CharacterProfileCompletionLocalPhase);
  const [error, setError] = React.useState("");
  const [confirming, setConfirming] = React.useState(false);
  const [reviewOpen, setReviewOpen] = React.useState(false);
  const [selection, dispatchSelection] = React.useReducer(
    reduceCharacterProfileCompletionSelection,
    undefined,
    createCharacterProfileCompletionSelectionState,
  );

  const loadStatus = React.useCallback(async (silent = false) => {
    if (!silent) setPhase("checking");
    setError("");
    try {
      const next = await apiRequest<CharacterProfileCompletionApiStatus>(
        `/novels/${novelId}/character-profile-completion/status`,
      );
      setStatus(next);
      if (next.job?.id && next.candidates.length) {
        dispatchSelection({
          type: "load-candidates",
          jobId: next.job.id,
          candidates: next.candidates,
        });
      }
    } catch (reason) {
      setError(readError(reason));
    } finally {
      if (!silent) setPhase("idle");
    }
  }, [novelId]);

  React.useEffect(() => {
    setStatus(null);
    dispatchSelection({ type: "clear-selections" });
    void loadStatus();
  }, [loadStatus, novelId]);

  React.useEffect(() => {
    if (status?.state !== "running") return undefined;
    const timer = window.setInterval(() => void loadStatus(true), 3000);
    return () => window.clearInterval(timer);
  }, [loadStatus, status?.state]);

  const summary = characterProfileCompletionSelectionSummary(selection);
  const candidateViews = characterProfileCompletionCandidateViews(selection);
  const presentation = characterProfileCompletionPresentation(status, {
    phase,
    error,
    confirming,
    selectedCount: summary.selectedCount,
  });

  const generate = async (forceNew: boolean) => {
    if (phase !== "idle" || confirming) return;
    setConfirming(true);
    try {
      const model = await getGenerationModelStatus();
      const label = generationModelLabel(model);
      Modal.confirm({
        className: "anw-modal",
        title: forceNew ? "确认重新分析角色性格" : "确认分析角色性格",
        content: `将使用当前 AI 小说作家模型 ${label} 分析正式角色资料、大纲和已采用正文，只生成候选，不会自动写入角色卡。`,
        okText: forceNew ? "重新分析" : "开始分析",
        cancelText: "取消",
        onCancel: () => setConfirming(false),
        onOk: async () => {
          setConfirming(false);
          setPhase("preparing");
          setError("");
          try {
            const next = await apiRequest<CharacterProfileCompletionApiStatus>(
              `/novels/${novelId}/character-profile-completion/generate`,
              { method: "POST", body: JSON.stringify({ force_new: forceNew }) },
            );
            setStatus(next);
            if (next.job?.id && next.candidates.length) {
              dispatchSelection({
                type: "load-candidates",
                jobId: next.job.id,
                candidates: next.candidates,
              });
              setReviewOpen(true);
            }
          } catch (reason) {
            setError(readError(reason));
            await loadStatus(true);
          } finally {
            setPhase("idle");
          }
        },
      });
    } catch (reason) {
      setConfirming(false);
      setError(readError(reason));
    }
  };

  const toggleCandidate = (candidate: CharacterProfileCompletionCandidate, checked: boolean) => {
    if (!checked) {
      dispatchSelection({
        type: "set-selected",
        characterId: candidate.character_id,
        selected: false,
      });
      return;
    }
    if (candidate.current_personality?.trim()) {
      Modal.confirm({
        className: "anw-modal",
        title: `确认替换“${candidate.character_name}”的已有性格？`,
        content: "已有性格默认受保护。确认后仍需点击“应用所选候选”才会写入，并可通过应用批次恢复。",
        okText: "允许替换",
        cancelText: "保留当前值",
        onOk: () => {
          dispatchSelection({ type: "confirm-replacement", characterId: candidate.character_id });
          dispatchSelection({
            type: "set-selected",
            characterId: candidate.character_id,
            selected: true,
          });
        },
      });
      return;
    }
    dispatchSelection({
      type: "set-selected",
      characterId: candidate.character_id,
      selected: true,
    });
  };

  const applySelected = async () => {
    if (!selection.jobId || summary.applyDisabled) return;
    setPhase("applying");
    setError("");
    try {
      const next = await apiRequest<CharacterProfileCompletionApiStatus>(
        `/novels/${novelId}/character-profile-completion/jobs/${selection.jobId}/apply`,
        {
          method: "POST",
          body: JSON.stringify({
            idempotency_key: `character-profile-${crypto.randomUUID()}`,
            decisions: summary.decisions,
          }),
        },
      );
      setStatus(next);
      setReviewOpen(false);
      dispatchSelection({ type: "clear-selections" });
      await onApplied();
    } catch (reason) {
      setError(readError(reason));
      await loadStatus(true);
    } finally {
      setPhase("idle");
    }
  };

  const restore = async () => {
    if (!status?.last_apply_batch_id) return;
    setPhase("restoring");
    setError("");
    try {
      const next = await apiRequest<CharacterProfileCompletionApiStatus>(
        `/novels/${novelId}/character-profile-completion/apply-batches/${status.last_apply_batch_id}/restore`,
        {
          method: "POST",
          body: JSON.stringify({
            idempotency_key: `character-profile-restore-${crypto.randomUUID()}`,
          }),
        },
      );
      setStatus(next);
      await onApplied();
    } catch (reason) {
      setError(readError(reason));
      await loadStatus(true);
    } finally {
      setPhase("idle");
    }
  };

  const runAction = () => {
    if (presentation.action === "reload-status") void loadStatus();
    else if (presentation.action === "generate") void generate(false);
    else if (presentation.action === "reanalyze") void generate(true);
    else if (presentation.action === "apply") setReviewOpen(true);
    else void restore();
  };

  return h(
    React.Fragment,
    null,
    h(
      "section",
      { className: `mb-relation-ai-status${phase !== "idle" ? " is-syncing" : ""}${error ? " is-error" : ""}`, role: "status", "aria-live": "polite" },
      h("span", { className: "mb-relation-ai-icon" }, phase !== "idle" ? h(Spin, { size: "small" }) : h(RobotOutlined)),
      h("span", { className: "mb-relation-ai-copy" },
        h("strong", null, presentation.title),
        h("small", null, presentation.description),
      ),
      status?.state === "ready"
        ? h(Button, { type: "text", size: "small", onClick: () => setReviewOpen(true) }, "审阅候选")
        : null,
      h(Button, {
        type: "text",
        size: "small",
        icon: h(ReloadOutlined),
        disabled: presentation.actionDisabled,
        onClick: runAction,
      }, presentation.actionLabel),
    ),
    h(
      Modal,
      {
        open: reviewOpen,
        className: "anw-modal",
        wrapClassName: "anw-assistant-aware-modal-wrap",
        width: 900,
        title: "审阅角色性格候选",
        onCancel: () => setReviewOpen(false),
        footer: h("div", null,
          h(Button, { onClick: () => setReviewOpen(false) }, "稍后处理"),
          h(Button, {
            type: "primary",
            disabled: summary.applyDisabled || phase === "applying",
            loading: phase === "applying",
            onClick: () => void applySelected(),
          }, `应用所选候选（${summary.selectedCount}）`),
        ),
      },
      h(Alert, {
        type: "info",
        showIcon: true,
        message: "候选默认不选中；应用只修改性格字段，其他角色资料保持不变。",
        className: "mb-review-alert",
      }),
      ...candidateViews.map((view, index) => {
        const candidate = selection.candidates[index];
        return h(
          "article",
          { key: view.characterId, className: "mb-role-card", style: { display: "block", marginTop: 12, padding: 16 } },
          h("div", { style: { display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between" } },
            h("strong", null, view.characterName),
            h("div", null,
              h(Tag, null, view.basisLabel),
              h(Tag, null, view.statusLabel),
              h(Checkbox, {
                checked: view.selected,
                disabled: view.selectionDisabled && !view.requiresReplacementConfirmation,
                onChange: (event: { target: { checked: boolean } }) => toggleCandidate(candidate, event.target.checked),
              }, "采用"),
            ),
          ),
          h("p", null, h("strong", null, "当前："), view.currentPersonality),
          h("p", null, h("strong", null, "建议："), view.suggestedPersonality),
          typeof candidate.confidence === "number"
            ? h(Progress, { percent: candidate.confidence, size: "small", format: () => view.confidenceLabel })
            : null,
          ...view.warnings.map((warning) => h(Alert, { key: warning, type: "warning", showIcon: true, message: warning, style: { marginTop: 8 } })),
          view.evidence.length
            ? h("ul", null, ...view.evidence.map((evidence, evidenceIndex) => h(
                "li",
                { key: `${view.characterId}-${evidenceIndex}` },
                `${evidence.sourceTypeLabel} · ${evidence.sourceIdLabel}：${evidence.quote}`,
              )))
            : h("p", null, "没有可核验证据。"),
        );
      }),
    ),
  );
}
