export type OutlineGenerationKind =
  | "outline_background"
  | "outline_characters"
  | "outline_plot"
  | "outline_highlight";


export type OutlineExplorationDirection =
  | "change_setting_focus"
  | "change_relationship_structure"
  | "change_conflict_structure"
  | "change_positioning_focus";


export interface OutlineGenerationTarget {
  step: 2 | 3 | 4 | 5;
  kind: OutlineGenerationKind;
  name: string;
  explorationDirection: OutlineExplorationDirection;
}


const TARGETS: Record<OutlineGenerationTarget["step"], OutlineGenerationTarget> = {
  2: { step: 2, kind: "outline_background", name: "故事背景", explorationDirection: "change_setting_focus" },
  3: { step: 3, kind: "outline_characters", name: "角色设定", explorationDirection: "change_relationship_structure" },
  4: { step: 4, kind: "outline_plot", name: "故事情节", explorationDirection: "change_conflict_structure" },
  5: { step: 5, kind: "outline_highlight", name: "故事亮点", explorationDirection: "change_positioning_focus" },
};


export function outlineGenerationTarget(step: number): OutlineGenerationTarget {
  if (step !== 2 && step !== 3 && step !== 4 && step !== 5) {
    throw new Error(`大纲生成步骤无效：${step}`);
  }
  return TARGETS[step];
}


export function nextOutlineGenerationTarget(currentStep: number): OutlineGenerationTarget {
  return outlineGenerationTarget(currentStep + 1);
}
