import { describe, expect, it } from "vitest";

import {
  RELATIONSHIP_GRAPH_SETTLE_MS,
  relationshipGraphOptions,
} from "./relationship-graph-policy";


describe("relationshipGraphOptions", () => {
  it("保留拖动时的节点、连线与相邻关系高亮", () => {
    const options = relationshipGraphOptions("novel-1", false);

    expect(options.interaction).toMatchObject({
      dragNodes: true,
      hideEdgesOnDrag: false,
      hideNodesOnDrag: false,
      hoverConnectedEdges: true,
      selectConnectedEdges: true,
    });
  });

  it("使用妙笔神书同类的 ForceAtlas2 物理参数并允许再次启动", () => {
    const options = relationshipGraphOptions("novel-1", true);

    expect(options.physics).toMatchObject({
      enabled: true,
      solver: "forceAtlas2Based",
      maxVelocity: 50,
      timestep: 0.35,
      stabilization: { enabled: true, iterations: 50 },
      forceAtlas2Based: {
        gravitationalConstant: -60,
        centralGravity: 0.008,
        springLength: 200,
        springConstant: 0.07,
      },
    });
    expect(RELATIONSHIP_GRAPH_SETTLE_MS).toBeGreaterThanOrEqual(450);
    expect(RELATIONSHIP_GRAPH_SETTLE_MS).toBeLessThanOrEqual(700);
  });
});
