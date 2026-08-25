export const SELECTION_MIRROR_PROBE_TOLERANCE_CSS_PX = 1;


export const REQUIRED_SELECTION_MIRROR_SCENARIOS = [
  "baseline",
  "scroll",
  "zoom",
  "high-dpi",
  "long-line",
  "wrapping",
  "ime",
] as const;


export type SelectionMirrorScenario =
  typeof REQUIRED_SELECTION_MIRROR_SCENARIOS[number];


export type SelectionToolbarStrategy = "selection-mirror" | "field-anchor";


export interface GeometryPoint {
  x: number;
  y: number;
}


/** All coordinates are CSS pixels in visual-viewport space. */
export interface GeometryRect {
  left: number;
  top: number;
  width: number;
  height: number;
}


export interface SelectionMirrorProbeSample {
  scenario: SelectionMirrorScenario;
  expected: GeometryPoint;
  measured?: GeometryPoint;
  /** False when repeated measurements flicker or follow a stale IME composition. */
  stable: boolean;
  toleranceCssPx?: number;
}


export interface SelectionMirrorStrategyDecision {
  strategy: SelectionToolbarStrategy;
  missingScenarios: readonly SelectionMirrorScenario[];
  unstableScenarios: readonly SelectionMirrorScenario[];
  maxObservedErrorCssPx: number;
}


export interface SelectionGeometryEnvironment {
  fieldScrollLeft: number;
  fieldScrollTop: number;
  visualViewportScale: number;
  devicePixelRatio: number;
  hasLongVisualLine: boolean;
  selectionWraps: boolean;
  isComposing: boolean;
}


export interface SelectionMirrorMeasurement {
  rect: GeometryRect;
  /** Font, padding, border, white-space and tab-size match the source field. */
  styleParityVerified: boolean;
  scrollCompensated?: boolean;
  zoomCoordinatesNormalized?: boolean;
  highDpiCoordinatesNormalized?: boolean;
  longLineMeasured?: boolean;
  wrappedSelectionMeasured?: boolean;
}


export type SelectionGeometryFallbackReason =
  | "mirror-not-adopted"
  | "mirror-measurement-missing"
  | "mirror-rect-invalid"
  | "mirror-style-parity-unverified"
  | "field-scroll-uncompensated"
  | "zoom-uncompensated"
  | "high-dpi-unverified"
  | "long-line-unverified"
  | "wrapping-unverified"
  | "ime-composition-active"
  | "selection-outside-field"
  | "selection-outside-viewport";


export type SelectionToolbarPlacementKind =
  | "selection-above"
  | "selection-below"
  | "field-below"
  | "field-above"
  | "field-top-right";


export interface SelectionToolbarPlacement {
  strategy: SelectionToolbarStrategy;
  precision: "verified-selection" | "field-level";
  x: number;
  y: number;
  placement: SelectionToolbarPlacementKind;
  fallbackReasons: readonly SelectionGeometryFallbackReason[];
}


export interface ResolveSelectionToolbarPlacementInput {
  viewportRect: GeometryRect;
  fieldRect: GeometryRect;
  toolbarSize: { width: number; height: number };
  environment: SelectionGeometryEnvironment;
  mirror?: SelectionMirrorMeasurement;
  mirrorDecision?: SelectionMirrorStrategyDecision;
  gap?: number;
  viewportPadding?: number;
}


const FLOAT_TOLERANCE = 0.001;
const SCROLL_TOLERANCE_CSS_PX = 0.5;


function isFinitePoint(point: GeometryPoint | undefined): point is GeometryPoint {
  return Boolean(
    point
    && Number.isFinite(point.x)
    && Number.isFinite(point.y),
  );
}


function pointError(expected: GeometryPoint, measured: GeometryPoint): number {
  return Math.max(
    Math.abs(expected.x - measured.x),
    Math.abs(expected.y - measured.y),
  );
}


/**
 * textarea mirror 只有覆盖全部风险场景、位置误差合格且重复测量稳定时才获准采用。
 * 缺样本不是“默认成功”，而是明确选择字段锚点。
 */
