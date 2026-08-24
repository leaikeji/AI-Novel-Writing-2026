import type { DataSet } from "vis-data";
import type { Edge, Network, Node } from "vis-network";

import {
  CharacterRelationshipRecord,
  NovelCharacterRecord,
  RelationshipGraphPositionRecord,
  RelationshipGraphViewRecord,
} from "./types";
import {
  compactRelationshipGraphLabel,
  relationshipCurveSpec,
  relationshipLaneMap,
} from "./relationship-domain";
import {
  RELATIONSHIP_GRAPH_SETTLE_MS,
  relationshipGraphOptions,
} from "./relationship-graph-policy";


const React = window.QwenPaw.host.React;
const h = React.createElement;


export interface RelationshipGraphSnapshot {
  zoom: number;
  pan_x: number;
  pan_y: number;
  positions: RelationshipGraphPositionRecord[];
}


export interface RelationshipGraphController {
  fit: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  focusNode: (characterId: string) => void;
  autoLayout: () => void;
  snapshot: () => RelationshipGraphSnapshot;
}


export interface RelationshipGraphProps {
  characters: NovelCharacterRecord[];
  relationships: CharacterRelationshipRecord[];
  view: RelationshipGraphViewRecord;
  controllerRef: { current: RelationshipGraphController | null };
  focusCharacterId?: string;
  onCharacterClick: (character: NovelCharacterRecord) => void;
  onRelationshipClick: (relationship: CharacterRelationshipRecord) => void;
  onViewStateChange: (scale: number, dirty: boolean) => void;
}


function graphNode(
  character: NovelCharacterRecord,
  savedPosition?: RelationshipGraphPositionRecord,
): Node {
  const main = character.role_type === "main";
  const pinned = Boolean(savedPosition?.pinned);
  const background = main ? "#ff7548" : "#587ce8";
  return {
    id: character.id,
    label: character.name,
    title: [character.name, String(character.details?.identity || "")].filter(Boolean).join(" · "),
    shape: "circle",
    size: main ? 42 : 34,
    widthConstraint: { minimum: main ? 72 : 62, maximum: main ? 82 : 74 },
    borderWidth: pinned ? 3 : 0,
    color: {
      background,
      border: pinned ? "#ffffff" : background,
      highlight: {
        background: main ? "#ff6a38" : "#466fe1",
        border: "#ffffff",
      },
      hover: {
        background: main ? "#ff7d53" : "#6687eb",
        border: "#ffffff",
      },
    },
    font: {
      color: "#ffffff",
      face: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      size: main ? 17 : 15,
      bold: { color: "#ffffff", size: main ? 17 : 15 },
    },
    shadow: {
      enabled: true,
      color: main ? "rgba(255,117,72,.22)" : "rgba(88,124,232,.2)",
      size: 14,
      x: 0,
      y: 4,
    },
    x: savedPosition?.x,
    y: savedPosition?.y,
    fixed: pinned ? { x: true, y: true } : false,
    physics: !pinned,
  };
}


function graphNodePinState(character: NovelCharacterRecord, pinned: boolean): Node {
  const main = character.role_type === "main";
  const background = main ? "#ff7548" : "#587ce8";
  return {
    id: character.id,
    fixed: pinned ? { x: true, y: true } : false,
    physics: !pinned,
    borderWidth: pinned ? 3 : 0,
    color: {
      background,
      border: pinned ? "#ffffff" : background,
      highlight: {
        background: main ? "#ff6a38" : "#466fe1",
        border: "#ffffff",
      },
      hover: {
        background: main ? "#ff7d53" : "#6687eb",
        border: "#ffffff",
      },
    },
  };
}


function graphEdge(relationship: CharacterRelationshipRecord, lane: number): Edge {
  const curve = relationshipCurveSpec(relationship, lane);
  const unresolved = relationship.directionality === "legacy_unspecified";
  return {
    id: relationship.id,
    from: relationship.source_character_id,
    to: relationship.target_character_id,
    label: compactRelationshipGraphLabel(relationship.label, relationship.relation_type),
    arrows: relationship.directionality === "directed"
      ? { to: { enabled: true, scaleFactor: 0.72, type: "arrow" } }
      : undefined,
    dashes: unresolved ? [5, 5] : false,
    color: {
      color: unresolved ? "#d59a74" : "#9ea4ae",
      highlight: "#ff7548",
      hover: "#ff8a61",
      opacity: 0.96,
    },
    width: 2,
    hoverWidth: 3,
    selectionWidth: 3,
    smooth: {
      enabled: true,
      type: curve.type,
      roundness: curve.roundness,
    },
    font: {
      color: unresolved ? "#b36e43" : "#707680",
      size: 12,
      face: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      background: "rgba(255,255,255,.94)",
      strokeWidth: 0,
      align: "top",
    },
    title: unresolved
      ? `${relationship.label} · 方向待确认`
      : relationship.description || relationship.label,
  };
}


