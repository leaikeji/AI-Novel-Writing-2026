import { describe, expect, it } from "vitest";

import {
  APP_ID,
  APP_PATH,
  CHAT_PATH,
  CORE_CHAT_ROUTE_ID,
  CREATIVE_CENTER_CHAT_PATH,
  HEALTH_PATH,
  WORKBENCH_CHAT_PATH,
} from "./contracts";

describe("PawApp public paths", () => {
  it("keeps all routes in the app namespace", () => {
    expect(APP_PATH).toBe(`/apps/${APP_ID}`);
    expect(HEALTH_PATH).toBe(`/${APP_ID}/health`);
    expect(CHAT_PATH).toBe("/chat");
    expect(CREATIVE_CENTER_CHAT_PATH).toBe("/chat?novel_center=1");
    expect(WORKBENCH_CHAT_PATH).toBe("/chat?novel_workbench=1");
    expect(CORE_CHAT_ROUTE_ID).toBe("core.chat");
  });
});