export function evaluateSelectionMirrorProbes(
  samples: readonly SelectionMirrorProbeSample[],
): SelectionMirrorStrategyDecision {
  const seen = new Set<SelectionMirrorScenario>();
  const unstable = new Set<SelectionMirrorScenario>();
  let maxObservedErrorCssPx = 0;

  for (const sample of samples) {
    seen.add(sample.scenario);
    const tolerance = sample.toleranceCssPx
      ?? SELECTION_MIRROR_PROBE_TOLERANCE_CSS_PX;
    if (!Number.isFinite(tolerance) || tolerance < 0) {
      unstable.add(sample.scenario);
      continue;
    }
    if (!isFinitePoint(sample.expected) || !isFinitePoint(sample.measured)) {
      unstable.add(sample.scenario);
      continue;
    }
    const error = pointError(sample.expected, sample.measured);
    maxObservedErrorCssPx = Math.max(maxObservedErrorCssPx, error);
    if (!sample.stable || error > tolerance) {
      unstable.add(sample.scenario);
    }
  }

  const missing = REQUIRED_SELECTION_MIRROR_SCENARIOS.filter(
    (scenario) => !seen.has(scenario),
  );
  const unstableScenarios = REQUIRED_SELECTION_MIRROR_SCENARIOS.filter(
    (scenario) => unstable.has(scenario),
  );
  return Object.freeze({
    strategy: missing.length === 0 && unstableScenarios.length === 0
      ? "selection-mirror"
      : "field-anchor",
    missingScenarios: Object.freeze(missing),
    unstableScenarios: Object.freeze(unstableScenarios),
    maxObservedErrorCssPx,
  });
}


/**
 * A0C-4 的保守决策：纯函数尖峰本身没有真实浏览器全场景证据，所以不把 mirror
 * 描述成精确定位。后续只有把真实探针结果传入并全部通过，才能显式改用 mirror。
 */
export const SELECTION_GEOMETRY_SPIKE_DECISION =
  evaluateSelectionMirrorProbes([]);


function requireRect(rect: GeometryRect, field: string): GeometryRect {
  if (
    !Number.isFinite(rect.left)
    || !Number.isFinite(rect.top)
    || !Number.isFinite(rect.width)
    || !Number.isFinite(rect.height)
    || rect.width <= 0
    || rect.height <= 0
  ) {
    throw new Error(`${field} must be a positive finite CSS-pixel rectangle`);
  }
  return rect;
}


function isUsableMirrorRect(rect: GeometryRect): boolean {
  return Number.isFinite(rect.left)
    && Number.isFinite(rect.top)
    && Number.isFinite(rect.width)
    && Number.isFinite(rect.height)
    && rect.width > 0
    && rect.height > 0;
}


function rectRight(rect: GeometryRect): number {
  return rect.left + rect.width;
}


function rectBottom(rect: GeometryRect): number {
  return rect.top + rect.height;
}


function intersects(left: GeometryRect, right: GeometryRect): boolean {
  return left.left < rectRight(right)
    && rectRight(left) > right.left
    && left.top < rectBottom(right)
    && rectBottom(left) > right.top;
}


function intersection(
  left: GeometryRect,
  right: GeometryRect,
): GeometryRect | null {
  const intersectionLeft = Math.max(left.left, right.left);
  const intersectionTop = Math.max(left.top, right.top);
  const intersectionRight = Math.min(rectRight(left), rectRight(right));
  const intersectionBottom = Math.min(rectBottom(left), rectBottom(right));
  if (
    intersectionRight <= intersectionLeft
    || intersectionBottom <= intersectionTop
  ) {
    return null;
  }
  return {
    left: intersectionLeft,
    top: intersectionTop,
    width: intersectionRight - intersectionLeft,
    height: intersectionBottom - intersectionTop,
  };
}


function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum));
}


function clampToolbarPoint(
  point: GeometryPoint,
  viewport: GeometryRect,
  toolbar: { width: number; height: number },
  padding: number,
): GeometryPoint {
  return {
    x: clamp(
      point.x,
      viewport.left + padding,
      rectRight(viewport) - padding - toolbar.width,
    ),
    y: clamp(
      point.y,
      viewport.top + padding,
      rectBottom(viewport) - padding - toolbar.height,
    ),
  };
}


function fieldPlacement(
  field: GeometryRect,
  viewport: GeometryRect,
  toolbar: { width: number; height: number },
  gap: number,
  padding: number,
): Pick<SelectionToolbarPlacement, "x" | "y" | "placement"> {
  const visibleField = intersection(field, viewport) ?? field;
  const desiredX = rectRight(visibleField) - toolbar.width;
  let desiredY: number;
  let placement: SelectionToolbarPlacementKind;

  if (
    rectBottom(visibleField) + gap + toolbar.height
    <= rectBottom(viewport) - padding
  ) {
    desiredY = rectBottom(visibleField) + gap;
    placement = "field-below";
  } else if (
    visibleField.top - gap - toolbar.height
    >= viewport.top + padding
  ) {
    desiredY = visibleField.top - gap - toolbar.height;
    placement = "field-above";
  } else {
    desiredY = visibleField.top + gap;
    placement = "field-top-right";
  }

  const point = clampToolbarPoint(
    { x: desiredX, y: desiredY },
    viewport,
    toolbar,
    padding,
  );
  return { ...point, placement };
}


