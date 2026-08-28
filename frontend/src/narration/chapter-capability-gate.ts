import type {
  CapabilityKey,
  FeatureCapability,
  NarrationCapabilities,
} from "./contracts";


const PLAYER_KEYS = Object.freeze([
  "narration_product",
  "product_player",
  "editor_production",
] as const satisfies readonly CapabilityKey[]);

const PRODUCTION_KEYS = Object.freeze([
  ...PLAYER_KEYS,
  "narration_synthesis",
  "automatic_speaker_detection",
] as const satisfies readonly CapabilityKey[]);


export interface ChapterNarrationCapabilityGate {
  readonly visible: boolean;
  readonly canLoadSession: boolean;
  readonly canProduce: boolean;
  readonly reasonCode: string | null;
  readonly blockedCapability: CapabilityKey | null;
}


/**
 * Retain the current gate when a fresh gate has the same user-visible meaning.
 * Overview polling creates new frozen objects even when the server matrix is
 * unchanged; stable identity keeps the current state/session alive until one
 * of the effective release decisions changes.
 */
export function retainEquivalentChapterNarrationCapabilityGate(
  current: ChapterNarrationCapabilityGate,
  next: ChapterNarrationCapabilityGate,
): ChapterNarrationCapabilityGate {
  const equivalent = current.visible === next.visible
    && current.canLoadSession === next.canLoadSession
    && current.canProduce === next.canProduce
    && current.reasonCode === next.reasonCode
    && current.blockedCapability === next.blockedCapability;
  return equivalent ? current : next;
}


export interface ChapterNarrationGateOverview {
  readonly novel_id: string;
  readonly capabilities: NarrationCapabilities;
}


export type ChapterNarrationGateOverviewLoader = (
  novelId: string,
  signal?: AbortSignal,
) => Promise<ChapterNarrationGateOverview>;


function isActionable(capability: FeatureCapability | undefined): boolean {
  return capability?.state === "enabled"
    && capability.visible
    && capability.actionable
    && capability.reason_code === null;
}


/**
 * A ready Sidecar is not a product release gate. The chapter editor consumes
 * the same authoritative capability matrix as the book reading settings and
 * fails closed when the complete player/production chain is not enabled.
 */
export function deriveChapterNarrationCapabilityGate(
  capabilities: NarrationCapabilities,
): ChapterNarrationCapabilityGate {
  const byKey = new Map(capabilities.items.map((item) => [item.key, item]));
  const playerBlocker = PLAYER_KEYS.find((key) => !isActionable(byKey.get(key))) ?? null;
  const productionBlocker = PRODUCTION_KEYS.find((key) => !isActionable(byKey.get(key))) ?? null;
  const blocker = productionBlocker ?? playerBlocker;
  const blocked = blocker === null ? undefined : byKey.get(blocker);
  const product = byKey.get("narration_product");
  const editor = byKey.get("editor_production");
  const player = byKey.get("product_player");
  return Object.freeze({
    visible: Boolean(product?.visible && (editor?.visible || player?.visible)),
    canLoadSession: playerBlocker === null,
    canProduce: productionBlocker === null,
    reasonCode: blocked?.reason_code ?? (blocker === null ? null : "CAPABILITY_DISABLED"),
    blockedCapability: blocker,
  });
}


/** Re-read the server-authoritative gate and fence a late cross-novel result. */
export async function loadChapterNarrationCapabilityGate(
  novelId: string,
  loader: ChapterNarrationGateOverviewLoader,
  signal?: AbortSignal,
): Promise<ChapterNarrationCapabilityGate> {
  const overview = await loader(novelId, signal);
  if (overview.novel_id !== novelId) {
    throw new Error("朗读权限返回了其他作品范围，章节朗读已关闭。");
  }
  return deriveChapterNarrationCapabilityGate(overview.capabilities);
}