export function RelationshipGraph({
  characters,
  relationships,
  view,
  controllerRef,
  focusCharacterId,
  onCharacterClick,
  onRelationshipClick,
  onViewStateChange,
}: RelationshipGraphProps) {
  const containerRef = React.useRef(null as HTMLDivElement | null);
  const networkRef = React.useRef(null as Network | null);
  const callbackRef = React.useRef({
    onCharacterClick,
    onRelationshipClick,
    onViewStateChange,
  });
  callbackRef.current = { onCharacterClick, onRelationshipClick, onViewStateChange };

  React.useEffect(() => {
    let cancelled = false;
    let nodes: DataSet<Node, "id"> | null = null;
    let edges: DataSet<Edge, "id"> | null = null;
    let clickTimer: number | null = null;
    let settleTimer: number | null = null;
    const container = containerRef.current;
    if (!container || characters.length === 0) return undefined;

    void Promise.all([import("vis-network"), import("vis-data")]).then(
      ([networkModule, dataModule]) => {
        if (cancelled || !containerRef.current) return;
        const savedPositions = new Map(
          view.positions.map((position) => [position.character_id, position]),
        );
        const pinnedNodeIds = new Set(
          view.positions.filter((position) => position.pinned).map((position) => position.character_id),
        );
        const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
        const lanes = relationshipLaneMap(relationships);
        nodes = new dataModule.DataSet(
          characters.map((character) => graphNode(character, savedPositions.get(character.id))),
        );
        edges = new dataModule.DataSet(
          relationships.map((relationship) => graphEdge(relationship, lanes.get(relationship.id) ?? 0)),
        );
        const needsPhysics = characters.some((character) => !savedPositions.has(character.id));
        const network = new networkModule.Network(
          containerRef.current,
          { nodes, edges },
          relationshipGraphOptions(view.random_seed, needsPhysics),
        );
        networkRef.current = network;

        const emitViewState = (dirty: boolean) => {
          callbackRef.current.onViewStateChange(network.getScale(), dirty);
        };
        const fitGraph = () => {
          network.fit({
            minZoomLevel: 0.18,
            maxZoomLevel: 1.12,
            animation: false,
          });
        };
        const clearClickTimer = () => {
          if (clickTimer === null) return;
          window.clearTimeout(clickTimer);
          clickTimer = null;
        };
        const clearSettleTimer = () => {
          if (settleTimer === null) return;
          window.clearTimeout(settleTimer);
          settleTimer = null;
        };
        const scheduleIdleStop = () => {
          clearSettleTimer();
          if (reducedMotion) {
            network.stopSimulation();
            return;
          }
          settleTimer = window.setTimeout(() => {
            network.stopSimulation();
            settleTimer = null;
          }, RELATIONSHIP_GRAPH_SETTLE_MS);
        };
        const restoreViewport = () => {
          if (view.version > 0) {
            network.moveTo({
              position: { x: view.pan_x, y: view.pan_y },
              scale: view.zoom,
              animation: false,
            });
          } else {
            fitGraph();
          }
        };
        const finishInitialLayout = () => {
          restoreViewport();
          if (reducedMotion) {
            network.stopSimulation();
            network.setOptions({ physics: { enabled: false } });
          } else {
            scheduleIdleStop();
          }
          emitViewState(false);
        };

        network.on("click", (params: any) => {
          clearClickTimer();
          clickTimer = window.setTimeout(() => {
            clickTimer = null;
            const nodeId = params.nodes?.[0];
            if (nodeId) {
              const character = characters.find((item) => item.id === String(nodeId));
              if (character) callbackRef.current.onCharacterClick(character);
              return;
            }
            const edgeId = params.edges?.[0];
            if (edgeId) {
              const relationship = relationships.find((item) => item.id === String(edgeId));
              if (relationship) callbackRef.current.onRelationshipClick(relationship);
            }
          }, 220);
        });
        network.on("doubleClick", (params: any) => {
          clearClickTimer();
          const nodeId = String(params.nodes?.[0] || "");
          if (!nodeId) return;
          const character = characters.find((item) => item.id === nodeId);
          if (!character) return;
          const pinned = !pinnedNodeIds.has(nodeId);
          if (pinned) pinnedNodeIds.add(nodeId);
          else pinnedNodeIds.delete(nodeId);
          nodes?.update(graphNodePinState(character, pinned));
          network.selectNodes([nodeId], true);
          if (pinned || reducedMotion) {
            network.stopSimulation();
          } else {
            network.startSimulation();
            scheduleIdleStop();
          }
          emitViewState(true);
        });
        network.on("dragStart", (params: any) => {
          clearSettleTimer();
          const nodeId = String(params.nodes?.[0] || "");
          if (!nodeId || pinnedNodeIds.has(nodeId)) return;
          network.selectNodes([nodeId], true);
          if (!reducedMotion) network.startSimulation();
        });
        network.on("dragEnd", (params: any) => {
          emitViewState(true);
          if (params.nodes?.length) scheduleIdleStop();
        });
        network.on("zoom", () => emitViewState(true));
        network.on("stabilized", clearSettleTimer);
        network.once("stabilizationIterationsDone", finishInitialLayout);
        if (!needsPhysics) {
          network.stopSimulation();
          finishInitialLayout();
        }

        const zoomTo = (scale: number) => {
          const targetScale = Math.max(0.18, Math.min(3.2, scale));
          network.moveTo({
            position: network.getViewPosition(),
            scale: targetScale,
            animation: false,
          });
          callbackRef.current.onViewStateChange(targetScale, true);
        };
        controllerRef.current = {
          fit: () => {
            fitGraph();
            emitViewState(true);
          },
          zoomIn: () => zoomTo(network.getScale() * 1.18),
          zoomOut: () => zoomTo(network.getScale() / 1.18),
          focusNode: (characterId: string) => {
            if (!nodes?.get(characterId)) return;
            network.focus(characterId, {
              scale: Math.max(1, network.getScale()),
              animation: { duration: 260, easingFunction: "easeInOutQuad" },
              locked: false,
            });
            network.selectNodes([characterId], true);
          },
          autoLayout: () => {
            clearSettleTimer();
            pinnedNodeIds.clear();
            const resetNodes = characters.map((character) => graphNode(character));
            nodes?.clear();
            nodes?.add(resetNodes);
            network.setOptions(relationshipGraphOptions(view.random_seed, true));
            network.once("stabilizationIterationsDone", () => {
              fitGraph();
              emitViewState(true);
              if (reducedMotion) {
                network.stopSimulation();
                network.setOptions({ physics: { enabled: false } });
              } else {
                scheduleIdleStop();
              }
            });
            network.stabilize(50);
          },
          snapshot: () => {
            const positions = network.getPositions(characters.map((character) => character.id));
            const pan = network.getViewPosition();
            return {
              zoom: network.getScale(),
              pan_x: pan.x,
              pan_y: pan.y,
              positions: characters.map((character) => ({
                character_id: character.id,
                x: positions[character.id]?.x ?? 0,
                y: positions[character.id]?.y ?? 0,
                pinned: pinnedNodeIds.has(character.id),
              })),
            };
          },
        };
      },
    );

    return () => {
      cancelled = true;
      if (clickTimer !== null) window.clearTimeout(clickTimer);
      if (settleTimer !== null) window.clearTimeout(settleTimer);
      controllerRef.current = null;
      networkRef.current?.destroy();
      networkRef.current = null;
      nodes = null;
      edges = null;
    };
  }, [characters, relationships, view.id, view.version, view.random_seed, view.positions]);

  React.useEffect(() => {
    if (focusCharacterId) controllerRef.current?.focusNode(focusCharacterId);
  }, [focusCharacterId]);

  return h("div", {
    ref: containerRef,
    className: "mb-relation-network",
    role: "application",
    tabIndex: 0,
    "aria-label": "角色关系图。可拖动角色，滚轮缩放，拖动画布空白区域平移。",
    "aria-description": "拖动角色时相邻人物会联动；双击角色可固定或取消固定位置。",
  });
}