function selectionPlacement(
  selection: GeometryRect,
  viewport: GeometryRect,
  toolbar: { width: number; height: number },
  gap: number,
  padding: number,
): Pick<SelectionToolbarPlacement, "x" | "y" | "placement"> {
  const desiredX = selection.left + (selection.width - toolbar.width) / 2;
  const fitsAbove = selection.top - gap - toolbar.height
    >= viewport.top + padding;
  const desiredY = fitsAbove
    ? selection.top - gap - toolbar.height
    : rectBottom(selection) + gap;
  const point = clampToolbarPoint(
    { x: desiredX, y: desiredY },
    viewport,
    toolbar,
    padding,
  );
  return {
    ...point,
    placement: fitsAbove ? "selection-above" : "selection-below",
  };
}


function mirrorFallbackReasons(
  input: ResolveSelectionToolbarPlacementInput,
  viewport: GeometryRect,
  field: GeometryRect,
): SelectionGeometryFallbackReason[] {
  const reasons: SelectionGeometryFallbackReason[] = [];
  const decision = input.mirrorDecision ?? SELECTION_GEOMETRY_SPIKE_DECISION;
  const mirror = input.mirror;
  const environment = input.environment;

  if (decision.strategy !== "selection-mirror") {
    reasons.push("mirror-not-adopted");
    return reasons;
  }
  if (!mirror) {
    reasons.push("mirror-measurement-missing");
    return reasons;
  }
  if (!isUsableMirrorRect(mirror.rect)) {
    reasons.push("mirror-rect-invalid");
    return reasons;
  }
  if (!mirror.styleParityVerified) {
    reasons.push("mirror-style-parity-unverified");
  }
  if (
    (
      Math.abs(environment.fieldScrollLeft) > SCROLL_TOLERANCE_CSS_PX
      || Math.abs(environment.fieldScrollTop) > SCROLL_TOLERANCE_CSS_PX
    )
    && mirror.scrollCompensated !== true
  ) {
    reasons.push("field-scroll-uncompensated");
  }
  if (
    Math.abs(environment.visualViewportScale - 1) > FLOAT_TOLERANCE
    && mirror.zoomCoordinatesNormalized !== true
  ) {
    reasons.push("zoom-uncompensated");
  }
  if (
    environment.devicePixelRatio > 1 + FLOAT_TOLERANCE
    && mirror.highDpiCoordinatesNormalized !== true
  ) {
    reasons.push("high-dpi-unverified");
  }
  if (
    environment.hasLongVisualLine
    && mirror.longLineMeasured !== true
  ) {
    reasons.push("long-line-unverified");
  }
  if (
    environment.selectionWraps
    && mirror.wrappedSelectionMeasured !== true
  ) {
    reasons.push("wrapping-unverified");
  }
  if (environment.isComposing) {
    reasons.push("ime-composition-active");
  }
  if (!intersects(mirror.rect, field)) {
    reasons.push("selection-outside-field");
  }
  if (!intersects(mirror.rect, viewport)) {
    reasons.push("selection-outside-viewport");
  }
  return reasons;
}


/**
 * 只计算定位，不读取或写入 DOM。调用方负责提供同一 visual viewport/CSS px 坐标系
 * 的矩形，并把返回的 x/y 应用到自己的受控 UI。
 */
export function resolveSelectionToolbarPlacement(
  input: ResolveSelectionToolbarPlacementInput,
): SelectionToolbarPlacement {
  const viewport = requireRect(input.viewportRect, "viewportRect");
  const field = requireRect(input.fieldRect, "fieldRect");
  const toolbar = {
    width: input.toolbarSize.width,
    height: input.toolbarSize.height,
  };
  if (
    !Number.isFinite(toolbar.width)
    || !Number.isFinite(toolbar.height)
    || toolbar.width <= 0
    || toolbar.height <= 0
  ) {
    throw new Error("toolbarSize must contain positive finite CSS-pixel values");
  }
  const environmentValues = [
    input.environment.fieldScrollLeft,
    input.environment.fieldScrollTop,
    input.environment.visualViewportScale,
    input.environment.devicePixelRatio,
  ];
  if (
    environmentValues.some((value) => !Number.isFinite(value))
    || input.environment.visualViewportScale <= 0
    || input.environment.devicePixelRatio <= 0
  ) {
    throw new Error("selection geometry environment must be finite and positive");
  }
  const gap = input.gap ?? 8;
  const padding = input.viewportPadding ?? 8;
  if (!Number.isFinite(gap) || gap < 0 || !Number.isFinite(padding) || padding < 0) {
    throw new Error("gap and viewportPadding must be finite non-negative values");
  }

  const fallbackReasons = mirrorFallbackReasons(input, viewport, field);
  if (fallbackReasons.length > 0 || !input.mirror) {
    return {
      strategy: "field-anchor",
      precision: "field-level",
      ...fieldPlacement(field, viewport, toolbar, gap, padding),
      fallbackReasons: Object.freeze(fallbackReasons),
    };
  }

  return {
    strategy: "selection-mirror",
    precision: "verified-selection",
    ...selectionPlacement(input.mirror.rect, viewport, toolbar, gap, padding),
    fallbackReasons: Object.freeze([]),
  };
}
