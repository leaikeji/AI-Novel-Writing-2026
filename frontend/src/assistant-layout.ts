import {
  ASSISTANT_PANE_COLLAPSED_WIDTH,
  ASSISTANT_PANE_DEFAULT_WIDTH,
  ASSISTANT_PANE_MAX_WIDTH,
  ASSISTANT_PANE_MIN_WIDTH,
} from "./assistant-pane";


export type AssistantWorkspacePageKind = "chapter-editor" | "studio";
export type AssistantWorkspaceDensity = "comfortable" | "compact" | "constrained";


export const ASSISTANT_CHAPTER_MAIN_MIN_WIDTH = 760;
export const ASSISTANT_STUDIO_MAIN_MIN_WIDTH = 720;
export const ASSISTANT_CONSTRAINED_MAIN_MIN_WIDTH = 640;


export interface AssistantWorkspaceLayoutInput {
  containerWidth: number;
  preferredAssistantWidth?: number;
  assistantCollapsed?: boolean;
  pageKind?: AssistantWorkspacePageKind;
}


export interface AssistantWorkspaceLayout {
  containerWidth: number;
  assistantWidth: number;
  mainWidth: number;
  mainMinWidth: number;
  density: AssistantWorkspaceDensity;
  assistantOverlay: boolean;
  recommendedNavigationWidth: number;
}


function finiteWidth(value: number | undefined, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, Math.round(value))
    : fallback;
}


function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
}


/**
 * A1 的共享三栏计算只消费 wrapper 的真实可用宽度，不猜宿主侧栏尺寸。
 * CSS 页面布局与 AssistantPane 都使用同一个结果，避免窗口宽度、宿主侧栏和
 * 工作台内部宽度各算一遍后漂移。
 */
export function resolveAssistantWorkspaceLayout(
  input: AssistantWorkspaceLayoutInput,
): AssistantWorkspaceLayout {
  const containerWidth = finiteWidth(input.containerWidth, 0);
  const pageKind = input.pageKind ?? "studio";
  const preferredWidth = clamp(
    finiteWidth(input.preferredAssistantWidth, ASSISTANT_PANE_DEFAULT_WIDTH),
    ASSISTANT_PANE_MIN_WIDTH,
    ASSISTANT_PANE_MAX_WIDTH,
  );
  const desiredMainMin = pageKind === "chapter-editor"
    ? ASSISTANT_CHAPTER_MAIN_MIN_WIDTH
    : ASSISTANT_STUDIO_MAIN_MIN_WIDTH;

  if (input.assistantCollapsed === true) {
    const mainWidth = Math.max(0, containerWidth - ASSISTANT_PANE_COLLAPSED_WIDTH);
    return {
      containerWidth,
      assistantWidth: ASSISTANT_PANE_COLLAPSED_WIDTH,
      mainWidth,
      mainMinWidth: desiredMainMin,
      density: mainWidth >= 1_180 ? "comfortable" : "compact",
      assistantOverlay: false,
      recommendedNavigationWidth: mainWidth >= 1_100 ? 286 : 240,
    };
  }

  const inlineMax = containerWidth - desiredMainMin;
  if (inlineMax >= ASSISTANT_PANE_MIN_WIDTH) {
    const assistantWidth = clamp(
      preferredWidth,
      ASSISTANT_PANE_MIN_WIDTH,
      Math.min(ASSISTANT_PANE_MAX_WIDTH, inlineMax),
    );
    const mainWidth = Math.max(0, containerWidth - assistantWidth);
    const density: AssistantWorkspaceDensity = mainWidth >= 1_260
      ? "comfortable"
      : mainWidth >= 940
        ? "compact"
        : "constrained";
    return {
      containerWidth,
      assistantWidth,
      mainWidth,
      mainMinWidth: desiredMainMin,
      density,
      assistantOverlay: false,
      recommendedNavigationWidth: density === "comfortable" ? 286 : 240,
    };
  }

  return {
    containerWidth,
    assistantWidth: Math.min(preferredWidth, Math.max(0, containerWidth)),
    mainWidth: containerWidth,
    mainMinWidth: ASSISTANT_CONSTRAINED_MAIN_MIN_WIDTH,
    density: "constrained",
    assistantOverlay: true,
    recommendedNavigationWidth: 220,
  };
}
