import type { Options } from "vis-network";


export const RELATIONSHIP_GRAPH_SETTLE_MS = 650;


export function relationshipGraphOptions(
  randomSeed: string,
  stabilizationEnabled: boolean,
): Options {
  return {
    autoResize: true,
    layout: { randomSeed, improvedLayout: true },
    interaction: {
      dragNodes: true,
      dragView: true,
      hideEdgesOnDrag: false,
      hideNodesOnDrag: false,
      hover: true,
      hoverConnectedEdges: true,
      keyboard: { enabled: true, bindToWindow: false, autoFocus: true },
      multiselect: false,
      navigationButtons: false,
      selectable: true,
      selectConnectedEdges: true,
      tooltipDelay: 350,
      zoomSpeed: 0.75,
      zoomView: true,
    },
    physics: {
      enabled: true,
      solver: "forceAtlas2Based",
      forceAtlas2Based: {
        gravitationalConstant: -60,
        centralGravity: 0.008,
        springLength: 200,
        springConstant: 0.07,
        damping: 0.5,
        avoidOverlap: 0.75,
      },
      maxVelocity: 50,
      minVelocity: 0.25,
      timestep: 0.35,
      stabilization: {
        enabled: stabilizationEnabled,
        iterations: 50,
        updateInterval: 25,
        fit: true,
      },
    },
    nodes: {
      chosen: true,
    },
    edges: {
      chosen: true,
      arrowStrikethrough: false,
    },
  };
}
